"""Contract tests for ``protokit._extensions`` — the custom-option seam (U5).

``desc.GetOptions()`` always returns an instance of a bootstrap
``descriptor_pb2`` options class, whose extension registry knows only the
default pool. An extension declared in any other pool — every descriptor set
loaded through ``protokit._pools`` — is refused by identity even when its full
name matches, so ``HasExtension`` / ``Extensions[]`` raise ``KeyError``. The
bytes are fine; only the class is wrong. ``rebind_options`` re-reads them
through the class of the options message the extension actually extends.

These tests pin that contract on the owner across all eight options types, so
a consumer inherits it rather than re-deriving it. Every pool here is built
with ``build_pool`` from a self-contained set; the default pool is not touched.
"""

from __future__ import annotations

import pytest
from google.protobuf import descriptor_pb2

from protokit._extensions import extends, rebind_options
from protokit._pools import build_pool, get_message_class

FD = descriptor_pb2.FieldDescriptorProto
_PKG = "pkextseam"

# (extension name, options message it extends, number)
_KINDS: tuple[tuple[str, str, int], ...] = (
    ("file_opt", "FileOptions", 68301),
    ("msg_opt", "MessageOptions", 68302),
    ("field_opt", "FieldOptions", 68303),
    ("oneof_opt", "OneofOptions", 68304),
    ("enum_opt", "EnumOptions", 68305),
    ("value_opt", "EnumValueOptions", 68306),
    ("svc_opt", "ServiceOptions", 68307),
    ("method_opt", "MethodOptions", 68308),
)


def _descriptor_proto_file() -> descriptor_pb2.FileDescriptorProto:
    fdp = descriptor_pb2.FileDescriptorProto()
    descriptor_pb2.DESCRIPTOR.CopyToProto(fdp)
    return fdp


def _extension_file() -> descriptor_pb2.FileDescriptorProto:
    extf = descriptor_pb2.FileDescriptorProto(
        name="pkextseam_ext.proto", package=_PKG, syntax="proto2",
    )
    extf.dependency.append("google/protobuf/descriptor.proto")
    for name, extendee, number in _KINDS:
        ext = extf.extension.add()
        ext.name, ext.number, ext.type = name, number, FD.TYPE_INT32
        ext.label = FD.LABEL_OPTIONAL
        ext.extendee = f".google.protobuf.{extendee}"
    return extf


def _build() -> dict[str, object]:
    """One annotated element of every options type, in an isolated pool.

    Each element carries its own option set to its extension number, so a
    value read back through the wrong element cannot pass by coincidence.
    """
    scratch_set = descriptor_pb2.FileDescriptorSet()
    scratch_set.file.extend([_descriptor_proto_file(), _extension_file()])
    scratch = build_pool(scratch_set)

    def annotate(options: object, ext_name: str, extendee: str, value: int) -> None:
        bound = get_message_class(scratch, f"google.protobuf.{extendee}")()
        bound.Extensions[scratch.FindExtensionByName(f"{_PKG}.{ext_name}")] = value
        options.MergeFromString(bound.SerializeToString())

    by_name = {name: (extendee, number) for name, extendee, number in _KINDS}

    def put(options: object, ext_name: str) -> None:
        extendee, number = by_name[ext_name]
        annotate(options, ext_name, extendee, number)

    target = descriptor_pb2.FileDescriptorProto(
        name="pkextseam_target.proto", package=_PKG, syntax="proto3",
    )
    target.dependency.append("pkextseam_ext.proto")
    put(target.options, "file_opt")
    msg = target.message_type.add()
    msg.name = "M"
    put(msg.options, "msg_opt")
    oneof = msg.oneof_decl.add()
    oneof.name = "choice"
    put(oneof.options, "oneof_opt")
    fld = msg.field.add()
    fld.name, fld.number, fld.type = "a", 1, FD.TYPE_INT32
    fld.label, fld.oneof_index = FD.LABEL_OPTIONAL, 0
    put(fld.options, "field_opt")
    bare = msg.field.add()
    bare.name, bare.number, bare.type = "bare", 2, FD.TYPE_INT32
    bare.label = FD.LABEL_OPTIONAL
    enum = target.enum_type.add()
    enum.name = "E"
    put(enum.options, "enum_opt")
    value = enum.value.add()
    value.name, value.number = "E_ZERO", 0
    put(value.options, "value_opt")
    svc = target.service.add()
    svc.name = "S"
    put(svc.options, "svc_opt")
    method = svc.method.add()
    method.name = "Call"
    method.input_type = method.output_type = f".{_PKG}.M"
    put(method.options, "method_opt")

    fds = descriptor_pb2.FileDescriptorSet()
    fds.file.extend([_descriptor_proto_file(), _extension_file(), target])
    pool = build_pool(fds)
    m = pool.FindMessageTypeByName(f"{_PKG}.M")
    e = pool.FindEnumTypeByName(f"{_PKG}.E")
    s = pool.FindServiceByName(f"{_PKG}.S")
    return {
        "pool": pool,
        "file_opt": pool.FindFileByName("pkextseam_target.proto"),
        "msg_opt": m,
        "oneof_opt": m.oneofs_by_name["choice"],
        "field_opt": m.fields_by_name["a"],
        "enum_opt": e,
        "value_opt": e.values_by_name["E_ZERO"],
        "svc_opt": s,
        "method_opt": s.FindMethodByName("Call"),
        "bare_field": m.fields_by_name["bare"],
    }


