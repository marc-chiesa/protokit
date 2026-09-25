"""Unit tests for ``protokit.options.get_option_value``.

Tier 1 (``Extensions[]``) runs against two kinds of pool, because
they fail differently. ``TestExtensionPresence`` registers its
extensions in the DEFAULT pool — what a generated ``_pb2`` does on
import. ``TestIsolatedPool`` builds a self-contained
``FileDescriptorSet`` into a fresh pool with ``build_pool``, which is
what every descriptor-set-loaded schema gets: there ``GetOptions()``
still returns the bootstrap ``FieldOptions`` class, which refuses an
isolated-pool extension by identity, so tier 1 engages only through
``protokit._extensions`` (V9: before it, every such option read as
``None``, indistinguishable from an absent one).

Tier 2 (``uninterpreted_option``) is what we get when building a
``FieldDescriptorProto`` programmatically, so we can exercise it
directly.
"""

from __future__ import annotations

from google.protobuf import descriptor_pb2, descriptor_pool, message_factory

from protokit._pools import build_pool
from protokit.options import get_option_value

FD = descriptor_pb2.FieldDescriptorProto


def _build_field_with_uninterp_option(
    *,
    option_name_parts: list[tuple[str, bool]],
    value_field: str,
    value: object,
) -> tuple[descriptor_pool.DescriptorPool, object]:
    """Build ``M { int32 x = 1 [(<option>) = <value>] }`` with the
    option left as ``uninterpreted_option`` (tier-2 path).

    Returns the pool and the resolved ``FieldDescriptor`` for
    ``M.x``.
    """
    pool = descriptor_pool.DescriptorPool()
    fdp = descriptor_pb2.FileDescriptorProto(
        name=f"uopt_{id(value):x}.proto", package="t", syntax="proto3",
    )
    mp = fdp.message_type.add()
    mp.name = "M"
    fp = mp.field.add()
    fp.name, fp.number, fp.type = "x", 1, FD.TYPE_INT32
    fp.label = FD.LABEL_OPTIONAL
    uo = fp.options.uninterpreted_option.add()
    for name_part, is_ext in option_name_parts:
        uo.name.add(name_part=name_part, is_extension=is_ext)
    # string_value is ``bytes`` in the descriptor proto; allow the
    # caller to pass the right type.
    setattr(uo, value_field, value)
    pool.Add(fdp)
    return pool, pool.FindMessageTypeByName("t.M").fields_by_name["x"]


_PRESENCE_PKG = "pkoptpresence"
_PRESENCE_PKG3 = "pkoptpresence3"


