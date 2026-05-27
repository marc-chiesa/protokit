"""Tests for the D6b Unit 3a R6 deprecated-replacement rule pack.

Covers the 5 rules registered in
:mod:`protokit.schema.lint.rules.options.deprecated_replacement` — one per
``*Options.deprecated`` ElementKind:

- ``options/deprecated-field-must-have-replacement-comment``
- ``options/deprecated-enum-value-must-have-replacement-comment``
- ``options/deprecated-method-must-have-replacement-comment``
- ``options/deprecated-message-must-have-replacement-comment``
- ``options/deprecated-enum-must-have-replacement-comment``

All 5 share ``_check_replacement_comment`` + ``_REPLACEMENT_PATTERNS`` and
the ``_sanitize_comment_for_params`` pipeline (truncate → sanitize →
brace-escape) per K-4 + K-5 of the D6b U3 plan.

Test compile must use ``include_source_info=True`` — without it,
``ctx.source_info_descriptors`` is ``None`` and every deprecated element
produces a finding regardless of comment content. The shared
``_run_single`` helper in ``rules/conftest.py`` defaults to ``False``, so
this module uses local helpers that pass ``include_source_info=True``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from protokit import _cli_utils
from protokit.schema.compile import compile_protos_to_result
from protokit.schema.lint.engine import LintEngine
from protokit.schema.lint.model import (
    ElementKind,
    LintProfile,
    LintReport,
    LintSeverity,
)
from protokit.schema.lint.rules.options import deprecated_replacement
from protokit.schema.lint.rules.options.deprecated_replacement import (
    _REPLACEMENT_PATTERNS,
    RULES,
    _check_replacement_comment,
    _sanitize_comment_for_params,
    check_deprecated_enum_must_have_replacement_comment,
    check_deprecated_enum_value_must_have_replacement_comment,
    check_deprecated_field_must_have_replacement_comment,
    check_deprecated_message_must_have_replacement_comment,
    check_deprecated_method_must_have_replacement_comment,
)

# ---------------------------------------------------------------------------
# Helpers — local because R6 tests need ``include_source_info=True``
# ---------------------------------------------------------------------------


def _compile_with_source_info(
    tmp_path: Path,
    sources: dict[str, str],
) -> Any:
    """Compile ``sources`` with ``include_source_info=True``.

    Mirrors ``rules/conftest._compile`` but enables source-info preservation
    so :func:`leading_comment` can resolve descriptor leading comments.
    """
    paths: list[Path] = []
    for fname, text in sources.items():
        p = tmp_path / fname
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        paths.append(p)
    return compile_protos_to_result(
        paths=paths,
        proto_paths=(str(tmp_path),),
        include_source_info=True,
    )


def _run_single(
    tmp_path: Path,
    sources: dict[str, str],
    rule_id: str,
) -> LintReport:
    """Run the engine with a profile containing only ``rule_id``.

    Compiles with ``include_source_info=True`` and loads the
    ``deprecated_replacement`` pack.
    """
    result = _compile_with_source_info(tmp_path, sources)
    engine = LintEngine()
    engine.load_rule_pack(deprecated_replacement)
    profile = LintProfile(
        name="_test_isolation",
        rule_ids=frozenset({rule_id}),
        min_severity=LintSeverity.INFO,
    )
    return engine.run(result, profile=profile)


# ---------------------------------------------------------------------------
# Module shape — RULES tuple + spec metadata
# ---------------------------------------------------------------------------


class TestPackShape:
    """The pack exposes RULES with all 5 R6 rules registered."""

    def test_rules_tuple_contains_five_callables(self) -> None:
        assert isinstance(RULES, tuple)
        assert len(RULES) == 5
        for fn in RULES:
            assert hasattr(fn, "_lint_spec")

    def test_pack_includes_all_five_rules(self) -> None:
        assert check_deprecated_field_must_have_replacement_comment in RULES
        assert check_deprecated_enum_value_must_have_replacement_comment in RULES
        assert check_deprecated_method_must_have_replacement_comment in RULES
        assert check_deprecated_message_must_have_replacement_comment in RULES
        assert check_deprecated_enum_must_have_replacement_comment in RULES


class TestRuleSpecs:
    """Each rule carries the expected D6b U3a spec metadata."""

    def test_field_spec(self) -> None:
        spec = check_deprecated_field_must_have_replacement_comment._lint_spec  # type: ignore[attr-defined]
        assert spec.rule_id == "options/deprecated-field-must-have-replacement-comment"
        assert spec.severity is LintSeverity.ERROR
        assert spec.profiles == ("default",)
        assert spec.element is ElementKind.FIELD
        assert spec.source_spec == ""

    def test_enum_value_spec(self) -> None:
        spec = check_deprecated_enum_value_must_have_replacement_comment._lint_spec  # type: ignore[attr-defined]
        assert spec.rule_id == "options/deprecated-enum-value-must-have-replacement-comment"
        assert spec.severity is LintSeverity.ERROR
        assert spec.profiles == ("default",)
        assert spec.element is ElementKind.ENUM_VALUE
        assert spec.source_spec == ""

    def test_method_spec(self) -> None:
        spec = check_deprecated_method_must_have_replacement_comment._lint_spec  # type: ignore[attr-defined]
        assert spec.rule_id == "options/deprecated-method-must-have-replacement-comment"
        assert spec.severity is LintSeverity.ERROR
        assert spec.profiles == ("default",)
        assert spec.element is ElementKind.METHOD
        assert spec.source_spec == ""

    def test_message_spec(self) -> None:
        spec = check_deprecated_message_must_have_replacement_comment._lint_spec  # type: ignore[attr-defined]
        assert spec.rule_id == "options/deprecated-message-must-have-replacement-comment"
        assert spec.severity is LintSeverity.ERROR
        assert spec.profiles == ("default",)
        assert spec.element is ElementKind.MESSAGE
        assert spec.source_spec == ""

    def test_enum_spec(self) -> None:
        spec = check_deprecated_enum_must_have_replacement_comment._lint_spec  # type: ignore[attr-defined]
        assert spec.rule_id == "options/deprecated-enum-must-have-replacement-comment"
        assert spec.severity is LintSeverity.ERROR
        assert spec.profiles == ("default",)
        assert spec.element is ElementKind.ENUM
        assert spec.source_spec == ""

    def test_all_rules_share_default_only_profile(self) -> None:
        """R6 ships in ``default`` only — ``recommended`` stays buf-BASIC parity."""
        for fn in RULES:
            assert fn._lint_spec.profiles == ("default",), (  # type: ignore[attr-defined]
                f"{fn._lint_spec.rule_id}: profiles must be ('default',) only"  # type: ignore[attr-defined]
            )

    def test_all_rules_protokit_original(self) -> None:
        """R6 has no buf analogue → empty ``source_spec`` excludes from parity."""
        for fn in RULES:
            assert fn._lint_spec.source_spec == "", (  # type: ignore[attr-defined]
                f"{fn._lint_spec.rule_id}: source_spec must be empty (R6 has no buf analogue)"  # type: ignore[attr-defined]
            )

    def test_all_rules_protokit_original_substring_in_docstring(self) -> None:
        """U7 presence ratchet hint — each rule's docstring carries 'Protokit-original'."""
        for fn in RULES:
            doc = fn.__doc__ or ""
            assert "Protokit-original" in doc, (
                f"{fn._lint_spec.rule_id}: docstring must contain 'Protokit-original'"  # type: ignore[attr-defined]
            )


