"""Tests for ``protokit.storage._where.compile_where`` — the ``--where`` compiler.

Coverage is driven by a single rich ``.proto`` compiled once (via the U2
``ProtoFileSchema``) so every field kind the grammar must handle — implicit and
explicit-presence scalars, enums, bytes, nested messages, repeated, map, oneof —
is a real descriptor, not a hand-built stub. Fault paths assert the typed
``WhereError`` and its message; the bool/HasField traps and the unset-traversal
semantics are pinned explicitly.
"""

from __future__ import annotations

import pytest

from protokit.storage._where import WhereError, compile_where
from protokit.storage.schema_source import ProtoFileSchema

_EVENT_PROTO = """\
syntax = "proto3";
package demo;

enum Color { RED = 0; GREEN = 1; BLUE = 2; }

message Header { int32 code = 1; }

message Event {
  int32 n = 1;
  double ratio = 2;
  bool flag = 3;
  string name = 4;
  bytes blob = 5;
  Color color = 6;
  Header header = 7;
  optional int32 opt = 8;
  repeated int32 tags = 9;
  map<string, int32> labels = 10;
  oneof choice { int32 a = 11; string b = 12; }
}
"""

_PROTO2 = """\
syntax = "proto2";
package demo2;
message Rec { optional int32 v = 1; }
"""


@pytest.fixture(scope="module")
def event_cls(tmp_path_factory: pytest.TempPathFactory) -> type:
    d = tmp_path_factory.mktemp("where")
    p = d / "event.proto"
    p.write_text(_EVENT_PROTO)
    return ProtoFileSchema(p, "demo.Event").resolve().message_class


@pytest.fixture(scope="module")
def rec2_cls(tmp_path_factory: pytest.TempPathFactory) -> type:
    d = tmp_path_factory.mktemp("where2")
    p = d / "rec.proto"
    p.write_text(_PROTO2)
    return ProtoFileSchema(p, "demo2.Rec").resolve().message_class


def _pred(expr: str, cls: type):  # noqa: ANN202 - returns Callable[[Message], bool]
    return compile_where(expr, cls.DESCRIPTOR)


class TestComparisonHappy:
    def test_int_equality(self, event_cls: type) -> None:
        pred = _pred("n == 7", event_cls)
        assert pred(event_cls(n=7)) is True
        assert pred(event_cls(n=8)) is False

    def test_inequality_is_negation_of_equality(self, event_cls: type) -> None:
        eq = _pred("n == 7", event_cls)
        ne = _pred("n != 7", event_cls)
        for value in (7, 8, 0):
            msg = event_cls(n=value)
            assert ne(msg) is (not eq(msg))

    def test_nested_path(self, event_cls: type) -> None:
        pred = _pred("header.code == 5", event_cls)
        assert pred(event_cls(header={"code": 5})) is True
        assert pred(event_cls(header={"code": 6})) is False

    def test_float(self, event_cls: type) -> None:
        assert _pred("ratio == 1.5", event_cls)(event_cls(ratio=1.5)) is True

    def test_string_plain_and_quoted_with_spaces_and_operator(
        self, event_cls: type
    ) -> None:
        assert _pred('name == "hi"', event_cls)(event_cls(name="hi")) is True
        assert _pred('name == "a b"', event_cls)(event_cls(name="a b")) is True
        # A quoted literal may contain the operator itself (first-op split +
        # quote-aware RHS).
        assert _pred('name == "a == b"', event_cls)(event_cls(name="a == b")) is True
        # Unquoted string value also works.
        assert _pred("name == hi", event_cls)(event_cls(name="hi")) is True

    def test_bytes(self, event_cls: type) -> None:
        assert _pred('blob == "abc"', event_cls)(event_cls(blob=b"abc")) is True


class TestBoolTrap:
    def test_false_literal_is_not_python_bool_of_string(self, event_cls: type) -> None:
        # bool("false") is True; if the compiler used it, this would be True.
        pred = _pred("flag == false", event_cls)
        assert pred(event_cls(flag=True)) is False
        assert pred(event_cls(flag=False)) is True

    def test_true_literal(self, event_cls: type) -> None:
        pred = _pred("flag == true", event_cls)
        assert pred(event_cls(flag=True)) is True

    def test_bad_bool_spelling_is_error(self, event_cls: type) -> None:
        with pytest.raises(WhereError, match="bool"):
            _pred("flag == maybe", event_cls)


