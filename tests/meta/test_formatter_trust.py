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

R4 names the *machine* counterpart too, so the same fixtures go through every
other registered built-in format, and each one's success verdict — JUnit's
failure/error counts, SARIF's ``executionSuccessful``, a JSON verdict boolean
— must say "not success" for the untrustworthy report and "success" for the
trustworthy one. ``_MACHINE_VERDICTS`` is compared for **equality** with the
registry, so a new format is either given a verdict reader or declared
verdict-free with a reason; it cannot land unclassified.

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
import functools
import importlib
import inspect
import json
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterator
from pathlib import Path

import click
import pytest

from protokit import _trust
from protokit.cli import main as root_group
from protokit.formatters import (
    FormatterContext,
    FormatterKind,
    _registry,
    get_formatter,
)
from protokit.message.model import Diagnostic, DiffResult, FieldPath
from protokit.schema.lint.model import LintReport, LintRuntimeWarning
from protokit.schema.model import CommitDiagnostic
from tests._trust_reports import (
    bisect_report,
    compat_report,
    error_diagnostic,
    history_report,
)

# A reason's text is written by a rule pack or plugin. This one tries to
# forge a second, stable-prefixed line.
_FORGED = "error[lint-fake]: analysis completed"
_HOSTILE = f"plugin crashed\n{_FORGED}"


def _error() -> Diagnostic:
    return error_diagnostic(_HOSTILE)


def _commit_error() -> CommitDiagnostic:
    return CommitDiagnostic("a" * 40, "error", None, _HOSTILE)


