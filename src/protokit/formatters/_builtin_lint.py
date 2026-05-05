"""Built-in LINT_REPORT formatters.

D3 ships ``human`` only. D4 will extend this module with
``json`` / ``junit`` / ``sarif`` formatters under the same
``FormatterKind.LINT_REPORT`` discriminator.

Cold-import contract: this module is **NOT** in the eager-load
tuple at ``src/protokit/formatters/__init__.py`` — preserves
D1's cold-import gate (``import protokit.schema`` does not
transitively load ``protokit.schema.lint`` or this module).
``protokit.schema.lint.cli`` imports this module at its module
top, which triggers the formatter registration as a side
effect at ``protokit.cli`` load time (i.e., on every
``protokit ...`` CLI invocation, regardless of which
subcommand fires).

Registration uses the internal ``_register_builtin`` helper
(idempotent under module reload + reserves the ``human`` name in
``_BUILTIN_NAMES``) rather than the public ``register_formatter``
which would raise ``FormatterError`` on the second import.
"""

from __future__ import annotations

from protokit.formatters._registry import (
    FormatterContext,
    FormatterKind,
    _register_builtin,
)
from protokit.schema.compile import LintCompileDiagnostic
from protokit.schema.lint.model import LintFinding, LintReport, LintRuleSpec


def _render_message(finding: LintFinding, spec: LintRuleSpec | None) -> str:
    """Interpolate a finding's params into its rule's message template.

    Falls back to a generic ``{rule_id}`` rendering when the
    spec is unavailable (e.g., a finding produced by a rule that
    was unloaded between ``run()`` and rendering, or if the
    engine produced findings without populating ``LintReport.specs``).
    Multi-kind rules (templates as ``dict[str, str]``) are
    looked up by ``finding.violation_kind``.

    Returns the rendered human-readable message string.
    """
    if spec is None:
        return f"{finding.rule_id}"

    template = spec.message_template
    if isinstance(template, dict):
        # Multi-kind rule: look up by violation_kind. Fall back to
        # a generic rendering if the kind is missing from the dict
        # (defensive — rule authors should declare every kind they
        # emit, but a typo shouldn't crash the formatter).
        template_str = template.get(finding.violation_kind, finding.rule_id)
    else:
        template_str = template

    if not template_str:
        return f"{finding.rule_id}"

    # TODO(D6): when user `--rule-pack`s ship, sandbox this format()
    # call. ``str.format(**params)`` lets a template author specify
    # large width specifiers (``{name:>1000000}`` produces a 1M-char
    # string — memory DoS) and traverse attributes
    # (``{name.__class__.__bases__}`` walks Python's type hierarchy).
    # For D3-D5 this is internal-pack-only (we control the templates),
    # so the threat surface is bounded. D6's brainstorm should design
    # the holistic plugin-security model alongside the `--rule-pack`
    # flag's user contract.
    try:
        return template_str.format(**finding.params)
    except (KeyError, IndexError, ValueError, AttributeError, TypeError):
        # Defensive: every exception ``str.format`` can raise from a
        # rule-author template + caller-supplied params:
        #   - ``KeyError``: missing param key (``"{missing}"``).
        #   - ``IndexError``: positional placeholder out of range
        #     (``"{0}"`` with empty params).
        #   - ``ValueError``: malformed format spec (``"{x:invalid}"``).
        #   - ``AttributeError``: dotted access on a value lacking
        #     the attribute (``"{name.bad}"`` against a string).
        #   - ``TypeError``: format-protocol mismatch (``"{name[0]}"``
        #     against an int) or ``__format__`` returning non-str.
        # Surface the rule_id + raw params rather than crashing the
        # whole render. Rule-author bugs become visible findings,
        # not lint-tool crashes.
        return f"{finding.rule_id} {finding.params!r}"


def _render_finding_line(finding: LintFinding, spec: LintRuleSpec | None) -> str:
    """Format a single finding as one grep-friendly line.

    Format:
        ``{SEVERITY} {location} [{rule_id}] {message}``

    Example:
        ``WARNING acme/user.proto:acme.User.bad_field [naming/snake-case-fields] Field 'bad_field' is not snake_case (AIP-122)``
    """
    severity = finding.severity.name  # "INFO" / "WARNING" / "ERROR"
    location = str(finding.location)
    message = _render_message(finding, spec)
    return f"{severity} {location} [{finding.rule_id}] {message}"


def lint_human(report: LintReport, _ctx: FormatterContext) -> str:
    """Render a LintReport as human-readable plaintext.

    Output shape: one finding per line in walk-emission order.
    For clean runs (no findings, no diagnostics), returns an empty
    string — the CLI is responsible for any "no findings" sentinel
    or the ``--statistics`` footer (see Unit 4 in the D3 plan).

    Findings render as::

        SEVERITY location [rule_id] interpolated message
        SEVERITY location [rule_id] interpolated message
        ...

    Compile diagnostics (when present) render before findings::

        diagnostic[CATEGORY]: message
        ...
        SEVERITY location [rule_id] message

    The ``--statistics`` footer is rendered by the CLI callback
    (Unit 4), NOT by this formatter — keeps the formatter pure
    so that machine formats (D4 json/junit/sarif) which embed
    counts in their structured payloads can reuse the same
    ``LintReport`` input without footer-stripping logic.

    The function is named ``lint_human`` (not ``_render_human``)
    to match the sibling-pattern parity convention established by
    ``_builtin_diff.diff_human`` / ``_builtin_compat.compat_human`` /
    ``_builtin_history.history_human`` / ``_builtin_bisect.bisect_human``
    — see ``docs/solutions/best-practices/audit-wire-format-before-claiming-sibling-parity-2026-05-03.md``.

    Args:
        report: The lint pass result to render.
        _ctx: Reserved for future per-CLI-flag rendering. Currently
            unused; underscore prefix marks the parameter as
            intentionally ignored without forcing a ``del``.
    """
    lines: list[str] = []

    # Compile diagnostics first (when source-mode compile produced
    # info / warning / error notes). Findings come after so they're
    # the focus when both are present. The loop variable's static
    # type is ``LintCompileDiagnostic`` (not ``Any``-via-getattr) so
    # mypy narrows correctly and any future shape change to the type
    # surfaces as a static error rather than silently masking via
    # defensive fallbacks.
    diag: LintCompileDiagnostic
    for diag in report.diagnostics:
        lines.append(f"diagnostic[{diag.category}]: {diag.message}")

    for finding in report.findings:
        spec = report.specs.get(finding.rule_id)
        lines.append(_render_finding_line(finding, spec))

    return "\n".join(lines)


# Idempotent registration at module import. The lint subcommand
# module imports this module at its top — see module docstring.
_register_builtin(name="human", fn=lint_human, kind=FormatterKind.LINT_REPORT)
