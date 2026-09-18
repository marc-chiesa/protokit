"""Built-in DIFF formatters: human and json.

Renders :class:`protokit.message.DiffResult` for the
``protokit diff`` CLI. The rendering logic was previously
inlined in ``protokit.message.cli`` as ``_format_diff_human`` /
``_serialize_value`` / ``_output_human`` / ``_output_json``;
it now lives here so the formatter registry owns it.

Note on ``--verbose`` semantics: the existing CLI suppresses
diagnostics on the equal-result path unless ``--verbose`` is
set. This formatter always renders diagnostics when present —
the CLI handles the equal-and-not-verbose case by short-
circuiting before invoking the formatter (Unit 5).
"""

from __future__ import annotations

import base64
import json
import math
from typing import Any

import click

from protokit import _trust
from protokit.formatters import _junit_xml as junit
from protokit.formatters._registry import (
    FormatterContext,
    FormatterKind,
    _register_builtin,
)
from protokit.message.model import (
    ChangeType,
    Difference,
    DiffResult,
    EnumValue,
)

_CHANGE_SYMBOLS = {
    ChangeType.ADDED: ("+", "green"),
    ChangeType.REMOVED: ("-", "red"),
    ChangeType.MODIFIED: ("~", "yellow"),
    ChangeType.TYPE_CHANGED: ("T", "magenta"),
    ChangeType.FIELD_NUMBER_CHANGED: ("#", "cyan"),
    ChangeType.CARDINALITY_CHANGED: ("C", "blue"),
}


def _annotation_suffix(diff: Difference) -> str:
    """REPORT-hook annotations as a trailing `` [a; b]``, matching ``str(diff)``.

    A hook calling ``ctx.annotate(...)`` attaches an explanation to a
    difference; before V25 closed, no built-in format emitted it, so the
    feature was write-only.
    """
    if not diff.annotations:
        return ""
    return f" [{'; '.join(diff.annotations)}]"


def _format_diff_human(diff: Difference) -> str:
    """Format a single Difference as a colored line, annotations included."""
    line = _format_change_human(diff)
    if diff.annotations:
        line += click.style(_annotation_suffix(diff), dim=True)
    return line


def _format_change_human(diff: Difference) -> str:
    """Format the change itself as a colored single-line string.

    Imported lazily to avoid a circular import — the value
    formatter lives in ``protokit.message.formatting`` which
    is itself imported from ``protokit.message`` at package
    load time.
    """
    from protokit.message.formatting import format_value as _format_value

    symbol, color = _CHANGE_SYMBOLS[diff.change_type]
    path_str = str(diff.path) if diff.path else "(root)"
    prefix = click.style(f"  {symbol} ", fg=color, bold=True)

    match diff.change_type:
        case ChangeType.ADDED:
            val = _format_value(diff.right_value)
            return (
                f"{prefix}{click.style(path_str, bold=True)}: "
                f"{click.style(val, fg='green')}"
            )
        case ChangeType.REMOVED:
            val = _format_value(diff.left_value)
            return (
                f"{prefix}{click.style(path_str, bold=True)}: "
                f"{click.style(val, fg='red')}"
            )
        case ChangeType.MODIFIED:
            old = _format_value(diff.left_value)
            new = _format_value(diff.right_value)
            return (
                f"{prefix}{click.style(path_str, bold=True)}: "
                f"{click.style(old, fg='red')} → {click.style(new, fg='green')}"
            )
        case ChangeType.TYPE_CHANGED:
            return (
                f"{prefix}{click.style(path_str, bold=True)}: "
                f"type {click.style(str(diff.left_type), fg='red')} → "
                f"{click.style(str(diff.right_type), fg='green')}"
            )
        case ChangeType.FIELD_NUMBER_CHANGED:
            return (
                f"{prefix}{click.style(path_str, bold=True)}: "
                f"field# {click.style(str(diff.left_field_number), fg='red')} → "
                f"{click.style(str(diff.right_field_number), fg='green')}"
            )
        case ChangeType.CARDINALITY_CHANGED:
            return (
                f"{prefix}{click.style(path_str, bold=True)}: "
                f"{click.style(str(diff.left_label), fg='red')} → "
                f"{click.style(str(diff.right_label), fg='green')}"
            )
    raise AssertionError(f"Unhandled change type: {diff.change_type}")  # unreachable


def _advisory_lines(result: DiffResult) -> list[str]:
    """Every non-error diagnostic, one yellow line each."""
    return [
        click.style(f"  ⚠ {d}", fg="yellow")
        for d in result.diagnostics if d.level != "error"
    ]


