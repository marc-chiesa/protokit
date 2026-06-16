"""Unit tests for the columnar recursion-detection walker (U1).

These exercise ``_find_recursive_cycle`` directly — a pure descriptor-graph walk
with no ptars/pyarrow dependency, so the module does NOT ``importorskip`` and runs
in the core test environment. The walker is the pre-flight that turns ptars'
recursive-schema segfault into a catchable rejection; the rejection wiring and the
end-to-end CLI behaviour live in ``test_columnar.py`` / ``cli/test_parquet_recursive.py``.
"""

from __future__ import annotations

from google.protobuf import (
    any_pb2,
    descriptor_pb2,
    descriptor_pool,
    struct_pb2,
    timestamp_pb2,
)

from protokit.storage._columnar import _find_recursive_cycle

F = descriptor_pb2.FieldDescriptorProto


def _desc(fds: descriptor_pb2.FileDescriptorSet, type_name: str):
    """Build an isolated pool from a FileDescriptorSet and resolve one message.

    Files must already be in dependency order (each dependency before its
    dependent), matching how ``_build_fds`` orders WKT files first.
    """
    pool = descriptor_pool.DescriptorPool()
    for fp in fds.file:
        pool.Add(fp)
    return pool.FindMessageTypeByName(type_name)


def _msgfield(msg, name, number, type_name, *, label=F.LABEL_OPTIONAL):
    fld = msg.field.add()
    fld.name, fld.number, fld.type, fld.label = name, number, F.TYPE_MESSAGE, label
    fld.type_name = type_name


# --- recursive shapes: a cycle is returned ----------------------------------


def test_direct_self_reference():
    fds = descriptor_pb2.FileDescriptorSet()
    f = fds.file.add()
    f.name, f.package, f.syntax = "node.proto", "n", "proto3"
    node = f.message_type.add()
    node.name = "Node"
    _msgfield(node, "children", 1, ".n.Node", label=F.LABEL_REPEATED)

    result = _find_recursive_cycle(_desc(fds, "n.Node"))
    assert result is not None
    cycle, is_wkt = result
    assert cycle == ["n.Node", "n.Node"]
    assert is_wkt is False


def test_mutual_recursion():
    fds = descriptor_pb2.FileDescriptorSet()
    f = fds.file.add()
    f.name, f.package, f.syntax = "ab.proto", "p", "proto3"
    a = f.message_type.add()
    a.name = "A"
    _msgfield(a, "b", 1, ".p.B")
    b = f.message_type.add()
    b.name = "B"
    _msgfield(b, "a", 1, ".p.A")

    result = _find_recursive_cycle(_desc(fds, "p.A"))
    assert result is not None
    cycle, is_wkt = result
    assert cycle == ["p.A", "p.B", "p.A"]
    assert is_wkt is False


def test_recursion_through_map_value():
    fds = descriptor_pb2.FileDescriptorSet()
    f = fds.file.add()
    f.name, f.package, f.syntax = "tree.proto", "t", "proto3"
    node = f.message_type.add()
    node.name = "Node"
    entry = node.nested_type.add()
    entry.name = "KidsEntry"
    entry.options.map_entry = True
    ek = entry.field.add()
    ek.name, ek.number, ek.type, ek.label = "key", 1, F.TYPE_STRING, F.LABEL_OPTIONAL
    _msgfield(entry, "value", 2, ".t.Node")  # map<string, Node>
    _msgfield(node, "kids", 1, ".t.Node.KidsEntry", label=F.LABEL_REPEATED)

    result = _find_recursive_cycle(_desc(fds, "t.Node"))
    assert result is not None
    cycle, is_wkt = result
    assert "t.Node" in cycle and is_wkt is False


def test_recursion_through_group():
    fds = descriptor_pb2.FileDescriptorSet()
    f = fds.file.add()
    f.name, f.package, f.syntax = "g.proto", "p", "proto2"
    outer = f.message_type.add()
    outer.name = "Outer"
    grp = outer.nested_type.add()
    grp.name = "G"
    _msgfield(grp, "o", 1, ".p.Outer")
    gf = outer.field.add()
    gf.name, gf.number, gf.type, gf.label = "g", 1, F.TYPE_GROUP, F.LABEL_REPEATED
    gf.type_name = ".p.Outer.G"

    result = _find_recursive_cycle(_desc(fds, "p.Outer"))
    assert result is not None
    cycle, is_wkt = result
    assert "p.Outer" in cycle and is_wkt is False


