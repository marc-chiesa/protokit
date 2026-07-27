"""Tests for buf-compatibility profile alias resolution (D6a U2, KTD-1).

Covers:

- The ``_PROFILE_ALIASES`` mapping resolves ``minimal -> essentials``
  and ``basic -> recommended`` at the ``_coerce_profile`` input boundary.
- Both pyproject and CLI input paths flow through ``_coerce_profile``,
  so alias resolution covers both surfaces with a single declaration
  (no double-resolution needed downstream).
- Resolution is case-insensitive and whitespace-tolerant per the
  ``normalize-at-input-boundary`` learning (the alias check happens
  AFTER ``.strip().lower()``).
- Primary protokit-native names (``essentials``, ``recommended``,
  ``default``) pass through unchanged.
- Aliases in a list-form profile resolve per-element.

The R7 mapping was carried in by D6a from the origin brainstorm; the
pinned set is exactly two entries — adding a third without updating
the tests is a regression signal.
"""

from __future__ import annotations

from protokit.schema.lint._config import (
    _PROFILE_ALIASES,
    ResolvedLintConfig,
    _coerce_profile,
)

# ---------------------------------------------------------------------------
# The mapping itself
# ---------------------------------------------------------------------------


class TestAliasMapping:
    def test_mapping_pinned_to_two_entries(self) -> None:
        """``_PROFILE_ALIASES`` contains exactly the two buf compatibility
        aliases with their documented primary-name targets. A drift here
        (e.g., adding ``strict -> default``, renaming ``recommended``)
        needs an explicit test update to stay coherent with R7's "buf
        aliases only" framing.
        """
        assert _PROFILE_ALIASES == {
            "minimal": "essentials",
            "basic": "recommended",
        }


# ---------------------------------------------------------------------------
# _coerce_profile resolves aliases at the boundary
# ---------------------------------------------------------------------------


class TestCoerceProfileResolvesAliases:
    def test_minimal_resolves_to_essentials(self) -> None:
        assert _coerce_profile("minimal") == ("essentials",)

    def test_basic_resolves_to_recommended(self) -> None:
        assert _coerce_profile("basic") == ("recommended",)

    def test_primary_name_passes_through_unchanged(self) -> None:
        """``essentials``/``recommended``/``default`` are primary names —
        they must not double-resolve or otherwise change.
        """
        assert _coerce_profile("essentials") == ("essentials",)
        assert _coerce_profile("recommended") == ("recommended",)
        assert _coerce_profile("default") == ("default",)

    def test_unknown_name_passes_through_unchanged(self) -> None:
        """Unknown names are returned verbatim (after normalization);
        rule-pack profile-name matching downstream decides whether the
        name resolves to anything. The alias mechanism is closed-set,
        not a free-form rewrite.
        """
        assert _coerce_profile("strict") == ("strict",)

    def test_uppercase_alias_normalized_then_resolved(self) -> None:
        """Per ``normalize-at-input-boundary``: ``.strip().lower()``
        runs BEFORE the alias check, so ``BASIC`` resolves through.
        """
        assert _coerce_profile("BASIC") == ("recommended",)
        assert _coerce_profile("Minimal") == ("essentials",)

    def test_whitespace_alias_normalized_then_resolved(self) -> None:
        assert _coerce_profile("  basic  ") == ("recommended",)
        assert _coerce_profile("\tminimal\n") == ("essentials",)

    def test_list_form_resolves_per_element(self) -> None:
        """Multi-profile composition: each element resolves through the
        alias mapping independently. Mixed alias + primary input is
        the common upgrade scenario for users adding the new
        ``recommended`` profile alongside an existing buf-aliased
        ``basic`` entry.
        """
        assert _coerce_profile(["basic", "default"]) == (
            "recommended",
            "default",
        )
        assert _coerce_profile(["minimal", "BASIC"]) == (
            "essentials",
            "recommended",
        )


# ---------------------------------------------------------------------------
# Alias resolution covers both pyproject and CLI input paths
# ---------------------------------------------------------------------------


class TestAliasesAcrossInputSurfaces:
    """Both pyproject ``profile = "basic"`` and CLI ``--profile basic``
    flow through ``_coerce_profile`` in ``from_dict``, so the alias
    mapping covers both surfaces with one declaration. These tests
    pin that contract at the ``ResolvedLintConfig`` boundary.
    """

    def test_pyproject_alias_resolves(self) -> None:
        resolved = ResolvedLintConfig.from_dict({"profile": "basic"}, {})
        assert resolved.profile == ("recommended",)

    def test_cli_alias_resolves(self) -> None:
        """The CLI override is passed RAW — exactly the
        ``tuple[str, ...]`` shape ``cli.py`` builds from the flag value,
        with no coercion pre-applied by the test.

        Pre-applying ``_coerce_profile`` here (the shape this test used
        to have) made it pass whether or not ``from_dict`` coerced the
        CLI tier at all, which is how ``--profile basic`` shipped
        exiting 2 while ``profile = "basic"`` linted. The end-to-end
        flag path is pinned in
        ``tests/schema/lint/cli/test_cli_profile_resolution.py``
        (``TestProfileAliasOnCliSurface``).
        """
        resolved = ResolvedLintConfig.from_dict(None, {"profile": ("basic",)})
        assert resolved.profile == ("recommended",)

    def test_cli_raw_value_is_normalized_then_resolved(self) -> None:
        """``from_dict`` is the single normalization boundary for the CLI
        tier: case and surrounding whitespace are folded before the alias
        lookup, so the flag layer hands its value over untouched.
        """
        resolved = ResolvedLintConfig.from_dict(
            None, {"profile": ("  BASIC  ",)},
        )
        assert resolved.profile == ("recommended",)

    def test_cli_replaces_pyproject_alias_with_alias(self) -> None:
        """CLI replaces pyproject for ``profile`` — both sides going
        through ``_coerce_profile`` means the CLI's alias takes
        precedence and resolves through the same mapping. The CLI value
        is raw here for the same reason as above.
        """
        resolved = ResolvedLintConfig.from_dict(
            {"profile": "basic"},
            {"profile": ("minimal",)},
        )
        assert resolved.profile == ("essentials",)


# ---------------------------------------------------------------------------
# Composition with the existing list-form profile
# ---------------------------------------------------------------------------


class TestAliasInListForm:
    def test_mixed_list_in_pyproject(self) -> None:
        resolved = ResolvedLintConfig.from_dict(
            {"profile": ["basic", "default"]}, {},
        )
        assert resolved.profile == ("recommended", "default")

    def test_all_aliases_in_pyproject(self) -> None:
        resolved = ResolvedLintConfig.from_dict(
            {"profile": ["minimal", "basic"]}, {},
        )
        assert resolved.profile == ("essentials", "recommended")
