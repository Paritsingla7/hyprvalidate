"""Schema-driven mapper: hyprlang AST -> Lua source (docs/PLAN.md row 7,
docs/CONVERTER_PLAN.md tasks 7.1-7.5 assembled).

Ties together dispatch.py (7.1), coerce.py (7.2), rename.py (7.3), and
todo.py (7.4) into `convert(schema, hyprlang_file) -> str`.

Scope, stated explicitly rather than left implicit: this maps the
constructs the project's own real hyprland.conf actually uses (config
sections, device blocks, gesture/monitor directives, the bind family, exec/
exit/submap/global dispatchers, window rules, source). Dispatcher and
directive shapes not exercised by that file (e.g. `permission`, most
`layerrule`/`workspace_rule` forms, `fullscreen` with an explicit mode) are
not modeled here - anything the mapper doesn't recognize becomes a
low-confidence TODO (task 7.4), never a guess.

Two argument-shape facts came from reading Hyprland's actual current
dispatcher implementation directly (LuaBindingsDispatchers.cpp), not
guessed:
  - `hl.dsp.focus({direction = ...})` replaces both old `movefocus` (a
    direction letter/word) and old `workspace` (a workspace selector, via
    `{workspace = ...}`) - both go through the same entry point,
    distinguished only by which table key is set.
  - old `movewindow`/`resizewindow` used via `bindm` (a mouse bind with no
    dispatcher params) map to `hl.dsp.window.drag()`/`resize()` specifically
    - NOT `hl.dsp.window.move()` - because a bindm mouse-drag bind has a
      fundamentally different shape from a keyboard direction bind, even
      though both dispatchers share the old name `movewindow`.
"""
from __future__ import annotations

from ..hyprlang.parser import Block, Directive, HyprlangFile, VariableAssign, WindowRule
from ..luaast.writer import anon_function, hlcall
from dataclasses import dataclass

from ..checker import _has_table_alternative, _scalar_kind_matches
from .coerce import coerce_value
from .dispatch import classify_block
from .rename import BIND_FLAG_RENAME, DISPATCHER_RENAME
from .todo import TodoNote, check_bind_flag, check_dispatcher, check_source_directive, render_program

# Module names for --split output. Chosen to match the hand-migration that
# already exists for this project's own config (configs/hyprland-lua/*.lua),
# which is the only worked example of "correctly modularized" available.
M_ENTRY = "hyprland"        # the require()-ing entry point
M_PLUGINS = "plugins"
M_MONITORS = "monitors"
M_DEVICES = "devices"
M_AUTOSTART = "autostart"
M_ENV = "env"
M_PERMISSIONS = "permissions"
M_APPEARANCE = "appearance"
M_INPUT = "input"
M_KEYBINDS = "keybinds"
M_WINDOWRULES = "windowrules"
M_OTHER = "other"

# hyprlang directive key -> module. `bind*` is handled by prefix, not here.
_DIRECTIVE_MODULE = {
    "monitor": M_MONITORS,
    "gesture": M_INPUT,
    "exec-once": M_AUTOSTART,
    "exec": M_AUTOSTART,
    "env": M_ENV,
    "envd": M_ENV,
    "permission": M_PERMISSIONS,
    "windowrule": M_WINDOWRULES,
    "windowrulev2": M_WINDOWRULES,
    "layerrule": "layerrules",
    "workspace": "workspacerules",
    "source": M_ENTRY,
}

# hyprlang config-section name -> module, for the sections where grouping
# several under one file matches how people actually think about them
# (everything visual together, etc). Any section NOT listed here gets its
# own file named after the section - deterministic, and avoids inventing a
# taxonomy for sections this project has no worked example of.
_CONFIG_SECTION_MODULE = {
    "general": M_APPEARANCE,
    "decoration": M_APPEARANCE,
    "animations": M_APPEARANCE,
    "master": M_APPEARANCE,
    "dwindle": M_APPEARANCE,
    "misc": M_APPEARANCE,
    "group": M_APPEARANCE,
    "cursor": M_APPEARANCE,
    "input": M_INPUT,
    "gestures": M_INPUT,
    "binds": M_KEYBINDS,
    "ecosystem": M_PERMISSIONS,
    "plugin": M_PLUGINS,
}

