from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from coach.errors import CoachError


PLAN_TITLE_RE = re.compile(r"^# (?P<title>.+)$", re.MULTILINE)
TOP_LEVEL_SECTION_RE = re.compile(r"^## (?P<heading>.+)$", re.MULTILINE)
SUBSECTION_RE = re.compile(r"^### (?P<heading>.+)$", re.MULTILINE)
WEEK_HEADING_RE = re.compile(r"^Week (?P<number>\d+): (?P<title>.+)$")

REQUIRED_WEEK_SUBSECTIONS = [
    "Goal",
    "Narrative",
    "Topics Covered",
    "By the End of This Week You Will Be Able To",
    "Assessment Targets",
    "Implementation",
]


def load_roadmap_dict(roadmap_path: Path) -> dict[str, Any]:
    try:
        raw = roadmap_path.read_text()
    except FileNotFoundError as exc:
        raise CoachError(f"Roadmap file not found: {roadmap_path}") from exc
    return parse_roadmap_markdown(raw)


def parse_roadmap_markdown(raw: str) -> dict[str, Any]:
    title_match = PLAN_TITLE_RE.search(raw)
    if not title_match:
        raise CoachError("Roadmap markdown must start with a level-1 title.")

    top_sections = split_sections(raw, TOP_LEVEL_SECTION_RE)
    if not top_sections:
        raise CoachError("Roadmap markdown does not contain any level-2 sections.")

    top_section_map = {heading: body for heading, body in top_sections if not heading.startswith("Week ")}

    overview = top_section_map.get("Overview", "").strip()
    if not overview:
        raise CoachError("Roadmap markdown must contain a non-empty `## Overview` section.")

    repository_structure_body = top_section_map.get("Repository Structure", "").strip()
    if not repository_structure_body:
        raise CoachError("Roadmap markdown must contain a non-empty `## Repository Structure` section.")

    capstone_summary_body = top_section_map.get("Capstone Summary", "").strip()
    if not capstone_summary_body:
        raise CoachError("Roadmap markdown must contain a non-empty `## Capstone Summary` section.")

    week_sections = [(heading, body) for heading, body in top_sections if heading.startswith("Week ")]
    if not week_sections:
        raise CoachError("Roadmap markdown must contain at least one week section.")

    weeks: list[dict[str, Any]] = []
    for expected_number, (heading, body) in enumerate(week_sections, start=1):
        match = WEEK_HEADING_RE.match(heading)
        if not match:
            raise CoachError(f"Invalid week heading format: `## {heading}`.")
        week_number = int(match.group("number"))
        short_title = match.group("title").strip()
        if week_number != expected_number:
            raise CoachError(
                f"Week headings must be contiguous starting at 1; expected Week {expected_number} but found Week {week_number}."
            )
        weeks.append(parse_week_section(week_number, short_title, body))

    return {
        "title": title_match.group("title").strip(),
        "overview": overview,
        "repository_structure": parse_repository_structure(repository_structure_body),
        "weeks": weeks,
        "capstone_summary": parse_capstone_summary(capstone_summary_body),
    }


def split_sections(block: str, pattern: re.Pattern[str]) -> list[tuple[str, str]]:
    matches = list(pattern.finditer(block))
    sections: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(block)
        sections.append((match.group("heading").strip(), block[start:end].strip()))
    return sections


def parse_repository_structure(body: str) -> dict[str, Any]:
    code_block_match = re.search(r"```(?:\w+)?\n(?P<tree>.*?)\n```", body, re.DOTALL)
    if not code_block_match:
        raise CoachError("`## Repository Structure` must contain a fenced code block with the repository tree.")

    tree = code_block_match.group("tree").strip()
    description = body.replace(code_block_match.group(0), "").strip()
    directories = parse_repository_directories(tree)
    if not directories:
        raise CoachError("`## Repository Structure` must list at least one scaffold directory.")

    return {
        "tree": tree,
        "directories": directories,
        "description": description,
    }


def parse_repository_directories(tree: str) -> list[str]:
    directories: list[str] = []
    for line in tree.splitlines():
        stripped = line.strip()
        if not stripped or stripped.endswith("/") is False:
            continue
        if stripped.startswith(("├──", "└──")):
            candidate = stripped.split("──", 1)[1].strip().rstrip("/")
            if candidate:
                directories.append(candidate)
    return dedupe_preserving_order(directories)


