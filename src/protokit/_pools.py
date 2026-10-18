"""Descriptor-pool construction and message-class resolution.

Library-level helpers that build *isolated* ``DescriptorPool``s from a
``FileDescriptorSet`` in dependency order, and resolve message classes by
fully-qualified name. They raise typed library exceptions (never
``sys.exit`` / Click errors) so non-CLI callers — the storage engine, the
diff and compat CLIs — share one pool-building path. CLI layers catch these
and translate to exit codes.

Why dependency ordering matters
-------------------------------
``DescriptorPool.Add(FileDescriptorProto)`` requires that every file named
in a descriptor's ``dependency`` list is already present in the pool.
``protoc --descriptor_set_out`` emits files in dependency order, so a naive
in-order add works for protoc output. But an arbitrary or *embedded*
``FileDescriptorSet`` — e.g. protokit's channelized-stream schema, which is
``(FileDescriptorSet, fully-qualified message name)`` and is not guaranteed
sorted — raises unknown-dependency errors on naive add. :func:`build_pool`
topologically sorts defensively so any well-formed (self-contained) set
loads regardless of file order.
"""

from __future__ import annotations

from collections import deque
from pathlib import Path

from google.protobuf import descriptor_pb2, descriptor_pool, message_factory
from google.protobuf.descriptor import Descriptor
from google.protobuf.message import DecodeError


class DescriptorPoolError(Exception):
    """Base for descriptor-pool construction and resolution failures."""


class MissingDependencyError(DescriptorPoolError):
    """A file names a ``dependency`` absent from the ``FileDescriptorSet``.

    The set must be the full transitive import closure — a channelized
    schema that references a file it does not carry cannot build a pool.
    """

    def __init__(self, file_name: str, dependency: str) -> None:
        self.file_name = file_name
        self.dependency = dependency
        super().__init__(
            f"file {file_name!r} depends on {dependency!r}, which is not "
            f"present in the FileDescriptorSet (the set must be the full "
            f"transitive import closure)."
        )


class DuplicateFileError(DescriptorPoolError):
    """Two file descriptors in the set share the same ``name``.

    ``DescriptorPool.Add`` rejects a duplicate file name with a
    ``TypeError``; mirroring that as a typed, named error keeps the failure
    *loud* (a naive de-dup would silently drop one definition and resolve an
    arbitrary, input-order-dependent winner).
    """

    def __init__(self, file_name: str) -> None:
        self.file_name = file_name
        super().__init__(
            f"duplicate file name {file_name!r} in the FileDescriptorSet; "
            f"each file descriptor must have a unique name."
        )


class MessageTypeNotFoundError(DescriptorPoolError):
    """A fully-qualified message type is absent from the pool.

    The message text matches the historical diff/compat CLI wording so the
    CLI layer can surface it verbatim.
    """

    def __init__(self, type_name: str) -> None:
        self.type_name = type_name
        super().__init__(f"Message type '{type_name}' not found in descriptor pool.")


def sort_files_by_dependency(
    files: list[descriptor_pb2.FileDescriptorProto],
) -> list[descriptor_pb2.FileDescriptorProto]:
    """Return ``files`` ordered so every file follows its dependencies.

    Iterative Kahn topological sort (no recursion, so it is safe on
    arbitrarily deep import chains). Ties are broken by input order, which
    keeps the output deterministic and leaves an already-sorted set
    effectively unchanged. Duplicate dependency entries within a file are
    counted once.

    Raises:
        DuplicateFileError: two files share the same ``name`` (a naive
            de-dup would silently drop a definition — we fail loudly, as
            ``DescriptorPool.Add`` itself does).
        MissingDependencyError: a file names a dependency not in ``files``.
        DescriptorPoolError: the file dependency graph contains a cycle.
    """
    by_name: dict[str, descriptor_pb2.FileDescriptorProto] = {}
    for f in files:
        if f.name in by_name:
            raise DuplicateFileError(f.name)
        by_name[f.name] = f

    # Build the dependency DAG. in_degree[name] = count of distinct deps;
    # dependents[dep] = files that import dep. Duplicate deps within a file
    # collapse via the set so in_degree stays accurate.
    in_degree: dict[str, int] = {}
    dependents: dict[str, list[str]] = {name: [] for name in by_name}
    for f in files:
        deps = set(f.dependency)
        for dep in deps:
            if dep not in by_name:
                raise MissingDependencyError(f.name, dep)
            dependents[dep].append(f.name)
        in_degree[f.name] = len(deps)

    # Seed with dependency-free files in input order for deterministic output.
    queue: deque[str] = deque(f.name for f in files if in_degree[f.name] == 0)
    ordered: list[descriptor_pb2.FileDescriptorProto] = []
    while queue:
        name = queue.popleft()
        ordered.append(by_name[name])
        for dependent in dependents[name]:
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)

    if len(ordered) != len(files):
        placed = {fd.name for fd in ordered}
        remaining = [f.name for f in files if f.name not in placed]
        raise DescriptorPoolError(
            f"cyclic file dependency among: {', '.join(map(repr, remaining))}"
        )
    return ordered


