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

import typing

import pytest
from google.protobuf import descriptor_pb2
from google.protobuf.message import DecodeError

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

    def test_invalid_utf8_string_option_raises_decode_error(self) -> None:
        """A proto3 string option holding invalid UTF-8 raises one type on
        both backends. Pure-python validates while parsing and raises
        ``UnicodeDecodeError``, upb raises ``DecodeError``; callers are told
        to expect the latter.
        """
        f = descriptor_pb2.FileDescriptorProto(
            name="pkextseam_utf8.proto", package=_PKG, syntax="proto3",
        )
        f.dependency.append("google/protobuf/descriptor.proto")
        ext = f.extension.add()
        ext.name, ext.number, ext.type = "text_opt", 68309, FD.TYPE_STRING
        ext.label, ext.extendee = FD.LABEL_OPTIONAL, ".google.protobuf.FieldOptions"
        fld = f.message_type.add(name="U").field.add()
        fld.name, fld.number, fld.type = "a", 1, FD.TYPE_INT32
        fld.label = FD.LABEL_OPTIONAL
        # 68309 as a length-delimited field holding the lone byte 0xff.
        fld.options.MergeFromString(bytes.fromhex("aaad2101ff"))
        fds = descriptor_pb2.FileDescriptorSet()
        fds.file.extend([_descriptor_proto_file(), f])
        pool = build_pool(fds)
        field = pool.FindMessageTypeByName(f"{_PKG}.U").fields_by_name["a"]
        with pytest.raises(DecodeError):
            rebind_options(
                field.GetOptions(), pool.FindExtensionByName(f"{_PKG}.text_opt"),
            )

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
    it was defined. Only ``typing.Any`` itself is left out, by identity: a
    ``typing`` alias can wrap a working builder, so the ``typing`` module
    is not an exemption.
    """

    @staticmethod
    def _public_functions(module: object) -> set[str]:
        return {
            name
            for name, value in vars(module).items()
            if not name.startswith("_")
            and callable(value)
            and value is not typing.Any
        }

    def test_seam_exports_only_the_re_read(self) -> None:
        import protokit._extensions as seam

        assert self._public_functions(seam) == {"extends", "options_of", "rebind_options"}

    def test_lint_helper_module_offers_no_options_class(self) -> None:
        import protokit.schema.lint._extension_access as lint_helpers

        assert self._public_functions(lint_helpers) == {
            "resolve_enum_value_for_comparison",
        }


# ---------------------------------------------------------------------------
# One malformed option cannot hide another (U7, R6/R7)
#
# ``rebind_options`` re-read an options message whole. A malformed option
# anywhere on the element (a string that is not UTF-8, a truncated record)
# failed that read, so every other option on the element became unreadable
# too. And a proto2 string option that is not UTF-8 came back as bytes on
# upb, where pure-Python refused it.
# ---------------------------------------------------------------------------


# Imported here, not at the top: published docs cite line numbers in this file.
import struct  # noqa: E402
import sys  # noqa: E402

from tests._pure_python_inventory import skip_under_pure_python  # noqa: E402
from tests.storage.proto_fixtures import encode_varint as _varint  # noqa: E402


def _record(number: int, wire_type: int, payload: bytes = b"") -> bytes:
    body = _varint(len(payload)) + payload if wire_type == 2 else payload
    return _varint(number << 3 | wire_type) + body


_SIBLING_PKG = "pkoptsibling"
# extension name -> (number, file, type, label, type_name)
_SIBLING_EXTS = {
    "text3": (68401, "pkoptsibling_p3.proto", FD.TYPE_STRING, FD.LABEL_OPTIONAL, None),
    "num_opt": (68402, "pkoptsibling_p3.proto", FD.TYPE_INT32, FD.LABEL_OPTIONAL, None),
    "text2": (68403, "pkoptsibling_p2.proto", FD.TYPE_STRING, FD.LABEL_OPTIONAL, None),
    "tags": (68404, "pkoptsibling_p2.proto", FD.TYPE_STRING, FD.LABEL_REPEATED, None),
    "info": (
        68405, "pkoptsibling_p2.proto", FD.TYPE_MESSAGE, FD.LABEL_OPTIONAL, f".{_SIBLING_PKG}.Info",
    ),
    "levels": (68406, "pkoptsibling_p2.proto", FD.TYPE_INT32, FD.LABEL_REPEATED, None),
    "ratio": (68408, "pkoptsibling_p2.proto", FD.TYPE_DOUBLE, FD.LABEL_OPTIONAL, None),
    "scale": (68409, "pkoptsibling_p2.proto", FD.TYPE_FLOAT, FD.LABEL_OPTIONAL, None),
    "tree": (
        68411, "pkoptsibling_p2.proto", FD.TYPE_MESSAGE, FD.LABEL_OPTIONAL, f".{_SIBLING_PKG}.Tree",
    ),
}


def _tree(depth: int) -> bytes:
    """A ``Tree`` with ``v = 7`` at the bottom of ``depth`` nested ``child`` messages."""
    body = _record(2, 0, b"\x07")
    for _ in range(depth):
        body = _record(1, 2, body)
    return body


# Past both parsers' limits. upb refuses more than 100 levels with DecodeError;
# pure-Python has no limit of its own and runs out of stack, so what it raises
# is RecursionError. Twice the interpreter's limit is past it from any caller.
_TOO_DEEP = 2 * sys.getrecursionlimit()
_BAD = b"\xff\xfe"
_SIBLING_FIELDS = {
    "bad3": _record(68401, 2, _BAD) + _record(68402, 0, b"\x07"),
    "bad2": _record(68403, 2, _BAD) + _record(68402, 0, b"\x07"),
    "bad_info": _record(68405, 2, _record(1, 2, _BAD)),
    "good_info": _record(68405, 2, _record(1, 2, b"ok")) + _record(68402, 0, b"\x07"),
    # Outer framing is valid, so the options message keeps these as opaque
    # bytes; only reading them as the extension's type fails.
    "truncated_info": _record(68405, 2, b"\x0a\x05ab") + _record(68402, 0, b"\x07"),
    # A packed repeated option whose second varint never ends.
    "truncated_levels": _record(68406, 2, b"\x01\xff") + _record(68402, 0, b"\x07"),
    # The re-read has to step over fixed-width records and nested groups to
    # reach the options after them; truncated_info sends it there.
    "beside_fixed": (
        _record(68408, 1, struct.pack("<d", 1.5)) + _record(68409, 5, struct.pack("<f", 0.5))
        + _record(68404, 2, b"a") + _record(68404, 2, b"b")
        + _record(68405, 2, b"\x0a\x05ab") + _record(68402, 0, b"\x07")
    ),
    "beside_nested_group": (
        _varint(68410 << 3 | 3) + _varint(1 << 3 | 3) + _record(2, 0, b"\x01")
        + _varint(1 << 3 | 4) + _varint(68410 << 3 | 4)
        + _record(68405, 2, b"\x0a\x05ab") + _record(68402, 0, b"\x07")
    ),
    "deep_tree": _record(68411, 2, _tree(_TOO_DEEP)) + _record(68402, 0, b"\x07"),
    "shallow_tree": _record(68411, 2, _tree(50)) + _record(68402, 0, b"\x07"),
}


def _sibling_pool() -> object:
    files: dict[str, descriptor_pb2.FileDescriptorProto] = {}
    for file_name, syntax in (
        ("pkoptsibling_p3.proto", "proto3"), ("pkoptsibling_p2.proto", "proto2"),
    ):
        f = descriptor_pb2.FileDescriptorProto(name=file_name, package=_SIBLING_PKG, syntax=syntax)
        f.dependency.append("google/protobuf/descriptor.proto")
        files[file_name] = f
    files["pkoptsibling_p2.proto"].message_type.add(name="Info").field.add(
        name="s", number=1, type=FD.TYPE_STRING, label=FD.LABEL_OPTIONAL,
    )
    tree = files["pkoptsibling_p2.proto"].message_type.add(name="Tree")
    tree.field.add(
        name="child", number=1, type=FD.TYPE_MESSAGE, label=FD.LABEL_OPTIONAL,
        type_name=f".{_SIBLING_PKG}.Tree",
    )
    tree.field.add(name="v", number=2, type=FD.TYPE_INT32, label=FD.LABEL_OPTIONAL)
    for name, (number, file_name, kind, label, type_name) in _SIBLING_EXTS.items():
        ext = files[file_name].extension.add()
        ext.name, ext.number, ext.type, ext.label = name, number, kind, label
        ext.extendee = ".google.protobuf.FieldOptions"
        if type_name:
            ext.type_name = type_name
    target = descriptor_pb2.FileDescriptorProto(
        name="pkoptsibling_t.proto", package=_SIBLING_PKG, syntax="proto3",
    )
    target.dependency.extend(["pkoptsibling_p3.proto", "pkoptsibling_p2.proto"])
    msg = target.message_type.add(name="M")
    for number, (field_name, raw) in enumerate(_SIBLING_FIELDS.items(), start=1):
        fld = msg.field.add(
            name=field_name, number=number, type=FD.TYPE_INT32, label=FD.LABEL_OPTIONAL,
        )
        fld.options.MergeFromString(raw)
    fds = descriptor_pb2.FileDescriptorSet()
    fds.file.extend([_descriptor_proto_file(), *files.values(), target])
    return build_pool(fds)


_SIBLING_POOL = _sibling_pool()


def _sibling_field(name: str) -> object:
    return _SIBLING_POOL.FindMessageTypeByName(f"{_SIBLING_PKG}.M").fields_by_name[name]


class TestOneMalformedOptionCannotHideAnother:
    @pytest.mark.parametrize(
        "field_name",
        [
            "bad3", "bad2", "good_info", "truncated_info", "truncated_levels",
            "beside_fixed", "beside_nested_group", "deep_tree", "shallow_tree",
        ],
    )
    def test_a_valid_option_reads_beside_a_malformed_one(self, field_name: str) -> None:
        from protokit.options import get_option_value

        value = get_option_value(
            _sibling_field(field_name), f"{_SIBLING_PKG}.num_opt", pool=_SIBLING_POOL,
        )
        assert value == 7

    @pytest.mark.parametrize(
        ("option", "expected"), [("ratio", 1.5), ("scale", 0.5), ("tags", ["a", "b"])],
    )
    def test_fixed_width_and_repeated_options_read_beside_a_malformed_one(
        self, option: str, expected: object,
    ) -> None:
        from protokit.options import get_option_value

        value = get_option_value(
            _sibling_field("beside_fixed"), f"{_SIBLING_PKG}.{option}", pool=_SIBLING_POOL,
        )
        assert (list(value) if option == "tags" else value) == expected

    @pytest.mark.parametrize(
        ("field_name", "option"),
        [
            ("bad3", "text3"), ("bad2", "text2"), ("bad_info", "info"), ("bad_info", "info.s"),
            ("truncated_info", "info"), ("truncated_levels", "levels"), ("deep_tree", "tree"),
        ],
    )
    def test_reading_the_malformed_option_raises_naming_it(
        self, field_name: str, option: str,
    ) -> None:
        from protokit.options import get_option_value

        with pytest.raises(DecodeError, match=f"{_SIBLING_PKG}.{option.split('.')[0]}"):
            get_option_value(
                _sibling_field(field_name), f"{_SIBLING_PKG}.{option}", pool=_SIBLING_POOL,
            )

    @pytest.mark.parametrize(
        "raw",
        [
            # Two tags, then a record whose varint value never ends.
            _record(68404, 2, b"a") + _record(68404, 2, b"b") + _varint(68402 << 3) + b"\xff",
            # One tag, then a record claiming 50 bytes that holds 2.
            _record(68404, 2, b"a") + _varint(68407 << 3 | 2) + b"\x32ab",
            # A group that never ends.
            _record(68404, 2, b"a") + _varint(68407 << 3 | 3) + _record(1, 0, b"\x01"),
            # An end-group marker with no group open.
            _varint(68407 << 3 | 4) + _record(68404, 2, b"a"),
            # Wire type 6 does not exist.
            _record(68404, 2, b"a") + _varint(68407 << 3 | 6),
        ],
        ids=[
            "value-runs-off-the-end", "length-past-the-end",
            "unterminated-group", "stray-end-group", "invalid-wire-type",
        ],
    )
    def test_a_framing_error_raises_instead_of_a_partial_repeated_value(self, raw: bytes) -> None:
        """Bytes no loader would hand over, so they go straight to the re-read."""
        from types import SimpleNamespace

        options = SimpleNamespace(
            DESCRIPTOR=descriptor_pb2.FieldOptions.DESCRIPTOR,
            SerializePartialToString=lambda: raw,
        )
        with pytest.raises(DecodeError):
            rebind_options(options, _SIBLING_POOL.FindExtensionByName(f"{_SIBLING_PKG}.tags"))

    def test_an_option_nested_within_both_parsers_limits_reads_whole(self) -> None:
        """The control for ``deep_tree``: depth alone does not fail a read."""
        from protokit.options import get_option_value

        node = get_option_value(
            _sibling_field("shallow_tree"), f"{_SIBLING_PKG}.tree", pool=_SIBLING_POOL,
        )
        for _ in range(50):
            assert node.HasField("child")
            node = node.child
        assert node.v == 7

    def test_an_option_the_element_does_not_set_still_reads_as_absent(self) -> None:
        from protokit.options import get_option_value

        value = get_option_value(
            _sibling_field("bad2"), f"{_SIBLING_PKG}.tags", pool=_SIBLING_POOL,
        )
        assert value is None

    @skip_under_pure_python(
        "premise holds only on upb: it parses a non-UTF-8 proto2 string and returns bytes, "
        "while the pure-Python parser rejects it before the options reach rebind_options"
    )
    def test_already_bound_options_holding_a_bad_proto2_string_raise(self) -> None:
        """The early return: options already of the extension's own class."""
        ext = _SIBLING_POOL.FindExtensionByName(f"{_SIBLING_PKG}.text2")
        bound = get_message_class(_SIBLING_POOL, "google.protobuf.FieldOptions")()
        bound.MergeFromString(_SIBLING_FIELDS["bad2"])
        with pytest.raises(DecodeError, match=f"{_SIBLING_PKG}.text2"):
            rebind_options(bound, ext)


