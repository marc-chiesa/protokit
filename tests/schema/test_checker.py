"""End-to-end tests for SchemaChecker."""

from __future__ import annotations

import pytest
from google.protobuf import descriptor_pool

from protokit.message.model import FieldPath
from protokit.schema import (
    CompatibilityLevel,
    Direction,
    Finding,
    SchemaChecker,
    Severity,
    Verdict,
    check_compatibility,
)
from tests.proto_builder import ProtoBuilder
from tests.schema.helpers import T, build_enum, build_message


# ---------------------------------------------------------------------------
# Basic top-level traversal
# ---------------------------------------------------------------------------


class TestEmptyMessages:
    def test_no_findings_when_identical_empty(self) -> None:
        old = descriptor_pool.DescriptorPool()
        new = descriptor_pool.DescriptorPool()
        build_message(old, "t.M", fields=[])
        build_message(new, "t.M", fields=[])
        report = check_compatibility(old, "t.M", new, "t.M")
        assert report.is_compatible
        assert report.verdict is Verdict.COMPATIBLE
        assert report.findings == ()

    def test_no_findings_when_identical_simple(self) -> None:
        old = descriptor_pool.DescriptorPool()
        new = descriptor_pool.DescriptorPool()
        for p in (old, new):
            build_message(
                p, "t.M",
                fields=[
                    {"name": "a", "number": 1, "type": T.TYPE_INT32},
                    {"name": "b", "number": 2, "type": T.TYPE_STRING},
                ],
            )
        report = check_compatibility(old, "t.M", new, "t.M")
        assert report.is_compatible


class TestSimpleDifferences:
    def test_field_removed_at_root(self) -> None:
        old = descriptor_pool.DescriptorPool()
        new = descriptor_pool.DescriptorPool()
        build_message(old, "t.M", fields=[
            {"name": "x", "number": 1, "type": T.TYPE_INT32},
        ])
        build_message(new, "t.M", fields=[])
        report = check_compatibility(old, "t.M", new, "t.M")
        assert not report.is_compatible
        rule_ids = {f.rule_id for f in report.findings}
        assert "field_removed" in rule_ids

    def test_field_added_at_root(self) -> None:
        old = descriptor_pool.DescriptorPool()
        new = descriptor_pool.DescriptorPool()
        build_message(old, "t.M", fields=[])
        build_message(new, "t.M", fields=[
            {"name": "x", "number": 1, "type": T.TYPE_INT32},
        ])
        report = check_compatibility(old, "t.M", new, "t.M")
        rule_ids = {f.rule_id for f in report.findings}
        assert "field_added" in rule_ids

    def test_path_set_correctly_on_finding(self) -> None:
        old = descriptor_pool.DescriptorPool()
        new = descriptor_pool.DescriptorPool()
        build_message(old, "t.M", fields=[
            {"name": "x", "number": 1, "type": T.TYPE_INT32},
        ])
        build_message(new, "t.M", fields=[])
        report = check_compatibility(old, "t.M", new, "t.M")
        f = next(f for f in report.findings if f.rule_id == "field_removed")
        assert f.path == FieldPath.parse("x")


# ---------------------------------------------------------------------------
# Recursion into nested messages
# ---------------------------------------------------------------------------


class TestNestedMessages:
    def _build_pair(
        self, *, old_inner_field: str | None, new_inner_field: str | None,
    ) -> tuple[descriptor_pool.DescriptorPool, descriptor_pool.DescriptorPool]:
        old = descriptor_pool.DescriptorPool()
        new = descriptor_pool.DescriptorPool()
        # Inner messages
        old_inner_fields = []
        if old_inner_field:
            old_inner_fields.append(
                {"name": old_inner_field, "number": 1, "type": T.TYPE_STRING}
            )
        new_inner_fields = []
        if new_inner_field:
            new_inner_fields.append(
                {"name": new_inner_field, "number": 1, "type": T.TYPE_STRING}
            )
        build_message(old, "t.Inner", fields=old_inner_fields)
        build_message(new, "t.Inner", fields=new_inner_fields)
        # Outer messages reference inner
        build_message(old, "t.Outer", fields=[
            {"name": "inner", "number": 1, "type": T.TYPE_MESSAGE, "type_name": "t.Inner"},
        ])
        build_message(new, "t.Outer", fields=[
            {"name": "inner", "number": 1, "type": T.TYPE_MESSAGE, "type_name": "t.Inner"},
        ])
        return old, new

    def test_field_change_in_nested_message(self) -> None:
        old, new = self._build_pair(
            old_inner_field="foo", new_inner_field=None,
        )
        report = check_compatibility(old, "t.Outer", new, "t.Outer")
        f = next(f for f in report.findings if f.rule_id == "field_removed")
        assert f.path == FieldPath.parse("inner.foo")

    def test_field_added_in_nested_message(self) -> None:
        old, new = self._build_pair(
            old_inner_field=None, new_inner_field="bar",
        )
        report = check_compatibility(old, "t.Outer", new, "t.Outer")
        f = next(f for f in report.findings if f.rule_id == "field_added")
        assert f.path == FieldPath.parse("inner.bar")

    def test_two_levels_deep(self) -> None:
        old = descriptor_pool.DescriptorPool()
        new = descriptor_pool.DescriptorPool()
        build_message(old, "t.A", fields=[
            {"name": "x", "number": 1, "type": T.TYPE_INT32},
        ])
        build_message(new, "t.A", fields=[])
        build_message(old, "t.B", fields=[
            {"name": "a", "number": 1, "type": T.TYPE_MESSAGE, "type_name": "t.A"},
        ])
        build_message(new, "t.B", fields=[
            {"name": "a", "number": 1, "type": T.TYPE_MESSAGE, "type_name": "t.A"},
        ])
        build_message(old, "t.C", fields=[
            {"name": "b", "number": 1, "type": T.TYPE_MESSAGE, "type_name": "t.B"},
        ])
        build_message(new, "t.C", fields=[
            {"name": "b", "number": 1, "type": T.TYPE_MESSAGE, "type_name": "t.B"},
        ])
        report = check_compatibility(old, "t.C", new, "t.C")
        f = next(f for f in report.findings if f.rule_id == "field_removed")
        assert f.path == FieldPath.parse("b.a.x")