def add_and_resolve(
    pool: descriptor_pool.DescriptorPool,
    fd: descriptor_pb2.FileDescriptorProto,
) -> None:
    """``pool.Add(fd)``, then force resolution and raise the typed error family.

    Resolution is asserted, never inferred from ``Add()`` raising (KTD6, V10).
    The two protobuf backends disagree about when a file with unresolvable
    symbols fails, measured on 5.27.5:

    * **upb** resolves eagerly and raises ``TypeError`` from ``Add`` itself —
      e.g. a field referencing a symbol no file in the set defines (a dangling
      symbol with no *missing-file* dependency, which a topological sort
      cannot detect).
    * **pure-Python** resolves lazily, so ``Add()`` returns cleanly and the
      caller walks away with a pool that merely looks populated. The failure
      only surfaces when something forces resolution, as ``KeyError``. A
      second file under an already-registered name with different content is
      its own shape again: ``DescriptorDatabaseConflictingDefinitionError``
      from ``Add`` itself, where upb raises ``TypeError``.

    ``FindFileByName`` forces it here on both. Pure-Python's own descriptor checks
    add more shapes (``ValueError``, ``IndexError``, ``AttributeError``), so any
    exception from the two calls is re-raised as :class:`DescriptorPoolError`.

    One product site does not use this helper on purpose: the lint
    descriptor-set loader (``schema/lint/_cli_utils.py``) repeats the
    Add-then-probe sequence inline because it must route on the raw exception
    to choose a stable ``error[lint-...]`` code, and collapsing both shapes
    here would hide that. The comment at that site names the U17 follow-up.

    Args:
        pool: The pool to populate.
        fd: The ``FileDescriptorProto`` to add.

    Raises:
        DescriptorPoolError: If the file cannot be resolved into the pool.
    """
    # Broad on purpose: the try holds the two protobuf calls, whose rejection
    # shapes vary by backend and version (see above), and the map-entry check.
    # BaseException (KeyboardInterrupt, SystemExit) is not caught and propagates.
    try:
        pool.Add(_honoured(fd))
        _refuse_map_typed_extensions(pool.FindFileByName(fd.name))
    except Exception as exc:
        raise _refusal_kind(exc)(
            f"could not build file {fd.name!r} into the descriptor pool: {exc}"
        ) from exc


def build_pool(
    fds: descriptor_pb2.FileDescriptorSet,
) -> descriptor_pool.DescriptorPool:
    """Build a fresh, isolated ``DescriptorPool`` from a ``FileDescriptorSet``.

    Files are added in dependency order into a brand-new pool — never the
    default pool — so concurrent pools may hold conflicting versions of the
    same fully-qualified type without collision.
    """
    pool = descriptor_pool.DescriptorPool()
    for fd in sort_files_by_dependency(list(require_decodable_strings(fds).file)):
        # Files are added in dependency order above, so a forward reference
        # within this set is already satisfied by the time its referrer is
        # added and the eager resolution below cannot false-positive.
        add_and_resolve(pool, fd)
    return pool


def load_pool_from_bytes(data: bytes) -> descriptor_pool.DescriptorPool:
    """Parse serialized ``FileDescriptorSet`` bytes and build an isolated pool.

    Raises:
        DescriptorPoolError: ``data`` is not a parseable ``FileDescriptorSet``
            (a corrupt/truncated channel surfaces as the typed family, not a raw
            protobuf ``DecodeError``), or the parsed set cannot build a pool.
    """
    fds = descriptor_pb2.FileDescriptorSet()
    try:
        fds.ParseFromString(data)
    except (DecodeError, UnicodeDecodeError, RecursionError) as exc:
        raise DescriptorPoolError(
            f"could not parse FileDescriptorSet bytes: {exc}"
        ) from exc
    return build_pool(fds)


def load_pool_from_path(path: Path) -> descriptor_pool.DescriptorPool:
    """Read a ``.descriptor_set`` file and build an isolated pool.

    A file that does not parse or build raises ``DescriptorPoolError``, as
    :func:`load_pool_from_bytes` does; an unreadable path raises ``OSError``.
    """
    return load_pool_from_bytes(Path(path).read_bytes())


