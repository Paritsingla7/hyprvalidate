"""The actual Validator logic. Walks a parsed Lua file (via
hyprvalidate.luaast.reader) and cross-references every `hl.*` symbol
reference and every `hl.config({...})` key/value against the schema (via
hyprvalidate.schema.extractor) — the one thing none of the four existing
hyprlang->lua converters do (see docs/COMPARISON.md).

Scope, stated explicitly rather than left implicit:
  - Symbol resolution walks HL.API -> namespace classes -> leaf `fun(...)`
    fields. Anything under `hl.plugin.*` beyond the one documented `load`
    field is accepted unconditionally - HL.PluginNamespace has a dynamic
    `[string] any` index signature for plugin-registered members (e.g.
    `hl.plugin.dynamic_cursors`) that isn't literal data the extractor can
    enumerate. See extractor.py's bracket-field regex.
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
  - Call-shape (arity) checking only applies to symbols whose stub type is
    a *named* signature (e.g. `hl.monitor` is `fun(spec: HL.MonitorSpec):
    nil`) - argument count is checked against required/optional params.
    Many stub functions are typed `fun(...): X` with no named params at
    all (the dsp.* dispatcher builders, `env`, `curve`, `animation`, etc) -
    those are never arity-checked, honestly, because there's nothing in
    the stub to check them against. Argument *type* checking (is arg 1
    actually a string) is not attempted - count only. Found via a real
    example: `hl.monitor(nil, {...})` in a GPT-fabricated test config
    resolves as a valid symbol (it is) but calls it with 2 args against a
    1-required-param signature - exactly what this closes.
  - Spec-table field checking: any call whose parameter is typed as a
    specific schema class (`hl.monitor`'s `spec: HL.MonitorSpec`,
    `hl.device`'s `HL.DeviceSpec`, `hl.gesture`'s `HL.GestureSpec`,
    `hl.bind`'s `opts?: HL.BindOptions`, `hl.window_rule`'s
    `HL.WindowRuleSpec`, `hl.permission`'s `HL.PermissionSpec`) has that
    table's keys checked against the class's actual fields, recursing when
    a field's own type is itself a class. Found via re-examining real test
    evidence: `hl.monitor({resolution = "preferred", ...})` passes with
    zero findings even after arity checking, because `resolution` isn't a
    real `HL.MonitorSpec` field (the real one is `mode`) and nothing
    checked spec-table *contents* before this.
    Deliberately excludes `hl.config` - its own param type (`HL.ConfigOpt`)
    is a *parallel*, differently-shaped representation of the same data (a
    nested class hierarchy vs. `config_value_types`'s flattened dotted
    map - verified they're not 1:1, e.g. `general.col` nests as its own
    sub-class in one but not the other) - unifying them would mean
    re-verifying every config section against a hierarchy that hasn't been
    checked yet, for no found benefit. `hl.config` keeps using its already
    -tested path; this is a second, narrower mechanism for everything else.
    Also excludes `hl.window_rule` specifically - found by this module's own
    test suite flooding false positives against the real config:
    `HL.WindowRuleSpec` only types 3 universal fields (enabled/match/name),
    unlike its siblings `HL.LayerRuleSpec` (13 fields) and
    `HL.WorkspaceRuleSpec` (17 fields) which are fully typed and DO get
    checked. Per-rule-type window fields (move/float/workspace/
    suppress_event/no_focus) are dynamically dispatched and deliberately
    absent from the stub - the same fact noted above about `hl.plugin.*`,
    rediscovered here for window rules specifically.
  - Uncalled-dispatcher-factory checking: any call argument whose declared
    param type includes `HL.Dispatcher` (currently `hl.bind`'s `dispatcher`
    param and `hl.dispatch`'s single param - found generically by scanning
    the schema, not hardcoded to those two names) is checked for being a
    bare `hl.dsp.*`-style symbol reference rather than an actual call, e.g.
    `hl.bind("SUPER + Q", hl.dsp.window.close)` (missing the trailing
    `()`). This is exactly the class of bug Hyprland's own issue #15871
    ("Improve lua error reporting") calls out - a factory reference passed
    where its *result* was meant, which type-checks under the stub's
    `HL.Dispatcher|function` union (a bare function reference IS a
    `function`) so nothing else here catches it. Detected by noticing the
    argument resolves (via `resolve_symbol`) to a function itself, rather
    than to a plain value or a genuine call/lambda.
  - Duplicate-bind checking: every `hl.bind(keys, ...)` call's `keys`
    argument is resolved - if it's a plain string literal, or a
    concatenation of only string literals (e.g. `"SUPER" .. " + Q"`) - and
    grouped; more than one bind resolving to the identical key combo is
    flagged. Also directly from #15871 ("repeating keys in a bind").
    Deliberately narrow: a `keys` expression built from a variable (the
    overwhelmingly common real-world pattern, e.g. `mainMod .. " + Q"`)
    can't be resolved without evaluating the script, so those binds are
    silently skipped rather than guessed at - same limitation
    `resolve_literal`/`_walk_config_table` already document for values
    that aren't literals.
  - Possible-missing-quotes checking: a config or spec-table value that's a
    *bare, single identifier* (`accel_profile = flat`, not `accel_profile =
    "flat"`) is flagged when that identifier is never assigned anywhere in
    the file (as a local, a global, a for-loop variable, or a function
    parameter) and the field's schema type includes `string`. An
    identifier that was never assigned would resolve to Lua's implicit
    `nil` global at runtime - i.e. this isn't a guess about intent, it's
    "this specific value cannot do anything other than silently become
    nil". This is the exact real-world bug in
    github.com/hyprwm/Hyprland#15727: a user's migrated `accel_profile =
    flat` silently discarded the accel profile and changed their mouse
    sensitivity, and was only found by a stranger reading their config.
    Deliberately does NOT fire for an identifier that *is* assigned
    somewhere (e.g. `local terminal = "foot"; ... = terminal`) - that's
    the legitimate variable-reference pattern already accepted elsewhere
    in this module, and this check reuses that same conservative
    "can't disprove it, don't flag it" stance. Scope tracking is
    deliberately flat (every assignment anywhere in the file counts as
    "defined", not just ones in an enclosing scope) - a false negative
    (missing a genuinely-undefined shadowed local) is an acceptable
    trade for never flagging a legitimately-scoped local as if it
    weren't defined.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from luaparser.astnodes import (
    Call, Invoke, Method, Table, Field as LuaField, Name,
    LocalAssign, Assign, Forin, Fornum,
    Function, LocalFunction, AnonymousFunction,
)

from hyprvalidate.luaast import reader
from hyprvalidate.schema.extractor import Schema


class FindingKind(str, Enum):
    UNKNOWN_SYMBOL = "unknown_symbol"
    UNKNOWN_CONFIG_KEY = "unknown_config_key"
    TYPE_MISMATCH = "type_mismatch"
    ARITY_MISMATCH = "arity_mismatch"
    UNKNOWN_SPEC_FIELD = "unknown_spec_field"
    UNCALLED_DISPATCHER = "uncalled_dispatcher"
    DUPLICATE_BIND = "duplicate_bind"
    POSSIBLE_MISSING_QUOTES = "possible_missing_quotes"


@dataclass
class FixEdit:
    """A single, unambiguous textual correction for a Finding: replace
    `source[start:end]` (character offsets, `end` exclusive) with
    `replacement`. Only attached to findings this module can correct with
    zero ambiguity about intent (see `fixer.py`) - most finding kinds never
    get one, and their `Finding.fix` stays None."""
    start: int
    end: int
    replacement: str


@dataclass
class Finding:
    kind: FindingKind
    line: int | None
    message: str
    fix: FixEdit | None = None


# Type-expression tokens that indicate "this alternative is a table/class
# shape, not a scalar" - used to decide whether to skip a mismatch rather
# than to model the shape. Found missing "table" (bare, e.g. `integer|table`,
# and LuaLS's generic form `table<string, string|boolean>`) by testing
# against two real, independent Hyprland Lua configs (Garuda Linux's
# distribution settings and the sea-shell project) - both use
# `hl.layer_rule({ match = { namespace = "..." } })`, which is exactly
# HL.LayerRuleSpec.match's real type, `table<string, string|boolean>`; this
# helper didn't recognize that as table-shaped at all, so every layer rule
# with a match table in the wild was a false positive here.
def _has_table_alternative(type_expr: str) -> bool:
    return "{" in type_expr or "HL." in type_expr or "table" in type_expr


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


def _type_expr_accepts_string(type_expr: str) -> bool:
    return "string" in (a.strip() for a in type_expr.split("|"))


# Globals provided by the Hyprland Lua runtime itself, not by anything a
# config file assigns - a bare reference to one of these is never "missing
# quotes", it's a real (if oddly-typed) value. Currently just the API root;
# extend here if the runtime grows more.
_RUNTIME_GLOBALS = {"hl"}


def _collect_defined_names(tree) -> set[str]:
    """Every identifier assigned anywhere in the file - as a local, a
    global, a for-loop variable, or a function parameter - flattened into
    one set with no scope structure. Used by the missing-quotes check: an
    identifier NOT in this set can only ever resolve to Lua's implicit
    `nil` global at runtime, so a bare reference to it in a string-typed
    field is a directly demonstrable bug, not a guess. Deliberately flat
    (ignores actual scoping) - see module docstring for why that's the
    right trade-off here."""
    names: set[str] = set(_RUNTIME_GLOBALS)
    for node in reader.walk(tree):
        if isinstance(node, (LocalAssign, Assign, Forin)):
            names.update(t.id for t in node.targets if isinstance(t, Name))
        elif isinstance(node, Fornum):
            if isinstance(node.target, Name):
                names.add(node.target.id)
        elif isinstance(node, (Function, LocalFunction, AnonymousFunction, Method)):
            names.update(a.id for a in node.args if isinstance(a, Name))
            name_node = getattr(node, "name", None)
            if isinstance(name_node, Name):
                names.add(name_node.id)
    return names


@dataclass
class Param:
    name: str
    type_expr: str
    optional: bool


@dataclass
class FunctionSignature:
    params: list[Param]
    has_vararg: bool  # a bare "..." entry - unlimited/unchecked trailing args


def _split_top_level(s: str, sep: str) -> list[str]:
    """Split on `sep`, but only at bracket depth 0 - so a param type like
    `table<string, string|number>` doesn't get split on its inner comma."""
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for ch in s:
        if ch in "({<":
            depth += 1
        elif ch in ")}>":
            depth -= 1
        if ch == sep and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    parts.append("".join(current))
    return parts


