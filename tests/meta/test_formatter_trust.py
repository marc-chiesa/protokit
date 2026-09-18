"""Bypass guards for the ``_trust`` seam (U7; R5, KTD1, KTD2).

``protokit._trust`` owns one question — *can this report be read as
success?* Its failure mode is **bypass drift** (KTD1): every report type
always carried the facts, and the human renderers went around them (V23,
V24). A contract test on the owner would be blind to that, so these are
bypass guards. There are two, because the consumers live in two places.

**Guard 1 — the formatter registry. Predicate: decidable, by execution.**
For every ``FormatterKind``, render the registered ``human`` formatter on an
untrustworthy report and on the same report made trustworthy, and require
the outputs to differ, every reason to be shown, and no reason to forge a
line. Nothing is inferred from names or source text: the renderer is run.
A new kind fails until it has a fixture here, and a new kind's renderer
fails until it asks the seam.

**Guard 2 — the root Click group. Predicate: decidable, by AST; and
necessary, not sufficient.** Guard 1 cannot see ``forensics``, whose
renderers are module-local and unregistered, nor any exit path. So this
guard enumerates every leaf command under ``protokit.cli.main`` and decides,
statically: *does the command callback's module-local call closure reference
the* ``protokit._trust`` *module?* That is a property of the syntax tree and
needs no heuristic. What it does **not** decide is the plan's full sentence,
"every terminal exit path consults ``_trust``" — that is a dominance property
over control flow, and a function that mentions ``_trust`` on one branch and
calls ``sys.exit(0)`` on another satisfies this guard. It is stated here
rather than implied: the guard catches a command that never reaches the seam
at all, which is the drift that actually happened, and the per-command exit
tests (U8) carry the rest.

Commands that do not reach the seam yet are listed in ``PENDING_U8``, which
is compared for **equality** with what the walk finds. U8 routes those exit
paths and deletes the entries; an entry that has become stale fails just as
loudly as a new command that bypasses the seam.
"""

from __future__ import annotations

import ast
import dataclasses
import importlib
import inspect
from collections.abc import Iterator
from pathlib import Path

import click
import pytest

from protokit import _trust
from protokit.cli import main as root_group
from protokit.formatters import FormatterContext, FormatterKind, get_formatter
from protokit.message.model import Diagnostic, DiffResult, FieldPath
from protokit.schema.lint.model import LintReport, LintRuntimeWarning
from protokit.schema.model import (
    BisectReport,
    CommitDiagnostic,
    CompatibilityLevel,
    CompatibilityReport,
    HistoryEntry,
    HistoryReport,
)

# A reason's text is written by a rule pack or plugin. This one tries to
# forge a second, stable-prefixed line.
_FORGED = "error[lint-fake]: analysis completed"
_HOSTILE = f"plugin crashed\n{_FORGED}"


def _error() -> Diagnostic:
    return Diagnostic(level="error", path=None, message=_HOSTILE)


def _commit_error() -> CommitDiagnostic:
    return CommitDiagnostic("a" * 40, "error", None, _HOSTILE)


def _compat(*diagnostics: Diagnostic) -> CompatibilityReport:
    return CompatibilityReport(
        level=CompatibilityLevel.STRICT, diagnostics=tuple(diagnostics),
    )


def _history(report: CompatibilityReport) -> HistoryReport:
    return HistoryReport(
        range_spec="A..B", old_sha="a", new_sha="b", commits_walked=2,
        entries=(HistoryEntry(
            commit_sha="c" * 40, parent_sha="p" * 40, commit_subject="s",
            report=report,
        ),),
    )


def _bisect(*diagnostics: CommitDiagnostic) -> BisectReport:
    return BisectReport(
        range_spec="A..B", old_sha="a", new_sha="b", breaking_commit=None,
        commits_walked=3, diagnostics=tuple(diagnostics),
    )


#: ``kind -> (untrustworthy report, the same report made trustworthy)``.
#: Both of a pair have nothing to report, so the only thing that can make
#: their renderings differ is the renderer asking the seam.
_FIXTURES: dict[FormatterKind, tuple[object, object]] = {
    FormatterKind.DIFF: (
        DiffResult(differences=(), truncated_paths=(FieldPath.parse("inner"),)),
        DiffResult(differences=()),
    ),
    FormatterKind.COMPAT: (_compat(_error()), _compat()),
    FormatterKind.COMPAT_HISTORY: (_history(_compat(_error())), _history(_compat())),
    FormatterKind.COMPAT_BISECT: (_bisect(_commit_error()), _bisect()),
    FormatterKind.LINT_REPORT: (
        LintReport(runtime_warnings=(LintRuntimeWarning(
            category="rule_exception", rule_id="x/y", message=_HOSTILE,
        ),)),
        LintReport(),
    ),
}


def _render_human(kind: FormatterKind, report: object) -> str:
    fn = get_formatter("human", kind)
    return click.unstyle(fn(report, FormatterContext(subcommand="guard")))  # type: ignore[arg-type]


