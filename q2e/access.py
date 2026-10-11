"""Setup code that proves a browser user is the person running BEDSIDE (needed only from another computer or a Codespace).

The code is created once and kept in the workspace folder (which git ignores), so it stays the same across restarts,
server workers and terminals. Show it any time with:  python -m q2e setup-code
Set your own with Q2E_SETUP_CODE in .env.
"""
from __future__ import annotations

import os
import re
import secrets

from .config import settings


def _file():
    return settings.workspace / ".setup_code"


def setup_code() -> str:
    own = os.environ.get("Q2E_SETUP_CODE", "").strip()
    if own:
        return own
    f = _file()
    try:
        code = f.read_text(encoding="utf-8").strip()
        if re.fullmatch(r"\d{4}-\d{4}", code):
            return code
    except OSError:
        pass
    code = f"{secrets.randbelow(10 ** 4):04d}-{secrets.randbelow(10 ** 4):04d}"
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(code, encoding="utf-8")
        os.chmod(f, 0o600)
    except OSError:
        pass
    return code


def _norm(code: str) -> str:
    return re.sub(r"[^0-9A-Za-z]", "", code or "").lower()


def check(code: str) -> bool:
    """Compare ignoring spaces and dashes (1234 5678, 12345678 and 1234-5678 are the same)."""
    given = _norm(code)
    return bool(given) and secrets.compare_digest(given, _norm(setup_code()))