def _build_presence_fixtures() -> dict[str, object]:
    """Register tier-1 extensions in the DEFAULT pool and return the
    ``fields_by_name`` mapping of a message whose fields carry them
    in every present/absent combination.

    Everything is namespaced and the extension numbers are
    distinctive, so this one-time global registration can't collide
    with anything else the suite loads.
    """
    pool = descriptor_pool.Default()

    extf = descriptor_pb2.FileDescriptorProto(
        name="pkoptpresence_ext.proto",
        package=_PRESENCE_PKG,
        syntax="proto2",
    )
    extf.dependency.append("google/protobuf/descriptor.proto")
    # A non-zero ``default_value`` makes the absent-vs-default
    # distinction visible: a leaked default reads as 7, never as a
    # value any test sets explicitly.
    limit = extf.extension.add()
    limit.name, limit.number, limit.type = "limit", 68101, FD.TYPE_INT32
    limit.label = FD.LABEL_OPTIONAL
    limit.extendee = ".google.protobuf.FieldOptions"
    limit.default_value = "7"
    tags = extf.extension.add()
    tags.name, tags.number, tags.type = "tags", 68102, FD.TYPE_STRING
    tags.label = FD.LABEL_REPEATED
    tags.extendee = ".google.protobuf.FieldOptions"
    cfg_msg = extf.message_type.add()
    cfg_msg.name = "Cfg"
    depth = cfg_msg.field.add()
    depth.name, depth.number, depth.type = "depth", 1, FD.TYPE_INT32
    depth.label = FD.LABEL_OPTIONAL
    depth.default_value = "5"
    cfg = extf.extension.add()
    cfg.name, cfg.number, cfg.type = "cfg", 68103, FD.TYPE_MESSAGE
    cfg.label = FD.LABEL_OPTIONAL
    cfg.extendee = ".google.protobuf.FieldOptions"
    cfg.type_name = f".{_PRESENCE_PKG}.Cfg"
    pool.Add(extf)

    # Extensions track presence in proto3 too, so the proto3 arm gets
    # the same treatment as the proto2 one.
    extf3 = descriptor_pb2.FileDescriptorProto(
        name="pkoptpresence_ext3.proto",
        package=_PRESENCE_PKG3,
        syntax="proto3",
    )
    extf3.dependency.append("google/protobuf/descriptor.proto")
    flag = extf3.extension.add()
    flag.name, flag.number, flag.type = "flag", 68104, FD.TYPE_INT32
    flag.label = FD.LABEL_OPTIONAL
    flag.extendee = ".google.protobuf.FieldOptions"
    pool.Add(extf3)

    ext_limit = pool.FindExtensionByName(f"{_PRESENCE_PKG}.limit")
    ext_tags = pool.FindExtensionByName(f"{_PRESENCE_PKG}.tags")
    ext_cfg = pool.FindExtensionByName(f"{_PRESENCE_PKG}.cfg")

    msgf = descriptor_pb2.FileDescriptorProto(
        name="pkoptpresence_msg.proto",
        package=_PRESENCE_PKG,
        syntax="proto3",
    )
    msgf.dependency.extend(
        ["pkoptpresence_ext.proto", "pkoptpresence_ext3.proto"],
    )
    mp = msgf.message_type.add()
    mp.name = "M"

    def _add_field(name: str, number: int) -> descriptor_pb2.FieldDescriptorProto:
        fp = mp.field.add()
        fp.name, fp.number, fp.type = name, number, FD.TYPE_INT32
        fp.label = FD.LABEL_OPTIONAL
        return fp

    _add_field("bare", 1)
    _add_field("annotated", 2).options.Extensions[ext_limit] = 42
    _add_field("zeroed", 3).options.Extensions[ext_limit] = 0
    _add_field("tagged", 4).options.Extensions[ext_tags].append("a")
    _add_field("configured", 5).options.Extensions[ext_cfg].depth = 9
    _add_field("configured_empty", 6).options.Extensions[ext_cfg].SetInParent()
    pool.Add(msgf)

    return pool.FindMessageTypeByName(f"{_PRESENCE_PKG}.M").fields_by_name


_PRESENCE_FIELDS = _build_presence_fixtures()


class TestExtensionPresence:
    """Tier-1 presence: a registered-but-unset extension is ABSENT.

    Callers gate on ``get_option_value(...) is not None``, so leaking
    the type default for an unset extension would fire a hook on
    every unannotated field in a schema.
    """

    def test_absent_scalar_extension_returns_none(self) -> None:
        assert get_option_value(
            _PRESENCE_FIELDS["bare"], f"{_PRESENCE_PKG}.limit",
        ) is None

    def test_present_scalar_extension_returns_value(self) -> None:
        assert get_option_value(
            _PRESENCE_FIELDS["annotated"], f"{_PRESENCE_PKG}.limit",
        ) == 42

    def test_explicit_zero_is_not_mistaken_for_absent(self) -> None:
        """The guard is presence, not truthiness: an explicit 0 that
        differs from the declared default still reads as set.
        """
        assert get_option_value(
            _PRESENCE_FIELDS["zeroed"], f"{_PRESENCE_PKG}.limit",
        ) == 0

    def test_absent_proto3_scalar_extension_returns_none(self) -> None:
        """Extensions carry explicit presence even under proto3."""
        assert get_option_value(
            _PRESENCE_FIELDS["bare"], f"{_PRESENCE_PKG3}.flag",
        ) is None

    def test_absent_repeated_extension_returns_none(self) -> None:
        """``HasExtension`` is unsupported for repeated extensions —
        emptiness is the only absence signal there.
        """
        assert get_option_value(
            _PRESENCE_FIELDS["bare"], f"{_PRESENCE_PKG}.tags",
        ) is None

    def test_present_repeated_extension_returns_values(self) -> None:
        assert list(
            get_option_value(
                _PRESENCE_FIELDS["tagged"], f"{_PRESENCE_PKG}.tags",
            ),
        ) == ["a"]

    def test_absent_message_extension_returns_none(self) -> None:
        assert get_option_value(
            _PRESENCE_FIELDS["bare"], f"{_PRESENCE_PKG}.cfg",
        ) is None

    def test_absent_message_extension_sub_path_returns_none(self) -> None:
        """The sub-field's own default must not leak either."""
        assert get_option_value(
            _PRESENCE_FIELDS["bare"], f"{_PRESENCE_PKG}.cfg.depth",
        ) is None

    def test_present_message_extension_sub_path_returns_value(self) -> None:
        assert get_option_value(
            _PRESENCE_FIELDS["configured"], f"{_PRESENCE_PKG}.cfg.depth",
        ) == 9

    def test_present_empty_message_extension_yields_sub_field_default(
        self,
    ) -> None:
        """Presence is the extension's, not the sub-field's: an
        explicitly-set empty ``Cfg`` is present, so its sub-field
        reads as the declared proto2 default.
        """
        assert get_option_value(
            _PRESENCE_FIELDS["configured_empty"],
            f"{_PRESENCE_PKG}.cfg.depth",
        ) == 5


