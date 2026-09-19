"""Bypass guards for the ``_trust`` seam (U7; R5, KTD1, KTD2).

``protokit._trust`` owns one question — *can this report be read as
success?* Its failure mode is **bypass drift** (KTD1): every report type
always carried the facts, and the renderers went around them (V23, V24). A
contract test on the owner would be blind to that, so these are bypass
guards. There are two, because the consumers live in two places.

**Guard 1 — the formatter registry. Predicate: decidable, by execution.**
For every ``FormatterKind`` and *every way the seam can distrust that kind*,
render the registered formatters and require the success verdict to be
withheld, every reason to be shown, and no reason to forge a line. Nothing
is inferred from names or source text: the renderer is run. A new kind fails
until it has fixtures here; a new format fails until it is classified.

One fixture per kind was not enough, and this is the lesson worth keeping:
a renderer that re-derives trust from the one signal that fixture happens to
carry (``if result.errors``) passed the guard while ignoring every other
signal. So each kind lists *every* mode the seam recognises for it, and the
machine formats run over all of them too.

**Renderers do not decide trust for themselves.** Running against a report
that really is untrustworthy cannot tell a renderer that asks the seam from
one that re-derives the answer and happens to agree — and the second is the
drift itself. ``TestNoRendererDecidesTrustForItself`` patches
``_trust.signals`` (the one function everything else here derives from, so a
renderer holding a cached reference to any of them still sees the lie) to
distrust a report with nothing wrong, and gives it a *novel signal kind*: no
format claims to render that kind structurally, so every one of them must
fail closed on it, exactly as it would the day the seam learns a new reason.

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
import re
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterator
from pathlib import Path

import click
import pytest

# LINT_REPORT formatters register when their module loads, and nothing in
# ``protokit.formatters`` loads it (the lint CLI does).
import protokit.formatters._builtin_lint  # noqa: F401
from protokit import _trust
from protokit.cli import main as root_group
from protokit.formatters import (
    FormatterContext,
    FormatterKind,
    _registry,
    get_formatter,
)
from protokit.message.model import (
    ChangeType,
    Diagnostic,
    Difference,
    DiffResult,
    FieldPath,
)
from protokit.schema.model import CommitDiagnostic, Finding
from tests._trust_reports import (
    bisect_report,
    compat_report,
    error_diagnostic,
    history_report,
    lint_report,
    truncated_diff_result,
)

_SRC = Path(__file__).resolve().parents[2] / "src" / "protokit"

# A reason's text is written by a rule pack or plugin. This one tries to
# forge a second, stable-prefixed line.
_FORGED = "error[lint-fake]: analysis completed"
_HOSTILE = f"plugin crashed\n{_FORGED}"


def _error() -> Diagnostic:
    return error_diagnostic(_HOSTILE)


def _commit_error(commit: str | None = "a" * 40) -> CommitDiagnostic:
    return CommitDiagnostic(commit, "error", None, _HOSTILE)  # type: ignore[arg-type]


def _finding() -> Finding:
    from protokit.schema.model import Direction, Severity
    return Finding(
        path=FieldPath.parse("user.email"), rule_id="field_removed",
        severity=Severity.SEMANTIC, direction=Direction.BACKWARD,
        message="field present in old schema, absent in new",
    )


def _difference() -> Difference:
    return Difference(
        path=FieldPath.parse("name"), change_type=ChangeType.MODIFIED,
        left_value="A", right_value="B",
    )


#: ``kind -> {mode: report}``: every way the seam recognises that kind as
#: untrustworthy, including one where the report ALSO has something to
#: report. A renderer that shows reasons only when it withholds a verdict
#: fails the with-findings modes.
_UNTRUSTED: dict[FormatterKind, dict[str, object]] = {
    FormatterKind.DIFF: {
        "truncated": truncated_diff_result(),
        "error": DiffResult(differences=(), diagnostics=(_error(),)),
        "error-with-differences": DiffResult(
            differences=(_difference(),), diagnostics=(_error(),),
        ),
        "truncated-with-differences": dataclasses.replace(
            truncated_diff_result(), differences=(_difference(),),
        ),
    },
    FormatterKind.COMPAT: {
        "error": compat_report(_error()),
        "error-with-findings": compat_report(_error(), findings=(_finding(),)),
    },
    FormatterKind.COMPAT_HISTORY: {
        "entry-error": history_report(entry_diags=(_error(),)),
        "aggregate-only": history_report(aggregate=(_commit_error("d" * 40),)),
        "aggregate-no-entries": history_report(
            aggregate=(_commit_error("d" * 40),), entries=False,
        ),
        "aggregate-uncommitted": history_report(aggregate=(_commit_error(None),)),
    },
    FormatterKind.COMPAT_BISECT: {
        "error": bisect_report(_commit_error()),
        "error-uncommitted": bisect_report(_commit_error(None)),
        "error-with-break": bisect_report(
            _commit_error(), breaking="f" * 40, findings=(_finding(),),
        ),
    },
    FormatterKind.LINT_REPORT: {
        # One per gated category, so U8 widening the set is exercised here
        # automatically rather than needing a new fixture.
        **{
            f"category-{c}": lint_report(categories=(c,), message=_HOSTILE)
            for c in sorted(_trust.INCOMPLETE_ANALYSIS_CATEGORIES)
        },
        "compile-error": lint_report(compile_error=_HOSTILE),
        "rule-exception-repeated": lint_report(
            categories=("rule_exception",), message=_HOSTILE, elements=9,
        ),
    },
}

#: The trustworthy counterpart of each kind: nothing to report, nothing
#: wrong. Its rendering is the success verdict the untrusted modes must
#: withhold.
_TRUSTED: dict[FormatterKind, object] = {
    FormatterKind.DIFF: DiffResult(differences=()),
    FormatterKind.COMPAT: compat_report(),
    FormatterKind.COMPAT_HISTORY: history_report(),
    FormatterKind.COMPAT_BISECT: bisect_report(),
    FormatterKind.LINT_REPORT: lint_report(),
}

_MODES = [
    pytest.param(kind, mode, id=f"{kind.name}-{mode}")
    for kind, modes in _UNTRUSTED.items() for mode in modes
]


def _render(name: str, kind: FormatterKind, report: object) -> str:
    fn = get_formatter(name, kind)
    return fn(report, FormatterContext(subcommand="guard"))  # type: ignore[arg-type]


def _render_human(kind: FormatterKind, report: object) -> str:
    return click.unstyle(_render("human", kind, report))


def _states_success(out: str, success: str) -> bool:
    """Whether ``out`` states ``success`` as its own word.

    Bounded on both sides: ``COMPATIBLE`` is a substring of ``INCOMPATIBLE``,
    and a plain ``in`` would read the refusal as the claim.
    """
    return bool(re.search(rf"(?<![A-Za-z]){re.escape(success)}(?![A-Za-z])", out))


#: The text that states success, per kind. A table, because "the last line of
#: the clean rendering" is defeated by appending one line after the verdict —
#: and because a *substring* check catches a verdict that moved or gained a
#: suffix, which line equality does not. ``None`` for a kind whose clean
#: rendering states no verdict (``lint`` prints nothing). Each entry is
#: premise-checked against the real clean rendering below, so it cannot go
#: stale.
_SUCCESS_TEXT: dict[FormatterKind, str | None] = {
    FormatterKind.DIFF: "Messages are equal",
    FormatterKind.COMPAT: "COMPATIBLE",
    FormatterKind.COMPAT_HISTORY: "OK",
    FormatterKind.COMPAT_BISECT: "no break found",
    FormatterKind.LINT_REPORT: None,
}


class TestEveryHumanFormatterAsksTheSeam:
    def test_every_formatter_kind_has_fixtures(self) -> None:
        """A sixth report kind cannot land without deciding how it is vouched for."""
        assert set(_UNTRUSTED) == set(FormatterKind)
        assert set(_TRUSTED) == set(FormatterKind)
        assert set(_SUCCESS_TEXT) == set(FormatterKind)

    @pytest.mark.parametrize("kind", list(FormatterKind), ids=lambda k: k.name)
    def test_success_text_premise(self, kind: FormatterKind) -> None:
        """The table names text the clean rendering actually prints."""
        out = _render_human(kind, _TRUSTED[kind])
        success = _SUCCESS_TEXT[kind]
        if success is None:
            assert not out.strip(), (kind.name, out)
        else:
            assert _states_success(out, success), (kind.name, out)

    @pytest.mark.parametrize(("kind", "mode"), _MODES)
    def test_fixture_premise(self, kind: FormatterKind, mode: str) -> None:
        """Each mode is untrusted, and the trusted counterpart is trusted."""
        assert not _trust.is_trustworthy(_UNTRUSTED[kind][mode])
        assert _trust.is_trustworthy(_TRUSTED[kind])

    @pytest.mark.parametrize(("kind", "mode"), _MODES)
    def test_an_untrustworthy_report_renders_differently(
        self, kind: FormatterKind, mode: str,
    ) -> None:
        assert _render_human(kind, _UNTRUSTED[kind][mode]) != _render_human(
            kind, _TRUSTED[kind],
        )

    @pytest.mark.parametrize(("kind", "mode"), _MODES)
    def test_the_success_verdict_is_withheld(
        self, kind: FormatterKind, mode: str,
    ) -> None:
        """Showing the reasons *beside* a pass is still a pass."""
        success = _SUCCESS_TEXT[kind]
        if success is None:
            return
        report = _UNTRUSTED[kind][mode]
        if kind is FormatterKind.COMPAT_HISTORY and mode.startswith("aggregate"):
            # The walk is in doubt, but each entry's own check finished, so
            # its OK line is the truth. The walk-level block is what must
            # appear; ``test_every_reason_is_rendered`` covers that.
            return
        assert not _states_success(_render_human(kind, report), success), (
            kind.name, mode,
        )

    @pytest.mark.parametrize(("kind", "mode"), _MODES)
    def test_every_reason_is_rendered(
        self, kind: FormatterKind, mode: str,
    ) -> None:
        report = _UNTRUSTED[kind][mode]
        out = _render_human(kind, report)
        reasons = _trust.reasons(report)
        assert reasons
        for reason in reasons:
            assert reason in out, (kind.name, mode, reason, out)

    @pytest.mark.parametrize(("kind", "mode"), _MODES)
    def test_a_reason_cannot_forge_a_line(
        self, kind: FormatterKind, mode: str,
    ) -> None:
        for line in _render_human(kind, _UNTRUSTED[kind][mode]).splitlines():
            assert not line.startswith("error["), (kind.name, mode, line)


# ---------------------------------------------------------------------------
# Machine formats — R4 names the machine counterpart too
# ---------------------------------------------------------------------------


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
    # its category, and no success boolean that could be wrong — which
    # ``test_a_verdict_free_format_states_no_verdict`` checks rather than
    # takes on trust.
    (FormatterKind.LINT_REPORT, "json"): None,
    (FormatterKind.LINT_REPORT, "junit"): _junit_passes,
    (FormatterKind.LINT_REPORT, "sarif"): _sarif_succeeded,
}

_VERDICT_FORMATS = sorted(
    (key for key, reader in _MACHINE_VERDICTS.items() if reader is not None),
    key=lambda key: (key[0].name, key[1]),
)
_VERDICT_MODES = [
    pytest.param(key, mode, id=f"{key[0].name}-{key[1]}-{mode}")
    for key in _VERDICT_FORMATS for mode in _UNTRUSTED[key[0]]
]


def _registered_builtins_from_source() -> set[tuple[str, str]]:
    """Every ``_register_builtin`` call in the package, read statically.

    The registry reflects what has been *imported*; a built-in registered by
    a module some CLI imports lazily is invisible to it at collection time,
    and so would escape classification while a real ``--format`` run reaches
    it. Reading the source finds it whether or not it has been imported.
    """
    found: set[tuple[str, str]] = set()
    for path in _SRC.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", None)
            if name != "_register_builtin":
                continue
            args = {kw.arg: kw.value for kw in node.keywords}
            first = node.args[0] if node.args else args.get("name")
            kind = args.get("kind")
            assert isinstance(first, ast.Constant) and isinstance(first.value, str), (
                f"{path}: formatter name must be a literal"
            )
            assert isinstance(kind, ast.Attribute), (
                f"{path}: kind= must be a FormatterKind attribute"
            )
            found.add((kind.attr, first.value))
    return found


class TestEveryMachineVerdictAsksTheSeam:
    def test_every_registered_format_is_classified(self) -> None:
        registered = {key for key in _registry._REGISTRY if key[1] != "human"}
        assert registered == set(_MACHINE_VERDICTS), (
            f"unclassified: {sorted(map(str, registered - set(_MACHINE_VERDICTS)))}; "
            f"stale: {sorted(map(str, set(_MACHINE_VERDICTS) - registered))}"
        )

    def test_no_builtin_escapes_by_being_imported_lazily(self) -> None:
        """The classification above covers every built-in in the source tree."""
        in_source = _registered_builtins_from_source()
        imported = {(kind.name, name) for kind, name in _registry._BUILTIN_NAMES}
        assert in_source == imported, (
            f"registered lazily (invisible to the registry at collection): "
            f"{sorted(in_source - imported)}; "
            f"registered without a source call: {sorted(imported - in_source)}"
        )

    @pytest.mark.parametrize(("key", "mode"), _VERDICT_MODES)
    def test_the_verdict_follows_the_seam(
        self, key: tuple[FormatterKind, str], mode: str,
    ) -> None:
        kind, name = key
        reader = _MACHINE_VERDICTS[key]
        assert reader is not None
        assert reader(_render(name, kind, _TRUSTED[kind])) is True
        assert reader(_render(name, kind, _UNTRUSTED[kind][mode])) is False

    @pytest.mark.parametrize(
        "key",
        [k for k, r in _MACHINE_VERDICTS.items() if r is None],
        ids=lambda k: f"{k[0].name}-{k[1]}",
    )
    def test_a_verdict_free_format_states_no_verdict(
        self, key: tuple[FormatterKind, str],
    ) -> None:
        """"Verdict-free" is a check, not a declaration.

        A format excused from the verdict table may not quietly grow a
        success boolean: the excuse is that it states no verdict at all.
        """
        kind, name = key
        for report in [_TRUSTED[kind], *_UNTRUSTED[kind].values()]:
            payload = json.loads(_render(name, kind, report))
            booleans = [k for k, v in payload.items() if isinstance(v, bool)]
            assert not booleans, (kind.name, name, booleans)


# ---------------------------------------------------------------------------
# No renderer decides trust for itself
# ---------------------------------------------------------------------------

_SENTINEL = "the-seam-said-so"
#: Long, and every word forges the prefix, so a renderer that wraps the line
#: cannot hide the forgery in a continuation.
_SENTINEL_FORGED = " ".join(["error[lint-fake]:"] * 30)
#: A kind no format claims to render structurally: this models the day the
#: seam learns a new reason, which every format must fail closed on.
_SENTINEL_KIND = "sentinel-reason"
_SENTINELS = (_SENTINEL, _SENTINEL_FORGED)


@pytest.fixture
def distrusting_seam(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the seam distrust every report, including ones with nothing wrong.

    Patches ``signals`` alone: ``reasons``, ``is_trustworthy``,
    ``signals_other_than`` and ``walk_level_reasons`` all derive from it, so a
    renderer that bound any of them still sees the lie.
    """
    monkeypatch.setattr(_trust, "signals", lambda report: tuple(
        _trust.Signal(_SENTINEL_KIND, text) for text in _SENTINELS
    ))


