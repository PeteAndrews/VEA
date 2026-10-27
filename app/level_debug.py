"""Optional debug dumps of level-judgement LLM prompts (env-gated)."""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.level_classifier import _load_level_judgement_prompt, build_llm_payload

logger = logging.getLogger(__name__)

_TRUTHY = frozenset({"1", "true", "yes", "on"})


def _debug_enabled() -> bool:
    return os.getenv("VEA_DEBUG_LEVEL_JUDGEMENT", "").strip().lower() in _TRUTHY


def _debug_dir() -> Path:
    raw = os.getenv("VEA_DEBUG_LEVEL_JUDGEMENT_DIR", "").strip()
    if raw:
        return Path(raw)
    return Path(os.getenv("VEA_DATA_DIR", "data")) / "debug" / "levels"


def _safe_part(value: str, *, fallback: str = "unknown") -> str:
    cleaned = re.sub(r"[^\w.-]+", "_", value.strip())
    return cleaned or fallback


def maybe_save_level_judgement_prompt_debug(
    context: dict[str, Any],
    *,
    meta: dict[str, Any],
) -> None:
    if not _debug_enabled():
        return
    try:
        artifact = {
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "meta": meta,
            "system_prompt": _load_level_judgement_prompt(),
            "user_payload": build_llm_payload(context),
        }
        out_dir = _debug_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
        level = meta.get("tentative_level")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        stem = "_".join(
            [
                stamp,
                _safe_part(str(meta.get("marking_session_id") or "session")),
                _safe_part(str(meta.get("response_id") or "response")),
                f"level-{level}" if level is not None else "level-unknown",
            ]
        )
        path = out_dir / f"{stem}.json"
        with path.open("w", encoding="utf-8") as handle:
            json.dump(artifact, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
    except OSError:
        logger.warning("failed to save level judgement debug prompt", exc_info=True)