_ISO_PKG = "pkoptiso"


def _isolated_extension_file() -> descriptor_pb2.FileDescriptorProto:
    """``pkoptiso_ext.proto``: custom options on two options types.

    Five ``FieldOptions`` extensions cover the value shapes tier 1
    returns (int, string, repeated, message, and a sub-field of that
    message); ``mopt`` extends ``MethodOptions`` instead, so a field
    can be asked for an option its options type never carries.
    """
    extf = descriptor_pb2.FileDescriptorProto(
        name="pkoptiso_ext.proto", package=_ISO_PKG, syntax="proto2",
    )
    extf.dependency.append("google/protobuf/descriptor.proto")
    cfg_msg = extf.message_type.add()
    cfg_msg.name = "Cfg"
    depth = cfg_msg.field.add()
    depth.name, depth.number, depth.type = "depth", 1, FD.TYPE_INT32
    depth.label = FD.LABEL_OPTIONAL
    for name, number, ftype, label, extendee in (
        ("limit", 68201, FD.TYPE_INT32, FD.LABEL_OPTIONAL, "FieldOptions"),
        ("label", 68202, FD.TYPE_STRING, FD.LABEL_OPTIONAL, "FieldOptions"),
        ("tags", 68203, FD.TYPE_STRING, FD.LABEL_REPEATED, "FieldOptions"),
        ("cfg", 68204, FD.TYPE_MESSAGE, FD.LABEL_OPTIONAL, "FieldOptions"),
        ("mopt", 68205, FD.TYPE_INT32, FD.LABEL_OPTIONAL, "MethodOptions"),
    ):
        ext = extf.extension.add()
        ext.name, ext.number, ext.type, ext.label = name, number, ftype, label
        ext.extendee = f".google.protobuf.{extendee}"
        if ftype == FD.TYPE_MESSAGE:
            ext.type_name = f".{_ISO_PKG}.Cfg"
    return extf


def _descriptor_proto_file() -> descriptor_pb2.FileDescriptorProto:
    fdp = descriptor_pb2.FileDescriptorProto()
    descriptor_pb2.DESCRIPTOR.CopyToProto(fdp)
    return fdp


def _build_isolated_fixtures() -> tuple[
    descriptor_pool.DescriptorPool, dict[str, object],
]:
    """Build a self-contained ``FileDescriptorSet`` into a fresh pool.

    Nothing touches the default pool: ``descriptor.proto`` travels in
    the set, as it does in a ``protoc --include_imports`` output, and
    ``build_pool`` builds every file into a brand-new pool. The
    annotations are written through a class bound to a scratch pool
    holding the same extension file, then carried into the message
    file as serialized options bytes — the only form in which a
    descriptor set can hold them.
    """
    scratch_set = descriptor_pb2.FileDescriptorSet()
    scratch_set.file.extend([_descriptor_proto_file(), _isolated_extension_file()])
    scratch = build_pool(scratch_set)
    options_cls = message_factory.GetMessageClass(
        scratch.FindMessageTypeByName("google.protobuf.FieldOptions"),
    )

    def _annotated(**values: object) -> bytes:
        opts = options_cls()
        for name, value in values.items():
            ext = scratch.FindExtensionByName(f"{_ISO_PKG}.{name}")
            if name == "tags":
                opts.Extensions[ext].extend(value)
            elif name == "cfg":
                opts.Extensions[ext].depth = value
            else:
                opts.Extensions[ext] = value
        return bytes(opts.SerializeToString())

    msgf = descriptor_pb2.FileDescriptorProto(
        name="pkoptiso_msg.proto", package=_ISO_PKG, syntax="proto3",
    )
    msgf.dependency.append("pkoptiso_ext.proto")
    mp = msgf.message_type.add()
    mp.name = "M"
    for number, (name, options_bytes) in enumerate(
        (
            ("bare", b""),
            ("annotated", _annotated(limit=42, label="hi", tags=["a", "b"], cfg=9)),
            ("zeroed", _annotated(limit=0)),
        ),
        start=1,
    ):
        fp = mp.field.add()
        fp.name, fp.number, fp.type = name, number, FD.TYPE_INT32
        fp.label = FD.LABEL_OPTIONAL
        if options_bytes:
            fp.options.MergeFromString(options_bytes)
    # A declared option and a still-uninterpreted one ride alongside
    # the custom ones, so the re-read is shown to keep both.
    fp.options.deprecated = True
    uo = fp.options.uninterpreted_option.add()
    uo.name.add(name_part="pending", is_extension=True)
    uo.string_value = b"later"

    fds = descriptor_pb2.FileDescriptorSet()
    fds.file.extend([_descriptor_proto_file(), _isolated_extension_file(), msgf])
    pool = build_pool(fds)
    return pool, dict(pool.FindMessageTypeByName(f"{_ISO_PKG}.M").fields_by_name)