@pytest.mark.usefixtures("distrusting_seam")
class TestNoRendererDecidesTrustForItself:
    """Bypass drift, caught by making the seam disagree with the report.

    The guards above run each renderer on a report that really is
    untrustworthy, so they cannot tell a renderer that *asks the seam* from
    one that re-derives the answer from ``report.diagnostics`` and happens to
    agree — and the second is the drift KTD1 names: a correct owner, and a
    call site going around it. It would stay green until the day the seam
    learned a new reason, and then silently disagree with it.
    """

    def test_the_patch_reaches_every_derived_function(self) -> None:
        """Premise: everything the renderers use derives from ``signals``."""
        trusted = _TRUSTED[FormatterKind.COMPAT]
        assert _trust.is_trustworthy(trusted) is False
        assert _trust.reasons(trusted) == _SENTINELS
        assert _trust.walk_level_reasons(trusted) == _SENTINELS
        assert tuple(
            s.text for s in _trust.signals_other_than(
                trusted, _trust.ERROR_DIAGNOSTIC,
            )
        ) == _SENTINELS

    @pytest.mark.parametrize("kind", list(FormatterKind), ids=lambda k: k.name)
    def test_human_renderers_follow_the_seam(self, kind: FormatterKind) -> None:
        out = _render_human(kind, _TRUSTED[kind])
        for sentinel in _SENTINELS:
            assert sentinel in out, (kind.name, out)
        for line in out.splitlines():
            assert not line.startswith("error["), (kind.name, line)
        success = _SUCCESS_TEXT[kind]
        if success is not None:
            assert not _states_success(out, success), (kind.name, out)

    @pytest.mark.parametrize(
        "key", _VERDICT_FORMATS, ids=lambda k: f"{k[0].name}-{k[1]}",
    )
    def test_machine_verdicts_follow_the_seam(
        self, key: tuple[FormatterKind, str],
    ) -> None:
        kind, name = key
        reader = _MACHINE_VERDICTS[key]
        assert reader is not None
        assert reader(_render(name, kind, _TRUSTED[kind])) is False, (
            kind.name, name,
        )


