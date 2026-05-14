"""Substring-ratchet for the KD-9 upgrade-safety docstring.

The KD-9 policy in ``protokit.schema.lint.rules.__init__`` documents
the pre-1.0 stance that new packs may be added to ``BUILTIN_PACKS``
freely when accompanied by a CHANGELOG entry, with the major-version
gate deferred until post-1.0. This test pins the pre-1.0 sentence
as a substring so that an accidental revert to the original
"major-version bump required" wording fails CI rather than silently
landing.

The test is intentionally a substring check, NOT a structural parse:
the docstring is human-facing prose, and re-flowing the surrounding
paragraphs should not break the ratchet. Only deleting or rewording
the pre-1.0 stance itself trips this assertion.
"""

from __future__ import annotations

import protokit.schema.lint.rules as rules_pkg

PRE_1_0_RATCHET_SUBSTRING = "pre-1.0 there is no stability guarantee"


class TestKD9Docstring:
    def test_module_docstring_exists(self) -> None:
        assert rules_pkg.__doc__ is not None, (
            "protokit.schema.lint.rules has no module docstring — "
            "KD-9 policy lives in that docstring; restore it."
        )

    def test_pre_1_0_stance_substring_is_present(self) -> None:
        """Substring ratchet against silent reversion of the pre-1.0 stance.

        See module docstring for the policy this ratchet pins. If
        you are intentionally rewording the KD-9 paragraph, update
        ``PRE_1_0_RATCHET_SUBSTRING`` above to match the new
        wording — but only after confirming the new wording carries
        the same meaning (new packs may be added freely while
        pre-1.0, communicated via CHANGELOG).
        """
        docstring = rules_pkg.__doc__ or ""
        assert PRE_1_0_RATCHET_SUBSTRING in docstring, (
            f"KD-9 docstring no longer contains "
            f"{PRE_1_0_RATCHET_SUBSTRING!r}. The pre-1.0 stance "
            "was reverted or reworded. Either restore the substring "
            "or update PRE_1_0_RATCHET_SUBSTRING in this test "
            "after confirming the new wording carries the same "
            "meaning."
        )
