"""Schema-typed value coercion (docs/CONVERTER_PLAN.md task 7.2).

hyprlang values are always raw strings; the target schema says what type
they should become. This is the fix for the exact bug 3 of 4 competitor
tools made independently (`animations.enabled` emitted as the *string*
`"true"` instead of the boolean `true`) - coerce by looking up the target
field's real type, not by string-sniffing the value itself.

Only recognizes hyprlang's own literal boolean spellings ("true"/"false",
case-insensitive) - not "yes"/"on"/"1", which aren't confirmed hyprlang
literals and would be a guess. A value that doesn't confidently match any
scalar alternative in the schema's type expression is passed through as a
string unchanged; task 7.4 decides what to do with low-confidence cases,
this module never guesses to force a coercion.
"""
from __future__ import annotations

from typing import Any


def _try_bool(raw: str) -> bool | None:
    lowered = raw.strip().lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    return None


def _try_int(raw: str) -> int | None:
    try:
        return int(raw.strip())
    except ValueError:
        return None


def _try_number(raw: str) -> float | int | None:
    as_int = _try_int(raw)
    if as_int is not None:
        return as_int
    try:
        return float(raw.strip())
    except ValueError:
        return None


_COERCERS = {
    "boolean": _try_bool,
    "integer": _try_int,
    "number": _try_number,
}


def coerce_value(type_expr: str, raw: str) -> tuple[Any, bool]:
    """Returns (value, matched). `matched` is True when `raw` confidently
    parsed as one of `type_expr`'s scalar alternatives (in declared order -
    the first alternative that parses wins); False means no scalar
    alternative matched and `raw` was returned unchanged as a string."""
    for alt in (a.strip() for a in type_expr.split("|")):
        coercer = _COERCERS.get(alt)
        if coercer is None:
            continue
        value = coercer(raw)
        if value is not None:
            return value, True
    return raw, False
