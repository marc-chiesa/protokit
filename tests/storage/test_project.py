"""Tests for ``protokit.storage._fields.project`` and the no-presence-fill shim (U2).

Companion to ``tests/storage/test_fields.py`` (which pins the U1 ``compile_fields``
validator). This module pins U2's render-time projection (KTD1:
render-dense-then-prune-the-dict) and the cross-version no-presence-fill kwarg
shim (KTD2).

Coverage is driven by a single rich ``.proto`` compiled once (via
``ProtoFileSchema``) whose submessages, ``map<string, Submessage>``,
repeated-submessage, and ``oneof``-submessage shapes each carry BOTH a nested
no-presence scalar and a nested presence-bearing field — so the recursive
correctness of the fill flag (the load-bearing KTD1 property) is exercised, not
just the top-level scalar shape.
"""

from __future__ import annotations

import inspect
import warnings

import pytest
from google.protobuf import json_format

from protokit.storage._fields import (
    NO_PRESENCE_FILL_KWARG,
    CompiledSelection,
    compile_fields,
    no_presence_kwarg,
    project,
)
from protokit.storage.schema_source import ProtoFileSchema

# ``Sub`` carries a no-presence scalar (``si``) AND a presence-bearing field
# (``sopt``), so projecting any ``Sub``-valued terminal (singular submessage,
# map value, repeated element, oneof submessage) exercises recursive fill.
_PROTO = """\
syntax = "proto3";
package demo;

enum Color { RED = 0; GREEN = 1; BLUE = 2; }

message Sub {
  int32 si = 1;
  optional int32 sopt = 2;
}

message Header {
  int32 code = 1;
  optional int32 hopt = 2;
}

message Event {
  int32 n = 1;
  optional int32 opt = 2;
  Color color = 3;
  bytes blob = 4;
  int64 big = 5;
  Header header = 6;
  repeated int32 tags = 7;
  map<string, int32> labels = 8;
  Sub singular_sub = 9;
  repeated Sub subs = 10;
  map<string, Sub> sub_map = 11;
  oneof choice {
    int32 a = 12;
    Sub sub_choice = 13;
  }
  string source = 14;
}
"""


@pytest.fixture(scope="module")
def event_cls() -> type:
    import tempfile
    from pathlib import Path

    d = Path(tempfile.mkdtemp(prefix="project_"))
    p = d / "event.proto"
    p.write_text(_PROTO)
    return ProtoFileSchema(p, "demo.Event").resolve().message_class


def _sel(spec: str, cls: type) -> CompiledSelection:
    return compile_fields(spec, cls.DESCRIPTOR)


# --- AE1: no-presence scalar at default under a present parent -------------


class TestNoPresenceShown:
    def test_implicit_scalar_at_default_is_shown(self, event_cls: type) -> None:
        # AE1: header set (present), header.code is a no-presence scalar at 0.
        m = event_cls()
        m.header.SetInParent()
        out = project(m, _sel("header.code", event_cls))
        assert out == {"header": {"code": 0}}

    def test_top_level_no_presence_scalar_at_default_is_shown(
        self, event_cls: type
    ) -> None:
        out = project(event_cls(), _sel("n", event_cls))
        assert out == {"n": 0}

    def test_unselected_fields_absent(self, event_cls: type) -> None:
        m = event_cls(n=7, source="x")
        out = project(m, _sel("n", event_cls))
        assert out == {"n": 7}

    def test_no_presence_non_default_value_renders(self, event_cls: type) -> None:
        m = event_cls(n=42)
        assert project(m, _sel("n", event_cls)) == {"n": 42}


# --- AE6: presence-bearing fields render by actual presence ----------------


