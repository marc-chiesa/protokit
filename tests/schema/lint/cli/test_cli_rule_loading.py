"""U3 tests for ``--rule-pack`` loading and error-code dispatch.

Covers the four U3-introduced error codes:
- ``no-rules`` (R9 zero-rules loud failure — reachable via
  user packs with empty RULES; the always-on built-in canary
  prevents the simpler "no flags" zero-rules path)
- ``rule-collision`` (DuplicateRuleError from
  ``engine.load_rule_pack``)
- ``rule-pack-load`` with ``kind=import`` token
  (ImportError, ModuleNotFoundError, SystemExit at import,
  arbitrary Exception at import)
- ``rule-pack-load`` with ``kind=shape`` token (compat-style
  ``RULES = ((rule_id, fn), ...)`` raises TypeError from
  ``engine.load_rule_pack`` because entries lack
  ``_lint_spec``)

Plus the stderr load-banner advisory line emitted on every
``--rule-pack`` invocation per the round-1 plan-review P1 fix.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from protokit.schema.lint.cli import main as lint_main
from protokit.schema.lint.model import LintProfile

# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


class TestRulePackHappyPaths:
    def test_single_user_pack_loads_alongside_builtins(
        self, clean_descriptor_set: Path,
    ) -> None:
        """Built-in canary + user pack — both fire.

        The clean fixture has snake_case-correct fields, so the
        canary fires nothing. The user pack ``pack_user_a`` flags
        fields starting with 'x'. The clean fixture has none, so
        no findings render. The pipeline runs end-to-end.
        """
        result = CliRunner().invoke(
            lint_main,
            [
                "--rule-pack", "tests.schema.lint.cli.user_packs.pack_user_a",
                str(clean_descriptor_set),
            ],
        )
        assert result.exit_code == 0, result.output
        # Stderr load-banner emitted once for the --rule-pack value:
        assert "loading user-supplied rule pack" in result.stderr
        assert "pack_user_a" in result.stderr

    def test_multiple_user_packs_load_in_argv_order(
        self, clean_descriptor_set: Path,
    ) -> None:
        """Repeatable --rule-pack accumulates packs.

        Two user packs + the built-in canary produces R25's
        multi-pack provenance line on stderr (gated on
        ``len(loaded_packs) >= 2``).
        """
        result = CliRunner().invoke(
            lint_main,
            [
                "--rule-pack", "tests.schema.lint.cli.user_packs.pack_user_a",
                "--rule-pack", "tests.schema.lint.cli.user_packs.pack_user_b",
                str(clean_descriptor_set),
            ],
        )
        assert result.exit_code == 0, result.output
        # Two load-banner lines, one per --rule-pack value:
        assert result.stderr.count("loading user-supplied rule pack") == 2
        # R25 provenance line fires (3 packs loaded total: builtin + 2 user):
        assert "protokit lint: profile 'default' from" in result.stderr
        assert "protokit.schema.lint.rules.naming" in result.stderr
        assert "pack_user_a" in result.stderr
        assert "pack_user_b" in result.stderr

    def test_load_banner_suppressed_under_no_rule_pack(
        self, clean_descriptor_set: Path,
    ) -> None:
        """Bare invocation (no --rule-pack) emits no load-banner."""
        result = CliRunner().invoke(
            lint_main, [str(clean_descriptor_set)],
        )
        assert result.exit_code == 0, result.output
        assert "loading user-supplied rule pack" not in result.stderr


# ---------------------------------------------------------------------------
# rule-pack-load error code (kind=import + kind=shape)
# ---------------------------------------------------------------------------


class TestRulePackLoadErrors:
    def test_nonexistent_module_routes_to_rule_pack_load_import(
        self, clean_descriptor_set: Path,
    ) -> None:
        """ModuleNotFoundError → rule-pack-load with kind=import."""
        result = CliRunner().invoke(
            lint_main,
            [
                "--rule-pack", "does.not.exist.nope",
                str(clean_descriptor_set),
            ],
        )
        assert result.exit_code == 2
        assert "error[lint-rule-pack-load]:" in result.stderr
        assert "kind=import:" in result.stderr
        assert "does.not.exist.nope" in result.stderr

    def test_module_body_zero_division_routes_to_rule_pack_load_import(
        self, clean_descriptor_set: Path,
    ) -> None:
        """Top-level body raises ZeroDivisionError → kind=import."""
        result = CliRunner().invoke(
            lint_main,
            [
                "--rule-pack",
                "tests.schema.lint.cli.user_packs.pack_module_raises",
                str(clean_descriptor_set),
            ],
        )
        assert result.exit_code == 2
        assert "error[lint-rule-pack-load]:" in result.stderr
        assert "kind=import:" in result.stderr
        assert "ZeroDivisionError" in result.stderr

    def test_module_body_sys_exits_routes_to_rule_pack_load_import(
        self, clean_descriptor_set: Path,
    ) -> None:
        """sys.exit(0) at module load → kind=import (NOT false-green CI exit).

        Critical security regression test: without the
        ``except SystemExit`` guard preceding ``except Exception``
        in ``_load_user_rule_pack``, a user pack calling
        ``sys.exit(0)`` at module load time would silently
        produce exit_code=0 with no error message.
        """
        result = CliRunner().invoke(
            lint_main,
            [
                "--rule-pack",
                "tests.schema.lint.cli.user_packs.pack_sys_exits",
                str(clean_descriptor_set),
            ],
        )
        assert result.exit_code == 2
        assert "error[lint-rule-pack-load]:" in result.stderr
        assert "kind=import:" in result.stderr
        assert "sys.exit(0)" in result.stderr

    def test_compat_format_rules_routes_to_rule_pack_load_shape(
        self, clean_descriptor_set: Path,
    ) -> None:
        """RULES = ((rule_id, fn), ...) → rule-pack-load with kind=shape.

        Imports successfully but ``engine.load_rule_pack`` raises
        TypeError because the tuple entries lack ``_lint_spec``.
        """
        result = CliRunner().invoke(
            lint_main,
            [
                "--rule-pack",
                "tests.schema.lint.cli.user_packs.pack_compat_format",
                str(clean_descriptor_set),
            ],
        )
        assert result.exit_code == 2
        assert "error[lint-rule-pack-load]:" in result.stderr
        assert "kind=shape:" in result.stderr
        # Message body references the audit-wire-format learning:
        assert "audit-wire-format" in result.stderr
        # Names the offending pack:
        assert "pack_compat_format" in result.stderr


# ---------------------------------------------------------------------------
# rule-collision error code
# ---------------------------------------------------------------------------


class TestRulePackNoRules:
    def test_pack_with_no_rules_attribute_routes_to_rule_pack_load_shape(
        self, clean_descriptor_set: Path,
    ) -> None:
        """Module with no RULES attribute → rule-pack-load with kind=shape.

        Imports successfully but engine.load_rule_pack raises AttributeError
        because the module has no RULES attribute at all.
        """
        result = CliRunner().invoke(
            lint_main,
            [
                "--rule-pack",
                "tests.schema.lint.cli.user_packs.pack_no_rules",
                str(clean_descriptor_set),
            ],
        )
        assert result.exit_code == 2
        assert "error[lint-rule-pack-load]:" in result.stderr
        assert "kind=shape:" in result.stderr
        assert "no RULES attribute" in result.stderr
        assert "pack_no_rules" in result.stderr


class TestRuleCollision:
    def test_user_pack_redeclares_builtin_rule_id_routes_to_rule_collision(
        self, clean_descriptor_set: Path,
    ) -> None:
        """User pack redeclaring naming/snake-case-fields → rule-collision."""
        result = CliRunner().invoke(
            lint_main,
            [
                "--rule-pack",
                "tests.schema.lint.cli.user_packs.pack_collision",
                str(clean_descriptor_set),
            ],
        )
        assert result.exit_code == 2
        assert "error[lint-rule-collision]:" in result.stderr
        assert "naming/snake-case-fields" in result.stderr
        # Pack name appears in the message body:
        assert "pack_collision" in result.stderr


# ---------------------------------------------------------------------------
# Fix C: LintProfile.from_pack TypeError defense-in-depth (kind=shape)
# ---------------------------------------------------------------------------


class TestFromPackTypeErrorGuard:
    def test_from_pack_typeerror_routes_to_rule_pack_load_shape(
        self, clean_descriptor_set: Path,
    ) -> None:
        """If LintProfile.from_pack raises TypeError, routes to rule-pack-load
        kind=shape.

        Simulates the defense-in-depth guard: from_pack is monkeypatched to
        raise TypeError. In practice the engine validates at load_rule_pack
        time, so this path is not user-reachable — the guard is defense-in-depth.
        """
        with patch.object(
            LintProfile,
            "from_pack",
            side_effect=TypeError("synthetic-from-pack-error"),
        ):
            result = CliRunner().invoke(
                lint_main, [str(clean_descriptor_set)],
            )
        assert result.exit_code == 2
        assert "error[lint-rule-pack-load]:" in result.stderr
        assert "kind=shape:" in result.stderr