# ---------------------------------------------------------------------------
# Cycle handling
# ---------------------------------------------------------------------------


class TestCycles:
    def _build_self_referential(
        self, pool: descriptor_pool.DescriptorPool, *, with_extra_field: bool = False,
    ) -> None:
        """Build TreeNode with a repeated TreeNode children field."""
        fields = [
            {"name": "value", "number": 1, "type": T.TYPE_STRING},
            {
                "name": "children", "number": 2, "type": T.TYPE_MESSAGE,
                "type_name": "t.TreeNode", "label": T.LABEL_REPEATED,
            },
        ]
        if with_extra_field:
            fields.append({"name": "tag", "number": 3, "type": T.TYPE_INT32})
        build_message(pool, "t.TreeNode", fields=fields)

    def test_self_reference_does_not_loop(self) -> None:
        old = descriptor_pool.DescriptorPool()
        new = descriptor_pool.DescriptorPool()
        self._build_self_referential(old)
        self._build_self_referential(new)
        report = check_compatibility(old, "t.TreeNode", new, "t.TreeNode")
        assert report.is_compatible

    def test_self_reference_findings_emitted_once(self) -> None:
        old = descriptor_pool.DescriptorPool()
        new = descriptor_pool.DescriptorPool()
        self._build_self_referential(old, with_extra_field=False)
        self._build_self_referential(new, with_extra_field=True)
        report = check_compatibility(old, "t.TreeNode", new, "t.TreeNode")
        added = [f for f in report.findings if f.rule_id == "field_added"]
        assert len(added) == 1
        assert added[0].path == FieldPath.parse("tag")

    def test_shared_nested_type_findings_appear_at_every_path(self) -> None:
        """Two different fields referencing the same shared nested
        type both receive findings (path-complete default).
        """
        old = descriptor_pool.DescriptorPool()
        new = descriptor_pool.DescriptorPool()
        build_message(old, "t.Shared", fields=[
            {"name": "secret", "number": 1, "type": T.TYPE_STRING},
        ])
        build_message(new, "t.Shared", fields=[])  # secret removed
        for p, label in ((old, "old"), (new, "new")):
            build_message(p, "t.Outer", fields=[
                {"name": "a", "number": 1, "type": T.TYPE_MESSAGE,
                 "type_name": "t.Shared"},
                {"name": "b", "number": 2, "type": T.TYPE_MESSAGE,
                 "type_name": "t.Shared"},
            ], file_name=f"outer_{label}.proto")

        report = check_compatibility(old, "t.Outer", new, "t.Outer")
        removed = [f for f in report.findings if f.rule_id == "field_removed"]
        # Both paths must report the removal so ignoring one doesn't
        # hide the other.
        paths = sorted(str(f.path) for f in removed)
        assert paths == ["a.secret", "b.secret"]

    def test_shared_nested_type_dedupe_opt_in(self) -> None:
        """``dedupe_by_type=True`` preserves the original behavior:
        findings for a shared type appear only at the first path.
        """
        old = descriptor_pool.DescriptorPool()
        new = descriptor_pool.DescriptorPool()
        build_message(old, "t.Shared", fields=[
            {"name": "secret", "number": 1, "type": T.TYPE_STRING},
        ])
        build_message(new, "t.Shared", fields=[])
        for p, label in ((old, "old"), (new, "new")):
            build_message(p, "t.Outer", fields=[
                {"name": "a", "number": 1, "type": T.TYPE_MESSAGE,
                 "type_name": "t.Shared"},
                {"name": "b", "number": 2, "type": T.TYPE_MESSAGE,
                 "type_name": "t.Shared"},
            ], file_name=f"outer_dedupe_{label}.proto")

        checker = SchemaChecker(dedupe_by_type=True)
        report = checker.check(old, "t.Outer", new, "t.Outer")
        removed = [f for f in report.findings if f.rule_id == "field_removed"]
        # Only the first-encountered path surfaces; the other is
        # suppressed by the visited set.
        assert len(removed) == 1

    def test_mutual_recursion(self) -> None:
        # A.b -> B; B.a -> A — pair (A,A) visited once; (B,B) visited once
        # Mutual references must live in the same FileDescriptorProto.
        from google.protobuf import descriptor_pb2
        old = descriptor_pool.DescriptorPool()
        new = descriptor_pool.DescriptorPool()
        for p in (old, new):
            fp = descriptor_pb2.FileDescriptorProto(
                name=f"mutual_{id(p):x}.proto", package="t", syntax="proto3",
            )
            ma = fp.message_type.add()
            ma.name = "A"
            fa = ma.field.add()
            fa.name = "b"
            fa.number = 1
            fa.type = T.TYPE_MESSAGE
            fa.type_name = "t.B"
            fa.label = T.LABEL_OPTIONAL
            mb = fp.message_type.add()
            mb.name = "B"
            fb = mb.field.add()
            fb.name = "a"
            fb.number = 1
            fb.type = T.TYPE_MESSAGE
            fb.type_name = "t.A"
            fb.label = T.LABEL_OPTIONAL
            p.Add(fp)
        report = check_compatibility(old, "t.A", new, "t.A")
        assert report.is_compatible


# ---------------------------------------------------------------------------
# Enum recursion via fields
# ---------------------------------------------------------------------------


