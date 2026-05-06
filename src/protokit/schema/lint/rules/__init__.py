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
**Adding a new pack to this tuple is an explicit decision tied to a
major-version release with a CHANGELOG entry**, NOT a routine code
change. The intent is upgrade safety: users who upgrade ``protokit``
between minor versions should NOT silently see new lint findings on
previously-green CI just because a new rule pack shipped.

The protokit-lint policy for D6+ rule packs is **default opt-in
registered, NOT auto-loaded**. New packs ship as importable
modules under ``protokit.schema.lint.rules.*`` and users opt in
via ``--rule-pack <module>``. Promotion of a pack into
``BUILTIN_PACKS`` happens only when:

1. The pack has been validated against representative protobuf
   schemas (no false-positive epidemic).
2. The protokit major version is being bumped (semver: adding to
   the auto-load set is a breaking change to the ``protokit lint``
   default behavior).
3. The CHANGELOG entry explicitly calls out the auto-load
   expansion + provides the opt-out path
   (``--no-builtin-rules`` or pinning protokit to the prior
   minor version).

Enforcement: ``tests/schema/lint/test_builtin_packs.py`` pins the
exact membership of ``BUILTIN_PACKS``. Any change to the tuple
fails the test, forcing the contributor to update the test to
match — a hard CI gate on **test consistency** that signals
explicit intent for any change to the auto-load surface. The
test does NOT enforce CHANGELOG-update-in-same-commit or
major-version coordination; those remain **soft norms enforced
via PR review**, not structural gates. The right time to invest
in a structural CHANGELOG-diff hook is when the second pack is
added (D6) — at one pack, the carrying cost of the hook
substrate exceeds present value.
"""

from __future__ import annotations

from types import ModuleType

from protokit.schema.lint.rules import naming

#: Curated set of rule pack modules that ``protokit lint``
#: auto-loads at subcommand startup. See module docstring for the
#: KD-9 upgrade-safety policy that governs additions.
BUILTIN_PACKS: tuple[ModuleType, ...] = (naming,)

__all__ = ["BUILTIN_PACKS"]
