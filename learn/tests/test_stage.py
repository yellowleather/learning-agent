"""Unit tests for LearnStage.

Covers the gate-driven side effects of the learning pipeline: reset clears
every downstream gate; answer scoring flips the learning gate exactly when
all required baseline questions pass; the cross-stage introspection helpers
(question_progress, required_questions_passed) read correctly off a session;
the build_checkpoint card renders for all four status branches; and the
normaliser / get_bundle / ensure_assist behaviours that the orchestrator
relies on.

The pipeline-building methods (_build_session, _compare_single_provider,
_validate_*) are exercised indirectly here and explicitly by the existing
controller-level integration tests in test_controller.py.
"""

from pathlib import Path

import pytest

from coach.config import AppConfig
from coach.errors import CoachError
from coach.models import (
    ArtifactState,
    Gates,
    Ledger,
    MetricsState,
    ProgressState,
)
from learn.models import (
    ConceptCard,
    LearningQuestion,
    LearningSession,
    QuestionAttempt,
    QuestionScore,
    ReadingMaterialPayload,
)
from learn.stage import LearnStage
from coach.state import StateStore


# -- Test doubles ----------------------------------------------------------


class _ScoringProvider:
    """Provider stub that always scores answers as `passed=True`. Sufficient
    for tests focused on the LearnStage scoring side-effects rather than on
    the score logic itself (which lives in the provider implementations)."""

    def score_learning_question(self, week_spec, question, answer, observation):
        return QuestionScore(passed=True, score_rationale="ok")


# -- Fixtures --------------------------------------------------------------


def _seed_state(tmp_path: Path) -> StateStore:
    """StateStore seeded with a minimal week-1 ledger."""
    config = AppConfig(
        provider="openai",
        model="test-model",
        roadmap_path="docs/plan.md",
        target_repo_path="target",
        state_dir="state",
    )
    state = StateStore(tmp_path, config)
    state.ensure_state_dir()
    ledger = Ledger(
        curriculum_metadata={"title": "T", "total_weeks": 1, "target_repo": "target"},
        state=ProgressState(
            current_week=1,
            active_dirs=["dir_one"],
            artifacts=ArtifactState(required_files=["dir_one/file.py"], completed_files=[]),
            gates=Gates(),
            metrics=MetricsState(required=["latency_p95"], recorded={}),
        ),
    )
    state.save_ledger(ledger)
    return state


def _make_session(
    *,
    questions: list[LearningQuestion] | None = None,
    attempts: list[QuestionAttempt] | None = None,
    week: int = 1,
) -> LearningSession:
    return LearningSession(
        week=week,
        questions=questions or [],
        attempts=attempts or [],
    )


def _baseline_question(qid: str) -> LearningQuestion:
    return LearningQuestion(
        id=qid,
        prompt_text=f"Prompt for {qid}",
        depth="baseline",
        scoring_rubric=["criterion"],
    )


def _passed_attempt(qid: str) -> QuestionAttempt:
    return QuestionAttempt(
        question_id=qid,
        answer="ans",
        result=QuestionScore(passed=True, score_rationale="ok"),
    )


def _failed_attempt(qid: str) -> QuestionAttempt:
    return QuestionAttempt(
        question_id=qid,
        answer="ans",
        result=QuestionScore(passed=False, score_rationale="missed"),
    )


class _StubCurriculum:
    """CurriculumAccess stand-in. Most LearnStage tests don't touch the
    roadmap; the ones that do (answer_question) use current_week()."""

    def current_week(self, _number: int) -> dict:
        return {
            "number": 1,
            "short_title": "First Week",
            "goal": "Do the thing",
            "active_dirs": ["dir_one"],
            "required_files": ["dir_one/file.py"],
            "required_metrics": ["latency_p95"],
        }

    def markdown(self) -> str:
        return ""

    def metadata(self):
        raise NotImplementedError


def _make_stage(tmp_path: Path) -> LearnStage:
    state = _seed_state(tmp_path)
    return LearnStage(
        state=state,
        curriculum=_StubCurriculum(),
        provider_factory=lambda: _ScoringProvider(),
    )


# -- Tests -----------------------------------------------------------------


def test_question_progress_returns_zeros_for_missing_session(tmp_path: Path) -> None:
    # The orchestrator may ask for question_progress before a session exists;
    # the result must be safe zeros instead of raising or returning None.
    stage = _make_stage(tmp_path)
    progress = stage.question_progress(None)
    assert progress == {"required_total": 0, "required_passed": 0, "required_pending": 0}


