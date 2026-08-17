"""Low-confidence TODO emission.

Anything the mapper can't resolve with full confidence - an old dispatcher
name not in DISPATCHER_RENAME, a bind flag that changes the bind's shape
(or isn't recognized at all), a `source` directive (which references
another file the converter doesn't inline) - becomes a clearly-marked
comment in the output. Never a silent guess: this is the single biggest
differentiator from the four existing tools found by reading their code
earlier in this project (EIonTusk's does this reasonably, the other three
don't).

`luaparser`'s printer (confirmed by reading printers.py) has no visitor
for `astnodes.Comment` at all - it can't round-trip through the AST/writer
path the way real statements do. TODO notes are therefore plain text,
joined with rendered statement source by `render_program`, not AST nodes.
"""
from __future__ import annotations

from dataclasses import dataclass

from .rename import BIND_FLAG_RENAME, DISPATCHER_RENAME, SHAPE_CHANGING_BIND_FLAGS
from ..luaast.writer import chunk, to_source


@dataclass
class TodoNote:
    reason: str
    detail: str
    line: int | None


def format_todo(note: TodoNote) -> str:
    loc = f" (hyprland.conf line {note.line})" if note.line is not None else ""
    return f"-- TODO(hyprvalidate convert): {note.detail}{loc}"


def check_dispatcher(name: str, line: int | None = None) -> TodoNote | None:
    if name in DISPATCHER_RENAME:
        return None
    return TodoNote(
        "unrecognized_dispatcher",
        f"unrecognized old dispatcher '{name}' - no confident rename, convert manually",
        line,
    )


def check_bind_flag(flag: str, line: int | None = None) -> TodoNote | None:
    if flag in BIND_FLAG_RENAME:
        return None
    if flag in SHAPE_CHANGING_BIND_FLAGS:
        return TodoNote(
            "unsupported_bind_flag",
            f"bind flag '{flag}' ({SHAPE_CHANGING_BIND_FLAGS[flag]}) changes the "
            f"bind's shape - not auto-converted, convert manually",
            line,
        )
    return TodoNote(
        "unknown_bind_flag",
        f"unknown bind flag '{flag}' - not a recognized hyprlang flag, convert manually",
        line,
    )


def check_source_directive(path: str, line: int | None = None) -> TodoNote:
    return TodoNote(
        "source_directive",
        f"source = {path} - sourced files aren't inlined by the converter, "
        f"convert and include that file separately",
        line,
    )


def render_program(items) -> str:
    """`items` is an iterable of (node_or_none, note_or_none) pairs. A note
    renders as a comment line; a node renders as its own statement. Both
    may be present (a best-effort statement still flagged for review), or
    just one."""
    lines: list[str] = []
    for node, note in items:
        if note is not None:
            lines.append(format_todo(note))
        if node is not None:
            lines.append(to_source(chunk([node])))
    return "\n".join(lines)