def parse_fun_signature(type_expr: str) -> FunctionSignature | None:
    """Parse a LuaLS `fun(...)` type expression's parameter list. Returns
    None if `type_expr` isn't a function type at all. Handles a param type
    that's itself a nested `fun(...)` (e.g. `hl.on`'s `cb: fun(...)` arg) by
    tracking bracket depth rather than splitting on the first close-paren."""
    open_idx = type_expr.find("(")
    if not type_expr.startswith("fun(") or open_idx == -1:
        return None

    depth = 0
    end = None
    for j in range(open_idx, len(type_expr)):
        c = type_expr[j]
        if c in "({<":
            depth += 1
        elif c in ")}>":
            depth -= 1
            if depth == 0:
                end = j
                break
    if end is None:
        return None

    param_str = type_expr[open_idx + 1:end].strip()
    if not param_str:
        return FunctionSignature(params=[], has_vararg=False)

    params: list[Param] = []
    has_vararg = False
    for tok in (t.strip() for t in _split_top_level(param_str, ",")):
        if not tok:
            continue
        if tok == "...":
            has_vararg = True
            continue
        if ":" in tok:
            name_part, type_part = tok.split(":", 1)
            name_part, type_part = name_part.strip(), type_part.strip()
        else:
            name_part, type_part = tok, "any"  # untyped bare param, not seen in practice
        optional = name_part.endswith("?")
        name = name_part[:-1] if optional else name_part
        params.append(Param(name=name, type_expr=type_part, optional=optional))
    return FunctionSignature(params=params, has_vararg=has_vararg)