# A block that becomes a top-level hl.X(spec) call (per dispatch.py) -> module.
_SPEC_BLOCK_MODULE = {
    "device": M_DEVICES,
    "monitor": M_MONITORS,
    "gesture": M_INPUT,
    "permission": M_PERMISSIONS,
    "window_rule": M_WINDOWRULES,
    "layer_rule": "layerrules",
    "workspace_rule": "workspacerules",
}


@dataclass
class ConvertedItem:
    """One emitted statement, tagged for module assignment. `line` is the
    original hyprlang source line, used to order modules in the entry file
    so the output reads in the same order as the input did."""
    node: object | None
    note: TodoNote | None
    module: str
    line: int | None


def _directive_module(key: str) -> str:
    if key.startswith("bind"):
        return M_KEYBINDS
    return _DIRECTIVE_MODULE.get(key, M_OTHER)


def _config_section_module(section: str) -> str:
    return _CONFIG_SECTION_MODULE.get(section, section)


def _spec_block_module(block_name: str) -> str:
    return _SPEC_BLOCK_MODULE.get(block_name, block_name)


def _coerce_or_note(type_expr: str, raw: str, notes: list[TodoNote], key_name: str, line: int | None):
    """Wraps coerce_value with the same self-check task 7.5 requires of the
    whole converter: if the raw value can't be confidently coerced AND a
    plain string wouldn't satisfy the schema type either, that's a real
    mismatch (e.g. the real config's own joke value,
    `animations { enabled = yes, please :) }`, isn't a valid boolean) -
    flag it instead of silently emitting a value the validator would flag."""
    value, matched = coerce_value(type_expr, raw)
    if not matched and not _scalar_kind_matches("string", type_expr) and not _has_table_alternative(type_expr):
        notes.append(TodoNote(
            "value_type_mismatch",
            f"'{key_name}' = '{raw}' doesn't confidently match its expected type ({type_expr})",
            line,
        ))
    return value


def _best_effort_scalar(raw: str):
    lowered = raw.strip().lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    return raw


def _build_keys_string(mods: str, keysym: str) -> str:
    parts = [m for m in mods.split() if m] if mods else []
    parts.append(keysym)
    return " + ".join(parts)


def _build_dispatcher_call(name: str, rest: list[str], line: int | None):
    """Returns (node_or_none, note_or_none) for a dispatcher call built from
    its old name and remaining (already comma-split) args."""
    if name not in DISPATCHER_RENAME:
        return None, check_dispatcher(name, line)

    target = DISPATCHER_RENAME[name]

    if name in ("killactive", "togglefloating", "pin", "exit"):
        return hlcall(target), None

    if name == "exec":
        if not rest:
            return None, TodoNote("malformed_exec", "exec dispatcher with no command", line)
        return hlcall(target, ", ".join(rest)), None

    if name in ("submap", "global"):
        if not rest:
            return None, TodoNote(f"malformed_{name}", f"{name} dispatcher with no argument", line)
        return hlcall(target, rest[0]), None

    if name == "movefocus":
        if not rest:
            return None, TodoNote("malformed_movefocus", "movefocus with no direction", line)
        return hlcall(target, {"direction": rest[0]}), None

    if name == "workspace":
        if not rest:
            return None, TodoNote("malformed_workspace", "workspace dispatcher with no id", line)
        return hlcall(target, {"workspace": rest[0]}), None

    if name in ("movetoworkspace", "movetoworkspacesilent"):
        if not rest:
            return None, TodoNote(f"malformed_{name}", f"{name} with no workspace", line)
        follow = name == "movetoworkspace"
        return hlcall(target, {"workspace": rest[0], "follow": follow}), None

    if name == "togglespecialworkspace":
        return hlcall(target, rest[0] if rest else ""), None

    if name in ("movewindow", "resizewindow"):
        # The bindm (mouse-drag) zero-arg case is handled by the caller
        # before reaching here - this is the keyboard-direction form.
        if len(rest) == 1:
            return hlcall(target, {"direction": rest[0]}), None
        return None, TodoNote(
            f"unmodeled_{name}_shape",
            f"{name} with args {rest!r} isn't a modeled shape (only bare bindm or a single direction are)",
            line,
        )

    return None, TodoNote("unmodeled_dispatcher", f"'{name}' has no modeled argument shape yet", line)


