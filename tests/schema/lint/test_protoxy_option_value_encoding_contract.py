"""D6d U1 — protoxy custom-extension encoding regression contract.

Pins the Phase 0 verification findings as a permanent regression
test (per the plan's ADV-7 finding): if a future protobuf / protoxy
release changes how custom extensions surface on a dynamic-pool
options message, this test fails BEFORE downstream synthetic-rule
behavior silently regresses.

Pinned contract:

1. ``GetOptions().Extensions[ext_desc]`` raises ``KeyError`` for a
   dynamic-pool extension that was applied at the proto source
   level — the value is NOT directly accessible via the bootstrap-
   pool-bound options instance ``GetOptions()`` returns.
2. The serialized bytes from ``GetOptions().SerializeToString()`` DO
   carry the extension value; re-parsing those bytes through a
   pool-bound options class makes ``HasExtension(ext_desc)`` and
   ``Extensions[ext_desc]`` work with proto2 presence semantics.
3. ``pool.FindExtensionByName(name)`` raises ``KeyError`` for an
   unregistered extension name (NOT silently returning ``None``) —
   the synthetic-rule loader's KD-10 precheck pattern depends on
   this raising shape.
4. Per Python wire-type mapping after the re-parse:
   - ``string`` extension → ``str``
   - ``int32`` extension → ``int`` (signed)
   - ``bool`` extension → ``bool``
   - ``enum`` extension → ``int`` (the enum NUMBER, not identifier)
   The synthetic-rule closure translates enum integers to identifier
   strings via ``ext_desc.enum_type.values_by_number[value].name``.

Updating this test in lockstep with the synthetic-rule closure
implementation when protobuf / protoxy versions change is part of the
upgrade discipline.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from google.protobuf import message_factory

from protokit.schema.compile import compile_protos_to_result

EXTENSION_PROTO = """\
syntax = "proto2";

package contract;

import "google/protobuf/descriptor.proto";

extend google.protobuf.MethodOptions {
    optional string s_ext = 60001;
    optional int32 i_ext = 60002;
    optional bool b_ext = 60003;
    optional Level e_ext = 60004;
}

enum Level {
    LOW = 0;
    MID = 1;
    HIGH = 2;
}
"""

SERVICE_PROTO = """\
syntax = "proto3";

package contract;

import "contract/ext.proto";

service S {
    rpc Annotated(R) returns (R) {
        option (contract.s_ext) = "alpha";
        option (contract.i_ext) = -7;
        option (contract.b_ext) = true;
        option (contract.e_ext) = HIGH;
    }
    rpc Bare(R) returns (R);
}