def _private_walk_finds_bytes(msg: object) -> bool:
    from protokit._extensions import _holds_undecodable, _list_fields

    return any(_holds_undecodable(field, value) for field, value in _list_fields(msg))


def _walk_corpus() -> list[tuple[str, object]]:
    """Messages from the shared walk's own contract tests, clean and (on upb) bad."""
    import contextlib

    from tests.meta import test_fieldview_contract as contract

    pool = contract._walk_pool()
    root = get_message_class(pool, "w2.Root")
    ext = pool.FindExtensionByName("w2.ext")
    corpus: list[tuple[str, object]] = []
    for where, _field_name in contract._WALK_CASES:
        msg = root()
        contract._populate(msg, where, ext)
        wire = msg.SerializeToString()
        corpus.append((f"clean-{where}", root.FromString(wire)))
        # pure-Python rejects the bad bytes while parsing, so only upb adds these.
        with contextlib.suppress(Exception):
            bad = wire.replace(contract._MARKER, contract._BAD)
            corpus.append((f"bad-{where}", root.FromString(bad)))
    for name in contract._SHADOWING_MESSAGE_NAMES:
        cls = contract._shadowing_message_class(name)
        corpus.append((f"shadow-clean-{name}", cls.FromString(bytes.fromhex("0a040a026f6b"))))
        with contextlib.suppress(Exception):
            corpus.append((f"shadow-bad-{name}", cls.FromString(bytes.fromhex("0a030a01ff"))))
    return corpus