class TestEnum:
    def test_by_name_and_number_agree(self, event_cls: type) -> None:
        by_name = _pred("color == BLUE", event_cls)
        by_number = _pred("color == 2", event_cls)
        msg = event_cls(color=2)
        assert by_name(msg) is True and by_number(msg) is True

    def test_unknown_name_lists_valid(self, event_cls: type) -> None:
        with pytest.raises(WhereError, match="PURPLE.*valid"):
            _pred("color == PURPLE", event_cls)

    def test_open_enum_unnamed_number_matches(self, event_cls: type) -> None:
        # proto3 open enums carry numbers without a declared name.
        msg = event_cls()
        msg.color = 99
        assert _pred("color == 99", event_cls)(msg) is True
        assert _pred("color == BLUE", event_cls)(msg) is False


class TestPresence:
    def test_message_field_presence(self, event_cls: type) -> None:
        pred = _pred("has:header", event_cls)
        assert pred(event_cls(header={"code": 1})) is True
        assert pred(event_cls()) is False

    def test_optional_scalar_presence(self, event_cls: type) -> None:
        pred = _pred("has:opt", event_cls)
        assert pred(event_cls(opt=0)) is True  # set-to-default still "present"
        assert pred(event_cls()) is False

    def test_proto2_singular_scalar_has_presence(self, rec2_cls: type) -> None:
        pred = _pred("has:v", rec2_cls)
        assert pred(rec2_cls(v=0)) is True
        assert pred(rec2_cls()) is False

    def test_implicit_scalar_presence_is_compile_error(self, event_cls: type) -> None:
        with pytest.raises(WhereError, match="no presence"):
            _pred("has:n", event_cls)

    @pytest.mark.parametrize("field", ["tags", "labels"])
    def test_repeated_and_map_presence_is_error(
        self, event_cls: type, field: str
    ) -> None:
        with pytest.raises(WhereError, match="no presence"):
            _pred(f"has:{field}", event_cls)


class TestKindRejection:
    def test_repeated_terminal_rejected(self, event_cls: type) -> None:
        with pytest.raises(WhereError, match="repeated"):
            _pred("tags == 1", event_cls)

    def test_map_terminal_rejected(self, event_cls: type) -> None:
        with pytest.raises(WhereError, match="map"):
            _pred("labels == 1", event_cls)

    def test_message_terminal_rejected(self, event_cls: type) -> None:
        with pytest.raises(WhereError, match="message field"):
            _pred("header == 1", event_cls)

    def test_oneof_name_is_not_a_field(self, event_cls: type) -> None:
        # The oneof *name* is not a field; its members (a/b) are.
        with pytest.raises(WhereError, match="no field 'choice'"):
            _pred("choice == 1", event_cls)

    def test_descend_into_scalar_rejected(self, event_cls: type) -> None:
        with pytest.raises(WhereError, match="descend into scalar"):
            _pred("n.sub == 1", event_cls)


class TestRicherRejected:
    @pytest.mark.parametrize(
        "expr",
        [
            "n == 1 and flag == true",
            "n == 1 or n == 2",
            "n > 0",
            "n < 5",
            "f(n) == 1",
            "n == 1 == 2",
        ],
    )
    def test_richer_expressions_point_at_python_api(
        self, event_cls: type, expr: str
    ) -> None:
        with pytest.raises(WhereError) as exc:
            _pred(expr, event_cls)
        assert "Python callable API" in str(exc.value)


class TestParsingEdges:
    def test_unknown_field_lists_available(self, event_cls: type) -> None:
        with pytest.raises(WhereError, match="no field 'nope'.*available"):
            _pred("nope == 1", event_cls)

    def test_missing_value_after_operator(self, event_cls: type) -> None:
        with pytest.raises(WhereError, match="missing value"):
            _pred("name ==", event_cls)

    def test_empty_string_literal_is_valid(self, event_cls: type) -> None:
        pred = _pred('name == ""', event_cls)
        assert pred(event_cls(name="")) is True
        assert pred(event_cls(name="x")) is False

    def test_unterminated_quote(self, event_cls: type) -> None:
        with pytest.raises(WhereError, match="unterminated"):
            _pred('name == "x', event_cls)

    def test_bare_path_without_operator_or_presence(self, event_cls: type) -> None:
        with pytest.raises(WhereError, match="expected"):
            _pred("header", event_cls)

    def test_empty_expression(self, event_cls: type) -> None:
        with pytest.raises(WhereError, match="empty"):
            _pred("   ", event_cls)


class TestUnsetTraversalSemantics:
    def test_unset_intermediate_message_traverses_to_default(
        self, event_cls: type
    ) -> None:
        # header is unset -> header.code reads the default 0 -> the record
        # "matches" header.code == 0. Documented protobuf semantics.
        assert _pred("header.code == 0", event_cls)(event_cls()) is True

    def test_unset_scalar_compares_against_default_under_ne(
        self, event_cls: type
    ) -> None:
        # name unset -> default "" -> name != "x" is True.
        assert _pred('name != "x"', event_cls)(event_cls()) is True
