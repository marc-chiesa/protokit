"""Tests for ``protokit.storage._fields.compile_fields`` — the ``--fields`` compiler.

Mirrors ``tests/storage/test_where.py``: coverage is driven by a single rich
``.proto`` compiled once (via ``ProtoFileSchema``) so every field kind the
selector must handle — an implicit (no-presence) scalar, a proto3 ``optional``
scalar, an enum, a ``bytes`` field, a nested singular submessage with its own
subfield, a repeated field, a ``map<string, X>``, and a ``oneof`` with two
members — is a real descriptor, not a hand-built stub.

The validating divergence from ``_where`` (any terminal kind is allowed) is
pinned by the happy cases (whole submessage / repeated / map / oneof-member
terminals), while the shared descent rules (no repeated/map/scalar
intermediates) and the typed, sorted-available-names error shape are pinned by
the reject cases.
"""

from __future__ import annotations

import pytest

from protokit.storage._fields import (
    CompiledSelection,
    FieldSelectionError,
    _walk_path,
    compile_fields,
)
from protokit.storage.schema_source import ProtoFileSchema
from protokit.storage.source import StorageError

_EVENT_PROTO = """\
syntax = "proto3";
package demo;

enum Color { RED = 0; GREEN = 1; BLUE = 2; }

message Header { int32 code = 1; }

message Event {
  int32 n = 1;
  optional int32 opt = 2;
  Color color = 3;
  bytes blob = 4;
  Header header = 5;
  repeated int32 tags = 6;
  map<string, int32> labels = 7;
  oneof choice { int32 a = 8; string b = 9; }
}
"""


@pytest.fixture(scope="module")
def event_cls(tmp_path_factory: pytest.TempPathFactory) -> type:
    d = tmp_path_factory.mktemp("fields")
    p = d / "event.proto"
    p.write_text(_EVENT_PROTO)
    return ProtoFileSchema(p, "demo.Event").resolve().message_class


def _sel(spec: str, cls: type) -> CompiledSelection:
    return compile_fields(spec, cls.DESCRIPTOR)


class TestHappy:
    def test_single_scalar(self, event_cls: type) -> None:
        assert _sel("n", event_cls).paths == (("n",),)

    def test_optional_scalar(self, event_cls: type) -> None:
        assert _sel("opt", event_cls).paths == (("opt",),)

    def test_enum(self, event_cls: type) -> None:
        assert _sel("color", event_cls).paths == (("color",),)

    def test_bytes(self, event_cls: type) -> None:
        assert _sel("blob", event_cls).paths == (("blob",),)

    def test_nested_subfield(self, event_cls: type) -> None:
        assert _sel("header.code", event_cls).paths == (("header", "code"),)

    def test_whole_singular_submessage_terminal(self, event_cls: type) -> None:
        # Divergence from _where: a singular-message terminal is a valid target.
        assert _sel("header", event_cls).paths == (("header",),)

    def test_whole_repeated_terminal(self, event_cls: type) -> None:
        # Divergence from _where: a repeated terminal is a valid target.
        assert _sel("tags", event_cls).paths == (("tags",),)

    def test_whole_map_terminal(self, event_cls: type) -> None:
        # Divergence from _where: a map terminal is a valid target.
        assert _sel("labels", event_cls).paths == (("labels",),)

    def test_oneof_member_terminal(self, event_cls: type) -> None:
        # A oneof *member* (not the oneof name) is a valid selection target.
        assert _sel("a", event_cls).paths == (("a",),)

    def test_multiple_comma_separated_paths_preserve_order(
        self, event_cls: type
    ) -> None:
        sel = _sel("header.code, n, labels", event_cls)
        assert sel.paths == (("header", "code"), ("n",), ("labels",))

    def test_whitespace_around_paths_is_trimmed(self, event_cls: type) -> None:
        assert _sel("  n ,  opt  ", event_cls).paths == (("n",), ("opt",))


class TestRejectDescent:
    def test_descend_into_repeated_rejected(self, event_cls: type) -> None:
        with pytest.raises(FieldSelectionError, match="repeated/map"):
            _sel("tags.x", event_cls)

    def test_descend_into_map_rejected(self, event_cls: type) -> None:
        with pytest.raises(FieldSelectionError, match="repeated/map"):
            _sel("labels.x", event_cls)

    def test_descend_into_scalar_rejected(self, event_cls: type) -> None:
        with pytest.raises(FieldSelectionError, match="descend into scalar"):
            _sel("n.x", event_cls)


class TestRejectNames:
    def test_unknown_field_lists_sorted_available(self, event_cls: type) -> None:
        with pytest.raises(FieldSelectionError) as exc:
            _sel("nope", event_cls)
        message = str(exc.value)
        assert "no field 'nope'" in message
        # The available names are listed sorted (the oneof members a/b are
        # fields; the oneof name 'choice' is not).
        expected = "a, b, blob, color, header, labels, n, opt, tags"
        assert expected in message

    def test_oneof_name_is_not_a_field(self, event_cls: type) -> None:
        with pytest.raises(FieldSelectionError, match="no field 'choice'"):
            _sel("choice", event_cls)


class TestRejectShape:
    def test_empty_spec(self, event_cls: type) -> None:
        with pytest.raises(FieldSelectionError, match="empty selection"):
            _sel("", event_cls)

    def test_whitespace_only_spec(self, event_cls: type) -> None:
        with pytest.raises(FieldSelectionError, match="empty selection"):
            _sel("   ", event_cls)

    def test_empty_path_trailing_comma(self, event_cls: type) -> None:
        with pytest.raises(FieldSelectionError, match="empty field path"):
            _sel("n,", event_cls)

    def test_empty_path_between_commas(self, event_cls: type) -> None:
        with pytest.raises(FieldSelectionError, match="empty field path"):
            _sel("a,,b", event_cls)

    def test_empty_segment(self, event_cls: type) -> None:
        with pytest.raises(FieldSelectionError, match="empty path segment"):
            _sel("header..code", event_cls)

    def test_non_identifier_segment(self, event_cls: type) -> None:
        with pytest.raises(FieldSelectionError, match="invalid field-path segment"):
            _sel("1bad", event_cls)


class TestErrorType:
    def test_is_storage_error_subclass(self) -> None:
        assert issubclass(FieldSelectionError, StorageError)

    def test_carries_spec_and_reason(self, event_cls: type) -> None:
        with pytest.raises(FieldSelectionError) as exc:
            _sel("nope", event_cls)
        assert exc.value.spec == "nope"
        assert "no field 'nope'" in exc.value.reason


class TestWalkPathInternalGuard:
    """``_walk_path`` refuses an empty path on its own, not just via its caller.

    ``compile_fields`` rejects an empty selection before it ever calls
    ``_walk_path``, so every existing "empty field path" test is satisfied
    upstream of this guard — a mutation audit replaced the raise with
    ``return []`` and the whole suite stayed green. The guard exists for an
    internal caller that bypasses the outer validator, and an empty field chain
    would project *nothing* rather than failing loudly, so it is worth pinning
    at the level it actually protects.
    """

    def test_empty_path_raises_rather_than_returning_no_fields(
        self, event_cls: type
    ) -> None:
        with pytest.raises(FieldSelectionError, match="empty field path"):
            _walk_path("", event_cls.DESCRIPTOR, spec="<internal>")

    def test_a_real_path_still_resolves(self, event_cls: type) -> None:
        """Guards against a fix that rejects everything."""
        chain = _walk_path("n", event_cls.DESCRIPTOR, spec="<internal>")
        assert [f.name for f in chain] == ["n"]
