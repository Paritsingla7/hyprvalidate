"""Tests for the hyprlang parser/AST (docs/CONVERTER_PLAN.md task 5.2)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from hyprvalidate.hyprlang.parser import (
    parse,
    parse_file,
    Directive,
    VariableAssign,
    Block,
    WindowRule,
)

REPO_ROOT = Path(__file__).parent.parent
REAL_CONF = REPO_ROOT.parent / "configs" / "hyprland.conf"


def _all_statements(statements):
    """Flatten top-level + nested-block statements for counting purposes."""
    out = []
    for s in statements:
        out.append(s)
        if isinstance(s, Block):
            out.extend(_all_statements(s.directives))
            out.extend(_all_statements(s.blocks))
    return out


def test_real_config_bind_count_matches_ground_truth():
    # ground truth: grep -cE '^\s*bind[a-z]*\s*=' configs/hyprland.conf
    hf = parse_file(REAL_CONF)
    flat = _all_statements(hf.statements)
    binds = [s for s in flat if isinstance(s, Directive) and s.key.startswith("bind")]
    assert len(binds) == 66


def test_real_config_monitor_count_matches_ground_truth():
    hf = parse_file(REAL_CONF)
    flat = _all_statements(hf.statements)
    monitors = [s for s in flat if isinstance(s, Directive) and s.key == "monitor"]
    assert len(monitors) == 1


def test_real_config_window_rule_count_matches_ground_truth():
    # ground truth: grep -cE '^\s*windowrule\s*\{' configs/hyprland.conf
    hf = parse_file(REAL_CONF)
    rules = [s for s in hf.statements if isinstance(s, WindowRule)]
    assert len(rules) == 11


def test_real_config_device_block_count_matches_ground_truth():
    hf = parse_file(REAL_CONF)
    devices = [s for s in hf.statements if isinstance(s, Block) and s.name == "device"]
    assert len(devices) == 4


def test_real_config_parses_without_crashing_and_has_variables():
    hf = parse_file(REAL_CONF)
    assert hf.variables["mainMod"] == "SUPER"
    assert hf.variables["terminal"] == "alacritty"


def test_variable_substitution_inlines_value():
    hf = parse("$mainMod = SUPER\nbind = $mainMod, T, exec, kitty\n")
    bind = next(s for s in hf.statements if isinstance(s, Directive))
    assert bind.args == ["SUPER", "T", "exec", "kitty"]


def test_variable_substitution_with_extra_modifier():
    hf = parse("$mainMod = SUPER\nbind = $mainMod CTRL, R, exec, foo\n")
    bind = next(s for s in hf.statements if isinstance(s, Directive))
    assert bind.args[0] == "SUPER CTRL"


def test_nested_blocks():
    hf = parse(
        "plugin {\n"
        "    dynamic-cursors {\n"
        "        enabled = true\n"
        "        shake {\n"
        "            threshold = 5.0\n"
        "        }\n"
        "    }\n"
        "}\n"
    )
    plugin = hf.statements[0]
    assert isinstance(plugin, Block) and plugin.name == "plugin"
    dc = plugin.blocks[0]
    assert dc.name == "dynamic-cursors"
    assert dc.directives[0].key == "enabled"
    shake = dc.blocks[0]
    assert shake.name == "shake"
    assert shake.directives[0].args == ["5.0"]


def test_block_form_window_rule():
    hf = parse(
        "windowrule {\n"
        "    name = suppress-maximize-events\n"
        "    match:class = .*\n"
        "    suppress_event = maximize\n"
        "}\n"
    )
    rule = hf.statements[0]
    assert isinstance(rule, WindowRule)
    assert rule.match == {"class": ".*"}
    assert rule.properties == {"name": "suppress-maximize-events", "suppress_event": "maximize"}


def test_one_line_window_rule_hits_the_same_node_type_as_block_form():
    """The exact defect this row exists to avoid (hypr2lua defect 3/4):
    one-line and block-form windowrule/windowrulev2 must produce the same
    AST node type, not two different representations."""
    hf = parse("windowrulev2 = float, class:^(kitty)$\n")
    rule = hf.statements[0]
    assert isinstance(rule, WindowRule)
    assert rule.properties == {"float": "true"}
    assert rule.match == {"class": "^(kitty)$"}


def test_one_line_window_rule_with_a_valued_property():
    hf = parse("windowrule = move 20 20, class:^(foo)$\n")
    rule = hf.statements[0]
    assert isinstance(rule, WindowRule)
    assert rule.properties == {"move": "20 20"}
    assert rule.match == {"class": "^(foo)$"}


def test_exec_once_directive():
    hf = parse("exec-once = mako\n")
    d = hf.statements[0]
    assert isinstance(d, Directive)
    assert d.key == "exec-once"
    assert d.args == ["mako"]


def test_plain_key_value_does_not_comma_split():
    """The exact bug found via the real config's own joke value: a plain
    key = value line keeps its whole remainder as one value, commas
    included - only specific multi-arg directives (bind/monitor/animation/
    bezier/gesture/layerrule/workspace/permission/env) comma-split."""
    hf = parse("animations {\n    enabled = yes, please :)\n}\n")
    block = hf.statements[0]
    d = block.directives[0]
    assert d.args == ["yes, please :)"]


def test_real_config_animations_enabled_is_not_comma_split():
    hf = parse_file(REAL_CONF)
    animations = next(s for s in hf.statements if isinstance(s, Block) and s.name == "animations")
    enabled = next(d for d in animations.directives if d.key == "enabled")
    assert enabled.args == ["yes, please :)"]


def test_bind_style_directive_still_comma_splits():
    hf = parse("$mainMod = SUPER\nbind = $mainMod, T, exec, kitty\n")
    d = hf.statements[1]
    assert d.args == ["SUPER", "T", "exec", "kitty"]


def test_source_directive():
    hf = parse("source = /home/x/noctalia-colors.conf\n")
    d = hf.statements[0]
    assert d.key == "source"
    assert d.args == ["/home/x/noctalia-colors.conf"]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
    print("all tests passed")