# ---------------------------------------------------------------------------
# _REPLACEMENT_PATTERNS + _check_replacement_comment unit tests
# ---------------------------------------------------------------------------


class TestReplacementPatterns:
    """Starting 4-pattern set — precision-first."""

    def test_four_starting_patterns(self) -> None:
        assert len(_REPLACEMENT_PATTERNS) == 4

    def test_use_x_instead_matches(self) -> None:
        assert _check_replacement_comment("Use NewField instead.")
        assert _check_replacement_comment("use new_field instead")
        assert _check_replacement_comment("USE com.acme.NewType INSTEAD")

    def test_replaced_by_matches(self) -> None:
        assert _check_replacement_comment("Replaced by NewField.")
        assert _check_replacement_comment("replaced with new_field")
        # ``replace by`` (without 'd') also matches the optional 'd?'.
        assert _check_replacement_comment("Replace by NewType")

    def test_migrate_to_matches(self) -> None:
        assert _check_replacement_comment("Migrate to v2.NewField.")
        assert _check_replacement_comment("MIGRATE TO new_api")

    def test_see_x_for_replacement_matches(self) -> None:
        assert _check_replacement_comment("See NewField for replacement.")
        assert _check_replacement_comment("see com.acme.NewType for the replacement")

    def test_javadoc_brace_form_matches(self) -> None:
        """Optional outer braces accommodate Javadoc-style references.

        Per the adversarial reviewer finding (D6b U3 /ce:review): protobuf
        authors borrowing JavaDoc-style conventions write
        ``Use {NewField} instead.`` instead of bare ``Use NewField instead.``.
        Without the optional ``\\{?...\\}?`` anchors in each pattern,
        ``[\\w.]+`` cannot match the braced token (``{`` is not a word
        char), producing a false negative on a canonical replacement
        reference. The brace anchors close that gap.
        """
        assert _check_replacement_comment("Use {NewField} instead.")
        assert _check_replacement_comment("use {new_field} instead")
        assert _check_replacement_comment("Replaced by {NewType}.")
        assert _check_replacement_comment("Migrate to {v2.NewField}.")
        assert _check_replacement_comment(
            "See {com.acme.NewType} for the replacement"
        )

    def test_non_canonical_phrasings_do_not_match(self) -> None:
        # Documented false negatives — precision-first per parent brainstorm.
        # These are deliberately ALLOWED to miss in the starting set.
        assert not _check_replacement_comment("@deprecated foo.Bar")
        assert not _check_replacement_comment("Removed: prefer NewField.")
        assert not _check_replacement_comment("DEPRECATED. See newer api.")
        assert not _check_replacement_comment("Don't use this field.")

    def test_none_returns_false(self) -> None:
        assert not _check_replacement_comment(None)

    def test_empty_string_returns_false(self) -> None:
        assert not _check_replacement_comment("")

    def test_word_boundary_prevents_substring_match(self) -> None:
        # ``misuse`` should NOT match ``use X instead`` if no real
        # ``use ... instead`` phrase is present.
        assert not _check_replacement_comment("misuse instead is bad")


