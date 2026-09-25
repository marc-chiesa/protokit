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


class TestParenthesisedExtensionSegment:
    """``(pkg.ext)`` is one segment: the path the differ emits must parse back.

    The differ reports a proto2 extension under its parenthesised
    fully-qualified name, and the CHANGELOG tells users to hand that exact
    string to ``--ignore``. A grammar that accepts only identifier segments
    emits a path it cannot read, so the documented mitigation raised.
    """

    def test_top_level_extension(self) -> None:
        fp = FieldPath.parse("(x.tag)")
        assert fp.segments == (PathSegment("(x.tag)"),)
        assert str(fp) == "(x.tag)"

    def test_nested_extension(self) -> None:
        fp = FieldPath.parse("inner.(x.tag)")
        assert fp.segments == (PathSegment("inner"), PathSegment("(x.tag)"))
        assert str(fp) == "inner.(x.tag)"

    def test_repeated_extension_index(self) -> None:
        fp = FieldPath.parse("(x.rep)[2]")
        assert fp.segments == (PathSegment("(x.rep)", "2"),)
        assert str(fp) == "(x.rep)[2]"

    def test_deeply_qualified_name(self) -> None:
        """An extension declared inside a message carries the message in its name."""
        fp = FieldPath.parse("(a.b.Msg.ext_nested).leaf")
        assert fp.segments == (PathSegment("(a.b.Msg.ext_nested)"), PathSegment("leaf"))

    def test_unqualified_name_is_still_a_valid_extension_segment(self) -> None:
        """A file with no package declares extensions with no dots at all."""
        assert FieldPath.parse("(ext)").segments == (PathSegment("(ext)"),)

    @pytest.mark.parametrize(
        "bad",
        ["()", "(a.)", "(.a)", "(a..b)", "(a", "(a)b", "a(b)", "(1a)", "(a-b)", "(a.b.)"],
    )
    def test_malformed_parenthesised_segment_is_rejected(self, bad: str) -> None:
        with pytest.raises(ValueError):
            FieldPath.parse(bad)

    def test_selector_matching_treats_the_segment_as_one_name(self) -> None:
        """Exact-length, name-equal: the same rule every other segment follows."""
        assert FieldPath.parse("inner.(x.tag)").matches_selector(FieldPath.parse("inner.(x.tag)"))
        assert not FieldPath.parse("(x.tag)").matches_selector(FieldPath.parse("inner.(x.tag)"))
        assert not FieldPath.parse("(x.tag)").matches_selector(FieldPath.parse("(x.rank)"))


class TestFieldPathFromAList:
    """Adjacent behavior to U6: the docstring's ``FieldPath([...])`` form.

    ``FieldPath.parse`` documents its result as ``FieldPath([PathSegment(...)])``,
    so a list must still build a path — now one that owns a tuple, compares
    and hashes like the tuple-built path, and does not follow the list.
    """

    def test_a_list_builds_the_same_path_as_a_tuple(self) -> None:
        segments = [PathSegment("user"), PathSegment("name")]
        from_list = FieldPath(segments)  # type: ignore[arg-type]
        segments.append(PathSegment("extra"))
        assert from_list == FieldPath.parse("user.name")
        assert hash(from_list) == hash(FieldPath.parse("user.name"))
        assert type(from_list.segments) is tuple

    def test_a_dotted_string_is_refused_rather_than_split(self) -> None:
        with pytest.raises(TypeError, match=r"FieldPath\.segments"):
            FieldPath("user.name")  # type: ignore[arg-type]
