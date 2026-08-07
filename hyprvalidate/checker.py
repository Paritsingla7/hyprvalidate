"""Row 4 in docs/PLAN.md: the actual Validator logic. Walks a parsed Lua
file (via hyprvalidate.luaast.reader) and cross-references every `hl.*`
symbol reference and every `hl.config({...})` key/value against the schema
(via hyprvalidate.schema.extractor) — the one thing none of the four
existing hyprlang->lua converters do (see docs/PLAN.md "Why").

Scope, stated explicitly rather than left implicit:
  - Symbol resolution walks HL.API -> namespace classes -> leaf `fun(...)`
    fields. Anything under `hl.plugin.*` beyond the one documented `load`
    field is accepted unconditionally - HL.PluginNamespace has a dynamic
    `[string] any` index signature for plugin-registered members (e.g.
    `hl.plugin.dynamic_cursors`) that isn't literal data the extractor can
    enumerate. See extractor.py's bracket-field regex and docs/PLAN.md.
  - Config-key/value checking only validates *scalar* values (string/
    number/boolean/nil) against the schema's type expression. A key whose
    schema type includes a table-shaped alternative (contains "{" or names
    an "HL." class, e.g. `string|HL.Gradient`) is accepted without
    structurally checking the table's own fields - that would require
    modelling every such class's shape, which is real work saved for a
    later pass if it turns out to matter. Documented, not silent.
  - A config value that's a variable reference, function call, or anything
    else that isn't a literal or a table constructor is accepted without
    comment - it can't be checked without evaluating the script.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from luaparser.astnodes import Call, Method, Table, Field as LuaField

from hyprvalidate.luaast import reader
from hyprvalidate.schema.extractor import Schema


class FindingKind(str, Enum):
    UNKNOWN_SYMBOL = "unknown_symbol"
    UNKNOWN_CONFIG_KEY = "unknown_config_key"
    TYPE_MISMATCH = "type_mismatch"


@dataclass
class Finding:
    kind: FindingKind
    line: int | None
    message: str


# Type-expression tokens that indicate "this alternative is a table/class
# shape, not a scalar" - used to decide whether to skip a mismatch rather
# than to model the shape.
def _has_table_alternative(type_expr: str) -> bool:
    return "{" in type_expr or "HL." in type_expr


_SCALAR_COMPAT = {
    "boolean": {"boolean"},
    "string": {"string"},
    "integer": {"number"},
    "number": {"number"},
}


def _scalar_kind_matches(kind: str, type_expr: str) -> bool:
    """True if a resolved scalar literal's kind satisfies a (possibly
    unioned) schema type expression, considering only the scalar
    alternatives in that expression."""
    for alt in (a.strip() for a in type_expr.split("|")):
        compat = _SCALAR_COMPAT.get(alt)
        if compat and kind in compat:
            return True
    return False


def resolve_symbol(schema: Schema, dotted_name: str) -> tuple[bool, str]:
    """Check a dotted `hl.*` symbol path against the schema. Returns
    (is_valid, reason). Names not starting with "hl" are out of scope and
    always considered valid (they're the user's own locals, not API)."""
    segments = dotted_name.split(".")
    if segments[0] != "hl":
        return True, "not an hl.* symbol, not checked"

    current_class = "HL.API"
    for i, seg in enumerate(segments[1:], start=1):
        cls = schema.classes.get(current_class)
        if cls is None:
            return False, f"internal: unknown schema class {current_class!r}"

        type_expr = cls.fields.get(seg)
        if type_expr is None:
            if current_class == "HL.PluginNamespace":
                # Dynamic index signature (`[string] any`) - plugins
                # register their own members at runtime. See module
                # docstring.
                return True, "hl.plugin.* member, accepted (dynamic)"
            return False, (
                f"'{seg}' is not a member of {current_class} "
                f"(resolving {dotted_name})"
            )

        if type_expr.startswith("fun("):
            remaining = segments[i + 1:]
            if remaining:
                return False, (
                    f"'{'.'.join(segments[:i+1])}' is a function, "
                    f"but '{'.'.join(remaining)}' is accessed on it"
                )
            return True, "resolved to a documented dispatcher/API function"

        if type_expr in schema.classes:
            current_class = type_expr
            continue

        # A plain-typed field (not a namespace, not a function) being
        # accessed further, e.g. treating a boolean config field as a
        # namespace - invalid.
        remaining = segments[i + 1:]
        if remaining:
            return False, (
                f"'{'.'.join(segments[:i+1])}' is type {type_expr!r}, "
                f"not a namespace - can't access '{'.'.join(remaining)}' on it"
            )
        return True, f"resolved to a field of type {type_expr!r}"

    return True, "resolved to a namespace (not called further)"


def _walk_config_table(
    schema: Schema, table: Table, prefix: str, line: int | None
) -> list[Finding]:
    findings: list[Finding] = []
    for field in table.fields:
        if field.key is None:
            continue  # array-style entry, not a config key - not our concern
        key_name = _field_key_name(field.key)
        if key_name is None:
            continue
        key_path = f"{prefix}.{key_name}" if prefix else key_name
        field_line = field.first_token.line if field.first_token else line

        if key_path == "plugin" or key_path.startswith("plugin."):
            # Plugin config is dynamically registered per-plugin at runtime
            # and structurally absent from config_value_types - same root
            # cause as HL.PluginNamespace's `[string] any` index signature
            # for symbol resolution (see module docstring). Not checkable
            # against the core schema; accepted without recursing further.
            continue

        is_leaf = key_path in schema.config_value_types
        is_container = any(
            k.startswith(key_path + ".") for k in schema.config_value_types
        )

        if not is_leaf and not is_container:
            findings.append(
                Finding(
                    FindingKind.UNKNOWN_CONFIG_KEY,
                    field_line,
                    f"'{key_path}' is not a known Hyprland config key",
                )
            )
            continue

        if isinstance(field.value, Table):
            if is_leaf:
                type_expr = schema.config_value_types[key_path]
                if not _has_table_alternative(type_expr):
                    findings.append(
                        Finding(
                            FindingKind.TYPE_MISMATCH,
                            field_line,
                            f"'{key_path}' expects {type_expr}, got a table",
                        )
                    )
                # else: table-shaped alternative allowed, e.g. HL.Gradient -
                # not checked further (see module docstring).
            else:
                findings.extend(
                    _walk_config_table(schema, field.value, key_path, field_line)
                )
            continue

        if is_leaf:
            literal = reader.resolve_literal(field.value)
            if literal is not None:
                type_expr = schema.config_value_types[key_path]
                if not _scalar_kind_matches(literal.kind, type_expr) and not _has_table_alternative(type_expr):
                    findings.append(
                        Finding(
                            FindingKind.TYPE_MISMATCH,
                            field_line,
                            f"'{key_path}' expects {type_expr}, got {literal.kind} ({literal.value!r})",
                        )
                    )
            # else: not a literal (variable/call) - can't check, accepted.
        # else (is_container but value isn't a Table): malformed but not
        # something we can classify further; skip rather than guess.

    return findings


def _field_key_name(key_expr) -> str | None:
    from luaparser.astnodes import Name, String

    if hasattr(key_expr, "id"):  # Name
        return key_expr.id
    if hasattr(key_expr, "s"):  # String (bracketed ["key"] = ... form)
        s = key_expr.s
        return s.decode() if isinstance(s, bytes) else s
    return None


def check(schema: Schema, tree) -> list[Finding]:
    """Run every check against an already-parsed Lua AST (from
    hyprvalidate.luaast.reader.parse/parse_file)."""
    findings: list[Finding] = []

    for node in reader.walk(tree):
        if not isinstance(node, (Call, Method)):
            continue
        dotted = reader.resolve_dotted_name(node.func)
        if dotted is None:
            continue
        line = node.first_token.line if node.first_token else None

        is_valid, reason = resolve_symbol(schema, dotted)
        if not is_valid:
            findings.append(Finding(FindingKind.UNKNOWN_SYMBOL, line, f"{dotted}: {reason}"))
            continue

        if dotted == "hl.config" and node.args and isinstance(node.args[0], Table):
            findings.extend(_walk_config_table(schema, node.args[0], "", line))

    return findings


def check_source(schema: Schema, source: str) -> list[Finding]:
    tree = reader.parse(source)
    return check(schema, tree)
