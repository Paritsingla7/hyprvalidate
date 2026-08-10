"""Lua AST builder helpers (docs/PLAN.md row 6).

`luaparser` writes Lua too (`ast.to_lua_source`), so this doesn't need a
custom Lua AST - it's a thin layer over `luaparser.astnodes` that gets one
footgun right in one place instead of at every call site: `astnodes.String`
takes both a `str` value and an already-Lua-quoted `raw` field, and getting
`raw` wrong (e.g. passing the bare Python string) makes the output
round-trip incorrectly.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple, Union

from luaparser import ast as luaast
from luaparser.astnodes import (
    Call,
    Chunk,
    Block,
    Field,
    FalseExpr,
    Index,
    IndexNotation,
    Name,
    Nil,
    Node,
    Number,
    String,
    StringDelimiter,
    Table,
    TrueExpr,
)


def luastr(s: str) -> String:
    """`raw` is the escaped *contents* only - the printer (LuaOutputVisitor,
    confirmed by reading luaparser/printers.py) wraps it in the delimiter's
    quote characters itself. Passing an already-quoted `raw` double-quotes
    the output instead of round-tripping."""
    escaped = s.replace("\\", "\\\\").replace('"', '\\"')
    return String(s=s.encode("utf-8"), raw=escaped, delimiter=StringDelimiter.DOUBLE_QUOTE)


def luanum(n) -> Number:
    return Number(n)


def luabool(b: bool):
    return TrueExpr() if b else FalseExpr()


def luaname(name: str) -> Name:
    return Name(identifier=name)


def member(*parts: str) -> Node:
    """Build a dotted member-access chain: member("hl", "dsp", "window", "close")
    -> the AST for `hl.dsp.window.close`."""
    if not parts:
        raise ValueError("member() needs at least one part")
    node: Node = luaname(parts[0])
    for part in parts[1:]:
        node = Index(idx=luaname(part), value=node, notation=IndexNotation.DOT)
    return node


def _to_expr(value: Any) -> Node:
    if isinstance(value, Node):
        return value
    if isinstance(value, bool):
        return luabool(value)
    if isinstance(value, str):
        return luastr(value)
    if isinstance(value, (int, float)):
        return luanum(value)
    if value is None:
        return Nil()
    if isinstance(value, dict):
        return luatable(value)
    if isinstance(value, (list, tuple)):
        return luatable(value)
    raise TypeError(f"don't know how to build a Lua expression from {type(value)!r}")


def luatable(items: Union[Dict[str, Any], Iterable[Any], Iterable[Tuple[str, Any]]]) -> Table:
    """Build a Lua table. A dict (or an iterable of (key, value) pairs)
    becomes a record-style table `{ key = value, ... }`; any other
    iterable becomes an array-style table `{ value, value, ... }`."""
    fields: List[Field] = []
    if isinstance(items, dict):
        pairs = items.items()
    else:
        items = list(items)
        if items and isinstance(items[0], tuple) and len(items[0]) == 2:
            pairs = items
        else:
            pairs = None

    if pairs is not None:
        for key, value in pairs:
            fields.append(Field(key=luaname(key), value=_to_expr(value)))
    else:
        for value in items:
            fields.append(Field(key=None, value=_to_expr(value)))

    return Table(fields=fields)


def hlcall(dotted_name: str, *args: Any) -> Call:
    """Build a call to a dotted hl.* function: hlcall("hl.monitor", {...})."""
    func = member(*dotted_name.split("."))
    return Call(func=func, args=[_to_expr(a) for a in args])


def chunk(statements: List[Node]) -> Chunk:
    return Chunk(body=Block(body=statements))


def to_source(root: Node) -> str:
    return luaast.to_lua_source(root)
