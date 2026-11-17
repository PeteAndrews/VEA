"""Load and parse baseline marking materials (question, mark scheme, commentary)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def materials_dir(data_dir: str | Path) -> Path:
    return Path(data_dir) / "marking-materials"


def _paths(data_dir: str | Path, assessment_id: str) -> tuple[Path, Path, Path]:
    base = materials_dir(data_dir)
    return (
        base / f"{assessment_id}-Q.txt",
        base / f"{assessment_id}-MS.txt",
        base / f"{assessment_id}-C.txt",
    )


def load_baseline_materials(data_dir: str | Path, assessment_id: str) -> dict[str, Any]:
    q_path, ms_path, c_path = _paths(data_dir, assessment_id)
    missing = [path.name for path in (q_path, ms_path, c_path) if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            f"Marking materials missing for {assessment_id}: {', '.join(missing)}"
        )
    question_text = q_path.read_text(encoding="utf-8")
    mark_scheme_text = ms_path.read_text(encoding="utf-8")
    commentary_text = c_path.read_text(encoding="utf-8")
    return {
        "question": parse_question_text(question_text),
        "mark_scheme": parse_mark_scheme_text(mark_scheme_text),
        "commentary": parse_commentary_text(commentary_text),
    }


def parse_question_text(text: str) -> dict[str, Any]:
    lines = [line.rstrip() for line in text.splitlines()]
    question_ref = ""
    body_lines: list[str] = []
    marks_text = ""
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if re.match(r"^Q\.\s*", stripped, re.IGNORECASE):
            question_ref = re.sub(r"^Q\.\s*", "", stripped, flags=re.IGNORECASE).strip()
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            marks_text = stripped
            continue
        body_lines.append(stripped)
    return {
        "question_ref": question_ref or None,
        "body_lines": body_lines,
        "marks_text": marks_text,
    }


_LEVEL_START = re.compile(
    r"^(Level\s+(\d+)|No relevant content)\s*[:.]?\s*(.*)$",
    re.IGNORECASE,
)
_MARK_SUFFIX = re.compile(r"\s*Mark:\s*([0-9]+(?:[–\-][0-9]+)?)\s*$", re.IGNORECASE)
_TRAILING_MARK = re.compile(r"(?:^|\s)([0-9]+(?:[–\-][0-9]+)?)\s*$")
_MARK_ONLY = re.compile(r"^[0-9]+(?:[–\-][0-9]+)?$")


def parse_mark_scheme_text(text: str) -> dict[str, Any]:
    normalized = text.replace("\r\n", "\n")
    for dash in ("‐", "‑", "‒", "–", "—", "−"):
        normalized = normalized.replace(dash, "-")
    parts = re.split(r"\n\s*Indicative content\s*:?\s*\n", normalized, maxsplit=1, flags=re.IGNORECASE)
    level_block = parts[0]
    indicative_block = parts[1] if len(parts) > 1 else ""

    levels = _parse_levels(level_block)
    indicative = _parse_indicative(indicative_block) if indicative_block.strip() else None
    return {"levels": levels, "indicative_content": indicative}


def _parse_levels(block: str) -> list[dict[str, Any]]:
    lines = block.splitlines()
    entries: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    def flush() -> None:
        nonlocal current
        if current is None:
            return
        current["descriptor"] = " ".join(current.pop("_parts", [])).strip()
        entries.append(current)
        current = None

    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        match = _LEVEL_START.match(line)
        if match:
            flush()
            label = match.group(1)
            level_num = int(match.group(2)) if match.group(2) else 0
            rest = match.group(3) or ""
            mark_match = _MARK_SUFFIX.search(rest) or _TRAILING_MARK.search(rest)
            mark = None
            descriptor_start = rest
            if mark_match:
                mark = mark_match.group(1).replace("-", "–")
                descriptor_start = rest[: mark_match.start()].strip()
            current = {
                "label": label,
                "level": level_num,
                "mark": mark,
                "_parts": [descriptor_start] if descriptor_start else [],
            }
            continue
        if current is not None:
            mark_only = re.match(r"^Mark:\s*([0-9]+(?:[–\-][0-9]+)?)\s*$", line, re.IGNORECASE)
            if mark_only or _MARK_ONLY.match(line):
                current["mark"] = (mark_only.group(1) if mark_only else line).replace("-", "–")
                continue
            mark_inline = _MARK_SUFFIX.search(line) or _TRAILING_MARK.search(line)
            if mark_inline:
                current["mark"] = mark_inline.group(1).replace("-", "–")
                line = line[: mark_inline.start()].strip()
            if line:
                current["_parts"].append(line)

    flush()
    return entries


def _parse_indicative(block: str) -> dict[str, Any]:
    lines = block.splitlines()
    themes: list[dict[str, Any]] = []
    footer_note = ""
    current_theme: dict[str, Any] | None = None
    current_item: dict[str, Any] | None = None

    def ensure_theme(title: str) -> None:
        nonlocal current_theme
        current_theme = {"title": title, "items": []}
        themes.append(current_theme)

    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if line.startswith("For Level"):
            footer_note = line
            break
        if line.endswith(":") and "•" not in line and not line.startswith("o "):
            ensure_theme(line)
            current_item = None
            continue
        if line.startswith("•"):
            bullet = line.lstrip("•").strip()
            current_item = {"text": bullet, "subitems": []}
            if current_theme is None:
                ensure_theme("")
            current_theme["items"].append(current_item)
            continue
        if line.startswith("o "):
            sub = line[2:].strip()
            if current_item is None:
                current_item = {"text": "", "subitems": []}
                if current_theme is None:
                    ensure_theme("")
                current_theme["items"].append(current_item)
            current_item["subitems"].append(sub)
            continue
        if line.startswith("-") and current_item is not None:
            continuation = line.lstrip("-").strip()
            if current_item["subitems"]:
                current_item["subitems"][-1] = f"{current_item['subitems'][-1]} {continuation}"
            else:
                current_item["text"] = f"{current_item['text']} {continuation}".strip()
            continue
        if current_item is not None:
            if current_item["subitems"]:
                current_item["subitems"][-1] = f"{current_item['subitems'][-1]} {line}"
            else:
                current_item["text"] = f"{current_item['text']} {line}".strip()

    return {"themes": themes, "footer_note": footer_note or None}


def parse_commentary_text(text: str) -> dict[str, Any]:
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    return {"paragraphs": paragraphs}