_ISO_POOL, _ISO_FIELDS = _build_isolated_fixtures()


class TestIsolatedPool:
    """Tier 1 on a pool built from a descriptor set (V9).

    Every option here was read as ``None`` before ``_extensions``
    re-read the options through the pool that declares them — the
    same answer an unannotated field gets, so a hook gating on
    ``is not None`` silently never fired.
    """

    def test_scalar_int_extension_resolves(self) -> None:
        assert get_option_value(
            _ISO_FIELDS["annotated"], f"{_ISO_PKG}.limit",
        ) == 42

    def test_scalar_string_extension_resolves(self) -> None:
        assert get_option_value(
            _ISO_FIELDS["annotated"], f"{_ISO_PKG}.label",
        ) == "hi"

    def test_repeated_extension_resolves(self) -> None:
        assert list(
            get_option_value(_ISO_FIELDS["annotated"], f"{_ISO_PKG}.tags"),
        ) == ["a", "b"]

    def test_message_extension_resolves(self) -> None:
        value = get_option_value(_ISO_FIELDS["annotated"], f"{_ISO_PKG}.cfg")
        assert value is not None
        assert value.depth == 9

    def test_message_extension_sub_path_resolves(self) -> None:
        assert get_option_value(
            _ISO_FIELDS["annotated"], f"{_ISO_PKG}.cfg.depth",
        ) == 9

    def test_explicit_zero_is_not_mistaken_for_absent(self) -> None:
        assert get_option_value(
            _ISO_FIELDS["zeroed"], f"{_ISO_PKG}.limit",
        ) == 0

    def test_absent_extensions_return_none(self) -> None:
        """Presence stays strict after the re-read: a registered but
        unset extension reads as absent, in every shape.
        """
        for option in ("limit", "label", "tags", "cfg", "cfg.depth"):
            assert get_option_value(
                _ISO_FIELDS["bare"], f"{_ISO_PKG}.{option}",
            ) is None, option

    def test_option_of_another_options_type_is_absent(self) -> None:
        """``mopt`` extends ``MethodOptions``, so no field can carry it.
        That is an absent option, not an error.
        """
        assert get_option_value(
            _ISO_FIELDS["annotated"], f"{_ISO_PKG}.mopt",
        ) is None

    def test_declared_and_uninterpreted_options_survive(self) -> None:
        """The re-read keeps what the options message already held: a
        declared field and the ``uninterpreted_option`` tier 2 scans.
        """
        field = _ISO_FIELDS["zeroed"]
        assert field.GetOptions().deprecated is True
        assert get_option_value(field, f"{_ISO_PKG}.limit") == 0
        assert get_option_value(field, "pending") == b"later"

    def test_explicit_pool_holding_the_extension_resolves(self) -> None:
        """``pool=`` names a pool other than the descriptor's own. The
        re-read binds to the pool that declares the extension, so the
        descriptor's own pool need not know it.
        """
        assert get_option_value(
            _ISO_FIELDS["annotated"], f"{_ISO_PKG}.limit", pool=_ISO_POOL,
        ) == 42
        other_pool, other_fields = _build_isolated_fixtures()
        assert other_pool is not _ISO_POOL
        assert get_option_value(
            other_fields["annotated"], f"{_ISO_PKG}.label", pool=_ISO_POOL,
        ) == "hi"