class TestEnumViaField:
    def test_enum_value_removed_via_field(self) -> None:
        old = descriptor_pool.DescriptorPool()
        new = descriptor_pool.DescriptorPool()
        build_enum(old, "t.Color", {"RED": 0, "BLUE": 1})
        build_enum(new, "t.Color", {"RED": 0})
        for p, label in ((old, "old"), (new, "new")):
            build_message(p, "t.M", fields=[
                {"name": "color", "number": 1, "type": T.TYPE_ENUM, "type_name": "t.Color"},
            ], file_name=f"m_{label}.proto")
        report = check_compatibility(old, "t.M", new, "t.M")
        f = next(f for f in report.findings if f.rule_id == "enum_value_removed")
        assert f.path == FieldPath.parse("color")
        assert "BLUE" in f.message

    def test_enum_in_nested_message(self) -> None:
        old = descriptor_pool.DescriptorPool()
        new = descriptor_pool.DescriptorPool()
        build_enum(old, "t.Color", {"RED": 0})
        build_enum(new, "t.Color", {"RED": 0, "BLUE": 1})
        for p, label in ((old, "old"), (new, "new")):
            build_message(p, "t.Inner", fields=[
                {"name": "c", "number": 1, "type": T.TYPE_ENUM, "type_name": "t.Color"},
            ], file_name=f"inner_{label}.proto")
            build_message(p, "t.Outer", fields=[
                {"name": "inner", "number": 1, "type": T.TYPE_MESSAGE, "type_name": "t.Inner"},
            ], file_name=f"outer_{label}.proto")
        report = check_compatibility(old, "t.Outer", new, "t.Outer")
        # default level STRICT — enum_value_added (FORWARD) is included
        f = next(f for f in report.findings if f.rule_id == "enum_value_added")
        assert f.path == FieldPath.parse("inner.c")


# ---------------------------------------------------------------------------
# Map handling
# ---------------------------------------------------------------------------


