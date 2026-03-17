from __future__ import annotations

import re
from pathlib import Path
from typing import List

from learning_agent.errors import LearningAgentError
from learning_agent.models import CurriculumMetadata, WeekSpec


WEEK_HEADER_RE = re.compile(r"^# Week (\d+) --- (.+)$", re.MULTILINE)
SECTION_RE_TEMPLATE = r"^## {heading}\n(?P<body>.*?)(?=^## |\Z)"


def load_curriculum(roadmap_path: Path, target_repo_path: str) -> tuple[CurriculumMetadata, List[WeekSpec]]:
    try:
        raw = roadmap_path.read_text()
    except FileNotFoundError as exc:
        raise LearningAgentError(f"Roadmap file not found: {roadmap_path}") from exc

    week_matches = list(WEEK_HEADER_RE.finditer(raw))
    if not week_matches:
        raise LearningAgentError("No weeks found in roadmap markdown.")

    weeks: List[WeekSpec] = []
    for index, match in enumerate(week_matches):
        start = match.end()
        end = week_matches[index + 1].start() if index + 1 < len(week_matches) else len(raw)
        block = raw[start:end].strip()
        week_number = int(match.group(1))
        week_title = match.group(2).strip()
        weeks.append(parse_week_block(week_number, week_title, block))

    metadata = CurriculumMetadata(
        title="AI Inference Engineering",
        total_weeks=len(weeks),
        target_repo=target_repo_path,
    )
    return metadata, weeks


def get_week_spec(weeks: List[WeekSpec], week_number: int) -> WeekSpec:
    for week in weeks:
        if week.number == week_number:
            return week
    raise LearningAgentError(f"Week {week_number} does not exist in the roadmap.")


def parse_week_block(week_number: int, week_title: str, block: str) -> WeekSpec:
    goal = extract_section_text(block, "Goal")
    learn = extract_section_text(block, "Learn")
    tasks_section = extract_section_text(block, "Tasks")
    tasks = extract_bullets(tasks_section)
    deliverables = extract_section_text(block, "Deliverables")
    concepts = extract_named_bullets(learn, "Concepts:")
    deliverable_paths = extract_deliverable_paths(deliverables)
    document_section = extract_document_paths(deliverables, block)
    all_deliverables = dedupe_preserving_order(deliverable_paths + document_section)
    required_files = [path for path in all_deliverables if not path.endswith("/")]
    active_dirs = derive_active_dirs(all_deliverables)
    required_metrics = derive_required_metrics(tasks_section, block)

    return WeekSpec(
        number=week_number,
        title=week_title,
        goal=goal,
        concepts=concepts,
        tasks=tasks,
        deliverable_paths=all_deliverables,
        required_files=required_files,
        active_dirs=active_dirs,
        required_metrics=required_metrics,
    )


def extract_section_text(block: str, heading: str) -> str:
    pattern = re.compile(SECTION_RE_TEMPLATE.format(heading=re.escape(heading)), re.MULTILINE | re.DOTALL)
    match = pattern.search(block)
    if not match:
        return ""
    return match.group("body").strip("\n")


def extract_named_bullets(section_text: str, marker: str) -> List[str]:
    if not section_text:
        return []
    lines = section_text.splitlines()
    collecting = False
    items: List[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped == marker:
            collecting = True
            continue
        if collecting and stripped.endswith(":") and not stripped.startswith("-"):
            break
        if collecting and stripped.startswith("-"):
            items.append(stripped[1:].strip())
    return items


def extract_bullets(section_text: str) -> List[str]:
    items: List[str] = []
    for line in section_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("-"):
            items.append(stripped[1:].strip())
    return items


def extract_deliverable_paths(section_text: str) -> List[str]:
    entries: List[str] = []
    current_dir = ""
    for line in section_text.splitlines():
        if not line.startswith("    "):
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()
        if not stripped:
            continue
        if indent == 4:
            current_dir = stripped.rstrip("/") if stripped.endswith("/") else ""
            entries.append(stripped if stripped.endswith("/") else stripped)
        elif indent >= 8 and current_dir:
            entries.append(f"{current_dir}/{stripped.rstrip('/')}")
    return entries


def extract_document_paths(deliverables_text: str, full_block: str) -> List[str]:
    if "Document:" not in full_block and "Documents:" not in full_block:
        return []
    paths: List[str] = []
    in_document = False
    for line in full_block.splitlines():
        stripped = line.strip()
        if stripped in {"Document:", "Documents:"}:
            in_document = True
            continue
        if in_document and stripped.startswith("## "):
            break
        if in_document and line.startswith("    "):
            paths.append(stripped.rstrip("/"))
        elif in_document and stripped and not stripped.startswith("------------------------------------------------------------------------"):
            # Stop once normal prose resumes.
            continue
    return paths


def derive_active_dirs(deliverable_paths: List[str]) -> List[str]:
    dirs: List[str] = []
    for path in deliverable_paths:
        normalized = path.rstrip("/")
        if "/" not in normalized:
            dirs.append(normalized)
            continue
        dirs.append(normalized.split("/", 1)[0])
    return dedupe_preserving_order(dirs)


def derive_required_metrics(tasks_text: str, block: str) -> List[str]:
    extra_metrics = []
    for marker in ("Add metrics:", "Measure:", "Track:"):
        extra_metrics.extend(extract_marker_bullets(block, marker))
    haystack = "\n".join([tasks_text, *extra_metrics]).lower()
    metrics: List[str] = []
    if "latency" in haystack:
        metrics.append("latency_p95")
    if "tokens/sec" in haystack or "tokens per second" in haystack:
        metrics.append("tokens_per_sec")
    if "throughput" in haystack:
        metrics.append("throughput")
    if "memory usage" in haystack:
        metrics.append("memory_usage")
    if "gpu utilization" in haystack:
        metrics.append("gpu_utilization")
    return dedupe_preserving_order(metrics)


def extract_marker_bullets(block: str, marker: str) -> List[str]:
    lines = block.splitlines()
    collecting = False
    items: List[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped == marker:
            collecting = True
            continue
        if collecting and stripped.endswith(":") and not stripped.startswith("-"):
            collecting = False
            continue
        if collecting and stripped.startswith("-"):
            items.append(stripped[1:].strip())
    return items


def dedupe_preserving_order(items: List[str]) -> List[str]:
    seen = set()
    ordered: List[str] = []
    for item in items:
        if item not in seen:
            ordered.append(item)
            seen.add(item)
    return ordered