class TestUninterpretedOption:
    """Tier-2 path: options stored as ``uninterpreted_option`` entries."""

    def test_returns_string_value(self) -> None:
        _, fd = _build_field_with_uninterp_option(
            option_name_parts=[("my_label", True)],
            value_field="string_value",
            value=b"hello",
        )
        assert get_option_value(fd, "my_label") == b"hello"

    def test_returns_identifier_value(self) -> None:
        _, fd = _build_field_with_uninterp_option(
            option_name_parts=[("my_kind", True)],
            value_field="identifier_value",
            value="ADMIN",
        )
        assert get_option_value(fd, "my_kind") == "ADMIN"

    def test_returns_positive_int_value(self) -> None:
        _, fd = _build_field_with_uninterp_option(
            option_name_parts=[("my_limit", True)],
            value_field="positive_int_value",
            value=42,
        )
        assert get_option_value(fd, "my_limit") == 42

    def test_returns_negative_int_value(self) -> None:
        _, fd = _build_field_with_uninterp_option(
            option_name_parts=[("my_offset", True)],
            value_field="negative_int_value",
            value=-7,
        )
        assert get_option_value(fd, "my_offset") == -7

    def test_returns_double_value(self) -> None:
        _, fd = _build_field_with_uninterp_option(
            option_name_parts=[("my_ratio", True)],
            value_field="double_value",
            value=3.14,
        )
        assert get_option_value(fd, "my_ratio") == 3.14

    def test_returns_aggregate_value(self) -> None:
        _, fd = _build_field_with_uninterp_option(
            option_name_parts=[("my_agg", True)],
            value_field="aggregate_value",
            value="{nested: true}",
        )
        assert get_option_value(fd, "my_agg") == "{nested: true}"

    def test_matches_dotted_path_exactly(self) -> None:
        """Nested NameParts reconstruct a dotted path for matching."""
        _, fd = _build_field_with_uninterp_option(
            option_name_parts=[
                ("validate", True),
                ("rules", False),
                ("int32", False),
                ("gte", False),
            ],
            value_field="positive_int_value",
            value=100,
        )
        assert get_option_value(
            fd, "validate.rules.int32.gte",
        ) == 100

    def test_returns_none_when_name_does_not_match(self) -> None:
        _, fd = _build_field_with_uninterp_option(
            option_name_parts=[("some_label", True)],
            value_field="string_value",
            value=b"x",
        )
        assert get_option_value(fd, "other_label") is None

    def test_returns_none_when_no_options_at_all(self) -> None:
        pool = descriptor_pool.DescriptorPool()
        fdp = descriptor_pb2.FileDescriptorProto(
            name="plain.proto", package="t", syntax="proto3",
        )
        mp = fdp.message_type.add()
        mp.name = "M"
        fp = mp.field.add()
        fp.name, fp.number, fp.type = "x", 1, FD.TYPE_INT32
        fp.label = FD.LABEL_OPTIONAL
        pool.Add(fdp)
        fd = pool.FindMessageTypeByName("t.M").fields_by_name["x"]
        assert get_option_value(fd, "anything.at.all") is None


