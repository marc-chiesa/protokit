"""Contract test for the ``_fieldview`` seam (U3, closes V26/V19).

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
from google.protobuf import descriptor_pb2, descriptor_pool

from protokit._fieldview import FieldView, is_map_field, map_entry

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
# (an extension reusing a reserved number is invisible to it; a U17 item). A
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