def resolve_symbol(schema: Schema, dotted_name: str) -> tuple[bool, str, str | None]:
    """Check a dotted `hl.*` symbol path against the schema. Returns
    (is_valid, reason, signature_type_expr). `signature_type_expr` is the
    resolved function's raw `fun(...)` type string when this is a valid,
    fully-resolved call target - None otherwise (not a call target, or
    invalid). Names not starting with "hl" are out of scope and always
    considered valid (they're the user's own locals, not API)."""
    segments = dotted_name.split(".")
    if segments[0] != "hl":
        return True, "not an hl.* symbol, not checked", None

    current_class = "HL.API"
    for i, seg in enumerate(segments[1:], start=1):
        cls = schema.classes.get(current_class)
        if cls is None:
            return False, f"internal: unknown schema class {current_class!r}", None

        type_expr = cls.fields.get(seg)
        if type_expr is None:
            if current_class == "HL.PluginNamespace":
                # Dynamic index signature (`[string] any`) - plugins
                # register their own members at runtime. See module
                # docstring.
                return True, "hl.plugin.* member, accepted (dynamic)", None
            return False, (
                f"'{seg}' is not a member of {current_class} "
                f"(resolving {dotted_name})"
            ), None

        if type_expr.startswith("fun("):
            remaining = segments[i + 1:]
            if remaining:
                return False, (
                    f"'{'.'.join(segments[:i+1])}' is a function, "
                    f"but '{'.'.join(remaining)}' is accessed on it"
                ), None
            return True, "resolved to a documented dispatcher/API function", type_expr

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
            ), None
        return True, f"resolved to a field of type {type_expr!r}", None

    return True, "resolved to a namespace (not called further)", None


