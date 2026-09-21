"""The one place that decides whether a report can be read as success.

Every protokit report can come back *empty for the wrong reason*: a plugin
crashed mid-check, ``max_depth`` cut the comparison above the only
difference, a lint rule raised before it looked at anything. Each report
type already records that — ``DiffResult.truncated_paths``,
``CompatibilityReport.errors``, ``LintReport.runtime_warnings`` — but each
renderer decided for itself whether to look, and they disagreed. ``compat``'s
JUnit and SARIF renderers looked where its human renderer did not, so one
report printed ``COMPATIBLE`` on a terminal and an error in CI (V23). Others
looked at part of it or at none: ``history``'s JUnit dropped an error no
commit entry carried, ``lint``'s emitted a passing ``clean`` case for a run
whose rule had raised, and ``diff``'s passed a comparison ``max_depth`` had
cut short, which its human renderer called ``Messages are equal.`` (V24).

This module is the single owner of that question (R5). A renderer or an
exit path asks :func:`is_trustworthy` before it claims success, and renders
:func:`reasons` whenever there are any, whatever the verdict.

**A reason is typed, because some formats already render it.** ``compat
--format junit`` turns each error diagnostic into its own ``<testcase>``,
with the path and commit a flat sentence would lose. Such a format must add
the reasons it does *not* already show, and only those, or it double-counts.
It says which it renders structurally (:func:`signals_other_than`) instead
of guessing from whether it happened to render anything — a guess that goes
wrong the day this module learns a reason that format never derived.

**Failure mode and guard (KTD1).** This is *bypass drift*: the facts were
always on the report, and call sites went around them. The guards are
therefore bypass guards — ``tests/meta/test_formatter_trust.py`` renders
every registered formatter against a report that is untrustworthy in each
way its kind can be, and walks the root Click group for commands whose code
never reaches this module.

**It fails closed.** A report type this module does not recognise raises
``TypeError``. Defaulting an unknown object to "trustworthy" would rebuild
the fail-open class inside the seam meant to end it: the next report kind
would silently render as success until someone remembered to come here.

**Every reason is one printable line.** A reason quotes diagnostic text a
rule pack or plugin wrote, and renderers print it next to stable,
grep-anchored prefixes (``error[lint-...]:``). A message carrying a newline
or an escape sequence could forge such a line, so every signal's text passes
through :func:`one_line` before it leaves this module. Text a renderer takes
from the report *directly* — a hook's annotation, a warning diagnostic — is
outside that guarantee unless the renderer calls :func:`one_line` itself,
which is why the function is public.

**Layer 0 (KTD8).** This module imports nothing from ``protokit`` at any
scope, so the report types cannot be named here. A kind is recognised by one
attribute only it has — ``truncated_paths``, ``entries``,
``breaking_commit``, ``runtime_warnings``, ``ranked``, ``divergences``,
``faults``, or ``findings`` last, because a ``LintReport`` has that one too. Some of those
carry the incompleteness signal and some (``breaking_commit``, ``findings``,
``divergences``) merely identify; what
they have in common is being a name no other kind answers to. Alongside it
this module requires ``diagnostics``, which every kind has, so an object
answering to neither is refused rather than waved through.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable
from typing import Any, NamedTuple

#: Analysis that did not complete — a selected rule that did not run, a
#: plugin that raised, an engine never reached: findings are a lower bound.
RULE_DID_NOT_RUN = "rule-did-not-run"
#: An error-level ``Diagnostic`` / ``CommitDiagnostic`` on the report. The
#: JUnit and SARIF renderers of compat, history and bisect already give each
#: one its own structured entry.
ERROR_DIAGNOSTIC = "error-diagnostic"
#: An error-level ``LintCompileDiagnostic``: the schema did not compile, so
#: no rule saw it. ``lint``'s own renderers show these separately.
COMPILE_DIAGNOSTIC = "compile-diagnostic"
#: ``max_depth`` cut the comparison above some subtrees.
TRUNCATION = "truncation"
#: A record a storage scan never read: a decode or framing fault that
#: ``--on-error skip`` / ``warn`` recovered past. The records that did come
#: out are a subset of the input, not the input.
RECORD_NOT_READ = "record-not-read"
#: A forensics candidate the ranking could not measure at all: a missing
#: proto2 ``required`` field left its modeled-byte fraction uncomputable, so
#: it never entered the contest and the winner won a smaller one.
#:
#: Deliberately NOT a candidate that merely failed to decode. That candidate
#: *was* measured -- it lost decisively, which is the ordinary result of
#: ranking one message against several schema versions, most of which are
#: not the one that produced it. Gating on it would make a healthy ranking
#: exit non-zero nearly every time. The case where *no* candidate parses is
#: still an error, caught by ``forensics match``'s own all-faulted check.
CANDIDATE_NOT_MEASURED = "candidate-not-measured"


class Signal(NamedTuple):
    """One reason a report cannot be read as success.

    Attributes:
        kind: Which of the four reason kinds above this is, so a renderer
            can tell the ones it already shows structurally from the ones
            it must add.
        text: One printable line, safe to print beside a stable prefix.
        commit: The commit a history/bisect reason belongs to, or ``None``.
        from_entry: True when a history reason came from an entry's own
            report, so the per-entry renderers already show it where the
            entry is.
    """

    kind: str
    text: str
    commit: str | None = None
    from_entry: bool = False


#: ``LintRuntimeWarning`` categories that mean a selected rule did not run,
#: so the findings are a lower bound on an unknown total (V33).
#:
#: ``all_files_excluded`` joined the pair the 0.15.1 gate shipped with (U8).
#: It fires when the user named inputs and an ``--exclude`` pattern dropped
#: *every one of them*, so the engine is short-circuited and never runs:
#: ``lint <schema> --exclude '*'`` rendered nothing and exited **0**, which is
#: the lint twin of V31 — a gate that silently stops gating. It cannot fire on
#: an ordinary run, because a filter that leaves one file standing lints that
#: file; the blast radius is confined to runs that already analysed nothing.
#:
#: Two categories that also mean a rule did not run remain ungated on purpose:
#: ``extension_unresolved`` and ``custom_annotation_extension_unresolved``.
#: The first fires on nearly every run whose inputs lack
#: ``google/api/field_behavior.proto``, so gating it would exit 2 almost
#: everywhere; the honest fix is to make that rule warn only when the schema
#: actually *uses* the extension, which is a redesign rather than a wider set
#: here, and is 0.17.0's. Widening this set is a breaking change either way;
#: ``TestIncompleteAnalysisCategoryClassification`` in
#: ``tests/schema/lint/test_model_dataclass_changes.py`` makes every category's
#: bucket an explicit decision rather than a default.
INCOMPLETE_ANALYSIS_CATEGORIES: frozenset[str] = frozenset({
    "rule_exception",
    "unloaded_rule",
    "all_files_excluded",
})


def one_line(text: str) -> str:
    """``text`` with every non-printable character replaced by a space.

    ``str.isprintable`` is false for the Unicode "Other" and "Separator"
    categories except the ASCII space: C0/C1 controls (newline, NUL, ESC,
    U+0085), and the line/paragraph separators U+2028/U+2029 that log
    aggregators split records on. Defined by Unicode category rather than a
    hand-kept list, so it needs nothing from ``protokit._cli_utils`` (which
    this layer-0 module may not import).

    Public because a renderer may print plugin-authored text this module
    never saw — a REPORT hook's annotation, a warning diagnostic — onto a
    line beside a stable prefix. One sanitizer, wherever such text lands.
    """
    if text.isprintable():
        return text
    return "".join(ch if ch.isprintable() else " " for ch in text)


def _diagnostic_text(d: Any) -> str:
    """``path: message`` when the diagnostic carries a path, else ``message``.

    Mirrors ``Diagnostic.__str__`` for the ``CommitDiagnostic`` shape, which
    has no ``__str__`` of its own: two plugin failures on the same commit
    differing only in path would otherwise read identically.
    """
    return f"{d.path}: {d.message}" if d.path else str(d.message)


def _commit_prefixed(commit: str | None, text: str) -> str:
    return f"{commit[:12]}: {text}" if commit else text


def _error_signals(diagnostics: Iterable[Any]) -> list[Signal]:
    """One ``ERROR_DIAGNOSTIC`` signal per error-level diagnostic, in order."""
    return [
        Signal(ERROR_DIAGNOSTIC, str(d))
        for d in diagnostics if d.level == "error"
    ]


def _diff_signals(result: Any) -> list[Signal]:
    out = _error_signals(result.diagnostics)
    if result.truncated_paths:
        paths = ", ".join(str(p) or "(root)" for p in result.truncated_paths)
        out.append(Signal(
            TRUNCATION,
            f"comparison truncated at max depth: "
            f"{len(result.truncated_paths)} subtree(s) not compared ({paths})",
        ))
    return out


def _compat_signals(report: Any) -> list[Signal]:
    return _error_signals(report.diagnostics)


def _aggregate_signals(
    diagnostics: Iterable[Any], already: Counter[tuple[str | None, str, str]],
) -> list[Signal]:
    """Aggregate ``CommitDiagnostic`` errors, minus restated per-entry ones.

    ``compat history`` builds the aggregate list by copying each entry's
    diagnostics, so a CLI-produced report states every entry error twice.
    Matched with multiplicity on commit, path and message, so two genuinely
    different failures on one commit both survive, and a deliberate repeat
    survives too.
    """
    out: list[Signal] = []
    for d in diagnostics:
        if d.level != "error":
            continue
        text = _diagnostic_text(d)
        key = (d.commit, d.path, d.message)
        if already[key]:
            already[key] -= 1
            continue
        out.append(Signal(
            ERROR_DIAGNOSTIC, _commit_prefixed(d.commit, text), commit=d.commit,
        ))
    return out


def _history_entry_errors(report: Any) -> list[tuple[str, Any]]:
    return [
        (entry.commit_sha, d)
        for entry in report.entries
        for d in entry.report.diagnostics
        if d.level == "error"
    ]


def _history_signals(report: Any) -> list[Signal]:
    entry_errors = _history_entry_errors(report)
    per_entry = [
        Signal(
            ERROR_DIAGNOSTIC, _commit_prefixed(sha, str(d)),
            commit=sha, from_entry=True,
        )
        for sha, d in entry_errors
    ]
    seen: Counter[tuple[str | None, str, str]] = Counter(
        (sha, d.path, d.message) for sha, d in entry_errors
    )
    return per_entry + _aggregate_signals(report.diagnostics, seen)


def _bisect_signals(report: Any) -> list[Signal]:
    return _aggregate_signals(report.diagnostics, Counter())


def _lint_signals(report: Any) -> list[Signal]:
    """Compile failures, then one signal per *rule* that did not run.

    The engine emits one runtime warning per dispatched element, so a single
    rule raising on a nine-field message produces nine warnings. Rendering
    those one-for-one would report nine rules as not having run; they are
    grouped here, at the owner, so every renderer counts rules.
    """
    out = [
        Signal(COMPILE_DIAGNOSTIC, str(d.message))
        for d in report.diagnostics if d.level == "error"
    ]
    groups: dict[tuple[str, str | None], list[Any]] = {}
    for w in report.runtime_warnings:
        if w.category in INCOMPLETE_ANALYSIS_CATEGORIES:
            groups.setdefault((w.category, w.rule_id), []).append(w)
    for (category, rule_id), warnings in groups.items():
        first = warnings[0]
        named = f"{rule_id}: " if rule_id else ""
        tail = f" (on {len(warnings)} elements)" if len(warnings) > 1 else ""
        out.append(Signal(
            RULE_DID_NOT_RUN, f"[{category}] {named}{first.message}{tail}",
        ))
    return out


#: ``CandidateFit.parse_outcome`` values that mean the candidate was never
#: measured at all: proto2-uninitialized, so the modeled byte count is
#: unavailable. ``decode_error`` is excluded on purpose -- see
#: :data:`CANDIDATE_NOT_MEASURED`. Both outcomes land in ``ParseTier.FAULT``,
#: so the tier is not the discriminator here.
_UNMEASURED_OUTCOMES: frozenset[str] = frozenset({"incomplete"})


def _match_signals(report: Any) -> list[Signal]:
    """Error diagnostics, then one signal per candidate that was not measured.

    A ranking answers "which of these schemas produced the message". A
    candidate whose modeled-byte fraction could not be computed did not lose
    that contest -- it never entered it -- so naming a winner over the
    remainder is a verdict over a smaller field than the user asked for.

    A candidate that merely failed to decode is the opposite case and costs
    no trust: it was measured and ruled out, which is what ranking a message
    against several schema versions is *for*. ``match`` still refuses the
    all-faulted case at the CLI, so a run where nothing parsed is an error
    rather than a ranking.
    """
    out = _error_signals(report.diagnostics)
    out.extend(
        Signal(
            CANDIDATE_NOT_MEASURED,
            f"{fit.label}: {fit.detail or fit.parse_outcome}",
        )
        for fit in report.ranked
        if fit.parse_outcome in _UNMEASURED_OUTCOMES
    )
    return out


def _scan_signals(report: Any) -> list[Signal]:
    """Error diagnostics, then one bounded signal for the records not read.

    ``--on-error skip`` / ``warn`` exist so a corrupt file still yields its
    good records; neither ever meant the scan read everything. One signal
    rather than one per fault, because a corrupt file can carry millions and
    ``warn`` has already streamed each to stderr -- the seam's job here is
    the verdict, not a second transcript of it.
    """
    out = _error_signals(report.diagnostics)
    if report.faults:
        first = f" (first: {report.first_fault})" if report.first_fault else ""
        out.append(Signal(
            RECORD_NOT_READ,
            f"{report.faults} record(s) were not read{first}",
        ))
    return out


def _drift_signals(report: Any) -> list[Signal]:
    """Error diagnostics only: a divergence is a finding, not an incompleteness.

    ``drift`` reconciles one message against one schema; each divergence is
    something it *found*, the analogue of a compat finding, and belongs on the
    findings rung rather than this one. The walk either completes or raises a
    typed error the CLI turns into exit 2, so the report has no partial state
    of its own. This exists so the kind is recognised rather than refused, and
    so a tool-level failure -- if forensics ever records one instead of
    raising -- cannot be read as success.
    """
    return _error_signals(report.diagnostics)


#: One row per report kind: the attribute whose presence identifies the kind,
#: and the function that reads its incompleteness signals. Order matters in
#: exactly one place: ``LintReport`` also has ``findings``, so the compat row
#: comes last and the lint row claims a ``LintReport`` first. ``diagnostics``
#: is deliberately not an identifying attribute — every kind carries it, so
#: it identifies none of them; it is required *alongside* the identifying one.
_KINDS: tuple[tuple[str, Callable[[Any], list[Signal]]], ...] = (
    ("runtime_warnings", _lint_signals),    # LintReport
    ("truncated_paths", _diff_signals),     # DiffResult
    ("entries", _history_signals),          # HistoryReport
    ("breaking_commit", _bisect_signals),   # BisectReport
    ("ranked", _match_signals),             # MatchReport
    ("divergences", _drift_signals),        # DriftReport
    ("faults", _scan_signals),              # storage's per-run scan report
    ("findings", _compat_signals),          # CompatibilityReport
)


def signals(report: object) -> tuple[Signal, ...]:
    """Every reason ``report`` cannot be read as success, typed.

    Args:
        report: A ``DiffResult``, ``CompatibilityReport``, ``HistoryReport``,
            ``BisectReport``, ``LintReport``, ``MatchReport`` or
            ``DriftReport``.

    Returns:
        Signals in emission order; empty when the report is trustworthy.
        Every ``text`` is a single printable line. An advisory
        warning-level diagnostic never appears; a lint *runtime* warning
        does, when its category is in ``INCOMPLETE_ANALYSIS_CATEGORIES``.

    Raises:
        TypeError: ``report`` is not one of the known kinds. Never defaults
            to trustworthy.
    """
    if hasattr(report, "diagnostics"):
        for attribute, fn in _KINDS:
            if hasattr(report, attribute):
                return tuple(
                    s._replace(text=one_line(s.text)) for s in fn(report)
                )
    raise TypeError(
        f"protokit._trust does not know how to vouch for "
        f"{type(report).__name__!r}: it carries none of the attributes a "
        f"protokit report records incompleteness on "
        f"({', '.join(a for a, _ in _KINDS)}). Refusing to default to "
        f"trustworthy.",
    )


def reasons(report: object) -> tuple[str, ...]:
    """The text of every signal, for a renderer that shows them as lines.

    Args:
        report: One of the known report kinds; see :func:`signals`.

    Returns:
        One printable line per reason, in emission order.

    Raises:
        TypeError: ``report`` is not one of the known kinds.
    """
    return tuple(s.text for s in signals(report))


def signals_other_than(
    report: object, kind: str, *, only_from_entries: bool = False,
) -> tuple[Signal, ...]:
    """Signals a format does not already render structurally.

    A machine renderer that turns every error diagnostic into its own
    ``<testcase>`` passes ``ERROR_DIAGNOSTIC`` and gets back what it has not
    shown — nothing today, and whatever this module learns tomorrow.

    Args:
        report: One of the known report kinds.
        kind: The signal kind the caller renders itself.
        only_from_entries: For ``HistoryReport``: the caller renders each
            *entry's* diagnostics inside that entry's suite, so only
            entry-level signals of ``kind`` are already shown. A
            walk-level one is not, and is returned.

    Returns:
        The signals the caller still has to render.

    Raises:
        TypeError: ``report`` is not one of the known kinds.
    """
    return tuple(
        s for s in signals(report)
        if s.kind != kind or (only_from_entries and not s.from_entry)
    )


def walk_level_reasons(report: object) -> tuple[str, ...]:
    """A ``HistoryReport``'s reasons that no entry carries.

    The per-commit renderers (``history_junit``'s one suite per entry) show
    each entry's own errors where the entry is; this is the remainder -- an
    aggregate error attributed to a commit with no entry, or to none -- which
    they would otherwise drop (V23's fourth site).

    Raises:
        TypeError: ``report`` is not one of the known kinds.
    """
    return tuple(s.text for s in signals(report) if not s.from_entry)


def is_trustworthy(report: object) -> bool:
    """Whether an empty ``report`` means "nothing found" rather than "did not look".

    Args:
        report: One of the known report kinds; see :func:`signals`.

    Returns:
        True iff :func:`signals` is empty.

    Raises:
        TypeError: ``report`` is not one of the known kinds.
    """
    return not signals(report)