def test_the_private_walk_agrees_with_the_shared_one() -> None:
    """``_extensions`` keeps its own copy of the UTF-8 walk (it may not import
    ``_fieldview``); this holds the two in step on the shared walk's corpus.
    """
    from protokit._fieldview import first_undecodable_string

    corpus = _walk_corpus()
    assert corpus
    disagreements = [
        name for name, msg in corpus
        if _private_walk_finds_bytes(msg) != (first_undecodable_string(msg) is not None)
    ]
    assert disagreements == []


@pytest.mark.parametrize(
    "number", [0, (1 << 29)], ids=["zero", "past-the-maximum"],
)
def test_the_record_splitter_rejects_an_out_of_range_field_number(number: int) -> None:
    """upb's parser refuses these; pure-Python's accepts them, so test the splitter itself."""
    from protokit._extensions import _records

    with pytest.raises(DecodeError, match="out of range"):
        _records(_record(68404, 2, b"a") + _varint(number << 3) + b"\x00")


# ---------------------------------------------------------------------------
# A closed enum option holding a number its enum does not declare
#
# upb marks a singular closed-enum extension present, with value 0, before it
# sets the undeclared number aside; pure-Python leaves the option absent.
# ---------------------------------------------------------------------------

_ENUM_PKG = "pkoptenum"
# extension name -> (number, file, type, label, type_name)
_ENUM_EXTS = {
    "with_zero": (
        68801, "pkoptenum_p2.proto", FD.TYPE_ENUM, FD.LABEL_OPTIONAL, f".{_ENUM_PKG}.WithZero",
    ),
    "no_zero": (
        68802, "pkoptenum_p2.proto", FD.TYPE_ENUM, FD.LABEL_OPTIONAL, f".{_ENUM_PKG}.NoZero",
    ),
    "negative": (
        68803, "pkoptenum_p2.proto", FD.TYPE_ENUM, FD.LABEL_OPTIONAL, f".{_ENUM_PKG}.Negative",
    ),
    "no_zero_list": (
        68804, "pkoptenum_p2.proto", FD.TYPE_ENUM, FD.LABEL_REPEATED, f".{_ENUM_PKG}.NoZero",
    ),
    "open": (68805, "pkoptenum_p3.proto", FD.TYPE_ENUM, FD.LABEL_OPTIONAL, f".{_ENUM_PKG}.Open"),
    "text3": (68806, "pkoptenum_p3.proto", FD.TYPE_STRING, FD.LABEL_OPTIONAL, None),
}
# enum name -> (file, declared numbers)
_ENUMS = {
    "WithZero": ("pkoptenum_p2.proto", (0, 1, 2)),
    "NoZero": ("pkoptenum_p2.proto", (1, 2)),
    "Negative": ("pkoptenum_p2.proto", (1, -2)),
    "Open": ("pkoptenum_p3.proto", (0, 1)),
}