def _missing_quotes_finding(
    key_or_field_name: str, value: object, type_expr: str, line: int | None,
    defined_names: set[str],
) -> Finding | None:
    if not (isinstance(value, Name) and _type_expr_accepts_string(type_expr)):
        return None
    if value.id in defined_names:
        return None
    fix = None
    if value.first_token is not None:
        # A bare Name is always a single token and always a valid Lua
        # identifier (that's what let it parse as a Name at all) - no
        # escaping needed to wrap it in quotes.
        fix = FixEdit(
            start=value.first_token.start,
            end=value.first_token.stop + 1,
            replacement=f'"{value.id}"',
        )
    return Finding(
        FindingKind.POSSIBLE_MISSING_QUOTES, line,
        f"'{key_or_field_name}' is set to the bare identifier '{value.id}', "
        f"which isn't defined anywhere in this file and would evaluate to "
        f"nil - did you mean the string \"{value.id}\"?",
        fix=fix,
    )


def _walk_config_table(
    schema: Schema, table: Table, prefix: str, line: int | None,
    defined_names: set[str],
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
                    _walk_config_table(schema, field.value, key_path, field_line, defined_names)
                )
            continue

        if is_leaf:
            type_expr = schema.config_value_types[key_path]
            literal = reader.resolve_literal(field.value)
            if literal is not None:
                if not _scalar_kind_matches(literal.kind, type_expr) and not _has_table_alternative(type_expr):
                    findings.append(
                        Finding(
                            FindingKind.TYPE_MISMATCH,
                            field_line,
                            f"'{key_path}' expects {type_expr}, got {literal.kind} ({literal.value!r})",
                        )
                    )
            else:
                finding = _missing_quotes_finding(key_path, field.value, type_expr, field_line, defined_names)
                if finding is not None:
                    findings.append(finding)
                # else: not a literal and not a flaggable bare identifier
                # (variable/call/defined-name) - can't check, accepted.
        # else (is_container but value isn't a Table): malformed but not
        # something we can classify further; skip rather than guess.

    return findings