def _combine_notes(notes: list[TodoNote]) -> TodoNote | None:
    if not notes:
        return None
    return TodoNote(notes[0].reason, "; ".join(n.detail for n in notes), notes[0].line)


def _build_bind(directive: Directive) -> tuple:
    flags = directive.key[len("bind"):]
    args = directive.args
    line = directive.line

    if len(args) < 3:
        return None, TodoNote("malformed_bind", f"bind directive has fewer than 3 fields: {args!r}", line)

    mods, keysym, dispatcher_name, *rest = args
    keys_str = _build_keys_string(mods, keysym)

    mouse_drag_special_case = (
        flags == "m" and dispatcher_name in ("movewindow", "resizewindow") and not rest
    )
    if mouse_drag_special_case:
        target = "hl.dsp.window.drag" if dispatcher_name == "movewindow" else "hl.dsp.window.resize"
        dispatcher_node, dispatcher_note = hlcall(target), None
    else:
        dispatcher_node, dispatcher_note = _build_dispatcher_call(dispatcher_name, rest, line)

    if dispatcher_node is None:
        return None, dispatcher_note

    notes = [dispatcher_note] if dispatcher_note else []
    bind_opts = {}
    if not mouse_drag_special_case:
        for f in flags:
            note = check_bind_flag(f, line)
            if note is not None:
                notes.append(note)
            else:
                bind_opts[BIND_FLAG_RENAME[f]] = True

    call_args = [keys_str, dispatcher_node]
    if bind_opts:
        call_args.append(bind_opts)
    bind_call = hlcall("hl.bind", *call_args)

    return bind_call, _combine_notes(notes)


def _set_nested(result: dict, dotted_key: str, value) -> None:
    """A hyprlang key can itself contain dots (`col.active_border = ...`
    is one real directive with a literal dot in its name) - the Lua schema
    represents that as a nested table (`col = { active_border = ... }`),
    not a flat key with a dot in it (which also isn't a valid bare Lua
    identifier). Found running the converter against the real config."""
    parts = dotted_key.split(".")
    node = result
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = value


def _flatten_config_block(schema, block: Block, prefix: str, notes: list[TodoNote]) -> dict:
    result = {}
    for d in block.directives:
        key_path = f"{prefix}.{d.key}" if prefix else d.key
        type_expr = schema.config_value_types.get(key_path)
        if type_expr is None:
            notes.append(TodoNote(
                "unknown_config_key",
                f"'{key_path}' is not a known Hyprland config key",
                d.line,
            ))
            continue
        raw = d.args[0] if d.args else ""
        value = _coerce_or_note(type_expr, raw, notes, key_path, d.line)
        _set_nested(result, d.key, value)
    for sub in block.blocks:
        sub_path = f"{prefix}.{sub.name}" if prefix else sub.name
        result[sub.name] = _flatten_config_block(schema, sub, sub_path, notes)
    return result


def _build_spec_call(schema, target: str, class_name: str, block: Block, notes: list[TodoNote]) -> tuple:
    cls = schema.classes.get(class_name)
    spec = {}
    for d in block.directives:
        type_expr = cls.fields.get(d.key) if cls else None
        raw = d.args[0] if d.args else ""
        if type_expr is None:
            notes.append(TodoNote(
                "unknown_spec_field",
                f"'{d.key}' is not a field of {class_name}",
                d.line,
            ))
            spec[d.key] = raw
            continue
        value = _coerce_or_note(type_expr, raw, notes, d.key, d.line)
        spec[d.key] = value
    return hlcall(target, spec), notes


def _build_window_rule(rule: WindowRule):
    payload = {}
    if "name" in rule.properties:
        payload["name"] = rule.properties["name"]
    if rule.match:
        payload["match"] = {k: _best_effort_scalar(v) for k, v in rule.match.items()}
    for key, value in rule.properties.items():
        if key == "name":
            continue
        payload[key] = _best_effort_scalar(value)
    return hlcall("hl.window_rule", payload)


