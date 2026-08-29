"""Phase 2 of schema-diff: given a `diff.SchemaDiff` and a real parsed
config, report only the subset of what changed that the config actually
uses - not "353 things exist now," but "you use 2 of the 11 things that
changed."

This is what makes a schema diff a usable product rather than noise:
Hyprland's API is large and the diff between any two versions touches a lot
of surface most configs never go near. Cross-referencing against what a
specific file actually references is the whole point.

Three kinds of usage are collected, each schema-independent except the
third:
  - config keys used in `hl.config({...})` blocks (dotted paths, same
    key-path logic `checker._walk_config_table` uses for validation - this
    module has its own copy because collecting "what's used" and checking
    "is it valid" are different shapes, even though they walk the same
    tree)
  - every dotted `hl.*` symbol a Call/Invoke actually targets
  - spec-table field names used inside a call whose parameter resolves (via
    the CURRENT schema - the one the config is actually written against
    today, not the target of the diff) to a known schema class, e.g.
    `hl.monitor({ mode = ... })` -> fields used on `HL.MonitorSpec`.
    Reuses `checker.resolve_symbol`/`checker.parse_fun_signature` rather
    than re-deriving signature resolution.

Every reported item is phrased as "this changed in the schema, and your
config uses it" - never "this will break". See `diff.py`'s module
docstring for why: the schema doesn't always accurately reflect real
runtime behavior at every point in time, in both directions.

Known, deliberate gap: this only sees fields *written* into a literal
table constructor (a spec table you build and pass in, e.g.
`hl.monitor({ mode = ... })`) - it does NOT see fields *read* off a
runtime object handed to a callback, e.g. `win.class` inside
`hl.on("window.opened", function(win) ... end)`. That second pattern is
exactly the shape of the real HL.Window `over_fullscreen` regression this
whole feature was scoped around - and it's invisible here by construction,
because knowing `win`'s type requires tracing which event name the
callback is registered for and what payload type that event carries,
which is real type-flow inference this module doesn't attempt. Config-key
usage and constructed-spec-table usage (HL.MonitorSpec, HL.PermissionSpec,
HL.BindOptions, etc.) are what's actually covered; anything read off a
callback parameter is not. Documented here rather than silently
overclaiming coverage.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from luaparser.astnodes import Call, Invoke, Table

from hyprvalidate.luaast import reader
from hyprvalidate.schema.extractor import Schema
from hyprvalidate.schema.diff import SchemaDiff, PossibleRename, ConfigKeyTypeChange, FieldTypeChange
from hyprvalidate.checker import resolve_symbol, parse_fun_signature


@dataclass
class UsedSymbols:
    config_keys: set[str] = field(default_factory=set)
    dotted_calls: set[str] = field(default_factory=set)
    # class name -> set of field names used in a spec-table argument of that class
    spec_table_fields: dict[str, set[str]] = field(default_factory=dict)


def _field_key_name(key_expr) -> str | None:
    from luaparser.astnodes import Name, String

    if hasattr(key_expr, "id"):
        return key_expr.id
    if hasattr(key_expr, "s"):
        s = key_expr.s
        return s.decode() if isinstance(s, bytes) else s
    return None


def _collect_config_keys(table: Table, prefix: str, out: set[str]) -> None:
    for f in table.fields:
        if f.key is None:
            continue
        key_name = _field_key_name(f.key)
        if key_name is None:
            continue
        key_path = f"{prefix}.{key_name}" if prefix else key_name
        out.add(key_path)
        if isinstance(f.value, Table):
            _collect_config_keys(f.value, key_path, out)


def _collect_spec_table_fields(table: Table, out: set[str]) -> None:
    for f in table.fields:
        if f.key is None:
            continue
        key_name = _field_key_name(f.key)
        if key_name is not None:
            out.add(key_name)


def find_used_symbols(schema: Schema, tree) -> UsedSymbols:
    """Walk a parsed config once and collect everything it references that
    a schema diff could possibly be relevant to."""
    used = UsedSymbols()

    for node in reader.walk(tree):
        if not isinstance(node, (Call, Invoke)):
            continue
        dotted = reader.resolve_dotted_name(node.func)
        if dotted is None:
            continue
        used.dotted_calls.add(dotted)

        if dotted == "hl.config" and node.args and isinstance(node.args[0], Table):
            _collect_config_keys(node.args[0], "", used.config_keys)
            continue

        is_valid, _reason, sig_type_expr = resolve_symbol(schema, dotted)
        if not is_valid or sig_type_expr is None:
            continue
        sig = parse_fun_signature(sig_type_expr)
        if sig is None:
            continue
        for idx, param in enumerate(sig.params):
            if param.type_expr not in schema.classes or idx >= len(node.args):
                continue
            arg = node.args[idx]
            if isinstance(arg, Table):
                fields_used = used.spec_table_fields.setdefault(param.type_expr, set())
                _collect_spec_table_fields(arg, fields_used)

    return used


@dataclass
class AffectedConfigKey:
    key: str
    kind: str  # "removed" | "type_changed" | "possible_rename"
    detail: str


@dataclass
class AffectedClassField:
    class_name: str
    field: str
    kind: str  # "removed" | "type_changed" | "possible_rename"
    detail: str


@dataclass
class AffectedClass:
    class_name: str
    used_via: set[str]  # dotted call(s) that resolve into this now-removed class


@dataclass
class ImpactReport:
    affected_config_keys: list[AffectedConfigKey] = field(default_factory=list)
    affected_class_fields: list[AffectedClassField] = field(default_factory=list)
    affected_classes: list[AffectedClass] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.affected_config_keys or self.affected_class_fields or self.affected_classes)


def _resolve_containing_class(schema: Schema, dotted_name: str) -> tuple[str, str] | None:
    """Same traversal `checker.resolve_symbol` does, but returns
    (containing_class_name, leaf_field_name) instead of validity - e.g.
    "hl.dsp.window.close" -> ("HL.DspWindowNamespace", "close"). Returns
    None for anything that doesn't resolve to a class field at all (not an
    hl.* symbol, or doesn't fully resolve)."""
    segments = dotted_name.split(".")
    if segments[0] != "hl" or len(segments) < 2:
        return None

    current_class = "HL.API"
    for seg in segments[1:-1]:
        cls = schema.classes.get(current_class)
        if cls is None:
            return None
        type_expr = cls.fields.get(seg)
        if type_expr is None or type_expr not in schema.classes:
            return None
        current_class = type_expr

    return current_class, segments[-1]


