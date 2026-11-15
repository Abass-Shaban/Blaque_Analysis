"""Vercel serverless entrypoint for BLAQUE ANALYSIS."""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is in sys.path so that 'backend' can be imported anywhere
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.app.main import app  # noqa: E402