def _build_monitor(directive: Directive):
    fields = ("output", "mode", "position", "scale")
    if len(directive.args) != len(fields):
        return None, TodoNote(
            "unmodeled_monitor_shape",
            f"monitor directive with {len(directive.args)} fields isn't the modeled "
            f"output,mode,position,scale shape",
            directive.line,
        )
    spec = dict(zip(fields, directive.args))
    return hlcall("hl.monitor", spec), None


def _build_gesture(directive: Directive):
    fields = ("fingers", "direction", "action")
    if len(directive.args) < len(fields):
        return None, TodoNote(
            "unmodeled_gesture_shape",
            f"gesture directive with {len(directive.args)} fields isn't the modeled "
            f"fingers,direction,action shape",
            directive.line,
        )
    fingers, direction, action = directive.args[:3]
    try:
        fingers_val = int(fingers)
    except ValueError:
        fingers_val = fingers
    spec = {"fingers": fingers_val, "direction": direction, "action": action}
    return hlcall("hl.gesture", spec), None


def _convert_items(schema, hf: HyprlangFile) -> list[ConvertedItem]:
    """Shared conversion pass behind both `convert` (flat) and
    `convert_split` (modular). Yields one ConvertedItem per emitted
    statement, tagged with its target module and original source line, in
    source order."""
    items: list[ConvertedItem] = []

    # exec-once has no direct call-shaped equivalent - the hand-migration
    # this project already did (see configs/hyprland-lua/autostart.lua)
    # consolidates every exec-once into one hl.on("hyprland.start", fn)
    # registration rather than one call per line, so the converter matches
    # that instead of emitting N duplicate registrations.
    exec_once_cmds = [
        d.args[0] for d in hf.statements
        if isinstance(d, Directive) and d.key == "exec-once" and d.args
    ]
    exec_once_emitted = False

    for stmt in hf.statements:
        if isinstance(stmt, VariableAssign):
            continue  # already inlined at parse time (row 5.2)

        if isinstance(stmt, WindowRule):
            items.append(ConvertedItem(_build_window_rule(stmt), None, M_WINDOWRULES, stmt.line))
            continue

        if isinstance(stmt, Directive):
            module = _directive_module(stmt.key)
            if stmt.key == "source":
                note = check_source_directive(stmt.args[0] if stmt.args else "", stmt.line)
                items.append(ConvertedItem(None, note, M_ENTRY, stmt.line))
            elif stmt.key == "exec-once":
                if not exec_once_emitted:
                    exec_once_emitted = True
                    fn = anon_function([hlcall("hl.exec_cmd", cmd) for cmd in exec_once_cmds])
                    items.append(ConvertedItem(
                        hlcall("hl.on", "hyprland.start", fn), None, module, stmt.line
                    ))
                # subsequent exec-once directives are already folded in above
            elif stmt.key == "env" and len(stmt.args) == 2:
                items.append(ConvertedItem(
                    hlcall("hl.env", stmt.args[0], stmt.args[1]), None, module, stmt.line
                ))
            elif stmt.key.startswith("bind"):
                node, note = _build_bind(stmt)
                items.append(ConvertedItem(node, note, module, stmt.line))
            elif stmt.key == "monitor":
                node, note = _build_monitor(stmt)
                items.append(ConvertedItem(node, note, module, stmt.line))
            elif stmt.key == "gesture":
                node, note = _build_gesture(stmt)
                items.append(ConvertedItem(node, note, module, stmt.line))
            else:
                items.append(ConvertedItem(None, TodoNote(
                    "unmodeled_directive",
                    f"'{stmt.key}' isn't a modeled top-level directive",
                    stmt.line,
                ), module, stmt.line))
            continue

        if isinstance(stmt, Block):
            if stmt.name == "plugin":
                # Plugin config is dynamically registered per-plugin at
                # runtime - structurally absent from the schema (same root
                # cause as HL.PluginNamespace's dynamic index signature,
                # see checker.py). There's nothing to flatten it against,
                # and its sub-block names (e.g. "dynamic-cursors") often
                # aren't even valid Lua identifiers. Flag for manual
                # conversion rather than emitting empty/invalid tables.
                items.append(ConvertedItem(None, TodoNote(
                    "plugin_config",
                    "plugin { ... } config is dynamically registered per-plugin - "
                    "not converted automatically, convert manually",
                    stmt.line,
                ), M_PLUGINS, stmt.line))
                continue

            target = classify_block(schema, stmt.name)
            notes: list[TodoNote] = []
            if target is not None:
                cls_field = schema.classes["HL.API"].fields[stmt.name]
                from ..checker import parse_fun_signature
                sig = parse_fun_signature(cls_field)
                class_name = next(p.type_expr for p in sig.params if p.type_expr in schema.classes)
                call, notes = _build_spec_call(schema, target, class_name, stmt, notes)
                module = _spec_block_module(stmt.name)
            else:
                inner = _flatten_config_block(schema, stmt, stmt.name, notes)
                call = hlcall("hl.config", {stmt.name: inner})
                module = _config_section_module(stmt.name)
            items.append(ConvertedItem(call, _combine_notes(notes), module, stmt.line))
            continue

    return items


