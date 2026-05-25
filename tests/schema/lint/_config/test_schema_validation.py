"""Tests for ``ResolvedLintConfig.from_dict`` schema validation (D5 U2).

Covers:

- **R3 unknown keys**: unknown top-level keys, and nested-table
  unknown keys surfaced as top-level (per KTD-2 single-pass posture).
- **R3a / KTD-5 type mismatches**: scalar-vs-list shape mismatches,
  bool rejected as int, and heterogeneous list elements with
  element-index naming.
- **Empty / absent table**: returns a config with all defaults
  (not an error per origin Q5 / Q18).
- **Error format**: every R3 / R3a / KTD-5 violation produces exit 2
  with ``error[lint-pyproject-config-invalid]:`` stable prefix.

The corresponding R5a *parse-time* failures (missing file,
unreadable, invalid TOML) are covered by ``test_loader.py`` and
carry ``error[lint-pyproject-config-load]:`` instead — they hit
the U1 loader, not U2's validator.
"""

from __future__ import annotations

import ast
import inspect
import textwrap

import pytest

from protokit.schema.lint._config import _ALLOWED_KEYS, ResolvedLintConfig
from protokit.schema.lint.model import LintSeverity

from .conftest import expect_invalid

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
#
# The ``_expect_invalid`` helper + ``INVALID_PREFIX`` constant are
# defined in ``conftest.py`` (extracted during the D6a U2 ce:review
# follow-ups to remove three-file duplication). Use the public names
# from there.


# ---------------------------------------------------------------------------
# Happy path: empty / absent table
# ---------------------------------------------------------------------------


class TestEmptyOrAbsentTable:
    def test_none_table_returns_defaults(self) -> None:
        resolved = ResolvedLintConfig.from_dict(None, {})
        assert resolved.profile == ("default",)
        assert resolved.exclude == ()
        assert resolved.min_severity is None
        assert resolved.max_warnings is None
        assert resolved.format == "human"
        assert resolved.min_severity_source == "default"
        assert resolved.pyproject_min_severity is None

    def test_empty_table_returns_defaults(self) -> None:
        resolved = ResolvedLintConfig.from_dict({}, {})
        assert resolved.profile == ("default",)
        assert resolved.exclude == ()
        assert resolved.min_severity is None
        assert resolved.max_warnings is None
        assert resolved.format == "human"
        assert resolved.min_severity_source == "default"
        assert resolved.pyproject_min_severity is None


# ---------------------------------------------------------------------------
# R3: unknown keys
# ---------------------------------------------------------------------------