_FIXTURE = _build()
_POOL = _FIXTURE["pool"]
_KIND_IDS = [name for name, _, _ in _KINDS]


def _ext(name: str) -> object:
    return _POOL.FindExtensionByName(f"{_PKG}.{name}")


class TestRebindOptions:
    @pytest.mark.parametrize("ext_name", _KIND_IDS)
    def test_bootstrap_options_are_refused_by_identity(self, ext_name: str) -> None:
        """The premise: without the re-read, protobuf refuses the lookup.

        If a protobuf release ever makes this pass, the seam is no longer
        needed — and this test is the one that says so.
        """
        options = _FIXTURE[ext_name].GetOptions()
        with pytest.raises(KeyError):
            options.HasExtension(_ext(ext_name))

    @pytest.mark.parametrize("ext_name", _KIND_IDS)
    def test_rebound_options_resolve_every_options_type(self, ext_name: str) -> None:
        ext = _ext(ext_name)
        rebound = rebind_options(_FIXTURE[ext_name].GetOptions(), ext)
        assert rebound.HasExtension(ext)
        assert rebound.Extensions[ext] == ext.number

    def test_unset_extension_stays_absent(self) -> None:
        ext = _ext("field_opt")
        rebound = rebind_options(_FIXTURE["bare_field"].GetOptions(), ext)
        assert not rebound.HasExtension(ext)

    def test_already_bound_options_are_returned_as_is(self) -> None:
        """No copy when the class already knows the extension — the case
        for every generated ``_pb2`` and for options this seam produced.
        """
        ext = _ext("field_opt")
        rebound = rebind_options(_FIXTURE["field_opt"].GetOptions(), ext)
        assert rebind_options(rebound, ext) is rebound

    def test_input_options_are_not_mutated(self) -> None:
        options = _FIXTURE["field_opt"].GetOptions()
        before = options.SerializeToString()
        rebind_options(options, _ext("field_opt"))
        assert options.SerializeToString() == before
        assert type(options) is descriptor_pb2.FieldOptions

    def test_extension_of_another_options_type_raises(self) -> None:
        """A method option asked of a field's options is a caller error the
        lint rules surface as ``rule_exception`` — it must not read as absent
        there, and it must not re-read field bytes as method options.
        """
        with pytest.raises(KeyError, match=r"MethodOptions.*FieldOptions"):
            rebind_options(
                _FIXTURE["field_opt"].GetOptions(),
                _ext("method_opt"),
            )


class TestExtends:
    @pytest.mark.parametrize("ext_name", _KIND_IDS)
    def test_matches_only_its_own_options_type(self, ext_name: str) -> None:
        options = _FIXTURE[ext_name].GetOptions()
        for other in _KIND_IDS:
            assert extends(options, _ext(other)) is (other == ext_name), other


class TestConstructionGuard:
    """KTD2's guard for this seam is construction, and this pins it.

    "Builds a pool-bound options class" is not statically decidable —
    ``protokit._pools.get_message_class`` makes the same
    ``GetMessageClass`` call for ordinary message classes, so a name
    match would fire on it on day one. What *is* decidable is that
    nothing hands a caller the class: the builder is private here, and
    the lint package's helper module no longer offers one. A consumer
    that needs a custom option goes through :func:`rebind_options` or
    re-derives the whole construction from scratch, which no test can
    rule out and this one does not claim to.

    A re-export counts as offering the class: binding protobuf's
    ``GetMessageClass`` to a public name here hands it to every caller as
    surely as defining a builder would, so a callable is counted wherever
    it was defined. Only typing constructs, which build no messages, are
    left out.
    """

    @staticmethod
    def _public_functions(module: object) -> set[str]:
        return {
            name
            for name, value in vars(module).items()
            if not name.startswith("_")
            and callable(value)
            and getattr(value, "__module__", None) not in {"typing", "typing_extensions"}
        }

    def test_seam_exports_only_the_re_read(self) -> None:
        import protokit._extensions as seam

        assert self._public_functions(seam) == {"extends", "rebind_options"}

    def test_lint_helper_module_offers_no_options_class(self) -> None:
        import protokit.schema.lint._extension_access as lint_helpers

        assert self._public_functions(lint_helpers) == {
            "resolve_enum_value_for_comparison",
        }
