"""R7 PACKAGE_SAME_* rule family (D6b U4a + U4b).

Seven cross-file lint rules that flag a package whose files disagree
on a language-specific ``FileOptions`` attribute:

- ``package/same-go-package`` (``go_package``)
- ``package/same-java-package`` (``java_package``)
- ``package/same-csharp-namespace`` (``csharp_namespace``)
- ``package/same-php-namespace`` (``php_namespace``)
- ``package/same-ruby-package`` (``ruby_package``)
- ``package/same-swift-prefix`` (``swift_prefix``)
- ``package/same-java-multiple-files`` (``java_multiple_files``)

This module is a SIBLING of :mod:`protokit.schema.lint.rules.package`
(NOT a subdirectory inside it — see ``package.py:29-34``'s explicit
defer comment that reserves this filename for the R7 family).

Architecture (all-disagreers-fire, U4b)
---------------------------------------

Each rule wraps a one-line call into the shared
:func:`_check_package_option` helper. The helper reads the engine's
pre-walk accumulator (``ctx.package_options[ctx.file.package][attr]``,
mapping ``filename -> value | None``) and emits exactly one finding
on ``ctx.file`` when the package has a disagreement.

Disagreement is detected on two arms (empirically locked against buf
v1.69.0 — see ``tests/schema/lint/rules/fixtures/package_same/_buf_smoke/recorded/``):

- ``len(declared) >= 2`` -> ``'multiple values "X,Y[,Z]"'`` payload.
  Values are sorted **alphabetic-by-value** (NOT file order; NOT first-
  encountered) per :file:`recorded/reverse-order-go.json`.
- ``len(declared) == 1 and has_omitter`` -> ``'both values "X" and no value'``
  payload. The single declared value flows in as-is.

Silent on three arms:

- ``ctx.package_options is None`` -> test-helper path; engine pre-walk
  did not run (e.g., the file was constructed via a unit-test helper
  bypassing :class:`LintEngine.run`).
- ``per_pkg is None`` -> caller's package not in the accumulator
  (defensive; expected to be unreachable for any file whose name lives
  in the pool).
- ``per_file is None or len(per_file) <= 1`` -> single-file package
  cannot disagree with itself.
- ``not declared`` -> all-omit (no file in the package declares the
  attr).
- ``len(declared) == 1 and not has_omitter`` -> all-agree (the single
  declared value is shared by every file; no omitters either).

Message template
----------------

All 7 rules ship the BYTE-IDENTICAL ``message_template`` (split
for the 100-char line cap; the runtime ``str`` is unbroken):

    'Files in package "{package}" have {values_payload} for '
    'option "{option_attr}" and all values must be equal.'

Empirically verified across all 7 rules' mixed-value + mixed-presence
smoke fixtures (21 buf v1.69.0 NDJSON snapshots committed alongside
the rule pack). The literal-identical template means the U7
presence-ratchet test can assert one substring across all 7 rule_ids.

Sanitization
------------

Each of the 3 string ``params`` values
(``package`` / ``option_attr`` / ``values_payload``) flows through
``_safe_for_stderr`` to collapse control characters + Unicode line
terminators, then a 500-char cap. Inner ``"`` characters in declared
values are escaped to ``\\"`` per-value BEFORE composition to match
buf's :file:`recorded/mixed-value-with-inner-quote.json` byte format.
``_safe_for_stderr`` does NOT do this escape (it only handles
control chars); the helper applies it explicitly.

No per-value sub-cap. The 500-char composed cap is the only DoS
bound (mirrors R6's pattern; per-value sub-cap dropped per the U4
document-review 3-persona convergence).

Severity + Profiles
-------------------

All 7 rules ship at ``LintSeverity.ERROR`` in profiles
``("recommended", "default")`` — buf BASIC parity. Demote per-rule
via ``[tool.protokit.lint.severities]`` for legitimate cross-language
vendor-isolation patterns.

BUILTIN_PACKS registration
--------------------------

This module is loadable but **NOT** registered in default
``BUILTIN_PACKS`` for U4b. Users opt in via
``--rule-pack=protokit.schema.lint.rules.package_same``.
``BUILTIN_PACKS`` registration + full migration docs land at U7
alongside the 0.2.0 -> 0.3.0 version bump per
[[pre-1.0-version-bump-as-communication-contract]].

References
----------

- D6b U4 plan:
  ``docs/plans/2026-05-17-002-feat-d6b-u4-r7-package-same-revised-plan.md``
- Per-unit brainstorm:
  ``docs/brainstorms/2026-05-17-d6b-u4-r7-package-same-revised-requirements.md``
- Empirical foundation (21 buf v1.69.0 NDJSON snapshots):
  ``tests/schema/lint/rules/fixtures/package_same/_buf_smoke/recorded/*.json``
- U4a engine plumbing landed in ``LintEngine._build_package_options_accumulator``
  (commits ``d58dc38`` + ``f20f632``).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from protokit.schema.lint._cli_utils import _safe_for_stderr
from protokit.schema.lint.decorator import lint_rule
from protokit.schema.lint.model import ElementKind, LintSeverity

if TYPE_CHECKING:
    from protokit.schema.lint.model import FileLintContext

# ---------------------------------------------------------------------------
# Shared constants — single source of truth for the 7-rule family
# ---------------------------------------------------------------------------

# Triples: (option_attr_on_FileOptions, protokit_rule_id, buf_alias).
# Order is the canonical order in which rules are documented + tested.
# Each triple defines one R7 rule; the @lint_rule callables below
# consume the rule_id + buf_alias for their decorator metadata and
# pass the option_attr to the shared ``_check_package_option`` helper.
_PACKAGE_SAME_OPTION_ATTRS: tuple[tuple[str, str, str], ...] = (
    (
        "go_package",
        "package/same-go-package",
        "buf:PACKAGE_SAME_GO_PACKAGE",
    ),
    (
        "java_package",
        "package/same-java-package",
        "buf:PACKAGE_SAME_JAVA_PACKAGE",
    ),
    (
        "csharp_namespace",
        "package/same-csharp-namespace",
        "buf:PACKAGE_SAME_CSHARP_NAMESPACE",
    ),
    (
        "php_namespace",
        "package/same-php-namespace",
        "buf:PACKAGE_SAME_PHP_NAMESPACE",
    ),
    (
        "ruby_package",
        "package/same-ruby-package",
        "buf:PACKAGE_SAME_RUBY_PACKAGE",
    ),
    (
        "swift_prefix",
        "package/same-swift-prefix",
        "buf:PACKAGE_SAME_SWIFT_PREFIX",
    ),
    (
        "java_multiple_files",
        "package/same-java-multiple-files",
        "buf:PACKAGE_SAME_JAVA_MULTIPLE_FILES",
    ),
)


#: str-view of the 7 option attrs — consumed by
#: :meth:`protokit.schema.lint.engine.LintEngine._build_package_options_accumulator`.
#: Computed once at module load (cheap; the triples tuple above is the
#: source of truth — extending the rule family means adding a triple
#: above, and this str-view automatically picks it up).
_PACKAGE_SAME_OPTION_ATTR_NAMES: tuple[str, ...] = tuple(
    attr for attr, _rule_id, _buf_alias in _PACKAGE_SAME_OPTION_ATTRS
)


# Buf v1.69.0's literal message_template. Byte-identical across all
# 7 rules per the cross-rule smoke fixtures.
# Empirical foundation:
#   - mixed-value-{rule}.json (7 snapshots)
#   - mixed-presence-{rule}.json (7 snapshots — 6 added in
#     deferred-question-resolution + 1 original mixed-presence.json)
#   - mixed-value-with-inner-quote.json
_MESSAGE_TEMPLATE: str = (
    'Files in package "{package}" have {values_payload} '
    'for option "{option_attr}" and all values must be equal.'
)


# ---------------------------------------------------------------------------
# Shared helper — all-disagreers-fire emit logic
# ---------------------------------------------------------------------------


def _escape_inner_quote(value: str) -> str:
    """Replace each ``"`` in ``value`` with ``\\"`` (literal backslash-quote).

    Required for byte-parity with buf v1.69.0's emit format per
    :file:`recorded/mixed-value-with-inner-quote.json` — buf renders
    inner quote characters as literal ``\\"`` in the message text.
    ``_safe_for_stderr`` does NOT do this escape (it only handles
    control characters), so the helper applies it explicitly per
    declared value BEFORE composition.
    """
    return value.replace('"', '\\"')


def _check_package_option(
    ctx: FileLintContext, option_attr: str, rule_id: str,
) -> None:
    """All-disagreers-fire emit logic shared across the 7 R7 rules.

    Reads ``ctx.package_options[ctx.file.package][option_attr]`` (the
    engine's pre-walk accumulator, mapping ``filename -> value | None``)
    and emits a single finding on ``ctx.file`` when the package's files
    disagree on ``option_attr``. The engine's per-file walk dispatches
    the rule once per root file, so a 3-file package with disagreement
    produces 3 findings (one per root file) — buf v1.69.0's
    all-disagreers-fire semantics.

    Silent on:

    - ``ctx.package_options is None`` -> test-helper path; pre-walk
      did not run.
    - ``per_pkg is None`` -> file's package not in the accumulator
      (defensive — unreachable when ``ctx.file.name`` is in the pool).
    - ``per_file is None or len(per_file) <= 1`` -> single-file
      package cannot disagree with itself.
    - All files omit the attr (``not declared``).
    - All files declare the same value AND no omitters
      (``len(declared) == 1 and not has_omitter``).

    Emits when:

    - 2+ distinct declared values exist (``'multiple values "X,Y[,Z]"'``;
      sorted alphabetic-by-value per :file:`recorded/reverse-order-go.json`).
    - Exactly 1 declared value PLUS at least 1 omitter
      (``'both values "X" and no value'``).

    Params:

    - ``package``: ``ctx.file.package`` (the empty string for files
      without a ``package`` declaration; per :file:`recorded/empty-package-mixed.json`
      empty-package files participate in disagreement detection like
      any other namespace).
    - ``option_attr``: the attr name (e.g., ``"go_package"``).
    - ``values_payload``: composed disagreement payload (see above).

    All 3 params flow through ``_safe_for_stderr`` to neutralize
    control characters + Unicode line terminators, then a 500-char
    cap. Inner ``"`` characters in declared values are escaped to
    ``\\"`` BEFORE composition to match buf's byte format.
    """
    if ctx.package_options is None:
        return
    per_pkg = ctx.package_options.get(ctx.file.package)
    if per_pkg is None:
        return
    per_file = per_pkg.get(option_attr)
    if per_file is None or len(per_file) <= 1:
        return

    declared_set: set[str] = {v for v in per_file.values() if v is not None}
    has_omitter = any(v is None for v in per_file.values())

    if not declared_set:
        return  # all-omit silent
    if len(declared_set) == 1 and not has_omitter:
        return  # all-agree silent

    # Disagreement: compose values_payload per buf's two message arms.
    if len(declared_set) >= 2:
        # Alphabetic-by-value sort empirically locked via
        # recorded/reverse-order-go.json — input ``a=Y, b=X, c=Y``
        # produces ``"X,Y"`` not ``"Y,X"``.
        escaped_values = [_escape_inner_quote(v) for v in sorted(declared_set)]
        values_payload = f'multiple values "{",".join(escaped_values)}"'
    else:
        # Mixed-presence: exactly 1 declared value + at least 1 omitter.
        # next(iter(...)) on a 1-element set is deterministic.
        single = next(iter(declared_set))
        values_payload = f'both values "{_escape_inner_quote(single)}" and no value'

    ctx.emit(
        violation_kind=rule_id,
        params={
            "package": _safe_for_stderr(ctx.file.package)[:500],
            "option_attr": _safe_for_stderr(option_attr)[:500],
            "values_payload": _safe_for_stderr(values_payload)[:500],
        },
    )


# ---------------------------------------------------------------------------
# Per-rule @lint_rule callables — one per option_attr in
# _PACKAGE_SAME_OPTION_ATTRS. Each is a 1-line wrapper into the
# shared helper. All 7 share the literal-identical message_template.
# ---------------------------------------------------------------------------


@lint_rule(
    rule_id="package/same-go-package",
    severity=LintSeverity.ERROR,
    profiles=("recommended", "default"),
    element=ElementKind.FILE,
    message_template=_MESSAGE_TEMPLATE,
    source_spec="buf:PACKAGE_SAME_GO_PACKAGE",
)
def check_same_go_package(ctx: FileLintContext) -> None:
    """Every file in a package must agree on ``option go_package``.

    Buf parity: ``buf:PACKAGE_SAME_GO_PACKAGE``. Empirically verified
    against buf v1.69.0 in
    :file:`tests/schema/lint/rules/fixtures/package_same/_buf_smoke/recorded/mixed-value.json`
    + :file:`recorded/mixed-presence.json`. All-disagreers-fire: any
    disagreement flags every file in the package equally. Demote via
    ``[tool.protokit.lint.severities]`` for legitimate cross-language
    vendor isolation patterns.
    """
    _check_package_option(ctx, "go_package", "package/same-go-package")


@lint_rule(
    rule_id="package/same-java-package",
    severity=LintSeverity.ERROR,
    profiles=("recommended", "default"),
    element=ElementKind.FILE,
    message_template=_MESSAGE_TEMPLATE,
    source_spec="buf:PACKAGE_SAME_JAVA_PACKAGE",
)
def check_same_java_package(ctx: FileLintContext) -> None:
    """Every file in a package must agree on ``option java_package``.

    Buf parity: ``buf:PACKAGE_SAME_JAVA_PACKAGE``. Empirically verified
    against buf v1.69.0 in
    :file:`recorded/mixed-value-java-package.json`
    + :file:`recorded/mixed-presence-java-package.json`. Demote via
    ``[tool.protokit.lint.severities]`` for legitimate cross-language
    vendor isolation patterns.
    """
    _check_package_option(ctx, "java_package", "package/same-java-package")


@lint_rule(
    rule_id="package/same-csharp-namespace",
    severity=LintSeverity.ERROR,
    profiles=("recommended", "default"),
    element=ElementKind.FILE,
    message_template=_MESSAGE_TEMPLATE,
    source_spec="buf:PACKAGE_SAME_CSHARP_NAMESPACE",
)
def check_same_csharp_namespace(ctx: FileLintContext) -> None:
    """Every file in a package must agree on ``option csharp_namespace``.

    Buf parity: ``buf:PACKAGE_SAME_CSHARP_NAMESPACE``. Empirically
    verified against buf v1.69.0 in
    :file:`recorded/mixed-value-csharp-namespace.json`
    + :file:`recorded/mixed-presence-csharp-namespace.json`. Demote
    via ``[tool.protokit.lint.severities]`` for legitimate
    cross-language vendor isolation patterns.
    """
    _check_package_option(
        ctx, "csharp_namespace", "package/same-csharp-namespace",
    )


@lint_rule(
    rule_id="package/same-php-namespace",
    severity=LintSeverity.ERROR,
    profiles=("recommended", "default"),
    element=ElementKind.FILE,
    message_template=_MESSAGE_TEMPLATE,
    source_spec="buf:PACKAGE_SAME_PHP_NAMESPACE",
)
def check_same_php_namespace(ctx: FileLintContext) -> None:
    """Every file in a package must agree on ``option php_namespace``.

    Buf parity: ``buf:PACKAGE_SAME_PHP_NAMESPACE``. Empirically
    verified against buf v1.69.0 in
    :file:`recorded/mixed-value-php-namespace.json`
    + :file:`recorded/mixed-presence-php-namespace.json`. Demote via
    ``[tool.protokit.lint.severities]`` for legitimate cross-language
    vendor isolation patterns.
    """
    _check_package_option(ctx, "php_namespace", "package/same-php-namespace")


@lint_rule(
    rule_id="package/same-ruby-package",
    severity=LintSeverity.ERROR,
    profiles=("recommended", "default"),
    element=ElementKind.FILE,
    message_template=_MESSAGE_TEMPLATE,
    source_spec="buf:PACKAGE_SAME_RUBY_PACKAGE",
)
def check_same_ruby_package(ctx: FileLintContext) -> None:
    """Every file in a package must agree on ``option ruby_package``.

    Buf parity: ``buf:PACKAGE_SAME_RUBY_PACKAGE``. Empirically verified
    against buf v1.69.0 in
    :file:`recorded/mixed-value-ruby-package.json`
    + :file:`recorded/mixed-presence-ruby-package.json`. Demote via
    ``[tool.protokit.lint.severities]`` for legitimate cross-language
    vendor isolation patterns.
    """
    _check_package_option(ctx, "ruby_package", "package/same-ruby-package")


@lint_rule(
    rule_id="package/same-swift-prefix",
    severity=LintSeverity.ERROR,
    profiles=("recommended", "default"),
    element=ElementKind.FILE,
    message_template=_MESSAGE_TEMPLATE,
    source_spec="buf:PACKAGE_SAME_SWIFT_PREFIX",
)
def check_same_swift_prefix(ctx: FileLintContext) -> None:
    """Every file in a package must agree on ``option swift_prefix``.

    Buf parity: ``buf:PACKAGE_SAME_SWIFT_PREFIX``. Empirically verified
    against buf v1.69.0 in
    :file:`recorded/mixed-value-swift-prefix.json`
    + :file:`recorded/mixed-presence-swift-prefix.json`. Demote via
    ``[tool.protokit.lint.severities]`` for legitimate cross-language
    vendor isolation patterns.
    """
    _check_package_option(ctx, "swift_prefix", "package/same-swift-prefix")


@lint_rule(
    rule_id="package/same-java-multiple-files",
    severity=LintSeverity.ERROR,
    profiles=("recommended", "default"),
    element=ElementKind.FILE,
    message_template=_MESSAGE_TEMPLATE,
    source_spec="buf:PACKAGE_SAME_JAVA_MULTIPLE_FILES",
)
def check_same_java_multiple_files(ctx: FileLintContext) -> None:
    """Every file in a package must agree on ``option java_multiple_files``.

    The only **boolean** PACKAGE_SAME_* rule. Pre-walk captures the
    value as the lowercase string ``"true"`` / ``"false"`` to byte-
    match buf's emit format (NOT Python's title-case
    ``"True"`` / ``"False"``) per
    :file:`recorded/mixed-value-java-multiple-files.json`. The helper
    then sorts alphabetic-by-value (``"false"`` precedes ``"true"``).

    Buf parity: ``buf:PACKAGE_SAME_JAVA_MULTIPLE_FILES``. Empirically
    verified against buf v1.69.0 in
    :file:`recorded/mixed-value-java-multiple-files.json`
    + :file:`recorded/mixed-presence-java-multiple-files.json`. Demote
    via ``[tool.protokit.lint.severities]`` for legitimate cross-
    language vendor isolation patterns.
    """
    _check_package_option(
        ctx, "java_multiple_files", "package/same-java-multiple-files",
    )


# ---------------------------------------------------------------------------
# RULES tuple — exposed to ``LintEngine.load_rule_pack`` via the
# ``--rule-pack=protokit.schema.lint.rules.package_same`` opt-in. NOT
# registered in default BUILTIN_PACKS until U7 (deferred per
# [[pre-1.0-version-bump-as-communication-contract]] alongside the
# 0.2.0 -> 0.3.0 version bump).
# ---------------------------------------------------------------------------


RULES: tuple[Callable[..., None], ...] = (
    check_same_go_package,
    check_same_java_package,
    check_same_csharp_namespace,
    check_same_php_namespace,
    check_same_ruby_package,
    check_same_swift_prefix,
    check_same_java_multiple_files,
)