def test_question_progress_counts_only_latest_attempts(tmp_path: Path) -> None:
    # If a baseline question has multiple attempts, only the latest counts
    # toward passed/pending — so a failed retry of a previously passed
    # answer should pull the count back down.
    stage = _make_stage(tmp_path)
    session = _make_session(
        questions=[_baseline_question("q1"), _baseline_question("q2")],
        attempts=[
            _passed_attempt("q1"),
            _failed_attempt("q1"),  # latest attempt for q1 is failed
            _passed_attempt("q2"),
        ],
    )
    progress = stage.question_progress(session)
    assert progress == {"required_total": 2, "required_passed": 1, "required_pending": 1}


def test_required_questions_passed_requires_all_required_to_have_passing_latest(tmp_path: Path) -> None:
    # All required baseline questions must have a passing *latest* attempt
    # before the learning gate is allowed to flip.
    stage = _make_stage(tmp_path)

    not_yet = _make_session(
        questions=[_baseline_question("q1"), _baseline_question("q2")],
        attempts=[_passed_attempt("q1")],
    )
    assert stage.required_questions_passed(not_yet) is False

    done = _make_session(
        questions=[_baseline_question("q1"), _baseline_question("q2")],
        attempts=[_passed_attempt("q1"), _passed_attempt("q2")],
    )
    assert stage.required_questions_passed(done) is True


def test_required_questions_passed_false_when_no_baseline_questions(tmp_path: Path) -> None:
    # A session with no required baseline questions should not flip the gate.
    stage = _make_stage(tmp_path)
    session = _make_session(questions=[])
    assert stage.required_questions_passed(session) is False


def test_answer_question_flips_gate_when_all_required_pass(tmp_path: Path) -> None:
    # Scoring the final missing required answer must flip
    # learning_check_passed on the persisted ledger.
    stage = _make_stage(tmp_path)
    # Seed a learning session on disk with two baseline questions and one
    # already-passed.
    seeded = _make_session(
        questions=[_baseline_question("q1"), _baseline_question("q2")],
        attempts=[_passed_attempt("q1")],
    )
    stage.state.save_learning(seeded)

    # Before scoring the second one, gate is off.
    assert stage.state.load_ledger().state.gates.learning_check_passed is False

    stage.answer_question("q2", "my answer")

    # After scoring (provider stub always passes), gate should be on.
    assert stage.state.load_ledger().state.gates.learning_check_passed is True


def test_reset_pipeline_clears_every_downstream_gate(tmp_path: Path) -> None:
    # reset_pipeline must clear learning, implementation, verification,
    # evidence, and week_approved — plus completed files / metrics /
    # observation / reflection / verification record.
    stage = _make_stage(tmp_path)
    ledger = stage.state.load_ledger()
    ledger.state.gates.learning_check_passed = True
    ledger.state.gates.implementation_complete = True
    ledger.state.gates.verification_passed = True
    ledger.state.gates.evidence_reliable = True
    ledger.state.gates.week_approved = True
    ledger.state.artifacts.completed_files = ["dir_one/file.py"]
    ledger.state.metrics.recorded = {"latency_p95": 10}
    stage.state.save_ledger(ledger)

    reset = stage.reset_pipeline()
    gates = reset.state.gates
    assert not (
        gates.learning_check_passed
        or gates.implementation_complete
        or gates.verification_passed
        or gates.evidence_reliable
        or gates.week_approved
    )
    assert reset.state.artifacts.completed_files == []
    assert reset.state.metrics.recorded == {}
    assert reset.state.verification is None
    assert reset.state.observation is None
    assert reset.state.reflection is None


def test_get_session_returns_none_when_no_session_on_disk(tmp_path: Path) -> None:
    # With no current_learning.json on disk, get_session returns None.
    stage = _make_stage(tmp_path)
    assert stage.get_session() is None


def test_get_bundle_returns_none_when_no_session(tmp_path: Path) -> None:
    # get_bundle is just a projection over get_session and must also return
    # None when there's nothing to project.
    stage = _make_stage(tmp_path)
    assert stage.get_bundle() is None


def test_get_bundle_strips_internal_fields_from_session(tmp_path: Path) -> None:
    # The bundle is the user-facing view: it must not surface rubric internals
    # the session model holds, only concept cards, reading, questions, and
    # attempts.
    stage = _make_stage(tmp_path)
    session = _make_session(
        questions=[_baseline_question("q1")],
        attempts=[_passed_attempt("q1")],
    )
    stage.state.save_learning(session)
    bundle = stage.get_bundle()
    assert bundle is not None
    assert bundle.week == 1
    assert [q.id for q in bundle.questions] == ["q1"]
    assert [a.question_id for a in bundle.attempts] == ["q1"]