#: ``kind -> (untrustworthy report, the same report made trustworthy)``.
#: Both of a pair have nothing to report, so the only thing that can make
#: their renderings differ is the renderer asking the seam.
_FIXTURES: dict[FormatterKind, tuple[object, object]] = {
    FormatterKind.DIFF: (
        DiffResult(differences=(), truncated_paths=(FieldPath.parse("inner"),)),
        DiffResult(differences=()),
    ),
    FormatterKind.COMPAT: (compat_report(_error()), compat_report()),
    FormatterKind.COMPAT_HISTORY: (
        history_report(entry_diags=(_error(),)), history_report(),
    ),
    FormatterKind.COMPAT_BISECT: (bisect_report(_commit_error()), bisect_report()),
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


def _junit_passes(out: str) -> bool:
    root = ET.fromstring(out)
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    return all(
        int(suite.get("failures") or 0) == 0 and int(suite.get("errors") or 0) == 0
        for suite in suites
    )


def _sarif_succeeded(out: str) -> bool:
    return all(
        invocation["executionSuccessful"]
        for run in json.loads(out)["runs"]
        for invocation in run["invocations"]
    )


def _json_key(*path: str) -> Callable[[str], bool]:
    def read(out: str) -> bool:
        value = json.loads(out)
        for key in path:
            value = value[key]
        assert isinstance(value, bool), (path, value)
        return value
    return read


def _history_json_succeeded(out: str) -> bool:
    payload = json.loads(out)
    return payload["complete"] and all(e["compatible"] for e in payload["entries"])


#: ``(kind, format) -> reader of that format's success verdict``, or ``None``
#: for a format that states no verdict — with the reason it may not state one.
_MACHINE_VERDICTS: dict[tuple[FormatterKind, str], Callable[[str], bool] | None] = {
    (FormatterKind.DIFF, "json"): _json_key("equal"),
    (FormatterKind.DIFF, "junit"): _junit_passes,
    (FormatterKind.COMPAT, "json"): _json_key("compatible"),
    (FormatterKind.COMPAT, "junit"): _junit_passes,
    (FormatterKind.COMPAT, "sarif"): _sarif_succeeded,
    (FormatterKind.COMPAT_HISTORY, "json"): _history_json_succeeded,
    (FormatterKind.COMPAT_HISTORY, "junit"): _junit_passes,
    (FormatterKind.COMPAT_HISTORY, "sarif"): _sarif_succeeded,
    (FormatterKind.COMPAT_BISECT, "json"): _json_key("complete"),
    (FormatterKind.COMPAT_BISECT, "junit"): _junit_passes,
    (FormatterKind.COMPAT_BISECT, "sarif"): _sarif_succeeded,
    # Deliberately verdict-free. The seam's lint categories are KNOWN
    # INCOMPLETE until U8 (three "rule did not run" categories are ungated),
    # so an affirmative ``"complete": true`` would over-claim on exactly the
    # runs it is ungated for. The payload carries every runtime warning with
    # its category, and no success boolean that could be wrong.
    (FormatterKind.LINT_REPORT, "json"): None,
    (FormatterKind.LINT_REPORT, "junit"): _junit_passes,
    (FormatterKind.LINT_REPORT, "sarif"): _sarif_succeeded,
}

_VERDICT_FORMATS = sorted(
    (key for key, reader in _MACHINE_VERDICTS.items() if reader is not None),
    key=lambda key: (key[0].name, key[1]),
)


class TestEveryMachineVerdictAsksTheSeam:
    def test_every_registered_format_is_classified(self) -> None:
        registered = {key for key in _registry._REGISTRY if key[1] != "human"}
        assert registered == set(_MACHINE_VERDICTS), (
            f"unclassified: {sorted(map(str, registered - set(_MACHINE_VERDICTS)))}; "
            f"stale: {sorted(map(str, set(_MACHINE_VERDICTS) - registered))}"
        )

    @pytest.mark.parametrize(
        "key", _VERDICT_FORMATS, ids=lambda k: f"{k[0].name}-{k[1]}",
    )
    def test_the_verdict_follows_the_seam(
        self, key: tuple[FormatterKind, str],
    ) -> None:
        kind, name = key
        reader = _MACHINE_VERDICTS[key]
        assert reader is not None
        fn = get_formatter(name, kind)
        untrusted, trusted = _FIXTURES[kind]
        ctx = FormatterContext(subcommand="guard")
        assert reader(fn(trusted, ctx)) is True  # type: ignore[arg-type]
        assert reader(fn(untrusted, ctx)) is False  # type: ignore[arg-type]


class TestTheFailurePathCannotCrashALegacyConsole:
    """The INCOMPLETE text is printed exactly when a run went wrong.

    ``history`` / ``bisect`` / ``lint`` human output is ASCII and ``compat``'s
    stays within cp1252, so a Windows console or a CI log piped under a legacy
    code page can always encode it. A glyph outside that set would raise
    ``UnicodeEncodeError`` on the one path where losing the output is worst.
    ``diff`` is exempt: its arrows and marks predate the seam.
    """

    @pytest.mark.parametrize("kind", [
        FormatterKind.COMPAT, FormatterKind.COMPAT_HISTORY,
        FormatterKind.COMPAT_BISECT, FormatterKind.LINT_REPORT,
    ], ids=lambda k: k.name)
    def test_untrustworthy_output_encodes_under_cp1252(
        self, kind: FormatterKind,
    ) -> None:
        untrusted, _ = _FIXTURES[kind]
        _render_human(kind, untrusted).encode("cp1252")


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


@functools.cache
def _module_functions(
    module_name: str,
) -> tuple[frozenset[str], dict[str, ast.FunctionDef | ast.AsyncFunctionDef]]:
    """``(seam aliases, top-level functions)`` of a module, parsed once.

    Several commands share a module (``compat`` has four in one file).
    """
    module = importlib.import_module(module_name)
    tree = ast.parse(Path(inspect.getsourcefile(module) or "").read_text())
    functions = {
        node.name: node for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    return frozenset(_seam_aliases(tree)), functions


def _reaches_seam(module_name: str, function_name: str) -> bool:
    """Does ``function_name``'s module-local call closure reference the seam?"""
    aliases, functions = _module_functions(module_name)
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