def _resolve_static_string(expr) -> str | None:
    """Resolve an expression to a plain string if it's a string literal, or
    a `Concat` (Lua `..`) of only string literals - e.g. `"SUPER" .. " + Q"`.
    Returns None for anything else, notably a concat involving a variable
    (`mainMod .. " + Q"`) - can't be resolved without evaluating the script,
    the same limitation `reader.resolve_literal` documents for values in
    general. Lives here rather than in `reader` because `resolve_literal`'s
    contract is explicitly scalars-only; this is a narrower, checker-local
    need (duplicate-bind detection)."""
    from luaparser.astnodes import Concat

    literal = reader.resolve_literal(expr)
    if literal is not None:
        return literal.value if literal.kind == "string" else None
    if isinstance(expr, Concat):
        left = _resolve_static_string(expr.left)
        right = _resolve_static_string(expr.right)
        if left is not None and right is not None:
            return left + right
    return None


def _field_key_name(key_expr) -> str | None:
    from luaparser.astnodes import Name, String

    if hasattr(key_expr, "id"):  # Name
        return key_expr.id
    if hasattr(key_expr, "s"):  # String (bracketed ["key"] = ... form)
        s = key_expr.s
        return s.decode() if isinstance(s, bytes) else s
    return None


def _check_spec_table(
    schema: Schema, table: Table, class_name: str, line: int | None,
    defined_names: set[str],
) -> list[Finding]:
    """Check a table's keys/values against a schema class's own fields
    (e.g. HL.MonitorSpec) - the spec-table mechanism, distinct from
    _walk_config_table's dotted-path check (hl.config only). See module
    docstring for why these stay separate rather than unified."""
    findings: list[Finding] = []
    cls = schema.classes.get(class_name)
    if cls is None:
        return findings  # shouldn't happen if class_name came from the schema itself

    for field in table.fields:
        if field.key is None:
            continue
        key_name = _field_key_name(field.key)
        if key_name is None:
            continue
        field_line = field.first_token.line if field.first_token else line

        type_expr = cls.fields.get(key_name)
        if type_expr is None:
            findings.append(Finding(
                FindingKind.UNKNOWN_SPEC_FIELD, field_line,
                f"'{key_name}' is not a field of {class_name}",
            ))
            continue

        if isinstance(field.value, Table):
            if type_expr in schema.classes:
                findings.extend(_check_spec_table(schema, field.value, type_expr, field_line, defined_names))
            elif not _has_table_alternative(type_expr):
                findings.append(Finding(
                    FindingKind.TYPE_MISMATCH, field_line,
                    f"'{key_name}' on {class_name} expects {type_expr}, got a table",
                ))
            continue

        literal = reader.resolve_literal(field.value)
        if literal is not None:
            if not _scalar_kind_matches(literal.kind, type_expr) and not _has_table_alternative(type_expr):
                findings.append(Finding(
                    FindingKind.TYPE_MISMATCH, field_line,
                    f"'{key_name}' on {class_name} expects {type_expr}, got {literal.kind} ({literal.value!r})",
                ))
        else:
            # Not a literal - either a flaggable bare identifier (see
            # _missing_quotes_finding) or a genuine variable/call, which
            # can't be checked further and is accepted, same as
            # _walk_config_table's documented behavior.
            finding = _missing_quotes_finding(key_name, field.value, type_expr, field_line, defined_names)
            if finding is not None:
                findings.append(finding)

    return findings


