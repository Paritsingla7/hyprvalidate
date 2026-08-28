"""Apply a `check`-produced Finding's textual fix, when it has one.

Deliberately separate from `checker.py`: that module's job is diagnosis
(never mutates anything), this module's job is applying a correction someone
else already decided was unambiguous - only `Finding`s carrying a
`checker.FixEdit` (see that module's docstring for which finding kinds ever
get one, and why the rest don't) are touched. This module does not decide
what's fixable; it only applies edits it's handed.

Patches are applied as targeted character-offset replacements against the
*original* source text, never a full AST-regenerate-and-reprint - the file
being patched is a user's hand-written config, and its comments and
formatting outside the flagged span must survive untouched. `convert` can
safely regenerate whole files because it's producing brand-new output; this
can't take that shortcut.
"""

from __future__ import annotations

from dataclasses import dataclass

from hyprvalidate.checker import Finding


@dataclass
class FixResult:
    source: str
    applied: list[Finding]
    remaining: list[Finding]


def apply_fixes(source: str, findings: list[Finding]) -> FixResult:
    """Apply every finding that carries a fix, and return the patched
    source alongside which findings were applied vs left as-is. Edits are
    applied back-to-front by offset so an earlier edit's insertion/deletion
    never shifts a later edit's already-computed offsets - the two use
    disjoint spans in practice (a bare-identifier value vs. a call-argument
    reference), but sorting this way makes that safe even if a future fix
    kind's span ever overlapped another's within the same statement."""
    applied = sorted(
        (f for f in findings if f.fix is not None),
        key=lambda f: f.fix.start,
        reverse=True,
    )
    remaining = [f for f in findings if f.fix is None]

    patched = source
    for finding in applied:
        edit = finding.fix
        patched = patched[: edit.start] + edit.replacement + patched[edit.end :]

    # Findings were collected in source order; `applied` was reordered for
    # patching, restore source order for reporting.
    applied.sort(key=lambda f: f.fix.start)
    return FixResult(source=patched, applied=applied, remaining=remaining)