def _untrusted_lines(result: DiffResult) -> list[str]:
    """``protokit._trust``'s reasons, one red line each.

    Error diagnostics and the ``max_depth`` truncation both arrive this way,
    in the seam's words: the renderer shows why the verdict was withheld
    exactly as the seam decided it, rather than re-deriving it from
    ``result.errors`` and ``result.is_complete`` side by side.
    """
    return [
        click.style(f"  ✗ {reason}", fg="red")
        for reason in _trust.reasons(result)
    ]


def diff_human(result: DiffResult, ctx: FormatterContext) -> str:
    """Render a DiffResult as colored human-readable text.

    Always renders diagnostics and truncation notices when
    present. The CLI is responsible for short-circuiting the
    equal-and-not-verbose case before calling this — see
    module docstring.

    Args:
        result: The DiffResult to render.
        ctx: Formatter context (unused).

    Returns:
        A multi-line string. A result with no differences returns the
        single line ``"Messages are equal."`` only when
        ``protokit._trust`` vouches for it. Otherwise there is no
        equality to assert, and the first line says why instead: the
        comparison is not trustworthy (an error diagnostic), or it is
        INCOMPLETE (``max_depth`` truncated it). A result with
        differences returns a header, body of diff lines, and trailing
        diagnostic / truncation blocks.
    """
    del ctx
    lines: list[str] = []

    if not result.has_changes():
        if _trust.is_trustworthy(result):
            lines.append(click.style("Messages are equal.", fg="green"))
        elif result.errors:
            # Never claim equality the engine cannot vouch for. An error means
            # the comparison itself broke, so "no differences" is the absence
            # of a finding, not a verdict — and a green success line above a
            # red error is the most misleading thing this formatter could say.
            lines.append(click.style(
                "No differences found, but the comparison is not trustworthy:",
                fg="red", bold=True,
            ))
        else:
            # V24: ``max_depth`` stopped the walk above some subtrees, so "no
            # differences" covers only what was looked at. The model has
            # always known (``is_complete``); this renderer did not ask.
            lines.append(click.style(
                "INCOMPLETE: no differences found above the max-depth cut, "
                "but the comparison did not finish:",
                fg="red", bold=True,
            ))
        lines.extend(_advisory_lines(result))
        lines.extend(_untrusted_lines(result))
        return "\n".join(lines)

    plural = "s" if len(result) != 1 else ""
    lines.append(click.style(
        f"Found {len(result)} difference{plural}:", bold=True,
    ))
    lines.append("")
    for diff in result:
        lines.append(_format_diff_human(diff))

    # A found difference is definitive, so the header above needs no consent
    # from the seam -- but the list may still be partial, and says so.
    untrusted = _untrusted_lines(result)
    if untrusted:
        lines.append("")
        lines.append(click.style(
            "Not trustworthy — there may be more differences:",
            fg="red", bold=True,
        ))
        lines.extend(untrusted)
    advisory = _advisory_lines(result)
    if advisory:
        lines.append("")
        lines.append(click.style("Warnings:", fg="yellow", bold=True))
        lines.extend(advisory)

    return "\n".join(lines)


def _serialize_value(val: object) -> Any:
    """Serialize a Difference value for JSON output.

    Handles ``None``, ``EnumValue``, ``bytes`` (base64), ``bool``,
    finite floats, and special floats (NaN/Infinity rendered as
    ``{"special_float": "..."}``).
    """
    if val is None:
        return None
    if isinstance(val, EnumValue):
        return {"name": val.name, "number": val.number}
    if isinstance(val, bytes):
        return base64.b64encode(val).decode("ascii")
    if isinstance(val, bool):
        return val  # check before int — bool is a subclass of int
    if isinstance(val, float):
        if math.isnan(val):
            return {"special_float": "NaN"}
        if math.isinf(val):
            return {"special_float": "Infinity" if val > 0 else "-Infinity"}
        return val
    return val


#: Schema version for the ``protokit diff --format json`` output (single source
#: of truth for the value).
#:
#: Bump on any output-shape change: a new or removed top-level key, or a changed
#: key meaning. Open-ended additions a forward-compatible consumer can ignore do
#: not bump. ``"0.1"`` -> ``"0.2"`` (0.16.0): ``equal`` changed meaning -- it is
#: now false for a truncated or errored comparison that found no differences --
#: alongside the new ``complete`` / ``truncated_paths`` top-level keys and the
#: per-entry ``annotations`` key. The next bump is at protokit 1.0, when the
#: deprecated ``old_value`` / ``new_value`` entry keys are removed.
#:
#: Absence semantic: output from protokit versions before this field existed
#: carries no ``schema_version`` key. Consumers must treat a missing key as a
#: known-older format (pre-this-release), not as a malformed response.
_DIFF_JSON_SCHEMA_VERSION = "0.2"  # PROTO_1_0_REMOVE: bump when old/new keys drop


