"""Built-in rule packs for protokit-lint.

This package marker is intentionally empty — submodules are loaded
only when explicitly imported by callers (preserves the cold-import
contract documented in ``docs/brainstorms/2026-04-30-protokit-lint-
delivery-1-foundation-requirements.md``).

Each submodule is a rule pack: a module exposing a top-level
``RULES`` tuple of ``@lint_rule``-decorated callables. Callers
import the rule pack module they want and pass it to
``LintEngine.load_rule_pack(module)``.

D2 ships a single rule pack: ``naming`` (``naming/snake-case-fields``).
D6 grows additional packs (e.g., ``enum``, ``message``).
"""