class TestEveryHumanFormatterAsksTheSeam:
    def test_every_formatter_kind_has_a_fixture(self) -> None:
        """A sixth report kind cannot land without deciding how it is vouched for."""
        assert set(_FIXTURES) == set(FormatterKind)

    @pytest.mark.parametrize("kind", list(FormatterKind), ids=lambda k: k.name)
    def test_fixture_premise(self, kind: FormatterKind) -> None:
        """The pair differs in trust and in nothing the renderer could show."""
        untrusted, trusted = _FIXTURES[kind]
        assert not _trust.is_trustworthy(untrusted)
        assert _trust.is_trustworthy(trusted)

    @pytest.mark.parametrize("kind", list(FormatterKind), ids=lambda k: k.name)
    def test_an_untrustworthy_report_renders_differently(
        self, kind: FormatterKind,
    ) -> None:
        untrusted, trusted = _FIXTURES[kind]
        assert _render_human(kind, untrusted) != _render_human(kind, trusted)

    @pytest.mark.parametrize("kind", list(FormatterKind), ids=lambda k: k.name)
    def test_every_reason_is_rendered(self, kind: FormatterKind) -> None:
        untrusted, _ = _FIXTURES[kind]
        out = _render_human(kind, untrusted)
        reasons = _trust.reasons(untrusted)
        assert reasons
        for reason in reasons:
            assert reason in out, (kind.name, reason, out)

    @pytest.mark.parametrize("kind", list(FormatterKind), ids=lambda k: k.name)
    def test_a_reason_cannot_forge_a_line(self, kind: FormatterKind) -> None:
        if kind is FormatterKind.DIFF:
            untrusted: object = DiffResult(differences=(), diagnostics=(_error(),))
        else:
            untrusted, _ = _FIXTURES[kind]
        for line in _render_human(kind, untrusted).splitlines():
            assert not line.startswith("error["), (kind.name, line)


# ---------------------------------------------------------------------------
# Guard 2 — the root Click group
# ---------------------------------------------------------------------------

#: Leaf commands whose callback does not reach ``protokit._trust`` yet. U8
#: ("route every exit decision through the U7 ``_trust`` predicate") owns
#: emptying this; it must be empty before 0.16.0 cuts. Why each is here:
#:
#: * ``compat *`` — the renderers they dispatch to ask the seam (guard 1), but
#:   the exit gates are ``if report.diagnostics: sys.exit(2)``, which is
#:   *stricter* than the seam (warnings exit 2 too). Routing them is a
#:   behavior decision, not a migration.
#: * ``forensics *`` / ``storage *`` — no report kind of theirs is known to
#:   the seam; U8 decides what vouching for a ``MatchReport`` or a scan means.
PENDING_U8: frozenset[str] = frozenset({
    "compat bisect",
    "compat check",
    "compat ci",
    "compat history",
    "forensics drift",
    "forensics match",
    "storage count",
    "storage head",
    "storage scan",
})


def _leaf_commands(
    command: click.Command, path: tuple[str, ...] = (),
) -> Iterator[tuple[str, click.Command]]:
    if isinstance(command, click.Group):
        for name, sub in sorted(command.commands.items()):
            yield from _leaf_commands(sub, (*path, name))
    else:
        yield " ".join(path), command


def _seam_aliases(tree: ast.Module) -> set[str]:
    """Local names bound to ``protokit._trust`` or to something imported from it."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                is_the_module = node.module == "protokit" and alias.name == "_trust"
                if is_the_module or node.module == "protokit._trust":
                    names.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "protokit._trust" and alias.asname:
                    names.add(alias.asname)
    return names


def _reaches_seam(module_name: str, function_name: str) -> bool:
    """Does ``function_name``'s module-local call closure reference the seam?"""
    module = importlib.import_module(module_name)
    tree = ast.parse(Path(inspect.getsourcefile(module) or "").read_text())
    aliases = _seam_aliases(tree)
    functions = {
        node.name: node for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    assert function_name in functions, (module_name, function_name)

    seen: set[str] = set()
    todo = [function_name]
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        for node in ast.walk(functions[name]):
            if isinstance(node, ast.Name):
                if node.id in aliases:
                    return True
                if node.id in functions:
                    todo.append(node.id)
    return False


class TestEveryCommandReachesTheSeam:
    def test_commands_that_bypass_the_seam_are_exactly_the_pending_set(self) -> None:
        bypassing = set()
        for path, command in _leaf_commands(root_group):
            callback = inspect.unwrap(command.callback)  # type: ignore[arg-type]
            if not _reaches_seam(callback.__module__, callback.__name__):
                bypassing.add(path)
        assert bypassing == PENDING_U8, (
            f"new bypass (route it through protokit._trust): "
            f"{sorted(bypassing - PENDING_U8)}; stale PENDING_U8 entry "
            f"(delete it): {sorted(PENDING_U8 - bypassing)}"
        )

    def test_the_walk_finds_the_whole_group(self) -> None:
        """The enumeration is not vacuous: it sees every registered subcommand."""
        roots = {path.split(" ")[0] for path, _ in _leaf_commands(root_group)}
        assert roots == set(root_group.commands)

    def test_the_predicate_is_not_vacuous(self) -> None:
        """It says yes to a function that reaches the seam, and no to one that does not."""
        assert _reaches_seam("protokit.message.cli", "main") is True
        assert _reaches_seam("protokit.message.cli", "_get_message_class") is False


def test_fixtures_are_frozen_report_types() -> None:
    """The fixtures are the real report dataclasses, not lookalikes."""
    for untrusted, trusted in _FIXTURES.values():
        assert dataclasses.is_dataclass(untrusted) and type(untrusted) is type(trusted)
