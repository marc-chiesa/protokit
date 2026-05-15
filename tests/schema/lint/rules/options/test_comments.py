"""Tests for ``protokit.schema.lint.rules.options._comments`` (D6b Unit 2).

Pins the two module-level free functions that bridge ``CompileResult.source_info_descriptors``
(shipped in U1) to the 5 R6 ElementKind LintContexts (wired in U2):

1. ``descriptor_path(descriptor) -> tuple[int, ...]`` — descriptor-graph
   coordinates encoder, dispatching across ``FieldDescriptor``,
   ``EnumValueDescriptor``, ``MethodDescriptor``, ``Descriptor`` (message)
   and ``EnumDescriptor``. Handles both top-level and nested cases.
2. ``leading_comment(source_info_descriptors, file_name, path) -> str | None``
   — leaf lookup walking ``source_code_info.location[]``. Returns the
   stripped ``leading_comments`` string or ``None`` for every shape of
   missing data.

These are pure-Python helpers operating on already-built descriptors and
``FileDescriptorProto`` instances; no backend dependency. ``descriptor_path``
tests build a real pool from an inline ``.proto`` fixture (the simplest way
to get authentic descriptor instances). ``leading_comment`` tests construct
``FileDescriptorProto`` instances by hand so the unit-level normalization
contract is exercised without backend coupling.

The wire-tag numbers asserted on (``4``/``5``/``6`` at the file level and
``2``/``3``/``4`` inside containers) come from ``descriptor.proto`` and are
the same contract R6 rules in U3 will rely on.
"""

from __future__ import annotations

from pathlib import Path

from google.protobuf import descriptor_pb2

from protokit.schema.compile import compile_protos_to_result
from protokit.schema.lint.rules.options._comments import (
    descriptor_path,
    leading_comment,
)