def parse_week_section(week_number: int, short_title: str, body: str) -> dict[str, Any]:
    subsections = split_sections(body, SUBSECTION_RE)
    subsection_map = {heading: subsection_body for heading, subsection_body in subsections}

    for heading in REQUIRED_WEEK_SUBSECTIONS:
        if not subsection_map.get(heading, "").strip():
            raise CoachError(f"Week {week_number} is missing required subsection `### {heading}`.")

    topics_covered = extract_bullets(subsection_map["Topics Covered"])
    if not topics_covered:
        raise CoachError(f"Week {week_number} `### Topics Covered` must contain direct bullet items.")

    by_end = extract_bullets(subsection_map["By the End of This Week You Will Be Able To"])
    if not by_end:
        raise CoachError(
            f"Week {week_number} `### By the End of This Week You Will Be Able To` must contain bullet items."
        )

    assessment_targets = extract_numbered_items(subsection_map["Assessment Targets"])
    if not assessment_targets:
        raise CoachError(f"Week {week_number} `### Assessment Targets` must contain numbered items.")

    implementation = parse_implementation_subsection(week_number, subsection_map["Implementation"])
    key_resources = extract_bullets(subsection_map.get("Key Resources", ""))

    return {
        "number": week_number,
        "title": f"Week {week_number}: {short_title}",
        "short_title": short_title,
        "goal": collapse_whitespace(subsection_map["Goal"]),
        "narrative": subsection_map["Narrative"].strip(),
        "topics_covered": topics_covered,
        "by_the_end_of_this_week_you_will_be_able_to": by_end,
        "assessment_targets": assessment_targets,
        "implementation": implementation,
        "key_resources": key_resources,
        "tasks": implementation["tasks"],
        "deliverable_paths": implementation["deliverable_paths"],
        "required_files": implementation["required_files"],
        "active_dirs": derive_active_dirs(implementation["deliverable_paths"]),
        "required_metrics": derive_required_metrics(implementation["tasks"], implementation["body"]),
    }


def parse_implementation_subsection(week_number: int, body: str) -> dict[str, Any]:
    files_label = None
    for candidate in ("**Files created this week:**", "**Files created/updated this week:**"):
        if candidate in body:
            files_label = candidate
            break
    if not files_label:
        raise CoachError(
            f"Week {week_number} `### Implementation` must include `**Files created this week:**` "
            "or `**Files created/updated this week:**`."
        )

    deliverables_text = extract_inline_marker_value(body, "**Deliverables:**")
    if not deliverables_text:
        raise CoachError(f"Week {week_number} `### Implementation` must include a `**Deliverables:**` line.")

    cloud_deployment = extract_inline_marker_value(body, "**Cloud deployment:**")
    if not cloud_deployment:
        raise CoachError(f"Week {week_number} `### Implementation` must include a `**Cloud deployment:**` line.")

    files = parse_implementation_files(week_number, body, files_label)
    deliverable_paths = dedupe_preserving_order(
        [file_entry["path"] for file_entry in files] + extract_deliverable_paths_from_text(deliverables_text)
    )
    required_files = [path for path in deliverable_paths if not path.endswith("/")]
    tasks = dedupe_preserving_order(
        [f"`{file_entry['path']}` — {file_entry['description']}".strip() for file_entry in files]
        + [deliverables_text, cloud_deployment]
    )

    return {
        "body": body.strip(),
        "files": files,
        "deliverables_text": deliverables_text,
        "deliverable_paths": deliverable_paths,
        "required_files": required_files,
        "cloud_deployment": cloud_deployment,
        "tasks": tasks,
    }


def parse_implementation_files(week_number: int, body: str, files_label: str) -> list[dict[str, str]]:
    lines = body.splitlines()
    collecting = False
    files: list[dict[str, str]] = []
    for line in lines:
        stripped = line.strip()
        if stripped == files_label:
            collecting = True
            continue
        if not collecting:
            continue
        if stripped.startswith("**Deliverables:**") or stripped.startswith("**Cloud deployment:**"):
            break
        if not stripped:
            continue
        if not stripped.startswith("- "):
            continue
        match = re.match(r"-\s+`(?P<path>[^`]+)`(?P<remainder>.*)$", stripped)
        if not match:
            raise CoachError(
                f"Week {week_number} implementation file bullets must begin with an explicit backticked repo-relative path."
            )
        path = normalize_repo_path(match.group("path"))
        if not path:
            raise CoachError(f"Week {week_number} contains an invalid implementation file path: `{match.group('path')}`.")
        remainder = match.group("remainder").strip()
        description = remainder.lstrip("—- ").strip()
        files.append(
            {
                "path": path,
                "description": description,
            }
        )

    if not files:
        raise CoachError(f"Week {week_number} `### Implementation` must list at least one file bullet.")
    return files