class TestPresenceBearing:
    def test_unset_optional_scalar_is_omitted_not_zero(
        self, event_cls: type
    ) -> None:
        # opt is proto3 optional and unset -> absent (NOT {"opt": 0}).
        out = project(event_cls(), _sel("opt", event_cls))
        assert out == {}

    def test_set_optional_at_default_value_is_shown(self, event_cls: type) -> None:
        # Set to its default (0) -> presence is real, so it IS shown.
        m = event_cls()
        m.opt = 0
        out = project(m, _sel("opt", event_cls))
        assert out == {"opt": 0}

    def test_unset_oneof_member_is_omitted(self, event_cls: type) -> None:
        out = project(event_cls(), _sel("a", event_cls))
        assert out == {}

    def test_inactive_oneof_member_is_omitted(self, event_cls: type) -> None:
        # 'a' is selected but 'sub_choice' is the active case -> 'a' absent.
        m = event_cls()
        m.sub_choice.SetInParent()
        out = project(m, _sel("a", event_cls))
        assert out == {}

    def test_leaf_under_unset_submessage_is_omitted(self, event_cls: type) -> None:
        # header is unset -> header.code path contributes nothing; no {"header": {}}.
        out = project(event_cls(), _sel("header.code", event_cls))
        assert out == {}

    def test_unset_singular_submessage_terminal_is_omitted(
        self, event_cls: type
    ) -> None:
        out = project(event_cls(), _sel("singular_sub", event_cls))
        assert out == {}


# --- Non-scalar terminals: recursive fill correctness (KTD1) ---------------


class TestNonScalarTerminalsRecursiveFill:
    """Each terminal's subtree has a nested no-presence scalar (``si``) AND a
    nested presence-bearing field (``sopt``); assert the former fills and the
    latter is absent inside every container kind."""

    def test_singular_submessage_terminal(self, event_cls: type) -> None:
        m = event_cls()
        m.singular_sub.SetInParent()
        out = project(m, _sel("singular_sub", event_cls))
        assert out == {"singular_sub": {"si": 0}}

    def test_map_submessage_value_terminal(self, event_cls: type) -> None:
        m = event_cls()
        m.sub_map["k"].SetInParent()
        out = project(m, _sel("sub_map", event_cls))
        assert out == {"sub_map": {"k": {"si": 0}}}

    def test_repeated_submessage_terminal(self, event_cls: type) -> None:
        m = event_cls()
        m.subs.add()
        m.subs.add(si=3)
        out = project(m, _sel("subs", event_cls))
        assert out == {"subs": [{"si": 0}, {"si": 3}]}

    def test_oneof_submessage_terminal(self, event_cls: type) -> None:
        m = event_cls()
        m.sub_choice.SetInParent()
        out = project(m, _sel("sub_choice", event_cls))
        assert out == {"sub_choice": {"si": 0}}

    def test_nested_presence_bearing_set_inside_terminal_shows(
        self, event_cls: type
    ) -> None:
        # When the nested presence-bearing field IS set, it appears (and at its
        # default value), proving the omission above is presence-driven.
        m = event_cls()
        m.singular_sub.sopt = 0
        out = project(m, _sel("singular_sub", event_cls))
        assert out == {"singular_sub": {"si": 0, "sopt": 0}}


# --- Leaf type-mapping reused from proto ------------------------------------


class TestLeafTypeMapping:
    def test_enum_renders_as_name_string(self, event_cls: type) -> None:
        m = event_cls(color=2)  # BLUE
        assert project(m, _sel("color", event_cls)) == {"color": "BLUE"}

    def test_enum_default_renders_as_name(self, event_cls: type) -> None:
        assert project(event_cls(), _sel("color", event_cls)) == {"color": "RED"}

    def test_int64_renders_as_string(self, event_cls: type) -> None:
        m = event_cls(big=9_999_999_999)
        assert project(m, _sel("big", event_cls)) == {"big": "9999999999"}

    def test_bytes_renders_as_base64(self, event_cls: type) -> None:
        import base64

        raw = b"\x00\x01\xff"
        m = event_cls(blob=raw)
        out = project(m, _sel("blob", event_cls))
        assert out == {"blob": base64.b64encode(raw).decode("ascii")}


# --- Key casing + map keys --------------------------------------------------


