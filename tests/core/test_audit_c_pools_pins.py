"""Regression pins for deferred re-audit findings in descriptor-set loading (family C, pools).

Every ``xfail`` in this module pins a LIVE defect that a later release owns.
Each pin is ``@pytest.mark.xfail(strict=True, raises=...)`` on the test
function itself, with a ``reason`` that begins with the finding ID and names
the owning unit and release. The suite stays green while the defect exists and
the pin flips to a hard failure (XPASS under strict mode) the day the mechanism
is fixed, so a fix cannot land silently and no pin can rot into a
permanently-red test.

Each pin asserts the correct outcome, and ``raises=`` names the exception that
was observed with ``--runxfail --tb=line`` under both protobuf backends, so a
pin that dies anywhere else is red rather than "expected". A passing control
sits beside every pin and shares its construction: a red control says the
harness broke, a red pin says the defect moved.

A defect on one backend only is pinned with
``@pytest.mark.xfail(condition=_PURE_PYTHON_BACKEND, strict=True, ...)``. Under
upb the marker does not apply and the pin is an ordinary passing test: it is
the upb control for the pure-Python pin.

Pinned here:

* **C02-C1** — pure-Python only. A ``FileDescriptorSet`` whose file declares an
  edition later than the runtime implements (2024, under protobuf 5.x) loads:
  ``load_pool_from_bytes`` returns a pool, and the first use of it
  (``get_message_class``, ``has_presence``, ``GetOptions``) raises a raw
  ``TypeError``. upb refuses the file at load with ``DescriptorPoolError``,
  which is the promised outcome. protobuf 4.25 implements no editions and
  protokit refuses every editions file there, so both tests skip on it. The
  edition is a constant: when a supported runtime implements 2024, the upb
  run of the pin turns red and the constant must move past the new maximum.
  Owner: U26 (after 0.19.0), group (a).
* **C02-C3**, the ``RecursionError`` half — ``get_message_class`` calls
  ``message_factory.GetMessageClass`` outside any ``try``, and building a
  class recurses once per link of a chain of message-typed fields, so on a
  valid chain of twice the interpreter's recursion limit the first call
  raises a raw ``RecursionError``, on both backends (a second call returns,
  from the classes cached on the way down; each test builds its own pool).
  The fixed outcome is not settled: the class builds, or a typed
  ``DescriptorPoolError`` is raised, and the pin accepts either. Owner: U26
  (after 0.19.0), group (a). The finding's other half, a field named
  ``DESCRIPTOR``, is a different defect with a different owner (U17a, with
  the field-name family) and is not pinned here.
* **E03-C1** (re-audit cycle 3) — a field that is neither repeated nor an
  extension, whose type is a ``map_entry`` message, passes the loader. Under
  upb ``get_message_class`` builds the class and the parse drops the field
  (not set, not unknown), so payloads that differ in it compare equal. Under
  pure-Python ``get_message_class`` raises protobuf's raw ``ValueError``
  (``map_entry set on non-repeated field``). The pin restates that
  ``ValueError`` as its failed assertion on purpose: ``raises=AssertionError``
  then covers both backends, while any other error (a different
  ``ValueError`` included) goes through ``pytest.fail`` and is red. The fixed
  outcome is not settled: a typed ``DescriptorPoolError`` from the load or the
  class build, or the field read as a message, and the pin accepts either on
  each backend. Owner: U26 (after 0.19.0), group (a).
"""

from __future__ import annotations

import sys

import pytest
from google.protobuf import descriptor_pb2
from google.protobuf.internal import api_implementation

from protokit._pools import (
    DescriptorPoolError,
    MessageTypeNotFoundError,
    get_message_class,
    load_pool_from_bytes,
)
from tests._editions import requires_editions

_F = descriptor_pb2.FieldDescriptorProto
_PKG = "auditcpools"
_PURE_PYTHON_BACKEND = api_implementation.Type() == "python"


# ---------------------------------------------------------------------------
# C02-C1 — an edition the runtime does not implement loads under pure-Python
# ---------------------------------------------------------------------------


