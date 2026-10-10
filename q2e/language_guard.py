"""Detects causal language that a cross-sectional design cannot support and proposes
associational rewrites (applied to the question, protocol text and generated report)."""
from __future__ import annotations

import re

_PATTERNS: list[tuple[str, str]] = [
    (r"\bcaus(?:e|es|ed|ing|al)\b", "is associated with"),
    (r"\blead(?:s)? to\b", "is associated with"),
    (r"\bresult(?:s|ed)? in\b", "is associated with"),
    (r"\beffect(?:s)? of\b", "association of"),
    (r"\bimpact(?:s)? of\b", "association of"),
    (r"\b(?:increase|increases|increased|raise|raises|elevate|elevates)\s+the\s+risk\b", "is associated with a higher prevalence"),
    (r"\b(?:reduce|reduces|reduced|lower|lowers|decrease|decreases)\s+the\s+risk\b", "is associated with a lower prevalence"),
    (r"\bprotect(?:s|ive)?\b", "is inversely associated"),
    (r"\bdue to\b", "associated with"),
    (r"\bbecause of\b", "in association with"),
    (r"\bdrive(?:s|n)?\b", "is associated with"),
    (r"\bcontribut(?:e|es|ed) to\b", "is associated with"),
    (r"\bprevent(?:s|ed)?\b", "is associated with lower"),
    (r"\b(?:improve|improves|worsen|worsens)\b", "is associated with differences in"),
    (r"\bdetermin(?:e|es|ant|ants) of\b", "correlates of"),
]


def scan_causal(text: str, design: str = "cross-sectional") -> list[dict]:
    """Return causal phrases found in `text` with suggested replacements."""
    if not text or design not in ("cross-sectional", "cross_sectional"):
        return []
    out = []
    low = text.lower()
    for pat, repl in _PATTERNS:
        for m in re.finditer(pat, low):
            ctx = text[max(0, m.start() - 40): m.end() + 40]
            out.append({"phrase": text[m.start():m.end()], "start": m.start(), "suggestion": repl, "context": ctx.strip()})
    return out


def soften(text: str) -> str:
    """Conservative automatic rewrite used for generated narrative only."""
    out = text
    for pat, repl in _PATTERNS[:5]:
        out = re.sub(pat, repl, out, flags=re.IGNORECASE)
    return out