# Inline proto fixture: top-level message with a field, a nested message
# (with a field), a nested enum (with a value); a file-level enum (with
# a value); a service with a method. Covers all 5 ElementKinds + the
# top-level vs nested split on messages and enums.
_PROTO = """\
syntax = "proto3";
package demo;

// Leading comment on TopMessage.
// Use TopMessageV2 instead.
message TopMessage {
    // Leading comment on top_field.
    string top_field = 1;

    // Leading comment on Nested.
    message Nested {
        // Leading comment on nested_field.
        int32 nested_field = 1;
    }

    // Leading comment on NestedEnum.
    enum NestedEnum {
        // Leading comment on NESTED_DEFAULT.
        NESTED_DEFAULT = 0;
        NESTED_ONE = 1;
    }
}

// Leading comment on TopEnum.
enum TopEnum {
    // Leading comment on TOP_DEFAULT.
    TOP_DEFAULT = 0;
    TOP_ONE = 1;
}

// Leading comment on DemoService.
service DemoService {
    // Leading comment on Echo.
    rpc Echo (TopMessage) returns (TopMessage);
}
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_pool(tmp_path: Path):
    """Compile the fixture proto and return its FileDescriptor + source-info map."""
    p = tmp_path / "demo.proto"
    p.write_text(_PROTO)
    result = compile_protos_to_result([p], include_source_info=True)
    assert result.source_info_descriptors is not None, (
        "fixture compile failed; cannot run descriptor_path tests"
    )
    fd = result.pool.FindFileByName("demo.proto")
    return fd, result.source_info_descriptors


def _make_fd_proto(*locations: tuple[tuple[int, ...], str]) -> descriptor_pb2.FileDescriptorProto:
    """Build a FileDescriptorProto carrying the given (path, leading_comments) Locations.

    Used by ``leading_comment`` tests to exercise normalization paths
    without depending on a real backend's source_code_info emission.
    """
    fd_proto = descriptor_pb2.FileDescriptorProto(name="demo.proto")
    for path, comment in locations:
        loc = fd_proto.source_code_info.location.add()
        loc.path.extend(path)
        loc.leading_comments = comment
    return fd_proto


# ---------------------------------------------------------------------------
# descriptor_path tests
# ---------------------------------------------------------------------------


class TestDescriptorPathTopLevelMessage:
    """``descriptor_path`` on a top-level message → ``(4, msg_index)``."""

    def test_top_level_message_path(self, tmp_path: Path) -> None:
        fd, _ = _build_pool(tmp_path)
        top = fd.message_types_by_name["TopMessage"]
        assert descriptor_path(top) == (4, 0)


class TestDescriptorPathNestedMessage:
    """``descriptor_path`` on a nested message → ``parent_path + (3, nested_index)``."""

    def test_nested_message_path(self, tmp_path: Path) -> None:
        fd, _ = _build_pool(tmp_path)
        top = fd.message_types_by_name["TopMessage"]
        nested = top.nested_types_by_name["Nested"]
        assert descriptor_path(nested) == (4, 0, 3, 0)


class TestDescriptorPathField:
    """``descriptor_path`` on a field → ``containing_msg_path + (2, field_index)``."""

    def test_field_in_top_level_message(self, tmp_path: Path) -> None:
        fd, _ = _build_pool(tmp_path)
        top = fd.message_types_by_name["TopMessage"]
        field = top.fields_by_name["top_field"]
        assert descriptor_path(field) == (4, 0, 2, 0)

    def test_field_in_nested_message(self, tmp_path: Path) -> None:
        fd, _ = _build_pool(tmp_path)
        top = fd.message_types_by_name["TopMessage"]
        nested = top.nested_types_by_name["Nested"]
        nested_field = nested.fields_by_name["nested_field"]
        # parent path is (4, 0, 3, 0); field is index 0 with tag 2 inside Nested.
        assert descriptor_path(nested_field) == (4, 0, 3, 0, 2, 0)


class TestDescriptorPathFileLevelEnum:
    """``descriptor_path`` on a file-level enum → ``(5, enum_index)``."""

    def test_file_level_enum_path(self, tmp_path: Path) -> None:
        fd, _ = _build_pool(tmp_path)
        top_enum = fd.enum_types_by_name["TopEnum"]
        assert descriptor_path(top_enum) == (5, 0)


class TestDescriptorPathNestedEnum:
    """``descriptor_path`` on a nested enum → ``parent_path + (4, enum_index)``."""

    def test_nested_enum_path(self, tmp_path: Path) -> None:
        fd, _ = _build_pool(tmp_path)
        top = fd.message_types_by_name["TopMessage"]
        nested_enum = top.enum_types_by_name["NestedEnum"]
        # The nested_type list comes first in DescriptorProto, but the
        # wire tag for enum_type inside a DescriptorProto is 4 (NOT 3,
        # which is nested_type / messages). The plan's K-5 table pins this.
        assert descriptor_path(nested_enum) == (4, 0, 4, 0)


class TestDescriptorPathEnumValue:
    """``descriptor_path`` on an enum value → ``enum_path + (2, value_index)``."""

    def test_value_in_file_level_enum(self, tmp_path: Path) -> None:
        fd, _ = _build_pool(tmp_path)
        top_enum = fd.enum_types_by_name["TopEnum"]
        default_value = top_enum.values_by_name["TOP_DEFAULT"]
        assert descriptor_path(default_value) == (5, 0, 2, 0)

    def test_value_in_nested_enum(self, tmp_path: Path) -> None:
        fd, _ = _build_pool(tmp_path)
        top = fd.message_types_by_name["TopMessage"]
        nested_enum = top.enum_types_by_name["NestedEnum"]
        default_value = nested_enum.values_by_name["NESTED_DEFAULT"]
        assert descriptor_path(default_value) == (4, 0, 4, 0, 2, 0)


class TestDescriptorPathMethod:
    """``descriptor_path`` on a method → ``(6, service_index, 2, method_index)``."""

    def test_method_path(self, tmp_path: Path) -> None:
        fd, _ = _build_pool(tmp_path)
        svc = fd.services_by_name["DemoService"]
        method = svc.methods_by_name["Echo"]
        assert descriptor_path(method) == (6, 0, 2, 0)


class TestDescriptorPathDeterminism:
    """Two consecutive calls on the same descriptor return identical paths."""

    def test_determinism_message(self, tmp_path: Path) -> None:
        fd, _ = _build_pool(tmp_path)
        top = fd.message_types_by_name["TopMessage"]
        path1 = descriptor_path(top)
        path2 = descriptor_path(top)
        assert path1 == path2

    def test_determinism_field(self, tmp_path: Path) -> None:
        fd, _ = _build_pool(tmp_path)
        top = fd.message_types_by_name["TopMessage"]
        field = top.fields_by_name["top_field"]
        assert descriptor_path(field) == descriptor_path(field)


class TestDescriptorPathRoundTripsAgainstBackend:
    """End-to-end pin: ``descriptor_path`` outputs match the backend's emitted Location paths.

    The strongest correctness signal — if the helper's tag-encoding diverges
    from the actual protobuf wire format, this test catches it (the lookup
    would silently return ``None`` for every R6 rule in U3).
    """

    def test_helper_paths_appear_in_real_source_code_info(
        self, tmp_path: Path
    ) -> None:
        fd, source_info_descriptors = _build_pool(tmp_path)
        fd_proto = source_info_descriptors["demo.proto"]
        emitted_paths = {tuple(loc.path) for loc in fd_proto.source_code_info.location}

        top = fd.message_types_by_name["TopMessage"]
        nested = top.nested_types_by_name["Nested"]
        nested_enum = top.enum_types_by_name["NestedEnum"]
        top_enum = fd.enum_types_by_name["TopEnum"]
        svc = fd.services_by_name["DemoService"]

        # Every helper output must correspond to a Location in the actual
        # source_code_info — otherwise leading_comment can never find it.
        assert descriptor_path(top) in emitted_paths
        assert descriptor_path(nested) in emitted_paths
        assert descriptor_path(nested_enum) in emitted_paths
        assert descriptor_path(top_enum) in emitted_paths
        assert descriptor_path(top.fields_by_name["top_field"]) in emitted_paths
        assert descriptor_path(nested.fields_by_name["nested_field"]) in emitted_paths
        assert descriptor_path(top_enum.values_by_name["TOP_DEFAULT"]) in emitted_paths
        assert descriptor_path(nested_enum.values_by_name["NESTED_DEFAULT"]) in emitted_paths
        assert descriptor_path(svc.methods_by_name["Echo"]) in emitted_paths


# ---------------------------------------------------------------------------
# leading_comment tests
# ---------------------------------------------------------------------------


class TestLeadingCommentHappyPath:
    """``leading_comment`` returns the stripped string for a matching Location."""

    def test_real_source_info_returns_comment(self, tmp_path: Path) -> None:
        fd, source_info_descriptors = _build_pool(tmp_path)
        top = fd.message_types_by_name["TopMessage"]
        path = descriptor_path(top)
        comment = leading_comment(source_info_descriptors, "demo.proto", path)
        assert comment is not None
        # The fixture comment text is preserved (whitespace stripped).
        assert "Leading comment on TopMessage" in comment
        assert "Use TopMessageV2 instead" in comment

    def test_manual_fd_proto_returns_comment(self) -> None:
        fd_proto = _make_fd_proto(((4, 0, 2, 0), "Use the new replacement field."))
        sl = {"demo.proto": fd_proto}
        comment = leading_comment(sl, "demo.proto", (4, 0, 2, 0))
        assert comment == "Use the new replacement field."


class TestLeadingCommentDefensiveNoneHandling:
    """``leading_comment(None, ...)`` returns ``None`` without raising."""

    def test_none_mapping_returns_none(self) -> None:
        assert leading_comment(None, "demo.proto", (4, 0, 2, 0)) is None


class TestLeadingCommentKeyMiss:
    """File name not in the mapping → ``None``."""

    def test_missing_file_returns_none(self) -> None:
        fd_proto = _make_fd_proto(((4, 0, 2, 0), "comment"))
        sl = {"other.proto": fd_proto}
        assert leading_comment(sl, "demo.proto", (4, 0, 2, 0)) is None


class TestLeadingCommentPathMiss:
    """No Location's path matches → ``None``."""

    def test_path_with_no_match_returns_none(self) -> None:
        fd_proto = _make_fd_proto(((4, 0, 2, 0), "comment"))
        sl = {"demo.proto": fd_proto}
        # 99,99 is intentionally absurd — no Location can match.
        assert leading_comment(sl, "demo.proto", (99, 99)) is None