class TestSanitizeCommentForParams:
    """Pipeline: truncate → sanitize → brace-escape."""

    def test_truncates_to_500_chars(self) -> None:
        long = "a" * 1000
        result = _sanitize_comment_for_params(long)
        # No braces in input, no sanitization needed → exactly 500 chars.
        assert len(result) == 500

    def test_none_returns_empty_string(self) -> None:
        assert _sanitize_comment_for_params(None) == ""

    def test_control_chars_collapsed_to_spaces(self) -> None:
        text = "Use\nNewField\rinstead\t."
        result = _sanitize_comment_for_params(text)
        # Newline/CR/tab collapsed by _safe_for_stderr.
        assert "\n" not in result
        assert "\r" not in result
        assert "\t" not in result
        # The visible content survives (with whitespace collapsed).
        assert "Use" in result
        assert "NewField" in result
        assert "instead" in result

    def test_u2028_u2029_sanitized(self) -> None:
        text = "line one\u2028line two\u2029line three"
        result = _sanitize_comment_for_params(text)
        assert "\u2028" not in result
        assert "\u2029" not in result

    def test_braces_doubled(self) -> None:
        text = "Use {NewField} instead."
        result = _sanitize_comment_for_params(text)
        assert "{{NewField}}" in result
        # Single braces gone, doubled present.
        assert "{NewField}" not in result.replace("{{NewField}}", "")

    def test_truncate_before_sanitize_combination(self) -> None:
        # 600 chars of mixed content; truncated to 500 first.
        text = "a" * 250 + "\n" + "b" * 350
        result = _sanitize_comment_for_params(text)
        assert len(result) == 500
        # The \n at position 250 was inside the truncated window.
        assert "\n" not in result


# ---------------------------------------------------------------------------
# Per-rule integration tests — happy path + sad path + edges
# ---------------------------------------------------------------------------


# Inline proto fixtures keyed by ElementKind. Each proto carries:
# - One deprecated element WITH a matching comment (zero findings expected)
# - One deprecated element with a non-matching comment (one finding expected)
# - One deprecated element with no comment (one finding expected)
# - One non-deprecated element (zero findings expected, regardless of comment)