def _enum_record(option: str, number: int, *, width: int = 64) -> bytes:
    """One varint record of ``option`` holding ``number``, in two's complement of ``width`` bits."""
    return _record(_ENUM_EXTS[option][0], 0, _varint(number % (1 << width)))


# field name -> the option it carries and its records
_ENUM_FIELDS = {
    "with_zero_9": ("with_zero", _enum_record("with_zero", 9)),
    "with_zero_0_9": ("with_zero", _enum_record("with_zero", 0) + _enum_record("with_zero", 9)),
    "with_zero_2_9": ("with_zero", _enum_record("with_zero", 2) + _enum_record("with_zero", 9)),
    "with_zero_9_2": ("with_zero", _enum_record("with_zero", 9) + _enum_record("with_zero", 2)),
    "no_zero_9": ("no_zero", _enum_record("no_zero", 9)),
    "negative_ten_bytes": ("negative", _enum_record("negative", -2)),
    "negative_five_bytes": ("negative", _enum_record("negative", -2, width=32)),
    "no_zero_9_beside_bad_text": (
        "no_zero", _record(68806, 2, _BAD) + _enum_record("no_zero", 9),
    ),
    "open_9": ("open", _enum_record("open", 9)),
    "with_zero_9_then_length_delimited": (
        "with_zero", _enum_record("with_zero", 9) + _record(68801, 2, b"\x02"),
    ),
    "no_zero_list_1_9_2": (
        "no_zero_list",
        _enum_record("no_zero_list", 1) + _enum_record("no_zero_list", 9)
        + _enum_record("no_zero_list", 2),
    ),
}


