"""Contract test for the ``_fieldview`` seam (U3: closes V19 and the differ's half of V26).

The compat checker's half of V26 stayed open after U3, because the checker
read only ``by_name``; it closed when the checker began pairing declared
extensions too (``_fieldview.data_extensions``). The contract below is about
the owner, so it could not see a consumer that never asked.

**Why a contract test and not a bypass guard (KTD1).** The two seam failure
modes need different guards. Bypass drift — a correct owner exists and a
call site goes around it — is caught by enumerating call sites. That is not
what happened here: all four consumers already routed through
``_descriptors.get_field_map``; nobody bypassed anything. The owner's
*contract* was wrong, and every consumer inherited the same blind spot
uniformly. A bypass guard is structurally blind to that, and a new owner
module would reproduce the identical single point of uniform failure under
a new name. So the primary guard is this: a differential check that the
owner's enumeration is **complete** against a descriptor corpus, so the
next wrong default fails a test instead of propagating to four consumers.

The corpus is built from ``descriptor_pb2`` directly rather than through
``tests/proto_builder.py`` so each shape's syntax, labels, and extension
ranges are visible in this file — a corpus whose construction is itself
indirect makes a completeness claim hard to audit.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from google.protobuf import descriptor as d
from google.protobuf import descriptor_pb2, descriptor_pool, message_factory
from google.protobuf.message import Message

from protokit._fieldview import (
    FieldView,
    StringWalk,
    data_extensions,
    extension_key,
    first_undecodable_string,
    is_map_field,
    is_message_like,
    map_entry,
    may_hold_unvalidated_string,
    same_message_kind,
)
from tests._editions import requires_editions
from tests._pure_python_inventory import skip_under_pure_python

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = _REPO_ROOT / "src" / "protokit"

_FD = d.FieldDescriptor


def _corpus_pool() -> descriptor_pool.DescriptorPool:
    """Build the descriptor corpus: proto2/proto3, map, repeated, oneof, nested, extensions."""
    pool = descriptor_pool.DescriptorPool()

    # --- proto2: extension ranges, a required field, nested + top-level extensions ---
    p2 = descriptor_pb2.FileDescriptorProto(name="c2.proto", package="c2", syntax="proto2")
    msg = p2.message_type.add(name="Msg")
    msg.field.add(name="req", number=1, type=_FD.TYPE_INT32, label=_FD.LABEL_REQUIRED)
    msg.field.add(name="opt", number=2, type=_FD.TYPE_STRING, label=_FD.LABEL_OPTIONAL)
    msg.field.add(name="rep", number=3, type=_FD.TYPE_INT64, label=_FD.LABEL_REPEATED)
    msg.extension_range.add(start=100, end=600)
    # nested message + a field referencing it
    nested = msg.nested_type.add(name="Inner")
    nested.field.add(name="leaf", number=1, type=_FD.TYPE_BOOL, label=_FD.LABEL_OPTIONAL)
    msg.field.add(
        name="inner", number=4, type=_FD.TYPE_MESSAGE, label=_FD.LABEL_OPTIONAL,
        type_name=".c2.Msg.Inner",
    )
    # an extension DECLARED INSIDE Msg that extends Msg
    msg.extension.add(
        name="ext_nested", number=101, type=_FD.TYPE_BOOL,
        label=_FD.LABEL_OPTIONAL, extendee=".c2.Msg",
    )
    # TOP-LEVEL extensions that also extend Msg, declared HIGHEST NUMBER
    # FIRST: ``FindAllExtensions`` returns declaration order, so the corpus
    # must not already be in number order or the ordering pin below passes
    # with the sort removed.
    p2.extension.add(
        name="ext_hi", number=102, type=_FD.TYPE_INT32,
        label=_FD.LABEL_OPTIONAL, extendee=".c2.Msg",
    )
    p2.extension.add(
        name="ext_top", number=100, type=_FD.TYPE_STRING,
        label=_FD.LABEL_OPTIONAL, extendee=".c2.Msg",
    )
    # an extension declared inside Msg that extends something ELSE — must NOT
    # appear in Msg's extension set, only in Other's.
    other = p2.message_type.add(name="Other")
    other.field.add(name="x", number=1, type=_FD.TYPE_INT32, label=_FD.LABEL_OPTIONAL)
    other.extension_range.add(start=100, end=200)
    msg.extension.add(
        name="ext_on_other", number=100, type=_FD.TYPE_INT32,
        label=_FD.LABEL_OPTIONAL, extendee=".c2.Other",
    )
    pool.Add(p2)

    # --- proto3: oneof, map, proto3-optional ---
    p3 = descriptor_pb2.FileDescriptorProto(name="c3.proto", package="c3", syntax="proto3")
    m3 = p3.message_type.add(name="Msg3")
    m3.field.add(name="plain", number=1, type=_FD.TYPE_STRING, label=_FD.LABEL_OPTIONAL)
    m3.oneof_decl.add(name="choice")
    m3.field.add(
        name="pick_a", number=2, type=_FD.TYPE_INT32,
        label=_FD.LABEL_OPTIONAL, oneof_index=0,
    )
    m3.field.add(
        name="pick_b", number=3, type=_FD.TYPE_STRING,
        label=_FD.LABEL_OPTIONAL, oneof_index=0,
    )
    entry = m3.nested_type.add(name="TagsEntry")
    entry.options.map_entry = True
    entry.field.add(name="key", number=1, type=_FD.TYPE_STRING, label=_FD.LABEL_OPTIONAL)
    entry.field.add(name="value", number=2, type=_FD.TYPE_INT32, label=_FD.LABEL_OPTIONAL)
    m3.field.add(
        name="tags", number=4, type=_FD.TYPE_MESSAGE,
        label=_FD.LABEL_REPEATED, type_name=".c3.Msg3.TagsEntry",
    )
    pool.Add(p3)
    return pool


@pytest.fixture(scope="module")
def pool() -> descriptor_pool.DescriptorPool:
    return _corpus_pool()


_CORPUS_MESSAGES = ("c2.Msg", "c2.Msg.Inner", "c2.Other", "c3.Msg3", "c3.Msg3.TagsEntry")


class TestEnumerationCompleteness:
    """The property that failed before U3: the owner must reach everything."""

    @pytest.mark.parametrize("full_name", _CORPUS_MESSAGES)
    def test_by_name_and_by_number_index_every_declared_field(
        self, pool: descriptor_pool.DescriptorPool, full_name: str,
    ) -> None:
        """Neither index may drop a declared field, and they must agree.

        This is the completeness half of the contract. A future
        implementation that filtered, sorted-and-truncated, or deduplicated
        by the wrong key fails here rather than silently under-reporting to
        four consumers.
        """
        desc = pool.FindMessageTypeByName(full_name)
        view = FieldView.of(desc)
        declared = list(desc.fields)
        assert set(view.by_name) == {f.name for f in declared}
        assert set(view.by_number) == {f.number for f in declared}
        assert len(view.by_name) == len(view.by_number) == len(declared)
        for f in declared:
            assert view.by_name[f.name] is f
            assert view.by_number[f.number] is f

    def test_extensions_are_reachable_at_all(
        self, pool: descriptor_pool.DescriptorPool,
    ) -> None:
        """The V19 regression in contract form.

        ``Descriptor.fields`` never contains extensions, so the pre-U3 owner
        could not reach a declared extension by any route — a proto2 message
        compared equal on an extension no matter what it carried. The owner
        must surface them.
        """
        view = FieldView.of(pool.FindMessageTypeByName("c2.Msg"))
        assert [e.full_name for e in view.extensions] == [
            "c2.ext_top", "c2.Msg.ext_nested", "c2.ext_hi",
        ]

    def test_extensions_means_extending_this_message_not_declared_inside_it(
        self, pool: descriptor_pool.DescriptorPool,
    ) -> None:
        """``FindAllExtensions`` semantics, pinned deliberately.

        ``Descriptor.extensions`` (declared *inside* this message) and
        ``pool.FindAllExtensions`` (extending this message) are different
        sets, and only the second is what can appear on the wire for this
        type. ``c2.Msg`` declares ``ext_on_other`` inside itself but that
        extension extends ``c2.Other`` — it belongs to Other's set, not
        Msg's. Confusing the two is the obvious wrong implementation.
        """
        msg = pool.FindMessageTypeByName("c2.Msg")
        other = pool.FindMessageTypeByName("c2.Other")
        declared_inside_msg = {e.full_name for e in msg.extensions}
        assert "c2.Msg.ext_on_other" in declared_inside_msg

        extending_msg = {e.full_name for e in FieldView.of(msg).extensions}
        assert "c2.Msg.ext_on_other" not in extending_msg

        extending_other = {e.full_name for e in FieldView.of(other).extensions}
        assert extending_other == {"c2.Msg.ext_on_other"}

    def test_extensions_are_ordered_by_field_number(
        self, pool: descriptor_pool.DescriptorPool,
    ) -> None:
        """Deterministic output without the caller re-sorting.

        The corpus declares ``ext_hi`` (102) before ``ext_top`` (100), so the
        pool's raw order is not number order and this fails if the sort goes.
        """
        view = FieldView.of(pool.FindMessageTypeByName("c2.Msg"))
        raw = [e.number for e in pool.FindAllExtensions(view.descriptor)]
        assert raw != sorted(raw), "corpus no longer exercises the sort"
        numbers = [e.number for e in view.extensions]
        assert numbers == sorted(numbers)

    def test_declared_and_extension_namespaces_stay_separate(
        self, pool: descriptor_pool.DescriptorPool,
    ) -> None:
        """The documented namespace decision, asserted so a change is deliberate.

        ``by_name``/``by_number`` are declared fields only. An extension's
        identity is its fully-qualified name and protobuf permits its short
        name to collide with a declared field's, so merging the two maps
        could shadow a real field. ``--where`` / ``--fields`` path resolution
        depends on this: it splits on ``.`` and requires identifier
        segments, so a dotted extension name is unreachable there by
        construction.
        """
        view = FieldView.of(pool.FindMessageTypeByName("c2.Msg"))
        ext_numbers = {e.number for e in view.extensions}
        assert not (set(view.by_number) & ext_numbers)
        for ext in view.extensions:
            assert "." in ext.full_name
            assert ext.full_name not in view.by_name


class TestMapEntry:
    def test_map_field_yields_key_and_value(
        self, pool: descriptor_pool.DescriptorPool,
    ) -> None:
        view = FieldView.of(pool.FindMessageTypeByName("c3.Msg3"))
        tags = view.by_name["tags"]
        assert is_map_field(tags)
        entry = map_entry(tags)
        assert entry is not None
        assert entry.key.name == "key" and entry.key.type == _FD.TYPE_STRING
        assert entry.value.name == "value" and entry.value.type == _FD.TYPE_INT32

    @pytest.mark.parametrize("field_name", ["plain", "pick_a"])
    def test_non_map_field_yields_none(
        self, pool: descriptor_pool.DescriptorPool, field_name: str,
    ) -> None:
        view = FieldView.of(pool.FindMessageTypeByName("c3.Msg3"))
        assert map_entry(view.by_name[field_name]) is None

    def test_repeated_message_that_is_not_a_map_yields_none(
        self, pool: descriptor_pool.DescriptorPool,
    ) -> None:
        """A repeated message field is the near-miss shape for ``map_entry``."""
        view = FieldView.of(pool.FindMessageTypeByName("c2.Msg"))
        assert map_entry(view.by_name["rep"]) is None
        assert map_entry(view.by_name["inner"]) is None


class TestViewIsImmutable:
    def test_indexes_reject_mutation(self, pool: descriptor_pool.DescriptorPool) -> None:
        """``frozen=True`` blocks rebinding; the proxies block content mutation."""
        view = FieldView.of(pool.FindMessageTypeByName("c2.Msg"))
        with pytest.raises(TypeError):
            view.by_name["injected"] = view.by_name["opt"]  # type: ignore[index]
        with pytest.raises(TypeError):
            view.by_number[999] = view.by_name["opt"]  # type: ignore[index]

    def test_indexes_are_built_lazily_and_cached(
        self, pool: descriptor_pool.DescriptorPool,
    ) -> None:
        """Each index is computed on first access and reused thereafter.

        The differ builds a view per message pair and reads only ``by_name``,
        so building ``by_number`` eagerly was measurable waste. Identity, not
        equality, is the assertion — equal-but-rebuilt would mean the cache is
        not working.
        """
        view = FieldView.of(pool.FindMessageTypeByName("c2.Msg"))
        assert view.by_name is view.by_name
        assert view.by_number is view.by_number
        assert set(view.by_name) == {f.name for f in view.descriptor.fields}
        assert set(view.by_number) == {f.number for f in view.descriptor.fields}

    @pytest.mark.parametrize(
        ("full_name", "expected"), [("c2.Msg", True), ("c3.Msg3", False)],
    )
    def test_has_extension_ranges_reports_whether_extensions_are_possible(
        self, pool: descriptor_pool.DescriptorPool, full_name: str, expected: bool,
    ) -> None:
        """The guard the differ uses to skip extension discovery entirely.

        A message declaring no extension range cannot carry a set extension,
        so the differ may skip walking ``ListFields`` for it. If this ever
        reports False for a message that CAN carry one, the differ silently
        stops comparing extensions — so it is asserted here rather than
        trusted.
        """
        view = FieldView.of(pool.FindMessageTypeByName(full_name))
        assert view.has_extension_ranges is expected
        if not expected:
            assert view.extensions == ()


# --- Scoped enumeration guard (KTD2) ---------------------------------------
#
# DECIDABILITY: this predicate IS statically decidable, with a stated
# over-approximation. It matches the attribute access ``<expr>.fields`` in
# an ``ast.For`` iterator or a comprehension — a syntactic shape, not a
# type- or taint-level claim. It therefore also matches a ``.fields``
# attribute on some unrelated object. That is a deliberate false-positive
# direction: in the migrated modules there is no such other ``.fields``, and
# a guard that over-approximates fails loudly rather than silently, which is
# the failure direction KTD2 requires.
#
# SCOPE: exactly the modules U3 migrates. A guard over all of
# ``src/protokit/`` would be red on day one and force an allowlist, and an
# allowlist is a one-line bypass — the very drift this release exists to
# stop.
#
# TODO(U17): direct field enumeration ALSO lives in the modules named in
# ``_UNMIGRATED`` below, which U3 does not migrate. Widening this guard to all
# of ``src/protokit/`` is a hard precondition of U17; do not add an allowlist
# instead.
#
# ``_UNMIGRATED`` is asserted against the tree, not maintained by hand. The
# first draft of this comment listed the remaining sites in prose and was
# wrong in both directions — it named two modules that enumerate nothing and
# omitted ``schema/rules.py``, whose ``reserved_field_reused`` has the very
# ``for fd in ...fields: if fd.is_extension: continue`` shape that V19 was
# (extensions now reach it through ``data_extensions``, but its field loop
# still enumerates directly; a U17 item). A
# hand-written list inside the guard that exists to prevent sibling
# blindness had itself gone blind. So the set below must equal what the
# walker finds: a module migrated to ``FieldView`` is removed from it (the
# ratchet), and a module that starts enumerating directly must be added to
# it on purpose, in a diff a reviewer sees.
#
# The walker's second draft matched only ``for x in <expr>.fields`` and the
# comprehension form, and so missed ``schema/lint/engine.py``, which
# enumerates through a sorting wrapper (``self._sorted_by_name(msg.fields)``)
# — a real V19-shaped blind spot: FIELD lint rules are dispatched over
# ``message.fields`` only, so no lint rule ever sees an extension (U17).
# It now matches ``.fields`` anywhere inside an iterator expression, as an
# argument to a builtin that consumes an iterable, and under a subscript.
# That over-approximates on purpose (KTD2): it also catches counting, like
# ``forensics/_match.py``'s ``len(descriptor.fields)``, which is
# extension-blind in the same way even though it never iterates.
_MIGRATED = (
    "message/differ.py",
    "schema/checker.py",
    "storage/_where.py",
    "storage/_fields.py",
    "_descriptors.py",
)
_UNMIGRATED = frozenset({
    "forensics/_drift.py",
    "forensics/_match.py",
    "schema/lint/engine.py",
    "schema/lint/rules/imports.py",
    "schema/rules.py",
    "storage/_columnar.py",
})
# The one sanctioned enumeration site: ``FieldView.of`` and its indexes.
_OWNER = "_fieldview.py"


# Builtins that consume an iterable: ``.fields`` handed to any of these is an
# enumeration even when no ``for`` is in sight.
_ITERABLE_CONSUMERS = frozenset({
    "list", "tuple", "set", "frozenset", "dict", "sorted", "reversed", "enumerate",
    "len", "map", "filter", "zip", "any", "all", "sum", "min", "max", "iter", "next",
})


def _direct_enumeration_lines(path: Path) -> list[int]:
    """Lines where the module enumerates ``<expr>.fields`` directly.

    A hit is a ``.fields`` attribute anywhere inside a ``for`` / comprehension
    iterator expression (which covers wrappers such as ``sorted(x.fields)`` or
    ``self._sorted_by_name(x.fields)``), as an argument to a builtin that
    consumes an iterable, or under a subscript.
    """
    tree = ast.parse(path.read_text())
    hits: set[int] = set()

    def _mentions_fields(node: ast.AST) -> bool:
        return any(
            isinstance(sub, ast.Attribute) and sub.attr == "fields" for sub in ast.walk(node)
        )

    def _enumerates(node: ast.AST) -> bool:
        if isinstance(node, ast.For):
            return _mentions_fields(node.iter)
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            return any(_mentions_fields(gen.iter) for gen in node.generators)
        if isinstance(node, ast.Call):
            return (
                isinstance(node.func, ast.Name)
                and node.func.id in _ITERABLE_CONSUMERS
                and any(_mentions_fields(arg) for arg in node.args)
            )
        if isinstance(node, ast.Subscript):
            return _mentions_fields(node.value)
        return False

    for node in ast.walk(tree):
        if _enumerates(node):
            hits.add(node.lineno)
    return sorted(hits)


@pytest.mark.parametrize("rel", _MIGRATED)
def test_migrated_modules_do_not_enumerate_fields_directly(rel: str) -> None:
    """A migrated consumer must go through ``FieldView``, not ``descriptor.fields``.

    ``FieldView.of`` itself is the one sanctioned enumeration site and lives
    in ``_fieldview.py``, which is deliberately outside this list.
    """
    path = _SRC / rel
    assert path.exists(), f"guard names a path that no longer exists: {rel}"
    hits = _direct_enumeration_lines(path)
    assert not hits, (
        f"{rel} enumerates `.fields` directly at line(s) {hits}; route it through "
        "protokit._fieldview.FieldView so the enumeration contract has one owner."
    )


def test_direct_enumeration_lives_only_in_the_owner_and_the_unmigrated_set() -> None:
    """The remaining sites are derived from the tree and must equal ``_UNMIGRATED``.

    Two failure directions, both deliberate: a module that migrated to
    ``FieldView`` fails here until it is removed from the set (so the U17
    precondition is tracked by the test, not by prose), and a module that
    starts enumerating ``.fields`` directly fails here until it is added
    (so a new blind spot is a reviewed decision, not a silent one).
    """
    found = {
        str(path.relative_to(_SRC))
        for path in sorted(_SRC.rglob("*.py"))
        if _direct_enumeration_lines(path)
    }
    assert found == _UNMIGRATED | {_OWNER}, (
        f"direct `.fields` enumeration sites drifted from _UNMIGRATED: "
        f"unexpected={sorted(found - _UNMIGRATED - {_OWNER})}, "
        f"no longer enumerating={sorted(_UNMIGRATED - found)}"
    )
    assert not (_UNMIGRATED & set(_MIGRATED))


def test_guard_detects_an_injected_violation() -> None:
    """The guard is non-vacuous: it must see a violation when one exists.

    A structural guard that cannot be shown to fire is a comment. This
    injects the exact shape into a synthetic module rather than trusting the
    walker by inspection.
    """
    import tempfile

    src = "def f(desc):\n    for field in desc.fields:\n        yield field\n"
    with tempfile.TemporaryDirectory() as tmp:
        probe = Path(tmp) / "probe.py"
        probe.write_text(src)
        assert _direct_enumeration_lines(probe) == [2]

        comp = Path(tmp) / "probe2.py"
        comp.write_text("def g(desc):\n    return [f for f in desc.fields]\n")
        assert _direct_enumeration_lines(comp) == [2]

        # The shapes the second draft missed: a wrapper call in the iterator,
        # a consuming builtin, and a subscript.
        wrapped = Path(tmp) / "probe3.py"
        wrapped.write_text(
            "def w(self, message):\n"
            "    for field in self._sorted_by_name(message.fields):\n"
            "        yield field\n"
            "    for field in sorted(message.fields, key=lambda f: f.name):\n"
            "        yield field\n"
            "    return len(message.fields), message.fields[0]\n"
        )
        assert _direct_enumeration_lines(wrapped) == [2, 4, 6]

        clean = Path(tmp) / "clean.py"
        clean.write_text(
            "def h(view):\n"
            "    return list(view.by_name.values()), view.fields_by_name['x']\n"
        )
        assert _direct_enumeration_lines(clean) == []


# --- Message-kind, extension-key and string-walk helpers ---
#
# Checker, rules, differ and the payload decode seams each asked "is this field a
# message?" and "is any string in this message undecodable?" in their own words,
# and the answers drifted: several sites tested ``TYPE_MESSAGE`` alone and missed
# groups and editions DELIMITED fields, which are ``TYPE_GROUP``. These helpers
# give each question one owner.

_FS = descriptor_pb2.FeatureSet


def _editions_file(name: str, package: str) -> descriptor_pb2.FileDescriptorProto:
    requires_editions()
    return descriptor_pb2.FileDescriptorProto(
        name=name, package=package, syntax="editions", edition=descriptor_pb2.EDITION_2023,
    )


def _map_entry_type(
    parent: descriptor_pb2.DescriptorProto, name: str, key_type: int, value_type: int,
    value_type_name: str = "",
) -> None:
    entry = parent.nested_type.add(name=name)
    entry.options.map_entry = True
    entry.field.add(name="key", number=1, type=key_type, label=_FD.LABEL_OPTIONAL)
    value = entry.field.add(name="value", number=2, type=value_type, label=_FD.LABEL_OPTIONAL)
    if value_type_name:  # an explicitly empty type_name is still "set" to upb
        value.type_name = value_type_name


def _kind_pool() -> descriptor_pool.DescriptorPool:
    """A proto2 message field and group, and an editions file whose messages are DELIMITED."""
    pool = descriptor_pool.DescriptorPool()

    k2 = descriptor_pb2.FileDescriptorProto(name="k2.proto", package="k2", syntax="proto2")
    k2.message_type.add(name="Leaf").field.add(
        name="x", number=1, type=_FD.TYPE_INT32, label=_FD.LABEL_OPTIONAL,
    )
    p2 = k2.message_type.add(name="P2")
    p2.field.add(
        name="msg", number=1, type=_FD.TYPE_MESSAGE, label=_FD.LABEL_OPTIONAL,
        type_name=".k2.Leaf",
    )
    p2.nested_type.add(name="Grp").field.add(
        name="x", number=1, type=_FD.TYPE_INT32, label=_FD.LABEL_OPTIONAL,
    )
    p2.field.add(
        name="grp", number=2, type=_FD.TYPE_GROUP, label=_FD.LABEL_OPTIONAL,
        type_name=".k2.P2.Grp",
    )
    p2.field.add(name="s", number=3, type=_FD.TYPE_STRING, label=_FD.LABEL_OPTIONAL)
    pool.Add(k2)

    # File-level DELIMITED turns every singular and repeated message field into
    # TYPE_GROUP, but a map field and its value stay TYPE_MESSAGE.
    k3 = _editions_file("k3.proto", "k3")
    k3.options.features.message_encoding = _FS.DELIMITED
    k3.message_type.add(name="Leaf").field.add(
        name="x", number=1, type=_FD.TYPE_INT32, label=_FD.LABEL_OPTIONAL,
    )
    d3 = k3.message_type.add(name="D")
    d3.field.add(
        name="delim", number=1, type=_FD.TYPE_MESSAGE, label=_FD.LABEL_OPTIONAL,
        type_name=".k3.Leaf",
    )
    _map_entry_type(d3, "MEntry", _FD.TYPE_STRING, _FD.TYPE_MESSAGE, ".k3.Leaf")
    d3.field.add(
        name="m", number=2, type=_FD.TYPE_MESSAGE, label=_FD.LABEL_REPEATED,
        type_name=".k3.D.MEntry",
    )
    pool.Add(k3)
    return pool


class TestMessageKind:
    @pytest.fixture(scope="class")
    def fields(self) -> dict[str, d.FieldDescriptor]:
        pool = _kind_pool()
        p2 = FieldView.of(pool.FindMessageTypeByName("k2.P2")).by_name
        d3 = FieldView.of(pool.FindMessageTypeByName("k3.D")).by_name
        entry = map_entry(d3["m"])
        assert entry is not None
        return {
            "msg": p2["msg"], "grp": p2["grp"], "s": p2["s"],
            "delim": d3["delim"], "map": d3["m"], "map_value": entry.value,
        }

    def test_the_corpus_has_the_shapes_it_claims(
        self, fields: dict[str, d.FieldDescriptor],
    ) -> None:
        """A DELIMITED field is TYPE_GROUP; a map field and its value never are."""
        assert fields["grp"].type == _FD.TYPE_GROUP
        assert fields["delim"].type == _FD.TYPE_GROUP
        assert fields["msg"].type == _FD.TYPE_MESSAGE
        assert fields["map"].type == _FD.TYPE_MESSAGE
        assert fields["map_value"].type == _FD.TYPE_MESSAGE

    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("msg", True), ("grp", True), ("delim", True), ("map", True),
            ("map_value", True), ("s", False),
        ],
    )
    def test_is_message_like(
        self, fields: dict[str, d.FieldDescriptor], name: str, expected: bool,
    ) -> None:
        assert is_message_like(fields[name]) is expected

    @pytest.mark.parametrize(
        ("left", "right", "expected"),
        [
            pytest.param("msg", "msg", True, id="message-message"),
            pytest.param("grp", "delim", True, id="proto2-group-editions-delimited"),
            pytest.param("delim", "grp", True, id="editions-delimited-proto2-group"),
            pytest.param("grp", "msg", False, id="group-message"),
            pytest.param("msg", "grp", False, id="message-group"),
            pytest.param("delim", "msg", False, id="delimited-message"),
            pytest.param("map_value", "delim", False, id="map-value-is-not-a-group"),
            pytest.param("map_value", "msg", True, id="map-value-is-a-message"),
            pytest.param("s", "s", False, id="string-string"),
            pytest.param("s", "msg", False, id="string-message"),
        ],
    )
    def test_same_message_kind_needs_the_same_kind_on_both_sides(
        self, fields: dict[str, d.FieldDescriptor], left: str, right: str, expected: bool,
    ) -> None:
        """KTD2: descend only message↔message or group↔group; a mixed pair does not."""
        assert same_message_kind(fields[left], fields[right]) is expected


class TestExtensionKey:
    @pytest.mark.parametrize(
        ("full_name", "expected"),
        [("c2.ext_top", "(c2.ext_top)"), ("c2.Msg.ext_nested", "(c2.Msg.ext_nested)")],
    )
    def test_key_is_the_parenthesised_full_name(
        self, pool: descriptor_pool.DescriptorPool, full_name: str, expected: str,
    ) -> None:
        """The spelling a one-segment ``FieldPath`` accepts, and never a declared name."""
        ext = pool.FindExtensionByName(full_name)
        assert extension_key(ext) == expected
        declared = FieldView.of(pool.FindMessageTypeByName("c2.Msg")).by_name
        assert extension_key(ext) not in declared


def _walk_pool() -> descriptor_pool.DescriptorPool:
    """Every place a proto2 string can sit: top level, nested, repeated, map, group, extension."""
    pool = descriptor_pool.DescriptorPool()
    w2 = descriptor_pb2.FileDescriptorProto(name="w2.proto", package="w2", syntax="proto2")
    w2.message_type.add(name="Leaf").field.add(
        name="s", number=1, type=_FD.TYPE_STRING, label=_FD.LABEL_OPTIONAL,
    )
    root = w2.message_type.add(name="Root")
    root.field.add(name="s", number=1, type=_FD.TYPE_STRING, label=_FD.LABEL_OPTIONAL)
    root.field.add(
        name="sub", number=2, type=_FD.TYPE_MESSAGE, label=_FD.LABEL_OPTIONAL,
        type_name=".w2.Leaf",
    )
    root.field.add(name="rs", number=3, type=_FD.TYPE_STRING, label=_FD.LABEL_REPEATED)
    _map_entry_type(root, "MEntry", _FD.TYPE_STRING, _FD.TYPE_STRING)
    root.field.add(
        name="m", number=4, type=_FD.TYPE_MESSAGE, label=_FD.LABEL_REPEATED,
        type_name=".w2.Root.MEntry",
    )
    root.field.add(
        name="rsub", number=5, type=_FD.TYPE_MESSAGE, label=_FD.LABEL_REPEATED,
        type_name=".w2.Leaf",
    )
    root.nested_type.add(name="G").field.add(
        name="s", number=1, type=_FD.TYPE_STRING, label=_FD.LABEL_OPTIONAL,
    )
    root.field.add(
        name="g", number=6, type=_FD.TYPE_GROUP, label=_FD.LABEL_OPTIONAL,
        type_name=".w2.Root.G",
    )
    _map_entry_type(root, "MlEntry", _FD.TYPE_INT32, _FD.TYPE_MESSAGE, ".w2.Leaf")
    root.field.add(
        name="ml", number=7, type=_FD.TYPE_MESSAGE, label=_FD.LABEL_REPEATED,
        type_name=".w2.Root.MlEntry",
    )
    root.extension_range.add(start=100, end=200)
    w2.extension.add(
        name="ext", number=100, type=_FD.TYPE_STRING, label=_FD.LABEL_OPTIONAL,
        extendee=".w2.Root",
    )
    pool.Add(w2)

    w3 = descriptor_pb2.FileDescriptorProto(name="w3.proto", package="w3", syntax="proto3")
    p3 = w3.message_type.add(name="P3")
    p3.field.add(name="s", number=1, type=_FD.TYPE_STRING, label=_FD.LABEL_OPTIONAL)
    _map_entry_type(p3, "MEntry", _FD.TYPE_STRING, _FD.TYPE_STRING)
    p3.field.add(
        name="m", number=2, type=_FD.TYPE_MESSAGE, label=_FD.LABEL_REPEATED,
        type_name=".w3.P3.MEntry",
    )
    pool.Add(w3)

    # utf8_validation = NONE on an editions string: upb leaves it unvalidated,
    # exactly like a proto2 string.
    w4 = _editions_file("w4.proto", "w4")
    w4.message_type.add(name="Unchecked").field.add(
        name="s", number=1, type=_FD.TYPE_STRING, label=_FD.LABEL_OPTIONAL,
    ).options.features.utf8_validation = _FS.NONE
    pool.Add(w4)
    return pool


# A marker the same length as the bad bytes that replace it, so every length
# prefix in the serialized message stays valid after the swap.
_MARKER, _BAD = b"ZZ", b"\xff\xfe"


def _populate(root: Message, where: str, ext: d.FieldDescriptor) -> None:
    marker = _MARKER.decode()
    if where == "top":
        root.s = marker
    elif where == "submessage":
        root.sub.s = marker
    elif where == "repeated":
        root.rs.extend(["ok", marker])
    elif where == "map-key":
        root.m[marker] = "ok"
    elif where == "map-value":
        root.m["ok"] = marker
    elif where == "repeated-submessage":
        root.rsub.add(s="ok")
        root.rsub.add(s=marker)
    elif where == "map-message-value":
        root.ml[1].s = marker
    elif where == "group":
        root.g.s = marker
    elif where == "extension":
        root.Extensions[ext] = marker
    else:  # pragma: no cover - a typo in the parametrize list
        raise AssertionError(where)


_WALK_CASES = [
    ("top", "w2.Root.s"),
    ("submessage", "w2.Leaf.s"),
    ("repeated", "w2.Root.rs"),
    ("map-key", "w2.Root.MEntry.key"),
    ("map-value", "w2.Root.MEntry.value"),
    ("repeated-submessage", "w2.Leaf.s"),
    ("map-message-value", "w2.Leaf.s"),
    ("group", "w2.Root.G.s"),
    ("extension", "w2.ext"),
]


class TestFirstUndecodableString:
    @pytest.fixture(scope="class")
    def walk_pool(self) -> descriptor_pool.DescriptorPool:
        return _walk_pool()

    def _root_class(self, walk_pool: descriptor_pool.DescriptorPool) -> type[Message]:
        cls: type[Message] = message_factory.GetMessageClass(
            walk_pool.FindMessageTypeByName("w2.Root"),
        )
        return cls

    @skip_under_pure_python(
        "premise holds only on upb: it parses a non-UTF-8 proto2 string and returns "
        "bytes, while the pure-Python parser rejects it before any walk could run"
    )
    @pytest.mark.parametrize(("where", "field_name"), _WALK_CASES)
    def test_finds_bytes_wherever_upb_left_them(
        self, walk_pool: descriptor_pool.DescriptorPool, where: str, field_name: str,
    ) -> None:
        """upb hands the bytes back at every depth, so the walk must reach every depth."""
        cls = self._root_class(walk_pool)
        root = cls()
        _populate(root, where, walk_pool.FindExtensionByName("w2.ext"))
        wire = root.SerializeToString()
        assert wire.count(_MARKER) == 1
        parsed = cls.FromString(wire.replace(_MARKER, _BAD))

        hit = first_undecodable_string(parsed)
        assert hit is not None
        field, value = hit
        assert (field.full_name, value) == (field_name, _BAD)

    @pytest.mark.parametrize("where", [case for case, _ in _WALK_CASES])
    def test_a_clean_message_has_no_hit(
        self, walk_pool: descriptor_pool.DescriptorPool, where: str,
    ) -> None:
        cls = self._root_class(walk_pool)
        root = cls()
        _populate(root, where, walk_pool.FindExtensionByName("w2.ext"))
        assert first_undecodable_string(cls.FromString(root.SerializeToString())) is None

    def test_a_proto3_message_has_no_hit(self, walk_pool: descriptor_pool.DescriptorPool) -> None:
        """Both runtimes validate proto3 strings while parsing; nothing is left to find."""
        cls: type[Message] = message_factory.GetMessageClass(
            walk_pool.FindMessageTypeByName("w3.P3"),
        )
        msg = cls(s="ok")
        msg.m["k"] = "v"
        assert first_undecodable_string(cls.FromString(msg.SerializeToString())) is None

    @skip_under_pure_python(
        "premise holds only on upb: it skips validation for utf8_validation = NONE, "
        "while the pure-Python parser validates every string"
    )
    def test_an_editions_string_without_validation_is_found(
        self, walk_pool: descriptor_pool.DescriptorPool,
    ) -> None:
        cls: type[Message] = message_factory.GetMessageClass(
            walk_pool.FindMessageTypeByName("w4.Unchecked"),
        )
        wire = cls(s=_MARKER.decode()).SerializeToString().replace(_MARKER, _BAD)
        hit = first_undecodable_string(cls.FromString(wire))
        assert hit is not None and hit[0].full_name == "w4.Unchecked.s"


def _reach_pool() -> descriptor_pool.DescriptorPool:
    """Types that can and cannot reach a string upb leaves unvalidated."""
    pool = descriptor_pool.DescriptorPool()
    r2 = descriptor_pb2.FileDescriptorProto(name="r2.proto", package="r2", syntax="proto2")
    ints2 = r2.message_type.add(name="Ints2")
    ints2.field.add(name="x", number=1, type=_FD.TYPE_INT32, label=_FD.LABEL_OPTIONAL)
    ints2.field.add(
        name="self", number=2, type=_FD.TYPE_MESSAGE, label=_FD.LABEL_OPTIONAL,
        type_name=".r2.Ints2",
    )
    r2.message_type.add(name="Str2").field.add(
        name="s", number=1, type=_FD.TYPE_STRING, label=_FD.LABEL_OPTIONAL,
    )
    ranged = r2.message_type.add(name="Ranged2")
    ranged.field.add(name="x", number=1, type=_FD.TYPE_INT32, label=_FD.LABEL_OPTIONAL)
    ranged.extension_range.add(start=100, end=200)
    pool.Add(r2)

    r3 = descriptor_pb2.FileDescriptorProto(
        name="r3.proto", package="r3", syntax="proto3", dependency=["r2.proto"],
    )
    plain = r3.message_type.add(name="Plain3")
    plain.field.add(name="s", number=1, type=_FD.TYPE_STRING, label=_FD.LABEL_OPTIONAL)
    _map_entry_type(plain, "MEntry", _FD.TYPE_STRING, _FD.TYPE_STRING)
    plain.field.add(
        name="m", number=2, type=_FD.TYPE_MESSAGE, label=_FD.LABEL_REPEATED,
        type_name=".r3.Plain3.MEntry",
    )
    plain.field.add(
        name="self", number=3, type=_FD.TYPE_MESSAGE, label=_FD.LABEL_OPTIONAL,
        type_name=".r3.Plain3",
    )
    r3.message_type.add(name="Bridge3").field.add(
        name="other", number=1, type=_FD.TYPE_MESSAGE, label=_FD.LABEL_OPTIONAL,
        type_name=".r2.Str2",
    )
    pool.Add(r3)

    r4 = _editions_file("r4.proto", "r4")
    r4.message_type.add(name="EdStr").field.add(
        name="s", number=1, type=_FD.TYPE_STRING, label=_FD.LABEL_OPTIONAL,
    )
    r4.message_type.add(name="EdInts").field.add(
        name="x", number=1, type=_FD.TYPE_INT32, label=_FD.LABEL_OPTIONAL,
    )
    pool.Add(r4)
    return pool


class TestMayHoldUnvalidatedString:
    """The per-type precompute behind KTD6's skip.

    A seam may skip the walk only for a type where this is False, so a False
    that should be True silently lets upb's bytes through. The cases below
    name each way a type becomes reachable, and a control that is not.
    """

    @pytest.fixture(scope="class")
    def reach_pool(self) -> descriptor_pool.DescriptorPool:
        return _reach_pool()

    @pytest.mark.parametrize(
        ("full_name", "expected"),
        [
            pytest.param("r3.Plain3", False, id="proto3-strings-map-and-self-reference"),
            pytest.param("r2.Ints2", False, id="proto2-without-strings-or-ranges"),
            pytest.param("r4.EdInts", False, id="editions-without-strings"),
            pytest.param("r2.Str2", True, id="proto2-string"),
            pytest.param("r2.Ranged2", True, id="extension-range"),
            pytest.param("r3.Bridge3", True, id="proto3-reaching-a-proto2-string"),
            # An editions string answers for itself: upb validates it unless it
            # sets utf8_validation = NONE (TestEachStringFieldAnswersForItself).
            pytest.param("r4.EdStr", False, id="editions-string"),
        ],
    )
    def test_reachability(
        self, reach_pool: descriptor_pool.DescriptorPool, full_name: str, expected: bool,
    ) -> None:
        desc = reach_pool.FindMessageTypeByName(full_name)
        assert may_hold_unvalidated_string(desc) is expected


class TestDataExtensions:
    """The extensions a schema comparison pairs: all but custom options."""

    def test_a_data_message_yields_its_extensions(
        self, pool: descriptor_pool.DescriptorPool,
    ) -> None:
        msg = pool.FindMessageTypeByName("c2.Msg")
        assert data_extensions(msg) == FieldView.of(msg).extensions != ()

    def test_a_message_without_extension_ranges_yields_none(
        self, pool: descriptor_pool.DescriptorPool,
    ) -> None:
        assert data_extensions(pool.FindMessageTypeByName("c3.Msg3")) == ()

    def test_an_options_message_yields_none_even_with_custom_options_loaded(self) -> None:
        """Which custom options a pool holds depends on the files it loaded."""
        descriptor_proto = descriptor_pb2.FileDescriptorProto()
        descriptor_pb2.DESCRIPTOR.CopyToProto(descriptor_proto)
        options = descriptor_pb2.FileDescriptorProto(
            name="o.proto", package="o", syntax="proto2",
            dependency=["google/protobuf/descriptor.proto"],
        )
        options.extension.add(
            name="my_opt", number=50000, type=_FD.TYPE_INT32, label=_FD.LABEL_OPTIONAL,
            extendee=".google.protobuf.FieldOptions",
        )
        pool = descriptor_pool.DescriptorPool()
        pool.Add(descriptor_proto)
        pool.Add(options)
        # Resolve the file as protokit's loaders do (``add_and_resolve``): the
        # pure-Python pool registers a file's extensions only once it is built.
        pool.FindFileByName("o.proto")
        field_options = pool.FindMessageTypeByName("google.protobuf.FieldOptions")
        assert FieldView.of(field_options).extensions != ()
        assert data_extensions(field_options) == ()


# Why several tests below run only on upb.
_UPB_ONLY_PREMISE = (
    "premise holds only on upb: it parses a non-UTF-8 proto2 string and returns "
    "bytes, while the pure-Python parser rejects it before any walk could run"
)


class TestStringWalk:
    """The planned walk behind ``first_undecodable_string``.

    A storage scan keeps one walk for every record, so a plan built for one
    message must serve the next, and a type that cannot hold a string upb left
    unvalidated must cost nothing to walk.
    """

    @skip_under_pure_python(_UPB_ONLY_PREMISE)
    def test_one_walk_finds_every_case_in_turn(self) -> None:
        pool = _walk_pool()
        cls = message_factory.GetMessageClass(pool.FindMessageTypeByName("w2.Root"))
        walk = StringWalk()
        for where, field_name in _WALK_CASES:
            root = cls()
            _populate(root, where, pool.FindExtensionByName("w2.ext"))
            clean = cls.FromString(root.SerializeToString())
            bad = cls.FromString(root.SerializeToString().replace(_MARKER, _BAD))
            assert walk.first(clean) is None, where
            hit = walk.first(bad)
            assert hit is not None and hit[0].full_name == field_name, where

    @pytest.mark.parametrize(
        ("full_name", "planned"),
        [
            pytest.param("r3.Plain3", [], id="proto3-strings-map-and-self-reference"),
            pytest.param("r2.Ints2", [], id="proto2-without-strings"),
            pytest.param("r2.Str2", ["s"], id="proto2-string"),
            pytest.param("r3.Bridge3", ["other"], id="proto3-field-reaching-a-proto2-string"),
            pytest.param("r4.EdStr", [], id="editions-string"),
        ],
    )
    def test_the_plan_reads_only_fields_that_can_hold_one(
        self, full_name: str, planned: list[str],
    ) -> None:
        walk = StringWalk()
        fields, *_ = walk._plan(_reach_pool().FindMessageTypeByName(full_name))
        assert [name for name, *_ in fields] == planned

    @skip_under_pure_python(_UPB_ONLY_PREMISE)
    def test_a_type_whose_only_string_is_an_extension_is_walked(self) -> None:
        """Nothing to plan among its own fields; the extension range still counts."""
        fdp = descriptor_pb2.FileDescriptorProto(name="e2.proto", package="e2", syntax="proto2")
        only = fdp.message_type.add(name="OnlyExt")
        only.extension_range.add(start=100, end=200)
        fdp.extension.add(
            name="tag", number=100, type=_FD.TYPE_STRING, label=_FD.LABEL_OPTIONAL,
            extendee=".e2.OnlyExt",
        )
        pool = descriptor_pool.DescriptorPool()
        pool.Add(fdp)
        cls = message_factory.GetMessageClass(pool.FindMessageTypeByName("e2.OnlyExt"))
        tag = pool.FindExtensionByName("e2.tag")
        msg = cls()
        msg.Extensions[tag] = _MARKER.decode()
        bad = cls.FromString(msg.SerializeToString().replace(_MARKER, _BAD))
        hit = StringWalk().first(bad)
        assert hit is not None and hit[0].full_name == "e2.tag"

    @skip_under_pure_python(_UPB_ONLY_PREMISE)
    def test_a_file_name_shared_by_two_pools_is_not_confused(self) -> None:
        """One walk over a proto3 and a proto2 file of the same name checks each by its syntax."""
        classes = {}
        for syntax in ("proto3", "proto2"):
            fdp = descriptor_pb2.FileDescriptorProto(name="same.proto", package="p", syntax=syntax)
            fdp.message_type.add(name="M").field.add(
                name="s", number=1, type=_FD.TYPE_STRING, label=_FD.LABEL_OPTIONAL,
            )
            pool = descriptor_pool.DescriptorPool()
            pool.Add(fdp)
            classes[syntax] = message_factory.GetMessageClass(pool.FindMessageTypeByName("p.M"))
        walk = StringWalk()
        assert walk.first(classes["proto3"].FromString(b"\x0a\x01x")) is None
        hit = walk.first(classes["proto2"].FromString(b"\x0a\x01\xff"))
        assert hit is not None and hit[0].full_name == "p.M.s"


def _shadowing_class(name: str) -> type[Message]:
    """proto2 ``sh.M`` with an int field named ``name`` and a ``child`` holding a string."""
    fdp = descriptor_pb2.FileDescriptorProto(name="sh.proto", package="sh", syntax="proto2")
    fdp.message_type.add(name="Child").field.add(
        name="s", number=1, type=_FD.TYPE_STRING, label=_FD.LABEL_OPTIONAL,
    )
    m = fdp.message_type.add(name="M")
    m.field.add(name=name, number=1, type=_FD.TYPE_INT32, label=_FD.LABEL_OPTIONAL)
    m.field.add(
        name="child", number=2, type=_FD.TYPE_MESSAGE, label=_FD.LABEL_OPTIONAL,
        type_name=".sh.Child",
    )
    pool = descriptor_pool.DescriptorPool()
    pool.Add(fdp)
    cls: type[Message] = message_factory.GetMessageClass(pool.FindMessageTypeByName("sh.M"))
    return cls


class TestStringWalkFieldNamesThatShadowTheMessageApi:
    """A field named like a ``Message`` method hides the method (upb) or is hidden by it."""

    # Not DESCRIPTOR: pure-Python protobuf cannot build a class with that field.
    @pytest.mark.parametrize("name", ["HasField", "ListFields", "Clear"])
    def test_a_clean_message_walks_without_error(self, name: str) -> None:
        cls = _shadowing_class(name)
        # n = 5, child { s: "a" }
        msg = cls.FromString(b"\x08\x05\x12\x03\x0a\x01a")
        assert StringWalk().first(msg) is None

    @skip_under_pure_python(_UPB_ONLY_PREMISE)
    @pytest.mark.parametrize("name", ["HasField", "ListFields", "DESCRIPTOR", "Clear"])
    def test_a_bad_string_beside_it_is_found(self, name: str) -> None:
        cls = _shadowing_class(name)
        msg = cls.FromString(b"\x08\x05\x12\x03\x0a\x01\xff")
        hit = StringWalk().first(msg)
        assert hit is not None and hit[0].full_name == "sh.Child.s"


@skip_under_pure_python(_UPB_ONLY_PREMISE)
def test_the_lowest_numbered_bad_string_is_reported_whatever_the_declaration_order() -> None:
    fdp = descriptor_pb2.FileDescriptorProto(name="o.proto", package="o", syntax="proto2")
    m = fdp.message_type.add(name="M")
    for name, number in (("second", 2), ("first", 1)):
        m.field.add(name=name, number=number, type=_FD.TYPE_STRING, label=_FD.LABEL_OPTIONAL)
    pool = descriptor_pool.DescriptorPool()
    pool.Add(fdp)
    cls = message_factory.GetMessageClass(pool.FindMessageTypeByName("o.M"))
    hit = StringWalk().first(cls.FromString(bytes.fromhex("0a01ff1201fe")))
    assert hit is not None and hit[0].full_name == "o.M.first"


def _shadowing_message_class(name: str) -> type[Message]:
    """proto2 ``sm.M`` with a *message* field named ``name`` holding ``sm.Inner.s``.

    ``M`` has an extension range (so ``Extensions`` is a live attribute) and, for a
    ``*_FIELD_NUMBER`` name, the field whose constant that name repeats.
    """
    fdp = descriptor_pb2.FileDescriptorProto(name="sm.proto", package="sm", syntax="proto2")
    fdp.message_type.add(name="Inner").field.add(
        name="s", number=1, type=_FD.TYPE_STRING, label=_FD.LABEL_OPTIONAL,
    )
    m = fdp.message_type.add(name="M")
    m.field.add(
        name=name, number=1, type=_FD.TYPE_MESSAGE, label=_FD.LABEL_OPTIONAL,
        type_name=".sm.Inner",
    )
    if name.endswith("_FIELD_NUMBER"):
        m.field.add(
            name=name.removesuffix("_FIELD_NUMBER").lower(), number=2,
            type=_FD.TYPE_INT32, label=_FD.LABEL_OPTIONAL,
        )
    m.extension_range.add(start=100, end=200)
    pool = descriptor_pool.DescriptorPool()
    pool.Add(fdp)
    cls: type[Message] = message_factory.GetMessageClass(pool.FindMessageTypeByName("sm.M"))
    return cls


_SHADOWING_MESSAGE_NAMES = [
    "Extensions", "FindInitializationErrors", "HasField", "ListFields", "Clear", "A_FIELD_NUMBER",
]


class TestStringWalkMessageFieldsThatShadowTheMessageApi:
    """A *message* field with a colliding name is the one the walk descends into."""

    @pytest.mark.parametrize("name", _SHADOWING_MESSAGE_NAMES)
    def test_a_clean_message_walks_without_error(self, name: str) -> None:
        msg = _shadowing_message_class(name).FromString(bytes.fromhex("0a040a026f6b"))
        assert StringWalk().first(msg) is None

    @skip_under_pure_python(_UPB_ONLY_PREMISE)
    @pytest.mark.parametrize("name", _SHADOWING_MESSAGE_NAMES)
    def test_a_bad_string_inside_it_is_found(self, name: str) -> None:
        msg = _shadowing_message_class(name).FromString(bytes.fromhex("0a030a01ff"))
        hit = StringWalk().first(msg)
        assert hit is not None and hit[0].full_name == "sm.Inner.s"


@skip_under_pure_python(_UPB_ONLY_PREMISE)
def test_a_bad_key_in_a_map_whose_values_need_no_walk_is_found() -> None:
    """``map<string, int32>``: the plan checks the keys and skips the values."""
    fdp = descriptor_pb2.FileDescriptorProto(name="mk.proto", package="mk", syntax="proto2")
    m = fdp.message_type.add(name="M")
    _map_entry_type(m, "CountsEntry", _FD.TYPE_STRING, _FD.TYPE_INT32)
    m.field.add(
        name="counts", number=1, type=_FD.TYPE_MESSAGE, label=_FD.LABEL_REPEATED,
        type_name=".mk.M.CountsEntry",
    )
    pool = descriptor_pool.DescriptorPool()
    pool.Add(fdp)
    cls = message_factory.GetMessageClass(pool.FindMessageTypeByName("mk.M"))
    walk = StringWalk()
    # counts { key: <k> value: 1 }
    assert walk.first(cls.FromString(bytes.fromhex("0a050a016b1001"))) is None
    hit = walk.first(cls.FromString(bytes.fromhex("0a050a01ff1001")))
    assert hit is not None and hit[0].full_name == "mk.M.CountsEntry.key"


def test_a_walk_plans_each_message_type_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """The per-record cost a storage scan pays assumes plans are reused, not rebuilt."""
    pool = _walk_pool()
    cls = message_factory.GetMessageClass(pool.FindMessageTypeByName("w2.Root"))
    walk = StringWalk()
    planned: list[str] = []
    real_plan = walk._plan

    def counting_plan(descriptor):  # type: ignore[no-untyped-def]
        planned.append(descriptor.full_name)
        return real_plan(descriptor)

    monkeypatch.setattr(walk, "_plan", counting_plan)
    root = cls()
    root.sub.s = "ok"
    for _ in range(3):
        assert walk.first(cls.FromString(root.SerializeToString())) is None
    assert sorted(planned) == ["w2.Leaf", "w2.Root"]


def _syntax_pool() -> descriptor_pool.DescriptorPool:
    """``own2.M`` (proto2) and ``own3.M`` (proto3): the same strings, and no editions file.

    Nothing here needs editions, so these types are planned on protobuf 4.25 as
    well, where a string field's answer is its file's syntax.
    """
    pool = descriptor_pool.DescriptorPool()
    for package, syntax in (("own2", "proto2"), ("own3", "proto3")):
        fdp = descriptor_pb2.FileDescriptorProto(
            name=f"{package}.proto", package=package, syntax=syntax,
        )
        m = fdp.message_type.add(name="M")
        m.field.add(name="s", number=1, type=_FD.TYPE_STRING, label=_FD.LABEL_OPTIONAL)
        m.field.add(name="rs", number=2, type=_FD.TYPE_STRING, label=_FD.LABEL_REPEATED)
        _map_entry_type(m, "TagsEntry", _FD.TYPE_STRING, _FD.TYPE_STRING)
        m.field.add(
            name="tags", number=3, type=_FD.TYPE_MESSAGE, label=_FD.LABEL_REPEATED,
            type_name=f".{package}.M.TagsEntry",
        )
        m.field.add(name="n", number=4, type=_FD.TYPE_INT32, label=_FD.LABEL_OPTIONAL)
        pool.Add(fdp)
    return pool


def _planned(descriptor: d.Descriptor) -> list[str]:
    fields, *_ = StringWalk()._plan(descriptor)
    return [name for name, *_ in fields]


class TestEachStringFieldAnswersForItself:
    """The walk asks each string field, and a map's key and value, whether upb validated it.

    The runtime answers: the field's own ``utf8_validation`` on protobuf 5.26 and
    later, its file's syntax on 4.25. No answer comes from the file's
    ``serialized_pb``: upb dies writing some files it loaded back out, and those
    bytes do not parse once the default pool declares an unrelated extension at
    one of the schema's option numbers.
    """

    def test_a_proto3_type_plans_no_field(self) -> None:
        desc = _syntax_pool().FindMessageTypeByName("own3.M")
        assert _planned(desc) == []
        assert may_hold_unvalidated_string(desc) is False

    def test_a_proto2_type_plans_each_string_and_both_halves_of_a_map(self) -> None:
        from protokit import _fieldview

        desc = _syntax_pool().FindMessageTypeByName("own2.M")
        fields, *_ = StringWalk()._plan(desc)
        assert [(name, kind) for name, kind, *_ in fields] == [
            ("s", _fieldview._STRING), ("rs", _fieldview._STRINGS), ("tags", _fieldview._MAP),
        ]
        map_plan = fields[2][2]
        assert map_plan is not None and map_plan[1:] == (True, _fieldview._STRING)
        assert may_hold_unvalidated_string(desc) is True

    def test_an_editions_string_is_planned_only_where_it_opts_out_of_validation(self) -> None:
        fdp = _editions_file("own4.proto", "own4")
        m = fdp.message_type.add(name="M")
        m.field.add(name="checked", number=1, type=_FD.TYPE_STRING, label=_FD.LABEL_OPTIONAL)
        m.field.add(
            name="raw", number=2, type=_FD.TYPE_STRING, label=_FD.LABEL_OPTIONAL,
        ).options.features.utf8_validation = _FS.NONE
        fdp.message_type.add(name="Checked").field.add(
            name="s", number=1, type=_FD.TYPE_STRING, label=_FD.LABEL_OPTIONAL,
        )
        pool = descriptor_pool.DescriptorPool()
        pool.Add(fdp)
        mixed = pool.FindMessageTypeByName("own4.M")
        assert _planned(mixed) == ["raw"]
        assert may_hold_unvalidated_string(mixed) is True
        checked = pool.FindMessageTypeByName("own4.Checked")
        assert _planned(checked) == []
        assert may_hold_unvalidated_string(checked) is False

    @pytest.mark.parametrize("package", ["own2", "own3"])
    def test_a_type_is_planned_and_walked_without_reading_serialized_pb(
        self, monkeypatch: pytest.MonkeyPatch, package: str,
    ) -> None:
        desc = _syntax_pool().FindMessageTypeByName(f"{package}.M")
        cls = message_factory.GetMessageClass(desc)
        message = cls(s="a", rs=["b"])
        message.tags["k"] = "v"
        parsed = cls.FromString(message.SerializeToString())
        reads: list[str] = []

        def read(file: d.FileDescriptor) -> bytes:
            reads.append(file.name)
            raise RuntimeError("serialized_pb was read")

        # Patched once the pool and the class exist: pure-Python sets the
        # attribute when it builds a file.
        monkeypatch.setattr(type(desc.file), "serialized_pb", property(read), raising=False)
        with pytest.raises(RuntimeError):
            _ = desc.file.serialized_pb
        reads.clear()

        assert _planned(desc) == ([] if package == "own3" else ["s", "rs", "tags"])
        assert may_hold_unvalidated_string(desc) is (package == "own2")
        assert StringWalk().first(parsed) is None
        assert first_undecodable_string(parsed) is None
        # Checked as well as raised: a read whose error something caught would pass.
        assert reads == []

    def test_a_field_that_cannot_answer_is_planned(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No answer means "read it": slower, never wrong, and never a new way to fail."""
        desc = _syntax_pool().FindMessageTypeByName("own3.M")
        field_type = type(desc.fields_by_name["s"])
        real = getattr(field_type, "_GetFeatures", None)

        class _NoUtf8Answer:
            """A field's features, except that reading ``utf8_validation`` raises."""

            def __init__(self, field: d.FieldDescriptor) -> None:
                self._field = field

            def __getattr__(self, name: str) -> object:
                # Pure-Python reads other features to answer ``label`` and ``type``.
                if name == "utf8_validation" or real is None:
                    raise TypeError("no answer for this field")
                return getattr(real(self._field), name)

        monkeypatch.setattr(
            field_type, "_GetFeatures", lambda field: _NoUtf8Answer(field), raising=False,
        )
        assert _planned(desc) == ["s", "rs", "tags"]
        assert may_hold_unvalidated_string(desc) is True
        cls = message_factory.GetMessageClass(desc)
        assert StringWalk().first(cls.FromString(b"\x0a\x01a")) is None

    def test_strict_warnings_do_not_change_the_answer(self) -> None:
        """protobuf 4.25 deprecates the syntax read: under ``-W error`` it raises unless hushed."""
        import warnings

        pool = _syntax_pool()
        if hasattr(pool.FindMessageTypeByName("own2.M").fields_by_name["s"], "_GetFeatures"):
            pytest.skip("this protobuf answers per field; the file's syntax is never read")
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            assert _planned(pool.FindMessageTypeByName("own3.M")) == []
            assert _planned(pool.FindMessageTypeByName("own2.M")) == ["s", "rs", "tags"]
            assert may_hold_unvalidated_string(pool.FindMessageTypeByName("own3.M")) is False

    def test_a_walk_reads_a_file_syntax_once(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Where the answer is the file's, one walk asks each file once, not once per field."""
        pool = _syntax_pool()
        desc = pool.FindMessageTypeByName("own2.M")
        if hasattr(desc.fields_by_name["s"], "_GetFeatures"):
            pytest.skip("this protobuf answers per field; the file's syntax is never read")
        file_type = type(desc.file)
        real = file_type.__dict__["syntax"]
        reads: list[str] = []

        def read(file: d.FileDescriptor) -> object:
            reads.append(file.name)
            return real.__get__(file, file_type)

        monkeypatch.setattr(file_type, "syntax", property(read))
        walk = StringWalk()
        walk._plan(desc)
        walk._plan(pool.FindMessageTypeByName("own2.M.TagsEntry"))
        assert reads == ["own2.proto"]


def _bad_default_class() -> type[Message]:
    """``dflt.M``: ``optional string s = 1 [default = <not UTF-8>]`` and ``optional int32 n = 2``.

    protoc accepts such a default and upb builds the type; an unset ``s`` then
    reads as ``bytes``. Pure-Python refuses the file, which is why the tests
    that use this run on upb only.
    """
    fdp = descriptor_pb2.FileDescriptorProto(name="dflt.proto", package="dflt", syntax="proto2")
    message = fdp.message_type.add(name="M")
    field = descriptor_pb2.FieldDescriptorProto
    message.field.add(
        name="s", number=1, type=field.TYPE_STRING, label=field.LABEL_OPTIONAL, default_value="?",
    )
    message.field.add(name="n", number=2, type=field.TYPE_INT32, label=field.LABEL_OPTIONAL)
    placeholder = b"\x3a\x01?"  # default_value is field 7 of FieldDescriptorProto
    serialized = fdp.SerializeToString()
    assert serialized.count(placeholder) == 1
    pool = descriptor_pool.DescriptorPool()
    pool.AddSerializedFile(serialized.replace(placeholder, b"\x3a\x01\xff"))
    return message_factory.GetMessageClass(pool.FindMessageTypeByName("dflt.M"))


@skip_under_pure_python(
    "premise holds only on upb: it builds a type whose string default is not UTF-8, "
    "while pure-Python refuses the file"
)
class TestOnlyASetFieldIsReported:
    """A schema default is the schema's, not the record's: the walk reports set fields only."""

    def test_an_unset_field_that_reads_a_default_that_is_not_utf8_is_no_hit(self) -> None:
        cls = _bad_default_class()
        message = cls.FromString(b"\x10\x05")  # n = 5; s is not set
        assert isinstance(message.s, bytes)  # the premise: the default reads as bytes
        assert first_undecodable_string(message) is None

    def test_the_same_field_set_to_bytes_that_are_not_utf8_is_a_hit(self) -> None:
        cls = _bad_default_class()
        hit = first_undecodable_string(cls.FromString(b"\x0a\x01\xfe"))
        assert hit is not None
        assert (hit[0].full_name, hit[1]) == ("dflt.M.s", b"\xfe")

    def test_a_field_without_presence_is_reported_for_what_it_holds(self) -> None:
        """Such a field has no default of its own, and asking whether it is set raises."""
        fdp = _editions_file("implicit.proto", "implicit")
        field = fdp.message_type.add(name="M").field.add(
            name="s", number=1, type=descriptor_pb2.FieldDescriptorProto.TYPE_STRING,
            label=descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL,
        )
        field.options.features.utf8_validation = _FS.NONE
        field.options.features.field_presence = _FS.IMPLICIT
        pool = descriptor_pool.DescriptorPool()
        pool.Add(fdp)
        desc = pool.FindMessageTypeByName("implicit.M")
        assert desc.fields_by_name["s"].has_presence is False
        cls = message_factory.GetMessageClass(desc)
        assert first_undecodable_string(cls()) is None
        hit = first_undecodable_string(cls.FromString(b"\x0a\x01\xfe"))
        assert hit is not None
        assert (hit[0].full_name, hit[1]) == ("implicit.M.s", b"\xfe")


def test_two_threads_reading_a_file_syntax_leave_the_warning_filters_as_they_were(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """protobuf 4.25: the hushed syntax read swaps the process's warning filters.

    Two threads inside that swap at once can leave the filters changed for good:
    the first to leave restores the list, and the second then restores the copy
    it saved while the first's change was in place. The second reader here is
    held inside its read until the first has left, which is that order.
    """
    import threading
    import warnings

    pool = _syntax_pool()
    desc = pool.FindMessageTypeByName("own2.M")
    if hasattr(desc.fields_by_name["s"], "_GetFeatures"):
        pytest.skip("this protobuf answers per field; the file's syntax is never read")
    file_type = type(desc.file)
    real = file_type.__dict__["syntax"]
    first_inside, second_inside = threading.Event(), threading.Event()
    release_first, release_second = threading.Event(), threading.Event()
    readers: list[str] = []

    def read(file: d.FileDescriptor) -> object:
        readers.append(threading.current_thread().name)
        if len(readers) == 1:
            first_inside.set()
            assert release_first.wait(10)
        else:
            second_inside.set()
            assert release_second.wait(10)
        return real.__get__(file, file_type)

    monkeypatch.setattr(file_type, "syntax", property(read))
    before = list(warnings.filters)
    first = threading.Thread(target=lambda: StringWalk()._plan(desc), name="first")
    second = threading.Thread(target=lambda: StringWalk()._plan(desc), name="second")
    first.start()
    assert first_inside.wait(10)
    second.start()
    second_inside.wait(0.5)  # it gets inside only if nothing keeps the two reads apart
    release_first.set()
    first.join(10)
    release_second.set()
    second.join(10)
    assert not first.is_alive() and not second.is_alive()
    assert readers == ["first", "second"]
    assert list(warnings.filters) == before



# --- fields named like the message class's private attributes ------------------
#
# Under pure-Python a class attribute wins over a field of the same name, so a
# message field named ``_Modified`` reads as the bound method and the walk
# descended into it. The names come from the runtime itself; a name its class
# cannot be built or parsed with is left out (that fails before any walk, as on
# 0.15.1).

_PRIVATE_NAME_RECORD = bytes.fromhex("0a040a026f6b")  # field 1 = Inner { s: "ok" }


def private_name_class(name: str, *, repeated: bool) -> type[Message] | None:
    """proto2 ``pn.M`` with a message field ``name`` holding ``pn.Inner.s``.

    ``None`` when the runtime cannot build the class or parse a record with it.
    """
    fdp = descriptor_pb2.FileDescriptorProto(name="pn.proto", package="pn", syntax="proto2")
    fdp.message_type.add(name="Inner").field.add(
        name="s", number=1, type=_FD.TYPE_STRING, label=_FD.LABEL_OPTIONAL,
    )
    fdp.message_type.add(name="M").field.add(
        name=name, number=1, type=_FD.TYPE_MESSAGE, type_name=".pn.Inner",
        label=_FD.LABEL_REPEATED if repeated else _FD.LABEL_OPTIONAL,
    )
    try:
        pool = descriptor_pool.DescriptorPool()
        pool.Add(fdp)
        cls: type[Message] = message_factory.GetMessageClass(pool.FindMessageTypeByName("pn.M"))
        cls.FromString(_PRIVATE_NAME_RECORD)
    except Exception:  # any refusal means the walk is never reached
        return None
    return cls


def private_names_that_build() -> list[tuple[str, bool]]:
    """Every underscore name of the runtime's message classes a record can be parsed with."""
    names = set(dir(Message)) | set(dir(descriptor_pb2.FileOptions))
    return [
        (name, repeated)
        for name in sorted(n for n in names if n.startswith("_"))
        for repeated in (False, True)
        if private_name_class(name, repeated=repeated) is not None
    ]


_PRIVATE_NAMES = private_names_that_build()


def _hides_the_field(name: str, repeated: bool) -> bool:
    """Whether reading ``name`` off a parsed record gives something other than the field."""
    cls = private_name_class(name, repeated=repeated)
    assert cls is not None
    value = getattr(cls.FromString(_PRIVATE_NAME_RECORD), name)
    return not (isinstance(value, Message) or type(value).__name__.startswith("Repeated"))


# The names this runtime lets a class attribute win over the field: the ones the
# walk must route round. Empty under upb, where the field always wins.
PRIVATE_NAMES_THAT_HIDE = [entry for entry in _PRIVATE_NAMES if _hides_the_field(*entry)]


@pytest.mark.parametrize(("name", "repeated"), _PRIVATE_NAMES)
def test_a_field_named_like_a_private_attribute_walks_without_error(
    name: str, repeated: bool,
) -> None:
    cls = private_name_class(name, repeated=repeated)
    assert cls is not None
    assert StringWalk().first(cls.FromString(_PRIVATE_NAME_RECORD)) is None


@skip_under_pure_python(_UPB_ONLY_PREMISE)
@pytest.mark.parametrize(("name", "repeated"), _PRIVATE_NAMES[:2])
def test_a_bad_string_beneath_a_private_named_field_is_found(name: str, repeated: bool) -> None:
    cls = private_name_class(name, repeated=repeated)
    assert cls is not None
    hit = StringWalk().first(cls.FromString(bytes.fromhex("0a030a01ff")))
    assert hit is not None and hit[0].full_name == "pn.Inner.s"


# --- a generated class whose nested message is named like a Message method ------
#
# A generated module keeps each nested message class in the outer class's
# dictionary. Under upb an instance looks a name up in its fields first and then
# in that dictionary, so a nested type named ``HasField`` or ``ListFields`` hides
# the method the walk's fast path calls.


def generated_class_with_nested(name: str) -> type[Message]:
    """proto2 ``gn.M { optional string s = 1; message <name> {} }`` laid out as a ``_pb2``.

    Built with the metaclass a generated module uses, nested classes in the class
    dictionary, without registering anything in the default pool.
    """
    from google.protobuf import reflection

    fdp = descriptor_pb2.FileDescriptorProto(name=f"gn_{name}.proto", package="gn", syntax="proto2")
    m = fdp.message_type.add(name="M")
    m.field.add(name="s", number=1, type=_FD.TYPE_STRING, label=_FD.LABEL_OPTIONAL)
    m.extension_range.add(start=100, end=200)
    m.nested_type.add(name=name)
    pool = descriptor_pool.DescriptorPool()
    pool.Add(fdp)
    desc = pool.FindMessageTypeByName("gn.M")
    nested = reflection.GeneratedProtocolMessageType(
        name, (Message,), {"DESCRIPTOR": desc.nested_types_by_name[name], "__module__": "gn_pb2"},
    )
    cls: type[Message] = reflection.GeneratedProtocolMessageType(
        "M", (Message,), {name: nested, "DESCRIPTOR": desc, "__module__": "gn_pb2"},
    )
    return cls


@pytest.mark.parametrize("name", ["HasField", "ListFields"])
def test_a_generated_class_with_a_nested_type_named_like_a_method_walks(name: str) -> None:
    cls = generated_class_with_nested(name)
    assert StringWalk().first(cls.FromString(b"\x0a\x02ok")) is None


@skip_under_pure_python(_UPB_ONLY_PREMISE)
@pytest.mark.parametrize("name", ["HasField", "ListFields"])
def test_a_bad_string_in_such_a_class_is_found(name: str) -> None:
    hit = StringWalk().first(generated_class_with_nested(name).FromString(b"\x0a\x01\xff"))
    assert hit is not None and hit[0].full_name == "gn.M.s"