_FIELD_PROTO_HAPPY = """\
syntax = "proto3";
package demo;

message User {
    // Use replacement_field instead.
    string old_field = 1 [deprecated = true];

    string current_field = 2;
}
"""

_FIELD_PROTO_SAD = """\
syntax = "proto3";
package demo;

message User {
    // This is being removed.
    string old_field = 1 [deprecated = true];
}
"""

_FIELD_PROTO_NO_COMMENT = """\
syntax = "proto3";
package demo;

message User {
    string old_field = 1 [deprecated = true];
}
"""

_FIELD_PROTO_NOT_DEPRECATED = """\
syntax = "proto3";
package demo;

message User {
    string old_field = 1;
}
"""


class TestDeprecatedFieldRule:
    """``options/deprecated-field-must-have-replacement-comment`` end-to-end."""

    def test_happy_path_matching_comment_yields_no_findings(
        self, tmp_path: Path,
    ) -> None:
        report = _run_single(
            tmp_path,
            {"demo.proto": _FIELD_PROTO_HAPPY},
            "options/deprecated-field-must-have-replacement-comment",
        )
        assert len(report.findings) == 0

    def test_sad_path_non_matching_comment_yields_one_finding(
        self, tmp_path: Path,
    ) -> None:
        report = _run_single(
            tmp_path,
            {"demo.proto": _FIELD_PROTO_SAD},
            "options/deprecated-field-must-have-replacement-comment",
        )
        assert len(report.findings) == 1
        f = report.findings[0]
        assert f.severity is LintSeverity.ERROR
        assert f.violation_kind == "options/deprecated-field-must-have-replacement-comment"
        # The non-matching comment is preserved (sanitized) in params.
        assert "This is being removed." in f.params["comment"]
        assert f.params["name"] == "old_field"

    def test_no_comment_yields_one_finding(
        self, tmp_path: Path,
    ) -> None:
        report = _run_single(
            tmp_path,
            {"demo.proto": _FIELD_PROTO_NO_COMMENT},
            "options/deprecated-field-must-have-replacement-comment",
        )
        assert len(report.findings) == 1
        # Empty comment in params (no leading_comment text was found).
        assert report.findings[0].params["comment"] == ""

    def test_not_deprecated_yields_no_findings(
        self, tmp_path: Path,
    ) -> None:
        report = _run_single(
            tmp_path,
            {"demo.proto": _FIELD_PROTO_NOT_DEPRECATED},
            "options/deprecated-field-must-have-replacement-comment",
        )
        assert len(report.findings) == 0


_ENUM_VALUE_PROTO_HAPPY = """\
syntax = "proto3";
package demo;

enum Status {
    UNKNOWN = 0;
    // Use ACTIVE instead.
    LEGACY = 1 [deprecated = true];
    ACTIVE = 2;
}
"""

_ENUM_VALUE_PROTO_SAD = """\
syntax = "proto3";
package demo;

enum Status {
    UNKNOWN = 0;
    // No replacement available.
    LEGACY = 1 [deprecated = true];
}
"""

_ENUM_VALUE_PROTO_NO_COMMENT = """\
syntax = "proto3";
package demo;

enum Status {
    UNKNOWN = 0;
    LEGACY = 1 [deprecated = true];
}
"""

_ENUM_VALUE_PROTO_NOT_DEPRECATED = """\
syntax = "proto3";
package demo;

enum Status {
    UNKNOWN = 0;
    LEGACY = 1;
}
"""