def _enum_pool() -> object:
    files: dict[str, descriptor_pb2.FileDescriptorProto] = {}
    for file_name, syntax in (("pkoptenum_p2.proto", "proto2"), ("pkoptenum_p3.proto", "proto3")):
        f = descriptor_pb2.FileDescriptorProto(name=file_name, package=_ENUM_PKG, syntax=syntax)
        f.dependency.append("google/protobuf/descriptor.proto")
        files[file_name] = f
    for enum_name, (file_name, numbers) in _ENUMS.items():
        enum = files[file_name].enum_type.add(name=enum_name)
        for number in numbers:
            value_name = f"{enum_name.upper()}_{number}".replace("-", "MINUS_")
            enum.value.add(name=value_name, number=number)
    for name, (number, file_name, kind, label, type_name) in _ENUM_EXTS.items():
        ext = files[file_name].extension.add()
        ext.name, ext.number, ext.type, ext.label = name, number, kind, label
        ext.extendee = ".google.protobuf.FieldOptions"
        if type_name:
            ext.type_name = type_name
    target = descriptor_pb2.FileDescriptorProto(
        name="pkoptenum_t.proto", package=_ENUM_PKG, syntax="proto3",
    )
    target.dependency.extend(files)
    msg = target.message_type.add(name="M")
    for number, (field_name, (_option, raw)) in enumerate(_ENUM_FIELDS.items(), start=1):
        fld = msg.field.add(
            name=field_name, number=number, type=FD.TYPE_INT32, label=FD.LABEL_OPTIONAL,
        )
        fld.options.MergeFromString(raw)
        # A varint record of another number holding 1, which every closed enum here declares.
        fld.options.deprecated = True
    fds = descriptor_pb2.FileDescriptorSet()
    fds.file.extend([_descriptor_proto_file(), *files.values(), target])
    return build_pool(fds)


