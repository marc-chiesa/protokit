"""Tests for ``_coerce_disabled_rules`` / ``_coerce_enabled_rules`` (D6f U2).

Consolidated parametrized matrix per scope-guardian F1 — both
helpers share the underlying ``_coerce_r9b_rule_id_list``
implementation, so test coverage parametrizes over the key shape
rather than duplicating the same scenarios in two files.

Verifies:

- List-only input (no scalar coercion); type-strict per element.
- ``.strip().lower()`` normalization at the input boundary per
  [[normalize-at-input-boundary-2026-05-07]].
- Format validation against :data:`_R9B_RULE_ID_REGEX` — accepts
  canonical ``pack/rule-suffix``, bare ``custom/<suffix>``, AND
  mangled ``custom/<suffix>__<kind>`` (including underscore-bearing
  kinds like ``enum_value``).
- Deduplication via the ``frozenset`` return shape.
- Empty list / omitted key → empty frozenset (no warning, no error).
"""

from __future__ import annotations

import pytest

from protokit.schema.lint._config import ResolvedLintConfig

from .conftest import expect_invalid

#: Both R9b list-typed keys share the parametrize matrix below.
_R9B_LIST_KEYS: tuple[str, ...] = ("disabled_rules", "enabled_rules")


class TestHappyPath:
    """Valid inputs across the three accepted rule_id shapes."""

    @pytest.mark.parametrize("key", _R9B_LIST_KEYS)
    def test_canonical_pack_rule_suffix(self, key: str) -> None:
        resolved = ResolvedLintConfig.from_dict(
            {key: ["naming/snake-case-fields"]}, {},
        )
        attr = getattr(resolved, key)
        assert attr == frozenset({"naming/snake-case-fields"})

    @pytest.mark.parametrize("key", _R9B_LIST_KEYS)
    def test_custom_bare_prefix_passes_validation(self, key: str) -> None:
        """Bare ``custom/<suffix>`` is accepted at coercion time;
        expansion against ``custom_annotation_rules`` happens in
        ``from_dict`` AFTER coercion."""
        resolved = ResolvedLintConfig.from_dict(
            {key: ["custom/audit-required"]}, {},
        )
        attr = getattr(resolved, key)
        # No matching custom_annotation_rules spec → entry preserved
        # as-is per KD-2 (R8c warning fires from CLI orchestration
        # layer, not from from_dict).
        assert attr == frozenset({"custom/audit-required"})

    @pytest.mark.parametrize("key", _R9B_LIST_KEYS)
    def test_custom_mangled_per_kind_form(self, key: str) -> None:
        """The ``__<kind>`` mangled form is accepted as-is."""
        resolved = ResolvedLintConfig.from_dict(
            {key: ["custom/audit-required__method"]}, {},
        )
        attr = getattr(resolved, key)
        assert attr == frozenset({"custom/audit-required__method"})

    @pytest.mark.parametrize("key", _R9B_LIST_KEYS)
    def test_custom_mangled_underscore_kind(self, key: str) -> None:
        """``enum_value`` is a valid ElementKind name (underscore
        inside the kind segment) — the regex must accept it."""
        resolved = ResolvedLintConfig.from_dict(
            {key: ["custom/audit-required__enum_value"]}, {},
        )
        attr = getattr(resolved, key)
        assert attr == frozenset({"custom/audit-required__enum_value"})

    @pytest.mark.parametrize("key", _R9B_LIST_KEYS)
    def test_empty_list_resolves_to_empty_frozenset(self, key: str) -> None:
        resolved = ResolvedLintConfig.from_dict({key: []}, {})
        attr = getattr(resolved, key)
        assert attr == frozenset()

    @pytest.mark.parametrize("key", _R9B_LIST_KEYS)
    def test_omitted_key_resolves_to_empty_frozenset(self, key: str) -> None:
        resolved = ResolvedLintConfig.from_dict({}, {})
        attr = getattr(resolved, key)
        assert attr == frozenset()


class TestNormalization:
    """KD-6 rule_id normalization at the input boundary."""

    @pytest.mark.parametrize("key", _R9B_LIST_KEYS)
    def test_uppercase_normalized_to_lowercase(self, key: str) -> None:
        resolved = ResolvedLintConfig.from_dict(
            {key: ["Naming/Snake-Case-Fields"]}, {},
        )
        attr = getattr(resolved, key)
        assert attr == frozenset({"naming/snake-case-fields"})

    @pytest.mark.parametrize("key", _R9B_LIST_KEYS)
    def test_surrounding_whitespace_stripped(self, key: str) -> None:
        resolved = ResolvedLintConfig.from_dict(
            {key: ["  naming/snake-case-fields  "]}, {},
        )
        attr = getattr(resolved, key)
        assert attr == frozenset({"naming/snake-case-fields"})

    @pytest.mark.parametrize("key", _R9B_LIST_KEYS)
    def test_duplicate_entries_deduplicated(self, key: str) -> None:
        """Same rule_id twice → one entry (frozenset semantics)."""
        resolved = ResolvedLintConfig.from_dict(
            {key: ["naming/snake-case-fields", "naming/snake-case-fields"]},
            {},
        )
        attr = getattr(resolved, key)
        assert attr == frozenset({"naming/snake-case-fields"})

    @pytest.mark.parametrize("key", _R9B_LIST_KEYS)
    def test_case_variants_dedup_after_normalization(self, key: str) -> None:
        """``"Naming/SNAKE-Case"`` and ``"naming/snake-case"`` collapse
        to the same canonical id after normalization."""
        resolved = ResolvedLintConfig.from_dict(
            {key: ["Naming/Snake-Case-Fields", "naming/snake-case-fields"]},
            {},
        )
        attr = getattr(resolved, key)
        assert attr == frozenset({"naming/snake-case-fields"})


