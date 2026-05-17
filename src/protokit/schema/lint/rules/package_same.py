"""R7 PACKAGE_SAME_* rule family — module shell (D6b U4a).

This module is a SIBLING of :mod:`protokit.schema.lint.rules.package`
(NOT a subdirectory inside it — see ``package.py:29-34``'s explicit
defer comment that reserves this filename for the R7 family).

U4a ships only the shared constants the engine pre-walk consumes:

- :data:`_PACKAGE_SAME_OPTION_ATTRS` — tuple of
  ``(option_attr, rule_id, buf_alias)`` triples. Single source of
  truth for the 7 PACKAGE_SAME_* attrs.
- :data:`_PACKAGE_SAME_OPTION_ATTR_NAMES` — str-view computed from the
  triples at module load. Imported by the engine pre-walk pass
  (``LintEngine._build_package_options_accumulator``) to capture every
  ``FileOptions`` value into the 3-level ``package_options``
  accumulator.

**U4a does NOT ship the 7 ``@lint_rule`` callables, the
``_check_package_option`` helper, the ``_canonical`` helper (the
revised brainstorm dropped this entirely), or the module-level
``RULES`` tuple.** U4b adds those + the BUILTIN_PACKS registration
(deferred to U7 alongside the 0.2.0 → 0.3.0 version bump per
[[pre-1.0-version-bump-as-communication-contract]]).

Empirically-locked design decisions encoded by the shared constants:

- All 7 PACKAGE_SAME_* rule_ids match buf BASIC's rule naming exactly
  (``"buf:PACKAGE_SAME_<NAME>"``).
- ``_PACKAGE_SAME_OPTION_ATTRS`` is the SINGLE source of truth: the
  engine pre-walk imports ``_PACKAGE_SAME_OPTION_ATTR_NAMES`` (the
  str-view computed at module load) so a new attr added here flows
  automatically into both the accumulator and the 7 rule wrappers
  U4b will define.

See ``docs/brainstorms/2026-05-17-d6b-u4-r7-package-same-revised-requirements.md``
and ``docs/plans/2026-05-17-002-feat-d6b-u4-r7-package-same-revised-plan.md``
for the full architectural context.
"""

from __future__ import annotations

# Triples: (option_attr_on_FileOptions, protokit_rule_id, buf_alias).
# Order is the canonical order in which rules are documented + tested.
# Each triple defines one R7 rule; U4b's @lint_rule callables consume
# the rule_id + buf_alias for their decorator metadata and pass the
# option_attr to the shared ``_check_package_option`` helper.
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


# RULES tuple intentionally absent in U4a — the 7 @lint_rule callables
# and the BUILTIN_PACKS registration land in U4b + U7 respectively.
# Importing this module today gives access to the constants above; it
# does NOT register any rule with the engine.
