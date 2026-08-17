"""Parse an existing Lua config file into an AST, and provide the two
schema-agnostic utilities the schema-driven checker (a separate component)
needs to walk it: resolving a dotted-member-access chain to a plain string
(e.g. `hl.dsp.window.close` from a Name/Index chain), and resolving a Lua
literal expression to a plain Python value + type-kind.

Deliberately does NOT know about the schema, and does not decide what's
valid — that's the checker's job. This module only answers "what does this
piece of syntax say", not "is that allowed".

Built on `luaparser` (MIT, ANTLR-generated Lua grammar) rather than a
hand-rolled parser - verified against this project's own real config
(hyprland-lua/keybinds.lua: 101 Call/Method nodes, lambda-bodied binds,
a Fornum loop) before adopting it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from luaparser import ast as _luaast
from luaparser.astnodes import (
    Chunk,
    Node,
    Name,
    Index,
    String,
    Number,
    TrueExpr,
    FalseExpr,
    Nil,
)


class LuaSyntaxError(Exception):
    """Raised when the input isn't valid Lua at all."""


def parse(source: str) -> Chunk:
    try:
        return _luaast.parse(source)
    except Exception as exc:  # luaparser raises its own ANTLR-wrapped errors
        raise LuaSyntaxError(str(exc)) from exc


def parse_file(path: str | Path) -> Chunk:
    return parse(Path(path).read_text())


def resolve_dotted_name(expr: Node | None) -> str | None:
    """Turn a Name/Index chain into a dotted string, e.g. the AST for
    `hl.dsp.window.close` -> "hl.dsp.window.close". Returns None for
    anything that isn't a plain dotted-access chain (e.g. `t[i]` with a
    non-Name index, a call, a literal).
    """
    if isinstance(expr, Name):
        return expr.id
    if isinstance(expr, Index):
        base = resolve_dotted_name(expr.value)
        if base is None:
            return None
        if isinstance(expr.idx, Name):
            return f"{base}.{expr.idx.id}"
        if isinstance(expr.idx, String):
            return f"{base}.{expr.idx.s.decode() if isinstance(expr.idx.s, bytes) else expr.idx.s}"
        return None
    return None


@dataclass
class LiteralValue:
    value: Any
    kind: str  # "string" | "number" | "boolean" | "nil"


def resolve_literal(expr: Node | None) -> LiteralValue | None:
    """Resolve a scalar Lua literal expression to a plain Python value.
    Returns None for anything that isn't a scalar literal (tables, calls,
    variable references, concatenation expressions, etc) - those need
    schema-aware handling the checker does, not this module.
    """
    if isinstance(expr, String):
        s = expr.s
        return LiteralValue(s.decode() if isinstance(s, bytes) else s, "string")
    if isinstance(expr, Number):
        return LiteralValue(expr.n, "number")
    if isinstance(expr, TrueExpr):
        return LiteralValue(True, "boolean")
    if isinstance(expr, FalseExpr):
        return LiteralValue(False, "boolean")
    if isinstance(expr, Nil):
        return LiteralValue(None, "nil")
    return None


def walk(tree: Node):
    """Re-exported for callers that just need to iterate every node -
    thin passthrough so callers only import from this module, not
    luaparser directly."""
    return _luaast.walk(tree)