_ENUM_POOL = _enum_pool()

# (field name, what its option reads as; ``None`` is absent)
_ENUM_READS = [
    ("with_zero_9", None),
    ("with_zero_0_9", 0),
    ("with_zero_2_9", 2),
    ("with_zero_9_2", 2),
    ("no_zero_9", None),
    ("negative_ten_bytes", -2),
    ("negative_five_bytes", -2),
    ("no_zero_9_beside_bad_text", None),
    ("open_9", 9),
    ("with_zero_9_then_length_delimited", None),
]


class TestAClosedEnumOptionHoldingAnUndeclaredNumber:
    """It reads as absent unless a record of it holds a number the enum declares.

    ``with_zero_9`` is the shape a look at the value read cannot settle: upb's 0
    is a number ``WithZero`` declares, and its message for ``[9]`` is the one it
    builds for ``[0, 9]``. The open (proto3) enum and the repeated option have
    no such split, and read as they did.
    """

    @staticmethod
    def _field_and_extension(field_name: str) -> tuple[object, object]:
        field = _ENUM_POOL.FindMessageTypeByName(f"{_ENUM_PKG}.M").fields_by_name[field_name]
        option = _ENUM_FIELDS[field_name][0]
        return field, _ENUM_POOL.FindExtensionByName(f"{_ENUM_PKG}.{option}")

    @pytest.mark.parametrize(("field_name", "expected"), _ENUM_READS)
    def test_get_option_value_reads_it(self, field_name: str, expected: int | None) -> None:
        from protokit.options import get_option_value

        field, ext = self._field_and_extension(field_name)
        assert get_option_value(field, ext.full_name) == expected

    @pytest.mark.parametrize(("field_name", "expected"), _ENUM_READS)
    def test_the_re_read_holds_it(self, field_name: str, expected: int | None) -> None:
        from protokit._extensions import options_of

        field, ext = self._field_and_extension(field_name)
        options = rebind_options(options_of(field), ext)
        assert options.HasExtension(ext) is (expected is not None)
        if expected is not None:
            assert options.Extensions[ext] == expected

    def test_a_repeated_option_keeps_its_declared_numbers(self) -> None:
        from protokit._extensions import options_of
        from protokit.options import get_option_value

        field, ext = self._field_and_extension("no_zero_list_1_9_2")
        assert list(get_option_value(field, ext.full_name)) == [1, 2]
        assert list(rebind_options(options_of(field), ext).Extensions[ext]) == [1, 2]


