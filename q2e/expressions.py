"""Python-side validation of the Q2E safe expression language.

The authoritative check happens in R (r/engine/R/dsl.R walks the parsed syntax tree).
This module mirrors it closely enough to (a) extract variable dependencies for the
compiler and (b) reject unsafe or malformed expressions before they are stored -
including expressions proposed by an LLM.
"""
from __future__ import annotations

import re

ALLOWED_FUNCTIONS = {
    "c", "ifelse", "coalesce", "any_of", "all_of", "cases", "pmin", "pmax", "log", "log10",
    "exp", "sqrt", "abs", "is.na", "round", "as.numeric",
}
CONSTANTS = {"TRUE", "FALSE", "NA", "Inf", "NaN", "T", "F"}
_TOKEN = re.compile(
    r"""\s*(?:
        (?P<string>"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')
      | (?P<number>\d+\.?\d*(?:[eE][-+]?\d+)?|\.\d+(?:[eE][-+]?\d+)?)
      | (?P<op>%in%|<=|>=|==|!=|[-+*/^<>!&|(),=])
      | (?P<ident>[A-Za-z.][A-Za-z0-9._]*)
    )""",
    re.VERBOSE,
)


class ExpressionError(ValueError):
    pass


def tokenize(expr: str) -> list[tuple[str, str]]:
    pos = 0
    out: list[tuple[str, str]] = []
    expr = expr.strip()
    while pos < len(expr):
        m = _TOKEN.match(expr, pos)
        if not m or m.end() == pos:
            raise ExpressionError(f"Unexpected character {expr[pos]!r} at position {pos} in '{expr}'")
        kind = m.lastgroup
        out.append((kind, m.group(kind)))
        pos = m.end()
    return out


def identifiers(expr: str) -> list[str]:
    """Variable names referenced by an expression (function names and named-argument keys excluded)."""
    toks = tokenize(expr)
    names: list[str] = []
    for i, (kind, val) in enumerate(toks):
        if kind != "ident":
            continue
        nxt = toks[i + 1] if i + 1 < len(toks) else None
        if nxt and nxt == ("op", "("):
            continue
        if nxt and nxt == ("op", "=") and (i + 2 >= len(toks) or toks[i + 2] != ("op", "=")):
            continue  # named argument such as .default =
        if val in CONSTANTS:
            continue
        if val not in names:
            names.append(val)
    return names


def validate(expr: str, known_names: set[str] | None = None) -> list[str]:
    """Raise ExpressionError if the expression is unsafe/malformed; return its identifiers."""
    if not isinstance(expr, str) or not expr.strip():
        raise ExpressionError("Expression is empty")
    if len(expr) > 2000:
        raise ExpressionError("Expression too long")
    toks = tokenize(expr)
    depth = 0
    for i, (kind, val) in enumerate(toks):
        if val == "(":
            depth += 1
        elif val == ")":
            depth -= 1
            if depth < 0:
                raise ExpressionError(f"Unbalanced parentheses in '{expr}'")
        if kind == "ident":
            nxt = toks[i + 1] if i + 1 < len(toks) else None
            if nxt == ("op", "(") and val not in ALLOWED_FUNCTIONS:
                raise ExpressionError(f"Function '{val}' is not allowed (allowed: {', '.join(sorted(ALLOWED_FUNCTIONS))})")
        if kind == "op" and val == "=":
            prev = toks[i - 1] if i > 0 else None
            if not prev or prev[0] != "ident" or depth == 0:
                raise ExpressionError(f"Assignment is not allowed in '{expr}'")
    if depth != 0:
        raise ExpressionError(f"Unbalanced parentheses in '{expr}'")
    if re.search(r"<-|->|<<-|;|\{|\}|\[|\]|\$|@|`|::", expr):
        raise ExpressionError(f"Disallowed construct in '{expr}'")
    ids = identifiers(expr)
    if known_names is not None:
        unknown = [n for n in ids if n not in known_names]
        if unknown:
            raise ExpressionError(f"Unknown variable(s) {', '.join(unknown)} in '{expr}'")
    return ids