class TestDeprecatedEnumValueRule:
    def test_happy_path_matching_comment(self, tmp_path: Path) -> None:
        report = _run_single(
            tmp_path,
            {"demo.proto": _ENUM_VALUE_PROTO_HAPPY},
            "options/deprecated-enum-value-must-have-replacement-comment",
        )
        assert len(report.findings) == 0

    def test_sad_path_non_matching_comment(self, tmp_path: Path) -> None:
        report = _run_single(
            tmp_path,
            {"demo.proto": _ENUM_VALUE_PROTO_SAD},
            "options/deprecated-enum-value-must-have-replacement-comment",
        )
        assert len(report.findings) == 1
        f = report.findings[0]
        assert f.severity is LintSeverity.ERROR
        assert f.params["name"] == "LEGACY"

    def test_no_comment_yields_one_finding(self, tmp_path: Path) -> None:
        report = _run_single(
            tmp_path,
            {"demo.proto": _ENUM_VALUE_PROTO_NO_COMMENT},
            "options/deprecated-enum-value-must-have-replacement-comment",
        )
        assert len(report.findings) == 1
        assert report.findings[0].params["comment"] == ""

    def test_not_deprecated_yields_no_findings(self, tmp_path: Path) -> None:
        report = _run_single(
            tmp_path,
            {"demo.proto": _ENUM_VALUE_PROTO_NOT_DEPRECATED},
            "options/deprecated-enum-value-must-have-replacement-comment",
        )
        assert len(report.findings) == 0


_METHOD_PROTO_HAPPY = """\
syntax = "proto3";
package demo;

message Req {}
message Resp {}

service S {
    // Replaced by GetUserV2.
    rpc GetUser (Req) returns (Resp) {
        option deprecated = true;
    }
}
"""

_METHOD_PROTO_SAD = """\
syntax = "proto3";
package demo;

message Req {}
message Resp {}

service S {
    // Old RPC.
    rpc GetUser (Req) returns (Resp) {
        option deprecated = true;
    }
}
"""


_METHOD_PROTO_NO_COMMENT = """\
syntax = "proto3";
package demo;

message Req {}
message Resp {}

service S {
    rpc GetUser (Req) returns (Resp) {
        option deprecated = true;
    }
}
"""

_METHOD_PROTO_NOT_DEPRECATED = """\
syntax = "proto3";
package demo;

message Req {}
message Resp {}

service S {
    rpc GetUser (Req) returns (Resp);
}
"""


class TestDeprecatedMethodRule:
    def test_happy_path_matching_comment(self, tmp_path: Path) -> None:
        report = _run_single(
            tmp_path,
            {"demo.proto": _METHOD_PROTO_HAPPY},
            "options/deprecated-method-must-have-replacement-comment",
        )
        assert len(report.findings) == 0

    def test_sad_path_non_matching_comment(self, tmp_path: Path) -> None:
        report = _run_single(
            tmp_path,
            {"demo.proto": _METHOD_PROTO_SAD},
            "options/deprecated-method-must-have-replacement-comment",
        )
        assert len(report.findings) == 1
        assert report.findings[0].params["name"] == "GetUser"

    def test_no_comment_yields_one_finding(self, tmp_path: Path) -> None:
        report = _run_single(
            tmp_path,
            {"demo.proto": _METHOD_PROTO_NO_COMMENT},
            "options/deprecated-method-must-have-replacement-comment",
        )
        assert len(report.findings) == 1
        assert report.findings[0].params["comment"] == ""

    def test_not_deprecated_yields_no_findings(self, tmp_path: Path) -> None:
        report = _run_single(
            tmp_path,
            {"demo.proto": _METHOD_PROTO_NOT_DEPRECATED},
            "options/deprecated-method-must-have-replacement-comment",
        )
        assert len(report.findings) == 0


_MESSAGE_PROTO_HAPPY = """\
syntax = "proto3";
package demo;

// Migrate to UserV2.
message User {
    option deprecated = true;
    string name = 1;
}
"""

_MESSAGE_PROTO_SAD = """\
syntax = "proto3";
package demo;

// Legacy entity.
message User {
    option deprecated = true;
    string name = 1;
}
"""


_MESSAGE_PROTO_NO_COMMENT = """\
syntax = "proto3";
package demo;

message User {
    option deprecated = true;
    string name = 1;
}
"""

_MESSAGE_PROTO_NOT_DEPRECATED = """\
syntax = "proto3";
package demo;

message User {
    string name = 1;
}
"""