class TestMaps:
    def test_map_to_repeated_fires(self) -> None:
        old = descriptor_pool.DescriptorPool()
        new = descriptor_pool.DescriptorPool()
        pb = ProtoBuilder(old)
        pb.map_message(
            "t.M", fields={},
            map_fields={"kv": (T.TYPE_STRING, T.TYPE_STRING, 1)},
        )
        build_message(new, "t.M", fields=[
            {"name": "kv", "number": 1, "type": T.TYPE_STRING, "label": T.LABEL_REPEATED},
        ])
        report = check_compatibility(old, "t.M", new, "t.M")
        assert any(f.rule_id == "map_to_repeated" for f in report.findings)

    def test_map_value_message_recursion(self) -> None:
        # map<string, Inner> on both sides; Inner gains a field.
        # With map-value dispatch, the recursion enters Inner via
        # ``items.value`` (the synthetic map-entry value sub-field),
        # so the added field surfaces at ``items.value.extra``.
        old = descriptor_pool.DescriptorPool()
        new = descriptor_pool.DescriptorPool()
        build_message(old, "t.Inner", fields=[
            {"name": "v", "number": 1, "type": T.TYPE_INT32},
        ])
        build_message(new, "t.Inner", fields=[
            {"name": "v", "number": 1, "type": T.TYPE_INT32},
            {"name": "extra", "number": 2, "type": T.TYPE_STRING},
        ])
        _build_map_msg_value(old, "t.M", map_field="items",
                             key_type=T.TYPE_STRING, value_type_name="t.Inner")
        _build_map_msg_value(new, "t.M", map_field="items",
                             key_type=T.TYPE_STRING, value_type_name="t.Inner")
        report = check_compatibility(old, "t.M", new, "t.M")
        f = next(f for f in report.findings if f.rule_id == "field_added")
        assert f.path == FieldPath.parse("items.value.extra")

    def test_map_value_type_rename_fires_field_type_name_changed(self) -> None:
        """map<K, OldMsg> → map<K, NewMsg>: the rule fires on the
        value sub-field (``items.value``) now that the engine
        dispatches field rules on the map-entry value.
        """
        old = descriptor_pool.DescriptorPool()
        new = descriptor_pool.DescriptorPool()
        build_message(old, "t.OldVal", fields=[
            {"name": "x", "number": 1, "type": T.TYPE_INT32},
        ])
        build_message(new, "t.NewVal", fields=[
            {"name": "x", "number": 1, "type": T.TYPE_INT32},
        ])
        _build_map_msg_value(old, "t.M", map_field="items",
                             key_type=T.TYPE_STRING, value_type_name="t.OldVal")
        _build_map_msg_value(new, "t.M", map_field="items",
                             key_type=T.TYPE_STRING, value_type_name="t.NewVal")
        report = check_compatibility(old, "t.M", new, "t.M")
        hits = [f for f in report.findings if f.rule_id == "field_type_name_changed"]
        assert len(hits) == 1
        assert hits[0].path == FieldPath.parse("items.value")
        assert "t.OldVal" in hits[0].message
        assert "t.NewVal" in hits[0].message

    def test_map_value_scalar_type_change_fires(self) -> None:
        """map<K, string> → map<K, bytes> now fires
        ``field_type_semantic_change`` at the value sub-field —
        pre-dispatch this was silent.
        """
        old = descriptor_pool.DescriptorPool()
        new = descriptor_pool.DescriptorPool()
        from tests.proto_builder import ProtoBuilder
        pb_old = ProtoBuilder(old)
        pb_old.map_message(
            "t.M", fields={},
            map_fields={"items": (T.TYPE_STRING, T.TYPE_STRING, 1)},
        )
        pb_new = ProtoBuilder(new)
        pb_new.map_message(
            "t.M", fields={},
            map_fields={"items": (T.TYPE_STRING, T.TYPE_BYTES, 1)},
        )
        report = check_compatibility(old, "t.M", new, "t.M")
        hits = [f for f in report.findings
                if f.rule_id == "field_type_semantic_change"]
        assert len(hits) == 1
        assert hits[0].path == FieldPath.parse("items.value")

    def test_map_value_kind_change_fires_wire_incompatible(self) -> None:
        """map<K, Msg> → map<K, Enum>: different wire groups, so
        ``field_type_wire_incompatible`` fires at ``items.value``.
        Pre-dispatch this was silent — exactly the round-5 gap.
        """
        old = descriptor_pool.DescriptorPool()
        new = descriptor_pool.DescriptorPool()
        build_message(old, "t.ValMsg", fields=[
            {"name": "x", "number": 1, "type": T.TYPE_INT32},
        ])
        build_enum(new, "t.ValEnum", {"ZERO": 0})
        _build_map_msg_value(old, "t.M", map_field="items",
                             key_type=T.TYPE_STRING, value_type_name="t.ValMsg")
        # Build a map<string, t.ValEnum> on the new side manually.
        from google.protobuf import descriptor_pb2 as dpb
        fp = dpb.FileDescriptorProto(
            name="new_enum_map.proto", package="t", syntax="proto3",
        )
        mp = fp.message_type.add()
        mp.name = "M"
        entry = mp.nested_type.add()
        entry.name = "ItemsEntry"
        entry.options.map_entry = True
        k = entry.field.add()
        k.name, k.number, k.type = "key", 1, T.TYPE_STRING
        k.label = T.LABEL_OPTIONAL
        v = entry.field.add()
        v.name, v.number, v.type = "value", 2, T.TYPE_ENUM
        v.type_name = "t.ValEnum"
        v.label = T.LABEL_OPTIONAL
        f = mp.field.add()
        f.name, f.number, f.type = "items", 1, T.TYPE_MESSAGE
        f.type_name = ".t.M.ItemsEntry"
        f.label = T.LABEL_REPEATED
        new.Add(fp)
        report = check_compatibility(old, "t.M", new, "t.M")
        hits = [f for f in report.findings
                if f.rule_id == "field_type_wire_incompatible"]
        assert len(hits) == 1
        assert hits[0].path == FieldPath.parse("items.value")

    def test_map_outer_rename_stays_silent_on_value(self) -> None:
        """Renaming the outer container (UserV1 → UserV2) must NOT
        fire value-level findings when the map contents are
        byte-identical — the synthetic MapEntry name rotates but
        the value-field's declared type doesn't.
        """
        old = descriptor_pool.DescriptorPool()
        new = descriptor_pool.DescriptorPool()
        from tests.proto_builder import ProtoBuilder
        ProtoBuilder(old).map_message(
            "t.UserV1", fields={},
            map_fields={"items": (T.TYPE_STRING, T.TYPE_INT32, 1)},
        )
        ProtoBuilder(new).map_message(
            "t.UserV2", fields={},
            map_fields={"items": (T.TYPE_STRING, T.TYPE_INT32, 1)},
        )
        report = check_compatibility(
            old, "t.UserV1", new, "t.UserV2",
            level=CompatibilityLevel.STRICT,
        )
        # No value-level findings — everything inside is unchanged.
        value_findings = [f for f in report.findings
                          if str(f.path).startswith("items.value")]
        assert value_findings == []

    def test_shared_map_value_findings_at_every_path(self) -> None:
        """Two map fields sharing the same value message type must
        both receive path-complete findings when the shared type
        changes. Guards against a cache-replay regression where
        only the first map field's findings would surface.
        """
        old = descriptor_pool.DescriptorPool()
        new = descriptor_pool.DescriptorPool()
        build_message(old, "t.Inner", fields=[
            {"name": "v", "number": 1, "type": T.TYPE_INT32},
        ])
        build_message(new, "t.Inner", fields=[
            {"name": "v", "number": 1, "type": T.TYPE_INT32},
            {"name": "extra", "number": 2, "type": T.TYPE_STRING},
        ])
        _build_outer_two_maps_msg_value(
            old, map_fields=("a", "b"), value_type_name="t.Inner",
            file_name="outer_two_maps_old.proto",
        )
        _build_outer_two_maps_msg_value(
            new, map_fields=("a", "b"), value_type_name="t.Inner",
            file_name="outer_two_maps_new.proto",
        )
        report = check_compatibility(old, "t.Outer", new, "t.Outer")
        added = sorted(
            str(f.path) for f in report.findings
            if f.rule_id == "field_added"
        )
        assert added == ["a.value.extra", "b.value.extra"]

    def test_cycle_through_map_value(self) -> None:
        """A message that self-references through its own map-value
        type must terminate and emit findings exactly once, just
        like a repeated-field self-reference.
        """
        old = descriptor_pool.DescriptorPool()
        new = descriptor_pool.DescriptorPool()
        _build_self_map_cycle(old, with_tag=False)
        _build_self_map_cycle(new, with_tag=True)
        report = check_compatibility(old, "t.Tree", new, "t.Tree")
        added = [f for f in report.findings if f.rule_id == "field_added"]
        assert len(added) == 1
        assert added[0].path == FieldPath.parse("tag")

    def test_map_value_enum_rename_fires_field_type_name_changed(self) -> None:
        """``map<K, OldEnum>`` → ``map<K, NewEnum>`` (same values,
        different enum name) must fire ``field_type_name_changed``
        at ``items.value`` — dispatching field rules on the value
        sub-field handles enum renames just like message renames.
        """
        old = descriptor_pool.DescriptorPool()
        new = descriptor_pool.DescriptorPool()
        build_enum(old, "t.OldEnum", {"ZERO": 0, "ONE": 1})
        build_enum(new, "t.NewEnum", {"ZERO": 0, "ONE": 1})
        _build_map_enum_value(old, "t.M", map_field="items",
                              key_type=T.TYPE_STRING, value_type_name="t.OldEnum")
        _build_map_enum_value(new, "t.M", map_field="items",
                              key_type=T.TYPE_STRING, value_type_name="t.NewEnum")
        report = check_compatibility(old, "t.M", new, "t.M",
                                     level=CompatibilityLevel.STRICT)
        hits = [f for f in report.findings if f.rule_id == "field_type_name_changed"]
        assert len(hits) == 1
        assert hits[0].path == FieldPath.parse("items.value")
        assert "t.OldEnum" in hits[0].message
        assert "t.NewEnum" in hits[0].message


