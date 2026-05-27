"""``options/deprecated_replacement`` rule pack — R6 family.

Five comment-aware lint rules that flag ``*Options.deprecated = true``
declarations whose leading comment lacks a recognized replacement
phrasing. One rule per ``*Options.deprecated`` ElementKind:

- ``options/deprecated-field-must-have-replacement-comment`` (FIELD)
- ``options/deprecated-enum-value-must-have-replacement-comment`` (ENUM_VALUE)
- ``options/deprecated-method-must-have-replacement-comment`` (METHOD)
- ``options/deprecated-message-must-have-replacement-comment`` (MESSAGE)
- ``options/deprecated-enum-must-have-replacement-comment`` (ENUM)

All five share a single ``_check_replacement_comment(text: str | None) -> bool``
helper and a module-level ``_REPLACEMENT_PATTERNS`` tuple of compiled
regexes. The heuristic is intentionally narrow (precision-first); real-world
deprecation comments use a wide variety of phrasings, so the starting
4-pattern set is tuned for high precision and accepts some false
negatives as a deliberate trade — see the parent brainstorm + per-unit
plan for the rationale.

**Profile.** All 5 rules ship in the ``default`` profile only. The
``recommended`` profile stays at buf BASIC parity — R6 has no buf
analogue and would dilute the parity claim. Users targeting the full
protokit capability via ``--profile default`` see R6 findings; users
targeting buf BASIC parity via ``--profile recommended`` do not.

**Severity.** All 5 rules ship at ``error`` severity in the ``default``
profile (promoted from the initial ``warning``). The current contract:
deprecated elements MUST carry a replacement reference in their
leading comment, or be explicitly disabled via the R9b mechanisms
(``[severities] "<rule_id>" = "off"`` or ``disabled_rules`` /
``--disable-rule``). The promotion was gated by an empirical hit-rate
validation against googleapis (200-file sample, seed=42): 19 hits
across 10 files, 0 noisy classifications. See the CHANGELOG entry for
the worked migration recipe; the heuristic regex is unchanged
(precision-first; some legitimate replacement phrasings still miss,
and R9b is the documented escape hatch).

**Sanitization.** Each finding's ``params["comment"]`` carries the
leading comment text (truncated to 500 chars) after running through the
existing ``_safe_for_stderr`` sanitizer to neutralize newlines, control
chars, and U+2028/U+2029 separators per the runtime-warning threat
model. The truncated + sanitized comment then has ``{`` / ``}``
characters doubled
(``.replace("{", "{{").replace("}", "}}")``) so
``message_template.format(**params)`` cannot raise ``KeyError`` on
adversarial input.

**Buf parity.** Each of the 5 rules carries ``source_spec=""`` (empty)
to exclude it from the parity harness — R6 has no buf analogue, per
the buf-parity-divergence documentation discipline (see the matching
learning under ``docs/solutions/``). The rule docstrings document this
protokit-original status explicitly so the delivery-boundary unit's
presence ratchet can assert on the substring.

**Descriptor-set-mode caveat.** When a descriptor set is loaded without
``protoc --include_source_info``, the captured ``FileDescriptorProto``
references will have empty ``source_code_info.location[]`` arrays. The
:func:`leading_comment` helper returns ``None`` for every lookup,
:func:`_check_replacement_comment` returns ``False`` for ``None`` input,
and the rules emit findings for every deprecated element in the schema.
This over-reporting is documented in the 0.3.0 CHANGELOG entry; the
workarounds are (a) regenerate the descriptor set with
``--include_source_info``, (b) lint via ``--proto`` mode instead,
(c) demote the R6 rules via ``[tool.protokit.lint.severities]`` (e.g.,
``"options/deprecated-field-must-have-replacement-comment" = "warning"``),
or (d) disable them per-rule via the R9b mechanisms
(``[severities] "<rule_id>" = "off"``, ``disabled_rules = [...]``, or
``--disable-rule <rule_id>``). A runtime ``LintCompileDiagnostic`` for
the absent-source-info case is deferred to a future delivery.

References:

- See the project's design notes for the R6 deprecated-replacement
  brainstorm and plan.
- Shared comment helpers:
  ``protokit.schema.lint.rules.options._comments``
  (``descriptor_path`` + ``leading_comment``)
- Shared sanitizer:
  ``protokit.schema.lint._cli_utils._safe_for_stderr``
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import TYPE_CHECKING

from protokit.schema.lint._cli_utils import _safe_for_stderr
from protokit.schema.lint.decorator import lint_rule
from protokit.schema.lint.model import ElementKind, LintSeverity
from protokit.schema.lint.rules.options._comments import (
    descriptor_path,
    leading_comment,
)

if TYPE_CHECKING:
    from protokit.schema.lint.model import (
        EnumLintContext,
        EnumValueLintContext,
        FieldLintContext,
        MessageLintContext,
        MethodLintContext,
    )


# ---------------------------------------------------------------------------
# Shared helper + regex patterns
# ---------------------------------------------------------------------------

#: Recognized replacement-phrasing patterns. The starting 4-pattern set
#: is intentionally narrow (precision-first per the parent brainstorm's
#: "minimize false positives at the cost of some false negatives" bias).
#: All patterns are case-insensitive and use ``\b`` word boundaries to
#: avoid matching mid-word coincidences.
#:
#: **Optional outer braces** (``\{?...\}?``) accommodate Javadoc-style
#: replacement references like ``// Use {NewField} instead.`` that
#: protobuf authors borrowing JavaDoc-style conventions write. Without
#: the optional braces, the inner ``[\w.]+`` token class cannot match
#: ``{NewField}`` (``{`` is not a word char), causing a false negative
#: for a canonical replacement reference; the post-review fix added the
#: optional brace anchors to close that gap.
#:
#: Corpus tuning against googleapis + grpc-proto + envoy +
#: opentelemetry-proto deprecation comments was DEFERRED at U3a
#: implementation time (offline environment without network egress).
#: Future deliveries may extend this tuple with additional patterns
#: validated against real-world corpora — pattern ADDITION is
#: backward-compatible (more comments match → fewer findings emitted).
#: Pattern REMOVAL or REPLACEMENT would break previously-matching
#: comments and requires explicit user communication (CHANGELOG entry).
_REPLACEMENT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\buse\s+\{?[\w.]+\}?\s+instead\b", re.IGNORECASE),
    re.compile(r"\breplaced?\s+(?:by|with)\s+\{?[\w.]+\}?", re.IGNORECASE),
    re.compile(r"\bmigrate\s+to\s+\{?[\w.]+\}?", re.IGNORECASE),
    re.compile(
        r"\bsee\s+\{?[\w.]+\}?\s+for\s+(?:the\s+)?replacement\b",
        re.IGNORECASE,
    ),
)


def _check_replacement_comment(text: str | None) -> bool:
    """Return ``True`` iff ``text`` contains a recognized replacement phrasing.

    Args:
        text: Stripped leading comment string, or ``None`` when no comment
            was attached to the deprecated element (or when ``include_source_info``
            was not enabled at compile time).

    Returns:
        ``True`` when ``text`` matches any pattern in
        :data:`_REPLACEMENT_PATTERNS`; ``False`` for the ``None`` input
        case or when no pattern matches.
    """
    if text is None:
        return False
    return any(pattern.search(text) for pattern in _REPLACEMENT_PATTERNS)


def _sanitize_comment_for_params(comment: str | None) -> str:
    """Truncate + sanitize + brace-escape a comment for ``params["comment"]``.

    Three-stage pipeline (truncate → sanitize → brace-escape):

    1. **Truncate to 500-char prefix.** Bounds wire-format size against
       adversarial protos carrying multi-KB deprecation comments.
    2. **Sanitize via ``_safe_for_stderr``.** Collapses control characters,
       U+0085 / U+2028 / U+2029 separators to spaces so the rendered
       message stays a single line.
    3. **Brace-escape (``{`` → ``{{``, ``}`` → ``}}``).** Protects
       ``message_template.format(**params)`` from ``KeyError`` when
       attacker-controlled comment bytes contain literal braces.

    **Invariant — brace-escape vs ``!r`` conversion.** The brace-escape
    is the PRIMARY injection guard for any ``message_template`` that
    interpolates ``{comment}`` WITHOUT the ``!r`` conversion. All 5
    current R6 templates use ``{comment!r}`` and so have ``repr()``-based
    defense-in-depth (Python's repr renders literal braces as part of
    the quoted string, never as format markers). A future R6-family
    rule (or a sibling pack) that drops ``!r`` would silently lose the
    repr defense AND would rely solely on this brace-escape to remain
    safe. Callers that interpolate ``{comment}`` directly MUST call
    this function; callers using ``{comment!r}`` should still call it
    for forward-safety. Do not relax the brace-escape without auditing
    every consumer of ``params["comment"]``.

    Args:
        comment: The unsanitized leading comment, or ``None``.

    Returns:
        The processed string (always non-``None``, possibly empty).
    """
    text = comment or ""
    truncated = text[:500]
    sanitized = _safe_for_stderr(truncated)
    return sanitized.replace("{", "{{").replace("}", "}}")


#: Shared boilerplate appended to every R6 rule's ``message_template``.
#: The 4-pattern enumeration matches ``_REPLACEMENT_PATTERNS`` above —
#: any pattern addition that ships in a future delivery should update
#: this constant so the rendered help text stays accurate. Keeping the
#: phrase in one place prevents drift between the 5 rules' templates.
_REPLACEMENT_HINT: str = (
    "leading comment (expected phrasing like 'Use X instead.', "
    "'Replaced by X.', 'Migrate to X.', or 'See X for the replacement.'; "
    "got: {comment!r})"
)


# ---------------------------------------------------------------------------
# 5 R6 rules — one per *Options.deprecated ElementKind
# ---------------------------------------------------------------------------


@lint_rule(
    rule_id="options/deprecated-field-must-have-replacement-comment",
    severity=LintSeverity.ERROR,
    profiles=("default",),
    element=ElementKind.FIELD,
    message_template=(
        "Deprecated field {name!r} is missing a replacement-instruction "
        + _REPLACEMENT_HINT
    ),
    source_spec="",
)
def check_deprecated_field_must_have_replacement_comment(
    ctx: FieldLintContext,
) -> None:
    """Fire on every ``[deprecated = true]`` field lacking a replacement comment.

    Reads the field's ``FieldOptions.deprecated`` bit; when set, looks up
    the field's leading comment via the U2-shipped
    :func:`leading_comment` helper and runs it through the shared
    :func:`_check_replacement_comment` regex matcher. Fires an error
    when no recognized replacement phrasing is found (D6f promotion;
    pre-D6f severity was ``warning``).

    Protokit-original — no buf analogue (per
    [[buf-parity-divergence-documentation-discipline]]).
    """
    if not ctx.field.GetOptions().deprecated:
        return
    path = descriptor_path(ctx.field)
    comment = leading_comment(ctx.source_info_descriptors, ctx.file.name, path)
    if _check_replacement_comment(comment):
        return
    ctx.emit(
        violation_kind="options/deprecated-field-must-have-replacement-comment",
        params={
            "name": ctx.field.name,
            "comment": _sanitize_comment_for_params(comment),
        },
    )


@lint_rule(
    rule_id="options/deprecated-enum-value-must-have-replacement-comment",
    severity=LintSeverity.ERROR,
    profiles=("default",),
    element=ElementKind.ENUM_VALUE,
    message_template=(
        "Deprecated enum value {name!r} is missing a replacement-instruction "
        + _REPLACEMENT_HINT
    ),
    source_spec="",
)
def check_deprecated_enum_value_must_have_replacement_comment(
    ctx: EnumValueLintContext,
) -> None:
    """Fire on every ``[deprecated = true]`` enum value lacking a replacement comment.

    Reads ``EnumValueOptions.deprecated``; on a match, looks up the
    value's leading comment and verifies it contains recognized
    replacement phrasing. Fires an error otherwise (D6f promotion; pre-D6f severity was
    ``warning``).

    Protokit-original — no buf analogue (per
    [[buf-parity-divergence-documentation-discipline]]).
    """
    if not ctx.value.GetOptions().deprecated:
        return
    path = descriptor_path(ctx.value)
    comment = leading_comment(ctx.source_info_descriptors, ctx.file.name, path)
    if _check_replacement_comment(comment):
        return
    ctx.emit(
        violation_kind="options/deprecated-enum-value-must-have-replacement-comment",
        params={
            "name": ctx.value.name,
            "comment": _sanitize_comment_for_params(comment),
        },
    )


@lint_rule(
    rule_id="options/deprecated-method-must-have-replacement-comment",
    severity=LintSeverity.ERROR,
    profiles=("default",),
    element=ElementKind.METHOD,
    message_template=(
        "Deprecated RPC method {name!r} is missing a replacement-instruction "
        + _REPLACEMENT_HINT
    ),
    source_spec="",
)
def check_deprecated_method_must_have_replacement_comment(
    ctx: MethodLintContext,
) -> None:
    """Fire on every ``[deprecated = true]`` RPC method lacking a replacement comment.

    Reads ``MethodOptions.deprecated``; on a match, looks up the method's
    leading comment and verifies it contains recognized replacement
    phrasing. Fires an error otherwise (D6f promotion; pre-D6f severity was
    ``warning``).

    Protokit-original — no buf analogue (per
    [[buf-parity-divergence-documentation-discipline]]).
    """
    if not ctx.method.GetOptions().deprecated:
        return
    path = descriptor_path(ctx.method)
    comment = leading_comment(ctx.source_info_descriptors, ctx.file.name, path)
    if _check_replacement_comment(comment):
        return
    ctx.emit(
        violation_kind="options/deprecated-method-must-have-replacement-comment",
        params={
            "name": ctx.method.name,
            "comment": _sanitize_comment_for_params(comment),
        },
    )


@lint_rule(
    rule_id="options/deprecated-message-must-have-replacement-comment",
    severity=LintSeverity.ERROR,
    profiles=("default",),
    element=ElementKind.MESSAGE,
    message_template=(
        "Deprecated message {name!r} is missing a replacement-instruction "
        + _REPLACEMENT_HINT
    ),
    source_spec="",
)
def check_deprecated_message_must_have_replacement_comment(
    ctx: MessageLintContext,
) -> None:
    """Fire on every ``[deprecated = true]`` message lacking a replacement comment.

    Reads ``MessageOptions.deprecated``; on a match, looks up the
    message's leading comment and verifies it contains recognized
    replacement phrasing. Fires an error otherwise (D6f promotion; pre-D6f severity was
    ``warning``).

    Protokit-original — no buf analogue (per
    [[buf-parity-divergence-documentation-discipline]]).
    """
    if not ctx.message.GetOptions().deprecated:
        return
    path = descriptor_path(ctx.message)
    comment = leading_comment(ctx.source_info_descriptors, ctx.file.name, path)
    if _check_replacement_comment(comment):
        return
    ctx.emit(
        violation_kind="options/deprecated-message-must-have-replacement-comment",
        params={
            "name": ctx.message.name,
            "comment": _sanitize_comment_for_params(comment),
        },
    )


@lint_rule(
    rule_id="options/deprecated-enum-must-have-replacement-comment",
    severity=LintSeverity.ERROR,
    profiles=("default",),
    element=ElementKind.ENUM,
    message_template=(
        "Deprecated enum {name!r} is missing a replacement-instruction "
        + _REPLACEMENT_HINT
    ),
    source_spec="",
)
def check_deprecated_enum_must_have_replacement_comment(
    ctx: EnumLintContext,
) -> None:
    """Fire on every ``[deprecated = true]`` enum lacking a replacement comment.

    Reads ``EnumOptions.deprecated``; on a match, looks up the enum's
    leading comment and verifies it contains recognized replacement
    phrasing. Fires an error otherwise (D6f promotion; pre-D6f severity was
    ``warning``).

    Protokit-original — no buf analogue (per
    [[buf-parity-divergence-documentation-discipline]]).
    """
    if not ctx.enum.GetOptions().deprecated:
        return
    path = descriptor_path(ctx.enum)
    comment = leading_comment(ctx.source_info_descriptors, ctx.file.name, path)
    if _check_replacement_comment(comment):
        return
    ctx.emit(
        violation_kind="options/deprecated-enum-must-have-replacement-comment",
        params={
            "name": ctx.enum.name,
            "comment": _sanitize_comment_for_params(comment),
        },
    )


# ---------------------------------------------------------------------------
# RULES tuple — exposed to ``BUILTIN_PACKS`` for engine auto-load
# ---------------------------------------------------------------------------


RULES: tuple[Callable[..., None], ...] = (
    check_deprecated_enum_must_have_replacement_comment,
    check_deprecated_enum_value_must_have_replacement_comment,
    check_deprecated_field_must_have_replacement_comment,
    check_deprecated_message_must_have_replacement_comment,
    check_deprecated_method_must_have_replacement_comment,
)