class TestKeyCasing:
    def test_keys_are_snake_case(self, event_cls: type) -> None:
        # singular_sub stays snake_case (camelCase render would be 'singularSub').
        m = event_cls()
        m.singular_sub.SetInParent()
        out = project(m, _sel("singular_sub", event_cls))
        assert "singular_sub" in out
        assert "singularSub" not in out

    def test_map_key_camelcase_data_preserved_verbatim(
        self, event_cls: type
    ) -> None:
        # A map KEY is data, not a field name: a camelCase key is NOT re-cased.
        m = event_cls()
        m.labels["myCamelKey"] = 5
        out = project(m, _sel("labels", event_cls))
        assert out == {"labels": {"myCamelKey": 5}}


# --- Ordering / multiple paths / nesting ------------------------------------


class TestMultiplePaths:
    def test_multiple_paths_preserve_nesting(self, event_cls: type) -> None:
        m = event_cls(n=1, source="src")
        m.header.code = 5
        out = project(m, _sel("header.code, source, n", event_cls))
        assert out == {"header": {"code": 5}, "source": "src", "n": 1}

    def test_two_leaves_under_same_parent_share_one_dict(
        self, event_cls: type
    ) -> None:
        m = event_cls()
        m.header.code = 9
        m.header.hopt = 3
        out = project(m, _sel("header.code, header.hopt", event_cls))
        assert out == {"header": {"code": 9, "hopt": 3}}


# --- Shim: characterization (KTD2) ------------------------------------------


class TestNoPresenceFillShim:
    def test_exactly_one_kwarg_exposed_and_helper_selects_it(self) -> None:
        params = inspect.signature(json_format.MessageToDict).parameters
        new = "always_print_fields_with_no_presence"
        old = "including_default_value_fields"
        present = [k for k in (new, old) if k in params]
        # The pinned protobuf>=4.21,<6 range exposes exactly one of the two.
        assert len(present) == 1, present
        selected = present[0]
        assert no_presence_kwarg() == selected
        assert selected == NO_PRESENCE_FILL_KWARG

    def test_helper_prefers_new_name_when_available(self) -> None:
        params = inspect.signature(json_format.MessageToDict).parameters
        if "always_print_fields_with_no_presence" in params:
            assert no_presence_kwarg() == "always_print_fields_with_no_presence"

    def test_fill_behavior_top_level(self, event_cls: type) -> None:
        # The selected kwarg fills no-presence and omits presence-bearing.
        dense = json_format.MessageToDict(
            event_cls(),
            preserving_proto_field_name=True,
            **{NO_PRESENCE_FILL_KWARG: True},
        )
        assert dense["n"] == 0  # no-presence scalar filled
        assert dense["color"] == "RED"  # no-presence enum filled
        assert dense["tags"] == []  # repeated filled (empty)
        assert dense["labels"] == {}  # map filled (empty)
        assert "opt" not in dense  # presence-bearing omitted
        assert "header" not in dense  # unset submessage omitted
        assert "a" not in dense and "sub_choice" not in dense  # oneof omitted

    def test_fill_behavior_nested_submessage(self, event_cls: type) -> None:
        # Pin NESTED fill so a future in-range protobuf bump is caught.
        m = event_cls()
        m.singular_sub.SetInParent()
        m.subs.add()
        m.sub_map["k"].SetInParent()
        dense = json_format.MessageToDict(
            m,
            preserving_proto_field_name=True,
            **{NO_PRESENCE_FILL_KWARG: True},
        )
        # submessage: nested no-presence filled, nested presence-bearing absent.
        assert dense["singular_sub"] == {"si": 0}
        # repeated element: same rule recurses.
        assert dense["subs"] == [{"si": 0}]
        # map value: same rule recurses.
        assert dense["sub_map"] == {"k": {"si": 0}}


# --- No warnings emitted ----------------------------------------------------


class TestNoWarnings:
    def test_project_emits_no_warnings(self, event_cls: type) -> None:
        m = event_cls(n=1)
        m.header.code = 0
        m.singular_sub.SetInParent()
        m.sub_map["k"].SetInParent()
        m.subs.add()
        sel = _sel(
            "n, header.code, opt, singular_sub, sub_map, subs, color, big, blob",
            event_cls,
        )
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            project(m, sel)
        offenders = [
            w for w in caught
            if issubclass(w.category, (UserWarning, DeprecationWarning))
        ]
        assert offenders == [], [str(w.message) for w in offenders]