def _build_map_msg_value(
    pool: descriptor_pool.DescriptorPool,
    full_name: str,
    *,
    map_field: str,
    key_type: int,
    value_type_name: str,
) -> None:
    """Build a message with a single map<key, MessageT> field."""
    from google.protobuf import descriptor_pb2
    parts = full_name.rsplit(".", 1)
    package = parts[0] if len(parts) > 1 else ""
    msg_name = parts[-1]
    fp = descriptor_pb2.FileDescriptorProto(
        name=f"map_{msg_name}_{id(pool):x}.proto",
        package=package,
        syntax="proto3",
    )
    mp = fp.message_type.add()
    mp.name = msg_name
    entry_name = f"{map_field.title().replace('_', '')}Entry"
    entry_msg = mp.nested_type.add()
    entry_msg.name = entry_name
    entry_msg.options.map_entry = True
    k = entry_msg.field.add()
    k.name = "key"
    k.number = 1
    k.type = key_type
    k.label = T.LABEL_OPTIONAL
    v = entry_msg.field.add()
    v.name = "value"
    v.number = 2
    v.type = T.TYPE_MESSAGE
    v.type_name = value_type_name
    v.label = T.LABEL_OPTIONAL
    f = mp.field.add()
    f.name = map_field
    f.number = 1
    f.type = T.TYPE_MESSAGE
    f.type_name = f".{package}.{msg_name}.{entry_name}" if package else f".{msg_name}.{entry_name}"
    f.label = T.LABEL_REPEATED
    pool.Add(fp)


def _build_map_enum_value(
    pool: descriptor_pool.DescriptorPool,
    full_name: str,
    *,
    map_field: str,
    key_type: int,
    value_type_name: str,
) -> None:
    """Build a message with a single map<key, EnumT> field."""
    from google.protobuf import descriptor_pb2
    parts = full_name.rsplit(".", 1)
    package = parts[0] if len(parts) > 1 else ""
    msg_name = parts[-1]
    fp = descriptor_pb2.FileDescriptorProto(
        name=f"mapenum_{msg_name}_{id(pool):x}.proto",
        package=package,
        syntax="proto3",
    )
    mp = fp.message_type.add()
    mp.name = msg_name
    entry_name = f"{map_field.title().replace('_', '')}Entry"
    entry_msg = mp.nested_type.add()
    entry_msg.name = entry_name
    entry_msg.options.map_entry = True
    k = entry_msg.field.add()
    k.name = "key"
    k.number = 1
    k.type = key_type
    k.label = T.LABEL_OPTIONAL
    v = entry_msg.field.add()
    v.name = "value"
    v.number = 2
    v.type = T.TYPE_ENUM
    v.type_name = value_type_name
    v.label = T.LABEL_OPTIONAL
    f = mp.field.add()
    f.name = map_field
    f.number = 1
    f.type = T.TYPE_MESSAGE
    f.type_name = f".{package}.{msg_name}.{entry_name}" if package else f".{msg_name}.{entry_name}"
    f.label = T.LABEL_REPEATED
    pool.Add(fp)


def _build_outer_two_maps_msg_value(
    pool: descriptor_pool.DescriptorPool,
    *,
    map_fields: tuple[str, str],
    value_type_name: str,
    file_name: str,
) -> None:
    """Build ``t.Outer { map<string, V> <a>; map<string, V> <b>; }``.

    Two map fields sharing the same user-authored value type, so the
    traversal sees the same ``(V, V)`` pair under two different
    paths. Exercises the path-complete cache replay for shared
    types referenced via maps.
    """
    from google.protobuf import descriptor_pb2
    fp = descriptor_pb2.FileDescriptorProto(
        name=file_name, package="t", syntax="proto3",
    )
    mp = fp.message_type.add()
    mp.name = "Outer"
    for idx, map_field in enumerate(map_fields):
        entry_name = f"{map_field.title().replace('_', '')}Entry"
        entry_msg = mp.nested_type.add()
        entry_msg.name = entry_name
        entry_msg.options.map_entry = True
        k = entry_msg.field.add()
        k.name, k.number, k.type = "key", 1, T.TYPE_STRING
        k.label = T.LABEL_OPTIONAL
        v = entry_msg.field.add()
        v.name, v.number, v.type = "value", 2, T.TYPE_MESSAGE
        v.type_name = value_type_name
        v.label = T.LABEL_OPTIONAL
        f = mp.field.add()
        f.name, f.number, f.type = map_field, idx + 1, T.TYPE_MESSAGE
        f.type_name = f".t.Outer.{entry_name}"
        f.label = T.LABEL_REPEATED
    pool.Add(fp)