class TestR3UnknownKeys:
    def test_typo_at_top_level(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        # Classic typo: `excldue` instead of `exclude`. The error names
        # the unknown key AND the recognized keys so users see both
        # what they typed wrong and what they meant.
        expect_invalid(
            {"excldue": []},
            {},
            capsys,
            substring="'excldue'",
        )

    def test_nested_table_surfaces_as_top_level_key(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        # `[tool.protokit.lint.rules.foo]` surfaces as top-level
        # `rules` (a dict value), which is not in the R2 allowlist.
        # D5 ships only the top-level message; D6 may extend to
        # dotted-path messages when nested tables become first-class.
        expect_invalid(
            {"rules": {"foo": {}}},
            {},
            capsys,
            substring="'rules'",
        )

    def test_message_lists_all_allowed_keys(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        with pytest.raises(SystemExit):
            ResolvedLintConfig.from_dict({"bogus": 1}, {})
        err = capsys.readouterr().err
        # All R2 allowlist keys must appear in the error so the user
        # sees the closed set. D6a U2 added `severities` and
        # `no_builtin_rules` (R9a + R9c); the test enumerates the full
        # set explicitly to catch silent drift if a key is ever removed
        # from _ALLOWED_KEYS without updating the error message.
        for allowed in (
            "profile", "exclude", "min_severity",
            "max_warnings", "format",
            "severities", "no_builtin_rules",
        ):
            assert repr(allowed) in err, err

    def test_multiple_unknown_keys_named_sorted(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        with pytest.raises(SystemExit):
            ResolvedLintConfig.from_dict(
                {"zeta": 1, "alpha": 2, "mu": 3}, {},
            )
        err = capsys.readouterr().err
        # Sorted alphabetical ordering for stable error output.
        alpha_idx = err.find("'alpha'")
        mu_idx = err.find("'mu'")
        zeta_idx = err.find("'zeta'")
        assert 0 < alpha_idx < mu_idx < zeta_idx


# ---------------------------------------------------------------------------
# R3a: per-field type mismatches (scalar/list shape)
# ---------------------------------------------------------------------------


class TestR3aProfileTypeMismatches:
    def test_profile_int_rejected(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        expect_invalid(
            {"profile": 42}, {}, capsys,
            substring="profile must be a string or list of strings",
        )

    def test_profile_list_with_non_string_element(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        # KTD-5: heterogeneous list. Element index named in the error.
        expect_invalid(
            {"profile": [1, 2]}, {}, capsys,
            substring="profile[0]",
        )

    def test_profile_list_with_bool_element(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        expect_invalid(
            {"profile": ["a", True]}, {}, capsys,
            substring="profile[1]",
        )

    def test_profile_empty_list_rejected(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        # KTD-5: an empty `profile = []` list is structurally well-typed
        # but semantically meaningless — there is no profile to resolve.
        # Reject at the schema-validation boundary so the user sees a
        # specific message instead of `lint-unknown-profile` later.
        expect_invalid(
            {"profile": []}, {}, capsys,
            substring="profile must not be empty",
        )


class TestR3aExcludeTypeMismatches:
    def test_exclude_scalar_rejected(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        # exclude is list-only (R15 distinguishes profile from exclude
        # on this dimension).
        expect_invalid(
            {"exclude": "vendor/**"}, {}, capsys,
            substring="exclude must be a list of strings",
        )

    def test_exclude_heterogeneous_list_names_element_index(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        # KTD-5: the brainstorm called out that heterogeneous lists
        # must name the offending element index.
        expect_invalid(
            {"exclude": ["a", 1, "b"]}, {}, capsys,
            substring="exclude[1]",
        )

    def test_exclude_bool_element_rejected(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        expect_invalid(
            {"exclude": ["a", True]}, {}, capsys,
            substring="exclude[1]",
        )


class TestR3aMinSeverityTypeMismatches:
    def test_min_severity_int_rejected(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        expect_invalid(
            {"min_severity": 1}, {}, capsys,
            substring="min_severity must be a string",
        )

    def test_min_severity_unknown_value(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        expect_invalid(
            {"min_severity": "critical"}, {}, capsys,
            substring="must be one of",
        )

    def test_min_severity_case_insensitive(self) -> None:
        # Boundary-normalize: WARNING / warning / Warning all accepted.
        for value in ("WARNING", "warning", "Warning", "  warning  "):
            resolved = ResolvedLintConfig.from_dict(
                {"min_severity": value}, {},
            )
            assert resolved.min_severity is LintSeverity.WARNING


class TestR3aMaxWarningsTypeMismatches:
    def test_max_warnings_string_rejected(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        expect_invalid(
            {"max_warnings": "0"}, {}, capsys,
            substring="max_warnings must be a non-negative integer",
        )

    def test_max_warnings_bool_rejected(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        # `True` is an int subclass in Python, but the boundary
        # explicitly rejects bools so `max_warnings = true` does
        # not silently coerce to `1`.
        expect_invalid(
            {"max_warnings": True}, {}, capsys,
            substring="max_warnings must be a non-negative integer",
        )

    def test_max_warnings_negative_rejected(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        expect_invalid(
            {"max_warnings": -1}, {}, capsys,
            substring="non-negative",
        )

    def test_max_warnings_zero_accepted(self) -> None:
        # Zero is the "fail on any WARNING" gate; explicitly valid.
        resolved = ResolvedLintConfig.from_dict({"max_warnings": 0}, {})
        assert resolved.max_warnings == 0


class TestR3aFormatTypeMismatches:
    def test_format_int_rejected(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        expect_invalid(
            {"format": 1}, {}, capsys,
            substring="format must be a string",
        )

    def test_format_normalized_at_boundary(self) -> None:
        # Case + whitespace handled at the input boundary so the
        # downstream format-registry lookup sees the canonical form.
        resolved = ResolvedLintConfig.from_dict({"format": "  JSON  "}, {})
        assert resolved.format == "json"


# ---------------------------------------------------------------------------
# GAP 5: _ALLOWED_KEYS vs from_dict dispatch drift guard
# ---------------------------------------------------------------------------


class TestAllowedKeysDriftGuard:
    """GAP 5: ``_ALLOWED_KEYS`` must stay in sync with the set of keys
    that ``from_dict``'s dispatch branches actually process.

    Regression: a contributor who adds a key to ``_ALLOWED_KEYS``
    without implementing the ``from_dict`` branch would produce a
    silent-drop (the key passes the allowlist check but is never
    read). The reverse — an orphan branch with no matching
    ``_ALLOWED_KEYS`` entry — means the key can never be reached.
    Both drift directions are caught here.
    """

    def test_allowed_keys_match_from_dict_dispatch_branches(self) -> None:
        """Drift guard: ``_ALLOWED_KEYS`` must match the set of keys that
        ``from_dict``'s dispatch branches process.

        Uses AST analysis of ``from_dict``'s source to extract the
        string literals compared via ``key == "X"`` in the dispatch
        chain, then asserts symmetry with ``_ALLOWED_KEYS``.
        """
        # ``inspect.getsource`` of a method returns the source with
        # its in-class indentation preserved; ``ast.parse`` rejects
        # indented top-level code, so dedent before parsing.
        source = textwrap.dedent(
            inspect.getsource(ResolvedLintConfig.from_dict),
        )
        tree = ast.parse(source)
        # Find all string literals in ``key == "X"`` comparisons.
        dispatched_keys: set[str] = set()
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Compare)
                and len(node.ops) == 1
                and isinstance(node.ops[0], ast.Eq)
                and isinstance(node.left, ast.Name)
                and node.left.id == "key"
                and len(node.comparators) == 1
                and isinstance(node.comparators[0], ast.Constant)
                and isinstance(node.comparators[0].value, str)
            ):
                dispatched_keys.add(node.comparators[0].value)
        assert dispatched_keys == _ALLOWED_KEYS, (
            f"_ALLOWED_KEYS and from_dict dispatch branches drifted. "
            f"_ALLOWED_KEYS - dispatched: {sorted(_ALLOWED_KEYS - dispatched_keys)!r}; "
            f"dispatched - _ALLOWED_KEYS: {sorted(dispatched_keys - _ALLOWED_KEYS)!r}"
        )
