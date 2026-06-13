"""Tests for FieldPath parsing, serialization, and filtering."""

import pytest

from protokit.message.model import FieldPath, PathSegment


class TestFieldPathParsing:
    """Test the unified path grammar parser."""

    def test_simple_name(self) -> None:
        fp = FieldPath.parse("name")
        assert len(fp.segments) == 1
        assert fp.segments[0] == PathSegment("name")

    def test_dotted_path(self) -> None:
        fp = FieldPath.parse("user.address.street")
        assert len(fp.segments) == 3
        assert str(fp) == "user.address.street"

    def test_repeated_index(self) -> None:
        fp = FieldPath.parse("items[2].name")
        assert len(fp.segments) == 2
        assert fp.segments[0] == PathSegment("items", "2")
        assert fp.segments[1] == PathSegment("name")
        assert str(fp) == "items[2].name"

    def test_native_map_string_key(self) -> None:
        fp = FieldPath.parse('labels["env"]')
        assert fp.segments[0] == PathSegment("labels", '"env"')
        assert str(fp) == 'labels["env"]'

    def test_native_map_int_key(self) -> None:
        fp = FieldPath.parse("scores[42]")
        assert fp.segments[0] == PathSegment("scores", "42")

    def test_native_map_negative_int_key(self) -> None:
        fp = FieldPath.parse("scores[-1]")
        assert fp.segments[0] == PathSegment("scores", "-1")

    def test_native_map_bool_key(self) -> None:
        fp = FieldPath.parse("flags[true]")
        assert fp.segments[0] == PathSegment("flags", "true")

    def test_treat_as_map_int_key(self) -> None:
        fp = FieldPath.parse("items[id=42].name")
        assert fp.segments[0] == PathSegment("items", "id=42")
        assert fp.segments[1] == PathSegment("name")

    def test_treat_as_map_string_key(self) -> None:
        fp = FieldPath.parse('items[id="a.b"].name')
        assert fp.segments[0] == PathSegment("items", 'id="a.b"')

    def test_treat_as_map_enum_key(self) -> None:
        fp = FieldPath.parse('items[status="ACTIVE"].name')
        assert fp.segments[0] == PathSegment("items", 'status="ACTIVE"')

    def test_deep_nesting(self) -> None:
        fp = FieldPath.parse("a.b.c.d.e.f")
        assert len(fp.segments) == 6

    def test_empty_path(self) -> None:
        fp = FieldPath.parse("")
        assert len(fp.segments) == 0
        assert str(fp) == ""

    def test_special_chars_in_quoted_key(self) -> None:
        fp = FieldPath.parse('labels["x]y"]')
        assert fp.segments[0] == PathSegment("labels", '"x]y"')

    def test_escaped_quote_in_key(self) -> None:
        fp = FieldPath.parse('labels["a\\"b"]')
        assert fp.segments[0] == PathSegment("labels", '"a\\"b"')

    def test_underscore_name(self) -> None:
        fp = FieldPath.parse("_private.field_name")
        assert len(fp.segments) == 2


class TestFieldPathRoundTrip:
    """Test that parse -> str -> parse produces identical results."""

    @pytest.mark.parametrize(
        "path_str",
        [
            "name",
            "user.address.street",
            "items[2].name",
            'labels["env"]',
            "scores[42]",
            "flags[true]",
            "items[id=42].name",
            'items[id="a.b"].name',
            "scores[-1]",
        ],
    )
    def test_round_trip(self, path_str: str) -> None:
        fp = FieldPath.parse(path_str)
        assert str(fp) == path_str
        fp2 = FieldPath.parse(str(fp))
        assert fp == fp2


class TestFieldPathErrors:
    """Test error handling for malformed paths."""

    def test_leading_dot(self) -> None:
        with pytest.raises(ValueError):
            FieldPath.parse(".name")

    def test_trailing_dot(self) -> None:
        with pytest.raises(ValueError):
            FieldPath.parse("name.")

    def test_unclosed_bracket(self) -> None:
        with pytest.raises(ValueError):
            FieldPath.parse("items[2")

    def test_starts_with_number(self) -> None:
        with pytest.raises(ValueError):
            FieldPath.parse("123.name")


class TestFieldPathFiltering:
    """Test segment-aware prefix and exact matching."""

    def test_prefix_match_simple(self) -> None:
        filter_path = FieldPath.parse("user")
        target = FieldPath.parse("user.name")
        assert filter_path.is_prefix_of(target)

    def test_prefix_match_does_not_match_partial_name(self) -> None:
        """user should NOT match user2.name (different segment name)."""
        filter_path = FieldPath.parse("user")
        target = FieldPath.parse("user2.name")
        assert not filter_path.is_prefix_of(target)

    def test_prefix_match_without_bracket_matches_any_bracket(self) -> None:
        filter_path = FieldPath.parse("items")
        assert filter_path.is_prefix_of(FieldPath.parse("items[2].name"))
        assert filter_path.is_prefix_of(FieldPath.parse("items[id=42].name"))
        assert filter_path.is_prefix_of(FieldPath.parse("items"))

    def test_prefix_match_with_bracket_matches_specific(self) -> None:
        filter_path = FieldPath.parse("items[id=42]")
        assert filter_path.is_prefix_of(FieldPath.parse("items[id=42].name"))
        assert not filter_path.is_prefix_of(FieldPath.parse("items[id=99].name"))

    def test_exact_match(self) -> None:
        fp1 = FieldPath.parse("user.name")
        fp2 = FieldPath.parse("user.name")
        assert fp1.matches_exact(fp2)

    def test_exact_no_match_prefix(self) -> None:
        fp1 = FieldPath.parse("user")
        fp2 = FieldPath.parse("user.name")
        assert not fp1.matches_exact(fp2)

    def test_exact_bracketless_does_not_match_bracketed(self) -> None:
        fp1 = FieldPath.parse("items")
        fp2 = FieldPath.parse("items[2]")
        assert not fp1.matches_exact(fp2)

    def test_exact_with_bracket_matches(self) -> None:
        fp1 = FieldPath.parse("items[2]")
        fp2 = FieldPath.parse("items[2]")
        assert fp1.matches_exact(fp2)

    def test_self_is_prefix_of_self(self) -> None:
        fp = FieldPath.parse("user.name")
        assert fp.is_prefix_of(fp)

    def test_child_method(self) -> None:
        fp = FieldPath.parse("user")
        child = fp.child("name")
        assert str(child) == "user.name"

    def test_child_with_bracket(self) -> None:
        fp = FieldPath.parse("items")
        child = fp.child("items", bracket="2")
        assert str(child) == "items.items[2]"
