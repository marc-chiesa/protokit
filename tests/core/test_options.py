"""Unit tests for ``protokit.options.get_option_value``.

Tier 1 (``Extensions[]``) is exercised end-to-end by the Phase
1.5 hook integration tests, where extensions are registered via
real generated ``_pb2`` modules. Unit-level Tier 1 testing over a
*custom* pool is blocked by protobuf's bootstrap-pool coupling
(``GetOptions()`` always returns a default-pool-bound
``FieldOptions`` instance, which doesn't recognize extensions from
a custom pool) — so ``TestExtensionPresence`` registers its
extensions in the DEFAULT pool instead, which is both the only
in-process way to make tier 1 engage and the realistic trigger (a
generated ``_pb2`` registers there on import).

Tier 2 (``uninterpreted_option``) is what we get when building a
``FieldDescriptorProto`` programmatically, so we can exercise it
directly.
"""

from __future__ import annotations

from google.protobuf import descriptor_pb2, descriptor_pool

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
    """The helper accepts any descriptor with ``GetOptions()`` + ``file``."""

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

    def test_raises_attribute_error_on_non_descriptor(self) -> None:
        """Passing something without ``GetOptions()`` is a bug — the
        helper lets ``AttributeError`` propagate rather than
        silently returning None, so the caller notices.
        """
        import pytest
        with pytest.raises(AttributeError):
            get_option_value(object(), "anything")


class TestPoolArgument:
    """The ``pool`` kwarg lets the caller override ``desc.file.pool``."""

    def test_default_pool_is_descriptor_file_pool(self) -> None:
        """When pool=None, the helper uses ``desc.file.pool``. Since
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