class TestDeprecatedMessageRule:
    def test_happy_path_matching_comment(self, tmp_path: Path) -> None:
        report = _run_single(
            tmp_path,
            {"demo.proto": _MESSAGE_PROTO_HAPPY},
            "options/deprecated-message-must-have-replacement-comment",
        )
        assert len(report.findings) == 0

    def test_sad_path_non_matching_comment(self, tmp_path: Path) -> None:
        report = _run_single(
            tmp_path,
            {"demo.proto": _MESSAGE_PROTO_SAD},
            "options/deprecated-message-must-have-replacement-comment",
        )
        assert len(report.findings) == 1
        assert report.findings[0].params["name"] == "User"

    def test_no_comment_yields_one_finding(self, tmp_path: Path) -> None:
        report = _run_single(
            tmp_path,
            {"demo.proto": _MESSAGE_PROTO_NO_COMMENT},
            "options/deprecated-message-must-have-replacement-comment",
        )
        assert len(report.findings) == 1
        assert report.findings[0].params["comment"] == ""

    def test_not_deprecated_yields_no_findings(self, tmp_path: Path) -> None:
        report = _run_single(
            tmp_path,
            {"demo.proto": _MESSAGE_PROTO_NOT_DEPRECATED},
            "options/deprecated-message-must-have-replacement-comment",
        )
        assert len(report.findings) == 0


_ENUM_PROTO_HAPPY = """\
syntax = "proto3";
package demo;

// See StatusV2 for the replacement.
enum Status {
    option deprecated = true;
    UNKNOWN = 0;
    ACTIVE = 1;
}
"""

_ENUM_PROTO_SAD = """\
syntax = "proto3";
package demo;

// Old enum.
enum Status {
    option deprecated = true;
    UNKNOWN = 0;
}
"""

_ENUM_PROTO_NO_COMMENT = """\
syntax = "proto3";
package demo;

enum Status {
    option deprecated = true;
    UNKNOWN = 0;
}
"""

_ENUM_PROTO_NOT_DEPRECATED = """\
syntax = "proto3";
package demo;

enum Status {
    UNKNOWN = 0;
}
"""


class TestDeprecatedEnumRule:
    def test_happy_path_matching_comment(self, tmp_path: Path) -> None:
        report = _run_single(
            tmp_path,
            {"demo.proto": _ENUM_PROTO_HAPPY},
            "options/deprecated-enum-must-have-replacement-comment",
        )
        assert len(report.findings) == 0

    def test_sad_path_non_matching_comment(self, tmp_path: Path) -> None:
        report = _run_single(
            tmp_path,
            {"demo.proto": _ENUM_PROTO_SAD},
            "options/deprecated-enum-must-have-replacement-comment",
        )
        assert len(report.findings) == 1
        assert report.findings[0].params["name"] == "Status"

    def test_no_comment_yields_one_finding(self, tmp_path: Path) -> None:
        report = _run_single(
            tmp_path,
            {"demo.proto": _ENUM_PROTO_NO_COMMENT},
            "options/deprecated-enum-must-have-replacement-comment",
        )
        assert len(report.findings) == 1
        assert report.findings[0].params["comment"] == ""

    def test_not_deprecated_yields_no_findings(self, tmp_path: Path) -> None:
        report = _run_single(
            tmp_path,
            {"demo.proto": _ENUM_PROTO_NOT_DEPRECATED},
            "options/deprecated-enum-must-have-replacement-comment",
        )
        assert len(report.findings) == 0


# ---------------------------------------------------------------------------
# Legacy-state test: source_info_descriptors is None → over-reports
# ---------------------------------------------------------------------------


class TestLegacySourceInfoNone:
    """When ``source_info_descriptors`` is ``None`` (no opt-in), R6 over-reports."""

    def test_field_over_reports_without_source_info(
        self, tmp_path: Path,
    ) -> None:
        # Compile WITHOUT include_source_info=True — emulates a caller
        # that hasn't opted in (or a descriptor set built without
        # --include_source_info).
        p = tmp_path / "demo.proto"
        p.write_text(_FIELD_PROTO_HAPPY)  # has matching comment
        result = compile_protos_to_result(
            paths=[p],
            proto_paths=(str(tmp_path),),
            # include_source_info NOT passed (defaults to False)
        )
        assert result.source_info_descriptors is None

        engine = LintEngine()
        engine.load_rule_pack(deprecated_replacement)
        profile = LintProfile(
            name="_test_isolation",
            rule_ids=frozenset(
                {"options/deprecated-field-must-have-replacement-comment"},
            ),
            min_severity=LintSeverity.INFO,
        )
        report = engine.run(result, profile=profile)
        # Without source info, leading_comment returns None and the helper
        # returns False — so the deprecated field over-reports despite
        # carrying a perfectly good replacement comment in the .proto source.
        # This is the documented descriptor-set-mode caveat (K-9).
        assert len(report.findings) == 1