def check(schema: Schema, tree) -> list[Finding]:
    """Run every check against an already-parsed Lua AST (from
    hyprvalidate.luaast.reader.parse/parse_file)."""
    findings: list[Finding] = []
    bind_key_lines: dict[str, list[int | None]] = {}
    defined_names = _collect_defined_names(tree)

    for node in reader.walk(tree):
        # NB: `Method` (a `function T:method() end` *definition*) has no
        # `.func` - it's not a call at all. `Invoke` (an `obj:bar()` *call*)
        # is what belongs here; Hyprland's own API is exclusively dot-style
        # (`hl.bind(...)`) so an Invoke's bare method name never resolves
        # as `hl.*` and is harmlessly skipped below, same as any other
        # foreign call - the only thing that matters is not crashing on it.
        if not isinstance(node, (Call, Invoke)):
            continue
        dotted = reader.resolve_dotted_name(node.func)
        if dotted is None:
            continue
        line = node.first_token.line if node.first_token else None

        if dotted == "hl.bind" and node.args:
            keys = _resolve_static_string(node.args[0])
            if keys is not None:
                bind_key_lines.setdefault(keys, []).append(line)

        is_valid, reason, sig_type_expr = resolve_symbol(schema, dotted)
        if not is_valid:
            findings.append(Finding(FindingKind.UNKNOWN_SYMBOL, line, f"{dotted}: {reason}"))
            continue

        if sig_type_expr is not None:
            sig = parse_fun_signature(sig_type_expr)
            if sig is not None:
                for idx, param in enumerate(sig.params):
                    if "HL.Dispatcher" not in param.type_expr or idx >= len(node.args):
                        continue
                    arg_dotted = reader.resolve_dotted_name(node.args[idx])
                    if arg_dotted is None:
                        continue
                    arg_valid, _reason, arg_sig = resolve_symbol(schema, arg_dotted)
                    if arg_valid and arg_sig is not None:
                        fix = None
                        arg_node = node.args[idx]
                        if arg_node.last_token is not None:
                            # Insert (not replace) right after the reference's
                            # last token - `()` is the minimal correction that
                            # makes this a call at all. If the dispatcher also
                            # needs arguments, the re-check after applying
                            # fixes will surface that as a fresh
                            # ARITY_MISMATCH - a different, honest problem,
                            # not something to guess at here.
                            insert_at = arg_node.last_token.stop + 1
                            fix = FixEdit(start=insert_at, end=insert_at, replacement="()")
                        findings.append(Finding(
                            FindingKind.UNCALLED_DISPATCHER, line,
                            f"{dotted}: argument {idx + 1} ('{arg_dotted}') is a "
                            f"dispatcher factory reference, not a call - did you "
                            f"mean '{arg_dotted}(...)'?",
                            fix=fix,
                        ))
            if sig is not None and not sig.has_vararg:
                n_args = len(node.args)
                min_args = sum(1 for p in sig.params if not p.optional)
                max_args = len(sig.params)
                if n_args < min_args:
                    findings.append(Finding(
                        FindingKind.ARITY_MISMATCH, line,
                        f"{dotted}: expects at least {min_args} argument(s), got {n_args}",
                    ))
                elif n_args > max_args:
                    findings.append(Finding(
                        FindingKind.ARITY_MISMATCH, line,
                        f"{dotted}: expects at most {max_args} argument(s), got {n_args}",
                    ))

                # Check spec-table arguments against their own schema
                # class, for every function except hl.config (its own
                # already-tested dotted-path mechanism, see module
                # docstring) and hl.window_rule specifically - found by
                # this check's own test suite flooding false positives on
                # the real config: HL.WindowRuleSpec only types 3
                # universal fields (enabled/match/name), unlike its
                # siblings HL.LayerRuleSpec (13 fields) and
                # HL.WorkspaceRuleSpec (17 fields) which are fully typed.
                # Per-rule-type fields (move/float/workspace/suppress_event/
                # no_focus) are dynamically dispatched and deliberately not
                # in the stub at all - the same fact already noted above
                # about hl.plugin.*, re-discovered the hard way here when
                # generalizing.
                if dotted not in ("hl.config", "hl.window_rule"):
                    for idx, param in enumerate(sig.params):
                        if param.type_expr in schema.classes and idx < len(node.args):
                            arg = node.args[idx]
                            if isinstance(arg, Table):
                                findings.extend(
                                    _check_spec_table(schema, arg, param.type_expr, line, defined_names)
                                )

        if dotted == "hl.config" and node.args and isinstance(node.args[0], Table):
            findings.extend(_walk_config_table(schema, node.args[0], "", line, defined_names))

    for keys, lines in bind_key_lines.items():
        if len(lines) < 2:
            continue
        for this_line in lines:
            others = ", ".join(str(l) for l in lines if l != this_line)
            findings.append(Finding(
                FindingKind.DUPLICATE_BIND, this_line,
                f"'{keys}' is bound more than once (also at line(s) {others})",
            ))

    return findings


def check_source(schema: Schema, source: str) -> list[Finding]:
    tree = reader.parse(source)
    return check(schema, tree)