class TestTheFailurePathCannotCrashALegacyConsole:
    """The INCOMPLETE text is printed exactly when a run went wrong.

    The renderers' own new text is ASCII for ``history`` / ``bisect`` /
    ``lint``; ``compat``'s stays within cp1252 because its pre-existing
    header carries an em dash. A glyph outside that set would raise
    ``UnicodeEncodeError`` on a Windows console or a CI log under a legacy
    code page — on the one path where losing the output is worst. ``diff`` is
    exempt: its arrows and marks predate the seam.

    The reasons themselves quote plugin text, which protokit does not choose,
    so these fixtures carry ASCII messages: what is asserted is the codec of
    the text the renderer adds.
    """

    _ASCII_FIXTURES: dict[FormatterKind, object] = {
        FormatterKind.COMPAT: compat_report(error_diagnostic("plugin crashed")),
        FormatterKind.COMPAT_HISTORY: history_report(
            entry_diags=(error_diagnostic("plugin crashed"),),
        ),
        FormatterKind.COMPAT_BISECT: bisect_report(
            CommitDiagnostic("a" * 40, "error", None, "plugin crashed"),
        ),
        FormatterKind.LINT_REPORT: lint_report(
            categories=("rule_exception",), message="rule blew up",
        ),
    }

    @pytest.mark.parametrize(("kind", "codec"), [
        (FormatterKind.COMPAT, "cp1252"),
        (FormatterKind.COMPAT_HISTORY, "ascii"),
        (FormatterKind.COMPAT_BISECT, "ascii"),
        (FormatterKind.LINT_REPORT, "ascii"),
    ], ids=lambda v: v if isinstance(v, str) else v.name)
    def test_untrustworthy_output_encodes(
        self, kind: FormatterKind, codec: str,
    ) -> None:
        _render_human(kind, self._ASCII_FIXTURES[kind]).encode(codec)


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
    """Every leaf under ``command``, asking the group rather than reading it.

    ``Group.commands`` is empty for a lazily-populated group, which would
    hide a whole subtree from this guard. ``list_commands`` /
    ``get_command`` are the interface every Click group implements.
    """
    if isinstance(command, click.Group):
        ctx = click.Context(command)
        for name in sorted(command.list_commands(ctx)):
            sub = command.get_command(ctx, name)
            assert sub is not None, (path, name)
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
        """The enumeration is not vacuous: it sees every registered subcommand.

        Compared against ``list_commands``, not ``.commands``: a lazily
        populated group leaves the latter empty, which would make this check
        agree with a walk that found nothing.
        """
        roots = {path.split(" ")[0] for path, _ in _leaf_commands(root_group)}
        assert roots == set(root_group.list_commands(click.Context(root_group)))
        assert len(roots) >= 5

    def test_the_predicate_is_not_vacuous(self) -> None:
        """It says yes to a function that reaches the seam, and no to one that does not."""
        assert _reaches_seam("protokit.message.cli", "main") is True
        assert _reaches_seam("protokit.message.cli", "_get_message_class") is False


def test_fixtures_are_frozen_report_types() -> None:
    """The fixtures are the real report dataclasses, not lookalikes."""
    for kind, trusted in _TRUSTED.items():
        assert dataclasses.is_dataclass(trusted)
        for mode, untrusted in _UNTRUSTED[kind].items():
            assert type(untrusted) is type(trusted), (kind.name, mode)