class TestErrorPaths:
    """Type / format / shape rejection."""

    @pytest.mark.parametrize("key", _R9B_LIST_KEYS)
    def test_scalar_string_rejected(
        self, key: str, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """List-only — scalar string is rejected even though it would
        be unambiguous."""
        expect_invalid(
            {key: "naming/snake-case-fields"},
            {},
            capsys,
            substring=f"{key} must be a list of strings",
        )

    @pytest.mark.parametrize("key", _R9B_LIST_KEYS)
    def test_dict_rejected(
        self, key: str, capsys: pytest.CaptureFixture[str],
    ) -> None:
        expect_invalid(
            {key: {"naming/snake-case-fields": "off"}},
            {},
            capsys,
            substring=f"{key} must be a list of strings",
        )

    @pytest.mark.parametrize("key", _R9B_LIST_KEYS)
    def test_non_string_element_rejected(
        self, key: str, capsys: pytest.CaptureFixture[str],
    ) -> None:
        expect_invalid(
            {key: [123]},
            {},
            capsys,
            substring=f"{key}[0] must be a string rule_id",
        )

    @pytest.mark.parametrize("key", _R9B_LIST_KEYS)
    def test_empty_string_element_rejected(
        self, key: str, capsys: pytest.CaptureFixture[str],
    ) -> None:
        expect_invalid(
            {key: [""]},
            {},
            capsys,
            substring=f"{key}[0] must be a non-empty rule_id",
        )

    @pytest.mark.parametrize("key", _R9B_LIST_KEYS)
    def test_whitespace_only_element_rejected(
        self, key: str, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """``"   "`` strips to empty → rejected via the same path."""
        expect_invalid(
            {key: ["   "]},
            {},
            capsys,
            substring=f"{key}[0] must be a non-empty rule_id",
        )

    @pytest.mark.parametrize("key", _R9B_LIST_KEYS)
    def test_missing_slash_rejected(
        self, key: str, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """No ``pack/rule-suffix`` separator → format-validation error.

        The error message includes the rejected value (Fix 14 / REL-1) so
        users see which entry is invalid without re-reading their config:
        ``{label}[0] 'invalid-format-no-slash' is not a valid rule_id``.
        """
        expect_invalid(
            {key: ["invalid-format-no-slash"]},
            {},
            capsys,
            substring="'invalid-format-no-slash' is not a valid rule_id",
        )

    @pytest.mark.parametrize("key", _R9B_LIST_KEYS)
    def test_uppercase_after_strip_rejected(
        self, key: str, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Uppercase is normalized to lowercase BEFORE regex
        validation, so this case is actually valid. The regression
        guard is that a TRULY invalid id (e.g., starting with a
        digit) still fails."""
        # Starting with a digit is invalid per the regex; the
        # normalization does not turn digit-start into letter-start.
        expect_invalid(
            {key: ["1pack/rule-suffix"]},
            {},
            capsys,
            substring="'1pack/rule-suffix' is not a valid rule_id",
        )


class TestCliOverrideSymmetry:
    """CLI overrides apply the SAME strictness per
    [[symmetric-coercion-strictness-multi-source-field-resolver-2026-05-12]]."""

    @pytest.mark.parametrize(
        "cli_key,error_label",
        [
            ("disabled_rules", "--disable-rule"),
            ("enabled_rules", "--enable-rule"),
        ],
    )
    def test_cli_override_with_invalid_format_rejected(
        self,
        cli_key: str,
        error_label: str,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """CLI override path applies regex validation; the error uses
        ``error[lint-cli-option-invalid]:`` (NOT ``pyproject-config-invalid``)
        to attribute the failure to the CLI flag, not pyproject.
        The rejected value is echoed inline (Fix 14 / REL-1):
        ``{label}[0] 'invalid-no-slash' is not a valid rule_id``."""
        with pytest.raises(SystemExit) as exc_info:
            from protokit.schema.lint._config import ResolvedLintConfig
            ResolvedLintConfig.from_dict(None, {cli_key: ("invalid-no-slash",)})
        assert exc_info.value.code == 2
        captured = capsys.readouterr()
        assert captured.err.startswith("error[lint-cli-option-invalid]:"), (
            f"CLI-sourced error should use 'cli-option-invalid' prefix; "
            f"got: {captured.err!r}"
        )
        assert "'invalid-no-slash' is not a valid rule_id" in captured.err

    @pytest.mark.parametrize("cli_key", _R9B_LIST_KEYS)
    def test_cli_override_normalizes_inputs(self, cli_key: str) -> None:
        """CLI inputs flow through ``.strip().lower()`` just like
        pyproject inputs."""
        resolved = ResolvedLintConfig.from_dict(
            None, {cli_key: ("  Naming/SNAKE-Case-Fields  ",)},
        )
        attr = getattr(resolved, cli_key)
        assert attr == frozenset({"naming/snake-case-fields"})

    @pytest.mark.parametrize("cli_key", _R9B_LIST_KEYS)
    def test_cli_override_with_none_means_flag_absent(
        self, cli_key: str,
    ) -> None:
        """Per KD-5, the CLI delivers ``None`` when the user did not
        type the flag — the natural empty-tuple sentinel is converted
        to ``None`` at the cli.py wiring boundary."""
        resolved = ResolvedLintConfig.from_dict(None, {cli_key: None})
        attr = getattr(resolved, cli_key)
        assert attr == frozenset()