def _set_value_keys(entry: dict[str, Any], left: Any, right: Any) -> None:
    """Populate the value-pair keys on a JSON diff entry.

    Canonical keys are ``left_value`` / ``right_value``. ``old_value`` /
    ``new_value`` are deprecated duplicate keys, removed in protokit 1.0. Every
    entry carries all four (``None`` for schema-evolution change types) so the
    shape is uniform across change types.
    """
    entry["left_value"] = left
    entry["right_value"] = right
    entry["old_value"] = left  # PROTO_1_0_REMOVE
    entry["new_value"] = right  # PROTO_1_0_REMOVE


def diff_json(result: DiffResult, ctx: FormatterContext) -> str:
    """Render a DiffResult as pretty-printed JSON.

    Top-level keys: ``schema_version`` (str), ``equal`` (bool), ``complete``
    (bool), ``truncated_paths`` (list of str), ``differences`` (list of dicts
    whose shape depends on ``change_type``), ``diagnostics`` (list of dicts).
    ``equal`` is true only when no difference was found **and** the comparison
    can be trusted: a ``max_depth``-truncated result (``complete`` false, the
    cut subtrees in ``truncated_paths``) or one carrying an error diagnostic is
    never ``equal``. The object is open/additive -- consumers should ignore
    unknown keys. Each entry carries canonical ``left_value`` / ``right_value``
    plus deprecated ``old_value`` / ``new_value`` (removed at 1.0; gate on
    ``schema_version`` to detect the change), and ``annotations`` (list of str,
    empty when no REPORT hook annotated the difference).

    Args:
        result: The DiffResult to render.
        ctx: Formatter context (unused).

    Returns:
        A JSON string with two-space indentation. Falls back to
        ``str()`` for objects that aren't directly JSON-serializable
        (matches the legacy ``default=str`` behavior).
    """
    del ctx
    diffs: list[dict[str, Any]] = []
    for d in result:
        entry: dict[str, Any] = {
            "path": str(d.path) if d.path else "",
            "change_type": d.change_type.value,
        }
        # _set_value_keys writes all four value keys (canonical left/right +
        # deprecated old/new) so every entry's shape is uniform across change
        # types. Read the real fields (not the deprecated .old_value/.new_value
        # properties) so the renderer doesn't trip its own deprecation warning.
        match d.change_type:
            case ChangeType.ADDED | ChangeType.REMOVED | ChangeType.MODIFIED:
                _set_value_keys(
                    entry, _serialize_value(d.left_value), _serialize_value(d.right_value)
                )
                entry["field_type"] = d.field_type
            case ChangeType.TYPE_CHANGED:
                _set_value_keys(entry, None, None)
                entry["field_type"] = None
                entry["left_type"] = d.left_type
                entry["right_type"] = d.right_type
            case ChangeType.FIELD_NUMBER_CHANGED:
                _set_value_keys(entry, None, None)
                entry["field_type"] = d.field_type
                entry["left_field_number"] = d.left_field_number
                entry["right_field_number"] = d.right_field_number
            case ChangeType.CARDINALITY_CHANGED:
                _set_value_keys(entry, None, None)
                entry["field_type"] = d.field_type
                entry["left_label"] = d.left_label
                entry["right_label"] = d.right_label
        entry["annotations"] = list(d.annotations)
        diffs.append(entry)

    diagnostics = [
        {"level": d.level, "path": d.path, "message": d.message}
        for d in result.diagnostics
    ]
    output = {
        "schema_version": _DIFF_JSON_SCHEMA_VERSION,
        # ``equal`` is a verdict, so it needs the seam's consent: a truncated
        # or errored comparison that found nothing has not shown equality.
        "equal": _trust.is_trustworthy(result) and not result.has_changes(),
        "complete": result.is_complete,
        "truncated_paths": [str(p) for p in result.truncated_paths],
        "differences": diffs,
        "diagnostics": diagnostics,
    }
    return json.dumps(output, indent=2, default=str)


def _difference_line(diff: Difference) -> str:
    """Single-line summary of a Difference for JUnit failure body.

    Plain text, no ANSI colors, no Unicode arrows — keeps the
    body parseable by CI consumers that surface failure text
    in HTML or terminal-unaware contexts.
    """
    return _change_line(diff) + _annotation_suffix(diff)