def compute_impact(schema: Schema, diff: SchemaDiff, used: UsedSymbols) -> ImpactReport:
    """Cross-reference a SchemaDiff against what a config actually uses.
    `schema` is the CURRENT schema (the one `used` was collected against) -
    needed to resolve which class a dotted call's field belongs to."""
    report = ImpactReport()

    for key in sorted(used.config_keys):
        rename = next((r for r in diff.config_key_possible_renames if r.old_name == key), None)
        if rename is not None:
            # A rename guess already states the "no longer exists" fact -
            # reporting the plain removal too would just say the same thing
            # twice, not add honesty.
            report.affected_config_keys.append(AffectedConfigKey(
                key=key, kind="possible_rename",
                detail=f"'{key}' no longer exists - possibly renamed to "
                       f"'{rename.new_name}' (heuristic guess, not confirmed - "
                       f"check the Hyprland changelog for the target version)",
            ))
        elif key in diff.config_keys_removed:
            report.affected_config_keys.append(AffectedConfigKey(
                key=key, kind="removed",
                detail=f"'{key}' no longer exists in the target schema "
                       f"(was: {diff.config_keys_removed[key]})",
            ))
        for change in diff.config_keys_type_changed:
            if change.key == key:
                report.affected_config_keys.append(AffectedConfigKey(
                    key=key, kind="type_changed",
                    detail=f"'{key}' changes from {change.old_type} to "
                           f"{change.new_type} in the target schema",
                ))

    for class_name, fields_used in used.spec_table_fields.items():
        class_diff = diff.class_diffs.get(class_name)
        if class_diff is None:
            continue
        for used_field in sorted(fields_used):
            rename = next((r for r in class_diff.possible_renames if r.old_name == used_field), None)
            if rename is not None:
                report.affected_class_fields.append(AffectedClassField(
                    class_name=class_name, field=used_field, kind="possible_rename",
                    detail=f"'{used_field}' on {class_name} no longer exists - "
                           f"possibly renamed to '{rename.new_name}' (heuristic "
                           f"guess, not confirmed)",
                ))
            elif used_field in class_diff.fields_removed:
                report.affected_class_fields.append(AffectedClassField(
                    class_name=class_name, field=used_field, kind="removed",
                    detail=f"'{used_field}' on {class_name} no longer exists in "
                           f"the target schema (was: {class_diff.fields_removed[used_field]})",
                ))
            for change in class_diff.fields_type_changed:
                if change.name == used_field:
                    report.affected_class_fields.append(AffectedClassField(
                        class_name=class_name, field=used_field, kind="type_changed",
                        detail=f"'{used_field}' on {class_name} changes from "
                               f"{change.old_type} to {change.new_type} in the target schema",
                    ))

    classes_removed = set(diff.classes_removed)
    if classes_removed:
        by_class: dict[str, set[str]] = {}
        for dotted in sorted(used.dotted_calls):
            resolved = _resolve_containing_class(schema, dotted)
            if resolved is None:
                continue
            containing_class, _leaf = resolved
            if containing_class in classes_removed:
                by_class.setdefault(containing_class, set()).add(dotted)
        for class_name, via in sorted(by_class.items()):
            report.affected_classes.append(AffectedClass(class_name=class_name, used_via=via))

    return report