class TestLeadingCommentNormalization:
    """``.strip()`` then ``or None`` — empty/whitespace → None; content preserved."""

    def test_empty_leading_comments_returns_none(self) -> None:
        fd_proto = _make_fd_proto(((4, 0, 2, 0), ""))
        sl = {"demo.proto": fd_proto}
        assert leading_comment(sl, "demo.proto", (4, 0, 2, 0)) is None

    def test_whitespace_only_comment_returns_none(self) -> None:
        fd_proto = _make_fd_proto(((4, 0, 2, 0), "   \n  \t  "))
        sl = {"demo.proto": fd_proto}
        assert leading_comment(sl, "demo.proto", (4, 0, 2, 0)) is None

    def test_leading_trailing_whitespace_stripped(self) -> None:
        fd_proto = _make_fd_proto(((4, 0, 2, 0), "   Use UserV2 instead   "))
        sl = {"demo.proto": fd_proto}
        assert leading_comment(sl, "demo.proto", (4, 0, 2, 0)) == "Use UserV2 instead"

    def test_internal_whitespace_preserved(self) -> None:
        # Leading/trailing whitespace stripped; internal newlines + indentation preserved.
        fd_proto = _make_fd_proto(((4, 0, 2, 0), "   Line 1.\n   Line 2.   "))
        sl = {"demo.proto": fd_proto}
        assert leading_comment(sl, "demo.proto", (4, 0, 2, 0)) == "Line 1.\n   Line 2."