class TestDescriptorVariants:
    """The helper accepts any descriptor with ``GetOptions()`` that can
    name its owning pool — which the accepted types do differently.
    """

    def test_accepts_message_descriptor(self) -> None:
        """Message-level options (e.g., ``[message_set_wire_format]``)
        go through the same ``GetOptions()`` / ``Extensions[]`` path.
        Exercise with an ``uninterpreted_option`` on the message.
        """
        pool = descriptor_pool.DescriptorPool()
        fdp = descriptor_pb2.FileDescriptorProto(
            name="msgopt.proto", package="t", syntax="proto3",
        )
        mp = fdp.message_type.add()
        mp.name = "M"
        uo = mp.options.uninterpreted_option.add()
        uo.name.add(name_part="my_msg_opt", is_extension=True)
        uo.string_value = b"ping"
        pool.Add(fdp)
        m_desc = pool.FindMessageTypeByName("t.M")
        assert get_option_value(m_desc, "my_msg_opt") == b"ping"

    def test_accepts_file_descriptor(self) -> None:
        """A ``FileDescriptor`` has no ``file`` attribute under the
        upb backend — it *is* the file — so the default-pool hop has
        to read ``desc.pool`` instead of ``desc.file.pool``.
        """
        pool = descriptor_pool.DescriptorPool()
        fdp = descriptor_pb2.FileDescriptorProto(
            name="fileopt.proto", package="t", syntax="proto3",
        )
        uo = fdp.options.uninterpreted_option.add()
        uo.name.add(name_part="my_file_opt", is_extension=True)
        uo.string_value = b"whole-file"
        pool.Add(fdp)
        f_desc = pool.FindFileByName("fileopt.proto")
        assert get_option_value(f_desc, "my_file_opt") == b"whole-file"

    def test_accepts_enum_value_descriptor(self) -> None:
        """An ``EnumValueDescriptor`` exposes neither ``file`` nor
        ``pool`` under the upb backend; the owning file is reachable
        only through its enum type (``desc.type.file``).
        """
        pool = descriptor_pool.DescriptorPool()
        fdp = descriptor_pb2.FileDescriptorProto(
            name="enumvalopt.proto", package="t", syntax="proto3",
        )
        ep = fdp.enum_type.add()
        ep.name = "E"
        vp = ep.value.add()
        vp.name, vp.number = "E_UNSPECIFIED", 0
        uo = vp.options.uninterpreted_option.add()
        uo.name.add(name_part="my_value_opt", is_extension=True)
        uo.string_value = b"zero"
        pool.Add(fdp)
        ev_desc = pool.FindEnumTypeByName("t.E").values_by_name["E_UNSPECIFIED"]
        assert get_option_value(ev_desc, "my_value_opt") == b"zero"

    def test_accepts_service_method_and_oneof_descriptors(self) -> None:
        """Under upb a ``MethodDescriptor`` reaches its file only through
        its service, and a ``OneofDescriptor`` only through its message;
        pure-python gives both a ``file``. Without the extra hops the
        helper raised ``AttributeError`` on upb alone.
        """
        pool = descriptor_pool.DescriptorPool()
        fdp = descriptor_pb2.FileDescriptorProto(
            name="svcopt.proto", package="t", syntax="proto3",
        )
        mp = fdp.message_type.add()
        mp.name = "M"
        oneof = mp.oneof_decl.add()
        oneof.name = "choice"
        fp = mp.field.add()
        fp.name, fp.number, fp.type = "x", 1, FD.TYPE_INT32
        fp.label, fp.oneof_index = FD.LABEL_OPTIONAL, 0
        sp = fdp.service.add()
        sp.name = "S"
        meth = sp.method.add()
        meth.name, meth.input_type, meth.output_type = "Call", ".t.M", ".t.M"
        for options, value in (
            (sp.options, b"svc"), (meth.options, b"rpc"), (oneof.options, b"one"),
        ):
            uo = options.uninterpreted_option.add()
            uo.name.add(name_part="my_opt", is_extension=True)
            uo.string_value = value
        pool.Add(fdp)
        service = pool.FindServiceByName("t.S")
        assert get_option_value(service, "my_opt") == b"svc"
        assert get_option_value(service.FindMethodByName("Call"), "my_opt") == b"rpc"
        m_desc = pool.FindMessageTypeByName("t.M")
        assert get_option_value(m_desc.oneofs_by_name["choice"], "my_opt") == b"one"

    def test_raises_attribute_error_on_non_descriptor(self) -> None:
        """Passing something without ``GetOptions()`` is a bug — the
        helper lets ``AttributeError`` propagate rather than
        silently returning None, so the caller notices.
        """
        import pytest
        with pytest.raises(AttributeError):
            get_option_value(object(), "anything")


class TestPoolArgument:
    """The ``pool`` kwarg lets the caller override the owning pool."""

    def test_default_pool_is_descriptor_file_pool(self) -> None:
        """When pool=None, the helper uses the descriptor's own pool. Since
        no extension is registered, the tier-1 path can't match and
        the tier-2 fallback runs. Verified end-to-end by
        ``TestUninterpretedOption``.
        """
        # This is a behavioral assertion about the default pool
        # fallback — already covered indirectly by the unin-tier
        # tests, which never pass ``pool=``. We include it here as
        # a documented invariant.
        pool, fd = _build_field_with_uninterp_option(
            option_name_parts=[("marker", True)],
            value_field="string_value",
            value=b"present",
        )
        # Without passing pool=, the default is fd.file.pool.
        assert get_option_value(fd, "marker") == b"present"
        # Passing the same pool explicitly behaves identically.
        assert get_option_value(fd, "marker", pool=pool) == b"present"
