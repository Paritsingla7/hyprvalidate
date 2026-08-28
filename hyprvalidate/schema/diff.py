"""Structural diff between two Schema snapshots - e.g. Hyprland v0.55.4's
schema vs v0.56.0's - so a config can eventually be warned about upstream
changes before it silently breaks on an update, not just validated against
whichever one version it's pointed at today.

Two honesty constraints shape everything here, both found empirically while
scoping this (see the real Hyprland corpus in `schemas/` and the diffs
between consecutive versions):

1. A schema diff is NOT a behavior diff. Hyprland's generated stub has
   lagged its own C++ implementation at least twice in this project's
   short history so far - `HL.PermissionSpec.allow` was wrong from the
   version it first shipped in (the real parser already required `mode`),
   and six `HL.API` methods sat as untyped `fun(...): any` for two point
   releases despite already working. That means: a reported change might
   just be the stub catching up to already-true reality (not a real
   behavior change), and the absence of a reported change is NOT proof
   nothing changed (a change the stub generator doesn't cover is invisible
   here by construction). Nothing in this module's output should ever be
   phrased as "this WILL break" - only "this changed in the schema between
   these two versions."

2. Renames are structurally invisible, and this module refuses to guess
   past what a name + matching type can confidently establish. The real
   HL.Window case (`over_fullscreen` -> `allowed_over_fullscreen`,
   Hyprland v0.55.4 -> v0.56.0) is genuinely undetectable by exact type
   match: `over_fullscreen` was Hyprland's *only* removed boolean field in
   that diff, but v0.56.0 added *two* new booleans to that same class
   (`allowed_over_fullscreen` and `pin_fullscreened`) - so type alone can't
   disambiguate which one it became. `possible_renames` below only fires
   on a clean 1:1 match (exactly one removed name of a given normalized
   type, exactly one added name of that same type) - it deliberately does
   NOT fall back to name-similarity heuristics (e.g. "over_fullscreen" is
   a substring of both "allowed_over_fullscreen" AND "fullscreen_handler",
   which would just trade a silent gap for a confident-sounding wrong
   guess). When it can't confidently tell, this reports the plain
   removed/added facts and stops there - same "documented, not silent,
   never guessed" stance as the rest of this project.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from hyprvalidate.schema.extractor import Schema


def normalize_type_expr(type_expr: str) -> str:
    """Two type expressions that are the same set of alternatives in a
    different order (`string|HL.Gradient` vs `HL.Gradient|string`) are the
    same type, not a change - Hyprland's own stub generator doesn't
    guarantee a stable union order across versions. Splits only at
    bracket-depth 0 so a nested type like `table<string, string|number>`
    doesn't get split on its inner `|`."""
    return "|".join(sorted(_split_union_top_level(type_expr)))


def _split_union_top_level(type_expr: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for ch in type_expr:
        if ch in "({<":
            depth += 1
        elif ch in ")}>":
            depth -= 1
        if ch == "|" and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    parts.append("".join(current).strip())
    return parts


def _types_equal(a: str, b: str) -> bool:
    return normalize_type_expr(a) == normalize_type_expr(b)


@dataclass
class PossibleRename:
    """A guess, not a fact - see module docstring. Only ever produced from
    a clean 1:1 match: exactly one removed name and exactly one added name
    share this (normalized) type within the same class or config-key
    namespace. Never used to drive an auto-fix."""
    old_name: str
    new_name: str
    type_expr: str


@dataclass
class FieldTypeChange:
    name: str
    old_type: str
    new_type: str


@dataclass
class ClassDiff:
    name: str
    fields_added: dict[str, str] = field(default_factory=dict)
    fields_removed: dict[str, str] = field(default_factory=dict)
    fields_type_changed: list[FieldTypeChange] = field(default_factory=list)
    possible_renames: list[PossibleRename] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.fields_added or self.fields_removed or self.fields_type_changed)


@dataclass
class AliasDiff:
    name: str
    literals_added: list[str] = field(default_factory=list)
    literals_removed: list[str] = field(default_factory=list)
    type_expr_change: tuple[str, str] | None = None  # (old, new), only when both are alias-form

    def is_empty(self) -> bool:
        return not (self.literals_added or self.literals_removed or self.type_expr_change)


@dataclass
class ConfigKeyTypeChange:
    key: str
    old_type: str
    new_type: str


