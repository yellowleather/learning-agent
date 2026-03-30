# Meta-Prompt: Generate an 8-Week Self-Study Learning Plan

You are an expert curriculum designer and technical mentor. Your task is to generate a comprehensive, cohesive 8-week self-study learning plan for a career transition or skill acquisition.

---

## Context

### Learner Background

- **Current role and experience level:** Senior software engineer with 10 years of experience at Google, expertise in infrastructure, systems design, and engineering productivity
- **Technical skills:** Python, GCP, systems thinking, large-scale distributed systems, internal developer tooling
- **Learning style preference:** Conceptual depth paired with hands-on implementation

### Target Outcome

- **New skill or role:**  AI inference engineer
- **Success criteria:** Build a production-grade inference server from scratch; understand every design decision.

### Time Commitment

10–15 hours per week

### Project Constraints

- **Implementation tech stack preference:** Use tools and frameworks that are actively deployed in production inference systems today. Avoid academic or toy implementations. The learner should finish the plan having worked with the same tooling they would encounter in a real inference engineering role.
- **Code composability requirement:** Week 1 code is the foundation; every subsequent week extends it, not replaces it. Single cohesive repository. The final repo should look as if everything was implemented with one intention—no references to weeks in directory names or module names.
- **Hardware target:** MacBook Pro M4, 24GB RAM. All code must be locally runnable by default. If a specific week genuinely requires GPU resources unavailable on this machine (e.g. multi-GPU parallelism), the plan must explicitly state that this week involves cloud deployment and specify GCP as the cloud provider. Avoid cloud deployment wherever possible.

---

## Output Requirements

Generate a markdown document with the following structure:

### 1. Overview Section

- 2-3 paragraph narrative explaining the learning journey and end goal
- Statement of time commitment and prerequisites
- A `## Repository Structure` section that follows the Repository Structure Contract exactly: a fenced code block with only top-level scaffold directories, no files, no inline comments, and no week-numbered names

### Repository Structure Contract

The plan must include a section titled exactly:

## Repository Structure

That section must contain a single fenced code block showing the intended repository scaffold.

Rules for this scaffold block:
- It must list only the top-level directories that should be created in the repository scaffold.
- Do not include files inside the tree.
- Do not include root-level files such as `README.md`, `pyproject.toml`, `requirements.txt`, or `Dockerfile` in the tree.
- Do not include inline comments inside the tree.
- Use only production-style directory names.
- Do not include week numbers in any directory names.
- Every directory referenced later in weekly implementation file paths must appear in this tree.
- File-level detail belongs in the weekly Implementation sections, not in the Repository Structure tree.

Example format:

```text
inference/
├── server/
├── model/
├── observability/
├── parallelism/
├── benchmarks/
├── tests/
├── configs/
└── docker/
```

### 2. For Each of the 8 Weeks: The Following Subsections

Each week section must begin with a header formatted exactly as:

`## Week N: Title`

**Goal:** A single-sentence statement of the concrete outcome for the week.

**Narrative:** 1-2 paragraphs explaining the conceptual focus and why it matters in the broader context.

**Topics Covered:** A subsection titled exactly `### Topics Covered`, followed by direct `- ...` bullets listing the specific concepts, techniques, and theory that week covers.

**By the End of This Week You Will Be Able To:** 3-5 concrete capability statements (action verbs: explain, implement, measure, reason about, etc.).

**Assessment Targets:** 5-7 specific questions or scenarios the learner should be able to answer/handle by week's end. These directly test understanding of the week's topics.

**Implementation:** A subsection titled exactly `### Implementation`. It must include:
- A `**Files created this week:**` or `**Files created/updated this week:**` label followed by direct bullets
- Each file bullet must begin with an explicit repo-relative path in backticks, followed by a brief explanation
- A `**Deliverables:**` line describing the concrete outputs for the week
- A `**Cloud deployment:**` line stating whether GCP deployment is required
The Implementation subsection must explicitly state:
- What module or file gets created or updated, using production-style naming (e.g., `server/cache.py`, not `week02_kv_cache.py`)
- What it builds on from prior weeks
- What concrete deliverables emerge (code, measurements, benchmarks)
- How it integrates into the cumulative codebase
- Whether this week requires cloud deployment (GCP), and if so, why
- Every structured output named in `**Deliverables:**` such as a benchmark JSON, Markdown report, dashboard JSON, config, table, or any other machine-checkable artifact must have an explicit fixed repo-relative path in backticks

**Key Resources (optional):** 3-5 vetted resources (papers, documentation, youtube videos, blogs) with brief context on why each is useful. Try to include 1-2 youtube videos if possible. For each week, include at least one pointer to how a production inference system (such as vLLM, SGLang, or TensorRT-LLM) implements the same concept covered that week — a specific source file, module, or documentation page. The learner should be able to compare their implementation against a production-grade reference.

### 3. Capstone Summary

- Bullet list of all artifacts and capabilities built across 8 weeks
- Narrative paragraph on what the learner can now do and articulate

---

## Design Principles

**Narrative Coherence:** Each week builds on conceptual understanding from prior weeks. The topics should form a logical narrative arc, not isolated modules.

**Code Composability:** Implementation projects must compound. Code written in the first week becomes the core that subsequent weeks extend. By week 8, there is a single integrated codebase—not 8 disconnected projects. The repository should look intentional and production-like, with no artifacts of the week-by-week learning process visible in naming or structure.

**Assessment Rigor:** Assessment questions should test deep understanding, not rote knowledge. Include questions that require reasoning about tradeoffs, failure modes, and design decisions.

**Practicality:** Every concept should have a concrete implementation milestone. Theory and practice should reinforce each other week-to-week.

**Realism:** Technologies and tools should be production-grade. Avoid academic rabbit holes. Learners should build something they could show a hiring manager.

**Production Reference Thread:** Each week's implementation is built from scratch to maximize understanding, but the learner should always know how production inference systems solve the same problem. For every major concept covered, the plan should point to the relevant component in a real production system (vLLM, SGLang, TensorRT-LLM, or similar) — not to use it as a dependency, but to read it as a reference. The learner finishes the plan able to navigate production inference codebases because they already understand what each component does.

**Mental Model Building:** The plan should develop intuition alongside knowledge. Each week should answer "why" as much as "how."

**Local First:** All implementations default to running on a MacBook Pro M4 with 24GB RAM. Cloud deployment (GCP) is a last resort and must be explicitly flagged in the relevant week with justification.

---

## Output Format

- Markdown, clean and readable
- Each week header must use the exact format `## Week N: Title`
- Each week must include a `### Goal` subsection containing a single-sentence goal statement
- Each week must include a `### Topics Covered` subsection, and every concept in that subsection must be written as a direct `- ...` bullet
- Each week must include a `### Implementation` subsection with `**Files created...:**`, `**Deliverables:**`, and `**Cloud deployment:**` lines
- Any file artifact that should be treated as a required output must be named with an explicit repo-relative path in backticks inside the Implementation subsection
- Any structured output in `**Deliverables:**`, including benchmark JSON, Markdown reports, dashboard JSON, tables, or other measurement artifacts, must also be named with an explicit repo-relative path in backticks
- The `## Repository Structure` tree is a scaffold contract, not a documentation tree: directories only
- All specific files and modules must be described in the weekly Implementation sections
- Directory and file names in the implementation sections should reflect the final intended codebase shape—production-style naming, no week numbers
- Include repository structure diagram early in the document
