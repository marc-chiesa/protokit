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
            f"cyclic file dependency among: {', '.join(remaining)}"
        )
    return ordered


def build_pool(
    fds: descriptor_pb2.FileDescriptorSet,
) -> descriptor_pool.DescriptorPool:
    """Build a fresh, isolated ``DescriptorPool`` from a ``FileDescriptorSet``.

    Files are added in dependency order into a brand-new pool — never the
    default pool — so concurrent pools may hold conflicting versions of the
    same fully-qualified type without collision.
    """
    pool = descriptor_pool.DescriptorPool()
    for fd in sort_files_by_dependency(list(fds.file)):
        try:
            pool.Add(fd)
        except TypeError as exc:
            # upb raises a bare TypeError when a descriptor cannot be built into
            # the pool — e.g. a field referencing a symbol no file in the set
            # defines (a dangling symbol with no *missing-file* dependency, which
            # the topo-sort cannot detect). Re-raise as the typed family so the
            # documented "typed library exceptions, never raw" contract holds for
            # every caller, including the storage register boundary.
            raise DescriptorPoolError(
                f"could not build file {fd.name!r} into the descriptor pool: {exc}"
            ) from exc
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
    except DecodeError as exc:
        raise DescriptorPoolError(
            f"could not parse FileDescriptorSet bytes: {exc}"
        ) from exc
    return build_pool(fds)


def load_pool_from_path(path: Path) -> descriptor_pool.DescriptorPool:
    """Read a ``.descriptor_set`` file and build an isolated pool.

    The caller is responsible for validating the path exists; a malformed
    file surfaces as a protobuf parse exception.
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
    return cls
