"""Unit tests for ``protokit.options.get_option_value``.

Tier 1 (``Extensions[]``) is exercised end-to-end by the Phase
1.5 hook integration tests, where extensions are registered via
real generated ``_pb2`` modules. Unit-level Tier 1 testing is
blocked by protobuf's bootstrap-pool coupling (``GetOptions()``
always returns a default-pool-bound ``FieldOptions`` instance,
which doesn't recognize extensions from a custom pool).

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
    name its owning pool — which the five accepted types do differently.
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