# ---------------------------------------------------------------------------
# Adversarial fixtures: multi-KB, control chars, U+2028/2029, braces
# ---------------------------------------------------------------------------


_ADVERSARIAL_PROTO_TEMPLATE = """\
syntax = "proto3";
package adversarial;

message AdversarialMessages {{
    {comment}
    string offending_field = 1 [deprecated = true];
}}
"""


def _make_adversarial_proto(comment_body: str) -> str:
    # The comment is rendered as a // line followed by the body. Newlines
    # in body would break the proto syntax, so we always treat body as a
    # single C-style comment.
    indented_lines = [f"    // {line}" for line in comment_body.split("\n")]
    return _ADVERSARIAL_PROTO_TEMPLATE.format(comment="\n".join(indented_lines))


class TestAdversarial:
    """Multi-KB / control-char / brace adversarial inputs."""

    def test_multi_kb_comment_truncated_to_500_chars(
        self, tmp_path: Path,
    ) -> None:
        # 5KB of single-line text — no newlines inside the comment body.
        long_body = "a" * 5000
        proto = _make_adversarial_proto(long_body)
        report = _run_single(
            tmp_path,
            {"adv.proto": proto},
            "options/deprecated-field-must-have-replacement-comment",
        )
        assert len(report.findings) == 1
        # Truncated to 500 chars BEFORE brace-escape. Brace-escape can
        # double each `{`/`}` to `{{`/`}}`, so the post-pipeline upper
        # bound is 1000 chars in the worst case (all-brace input).
        # This fixture uses 'a' * 5000 (no braces), so the actual length
        # is exactly 500, but the bound below documents the general case.
        assert len(report.findings[0].params["comment"]) <= 1000

    @pytest.mark.skipif(
        not _cli_utils._has_protoxy(),
        reason=(
            "fixture deliberately embeds U+0085 / U+2028 / U+2029 / NUL / DEL "
            "control chars in a // comment to verify the sanitization "
            "pipeline. Strict protoc (3.21+) rejects these at parse time "
            "(`Invalid control characters encountered in text`), so the lint "
            "rule never observes the descriptor. Protoxy's embedded protoc "
            "permits the input through to the rule; the adversarial coverage "
            "is meaningful only on the protoxy backend"
        ),
    )
    def test_control_chars_sanitized(self, tmp_path: Path) -> None:
        # Proto-comment // lines can't carry raw newlines in the body
        # itself (// ends at the next \n), but they CAN carry U+0085 /
        # U+2028 / U+2029 / NUL / DEL as bytes embedded in the // text.
        # The comment body deliberately does NOT match any pattern in
        # _REPLACEMENT_PATTERNS so the rule fires unconditionally and
        # the sanitization assertions are never skipped via a vacuous
        # early-return. The forbidden chars are written as escape
        # sequences (\u2028 etc.) rather than raw literals so the source
        # file stays editor-safe and review-diffable.
        body = (
            "Removed nel\x85 line\u2028 para\u2029 del\x7f nul\x00 chars"
        )
        proto = _make_adversarial_proto(body)
        report = _run_single(
            tmp_path,
            {"adv.proto": proto},
            "options/deprecated-field-must-have-replacement-comment",
        )
        # Body matches no replacement pattern → exactly one finding fires.
        assert len(report.findings) == 1
        sanitized = report.findings[0].params["comment"]
        # Confirm every targeted control char was collapsed by
        # _safe_for_stderr.
        for forbidden in ("\x85", "\u2028", "\u2029", "\x7f", "\x00"):
            assert forbidden not in sanitized, (
                f"forbidden char {forbidden!r} survived sanitization"
            )

    def test_braces_in_comment_safe_for_format(self, tmp_path: Path) -> None:
        body = "Use {NewField} for replacement key {foo}"
        proto = _make_adversarial_proto(body)
        report = _run_single(
            tmp_path,
            {"adv.proto": proto},
            "options/deprecated-field-must-have-replacement-comment",
        )
        # The comment doesn't match any pattern (no "instead", no "by/with",
        # no "migrate to", no "see X for the replacement"), so a finding fires.
        assert len(report.findings) == 1
        sanitized = report.findings[0].params["comment"]
        # Braces are doubled per K-4.
        assert "{{NewField}}" in sanitized
        assert "{{foo}}" in sanitized
        # Single-brace tokens are gone (every { became {{).
        # Verify no unpaired single brace exists.
        single_left = sanitized.count("{") - 2 * sanitized.count("{{")
        single_right = sanitized.count("}") - 2 * sanitized.count("}}")
        assert single_left == 0
        assert single_right == 0

    def test_braces_render_via_message_template_without_keyerror(
        self, tmp_path: Path,
    ) -> None:
        """End-to-end: rendered message must not raise KeyError on adversarial braces."""
        body = "Use {arbitrary_key} as a replacement"
        proto = _make_adversarial_proto(body)
        report = _run_single(
            tmp_path,
            {"adv.proto": proto},
            "options/deprecated-field-must-have-replacement-comment",
        )
        assert len(report.findings) == 1
        finding = report.findings[0]
        # Render the message template manually (engine doesn't pre-render).
        spec = check_deprecated_field_must_have_replacement_comment._lint_spec  # type: ignore[attr-defined]
        # Resolve template (string for single-kind rules).
        template = (
            spec.message_template
            if isinstance(spec.message_template, str)
            else spec.message_template[finding.violation_kind]
        )
        # This MUST NOT raise KeyError on the adversarial brace tokens.
        rendered = template.format(**finding.params)
        # And the rendered message should contain the safe doubled form.
        assert "{arbitrary_key}" in rendered or "{{arbitrary_key}}" in rendered


