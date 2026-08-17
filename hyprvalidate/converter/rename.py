"""Dispatcher/bind-flag rename tables.

hyprlang's old dispatcher names and single-letter bind flags don't exist in
the new Lua schema at all - there's nothing to derive this from, unlike the
block-dispatch and value-coercion logic elsewhere in this package. These
are hand-curated tables, verified against real evidence rather than guessed:

  - DISPATCHER_RENAME was built by reading Hyprland's actual current
    dispatcher implementation
    (src/config/lua/bindings/LuaBindingsDispatchers.cpp, function bodies for
    hlWindowMove/hlFocus etc, fetched and read directly) to confirm each old
    dispatcher's real new target - not copied from a competitor's table.
    hyprconf2lua's own DISPATCHER_MAP was read for comparison and is NOT a
    reliable source: cross-checking it against the schema is exactly what
    caught its bind-flag table's bugs below.
  - BIND_FLAG_RENAME was built from the archived Hyprland 0.54.0 wiki's
    "Bind flags" table (the last version documenting the pre-Lua hyprlang
    format, fetched directly - the current wiki only documents the new
    format) and independently cross-checked against every field HL
    .BindOptions actually declares in the installed stub.
    This caught two confirmed mistakes other tools made from memory/guessing:
      - `r` is "release", not "repeat" (that's `e`) - hyprconf2lua's own
        BIND_FLAGS_TO_OPTIONS maps r -> "repeating", which is wrong.
      - `m` ("mouse") has no corresponding HL.BindOptions field in the
        installed stub at all, despite the *current* Lua wiki's own
        examples using `{ mouse = true }` - a real docs/schema
        discrepancy, not something to paper over by inventing a field.
        This project hit the same trap once before, in its own earlier
        `mouse`->`drag` bug - `g` ("drag") is the flag that maps to
        the real `drag` field; `m` is deliberately left out here rather
        than mapped to a field that doesn't exist.

Three old flags are deliberately excluded from BIND_FLAG_RENAME because
they change the *shape* of the bind call, not just a boolean option, so a
letter->field table can't represent them honestly:
  - `d` ("has description") - old format inserts the description as a
    positional argument (`bindd = MOD, KEY, description, dispatcher,
    params`), it doesn't just toggle a flag.
  - `s` ("separate") - changes how MODS/KEY combine into multiple binds,
    not a per-bind option field at all (no matching HL.BindOptions field
    exists).
  - `m` ("mouse") - see above; the real replacement is the `g`/`drag`
    field plus using `hl.dsp.window.drag()`/`resize()` as the dispatcher,
    not a flag rename.
These surface through this package's low-confidence TODO emission (see
todo.py) instead of a silent (and wrong) guess.
"""
from __future__ import annotations

# Old dispatcher name -> new dotted hl.dsp.* target. Argument-shape
# translation (e.g. movetoworkspace's positional workspace arg becoming
# `{ workspace = ..., follow = false }`) is the mapper's job when it builds
# the call, not this table's - this only answers "which function".
DISPATCHER_RENAME: dict[str, str] = {
    "killactive": "hl.dsp.window.close",
    "togglefloating": "hl.dsp.window.float",
    "fullscreen": "hl.dsp.window.fullscreen",
    "pin": "hl.dsp.window.pin",
    "movefocus": "hl.dsp.focus",
    "workspace": "hl.dsp.focus",
    "movetoworkspace": "hl.dsp.window.move",
    "movetoworkspacesilent": "hl.dsp.window.move",
    "togglespecialworkspace": "hl.dsp.workspace.toggle_special",
    "movewindow": "hl.dsp.window.move",
    "resizewindow": "hl.dsp.window.resize",
    "exec": "hl.dsp.exec_cmd",
    "exit": "hl.dsp.exit",
    "submap": "hl.dsp.submap",
    "global": "hl.dsp.global",
}

# Old single-letter bind flag -> real HL.BindOptions field name.
BIND_FLAG_RENAME: dict[str, str] = {
    "l": "locked",
    "r": "release",
    "c": "click",
    "g": "drag",
    "o": "long_press",
    "e": "repeating",
    "n": "non_consuming",
    "t": "transparent",
    "i": "ignore_mods",
    "p": "dont_inhibit",
    "u": "submap_universal",
}

# Old flags that change the bind call's shape rather than toggling a field -
# see module docstring. Kept here (not just absent from the table above) so
# todo.py can recognize "this flag is known but unsupported" and say so,
# instead of silently treating it as "unknown flag, guess something".
SHAPE_CHANGING_BIND_FLAGS: dict[str, str] = {
    "d": "has description - inserts description as a positional argument, not a flag",
    "s": "separate - combines mods/keys into multiple binds, not a per-bind option",
    "m": "mouse - no matching HL.BindOptions field; use the 'g'/drag field and a mouse dispatcher instead",
}
