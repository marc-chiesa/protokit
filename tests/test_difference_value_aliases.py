"""Tests for the deprecated ``old_value``/``new_value`` read aliases.

The message-differ value pair was renamed ``old_value``/``new_value`` ->
``left_value``/``right_value`` (two arbitrary messages, neither privileged as
"old"). The old names survive as deprecated read-only ``@property`` aliases
that emit ``UserWarning`` and are removed in protokit 1.0. The JSON formatter
dual-emits both key pairs for one release.
"""

from __future__ import annotations

import json
import warnings

import pytest
from google.protobuf.descriptor_pb2 import FieldDescriptorProto as F

from protokit.formatters import FormatterContext, FormatterKind, get_formatter
from protokit.message import ChangeType, diff_messages
from tests.proto_builder import ProtoBuilder


def _modified_diff():
    """A real MODIFIED diff: t.M(a='A') vs t.M(a='B')."""
    b = ProtoBuilder()
    b.message("t.M", {"a": (F.TYPE_STRING, 1)})
    cls = b.get_message_class("t.M")
    result = diff_messages(cls(a="A"), cls(a="B"))
    diffs = list(result)
    assert len(diffs) == 1 and diffs[0].change_type is ChangeType.MODIFIED
    return result, diffs[0]


class TestValueAliases:
    def test_old_value_alias_reads_and_warns(self) -> None:
        _, d = _modified_diff()
        with pytest.warns(UserWarning, match=r"old_value is deprecated"):
            assert d.old_value == "A"
        with pytest.warns(UserWarning, match=r"new_value is deprecated"):
            assert d.new_value == "B"

    def test_alias_proxies_to_canonical(self) -> None:
        _, d = _modified_diff()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            assert d.old_value == d.left_value == "A"
            assert d.new_value == d.right_value == "B"

    def test_canonical_fields_do_not_warn(self) -> None:
        _, d = _modified_diff()
        with warnings.catch_warnings():
            warnings.simplefilter("error")  # any warning becomes an error
            assert d.left_value == "A"
            assert d.right_value == "B"

    def test_aliases_are_read_only(self) -> None:
        # Read-only properties on a frozen dataclass.
        _, d = _modified_diff()
        with pytest.raises(AttributeError):
            d.old_value = "x"  # type: ignore[misc]


class TestJsonDualEmit:
    def test_value_change_emits_both_key_pairs(self) -> None:
        result, _ = _modified_diff()
        fn = get_formatter("json", FormatterKind.DIFF)
        payload = json.loads(fn(result, FormatterContext(subcommand="diff")))
        entry = payload["differences"][0]
        assert entry["left_value"] == entry["old_value"] == "A"
        assert entry["right_value"] == entry["new_value"] == "B"


class TestFormattersDoNotSelfWarn:
    def test_builtin_formatters_read_canonical_fields(self) -> None:
        # If any formatter read the deprecated .old_value/.new_value property,
        # the UserWarning-as-error would surface here.
        result, _ = _modified_diff()
        with warnings.catch_warnings():
            warnings.simplefilter("error", UserWarning)
            for name in ("human", "json", "junit"):
                fn = get_formatter(name, FormatterKind.DIFF)
                fn(result, FormatterContext(subcommand="diff"))