class TestLeadingCommentControlCharsPassThrough:
    """``.strip()`` only removes whitespace — control chars survive verbatim.

    Sanitization is the caller's responsibility (U3 rules forward through the
    existing ``_safe_for_stderr`` sanitizer at finding-construction time).
    Pinning this contract here ensures helper authors don't accidentally add
    sanitization that would interfere with the dual-sanitization model.
    """

    def test_control_chars_passed_through(self) -> None:
        # \x1b (ESC) is not whitespace; .strip() leaves it untouched.
        fd_proto = _make_fd_proto(((4, 0, 2, 0), "alpha\x1bbeta"))
        sl = {"demo.proto": fd_proto}
        assert leading_comment(sl, "demo.proto", (4, 0, 2, 0)) == "alpha\x1bbeta"

    def test_line_separator_passed_through(self) -> None:
        # U+2028 (LINE SEPARATOR) — JSON would NOT escape this; the
        # helper preserves it so callers can sanitize at output time.
        fd_proto = _make_fd_proto(((4, 0, 2, 0), "alpha beta"))
        sl = {"demo.proto": fd_proto}
        assert leading_comment(sl, "demo.proto", (4, 0, 2, 0)) == "alpha beta"


class TestLeadingCommentTypeContract:
    """``path`` accepted as any iterable yielding ints (list or tuple)."""

    def test_list_and_tuple_arguments_return_same_result(self) -> None:
        fd_proto = _make_fd_proto(((4, 0, 2, 0), "comment"))
        sl = {"demo.proto": fd_proto}
        # Both should match the same Location.
        list_result = leading_comment(sl, "demo.proto", [4, 0, 2, 0])  # type: ignore[arg-type]
        tuple_result = leading_comment(sl, "demo.proto", (4, 0, 2, 0))
        assert list_result == tuple_result == "comment"


class TestLeadingCommentDeterminism:
    """Two consecutive calls with identical inputs return identical results."""

    def test_determinism(self) -> None:
        fd_proto = _make_fd_proto(((4, 0, 2, 0), "comment"))
        sl = {"demo.proto": fd_proto}
        first = leading_comment(sl, "demo.proto", (4, 0, 2, 0))
        second = leading_comment(sl, "demo.proto", (4, 0, 2, 0))
        assert first == second


class TestLeadingCommentMultipleLocationsPicksMatching:
    """When the mapping has multiple Locations, only the matching one is returned."""

    def test_picks_correct_location_among_many(self) -> None:
        fd_proto = _make_fd_proto(
            ((4, 0), "TopMessage comment"),
            ((4, 0, 2, 0), "top_field comment"),
            ((4, 0, 2, 1), "second field comment"),
            ((5, 0), "TopEnum comment"),
        )
        sl = {"demo.proto": fd_proto}
        assert (
            leading_comment(sl, "demo.proto", (4, 0)) == "TopMessage comment"
        )
        assert (
            leading_comment(sl, "demo.proto", (4, 0, 2, 0)) == "top_field comment"
        )
        assert (
            leading_comment(sl, "demo.proto", (5, 0)) == "TopEnum comment"
        )