def _edition_set(edition_name: str) -> bytes:
    """A serialized set of one editions file declaring ``edition_name``, with one message ``M``.

    Skips on a runtime that implements no editions, before naming the edition:
    protobuf 4.25 has no ``EDITION_2024``.
    """
    requires_editions()
    file = descriptor_pb2.FileDescriptorProto(
        name="auditcpools/e.proto", package=_PKG, syntax="editions",
        edition=getattr(descriptor_pb2, edition_name),
    )
    file.message_type.add(name="M").field.add(
        name="x", number=1, type=_F.TYPE_INT32, label=_F.LABEL_OPTIONAL,
    )
    return descriptor_pb2.FileDescriptorSet(file=[file]).SerializeToString()


@pytest.mark.xfail(
    condition=_PURE_PYTHON_BACKEND,
    strict=True,
    raises=pytest.fail.Exception,
    reason=(
        "C02-C1: owned by U26 (after 0.19.0). Pure-Python only. The pure-Python "
        "runtime adds an edition-2024 file to the pool without resolving its "
        "features, and load_pool_from_bytes asks nothing that would, so the load "
        "returns a pool (DID NOT RAISE) and the first get_message_class, "
        "has_presence or GetOptions raises a raw TypeError instead."
    ),
)
def test_c02_c1_an_edition_later_than_the_runtime_implements_is_refused_at_load() -> None:
    """Under upb this is the upb control for the pure-Python pin (see the module docstring)."""
    data = _edition_set("EDITION_2024")
    with pytest.raises(DescriptorPoolError):
        load_pool_from_bytes(data)


def test_c02_c1_an_edition_the_runtime_implements_loads_and_builds_control() -> None:
    # The same file with the edition the runtime does implement: it loads, and
    # the class the pin's first use dies on builds and holds a value.
    pool = load_pool_from_bytes(_edition_set("EDITION_2023"))
    message_class = get_message_class(pool, f"{_PKG}.M")
    assert message_class(x=1).x == 1


# ---------------------------------------------------------------------------
# C02-C3, RecursionError half — get_message_class on a valid deep chain
# ---------------------------------------------------------------------------

# Past the limit from any caller: about two frames per link were measured on
# Python 3.12 and 3.13, under both backends, protobuf 4.25 and 5.27.
_LINKS = 2 * sys.getrecursionlimit()


def _chain_set(links: int) -> bytes:
    """A serialized set of one proto3 file: ``M0`` holds ``M1`` holds ... ``M<links-1>``."""
    file = descriptor_pb2.FileDescriptorProto(
        name="auditcpools/chain.proto", package=_PKG, syntax="proto3",
    )
    for index in range(links):
        link = file.message_type.add(name=f"M{index}")
        if index + 1 < links:
            link.field.add(
                name="next", number=1, type=_F.TYPE_MESSAGE, label=_F.LABEL_OPTIONAL,
                type_name=f".{_PKG}.M{index + 1}",
            )
    return descriptor_pb2.FileDescriptorSet(file=[file]).SerializeToString()


@pytest.mark.xfail(
    strict=True,
    raises=RecursionError,
    reason=(
        "C02-C3 (RecursionError half): owned by U26 (after 0.19.0). "
        "get_message_class calls message_factory.GetMessageClass outside any try, "
        "and building a class recurses once per message-typed link, so on a valid "
        "chain of twice the recursion limit the first call raises a raw "
        "RecursionError on both backends. Either outcome counts as fixed: the class "
        "builds, or a typed DescriptorPoolError is raised."
    ),
)
def test_c02_c3_get_message_class_on_a_valid_deep_chain_builds_or_refuses_typed() -> None:
    pool = load_pool_from_bytes(_chain_set(_LINKS))  # a fresh pool: nothing built yet
    try:
        message_class = get_message_class(pool, f"{_PKG}.M0")
    except MessageTypeNotFoundError:
        raise  # the set did not hold the type: neither fixed outcome
    except DescriptorPoolError:
        return  # a typed refusal is one of the two fixed outcomes
    assert message_class.DESCRIPTOR.full_name == f"{_PKG}.M0"  # type: ignore[attr-defined]