def get_message_class(
    pool: descriptor_pool.DescriptorPool,
    type_name: str,
) -> type:
    """Resolve a fully-qualified message type to its generated class.

    Raises:
        MessageTypeNotFoundError: the type is not present in ``pool``.
    """
    try:
        desc: Descriptor = pool.FindMessageTypeByName(type_name)
    except KeyError as exc:
        raise MessageTypeNotFoundError(type_name) from exc
    # Assign to a typed local rather than returning Any directly — matches
    # the codebase pattern (schema/lint/_extension_access.py) and satisfies
    # mypy's warn_return_any under strict mode (protobuf ships no stubs).
    cls: type = message_factory.GetMessageClass(desc)
    return _ready_to_parse(cls)


def require_decodable_strings(
    fds: descriptor_pb2.FileDescriptorSet,
) -> descriptor_pb2.FileDescriptorSet:
    """Return ``fds`` unchanged, or raise if any string in it is not UTF-8.

    The two runtimes disagree about when an undecodable string fails. The
    pure-Python runtime rejects it while parsing (``UnicodeDecodeError``).
    upb parses it and hands the field back as ``bytes``; a bad package or
    type name then fails at ``Add``, but a bad file *name* survives ``Add``
    and only raises ``UnicodeDecodeError`` later, wherever something reads
    the descriptor's ``name``. Checking every string field here makes upb
    fail at the same boundary pure-Python does.

    Raises:
        DescriptorPoolError: A string is not UTF-8, or a file needs editions (:func:`_honoured`).
    """
    from protokit._fieldview import first_undecodable_string

    # The walk lives in the layer-0 seam so the payload decode seams share it.
    hit = first_undecodable_string(fds)
    if hit is not None:
        field, value = hit
        raise DescriptorPoolError(f"{field.full_name} is not valid UTF-8: {value[:64]!r}")
    return _all_honoured(fds)


def _ready_to_parse(message_class: type) -> type:
    """``message_class``, once every repeated extension its messages can hold has a class.

    Under pure-Python a payload holding a repeated message-typed extension
    otherwise fails to parse with ``AttributeError``; see
    :func:`protokit._fieldview.build_extension_classes`. Defined down here
    because published docs cite line numbers in this file.
    """
    from protokit._fieldview import build_extension_classes

    build_extension_classes(message_class.DESCRIPTOR)  # type: ignore[attr-defined]
    return message_class


# Down here, import included, because published docs cite line numbers in this file.
import functools  # noqa: E402


class EditionsNotImplementedError(DescriptorPoolError):
    """An editions file, on a protobuf runtime that does not implement editions.

    protobuf 4.25 loads an ``edition = "2023"`` file without complaint and
    reads every feature in it as unset: a ``DELIMITED`` field is an ordinary
    length-prefixed message, a ``LEGACY_REQUIRED`` field is not required, and
    a scalar field with explicit presence has none. Every answer protokit gave about
    such a schema there was computed from a different schema, so the file is
    refused instead. protobuf 5.26 and later implement editions.
    """

    def __init__(self, file_name: str) -> None:
        from google.protobuf import __version__ as protobuf_version

        self.file_name = file_name
        super().__init__(
            f"{file_name!r} is an editions file, and protobuf "
            f"{protobuf_version} does not implement editions: it would read the "
            f"file's features as unset. protobuf 5.26 or later is needed."
        )


def _honoured(fd: descriptor_pb2.FileDescriptorProto) -> descriptor_pb2.FileDescriptorProto:
    """Return ``fd``, or raise if it is an editions file this runtime cannot honour.

    Raises:
        EditionsNotImplementedError: see there.
    """
    if _declares_an_edition(fd) and not _implements_editions():
        raise EditionsNotImplementedError(fd.name)
    return fd


# EDITION_UNKNOWN, EDITION_PROTO2 and EDITION_PROTO3: what a proto2 or proto3
# file may carry. By number: protobuf 4.25 does not name the last two.
_NOT_AN_EDITION = (0, 998, 999)


def _declares_an_edition(fd: descriptor_pb2.FileDescriptorProto) -> bool:
    """Whether ``fd`` says it is an editions file, in either of the two places it can.

    protoc writes both ``syntax = "editions"`` and ``edition``. A file built by
    hand may carry one: pure-Python 5.27 applies features for either alone,
    and protobuf 4.25 ignores them for either alone.
    """
    return fd.syntax == "editions" or (
        fd.HasField("edition") and fd.edition not in _NOT_AN_EDITION
    )


def _all_honoured(fds: descriptor_pb2.FileDescriptorSet) -> descriptor_pb2.FileDescriptorSet:
    """Return ``fds``, or raise for the first file in it that :func:`_honoured` refuses."""
    for fd in fds.file:
        _honoured(fd)
    return fds