@dataclass
class SchemaDiff:
    classes_added: list[str] = field(default_factory=list)
    classes_removed: list[str] = field(default_factory=list)
    class_diffs: dict[str, ClassDiff] = field(default_factory=dict)  # only non-empty ones

    aliases_added: list[str] = field(default_factory=list)
    aliases_removed: list[str] = field(default_factory=list)
    alias_diffs: dict[str, AliasDiff] = field(default_factory=dict)  # only non-empty ones

    config_keys_added: dict[str, str] = field(default_factory=dict)
    config_keys_removed: dict[str, str] = field(default_factory=dict)
    config_keys_type_changed: list[ConfigKeyTypeChange] = field(default_factory=list)
    config_key_possible_renames: list[PossibleRename] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (
            self.classes_added or self.classes_removed or self.class_diffs
            or self.aliases_added or self.aliases_removed or self.alias_diffs
            or self.config_keys_added or self.config_keys_removed
            or self.config_keys_type_changed
        )


def _find_possible_renames(
    removed: dict[str, str], added: dict[str, str]
) -> list[PossibleRename]:
    """Group removed/added names by normalized type; a type bucket with
    exactly one name on each side is a confident 1:1 rename candidate.
    Any bucket with more than one name on either side is left alone - see
    module docstring for why this doesn't fall back to guessing further."""
    removed_by_type: dict[str, list[str]] = {}
    for name, type_expr in removed.items():
        removed_by_type.setdefault(normalize_type_expr(type_expr), []).append(name)

    added_by_type: dict[str, list[str]] = {}
    for name, type_expr in added.items():
        added_by_type.setdefault(normalize_type_expr(type_expr), []).append(name)

    renames = []
    for norm_type, removed_names in removed_by_type.items():
        added_names = added_by_type.get(norm_type, [])
        if len(removed_names) == 1 and len(added_names) == 1:
            renames.append(PossibleRename(
                old_name=removed_names[0], new_name=added_names[0], type_expr=norm_type,
            ))
    return renames


def _diff_fields(old_fields: dict[str, str], new_fields: dict[str, str]) -> tuple[
    dict[str, str], dict[str, str], list[FieldTypeChange], list[PossibleRename]
]:
    added = {k: v for k, v in new_fields.items() if k not in old_fields}
    removed = {k: v for k, v in old_fields.items() if k not in new_fields}
    type_changed = [
        FieldTypeChange(name=k, old_type=old_fields[k], new_type=new_fields[k])
        for k in old_fields.keys() & new_fields.keys()
        if not _types_equal(old_fields[k], new_fields[k])
    ]
    renames = _find_possible_renames(removed, added)
    return added, removed, type_changed, renames


def diff_schemas(old: Schema, new: Schema) -> SchemaDiff:
    """Compare two Schema snapshots - typically two Hyprland versions'
    extracted schemas, `old` being the earlier one. Order matters only for
    which side "added"/"removed" describe; the comparison itself is
    symmetric otherwise."""
    diff = SchemaDiff()

    diff.classes_added = sorted(new.classes.keys() - old.classes.keys())
    diff.classes_removed = sorted(old.classes.keys() - new.classes.keys())
    for name in sorted(old.classes.keys() & new.classes.keys()):
        added, removed, type_changed, renames = _diff_fields(
            old.classes[name].fields, new.classes[name].fields
        )
        if added or removed or type_changed:
            diff.class_diffs[name] = ClassDiff(
                name=name, fields_added=added, fields_removed=removed,
                fields_type_changed=type_changed, possible_renames=renames,
            )

    diff.aliases_added = sorted(new.aliases.keys() - old.aliases.keys())
    diff.aliases_removed = sorted(old.aliases.keys() - new.aliases.keys())
    for name in sorted(old.aliases.keys() & new.aliases.keys()):
        old_alias, new_alias = old.aliases[name], new.aliases[name]
        literals_added = sorted(set(new_alias.literals) - set(old_alias.literals))
        literals_removed = sorted(set(old_alias.literals) - set(new_alias.literals))
        type_expr_change = None
        if old_alias.type_expr is not None and new_alias.type_expr is not None:
            if not _types_equal(old_alias.type_expr, new_alias.type_expr):
                type_expr_change = (old_alias.type_expr, new_alias.type_expr)
        alias_diff = AliasDiff(
            name=name, literals_added=literals_added,
            literals_removed=literals_removed, type_expr_change=type_expr_change,
        )
        if not alias_diff.is_empty():
            diff.alias_diffs[name] = alias_diff

    ckt_added, ckt_removed, ckt_type_changed, ckt_renames = _diff_fields(
        old.config_value_types, new.config_value_types
    )
    diff.config_keys_added = ckt_added
    diff.config_keys_removed = ckt_removed
    diff.config_keys_type_changed = [
        ConfigKeyTypeChange(key=c.name, old_type=c.old_type, new_type=c.new_type)
        for c in ckt_type_changed
    ]
    diff.config_key_possible_renames = ckt_renames

    return diff