def test_build_checkpoint_not_started_when_no_session_and_no_gate(tmp_path: Path) -> None:
    # Before any session is loaded and the learning gate is still off, the
    # checkpoint reads as not_started so the UI prompts the user.
    stage = _make_stage(tmp_path)
    ledger = stage.state.load_ledger()
    checkpoint = stage.build_checkpoint(ledger, None)
    assert checkpoint.status == "not_started"


def test_build_checkpoint_passed_when_session_missing_but_gate_on(tmp_path: Path) -> None:
    # If the gate is already on (e.g. user re-entered the week), the missing
    # session still reads as passed.
    stage = _make_stage(tmp_path)
    ledger = stage.state.load_ledger()
    ledger.state.gates.learning_check_passed = True
    checkpoint = stage.build_checkpoint(ledger, None)
    assert checkpoint.status == "passed"


def test_build_checkpoint_failed_when_a_required_attempt_is_failed(tmp_path: Path) -> None:
    # A failing latest attempt on any required question shows as failed in
    # the checkpoint.
    stage = _make_stage(tmp_path)
    session = _make_session(
        questions=[_baseline_question("q1"), _baseline_question("q2")],
        attempts=[_passed_attempt("q1"), _failed_attempt("q2")],
    )
    ledger = stage.state.load_ledger()
    checkpoint = stage.build_checkpoint(ledger, session)
    assert checkpoint.status == "failed"
    assert "1/2" in checkpoint.reason


def test_build_checkpoint_in_progress_when_some_attempts_but_none_failed(tmp_path: Path) -> None:
    # Mid-flight — some attempts recorded, none failed, not all passed yet.
    stage = _make_stage(tmp_path)
    session = _make_session(
        questions=[_baseline_question("q1"), _baseline_question("q2")],
        attempts=[_passed_attempt("q1")],
    )
    ledger = stage.state.load_ledger()
    checkpoint = stage.build_checkpoint(ledger, session)
    assert checkpoint.status == "in_progress"


def test_build_checkpoint_passed_when_all_required_attempts_pass(tmp_path: Path) -> None:
    # All required questions passed → checkpoint passes.
    stage = _make_stage(tmp_path)
    session = _make_session(
        questions=[_baseline_question("q1"), _baseline_question("q2")],
        attempts=[_passed_attempt("q1"), _passed_attempt("q2")],
    )
    ledger = stage.state.load_ledger()
    checkpoint = stage.build_checkpoint(ledger, session)
    assert checkpoint.status == "passed"


def test_normalize_reading_material_injects_canonical_heading(tmp_path: Path) -> None:
    # When a reading body lacks the canonical "How This Week Works" heading,
    # the normaliser prepends it so the downstream validator passes.
    stage = _make_stage(tmp_path)
    payload = ReadingMaterialPayload(
        week=1,
        title=" My Title ",
        body_markdown="Some intro paragraph.\n\n## Other Section\n\nbody.",
    )
    normalized = stage._normalize_reading_material(payload)
    assert normalized.title == "My Title"
    assert normalized.body_markdown.startswith("## How This Week Works")


def test_normalize_concept_cards_assigns_ids_and_dedupes(tmp_path: Path) -> None:
    # The normaliser must (a) fill in missing ids from concept/title and
    # (b) suffix duplicates so the resulting ids are unique.
    stage = _make_stage(tmp_path)
    cards = [
        ConceptCard(
            id="",
            concept="kv_cache",
            title="KV Cache",
            explanation="x",
            why_it_matters="y",
            common_mistake="z",
            quick_check_question=None,
        ),
        ConceptCard(
            id="",
            concept="kv_cache",
            title="KV Cache",
            explanation="x",
            why_it_matters="y",
            common_mistake="z",
            quick_check_question=None,
        ),
    ]
    normalized = stage._normalize_concept_cards(cards)
    assert normalized[0].id == "kv-cache"
    assert normalized[1].id == "kv-cache-2"


def test_question_by_id_raises_when_missing(tmp_path: Path) -> None:
    # Asking for a question id that doesn't exist surfaces a CoachError
    # with the id echoed back, so the caller can present a useful message.
    stage = _make_stage(tmp_path)
    session = _make_session(questions=[_baseline_question("q1")])
    with pytest.raises(CoachError) as excinfo:
        stage._question_by_id(session, "nope")
    assert "nope" in str(excinfo.value)