def test_bytes_the_record_splitter_refuses_keep_what_the_runtime_read() -> None:
    """Pure-Python reads past an end-group marker of another number; _records does not."""
    from types import SimpleNamespace

    from protokit._extensions import _records
    from tests._pure_python_inventory import runtime_backend

    ext = _ENUM_POOL.FindExtensionByName(f"{_ENUM_PKG}.no_zero")
    raw = _enum_record("no_zero", 2) + _varint(7000 << 3 | 3) + _varint(7001 << 3 | 4)
    with pytest.raises(DecodeError, match="end-group"):
        _records(raw)
    options = SimpleNamespace(
        DESCRIPTOR=descriptor_pb2.FieldOptions.DESCRIPTOR, SerializePartialToString=lambda: raw,
    )
    if runtime_backend() != "python":
        with pytest.raises(DecodeError):
            rebind_options(options, ext)
        pytest.skip("upb refuses these bytes itself, so the re-read never holds a value")
    assert rebind_options(options, ext).Extensions[ext] == 2


# Runs in a child process: where the refusal is missing, upb ends the interpreter.
_MAP_ENTRY_EXTENSION = r"""
import json
import sys
from pathlib import Path

from click.testing import CliRunner
from google.protobuf import descriptor_pb2 as d
from google.protobuf.message import DecodeError

from protokit._extensions import options_of, rebind_options
from protokit._pools import build_pool
from protokit.options import get_option_value
from protokit.schema.lint.cli import main as lint_main

F = d.FieldDescriptorProto
ext_file = d.FileDescriptorProto(
    name="ph/ext.proto", package="ph", syntax="proto2",
    dependency=["google/protobuf/descriptor.proto"],
)
entry = ext_file.message_type.add(name="LabelsEntry")
entry.options.map_entry = True
for name, number in (("key", 1), ("value", 2)):
    entry.field.add(name=name, number=number, type=F.TYPE_STRING, label=F.LABEL_OPTIONAL)
ext_file.extension.add(
    name="labels", number=76001, type=F.TYPE_MESSAGE, label=F.LABEL_REPEATED,
    type_name=".ph.LabelsEntry", extendee=".google.protobuf.FieldOptions",
)
ext_file.extension.add(
    name="num", number=76002, type=F.TYPE_INT32, label=F.LABEL_OPTIONAL,
    extendee=".google.protobuf.FieldOptions",
)
user = d.FileDescriptorProto(
    name="ph/user.proto", package="ph", syntax="proto3", dependency=["ph/ext.proto"],
)
field = user.message_type.add(name="M").field.add(
    name="x", number=1, type=F.TYPE_INT32, label=F.LABEL_OPTIONAL,
)
# (ph.labels) = { key: "k" value: "v" }, then (ph.num) = 7
field.options.MergeFromString(bytes.fromhex("8a8e25060a016b120176") + bytes.fromhex("908e2507"))
# One level down: (ph.rules) = { max: 5 [ph.inner]: { key: "k" value: "v" } }
rules = ext_file.message_type.add(name="Rules")
rules.field.add(name="max", number=1, type=F.TYPE_INT32, label=F.LABEL_OPTIONAL)
rules.extension_range.add(start=100, end=200)
ext_file.extension.add(
    name="rules", number=76003, type=F.TYPE_MESSAGE, label=F.LABEL_OPTIONAL,
    type_name=".ph.Rules", extendee=".google.protobuf.FieldOptions",
)
ext_file.extension.add(
    name="inner", number=100, type=F.TYPE_MESSAGE, label=F.LABEL_REPEATED,
    type_name=".ph.LabelsEntry", extendee=".ph.Rules",
)
nested = user.message_type[0].field.add(
    name="y", number=2, type=F.TYPE_INT32, label=F.LABEL_OPTIONAL,
)
# tag 76003 wire 2 = 9a 8e 25; body = max 5 (08 05) + inner (a2 06, 6 bytes)
nested.options.MergeFromString(bytes.fromhex("9a8e250b0805a206060a016b120176"))
user.message_type[0].field.add(name="bare", number=3, type=F.TYPE_INT32, label=F.LABEL_OPTIONAL)
fds = d.FileDescriptorSet()
fds.file.add().ParseFromString(d.DESCRIPTOR.serialized_pb)
fds.file.extend([ext_file, user])
pool = build_pool(fds)
fields = pool.FindMessageTypeByName("ph.M").fields_by_name
x, y, bare = fields["x"], fields["y"], fields["bare"]
labels = pool.FindExtensionByName("ph.labels")


def outcome(read):
    try:
        return ["value", repr(read())]
    except DecodeError as exc:
        return ["DecodeError", str(exc)]


scratch = Path(sys.argv[1])
(scratch / "set.binpb").write_bytes(fds.SerializeToString())
(scratch / "pyproject.toml").write_text(
    "[[tool.protokit.lint.custom_annotation_rules]]\n"
    'rule_suffix = "labels"\noption = "ph.labels"\nelement_kinds = ["field"]\n'
    'severity = "error"\n'
)
lint = CliRunner().invoke(lint_main, [
    str(scratch / "set.binpb"), "--no-builtin-rules",
    "--config", str(scratch / "pyproject.toml"), "--format", "json",
])
print(json.dumps({
    "re_read": outcome(lambda: rebind_options(options_of(x), labels)),
    "read": outcome(lambda: get_option_value(x, "ph.labels")),
    "another_option": outcome(lambda: get_option_value(x, "ph.num")),
    "not_carried": outcome(lambda: get_option_value(bare, "ph.labels")),
    "one_level_down": outcome(lambda: get_option_value(y, "ph.rules")),
    "beside_one_level_down": outcome(lambda: get_option_value(y, "ph.rules.max")),
    "lint_exit": lint.exit_code,
    "lint_says": "rule_exception" in lint.output,
}))
"""


