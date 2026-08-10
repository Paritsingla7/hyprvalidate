"""Tests for the hyprlang lexer (docs/CONVERTER_PLAN.md task 5.1)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from hyprvalidate.hyprlang.lexer import tokenize

REPO_ROOT = Path(__file__).parent.parent
REAL_CONF = REPO_ROOT.parent / "configs" / "hyprland.conf"


def test_tokenizes_the_real_config_end_to_end_no_crash():
    assert REAL_CONF.is_file(), f"expected the real config at {REAL_CONF}"
    source = REAL_CONF.read_text()
    tokens = tokenize(source)
    assert tokens[-1].type == "EOF"
    assert len(tokens) > 100


def test_real_config_has_sane_token_stream():
    source = REAL_CONF.read_text()
    tokens = tokenize(source)
    kinds = [t.type for t in tokens]
    assert kinds.count("BLOCK_OPEN") == kinds.count("BLOCK_CLOSE")
    assert "IDENT" in kinds
    assert "EQUALS" in kinds


def test_block_and_flat_directive():
    tokens = tokenize("general {\n    gaps_in = 5\n}\n")
    kinds = [t.type for t in tokens]
    assert kinds == [
        "IDENT", "BLOCK_OPEN", "NEWLINE",
        "IDENT", "EQUALS", "IDENT", "NEWLINE",
        "BLOCK_CLOSE", "NEWLINE", "EOF",
    ]


def test_string_token_strips_quotes():
    tokens = tokenize('exec-once = notify-send "hello"')
    strings = [t for t in tokens if t.type == "STRING"]
    assert strings[0].value == "hello"


def test_shell_expansion_is_its_own_token_not_dollar_plus_block():
    tokens = tokenize("$var = ${HOME}/bin")
    kinds = [t.type for t in tokens]
    assert "SHELL_EXP" in kinds
    shell = next(t for t in tokens if t.type == "SHELL_EXP")
    assert shell.value == "${HOME}"


def test_backslash_continuation_joins_lines_without_a_token():
    tokens = tokenize("exec-once = foo \\\n    bar\n")
    kinds = [t.type for t in tokens]
    assert "CONT" not in kinds
    idents = [t.value for t in tokens if t.type == "IDENT"]
    assert "foo" in idents and "bar" in idents


def test_comment_is_tokenized_separately():
    tokens = tokenize("gaps_in = 5 # a comment\n")
    comments = [t for t in tokens if t.type == "COMMENT"]
    assert comments[0].value == "# a comment"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
    print("all tests passed")