def _build_self_map_cycle(
    pool: descriptor_pool.DescriptorPool,
    *,
    with_tag: bool,
) -> None:
    """Build ``t.Tree { map<string, Tree> children = 1; [int32 tag = 2] }``.

    The map-value type is the containing message itself — exercises
    cycle detection when the recursion enters via the map-entry
    ``value`` sub-field.
    """
    from google.protobuf import descriptor_pb2
    fp = descriptor_pb2.FileDescriptorProto(
        name=f"tree_{id(pool):x}.proto", package="t", syntax="proto3",
    )
    mp = fp.message_type.add()
    mp.name = "Tree"
    entry_msg = mp.nested_type.add()
    entry_msg.name = "ChildrenEntry"
    entry_msg.options.map_entry = True
    k = entry_msg.field.add()
    k.name, k.number, k.type = "key", 1, T.TYPE_STRING
    k.label = T.LABEL_OPTIONAL
    v = entry_msg.field.add()
    v.name, v.number, v.type = "value", 2, T.TYPE_MESSAGE
    v.type_name = "t.Tree"
    v.label = T.LABEL_OPTIONAL
    f1 = mp.field.add()
    f1.name, f1.number, f1.type = "children", 1, T.TYPE_MESSAGE
    f1.type_name = ".t.Tree.ChildrenEntry"
    f1.label = T.LABEL_REPEATED
    if with_tag:
        f2 = mp.field.add()
        f2.name, f2.number, f2.type = "tag", 2, T.TYPE_INT32
        f2.label = T.LABEL_OPTIONAL
    pool.Add(fp)


# ---------------------------------------------------------------------------
# End-to-end profile behavior (filter unit tests live in test_profiles.py)
# ---------------------------------------------------------------------------


class TestEndToEndProfileBehavior:
    """Worked example: user_v1 -> user_v2 across all four profiles.

    Directions are assigned by compat risk (which reader is at risk)
    rather than direction of schema change. So CONSUMER_SAFE now
    surfaces additions that old consumers can't interpret (field_added,
    enum_value_added) in addition to removals.
    """

    def _build_user_pair(self) -> tuple[descriptor_pool.DescriptorPool, descriptor_pool.DescriptorPool]:
        old = descriptor_pool.DescriptorPool()
        new = descriptor_pool.DescriptorPool()
        build_enum(old, "acme.PhoneType", {"MOBILE": 0, "HOME": 1, "WORK": 2})
        build_enum(new, "acme.PhoneType", {"MOBILE": 0, "HOME": 1, "WORK": 2, "FAX": 3})
        for p, label in ((old, "old"), (new, "new")):
            file_name = f"user_{label}.proto"
            if label == "old":
                fields = [
                    {"name": "name", "number": 1, "type": T.TYPE_STRING},
                    {"name": "email", "number": 2, "type": T.TYPE_STRING},
                    {"name": "phone_type", "number": 3, "type": T.TYPE_ENUM,
                     "type_name": "acme.PhoneType"},
                    {"name": "internal_notes", "number": 4, "type": T.TYPE_STRING},
                ]
                build_message(p, "acme.User", fields=fields, file_name=file_name)
            else:
                fields = [
                    {"name": "name", "number": 1, "type": T.TYPE_STRING},
                    {"name": "email", "number": 2, "type": T.TYPE_BYTES},
                    {"name": "phone_type", "number": 3, "type": T.TYPE_ENUM,
                     "type_name": "acme.PhoneType"},
                    {"name": "nickname", "number": 5, "type": T.TYPE_STRING,
                     "proto3_optional": True, "oneof_index": 0},
                ]
                build_message(
                    p, "acme.User",
                    fields=fields,
                    oneofs=["_nickname"],
                    file_name=file_name,
                )
        return old, new

    def test_consumer_safe_surfaces_risks_to_old_consumers(self) -> None:
        old, new = self._build_user_pair()
        report = check_compatibility(
            old, "acme.User", new, "acme.User",
            level=CompatibilityLevel.CONSUMER_SAFE,
        )
        ids = {f.rule_id for f in report.findings}
        assert "field_type_semantic_change" in ids   # email string -> bytes
        assert "field_removed" in ids                # internal_notes (BACKWARD)
        assert "field_added" in ids                  # nickname (BACKWARD — old consumer sees unknown)
        assert "enum_value_added" in ids             # FAX (BACKWARD — old consumer unknown value)
        assert not report.is_compatible

    def test_producer_safe_surfaces_risks_to_new_consumers(self) -> None:
        old, new = self._build_user_pair()
        report = check_compatibility(
            old, "acme.User", new, "acme.User",
            level=CompatibilityLevel.PRODUCER_SAFE,
        )
        ids = {f.rule_id for f in report.findings}
        # The email type change is BOTH — surfaces everywhere.
        assert "field_type_semantic_change" in ids
        # Backward-compat concerns (risks to new consumer on old data)
        # are filtered OUT because this worked example has no such
        # change — v2 doesn't remove any enum values and doesn't add
        # a proto2 required field. CONSUMER_SAFE-only findings:
        assert "field_removed" not in ids
        assert "field_added" not in ids
        assert "enum_value_added" not in ids

    def test_strict_includes_all(self) -> None:
        old, new = self._build_user_pair()
        report = check_compatibility(
            old, "acme.User", new, "acme.User",
            level=CompatibilityLevel.STRICT,
        )
        ids = {f.rule_id for f in report.findings}
        assert {"field_type_semantic_change", "field_removed",
                "field_added", "enum_value_added"} <= ids

    def test_wire_only_no_findings(self) -> None:
        old, new = self._build_user_pair()
        report = check_compatibility(
            old, "acme.User", new, "acme.User",
            level=CompatibilityLevel.WIRE,
        )
        # No wire-level breaks in this scenario.
        assert report.is_compatible


# ---------------------------------------------------------------------------
# Ignore paths
# ---------------------------------------------------------------------------