def test_c02_c3_get_message_class_one_hundred_links_from_the_end_control() -> None:
    # The same set in a fresh pool: only the type asked for differs, and a
    # chain of one hundred links builds.
    pool = load_pool_from_bytes(_chain_set(_LINKS))
    name = f"{_PKG}.M{_LINKS - 100}"
    assert get_message_class(pool, name).DESCRIPTOR.full_name == name  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# E03-C1 — a singular field typed as a map entry passes the loader
# ---------------------------------------------------------------------------

# id = 1, labels = {key: "k", value: <last byte>}: field 20, length 6.
_LABELS_V = bytes.fromhex("0801a201060a016b120176")
_LABELS_W = bytes.fromhex("0801a201060a016b120177")


def _map_entry_field_set(label: int) -> bytes:
    """A serialized proto2 set: ``Holder.labels = 20`` with ``label``, typed as a map entry."""
    file = descriptor_pb2.FileDescriptorProto(
        name="auditcpools/m.proto", package=_PKG, syntax="proto2"
    )
    holder = file.message_type.add(name="Holder")
    holder.field.add(name="id", number=1, type=_F.TYPE_INT32, label=_F.LABEL_OPTIONAL)
    entry = holder.nested_type.add(name="LabelsEntry")
    entry.options.map_entry = True
    entry.field.add(name="key", number=1, type=_F.TYPE_STRING, label=_F.LABEL_OPTIONAL)
    entry.field.add(name="value", number=2, type=_F.TYPE_STRING, label=_F.LABEL_OPTIONAL)
    holder.field.add(
        name="labels",
        number=20,
        type=_F.TYPE_MESSAGE,
        label=label,
        type_name=f".{_PKG}.Holder.LabelsEntry",
    )
    return descriptor_pb2.FileDescriptorSet(file=[file]).SerializeToString()


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "E03-C1: owned by U26 (after 0.19.0). A singular field (not an extension) "
        "typed as a map entry passes the loader. Under upb the parse drops the "
        "field, so payloads that differ in it compare equal; under pure-Python "
        "get_message_class raises protobuf's raw ValueError ('map_entry set on "
        "non-repeated field'), which the pin restates as its assertion. Either "
        "outcome counts as fixed: a typed DescriptorPoolError at load or class "
        "build, or the field read as a message."
    ),
)
def test_e03_c1_a_singular_field_typed_as_a_map_entry_is_refused_or_read() -> None:
    raw_value_error: ValueError | None = None
    try:
        pool = load_pool_from_bytes(_map_entry_field_set(_F.LABEL_OPTIONAL))
        message_class = get_message_class(pool, f"{_PKG}.Holder")
    except MessageTypeNotFoundError as exc:
        pytest.fail(f"the set did not hold the type, neither fixed outcome: {exc}")
    except DescriptorPoolError:
        return  # a typed refusal is one of the two fixed outcomes
    except ValueError as exc:
        if "map_entry set on non-repeated field" not in str(exc):
            pytest.fail(f"a ValueError other than the pinned one: {exc!r}")
        raw_value_error = exc
    assert raw_value_error is None, (
        f"pure-Python: get_message_class raised protobuf's raw {raw_value_error!r}"
    )
    left = message_class.FromString(_LABELS_V)  # type: ignore[attr-defined]
    right = message_class.FromString(_LABELS_W)  # type: ignore[attr-defined]
    assert (left.labels.key, left.labels.value) == ("k", "v"), (
        f"upb: the parse dropped the field, re-serialized {left.SerializeToString().hex()}"
    )
    assert left != right


def test_e03_c1_the_same_field_repeated_is_a_map_and_reads_control() -> None:
    # The same set with ``labels`` repeated is an ordinary map field: it loads,
    # builds and reads the pin's payloads, which differ.
    pool = load_pool_from_bytes(_map_entry_field_set(_F.LABEL_REPEATED))
    message_class = get_message_class(pool, f"{_PKG}.Holder")
    left = message_class.FromString(_LABELS_V)  # type: ignore[attr-defined]
    assert dict(left.labels) == {"k": "v"}
    assert left != message_class.FromString(_LABELS_W)  # type: ignore[attr-defined]
