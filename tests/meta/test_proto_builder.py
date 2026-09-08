"""Tests for the ProtoBuilder test helper itself."""

import os
import subprocess
import sys
from pathlib import Path

from google.protobuf import descriptor_pb2, descriptor_pool

from tests.proto_builder import ProtoBuilder, wire_dependencies
from tests.schema.helpers import build_enum, build_message

_REPO_ROOT = Path(__file__).resolve().parents[2]
T = descriptor_pb2.FieldDescriptorProto


class TestProtoBuilderBasic:
    def test_simple_message(self) -> None:
        builder = ProtoBuilder()
        builder.message("test.Simple", {
            "name": (descriptor_pb2.FieldDescriptorProto.TYPE_STRING, 1),
            "age": (descriptor_pb2.FieldDescriptorProto.TYPE_INT32, 2),
        })
        msg = builder.build("test.Simple", name="Alice", age=30)
        assert msg.name == "Alice"
        assert msg.age == 30

    def test_nested_message(self) -> None:
        builder = ProtoBuilder()
        builder.message("test.Address", {
            "street": (descriptor_pb2.FieldDescriptorProto.TYPE_STRING, 1),
        })
        builder.message("test.Person", {
            "name": (descriptor_pb2.FieldDescriptorProto.TYPE_STRING, 1),
            "address": (descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE, 2, ".test.Address"),
        })
        addr = builder.build("test.Address", street="Main St")
        person = builder.build("test.Person", name="Alice")
        person.address.CopyFrom(addr)
        assert person.address.street == "Main St"

    def test_repeated_field(self) -> None:
        builder = ProtoBuilder()
        builder.message_with_repeated(
            "test.List",
            {"values": (descriptor_pb2.FieldDescriptorProto.TYPE_INT32, 1)},
            repeated_fields={"values"},
        )
        msg = builder.build("test.List")
        msg.values.append(1)
        msg.values.append(2)
        assert list(msg.values) == [1, 2]

    def test_map_field(self) -> None:
        builder = ProtoBuilder()
        builder.map_message(
            "test.Config",
            fields={},
            map_fields={
                "labels": (
                    descriptor_pb2.FieldDescriptorProto.TYPE_STRING,
                    descriptor_pb2.FieldDescriptorProto.TYPE_STRING,
                    1,
                ),
            },
        )
        msg = builder.build("test.Config")
        msg.labels["env"] = "prod"
        assert msg.labels["env"] == "prod"

    def test_separate_pools(self) -> None:
        """Messages from different pools are different Python types."""
        builder1 = ProtoBuilder()
        builder1.message("test.Msg", {
            "value": (descriptor_pb2.FieldDescriptorProto.TYPE_STRING, 1),
        })

        builder2 = ProtoBuilder()
        builder2.message("test.Msg", {
            "value": (descriptor_pb2.FieldDescriptorProto.TYPE_STRING, 1),
        })

        msg1 = builder1.build("test.Msg", value="hello")
        msg2 = builder2.build("test.Msg", value="hello")

        # Same logical content but different pools = different types
        assert type(msg1) is not type(msg2)
        assert msg1.value == msg2.value

    def test_enum_field(self) -> None:
        builder = ProtoBuilder()
        builder.message(
            "test.WithEnum",
            fields={
                "status": (descriptor_pb2.FieldDescriptorProto.TYPE_ENUM, 1, ".test.WithEnum.Status"),
            },
            enums={
                "Status": {"UNKNOWN": 0, "ACTIVE": 1, "INACTIVE": 2},
            },
        )
        msg = builder.build("test.WithEnum", status=1)
        assert msg.status == 1

    def test_oneof(self) -> None:
        builder = ProtoBuilder()
        builder.message(
            "test.WithOneof",
            fields={
                "str_val": (descriptor_pb2.FieldDescriptorProto.TYPE_STRING, 1),
                "int_val": (descriptor_pb2.FieldDescriptorProto.TYPE_INT32, 2),
            },
            oneofs={"value": ["str_val", "int_val"]},
        )
        msg = builder.build("test.WithOneof", str_val="hello")
        assert msg.HasField("str_val")
        assert msg.WhichOneof("value") == "str_val"


# ---------------------------------------------------------------------------
# Dependency wiring (KTD11 / U22)
# ---------------------------------------------------------------------------
#
# Every builder emits one ``FileDescriptorProto`` per message. A field whose
# ``type_name`` lives in an earlier file is a *cross-file* reference, and the
# pure-Python ``DescriptorPool`` resolves those only through the file's
# ``dependency`` list — upb resolves them from the whole pool and so hid the
# omission for the suite's entire life. ``wire_dependencies`` closes the gap
# by resolving each referent through the pool and recording its file.