class TestIgnorePaths:
    def test_ignore_suppresses_exact_path(self) -> None:
        old = descriptor_pool.DescriptorPool()
        new = descriptor_pool.DescriptorPool()
        build_message(old, "t.M", fields=[
            {"name": "x", "number": 1, "type": T.TYPE_STRING},
            {"name": "y", "number": 2, "type": T.TYPE_STRING},
        ])
        build_message(new, "t.M", fields=[])
        checker = SchemaChecker()
        checker.ignore("x")
        report = checker.check(old, "t.M", new, "t.M")
        ids = {(f.rule_id, str(f.path)) for f in report.findings}
        assert ("field_removed", "y") in ids
        assert all(str(f.path) != "x" for f in report.findings)

    def test_ignore_suppresses_descendants(self) -> None:
        old = descriptor_pool.DescriptorPool()
        new = descriptor_pool.DescriptorPool()
        build_message(old, "t.Inner", fields=[
            {"name": "secret", "number": 1, "type": T.TYPE_STRING},
        ])
        build_message(new, "t.Inner", fields=[])
        for p, label in ((old, "old"), (new, "new")):
            build_message(p, "t.Outer", fields=[
                {"name": "debug", "number": 1, "type": T.TYPE_MESSAGE,
                 "type_name": "t.Inner"},
                {"name": "data", "number": 2, "type": T.TYPE_STRING},
            ], file_name=f"outer_{label}.proto")
        checker = SchemaChecker()
        checker.ignore("debug")
        report = checker.check(old, "t.Outer", new, "t.Outer")
        # debug.secret should be ignored
        assert not any(str(f.path).startswith("debug") for f in report.findings)

    def test_ignore_suppresses_map_value_path(self) -> None:
        """Ignoring a map field's ``value``-rooted prefix hides both
        the value sub-field dispatches and the recursion findings
        under it.
        """
        old = descriptor_pool.DescriptorPool()
        new = descriptor_pool.DescriptorPool()
        build_message(old, "t.Inner", fields=[
            {"name": "secret", "number": 1, "type": T.TYPE_STRING},
        ])
        build_message(new, "t.Inner", fields=[])  # secret removed
        _build_map_msg_value(old, "t.M", map_field="items",
                             key_type=T.TYPE_STRING, value_type_name="t.Inner")
        _build_map_msg_value(new, "t.M", map_field="items",
                             key_type=T.TYPE_STRING, value_type_name="t.Inner")
        checker = SchemaChecker()
        checker.ignore("items.value")
        report = checker.check(old, "t.M", new, "t.M")
        assert not any(
            str(f.path).startswith("items.value") for f in report.findings
        )


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrors:
    def test_missing_old_type(self) -> None:
        old = descriptor_pool.DescriptorPool()
        new = descriptor_pool.DescriptorPool()
        build_message(new, "t.M", fields=[])
        with pytest.raises(ValueError, match="old_type"):
            check_compatibility(old, "t.M", new, "t.M")

    def test_missing_new_type(self) -> None:
        old = descriptor_pool.DescriptorPool()
        new = descriptor_pool.DescriptorPool()
        build_message(old, "t.M", fields=[])
        with pytest.raises(ValueError, match="new_type"):
            check_compatibility(old, "t.M", new, "t.M")


# ---------------------------------------------------------------------------
# Custom rule registration
# ---------------------------------------------------------------------------


