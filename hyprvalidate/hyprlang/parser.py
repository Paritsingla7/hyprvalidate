"""Parser/AST for the old hyprlang .conf format.

Builds a small AST from the lexer's token stream: blocks, flat directives,
$variable assignment/substitution, and a single unified WindowRule node for
both `windowrule { ... }` (block form) and `windowrule = rule, selector`
(one-line form) - hypr2lua's defect 3/4 was routing these to different
handlers; here they always produce the same node type.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Union

from .lexer import Token, tokenize

WINDOW_RULE_NAMES = ("windowrule", "windowrulev2")

# Directive keys whose value is a comma-separated list of positional args in
# real hyprlang - everything else keeps its whole remainder as one value
# (commas included), since a plain `key = value` line is never split.
COMMA_LIST_KEYS = frozenset({
    "monitor", "animation", "bezier", "gesture", "layerrule", "workspace",
    "permission", "env",
})


def _is_comma_list_key(key: str) -> bool:
    return key in COMMA_LIST_KEYS or key.startswith("bind")


@dataclass
class Directive:
    key: str
    args: List[str]
    line: int


@dataclass
class VariableAssign:
    name: str
    value: str
    line: int


@dataclass
class Block:
    name: str
    directives: List[Directive] = field(default_factory=list)
    blocks: List["Block"] = field(default_factory=list)
    line: int = 0


@dataclass
class WindowRule:
    line: int
    match: Dict[str, str] = field(default_factory=dict)
    properties: Dict[str, str] = field(default_factory=dict)


Statement = Union[Directive, VariableAssign, Block, WindowRule]


@dataclass
class HyprlangFile:
    variables: Dict[str, str]
    statements: List[Statement]


class ParseError(Exception):
    def __init__(self, message: str, line: int):
        self.line = line
        super().__init__(f"L{line}: {message}")


class _Parser:
    def __init__(self, tokens: List[Token]):
        # Comments carry no structural meaning here - drop them, keep NEWLINE
        # as the statement terminator that was already alongside them.
        self.tokens = [t for t in tokens if t.type != "COMMENT"]
        self.pos = 0
        self.variables: Dict[str, str] = {}

    def _peek(self, offset: int = 0) -> Token:
        idx = self.pos + offset
        return self.tokens[idx] if idx < len(self.tokens) else self.tokens[-1]

    def _advance(self) -> Token:
        tok = self.tokens[self.pos]
        if tok.type != "EOF":
            self.pos += 1
        return tok

    def _skip_newlines(self) -> None:
        while self._peek().type == "NEWLINE":
            self._advance()

    def _substitute(self, text: str) -> str:
        if text.startswith("$") and text[1:] in self.variables:
            return self.variables[text[1:]]
        return text

    def _read_value_tokens_until_newline(self) -> List[Token]:
        value_tokens: List[Token] = []
        while self._peek().type not in ("NEWLINE", "EOF"):
            value_tokens.append(self._advance())
        return value_tokens

    def _tokens_to_args(self, value_tokens: List[Token], split_commas: bool = True) -> List[str]:
        """Join a value's tokens into $-substituted arg strings, comma-split
        only when `split_commas` is true. hyprlang only comma-splits for
        specific multi-arg directives (bind/monitor/animation/bezier/
        gesture/layerrule/workspace/permission/env, see COMMA_LIST_KEYS) -
        a plain `key = value` keeps its whole remainder as one value, commas
        included. Found via the real config's own joke value
        (`animations { enabled = yes, please :) }`), which a blanket comma
        split would wrongly cut into two args.

        Adjacency (no whitespace) is preserved without a space; a gap in the
        source (whitespace the lexer's SKIP rule discarded) becomes exactly
        one space. ponytail: STRING tokens' stripped quotes throw this off
        by 2 columns if something is glued directly onto a quoted string
        with zero whitespace - not a real shape in this project's configs,
        not worth tracking exact end-columns per token type for.
        """
        segments: List[List[Token]] = [[]]
        for tok in value_tokens:
            if split_commas and tok.type == "COMMA":
                segments.append([])
            else:
                segments[-1].append(tok)

        args: List[str] = []
        for seg in segments:
            piece = ""
            prev_end_col: Optional[int] = None
            pending_dollar = False
            for tok in seg:
                if tok.type == "DOLLAR":
                    pending_dollar = True
                    prev_end_col = tok.col + 1
                    continue
                gap = prev_end_col is not None and tok.col > prev_end_col
                if pending_dollar:
                    piece += self._substitute("$" + tok.value)
                    pending_dollar = False
                else:
                    if piece and gap:
                        piece += " "
                    piece += tok.value
                prev_end_col = tok.col + len(tok.value)
            args.append(piece.strip())
        return args

    def parse(self) -> HyprlangFile:
        statements = self._parse_statements()
        return HyprlangFile(variables=self.variables, statements=statements)

    def _parse_statements(self) -> List[Statement]:
        statements: List[Statement] = []
        while True:
            self._skip_newlines()
            tok = self._peek()
            if tok.type in ("EOF", "BLOCK_CLOSE"):
                break
            statements.append(self._parse_one_statement())
        return statements

    def _parse_one_statement(self) -> Statement:
        tok = self._peek()
        line = tok.line

        if tok.type == "DOLLAR":
            self._advance()
            name = self._advance().value
            self._expect("EQUALS", line)
            value_tokens = self._read_value_tokens_until_newline()
            value = self._tokens_to_args(value_tokens)[0] if value_tokens else ""
            self.variables[name] = value
            return VariableAssign(name=name, value=value, line=line)

        if tok.type != "IDENT":
            raise ParseError(f"expected a directive, block, or variable, got {tok.type}", line)

        key_parts = [self._advance().value]
        while self._peek().type in ("COLON", "DOT"):
            key_parts.append(self._advance().value)
            key_parts.append(self._advance().value)
        key = "".join(key_parts)

        nxt = self._peek()
        if nxt.type == "BLOCK_OPEN":
            self._advance()
            block = self._parse_block(key, line)
            if key in WINDOW_RULE_NAMES:
                return _block_to_window_rule(block)
            return block

        if nxt.type == "EQUALS":
            self._advance()
            value_tokens = self._read_value_tokens_until_newline()
            split_commas = key in WINDOW_RULE_NAMES or _is_comma_list_key(key)
            args = self._tokens_to_args(value_tokens, split_commas=split_commas)
            if key in WINDOW_RULE_NAMES:
                return _one_line_to_window_rule(args, line)
            return Directive(key=key, args=args, line=line)

        raise ParseError(f"expected '=' or '{{' after '{key}', got {nxt.type}", line)

    def _expect(self, token_type: str, line: int) -> Token:
        tok = self._peek()
        if tok.type != token_type:
            raise ParseError(f"expected {token_type}, got {tok.type}", line)
        return self._advance()

    def _parse_block(self, name: str, line: int) -> Block:
        block = Block(name=name, line=line)
        for stmt in self._parse_statements():
            if isinstance(stmt, Block):
                block.blocks.append(stmt)
            elif isinstance(stmt, Directive):
                block.directives.append(stmt)
            elif isinstance(stmt, VariableAssign):
                # hyprlang allows $var = ... inside blocks too; keep it in
                # the shared global variable table, don't attach to a node.
                pass
            else:
                raise ParseError(f"unexpected nested window rule inside '{name}'", line)
        self._expect("BLOCK_CLOSE", line)
        return block

    def _current_line(self) -> int:
        return self._peek().line


def _block_to_window_rule(block: Block) -> WindowRule:
    rule = WindowRule(line=block.line)
    for d in block.directives:
        value = d.args[0] if d.args else ""
        if d.key.startswith("match:"):
            rule.match[d.key[len("match:"):]] = value
        else:
            rule.properties[d.key] = value
    return rule


def _one_line_to_window_rule(args: List[str], line: int) -> WindowRule:
    rule = WindowRule(line=line)
    if not args:
        return rule
    rule_spec, *selectors = args
    if " " in rule_spec:
        prop, val = rule_spec.split(" ", 1)
        rule.properties[prop] = val
    elif rule_spec:
        rule.properties[rule_spec] = "true"
    for sel in selectors:
        if ":" in sel:
            k, v = sel.split(":", 1)
            rule.match[k] = v
    return rule


def parse(source: str) -> HyprlangFile:
    return _Parser(tokenize(source)).parse()


def parse_file(path) -> HyprlangFile:
    with open(path, "r") as f:
        return parse(f.read())