def _change_line(diff: Difference) -> str:
    """The change-type-specific part of :func:`_difference_line`."""
    path = str(diff.path) if diff.path else "(root)"
    match diff.change_type:
        case ChangeType.ADDED:
            return f"+ {path}: {diff.right_value!r}"
        case ChangeType.REMOVED:
            return f"- {path}: {diff.left_value!r}"
        case ChangeType.MODIFIED:
            return f"~ {path}: {diff.left_value!r} -> {diff.right_value!r}"
        case ChangeType.TYPE_CHANGED:
            return f"T {path}: type {diff.left_type} -> {diff.right_type}"
        case ChangeType.FIELD_NUMBER_CHANGED:
            return (
                f"# {path}: field# {diff.left_field_number} -> "
                f"{diff.right_field_number}"
            )
        case ChangeType.CARDINALITY_CHANGED:
            return f"C {path}: {diff.left_label} -> {diff.right_label}"
    raise AssertionError(f"unhandled change type: {diff.change_type}")  # unreachable


def diff_junit(result: DiffResult, ctx: FormatterContext) -> str:
    """Render a DiffResult as JUnit XML using a binary-result pattern.

    Emits a single ``<testsuite>`` containing exactly one
    ``<testcase>``. The case passes when ``result.has_changes()``
    is False; otherwise it carries a ``<failure>`` whose body
    lists each Difference on its own line.

    Rationale (see plan Key Technical Decisions): a diff is one
    assertion ("these messages are equal") with per-field
    differences as evidence of the single failure. Per-difference
    testcase rendering would produce "100 tests / 100 failures"
    noise in CI aggregators with no extra signal vs.
    "1 test / 1 failure with 100 lines of body."

    Args:
        result: The DiffResult to render.
        ctx: Formatter context (used only for warning attribution
            via ``<system-out>``).

    Returns:
        UTF-8 XML string with the standard prolog.
    """
    del ctx
    has_changes = result.has_changes()
    n = len(result)
    failures = 1 if has_changes else 0
    # An error-level diagnostic means the tool itself broke (plugin crash,
    # hook exception), and Diagnostic's contract is that CI must treat it as
    # fail-closed EVEN WHEN no differences were found. Counting it here is
    # what stops an equal-but-broken comparison rendering as a green job. A
    # ``max_depth`` truncation is the same shape (V24) -- "found nothing" over
    # a walk that did not finish -- so the seam, not ``result.errors``, decides.
    untrusted = _trust.reasons(result)
    errors = 1 if untrusted else 0
    # One testcase for the comparison verdict, plus one for the integrity
    # diagnostics when present. ``tests`` counts CASES, not conditions, so
    # ``tests - failures - errors`` never goes negative for an aggregator
    # deriving a pass count that way (GitLab, some Jenkins renderers).
    tests = 1 + errors

    suite = junit.make_testsuite(
        name="protokit-diff",
        tests=tests,
        failures=failures,
        errors=errors,
    )
    case = junit.make_testcase(
        classname="diff", name="messages-equal",
    )
    if has_changes:
        body = "\n".join(_difference_line(d) for d in result)
        plural = "s" if n != 1 else ""
        junit.append_failure(
            case,
            message=f"{n} difference{plural} found",
            type_="diff",
            body=body,
        )
    junit.add_testcase(suite, case)
    if untrusted:
        # A failure is "the messages differ" (a real verdict); an error is
        # "the comparison itself is untrustworthy". They can co-occur, but
        # they must NOT share a testcase: the JUnit schema models
        # <testcase>'s content as a choice of AT MOST ONE of
        # skipped|error|failure, so emitting both produces a document strict
        # consumers reject — and a rejected report reads as "no test results"
        # in several CI systems, which is the very green-on-broken outcome
        # counting the diagnostic exists to prevent. Own testcase, matching
        # _builtin_compat / _builtin_bisect / _builtin_lint.
        error_case = junit.make_testcase(
            classname="diagnostic", name="comparison-integrity",
        )
        junit.append_error(
            error_case,
            message=f"{len(untrusted)} reason(s) the comparison cannot be trusted",
            type_="diagnostic",
            body="\n".join(untrusted),
        )
        junit.add_testcase(suite, error_case)
    if result.warnings:
        junit.append_system_out(
            suite, "\n".join(str(d) for d in result.warnings),
        )

    # Emit <testsuite> as root (the xsd's standalone form). The
    # aggregating <testsuites> wrapper is reserved for HISTORY,
    # which the xsd requires to set package/id on each child.
    return junit.serialize(suite)


_register_builtin("human", diff_human, kind=FormatterKind.DIFF)
_register_builtin("json", diff_json, kind=FormatterKind.DIFF)
_register_builtin("junit", diff_junit, kind=FormatterKind.DIFF)
