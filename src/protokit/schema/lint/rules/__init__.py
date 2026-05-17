"""Built-in rule packs for protokit-lint.

This package marker exposes the curated set of rule packs that
``protokit lint`` auto-loads at subcommand startup. Submodules are
loaded only when explicitly imported by callers (preserves the
cold-import contract documented in
``docs/brainstorms/2026-04-30-protokit-lint-delivery-1-foundation-requirements.md``).

Each submodule is a rule pack: a module exposing a top-level
``RULES`` tuple of ``@lint_rule``-decorated callables. Callers
import the rule pack module they want and pass it to
``LintEngine.load_rule_pack(module)``.

D2 ships a single rule pack: ``naming`` (``naming/snake-case-fields``).
D6 grows additional packs (e.g., ``enum``, ``message``).

KD-9 upgrade-safety policy
--------------------------

``BUILTIN_PACKS`` is the **single source of truth** for which packs
auto-load when ``protokit lint`` runs without ``--no-builtin-rules``.
**Adding a new pack to this tuple is an explicit decision communicated
via a CHANGELOG entry**, NOT a routine code change. The intent is
upgrade safety: users who upgrade ``protokit`` between minor
versions should be able to predict — via the CHANGELOG — when new
lint findings will appear on previously-green CI because a new rule
pack shipped.

The protokit-lint policy for D6+ rule packs is **default opt-in
registered, NOT auto-loaded** *outside* of the deliberate
``BUILTIN_PACKS`` curation. New packs ship as importable modules
under ``protokit.schema.lint.rules.*`` and users opt in via
``--rule-pack <module>``. Promotion of a pack into
``BUILTIN_PACKS`` happens only when:

1. The pack has been validated against representative protobuf
   schemas (no false-positive epidemic).
2. The protokit version policy is honored. **While protokit is
   pre-1.0 there is no stability guarantee; new packs may be added
   to BUILTIN_PACKS freely, accompanied by a CHANGELOG entry
   describing what users will see on upgrade.** Post-1.0, additions
   are gated on a major-version bump per the original intent
   (adding to the auto-load set is a breaking change to the
   ``protokit lint`` default behavior under semver).
3. A CHANGELOG entry explicitly calls out the auto-load expansion +
   provides the opt-out path (``--no-builtin-rules`` /
   ``[tool.protokit.lint] no_builtin_rules = true`` /
   ``--min-severity=warning`` global demotion /
   ``[tool.protokit.lint.severities]`` per-rule demotion / pinning
   protokit to the prior minor version). The plain CHANGELOG
   description is the communication contract; pre-1.0 there is no
   decorative marker requirement.

Enforcement: ``tests/schema/lint/test_builtin_packs.py`` pins the
exact membership of ``BUILTIN_PACKS``. Any change to the tuple
fails the test, forcing the contributor to update the test to
match — a hard CI gate on **test consistency** that signals
explicit intent for any change to the auto-load surface. The
test does NOT enforce CHANGELOG-update-in-same-commit or
version-bump coordination; those remain **soft norms enforced
via PR review**, not structural gates. The right time to invest
in a structural CHANGELOG-diff hook is post-1.0, when the
auto-load set becomes a stability-bearing surface.
"""

from __future__ import annotations

from types import ModuleType

from protokit.schema.lint.rules import (
    enum,
    file,
    imports,
    naming,
    package,
    package_same,  # noqa: F401
)
from protokit.schema.lint.rules.options import deprecated_replacement

# ``package_same`` (D6b U4b R7 PACKAGE_SAME_* family) is imported here
# so users can opt in via ``--rule-pack=protokit.schema.lint.rules.package_same``
# without typing the import path themselves AND so the cold-import
# regression test at ``tests/schema/lint/test_cold_import_extended.py``
# has a known forbidden-modules target to assert against. It is
# **DELIBERATELY NOT** in ``BUILTIN_PACKS`` below — registration is
# deferred to U7 alongside the 0.2.0 -> 0.3.0 version bump per
# [[pre-1.0-version-bump-as-communication-contract]]. Loading the
# module is dormant-by-default: dormant code is the explicit opt-in
# pattern this delivery uses to ship R7 without auto-failing every
# pull-from-main between U4b and U7. The trailing F401 suppression
# on the import line keeps ruff quiet about the apparently-unused
# import without polluting the module namespace with a discard
# binding — matches the suppression idiom used at
# ``cli.py:81`` and ``formatters/__init__.py:65-71``.

#: Curated set of rule pack modules that ``protokit lint``
#: auto-loads at subcommand startup. See module docstring for the
#: KD-9 upgrade-safety policy that governs additions.
#:
#: D6a 0.2.0 release adds four packs beyond the D2 ``naming``
#: canary: ``enum`` (``no-allow-alias`` + ``first-value-zero``),
#: ``imports`` (``no-public`` + ``no-weak`` + ``unused``),
#: ``package`` (``defined`` + ``directory-match``), and ``file``
#: (``syntax-specified``). 14 rules total across 5 packs, covering
#: buf BASIC parity for single-language teams. The 0.2.0 CHANGELOG
#: entry documents the auto-load expansion + demotion paths per the
#: KD-9 communication contract.
#:
#: D6b U3a adds the ``options/deprecated_replacement`` pack — the
#: first comment-aware rule family (5 rules), one per
#: ``*Options.deprecated`` ElementKind (FIELD, ENUM_VALUE, METHOD,
#: MESSAGE, ENUM). The pack ships in ``default`` profile only; the
#: ``recommended`` profile stays at buf BASIC parity (R6 has no buf
#: analogue). Severity ``warning`` bounds the heuristic-regex
#: blast radius. See the D6b U3 plan for the CHANGELOG-communication
#: contract that the auto-load expansion brings.
BUILTIN_PACKS: tuple[ModuleType, ...] = (
    naming,
    enum,
    imports,
    package,
    file,
    deprecated_replacement,
)

__all__ = ["BUILTIN_PACKS"]