def convert(schema, hf: HyprlangFile) -> str:
    """Converts a parsed hyprlang file (hyprvalidate.hyprlang.parser output)
    into Lua source text, using the schema to decide dispatch/coercion/
    validity rather than guessing. Anything not confidently resolved
    becomes a `-- TODO(hyprvalidate convert): ...` comment instead of
    silently wrong output."""
    items = _convert_items(schema, hf)
    return render_program([(i.node, i.note) for i in items])


_ENTRY_HEADER = """\
-- Generated by hyprvalidate convert --split.
--
-- Deployment note: require() resolves modules relative to the directory
-- this file lives in, so copy every .lua file here flat into
-- ~/.config/hypr/ (this file must stay named hyprland.lua there). Nesting
-- the modules one level deeper needs extra package.path setup.
--
-- Order below follows the original config's own order. Each require() runs
-- its module body immediately, so statements that depend on order (repeated
-- config keys, duplicate binds, window-rule precedence) keep the relative
-- order they had in the source file.
"""


def convert_split(schema, hf: HyprlangFile) -> dict[str, str]:
    """Convert into a set of modular files instead of one flat file.

    Returns {filename: lua_source}, always including the `hyprland.lua`
    entry point that require()s the rest. Modules with no statements
    produce no file.

    Why bucketing by module is safe despite reordering relative to the
    source file: statements are grouped by subsystem, and within a module
    source order is preserved exactly. The three things in hyprlang where
    order actually carries meaning - repeated config keys (last write wins,
    confirmed against Hyprland's own hlConfig implementation), duplicate
    binds on one key (all fire, in order), and window-rule precedence - are
    each confined to a single module by this mapping, so their relative
    order survives. Cross-module order is between independent subsystems.
    `tests/test_converter_split.py` asserts both halves of that claim
    mechanically rather than trusting this comment.
    """
    items = _convert_items(schema, hf)

    buckets: dict[str, list[ConvertedItem]] = {}
    for item in items:
        buckets.setdefault(item.module, []).append(item)

    entry_items = buckets.pop(M_ENTRY, [])

    # Modules appear in the entry file in the order their first statement
    # appeared in the original config, so reading top to bottom matches the
    # source. Ties (and missing line numbers) fall back to the name so the
    # output is deterministic.
    module_order = sorted(
        buckets, key=lambda m: (min((i.line or 0) for i in buckets[m]), m)
    )

    files: dict[str, str] = {}
    for module in module_order:
        body = render_program([(i.node, i.note) for i in buckets[module]])
        files[f"{module}.lua"] = body.rstrip("\n") + "\n"

    entry_parts = [_ENTRY_HEADER]
    if entry_items:
        entry_parts.append(
            render_program([(i.node, i.note) for i in entry_items]).rstrip("\n") + "\n"
        )
    entry_parts.append(
        "\n".join(f'require("{m}")' for m in module_order) + "\n" if module_order else ""
    )
    files[f"{M_ENTRY}.lua"] = "\n".join(p for p in entry_parts if p)

    return files