def test_an_extension_typed_as_a_map_entry_is_refused_on_both_backends() -> None:
    """Protobuf has no map extensions, but a descriptor set can declare one.

    Both runtimes build the pool. Reading the option is refused by name, and so
    is an option whose message holds one. The element's other options still
    read, an element that does not carry the option reads it as absent, and
    ``lint`` reports the rule could not run instead of dying.
    """
    import json
    import os
    import subprocess
    import tempfile
    from pathlib import Path

    src = Path(__file__).resolve().parents[2] / "src"
    with tempfile.TemporaryDirectory() as scratch:
        result = subprocess.run(
            [sys.executable, "-c", _MAP_ENTRY_EXTENSION, scratch],
            capture_output=True, text=True, check=False, timeout=300,
            env={**os.environ, "PYTHONPATH": str(src)},
        )
    assert result.returncode == 0, result.stderr[-2000:]
    seen = json.loads(result.stdout.strip().splitlines()[-1])
    assert seen["re_read"][0] == "DecodeError" and "ph.labels" in seen["re_read"][1]
    assert seen["read"][0] == "DecodeError" and "ph.labels" in seen["read"][1]
    assert seen["another_option"] == ["value", "7"]
    assert seen["not_carried"] == ["value", "None"]
    for read in ("one_level_down", "beside_one_level_down"):
        assert seen[read][0] == "DecodeError" and "ph.inner" in seen[read][1]
    assert (seen["lint_exit"], seen["lint_says"]) == (2, True)