class TestCustomRules:
    def test_custom_field_rule_invoked(self) -> None:
        old = descriptor_pool.DescriptorPool()
        new = descriptor_pool.DescriptorPool()
        build_message(old, "t.M", fields=[
            {"name": "x", "number": 1, "type": T.TYPE_STRING},
        ])
        build_message(new, "t.M", fields=[
            {"name": "x", "number": 1, "type": T.TYPE_STRING},
        ])
        seen: list[str] = []

        def my_rule(old_fd, new_fd, path):
            seen.append(str(path))
            return []

        checker = SchemaChecker()
        checker.register_raw_field_rule("seen", my_rule)
        checker.check(old, "t.M", new, "t.M")
        assert "x" in seen

    def test_custom_field_rule_emits(self) -> None:
        old = descriptor_pool.DescriptorPool()
        new = descriptor_pool.DescriptorPool()
        build_message(old, "t.M", fields=[
            {"name": "x", "number": 1, "type": T.TYPE_STRING},
        ])
        build_message(new, "t.M", fields=[
            {"name": "x", "number": 1, "type": T.TYPE_STRING},
        ])

        def reject_x(old_fd, new_fd, path):
            if old_fd is not None and old_fd.name == "x":
                return [Finding(
                    path=path, rule_id="custom",
                    severity=Severity.WIRE,
                    direction=Direction.BOTH,
                    message="x is forbidden",
                )]
            return []

        checker = SchemaChecker(level=CompatibilityLevel.WIRE)
        checker.register_raw_field_rule("custom", reject_x)
        report = checker.check(old, "t.M", new, "t.M")
        assert any(f.rule_id == "custom" for f in report.findings)

    def test_register_raw_enum_rule(self) -> None:
        """The raw return-style enum rule API is part of the public surface."""
        old = descriptor_pool.DescriptorPool()
        new = descriptor_pool.DescriptorPool()
        build_enum(old, "t.Color", {"RED": 0, "BLUE": 1})
        build_enum(new, "t.Color", {"RED": 0})  # BLUE removed
        for p, label in ((old, "old"), (new, "new")):
            build_message(p, "t.M", fields=[
                {"name": "c", "number": 1, "type": T.TYPE_ENUM,
                 "type_name": "t.Color"},
            ], file_name=f"enum_consumer_{label}.proto")

        seen: list[tuple[str, str]] = []

        def my_enum_rule(old_enum, new_enum, path):
            if old_enum is None or new_enum is None:
                return []
            for v in old_enum.values:
                seen.append((v.name, str(path)))
            return []

        checker = SchemaChecker(include_builtin=False)
        checker.register_raw_enum_rule("record", my_enum_rule)
        checker.check(old, "t.M", new, "t.M")
        # The rule saw the old enum's values at the field's path.
        assert ("RED", "c") in seen
        assert ("BLUE", "c") in seen

    def test_register_raw_message_rule(self) -> None:
        """The raw return-style message rule API is part of the public surface."""
        old = descriptor_pool.DescriptorPool()
        new = descriptor_pool.DescriptorPool()
        for p in (old, new):
            build_message(p, "t.M", fields=[
                {"name": "x", "number": 1, "type": T.TYPE_STRING},
            ])

        visits: list[str] = []

        def my_msg_rule(old_desc, new_desc, path):
            if old_desc is not None:
                visits.append(old_desc.full_name)
            return []

        checker = SchemaChecker(include_builtin=False)
        checker.register_raw_message_rule("visit", my_msg_rule)
        checker.check(old, "t.M", new, "t.M")
        assert visits == ["t.M"]

    def test_include_builtin_false_drops_builtins(self) -> None:
        old = descriptor_pool.DescriptorPool()
        new = descriptor_pool.DescriptorPool()
        build_message(old, "t.M", fields=[
            {"name": "x", "number": 1, "type": T.TYPE_STRING},
        ])
        build_message(new, "t.M", fields=[])
        checker = SchemaChecker(include_builtin=False)
        report = checker.check(old, "t.M", new, "t.M")
        # field_removed is built-in and should not fire
        assert all(f.rule_id != "field_removed" for f in report.findings)

    def test_emit_plugin_runs_on_map_value_sub_field(self) -> None:
        """An emit-style field plugin must receive the synthetic
        ``MapEntry.value`` descriptor at path ``<map>.value``. Locks
        in the plugin API contract for map-value dispatch.
        """
        old = descriptor_pool.DescriptorPool()
        new = descriptor_pool.DescriptorPool()
        build_message(old, "t.Inner", fields=[
            {"name": "v", "number": 1, "type": T.TYPE_INT32},
        ])
        build_message(new, "t.Inner", fields=[
            {"name": "v", "number": 1, "type": T.TYPE_INT32},
        ])
        _build_map_msg_value(old, "t.M", map_field="items",
                             key_type=T.TYPE_STRING, value_type_name="t.Inner")
        _build_map_msg_value(new, "t.M", map_field="items",
                             key_type=T.TYPE_STRING, value_type_name="t.Inner")

        seen: list[tuple[str, str | None, str | None]] = []

        def probe(ctx) -> None:
            seen.append((
                str(ctx.path),
                ctx.old_field.name if ctx.old_field else None,
                ctx.new_field.name if ctx.new_field else None,
            ))

        checker = SchemaChecker(include_builtin=False)
        checker.register_field_rule("probe", probe)
        checker.check(old, "t.M", new, "t.M")
        # The plugin must have been invoked on the value sub-field
        # with name "value" at path "items.value" — NOT on the
        # synthetic MapEntry itself, and NOT at "items".
        assert ("items.value", "value", "value") in seen

    def test_raw_rule_out_of_subtree_path_preserved_on_replay(self) -> None:
        """Regression lock for ``_strip_path_prefix``: a raw rule that
        emits at a path unrelated to the current visit's entry path
        must NOT get that path mangled by cache replay. Before the
        fallback fix, replaying a shared type at prefix ``a`` would
        concatenate it onto the finding's original path, producing
        ``a.global_issue`` instead of the rule's intended
        ``global_issue``.
        """
        old = descriptor_pool.DescriptorPool()
        new = descriptor_pool.DescriptorPool()
        build_message(old, "t.Shared", fields=[
            {"name": "x", "number": 1, "type": T.TYPE_INT32},
        ])
        build_message(new, "t.Shared", fields=[
            {"name": "x", "number": 1, "type": T.TYPE_INT32},
        ])
        for p, label in ((old, "old"), (new, "new")):
            build_message(p, "t.Outer", fields=[
                {"name": "a", "number": 1, "type": T.TYPE_MESSAGE,
                 "type_name": "t.Shared"},
                {"name": "b", "number": 2, "type": T.TYPE_MESSAGE,
                 "type_name": "t.Shared"},
            ], file_name=f"out_raw_{label}.proto")

        def rogue(old_m, new_m, path):
            # Emit at an absolute, non-entry-rooted path. A real rule
            # wouldn't typically do this, but plugin authors can, and
            # the engine must not corrupt those paths on replay.
            return [Finding(
                path=FieldPath.parse("global_issue"),
                rule_id="rogue",
                severity=Severity.POLICY,
                direction=Direction.BOTH,
                message=f"fired under {path!s}",
            )]

        checker = SchemaChecker(include_builtin=False)
        checker.register_raw_message_rule("rogue", rogue)
        report = checker.check(old, "t.Outer", new, "t.Outer")
        rogue_paths = [str(f.path) for f in report.findings
                       if f.rule_id == "rogue"]
        # Three firings (Outer + Shared-at-a + Shared-at-b-via-cache),
        # all at the rule's intended path — never ``a.global_issue``
        # or ``b.global_issue`` from a mangled prefix concat.
        assert rogue_paths == ["global_issue"] * 3


# ---------------------------------------------------------------------------
# Cross-type comparison
# ---------------------------------------------------------------------------


class TestCrossType:
    def test_different_type_names(self) -> None:
        old = descriptor_pool.DescriptorPool()
        new = descriptor_pool.DescriptorPool()
        build_message(old, "t.UserV1", fields=[
            {"name": "name", "number": 1, "type": T.TYPE_STRING},
            {"name": "email", "number": 2, "type": T.TYPE_STRING},
        ])
        build_message(new, "t.UserV2", fields=[
            {"name": "name", "number": 1, "type": T.TYPE_STRING},
        ])
        report = check_compatibility(old, "t.UserV1", new, "t.UserV2")
        assert any(f.rule_id == "field_removed" and str(f.path) == "email"
                   for f in report.findings)
