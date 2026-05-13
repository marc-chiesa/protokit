"""Tests for ``[tool.protokit.lint] no_builtin_rules`` parsing (D6a U2, R9c).

Covers:

- Happy path: ``no_builtin_rules = true`` resolves to ``True`` on
  ``ResolvedLintConfig``; ``= false`` resolves to ``False``; omitted
  defaults to ``False``.
- CLI > pyproject precedence: when ``cli_overrides`` provides
  ``no_builtin_rules``, it wins regardless of pyproject value. CLI
  ``None`` defers to pyproject. CLI ``True`` over pyproject ``False``
  is the typical "user typed --no-builtin-rules" path.
- Error paths: non-bool inputs (string ``"true"``, int ``1``) hard-error.
  Bool-as-int is a Python footgun TOML users would not expect, so
  the coercion rejects strings explicitly.
- The CLI flag implementation (``ParameterSource`` detection) lives
  in ``cli.py`` and is tested at the CLI layer; these tests cover
  the input-boundary contract only.

The pyproject key name is ``no_builtin_rules`` (mirrors the CLI flag
``--no-builtin-rules``) per the "Resolved During Planning"
clarification: positive-form ``builtin_rules = false`` was considered
and rejected to keep CLI and pyproject surfaces semantically aligned.
"""

from __future__ import annotations

import pytest

from protokit.schema.lint._config import ResolvedLintConfig

# ---------------------------------------------------------------------------
# Helpers (mirrors test_schema_validation.py shape)
# ---------------------------------------------------------------------------


_PREFIX: str = "error[lint-pyproject-config-invalid]:"


def _expect_invalid(
    table: dict[str, object],
    cli_overrides: dict[str, object],
    capsys: pytest.CaptureFixture[str],
    *,
    substring: str,
) -> None:
    """Call ``from_dict`` expecting exit 2 with the invalid-prefix message."""
    with pytest.raises(SystemExit) as excinfo:
        ResolvedLintConfig.from_dict(table, cli_overrides)
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert err.startswith(_PREFIX), err
    assert substring in err, err


# ---------------------------------------------------------------------------
# Happy path: pyproject-only
# ---------------------------------------------------------------------------


class TestNoBuiltinRulesPyproject:
    def test_true_resolves_to_true(self) -> None:
        resolved = ResolvedLintConfig.from_dict(
            {"no_builtin_rules": True}, {},
        )
        assert resolved.no_builtin_rules is True

    def test_false_resolves_to_false(self) -> None:
        resolved = ResolvedLintConfig.from_dict(
            {"no_builtin_rules": False}, {},
        )
        assert resolved.no_builtin_rules is False

    def test_omitted_key_defaults_to_false(self) -> None:
        """When the pyproject table doesn't set ``no_builtin_rules`` at
        all, the default factory produces ``False`` — meaning
        ``BUILTIN_PACKS`` auto-load proceeds as usual.
        """
        resolved = ResolvedLintConfig.from_dict(None, {})
        assert resolved.no_builtin_rules is False


# ---------------------------------------------------------------------------
# CLI > pyproject precedence
# ---------------------------------------------------------------------------


class TestNoBuiltinRulesPrecedence:
    def test_cli_true_overrides_pyproject_false(self) -> None:
        """User typed ``--no-builtin-rules`` while pyproject says
        ``no_builtin_rules = false`` — the CLI wins.
        """
        resolved = ResolvedLintConfig.from_dict(
            {"no_builtin_rules": False},
            {"no_builtin_rules": True},
        )
        assert resolved.no_builtin_rules is True

    def test_cli_false_overrides_pyproject_true(self) -> None:
        """User explicitly passed ``--no-builtin-rules=False`` (or the
        flag equivalent) while pyproject says ``true`` — CLI still
        wins. This is the dual of the previous test pinned for
        symmetry.
        """
        resolved = ResolvedLintConfig.from_dict(
            {"no_builtin_rules": True},
            {"no_builtin_rules": False},
        )
        assert resolved.no_builtin_rules is False

    def test_cli_none_defers_to_pyproject(self) -> None:
        """``cli_overrides["no_builtin_rules"] = None`` means "CLI did
        not explicitly set this flag" — defer to pyproject.
        """
        resolved = ResolvedLintConfig.from_dict(
            {"no_builtin_rules": True},
            {"no_builtin_rules": None},
        )
        assert resolved.no_builtin_rules is True

    def test_cli_omitted_defers_to_pyproject(self) -> None:
        """When ``cli_overrides`` doesn't include the key at all, it's
        equivalent to ``None`` — defer to pyproject.
        """
        resolved = ResolvedLintConfig.from_dict(
            {"no_builtin_rules": True}, {},
        )
        assert resolved.no_builtin_rules is True

    def test_no_pyproject_no_cli_defaults_false(self) -> None:
        resolved = ResolvedLintConfig.from_dict(None, {})
        assert resolved.no_builtin_rules is False


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


class TestNoBuiltinRulesErrors:
    def test_string_true_rejected(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """TOML string ``"true"`` is not a boolean — reject explicitly
        rather than silently coercing. TOML's type system makes this
        a typo signal, not a flexibility win.
        """
        _expect_invalid(
            {"no_builtin_rules": "true"},
            {},
            capsys,
            substring="no_builtin_rules must be a boolean",
        )

    def test_int_one_rejected(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Bool-as-int is a Python footgun (``isinstance(True, int)``
        is True), and TOML's type system makes ``1`` a distinct
        integer value. The coercion uses ``isinstance(value, bool)``
        (NOT ``not isinstance(value, int)``) which means int ``1``
        is rejected.
        """
        _expect_invalid(
            {"no_builtin_rules": 1},
            {},
            capsys,
            substring="no_builtin_rules must be a boolean",
        )

    def test_int_zero_rejected(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        _expect_invalid(
            {"no_builtin_rules": 0},
            {},
            capsys,
            substring="no_builtin_rules must be a boolean",
        )

    def test_list_value_rejected(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        _expect_invalid(
            {"no_builtin_rules": [True]},
            {},
            capsys,
            substring="no_builtin_rules must be a boolean",
        )
