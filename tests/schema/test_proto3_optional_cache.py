"""``_proto3_optional_fields``' per-check cache must not alias descriptors (upb).

The cache is keyed by ``id(desc)``. Under upb a ``Descriptor`` is a Python
wrapper created on demand and released when nothing references it, so
within one ``check()`` run a collected wrapper's id can be handed to a
different message's wrapper. A bare id() cache then returns the previous
message's proto3-optional set for the new one, and the ``oneof_membership``
and ``presence`` rules read the wrong answer — measured on protobuf 5.27.5
as 111 ``oneof_membership_changed`` findings on a 200-message chain where
exactly 100 exist. The pure-Python runtime keeps its descriptors alive and
never aliases, which is why the suite did not see it.

The chain alternates the two shapes so a stale hit is always wrong: messages
``k % 4 in {0, 1}`` declare a proto3 ``optional`` (a synthetic oneof that
must NOT count as membership) and ``k % 4 in {2, 3}`` move a plain field
into a real oneof between old and new (which MUST count). Every message is
reachable from ``M0`` through ``next``.
"""

from __future__ import annotations

from collections import Counter

import pytest
from google.protobuf import descriptor_pb2, descriptor_pool

from protokit.schema import check_compatibility

_FD = descriptor_pb2.FieldDescriptorProto


def _chain(n: int, *, new: bool) -> descriptor_pool.DescriptorPool:
    fdp = descriptor_pb2.FileDescriptorProto(name="s.proto", package="s", syntax="proto3")
    for k in range(n):
        msg = fdp.message_type.add(name=f"M{k}")
        if k % 4 in (0, 1):
            msg.oneof_decl.add(name="_x")
            fld = msg.field.add(
                name="x", number=1, type=_FD.TYPE_INT32, label=_FD.LABEL_OPTIONAL, oneof_index=0,
            )
            fld.proto3_optional = True
        elif new:
            msg.oneof_decl.add(name="o")
            msg.field.add(
                name="x", number=1, type=_FD.TYPE_INT32, label=_FD.LABEL_OPTIONAL, oneof_index=0,
            )
        else:
            msg.field.add(name="x", number=1, type=_FD.TYPE_INT32, label=_FD.LABEL_OPTIONAL)
        if k + 1 < n:
            msg.field.add(
                name="next", number=2, type=_FD.TYPE_MESSAGE, label=_FD.LABEL_OPTIONAL,
                type_name=f".s.M{k + 1}",
            )
    pool = descriptor_pool.DescriptorPool()
    pool.Add(fdp)
    return pool


@pytest.mark.parametrize("n", [40, 200])
def test_oneof_membership_findings_are_exact(n: int) -> None:
    result = check_compatibility(_chain(n, new=False), "s.M0", _chain(n, new=True), "s.M0")
    counts = Counter(f.rule_id for f in result.findings)
    assert counts["oneof_membership_changed"] == n // 2, counts
    assert counts["presence_changed"] == n // 2, counts