class TestDependencyWiring:
    def test_cross_file_message_reference_records_dependency(self) -> None:
        """The KTD3 proof: a two-file builder pool names the referent's file.

        Without wiring, ``generated_2.proto`` has an empty ``dependencies``
        tuple under upb (which resolves the reference anyway) and raises
        ``KeyError`` under pure-Python (which does not).
        """
        builder = ProtoBuilder()
        builder.message("test.Address", {"street": (T.TYPE_STRING, 1)})
        builder.message(
            "test.Person",
            {"address": (T.TYPE_MESSAGE, 1, ".test.Address")},
        )
        person_file = builder.pool.FindFileByName("generated_2.proto")
        assert [d.name for d in person_file.dependencies] == ["generated_1.proto"]

    def test_same_file_reference_adds_no_dependency(self) -> None:
        builder = ProtoBuilder()
        builder.message(
            "test.WithEnum",
            fields={"status": (T.TYPE_ENUM, 1, ".test.WithEnum.Status")},
            enums={"Status": {"UNKNOWN": 0, "ACTIVE": 1}},
        )
        deps = builder.pool.FindFileByName("generated_1.proto").dependencies
        assert [d.name for d in deps] == []

    def test_shared_prepopulated_pool_resolves_hand_added_referent(self) -> None:
        """Resolution goes through the pool, never a builder-local file list."""
        pool = descriptor_pool.DescriptorPool()
        fp = descriptor_pb2.FileDescriptorProto(
            name="hand_made.proto", package="test", syntax="proto3",
        )
        fp.message_type.add().name = "Referent"
        pool.Add(fp)

        builder = ProtoBuilder(pool=pool)
        builder.message("test.User", {"ref": (T.TYPE_MESSAGE, 1, ".test.Referent")})
        user_file = pool.FindFileByName("generated_1.proto")
        assert [d.name for d in user_file.dependencies] == ["hand_made.proto"]

    def test_map_message_value_never_crosses_files(self) -> None:
        builder = ProtoBuilder()
        builder.map_message(
            "test.Config",
            fields={},
            map_fields={"labels": (T.TYPE_STRING, T.TYPE_STRING, 1)},
        )
        deps = builder.pool.FindFileByName("generated_1.proto").dependencies
        assert [d.name for d in deps] == []

    def test_build_message_wires_cross_file_reference(self) -> None:
        pool = descriptor_pool.DescriptorPool()
        build_message(pool, "t.Inner", fields=[
            {"name": "x", "number": 1, "type": T.TYPE_INT32},
        ], file_name="inner.proto")
        build_message(pool, "t.Outer", fields=[
            {"name": "inner", "number": 1, "type": T.TYPE_MESSAGE, "type_name": "t.Inner"},
        ], file_name="outer.proto")
        outer = pool.FindFileByName("outer.proto")
        assert [d.name for d in outer.dependencies] == ["inner.proto"]

    def test_build_enum_referent_resolves_through_find_enum_type_by_name(self) -> None:
        pool = descriptor_pool.DescriptorPool()
        build_enum(pool, "t.Color", {"RED": 0, "BLUE": 1}, file_name="color.proto")
        build_message(pool, "t.Paint", fields=[
            {"name": "color", "number": 1, "type": T.TYPE_ENUM, "type_name": "t.Color"},
        ], file_name="paint.proto")
        paint = pool.FindFileByName("paint.proto")
        assert [d.name for d in paint.dependencies] == ["color.proto"]

    def test_wire_dependencies_tolerates_unresolvable_referent(self) -> None:
        """A forward or same-file reference is a miss, not an error."""
        pool = descriptor_pool.DescriptorPool()
        fp = descriptor_pb2.FileDescriptorProto(name="fwd.proto", package="t")
        m = fp.message_type.add()
        m.name = "A"
        f = m.field.add()
        f.name, f.number, f.type, f.type_name = "b", 1, T.TYPE_MESSAGE, "t.NotYetThere"
        wire_dependencies(fp, pool)
        assert list(fp.dependency) == []

    def test_wire_dependencies_records_each_file_once(self) -> None:
        pool = descriptor_pool.DescriptorPool()
        build_message(pool, "t.A", file_name="ab.proto")
        build_message(pool, "t.B", file_name="ab2.proto")
        fp = descriptor_pb2.FileDescriptorProto(name="c.proto", package="t")
        m = fp.message_type.add()
        m.name = "C"
        for i, ref in enumerate(("t.A", "t.A", "t.B"), start=1):
            f = m.field.add()
            f.name, f.number, f.type, f.type_name = f"f{i}", i, T.TYPE_MESSAGE, ref
        wire_dependencies(fp, pool)
        assert list(fp.dependency) == ["ab.proto", "ab2.proto"]

    def test_cross_file_reference_resolves_under_pure_python(self) -> None:
        """The construction that used to raise ``KeyError`` on the pure-Python
        backend now resolves. Runs in a subprocess because the backend is
        chosen at import time; skipped only if the runtime cannot be forced.
        """
        script = (
            "from google.protobuf.internal import api_implementation\n"
            "assert api_implementation.Type() == 'python', api_implementation.Type()\n"
            "from google.protobuf import descriptor_pb2\n"
            "from tests.proto_builder import ProtoBuilder\n"
            "T = descriptor_pb2.FieldDescriptorProto\n"
            "b = ProtoBuilder()\n"
            "b.message('test.Address', {'street': (T.TYPE_STRING, 1)})\n"
            "b.message('test.Person', {'address': (T.TYPE_MESSAGE, 1, '.test.Address')})\n"
            "person = b.build('test.Person')\n"
            "person.address.street = 'Main St'\n"
            "print(person.address.street)\n"
        )
        env = dict(os.environ, PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION="python",
                   PYTHONPATH=str(_REPO_ROOT))
        result = subprocess.run(
            [sys.executable, "-c", script], cwd=_REPO_ROOT, env=env,
            capture_output=True, text=True, timeout=60, check=False,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "Main St"
