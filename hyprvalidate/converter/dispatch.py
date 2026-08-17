"""Block-type dispatch.

Given a hyprlang block's name, decide whether it becomes a top-level
`hl.<name>(spec)` call or flattens into `hl.config({...})`'s dotted-key
space. Derived live from the schema (`HL.API`'s own fields) via the same
walk `resolve_symbol` already uses - not a hand-typed whitelist. hypr-migrate
had this exact idea (`KNOWN_SECTIONS`) and never wired it in; deriving it
live means it can't go stale or go unwired.

Only exact name matches are resolved here. A hyprlang directive whose old
name doesn't literally match its HL.API counterpart (e.g. `layerrule` vs.
`layer_rule`) is a rename, not a dispatch decision - that's rename.py's
hand-curated, schema-checked table, not this module's job.
"""
from __future__ import annotations

from hyprvalidate.checker import parse_fun_signature
from hyprvalidate.schema.extractor import Schema


def classify_block(schema: Schema, name: str) -> str | None:
    """Returns the dotted target ("hl.<name>") if `name` matches an HL.API
    field typed as a named `fun(spec: HL.SomeSpec)` signature - i.e. this
    hyprlang block should become that top-level call. Returns None if it
    should instead flatten into hl.config's dotted-key space (either no
    matching field exists at all, or the field isn't a spec-shaped call)."""
    api = schema.classes.get("HL.API")
    if api is None:
        return None

    type_expr = api.fields.get(name)
    if type_expr is None or not type_expr.startswith("fun("):
        return None

    sig = parse_fun_signature(type_expr)
    if sig is None:
        return None

    has_spec_param = any(p.type_expr in schema.classes for p in sig.params)
    return f"hl.{name}" if has_spec_param else None
