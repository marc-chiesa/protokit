"""The records seam: what a frozen record's collection field accepts (U6).

``tests/meta/test_frozen_records.py`` proves every public record *uses* the
seam; this file pins what the seam itself does, so that guard's checks rest on
a contract rather than on whichever helper a record happens to call.
"""

from __future__ import annotations

from collections import OrderedDict
from types import MappingProxyType

import pytest

from protokit._records import (
    as_dict,
    as_frozenset,
    as_mapping,
    as_tuple,
    one_of,
    own_tuples,
    own_tuples_of_tuples,
)


class TestAsTuple:
    def test_a_tuple_is_returned_as_itself(self) -> None:
        value = (1, 2)
        assert as_tuple(value, "R.f") is value

    @pytest.mark.parametrize(
        "value",
        [[1, 2], (x for x in (1, 2)), range(1, 3), {1: None, 2: None}.keys()],
        ids=["list", "generator", "range", "keys-view"],
    )
    def test_any_other_iterable_is_copied_in_order(self, value: object) -> None:
        assert as_tuple(value, "R.f") == (1, 2)  # type: ignore[arg-type]

    def test_a_set_is_accepted(self) -> None:
        assert sorted(as_tuple({2, 1}, "R.f")) == [1, 2]

    def test_a_tuple_subclass_becomes_a_plain_tuple(self) -> None:
        class Pair(tuple):  # type: ignore[type-arg]
            pass

        assert type(as_tuple(Pair((1, 2)), "R.f")) is tuple

    @pytest.mark.parametrize(
        ("value", "pieces"),
        [
            ("abc", "characters"),
            (b"abc", "integers"),
            (bytearray(b"abc"), "integers"),
            ({"a": 1}, "its keys"),
            (MappingProxyType({"a": 1}), "its keys"),
            (OrderedDict(a=1), "its keys"),
        ],
        ids=["str", "bytes", "bytearray", "dict", "mappingproxy", "ordereddict"],
    )
    def test_inputs_iteration_would_take_apart_are_refused(
        self, value: object, pieces: str,
    ) -> None:
        with pytest.raises(TypeError, match=rf"R\.f .*split it into {pieces}"):
            as_tuple(value, "R.f")  # type: ignore[arg-type]

    def test_a_non_iterable_is_refused_with_the_field_name(self) -> None:
        with pytest.raises(TypeError, match=r"R\.f must be a collection of items, not a int"):
            as_tuple(5, "R.f")  # type: ignore[arg-type]

    def test_a_type_error_raised_while_iterating_is_not_relabelled(self) -> None:
        def broken() -> object:
            yield 1
            raise TypeError("from the generator")

        with pytest.raises(TypeError, match="from the generator"):
            as_tuple(broken(), "R.f")  # type: ignore[arg-type]


class TestAsFrozenset:
    def test_a_frozenset_is_returned_as_itself(self) -> None:
        value = frozenset({1})
        assert as_frozenset(value, "R.f") is value

    def test_a_set_is_copied(self) -> None:
        source = {1}
        result = as_frozenset(source, "R.f")
        source.add(2)
        assert result == frozenset({1})

    def test_a_string_is_refused(self) -> None:
        with pytest.raises(TypeError, match=r"R\.f"):
            as_frozenset("ab", "R.f")


class TestAsMapping:
    def test_a_dict_is_copied_into_a_read_only_view(self) -> None:
        source = {"a": 1}
        result = as_mapping(source, "R.f")
        source["b"] = 2
        assert dict(result) == {"a": 1}
        with pytest.raises(TypeError):
            result["c"] = 3  # type: ignore[index]

    def test_a_mapping_proxy_passes_through_uncopied(self) -> None:
        # The lint engine builds one context per element per rule from the
        # same proxies; copying them there would be quadratic.
        proxy = MappingProxyType({"a": 1})
        assert as_mapping(proxy, "R.f") is proxy

    def test_an_object_with_keys_is_accepted_like_dict_accepts_it(self) -> None:
        class Quacks:
            def keys(self) -> list[str]:
                return ["a"]

            def __getitem__(self, key: str) -> int:
                return 1

        assert dict(as_mapping(Quacks(), "R.f")) == {"a": 1}  # type: ignore[arg-type]

    @pytest.mark.parametrize("value", [[("a", 1)], "ab", 5])
    def test_a_non_mapping_is_refused(self, value: object) -> None:
        with pytest.raises(TypeError, match=r"R\.f must be a mapping"):
            as_mapping(value, "R.f")  # type: ignore[arg-type]


class TestOneOf:
    def test_a_member_is_returned(self) -> None:
        assert one_of("error", frozenset({"error"}), "R.level") == "error"

    def test_a_non_member_is_refused_naming_the_allowed_values(self) -> None:
        expected = r"R\.level must be one of \['error', 'info'\], got 'fatal'"
        with pytest.raises(ValueError, match=expected):
            one_of("fatal", frozenset({"error", "info"}), "R.level")


class TestOwnTuples:
    def test_names_the_record_type_in_the_error(self) -> None:
        class Record:
            items = "ab"

        with pytest.raises(TypeError, match=r"Record\.items"):
            own_tuples(Record(), "items")


class TestAsDict:
    def test_a_dict_is_copied_and_stays_a_dict(self) -> None:
        source = {"a": 1}
        result = as_dict(source, "R.f")
        source["b"] = 2
        assert result == {"a": 1}
        assert type(result) is dict

    @pytest.mark.parametrize("value", [["ab"], [("a", 1)], "ab"])
    def test_what_dict_would_pair_up_is_refused(self, value: object) -> None:
        # dict(["ab"]) is {"a": "b"}: a list of pairs is not a mapping.
        with pytest.raises(TypeError, match=r"R\.f must be a mapping"):
            as_dict(value, "R.f")  # type: ignore[arg-type]


class TestOwnTuplesOfTuples:
    def test_each_element_is_owned_as_a_tuple(self) -> None:
        class Record:
            pairs: object = None

        pair = ["x", 1]
        record = Record()
        record.pairs = [pair]
        own_tuples_of_tuples(record, "pairs")
        pair[0] = "y"
        assert record.pairs == (("x", 1),)

    def test_a_string_element_is_refused_naming_the_position(self) -> None:
        class Record:
            pairs: object = ["ab"]

        with pytest.raises(TypeError, match=r"Record\.pairs\[\]"):
            own_tuples_of_tuples(Record(), "pairs")