# ---------------------------------------------------------------------------
# Profile composition: R6 fires under default, silent under recommended
# ---------------------------------------------------------------------------


_MIXED_PROTO = """\
syntax = "proto3";
package mixed;

// Old field.
message Mix {
    string deprecated_field = 1 [deprecated = true];
}
"""


class TestProfileMembership:
    """R6 fires under ``default``; silent under ``recommended``."""

    def test_default_profile_fires_r6(self, tmp_path: Path) -> None:
        result = _compile_with_source_info(tmp_path, {"mix.proto": _MIXED_PROTO})
        engine = LintEngine()
        engine.load_rule_pack(deprecated_replacement)
        profile = LintProfile.from_pack(deprecated_replacement, "default")
        report = engine.run(result, profile=profile)
        assert len(report.findings) == 1
        assert (
            report.findings[0].rule_id
            == "options/deprecated-field-must-have-replacement-comment"
        )

    def test_recommended_profile_silent_on_r6(self, tmp_path: Path) -> None:
        result = _compile_with_source_info(tmp_path, {"mix.proto": _MIXED_PROTO})
        engine = LintEngine()
        engine.load_rule_pack(deprecated_replacement)
        # ``recommended`` is not declared on any R6 rule → from_pack
        # composes an empty rule_ids set for this profile name.
        profile = LintProfile.from_pack(deprecated_replacement, "recommended")
        report = engine.run(result, profile=profile)
        assert len(report.findings) == 0


# ---------------------------------------------------------------------------
# Per-rule severities demotion via the standard [severities] table
# ---------------------------------------------------------------------------


class TestPerRuleSeveritiesDemotion:
    """A single R6 rule demoted to info → that rule's findings render as info."""

    def test_field_rule_demoted_to_info(self, tmp_path: Path) -> None:
        result = _compile_with_source_info(
            tmp_path, {"demo.proto": _FIELD_PROTO_SAD},
        )
        engine = LintEngine()
        engine.load_rule_pack(deprecated_replacement)
        profile = LintProfile(
            name="_test_demotion",
            rule_ids=frozenset(
                {"options/deprecated-field-must-have-replacement-comment"},
            ),
            min_severity=LintSeverity.INFO,
            rule_severity_overrides={
                "options/deprecated-field-must-have-replacement-comment": (
                    LintSeverity.INFO
                ),
            },
        )
        report = engine.run(result, profile=profile)
        assert len(report.findings) == 1
        assert report.findings[0].severity is LintSeverity.INFO