def extract_deliverable_paths_from_text(deliverables_text: str) -> list[str]:
    validate_structured_deliverables_have_paths(deliverables_text)
    paths: list[str] = []
    for match in re.finditer(r"`([^`\n]+)`", deliverables_text):
        candidate = normalize_repo_path(match.group(1))
        if candidate:
            paths.append(candidate)
    return dedupe_preserving_order(paths)


def validate_structured_deliverables_have_paths(deliverables_text: str) -> None:
    sentences = [sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+", deliverables_text) if sentence.strip()]
    structured_keywords = ("json", "report", "dashboard", "table", "readme", "runbook", "analysis", "note")
    for sentence in sentences:
        lower = sentence.lower()
        if any(keyword in lower for keyword in structured_keywords) and "`" not in sentence:
            raise CoachError(
                "Structured outputs in `**Deliverables:**` must have explicit repo-relative paths in backticks."
            )


def parse_capstone_summary(body: str) -> dict[str, Any]:
    subsections = split_sections(body, SUBSECTION_RE)
    subsection_map = {heading: subsection_body for heading, subsection_body in subsections}

    artifacts_built = parse_markdown_table(subsection_map.get("Artifacts Built", ""))
    if not artifacts_built:
        raise CoachError("`## Capstone Summary` must include a non-empty `### Artifacts Built` table.")

    what_you_can_now_do = subsection_map.get("What You Can Now Do", "").strip()
    if not what_you_can_now_do:
        raise CoachError("`## Capstone Summary` must include a non-empty `### What You Can Now Do` section.")

    return {
        "artifacts_built": artifacts_built,
        "what_you_can_now_do": what_you_can_now_do,
    }


def parse_markdown_table(body: str) -> list[dict[str, str]]:
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    table_lines = [line for line in lines if line.startswith("|") and line.endswith("|")]
    if len(table_lines) < 3:
        return []

    headers = [cell.strip() for cell in table_lines[0].strip("|").split("|")]
    rows: list[dict[str, str]] = []
    for line in table_lines[2:]:
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) != len(headers):
            continue
        rows.append(dict(zip([slugify_header(header) for header in headers], cells)))
    return rows


def slugify_header(header: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", header.lower()).strip("_")


def extract_bullets(section_text: str) -> list[str]:
    items: list[str] = []
    for line in section_text.splitlines():
        stripped = line.strip()
        if is_markdown_thematic_break(stripped):
            continue
        if stripped.startswith("-"):
            items.append(stripped[1:].strip())
    return items


def extract_numbered_items(section_text: str) -> list[str]:
    items: list[str] = []
    for line in section_text.splitlines():
        stripped = line.strip()
        match = re.match(r"\d+\.\s+(.*)", stripped)
        if match:
            items.append(match.group(1).strip())
    return items


def extract_inline_marker_value(section_text: str, marker: str) -> str:
    for line in section_text.splitlines():
        stripped = line.strip()
        if stripped.startswith(marker):
            return stripped[len(marker) :].strip()
    return ""


def normalize_repo_path(candidate: str) -> str:
    cleaned = candidate.strip().strip("`").rstrip(".,:")
    if not cleaned:
        return ""
    if cleaned.endswith("/"):
        return cleaned
    if cleaned in {"README", "README.md"}:
        return "README.md"
    if cleaned == "RUNBOOK.md":
        return "RUNBOOK.md"
    if "/" in cleaned or "." in cleaned:
        return cleaned.rstrip("/")
    return ""


def derive_active_dirs(deliverable_paths: list[str]) -> list[str]:
    dirs: list[str] = []
    for path in deliverable_paths:
        normalized = path.rstrip("/")
        if "/" not in normalized:
            dirs.append(normalized)
            continue
        dirs.append(normalized.split("/", 1)[0])
    return dedupe_preserving_order(dirs)


def derive_required_metrics(tasks: list[str], implementation_text: str) -> list[str]:
    haystack = "\n".join([*tasks, implementation_text]).lower()
    metrics: list[str] = []
    if "latency" in haystack or "ttft" in haystack or "itl" in haystack:
        metrics.append("latency_p95")
    if "tokens/sec" in haystack or "tokens per second" in haystack:
        metrics.append("tokens_per_sec")
    if "throughput" in haystack:
        metrics.append("throughput")
    if "memory usage" in haystack or "memory consumption" in haystack:
        metrics.append("memory_usage")
    if "gpu utilization" in haystack:
        metrics.append("gpu_utilization")
    return dedupe_preserving_order(metrics)


def collapse_whitespace(text: str) -> str:
    return " ".join(text.split())


def is_markdown_thematic_break(line: str) -> bool:
    return bool(re.fullmatch(r"([-*_])\1{2,}", line))


def dedupe_preserving_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item not in seen:
            ordered.append(item)
            seen.add(item)
    return ordered
