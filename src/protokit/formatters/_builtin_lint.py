"""Built-in LINT_REPORT formatters.

D3 ships all four lint formatters: ``human``, ``json``,
``junit``, ``sarif`` (the original D3+D4 split was reversed
during D3 brainstorm pressure-test pass per KD-5 — half-formatter
parity damaged the CI-auditability identity bet, so D3 absorbs
the original D4 scope). All four are registered under the same
``FormatterKind.LINT_REPORT`` discriminator. Unit 1 shipped
``human`` first (commit ``c610dae``); the three machine
formatters land in U4.

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

    # ``str.format(**params)`` is a D3-present trust-boundary: R8
    # lets users load `--rule-pack` modules whose `LintRuleSpec`
    # objects control these templates AND ``LintFinding.params``
    # is typed ``dict[str, Any]`` so a user pack can store
    # objects with custom ``__format__`` methods that can raise
    # arbitrary ``Exception`` subclasses (``OverflowError``,
    # ``ZeroDivisionError``, ``StopIteration``, etc.). The catch
    # is a bare ``except Exception`` rather than a named tuple
    # so that buggy or malicious user-pack templates produce a
    # graceful rule_id fallback rather than crashing the
    # formatter mid-render and dropping every subsequent
    # finding.
    #
    # Threats acknowledged but NOT fully mitigated by this catch:
    #   - Width-specifier OS OOM-kill: ``"{x:>10000000000}"`` may
    #     allocate a large string before any Python exception
    #     fires; the OS OOM-killer terminates the process before
    #     the catch runs. Defense requires a width-cap pre-check
    #     (deferred to D6 holistic plugin-security model).
    #   - Attribute-traversal information disclosure:
    #     ``"{name.__class__.__mro__}"`` returns successfully
    #     and renders into output. No exception fires; the
    #     catch is irrelevant. Defense requires template
    #     validation/sanitization (deferred to D6).
    #
    # TODO(D6): the holistic plugin-security model — whitelist
    # of safe format specs / pre-flight regex rejection of
    # unsafe traversal patterns / safe-eval substitute — lands
    # alongside the `--rule-pack` user-contract design. The
    # broad ``except Exception`` here is defense-in-depth
    # against crash-recovery, not a complete solution.
    try:
        return template_str.format(**finding.params)
    except Exception:
        # Defensive: any Exception from str.format or a user
        # pack's custom __format__ method routes through a
        # graceful rule_id + raw params fallback. Common cases:
        #   - ``KeyError``: missing param key (``"{missing}"``).
        #   - ``IndexError``: positional placeholder out of range.
        #   - ``ValueError``: malformed format spec or excess
        #     nesting (``"{x:{y:{z}}}"``).
        #   - ``AttributeError``: dotted access on a value
        #     lacking the attribute.
        #   - ``TypeError``: format-protocol mismatch or
        #     ``__format__`` returning non-str.
        #   - ``MemoryError``: rare; user-pack ``__format__``
        #     allocates internally and exhausts memory before
        #     OS OOM-kill.
        #   - ``RecursionError``: deeply-recursive user-pack
        #     ``__format__``.
        #   - Any other ``Exception`` subclass from a custom
        #     ``__format__`` implementation in user-pack params.
        # ``BaseException`` (KeyboardInterrupt, SystemExit) is
        # NOT caught — those propagate normally so users can
        # cancel with Ctrl-C and the run_formatter_safely outer
        # SystemExit guard catches sys.exit() bypass attempts.
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
    so that machine formats (``lint_json`` / ``lint_junit`` /
    ``lint_sarif``, also shipped in D3 per KD-5 revised) which
    embed counts in their structured payloads can reuse the same
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