def test_recursion_through_oneof():
    fds = descriptor_pb2.FileDescriptorSet()
    f = fds.file.add()
    f.name, f.package, f.syntax = "node.proto", "n", "proto3"
    node = f.message_type.add()
    node.name = "Node"
    od = node.oneof_decl.add()
    od.name = "choice"
    fld = node.field.add()
    fld.name, fld.number, fld.type, fld.label = "child", 1, F.TYPE_MESSAGE, F.LABEL_OPTIONAL
    fld.type_name = ".n.Node"
    fld.oneof_index = 0

    result = _find_recursive_cycle(_desc(fds, "n.Node"))
    assert result is not None
    cycle, _ = result
    assert cycle == ["n.Node", "n.Node"]


# --- recursive well-known types: cycle returned, flagged WKT-family ----------


def test_struct_embed_is_wkt_family():
    fds = descriptor_pb2.FileDescriptorSet()
    struct_pb2.DESCRIPTOR.CopyToProto(fds.file.add())
    f = fds.file.add()
    f.name, f.package, f.syntax = "u.proto", "u", "proto3"
    f.dependency.append("google/protobuf/struct.proto")
    holder = f.message_type.add()
    holder.name = "HasStruct"
    _msgfield(holder, "s", 1, ".google.protobuf.Struct")

    result = _find_recursive_cycle(_desc(fds, "u.HasStruct"))
    assert result is not None
    cycle, is_wkt = result
    assert is_wkt is True
    assert all(n.startswith("google.protobuf.") for n in cycle)


# --- acyclic shapes: no cycle -----------------------------------------------


def test_diamond_is_not_a_cycle():
    fds = descriptor_pb2.FileDescriptorSet()
    f = fds.file.add()
    f.name, f.package, f.syntax = "d.proto", "p", "proto3"
    for name, refs in (("A", ("B", "C")), ("B", ("D",)), ("C", ("D",))):
        m = f.message_type.add()
        m.name = name
        for i, ref in enumerate(refs, start=1):
            _msgfield(m, ref.lower(), i, f".p.{ref}")
    d = f.message_type.add()
    d.name = "D"
    x = d.field.add()
    x.name, x.number, x.type, x.label = "x", 1, F.TYPE_INT32, F.LABEL_OPTIONAL

    assert _find_recursive_cycle(_desc(fds, "p.A")) is None


def test_deep_finite_nesting_is_not_a_cycle():
    fds = descriptor_pb2.FileDescriptorSet()
    f = fds.file.add()
    f.name, f.package, f.syntax = "deep.proto", "p", "proto3"
    a = f.message_type.add()
    a.name = "A"
    _msgfield(a, "b", 1, ".p.B")
    b = f.message_type.add()
    b.name = "B"
    _msgfield(b, "c", 1, ".p.C")
    c = f.message_type.add()
    c.name = "C"
    x = c.field.add()
    x.name, x.number, x.type, x.label = "x", 1, F.TYPE_INT32, F.LABEL_OPTIONAL

    assert _find_recursive_cycle(_desc(fds, "p.A")) is None


def test_wide_diamond_terminates_without_blowup():
    # Each level has two message fields both pointing at the next level, so there
    # are 2**N acyclic root->leaf paths. Without the `acyclic` memo the walk
    # re-visits shared nodes once per path and hangs; with it the walk is O(V+E)
    # and returns immediately. This test's completion is the regression guard.
    fds = descriptor_pb2.FileDescriptorSet()
    f = fds.file.add()
    f.name, f.package, f.syntax = "diamond.proto", "p", "proto3"
    depth = 40
    for i in range(depth):
        m = f.message_type.add()
        m.name = f"L{i}"
        _msgfield(m, "a", 1, f".p.L{i + 1}")
        _msgfield(m, "b", 2, f".p.L{i + 1}")
    leaf = f.message_type.add()
    leaf.name = f"L{depth}"
    x = leaf.field.add()
    x.name, x.number, x.type, x.label = "x", 1, F.TYPE_INT32, F.LABEL_OPTIONAL

    assert _find_recursive_cycle(_desc(fds, "p.L0")) is None


def test_non_recursive_wkt_embed_is_not_a_cycle():
    fds = descriptor_pb2.FileDescriptorSet()
    timestamp_pb2.DESCRIPTOR.CopyToProto(fds.file.add())
    any_pb2.DESCRIPTOR.CopyToProto(fds.file.add())
    f = fds.file.add()
    f.name, f.package, f.syntax = "w.proto", "w", "proto3"
    f.dependency.append("google/protobuf/timestamp.proto")
    f.dependency.append("google/protobuf/any.proto")
    holder = f.message_type.add()
    holder.name = "Holder"
    _msgfield(holder, "t", 1, ".google.protobuf.Timestamp")
    _msgfield(holder, "a", 2, ".google.protobuf.Any")

    assert _find_recursive_cycle(_desc(fds, "w.Holder")) is None