def _implements_editions() -> bool:
    """Whether this protobuf runtime applies the features an editions file declares.

    Asked once, of the runtime and not of its version number (see
    :func:`_editions_probe`). With no stack left to ask, the answer is yes and
    is not kept: a schema is not refused on a guess, and the next call asks again.
    """
    try:
        return _editions_probe()
    except RecursionError:
        return True


@functools.cache
def _editions_probe() -> bool:
    """Build one ``DELIMITED`` field in a pool of its own and say whether it is a group.

    It is on a runtime that implements editions, and a plain message on one
    that does not. A runtime that refuses the file outright does not implement
    them either.
    """
    field_type = descriptor_pb2.FieldDescriptorProto
    probe = descriptor_pb2.FileDescriptorProto(
        name="protokit/_editions_probe.proto", package="protokit_editions_probe",
        syntax="editions",
    )
    try:
        probe.edition = descriptor_pb2.EDITION_2023
        message = probe.message_type.add(name="Probe")
        message.nested_type.add(name="Inner")
        field = message.field.add(
            name="inner", number=1, type=field_type.TYPE_MESSAGE,
            label=field_type.LABEL_OPTIONAL, type_name=".protokit_editions_probe.Probe.Inner",
        )
        # features { message_encoding: DELIMITED }, written as bytes: a runtime
        # that predates editions has no such field to set.
        field.options.MergeFromString(bytes.fromhex("aa01022802"))
        pool = descriptor_pool.DescriptorPool()
        pool.AddSerializedFile(probe.SerializeToString())
        built = pool.FindMessageTypeByName("protokit_editions_probe.Probe").fields_by_name["inner"]
    except RecursionError:
        raise  # not an answer about the runtime, and not to be cached as one
    except Exception:  # whatever shape the refusal takes, it is a refusal
        return False
    implemented: bool = built.type == field_type.TYPE_GROUP
    return implemented



# An extension typed as a map entry. Protobuf has no map extensions and no
# compiler writes one from ``map<K, V>``, but a hand-written set can declare
# one, and protoxy and protoc 3.21 compile one written out with an explicit
# ``option map_entry = true``. Under upb a payload that sets it reaches a map
# container the runtime cannot build and kills the process, so every loader
# refuses the schema. The check reads the descriptors the runtime resolved,
# so a type name means what it means to the runtime: every file added through
# :func:`add_and_resolve`, and lint's descriptor-set loader, which adds files
# itself, through :func:`_refuse_map_typed_extensions_in`.


class MapTypedExtensionError(DescriptorPoolError):
    """A schema declares an extension whose type is a map entry.

    A property of the schema, not of how it was compiled or loaded: another
    compiler or loader would build the same extension.
    """


def _refuse_map_typed_extensions(file: Any) -> None:
    """Raise if the resolved file declares an extension typed as a map entry."""
    pending = list(file.message_types_by_name.values())
    extensions = list(file.extensions_by_name.values())
    while pending:
        message = pending.pop()
        extensions.extend(message.extensions)
        pending.extend(message.nested_types)
    for ext in extensions:
        target = ext.message_type
        # Pure-Python hands back an enum here for a message-typed field naming one.
        if isinstance(target, Descriptor) and target.GetOptions().map_entry:
            raise MapTypedExtensionError(
                f"extension {ext.full_name} in {file.name!r} is typed as the map entry "
                f"{target.full_name}; protobuf has no map extensions"
            )


def _refuse_map_typed_extensions_in(files: Iterable[descriptor_pb2.FileDescriptorProto]) -> None:
    """Add ``files`` to a scratch pool in order and refuse a map-typed extension.

    For a loader that adds files itself. The files go in the order that loader
    adds them, because upb resolves a relative type name against what the pool
    holds at the time. A set that does not build stops the check: the loader
    reports why when it adds the same files.
    """
    pool = descriptor_pool.DescriptorPool()
    for fd in files:
        try:
            pool.Add(fd)
            built = pool.FindFileByName(fd.name)
        except Exception:  # whatever the runtime refuses, the loader will too
            return
        _refuse_map_typed_extensions(built)


def _refusal_kind(exc: Exception) -> type[DescriptorPoolError]:
    """The error :func:`add_and_resolve` raises for ``exc``: a map-typed
    extension keeps its own type, so a compile path can tell it from a file
    one compiler could not build."""
    return type(exc) if isinstance(exc, MapTypedExtensionError) else DescriptorPoolError


# Imported here, not at the top: published docs cite line numbers in this file.
from collections.abc import Iterable  # noqa: E402
from typing import Any  # noqa: E402