message R { string a = 1; }
"""


@pytest.fixture
def compiled(tmp_path: Path):
    ext_path = tmp_path / "contract" / "ext.proto"
    svc_path = tmp_path / "contract" / "service.proto"
    ext_path.parent.mkdir(parents=True, exist_ok=True)
    ext_path.write_text(EXTENSION_PROTO)
    svc_path.write_text(SERVICE_PROTO)
    return compile_protos_to_result(
        paths=[ext_path, svc_path],
        proto_paths=[str(tmp_path)],
    )


class TestEncodingContract:
    """Pins the four contract clauses above."""

    def test_dynamic_pool_extensions_accessor_raises(self, compiled) -> None:
        """Clause 1: ``Extensions[ext_desc]`` on the bootstrap-pool-bound
        ``GetOptions()`` raises ``KeyError`` for the dynamic-pool
        extension descriptor.
        """
        pool = compiled.pool
        method = pool.FindServiceByName("contract.S").FindMethodByName("Annotated")
        ext_desc = pool.FindExtensionByName("contract.s_ext")
        options = method.GetOptions()
        with pytest.raises((KeyError, ValueError)):
            _ = options.Extensions[ext_desc]

    def test_serialized_bytes_carry_extension_data(self, compiled) -> None:
        """Clause 2 (precondition): the options message's serialized
        bytes are NON-EMPTY for annotated methods (the values are
        actually present in the wire format)."""
        pool = compiled.pool
        method = pool.FindServiceByName("contract.S").FindMethodByName("Annotated")
        serialized = method.GetOptions().SerializeToString()
        assert serialized  # non-empty

    def test_reparse_workaround_recovers_string_extension(self, compiled) -> None:
        pool = compiled.pool
        method = pool.FindServiceByName("contract.S").FindMethodByName("Annotated")
        options_desc = pool.FindMessageTypeByName("google.protobuf.MethodOptions")
        get_message_class = getattr(message_factory, "GetMessageClass", None)
        assert get_message_class is not None, (
            "protobuf < 5.26 lacks GetMessageClass; the fallback path "
            "in _custom_rules.py covers it but this regression test "
            "exercises the supported (5.26+) path."
        )
        cls = get_message_class(options_desc)
        parsed = cls()
        parsed.MergeFromString(method.GetOptions().SerializeToString())
        ext_desc = pool.FindExtensionByName("contract.s_ext")
        assert parsed.HasExtension(ext_desc)
        value = parsed.Extensions[ext_desc]
        assert value == "alpha"
        assert isinstance(value, str)

    def test_reparse_recovers_signed_int(self, compiled) -> None:
        pool = compiled.pool
        method = pool.FindServiceByName("contract.S").FindMethodByName("Annotated")
        options_desc = pool.FindMessageTypeByName("google.protobuf.MethodOptions")
        cls = message_factory.GetMessageClass(options_desc)
        parsed = cls()
        parsed.MergeFromString(method.GetOptions().SerializeToString())
        ext_desc = pool.FindExtensionByName("contract.i_ext")
        assert parsed.Extensions[ext_desc] == -7

    def test_reparse_recovers_bool(self, compiled) -> None:
        pool = compiled.pool
        method = pool.FindServiceByName("contract.S").FindMethodByName("Annotated")
        options_desc = pool.FindMessageTypeByName("google.protobuf.MethodOptions")
        cls = message_factory.GetMessageClass(options_desc)
        parsed = cls()
        parsed.MergeFromString(method.GetOptions().SerializeToString())
        ext_desc = pool.FindExtensionByName("contract.b_ext")
        value = parsed.Extensions[ext_desc]
        assert value is True
        assert isinstance(value, bool)

    def test_reparse_enum_returns_integer_number(self, compiled) -> None:
        """Clause 4: enum extensions return the enum NUMBER (int), not
        the identifier string. Closures must convert via
        ``enum_type.values_by_number[v].name``.
        """
        pool = compiled.pool
        method = pool.FindServiceByName("contract.S").FindMethodByName("Annotated")
        options_desc = pool.FindMessageTypeByName("google.protobuf.MethodOptions")
        cls = message_factory.GetMessageClass(options_desc)
        parsed = cls()
        parsed.MergeFromString(method.GetOptions().SerializeToString())
        ext_desc = pool.FindExtensionByName("contract.e_ext")
        value = parsed.Extensions[ext_desc]
        # HIGH = 2 per the .proto definition above.
        assert value == 2
        assert isinstance(value, int)
        # The identifier name is reachable via the enum descriptor:
        assert ext_desc.enum_type.values_by_number[value].name == "HIGH"

    def test_bare_method_has_extension_returns_false(self, compiled) -> None:
        """When the extension is NOT applied at the source, after re-
        parse ``HasExtension`` returns False (proto2 presence)."""
        pool = compiled.pool
        bare = pool.FindServiceByName("contract.S").FindMethodByName("Bare")
        options_desc = pool.FindMessageTypeByName("google.protobuf.MethodOptions")
        cls = message_factory.GetMessageClass(options_desc)
        parsed = cls()
        parsed.MergeFromString(bare.GetOptions().SerializeToString())
        ext_desc = pool.FindExtensionByName("contract.s_ext")
        assert not parsed.HasExtension(ext_desc)

    def test_find_extension_by_name_raises_on_unknown(
        self, compiled,
    ) -> None:
        """Clause 3: ``KeyError`` for an unregistered extension name.
        The KD-10 synthetic-rule precheck pattern depends on this
        shape (catch ``KeyError`` → emit ``custom_annotation_extension_unresolved``).
        """
        pool = compiled.pool
        with pytest.raises(KeyError):
            pool.FindExtensionByName("notinpool.totally.absent")
