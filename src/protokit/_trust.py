"""The one place that decides whether a report can be read as success.

Every protokit report can come back *empty for the wrong reason*: a plugin
crashed mid-check, ``max_depth`` cut the comparison above the only
difference, a lint rule raised before it looked at anything. Each report
type already records that — ``DiffResult.truncated_paths``,
``CompatibilityReport.errors``, ``LintReport.runtime_warnings`` — but each
renderer decided for itself whether to look. The machine renderers (JUnit,
SARIF) looked; the human renderers did not, so the same object printed
``COMPATIBLE`` on a terminal and an error in CI (V23), and a truncated diff
printed ``Messages are equal.`` while the model knew it had not finished
(V24).

This module is the single owner of that question (R5). A renderer or an
exit path asks :func:`is_trustworthy` before it claims success, and renders
:func:`reasons` whenever there are any, whatever the verdict.

**Failure mode and guard (KTD1).** This is *bypass drift*: the facts were
always on the report, and call sites went around them. The guards are
therefore bypass guards — ``tests/meta/test_formatter_trust.py`` renders
every registered human formatter with and without an untrustworthy report,
and walks the root Click group for commands whose code never reaches this
module.

**It fails closed.** A report type this module does not recognise raises
``TypeError``. Defaulting an unknown object to "trustworthy" would rebuild
the fail-open class inside the seam meant to end it: a sixth report kind
would silently render as success until someone remembered to come here.

**Every reason is one printable line.** A reason quotes diagnostic text a
rule pack or plugin wrote, and renderers print it next to stable,
grep-anchored prefixes (``error[lint-...]:``). A message carrying a newline
or an escape sequence could forge such a line, so :func:`reasons` replaces
every non-printable character with a space before anything leaves this
module. It is enforced here, once, rather than remembered at each renderer.

**Layer 0 (KTD8).** This module imports nothing from ``protokit`` at any
scope, so the report types cannot be named here. Kinds are recognised by
the attribute that carries their incompleteness signal — which is also what
makes the recognition honest: an object without the signal attribute has
nothing for this module to inspect, and is refused rather than waved
through.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable
from typing import Any

#: ``LintRuntimeWarning`` categories that mean a selected rule did not run,
#: so the findings are a lower bound on an unknown total (V33).
#:
#: Deliberately the same pair the 0.15.1 lint exit gate shipped with: U7
#: moves the owner, not the reach. Three further categories also mean a rule
#: did not run (``extension_unresolved``,
#: ``custom_annotation_extension_unresolved``, ``all_files_excluded``) and are
#: not gated, for blast radius — ``extension_unresolved`` fires on nearly every
#: run whose inputs lack ``google/api/field_behavior.proto``. Widening this set
#: is a breaking change that U8 owns; ``TestIncompleteAnalysisGateIsExhaustive``
#: in ``tests/schema/lint/test_model_dataclass_changes.py`` makes every
#: category's bucket an explicit decision.
INCOMPLETE_ANALYSIS_CATEGORIES: frozenset[str] = frozenset({
    "rule_exception",
    "unloaded_rule",
})


def _one_line(text: str) -> str:
    """``text`` with every non-printable character replaced by a space.

    ``str.isprintable`` is false for the Unicode "Other" and "Separator"
    categories except the ASCII space: C0/C1 controls (newline, NUL, ESC,
    U+0085), and the line/paragraph separators U+2028/U+2029 that log
    aggregators split records on. Defined by Unicode category rather than a
    hand-kept list, so it needs nothing from ``protokit._cli_utils`` (which
    this layer-0 module may not import).
    """
    return "".join(ch if ch.isprintable() else " " for ch in text)


def _error_messages(diagnostics: Iterable[Any]) -> list[str]:
    """``str()`` of every error-level diagnostic, in emission order."""
    return [str(d) for d in diagnostics if d.level == "error"]


def _commit_error(commit: str | None, message: str) -> str:
    return f"{commit[:12]}: {message}" if commit else message


def _diff_reasons(result: Any) -> list[str]:
    out = _error_messages(result.diagnostics)
    if result.truncated_paths:
        paths = ", ".join(str(p) or "(root)" for p in result.truncated_paths)
        out.append(
            f"comparison truncated at max depth: {len(result.truncated_paths)} "
            f"subtree(s) not compared ({paths})",
        )
    return out


def _compat_reasons(report: Any) -> list[str]:
    return _error_messages(report.diagnostics)


def _aggregate_reasons(
    diagnostics: Iterable[Any], already: Counter[tuple[str | None, str]],
) -> list[str]:
    """Aggregate ``CommitDiagnostic`` errors, minus restated per-entry ones.

    ``compat history`` builds the aggregate list by copying each entry's
    diagnostics, so a CLI-produced report states every entry error twice.
    Matched with multiplicity so a hand-built report's genuinely extra (or
    deliberately repeated) aggregate errors all survive.
    """
    out: list[str] = []
    for d in diagnostics:
        if d.level != "error":
            continue
        key = (d.commit, d.message)
        if already[key]:
            already[key] -= 1
            continue
        out.append(_commit_error(d.commit, d.message))
    return out


def _history_entry_errors(report: Any) -> list[tuple[str, Any]]:
    return [
        (entry.commit_sha, d)
        for entry in report.entries
        for d in entry.report.diagnostics
        if d.level == "error"
    ]


def walk_level_reasons(report: Any) -> tuple[str, ...]:
    """A ``HistoryReport``'s reasons that no entry carries.

    The per-commit renderers (``history_junit``'s one suite per entry) show
    each entry's own errors where the entry is; this is the remainder -- an
    aggregate error attributed to a commit with no entry, or to none -- which
    they would otherwise drop (V23's fourth site).
    """
    seen: Counter[tuple[str | None, str]] = Counter(
        (sha, d.message) for sha, d in _history_entry_errors(report)
    )
    return tuple(
        _one_line(reason)
        for reason in _aggregate_reasons(report.diagnostics, seen)
    )


def _history_reasons(report: Any) -> list[str]:
    per_entry = [
        _commit_error(sha, str(d)) for sha, d in _history_entry_errors(report)
    ]
    return per_entry + list(walk_level_reasons(report))


def _bisect_reasons(report: Any) -> list[str]:
    return _aggregate_reasons(report.diagnostics, Counter())


def _lint_reasons(report: Any) -> list[str]:
    return [
        f"[{w.category}] {w.message}"
        for w in report.runtime_warnings
        if w.category in INCOMPLETE_ANALYSIS_CATEGORIES
    ]


#: One row per report kind: the attribute whose presence identifies the kind,
#: and the function that reads its incompleteness signal. Order matters in
#: exactly one place: ``LintReport`` also has ``findings``, so the compat row
#: comes last and the lint row claims a ``LintReport`` first. ``diagnostics``
#: is deliberately not an identifying attribute — all five kinds carry it, so
#: it identifies none of them; it is required *alongside* the identifying one.
_KINDS: tuple[tuple[str, Callable[[Any], list[str]]], ...] = (
    ("runtime_warnings", _lint_reasons),    # LintReport
    ("truncated_paths", _diff_reasons),     # DiffResult
    ("entries", _history_reasons),          # HistoryReport
    ("breaking_commit", _bisect_reasons),   # BisectReport
    ("findings", _compat_reasons),          # CompatibilityReport
)


def reasons(report: object) -> tuple[str, ...]:
    """Why ``report`` cannot be read as success, one line per cause.

    Args:
        report: A ``DiffResult``, ``CompatibilityReport``, ``HistoryReport``,
            ``BisectReport`` or ``LintReport``.

    Returns:
        Human-readable reasons in emission order; empty when the report is
        trustworthy. Each is a single line of printable characters, safe to
        print beside a stable prefix. Warnings never appear here — they are
        advisory.

    Raises:
        TypeError: ``report`` is not one of the five kinds. Never defaults
            to trustworthy.
    """
    for attribute, fn in _KINDS:
        if hasattr(report, attribute) and hasattr(report, "diagnostics"):
            return tuple(_one_line(reason) for reason in fn(report))
    raise TypeError(
        f"protokit._trust does not know how to vouch for "
        f"{type(report).__name__!r}: it carries none of the attributes a "
        f"protokit report records incompleteness on "
        f"({', '.join(a for a, _ in _KINDS)}). Refusing to default to "
        f"trustworthy.",
    )


def is_trustworthy(report: object) -> bool:
    """Whether an empty ``report`` means "nothing found" rather than "did not look".

    Args:
        report: One of the five report kinds; see :func:`reasons`.

    Returns:
        True iff :func:`reasons` is empty.

    Raises:
        TypeError: ``report`` is not one of the five kinds.
    """
    return not reasons(report)
