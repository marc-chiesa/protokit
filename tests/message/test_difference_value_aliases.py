"""Tests for the deprecated ``old_value``/``new_value`` read aliases.

The message-differ value pair was renamed ``old_value``/``new_value`` ->
``left_value``/``right_value`` (two arbitrary messages, neither privileged as
"old"). The old names survive as deprecated read-only ``@property`` aliases
that emit ``UserWarning`` and are removed in protokit 1.0. The JSON formatter
dual-emits both key pairs (canonical + deprecated) for one release and carries
a ``schema_version`` field. Constructing with the old kwargs is intentionally
no longer accepted.
"""

from __future__ import annotations

import json
import warnings
from typing import Any

import pytest
from google.protobuf.descriptor_pb2 import FieldDescriptorProto as F

from protokit.formatters import FormatterContext, FormatterKind, get_formatter
from protokit.message import ChangeType, Difference, DiffResult, diff_messages
from protokit.message.model import FieldPath
from protokit.message.pytest_plugin import pytest_assertrepr_compare
from tests.proto_builder import ProtoBuilder


def _modified_diff() -> tuple[DiffResult, Difference]:
    """A real MODIFIED diff: t.M(a='A') vs t.M(a='B')."""
    b = ProtoBuilder()
    b.message("t.M", {"a": (F.TYPE_STRING, 1)})
    cls = b.get_message_class("t.M")
    result = diff_messages(cls(a="A"), cls(a="B"))
    diffs = list(result)
    assert len(diffs) == 1 and diffs[0].change_type is ChangeType.MODIFIED
    return result, diffs[0]


def _added() -> Difference:
    """An ADDED diff: the right side has the value, the left is None."""
    return Difference(path=FieldPath.parse("x"), change_type=ChangeType.ADDED, right_value="v")


def _removed() -> Difference:
    """A REMOVED diff: the left side has the value, the right is None."""
    return Difference(path=FieldPath.parse("x"), change_type=ChangeType.REMOVED, left_value="v")


def _json(result: DiffResult) -> dict[str, Any]:
    """Render a DiffResult through the JSON formatter and parse the payload."""
    fn = get_formatter("json", FormatterKind.DIFF)
    return json.loads(fn(result, FormatterContext(subcommand="diff")))


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

    def test_aliases_on_added_and_removed_proxy_none(self) -> None:
        # ADDED: left_value is None (so old_value proxies None and warns).
        d_added = _added()
        with pytest.warns(UserWarning, match=r"old_value is deprecated"):
            assert d_added.old_value is None
        with pytest.warns(UserWarning, match=r"new_value is deprecated"):
            assert d_added.new_value == "v"
        # REMOVED: right_value is None (so new_value proxies None and warns).
        d_removed = _removed()
        with pytest.warns(UserWarning, match=r"new_value is deprecated"):
            assert d_removed.new_value is None
        with pytest.warns(UserWarning, match=r"old_value is deprecated"):
            assert d_removed.old_value == "v"

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
        with pytest.raises(AttributeError):
            d.new_value = "x"  # type: ignore[misc]


class TestConstruction:
    def test_old_kwargs_no_longer_accepted(self) -> None:
        # Construction via the old kwarg names is intentionally a hard break.
        # match= pins the error to the rejected-kwarg TypeError, not some other.
        with pytest.raises(TypeError, match="old_value"):
            Difference(path=FieldPath.parse("x"), change_type=ChangeType.REMOVED, old_value="v")  # type: ignore[call-arg]
        with pytest.raises(TypeError, match="new_value"):
            Difference(path=FieldPath.parse("x"), change_type=ChangeType.ADDED, new_value="v")  # type: ignore[call-arg]


class TestJsonDualEmit:
    def test_value_change_emits_both_key_pairs(self) -> None:
        result, _ = _modified_diff()
        entry = _json(result)["differences"][0]
        assert entry["left_value"] == entry["old_value"] == "A"
        assert entry["right_value"] == entry["new_value"] == "B"

    @pytest.mark.parametrize(
        ("change_type", "extra"),
        [
            (ChangeType.TYPE_CHANGED, {"left_type": "TYPE_INT32", "right_type": "TYPE_STRING"}),
            (ChangeType.FIELD_NUMBER_CHANGED, {"left_field_number": 1, "right_field_number": 2}),
            (ChangeType.CARDINALITY_CHANGED, {"left_label": "singular", "right_label": "repeated"}),
        ],
    )
    def test_schema_evolution_entry_has_all_four_value_keys_null(
        self, change_type: ChangeType, extra: dict[str, Any]
    ) -> None:
        # Every schema-evolution change type carries all four value keys, null.
        d = Difference(path=FieldPath.parse("f"), change_type=change_type, **extra)
        entry = _json(DiffResult(differences=(d,)))["differences"][0]
        for key in ("left_value", "right_value", "old_value", "new_value"):
            assert key in entry and entry[key] is None

    def test_output_carries_schema_version(self) -> None:
        result, _ = _modified_diff()
        assert _json(result)["schema_version"] == "0.1"


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

    def test_pytest_plugin_does_not_self_warn(self) -> None:
        # The assertrepr hook was migrated to the canonical fields; rendering it
        # must not trip the deprecation warning.
        b = ProtoBuilder()
        b.message("t.M", {"a": (F.TYPE_STRING, 1)})
        cls = b.get_message_class("t.M")
        with warnings.catch_warnings():
            warnings.simplefilter("error", UserWarning)
            out = pytest_assertrepr_compare(None, "==", cls(a="A"), cls(a="B"))
        assert out is not None and any(line.strip().startswith("~") for line in out)
