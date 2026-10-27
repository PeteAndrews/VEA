"""Backend install root and default paths (works when cwd is backend/)."""

from __future__ import annotations

import os
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = Path(os.getenv("VEA_PROJECT_ROOT", str(BACKEND_ROOT)))
DATA_DIR = Path(os.getenv("VEA_DATA_DIR", str(BACKEND_ROOT / "data")))
PROMPTS_DIR = Path(os.getenv("VEA_PROMPTS_DIR", str(BACKEND_ROOT / "prompts")))
