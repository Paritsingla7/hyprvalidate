"""Tests for the luac gate.

Uses inline fixtures, not reference-tools/ (that dir is gitignored -
local-only research clones, not something this suite can depend on).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from hyprvalidate.luaast import luac_gate

VALID_SNIPPET = "hl.bind('SUPER + Q', hl.dsp.window.close())"

# The exact class of syntax error one of the real competitor tools produced:
# a colon used as a bare table key (`match:class = "..."`), which is not
# legal Lua - this is not a synthetic example, it's representative of a
# defect actually found in this project's research.
INVALID_SNIPPET = 'hl.config({ windowrule = { match:class = ".*" } })'


def test_valid_lua_passes():
    result = luac_gate.check_source(VALID_SNIPPET)
    assert result.ok
    assert result.message is None


def test_invalid_lua_fails_with_a_useful_message():
    result = luac_gate.check_source(INVALID_SNIPPET, chunk_name="badfile.lua")
    assert not result.ok
    assert result.message is not None
    assert "badfile.lua" in result.message
    assert "stdin" not in result.message  # chunk name should be swapped in


def test_check_file_reads_a_real_file(tmp_path):
    f = tmp_path / "ok.lua"
    f.write_text(VALID_SNIPPET)
    result = luac_gate.check_file(f)
    assert result.ok


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            import inspect
            if "tmp_path" in inspect.signature(fn).parameters:
                import tempfile
                with tempfile.TemporaryDirectory() as d:
                    fn(Path(d))
            else:
                fn()
            print(f"ok  {name}")
    print("all tests passed")
