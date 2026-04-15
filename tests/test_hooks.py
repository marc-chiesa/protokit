"""Phase 1.5 — MessageDifferencer hook pipeline tests.

Covers the VALIDATE / COMPARE / REPORT stages, message-level
validation hooks, presence-gated paths, repeated/map integration,
warning capture, hook-exception safety, and zero-hooks
equivalence with pre-1.5 behavior.
"""

from __future__ import annotations

from google.protobuf import descriptor_pb2

from protokit.message import ChangeType, MessageDifferencer, diff_messages
from protokit.message.model import (
    FieldHookContext,
    HookStage,
    MessageHookContext,
)
from tests.proto_builder import ProtoBuilder

T = descriptor_pb2.FieldDescriptorProto


# ---------------------------------------------------------------------------
# VALIDATE stage
# ---------------------------------------------------------------------------


class TestValidateStage:
    def test_fires_on_changed_scalar(self) -> None:
        builder = ProtoBuilder()
        builder.message("t.M", {"x": (T.TYPE_INT32, 1)})
        left = builder.build("t.M", x=1)
        right = builder.build("t.M", x=2)

        seen: list[tuple[str, HookStage]] = []

        def hook(ctx: FieldHookContext) -> None:
            seen.append((str(ctx.path), ctx.stage))

        differ = MessageDifferencer()
        differ.register_validate_hook(hook)
        differ.compare(left, right)
        assert ("x", HookStage.VALIDATE) in seen

    def test_fires_on_equal_scalar_too(self) -> None:
        """VALIDATE fires regardless of whether a diff will be emitted."""
        builder = ProtoBuilder()
        builder.message("t.M", {"x": (T.TYPE_INT32, 1)})
        left = builder.build("t.M", x=7)
        right = builder.build("t.M", x=7)

        called_with: list[FieldHookContext] = []

        def hook(ctx: FieldHookContext) -> None:
            called_with.append(ctx)

        differ = MessageDifferencer()
        differ.register_validate_hook(hook)
        differ.compare(left, right)
        assert len(called_with) == 1
        assert str(called_with[0].path) == "x"

    def test_fires_on_presence_both_unset_proto2(self) -> None:
        """proto2 optional that's unset on both sides still fires VALIDATE."""
        builder = ProtoBuilder()
        builder.message(
            "t.M", {"x": (T.TYPE_INT32, 1)},
            syntax="proto2",
        )
        left = builder.build("t.M")
        right = builder.build("t.M")

        seen: list[str] = []

        def hook(ctx: FieldHookContext) -> None:
            seen.append(str(ctx.path))

        differ = MessageDifferencer()
        differ.register_validate_hook(hook)
        differ.compare(left, right)
        assert "x" in seen

    def test_fires_on_presence_added_proto2(self) -> None:
        """proto2 optional set only on the right fires VALIDATE + emits ADDED."""
        builder = ProtoBuilder()
        builder.message(
            "t.M", {"x": (T.TYPE_INT32, 1)},
            syntax="proto2",
        )
        left = builder.build("t.M")
        right = builder.build("t.M", x=5)

        seen_values: list[tuple[object, object]] = []

        def hook(ctx: FieldHookContext) -> None:
            seen_values.append((ctx.left_value, ctx.right_value))

        differ = MessageDifferencer()
        differ.register_validate_hook(hook)
        result = differ.compare(left, right)
        # VALIDATE saw right_value=5 but left_value=None (unset)
        assert (None, 5) in seen_values
        # ADDED diff still emitted
        assert any(d.change_type == ChangeType.ADDED for d in result)

    def test_warn_appears_in_diffresult_warnings(self) -> None:
        builder = ProtoBuilder()
        builder.message("t.M", {"x": (T.TYPE_INT32, 1)})
        left = builder.build("t.M", x=10)
        right = builder.build("t.M", x=20)

        def hook(ctx: FieldHookContext) -> None:
            ctx.warn(f"bounds violated at {ctx.path}")

        differ = MessageDifferencer()
        differ.register_validate_hook(hook)
        result = differ.compare(left, right)
        assert any(
            "bounds violated at x" == w.message and w.path == "x"
            for w in result.warnings
        )


# ---------------------------------------------------------------------------
# COMPARE stage
# ---------------------------------------------------------------------------


class TestCompareStage:
    def test_override_equal_suppresses_modified(self) -> None:
        """COMPARE hook calling override_equal() prevents the MODIFIED diff."""
        builder = ProtoBuilder()
        builder.message("t.M", {"score": (T.TYPE_INT32, 1)})
        left = builder.build("t.M", score=99)
        right = builder.build("t.M", score=100)

        def hook(ctx: FieldHookContext) -> None:
            # treat score as equal if both within 10 units
            if ctx.left_value is None or ctx.right_value is None:
                return
            if abs(ctx.right_value - ctx.left_value) <= 10:
                ctx.override_equal()

        differ = MessageDifferencer()
        differ.register_compare_hook(hook)
        result = differ.compare(left, right)
        assert not result.has_changes()

    def test_override_equal_is_noop_in_validate_stage(self) -> None:
        """override_equal() called from a VALIDATE hook must NOT suppress the diff."""
        builder = ProtoBuilder()
        builder.message("t.M", {"x": (T.TYPE_INT32, 1)})
        left = builder.build("t.M", x=1)
        right = builder.build("t.M", x=2)

        def hook(ctx: FieldHookContext) -> None:
            ctx.override_equal()  # wrong stage — no-op

        differ = MessageDifferencer()
        differ.register_validate_hook(hook)
        result = differ.compare(left, right)
        assert result.has_changes()

    def test_compare_hooks_skipped_on_presence_gated_paths(self) -> None:
        """Presence changes (one-sided proto2 optional) skip COMPARE."""
        builder = ProtoBuilder()
        builder.message(
            "t.M", {"x": (T.TYPE_INT32, 1)},
            syntax="proto2",
        )
        left = builder.build("t.M")
        right = builder.build("t.M", x=5)

        fired_stages: list[HookStage] = []

        def vhook(ctx: FieldHookContext) -> None:
            fired_stages.append(ctx.stage)

        def chook(ctx: FieldHookContext) -> None:
            fired_stages.append(ctx.stage)

        differ = MessageDifferencer()
        differ.register_validate_hook(vhook)
        differ.register_compare_hook(chook)
        differ.compare(left, right)
        # VALIDATE fired, COMPARE did not (presence-gated ADDED path).
        assert HookStage.VALIDATE in fired_stages
        assert HookStage.COMPARE not in fired_stages


# ---------------------------------------------------------------------------
# REPORT stage
# ---------------------------------------------------------------------------


class TestReportStage:
    def test_annotate_attaches_to_difference(self) -> None:
        builder = ProtoBuilder()
        builder.message("t.M", {"name": (T.TYPE_STRING, 1)})
        left = builder.build("t.M", name="alice")
        right = builder.build("t.M", name="bob")

        def hook(ctx: FieldHookContext) -> None:
            ctx.annotate("name field")

        differ = MessageDifferencer()
        differ.register_report_hook(hook)
        result = differ.compare(left, right)
        assert len(result) == 1
        assert result.differences[0].annotations == ("name field",)

    def test_multiple_annotations_accumulate_in_order(self) -> None:
        builder = ProtoBuilder()
        builder.message("t.M", {"name": (T.TYPE_STRING, 1)})
        left = builder.build("t.M", name="alice")
        right = builder.build("t.M", name="bob")

        def first(ctx: FieldHookContext) -> None:
            ctx.annotate("first")

        def second(ctx: FieldHookContext) -> None:
            ctx.annotate("second")

        differ = MessageDifferencer()
        differ.register_report_hook(first)
        differ.register_report_hook(second)
        result = differ.compare(left, right)
        assert result.differences[0].annotations == ("first", "second")

    def test_annotate_is_noop_when_no_diff(self) -> None:
        """REPORT doesn't fire when values compare equal → no annotations anywhere."""
        builder = ProtoBuilder()
        builder.message("t.M", {"x": (T.TYPE_INT32, 1)})
        left = builder.build("t.M", x=5)
        right = builder.build("t.M", x=5)

        fired = []

        def hook(ctx: FieldHookContext) -> None:
            fired.append(ctx.stage)
            ctx.annotate("should-not-attach")  # won't attach anyway

        differ = MessageDifferencer()
        differ.register_report_hook(hook)
        result = differ.compare(left, right)
        assert fired == []  # REPORT not fired at all
        assert not result.has_changes()

    def test_annotate_fires_on_presence_added(self) -> None:
        """REPORT fires on presence-gated ADDED diffs too."""
        builder = ProtoBuilder()
        builder.message(
            "t.M", {"x": (T.TYPE_INT32, 1)},
            syntax="proto2",
        )
        left = builder.build("t.M")
        right = builder.build("t.M", x=7)

        def hook(ctx: FieldHookContext) -> None:
            ctx.annotate(f"{ctx.stage.value} at {ctx.path}")

        differ = MessageDifferencer()
        differ.register_report_hook(hook)
        result = differ.compare(left, right)
        added = [d for d in result if d.change_type == ChangeType.ADDED]
        assert len(added) == 1
        assert added[0].annotations == ("REPORT at x",)

    def test_difference_str_renders_annotations(self) -> None:
        builder = ProtoBuilder()
        builder.message("t.M", {"x": (T.TYPE_INT32, 1)})
        left = builder.build("t.M", x=1)
        right = builder.build("t.M", x=2)

        def hook(ctx: FieldHookContext) -> None:
            ctx.annotate("over limit")
            ctx.annotate("tracked")

        differ = MessageDifferencer()
        differ.register_report_hook(hook)
        result = differ.compare(left, right)
        s = str(result.differences[0])
        assert "[over limit; tracked]" in s


# ---------------------------------------------------------------------------
# Repeated + map integration
# ---------------------------------------------------------------------------


class TestRepeatedAndMapIntegration:
    def test_hooks_fire_on_repeated_scalar_pair(self) -> None:
        builder = ProtoBuilder()
        builder.message(
            "t.M", {"tags": (T.TYPE_STRING, 1)},
            repeated_fields={"tags"},
        )
        left = builder.build("t.M", tags=["a", "b"])
        right = builder.build("t.M", tags=["a", "c"])

        seen_paths: list[str] = []

        def hook(ctx: FieldHookContext) -> None:
            seen_paths.append(str(ctx.path))

        differ = MessageDifferencer()
        differ.register_validate_hook(hook)
        result = differ.compare(left, right)
        # Hook fired on each pairwise element.
        assert seen_paths.count("tags[0]") >= 1
        assert seen_paths.count("tags[1]") >= 1
        # Only the changed index produces a diff.
        assert any("tags[1]" in str(d.path) for d in result)

    def test_hooks_fire_on_map_scalar_value(self) -> None:
        builder = ProtoBuilder()
        builder.map_message(
            "t.M", fields={},
            map_fields={"items": (T.TYPE_STRING, T.TYPE_INT32, 1)},
        )
        MsgCls = builder.get_message_class("t.M")
        left = MsgCls(items={"a": 1, "b": 2})
        right = MsgCls(items={"a": 1, "b": 3})

        seen_paths: list[str] = []
        saw_override = []

        def vhook(ctx: FieldHookContext) -> None:
            seen_paths.append(str(ctx.path))

        def chook(ctx: FieldHookContext) -> None:
            # Map value path carries the key as a bracket segment; the
            # hook path format is ``items[<key>]``.
            if str(ctx.path) == 'items["b"]':
                saw_override.append(True)
                ctx.override_equal()

        differ = MessageDifferencer()
        differ.register_validate_hook(vhook)
        differ.register_compare_hook(chook)
        result = differ.compare(left, right)
        assert 'items["b"]' in seen_paths
        assert saw_override == [True]
        assert not result.has_changes()


# ---------------------------------------------------------------------------
# Message-level VALIDATE
# ---------------------------------------------------------------------------


class TestMessageValidateHook:
    def test_fires_on_root_message(self) -> None:
        builder = ProtoBuilder()
        builder.message("t.M", {"x": (T.TYPE_INT32, 1)})
        left = builder.build("t.M", x=1)
        right = builder.build("t.M", x=2)

        seen: list[tuple[str, bool, bool]] = []

        def hook(ctx: MessageHookContext) -> None:
            seen.append((
                str(ctx.path),
                ctx.left_msg is not None,
                ctx.right_msg is not None,
            ))

        differ = MessageDifferencer()
        differ.register_message_validate_hook(hook)
        differ.compare(left, right)
        assert ("", True, True) in seen

    def test_fires_on_nested_message(self) -> None:
        builder = ProtoBuilder()
        builder.message("t.Inner", {"v": (T.TYPE_INT32, 1)})
        builder.message(
            "t.Outer",
            {"inner": (T.TYPE_MESSAGE, 1, "t.Inner")},
        )
        Outer = builder.get_message_class("t.Outer")
        Inner = builder.get_message_class("t.Inner")
        left = Outer(inner=Inner(v=1))
        right = Outer(inner=Inner(v=2))

        paths: list[str] = []

        def hook(ctx: MessageHookContext) -> None:
            paths.append(str(ctx.path))

        differ = MessageDifferencer()
        differ.register_message_validate_hook(hook)
        differ.compare(left, right)
        assert "" in paths
        assert "inner" in paths

    def test_warn_appears_in_diffresult_warnings(self) -> None:
        builder = ProtoBuilder()
        builder.message("t.M", {"x": (T.TYPE_INT32, 1)})
        left = builder.build("t.M", x=1)
        right = builder.build("t.M", x=2)

        def hook(ctx: MessageHookContext) -> None:
            ctx.warn(f"message at {ctx.path!s}")

        differ = MessageDifferencer()
        differ.register_message_validate_hook(hook)
        result = differ.compare(left, right)
        assert any(
            "message at " in w.message for w in result.warnings
        )


# ---------------------------------------------------------------------------
# Hook exception safety
# ---------------------------------------------------------------------------


class TestHookExceptionSafety:
    def test_raising_field_hook_becomes_warning_and_continues(self) -> None:
        builder = ProtoBuilder()
        builder.message("t.M", {
            "x": (T.TYPE_INT32, 1),
            "y": (T.TYPE_STRING, 2),
        })
        left = builder.build("t.M", x=1, y="alice")
        right = builder.build("t.M", x=2, y="bob")

        def bad(ctx: FieldHookContext) -> None:
            raise RuntimeError("boom")

        differ = MessageDifferencer()
        differ.register_validate_hook(bad)
        result = differ.compare(left, right)
        # Comparison continues — both diffs emitted.
        paths = {str(d.path) for d in result}
        assert paths == {"x", "y"}
        # Each field triggers one warning.
        assert sum(
            "raised RuntimeError" in w.message for w in result.warnings
        ) >= 2

    def test_raising_message_hook_becomes_warning(self) -> None:
        builder = ProtoBuilder()
        builder.message("t.M", {"x": (T.TYPE_INT32, 1)})
        left = builder.build("t.M", x=1)
        right = builder.build("t.M", x=2)

        def bad(ctx: MessageHookContext) -> None:
            raise ValueError("nope")

        differ = MessageDifferencer()
        differ.register_message_validate_hook(bad)
        result = differ.compare(left, right)
        assert any(
            "raised ValueError" in w.message for w in result.warnings
        )
        # Field comparison still ran.
        assert any(str(d.path) == "x" for d in result)


# ---------------------------------------------------------------------------
# Zero-hooks equivalence / fast path
# ---------------------------------------------------------------------------


class TestZeroHooksFastPath:
    def test_default_differ_matches_diff_messages(self) -> None:
        """A differ with no hooks must be byte-identical to ``diff_messages``."""
        builder = ProtoBuilder()
        builder.message("t.M", {
            "name": (T.TYPE_STRING, 1),
            "count": (T.TYPE_INT32, 2),
        })
        left = builder.build("t.M", name="a", count=5)
        right = builder.build("t.M", name="b", count=10)

        hooked = MessageDifferencer().compare(left, right)
        baseline = diff_messages(left, right)
        assert hooked.differences == baseline.differences
        assert hooked.warnings == baseline.warnings

    def test_pool_refs_cleared_after_compare(self) -> None:
        """Re-using the differ must not leak pool refs across calls."""
        builder = ProtoBuilder()
        builder.message("t.M", {"x": (T.TYPE_INT32, 1)})
        left = builder.build("t.M", x=1)
        right = builder.build("t.M", x=2)

        differ = MessageDifferencer()
        differ.compare(left, right)
        assert differ._left_pool is None
        assert differ._right_pool is None


# ---------------------------------------------------------------------------
# Context pool access
# ---------------------------------------------------------------------------


class TestContextPoolAccess:
    def test_ctx_exposes_left_and_right_pools(self) -> None:
        builder = ProtoBuilder()
        builder.message("t.M", {"x": (T.TYPE_INT32, 1)})
        left = builder.build("t.M", x=1)
        right = builder.build("t.M", x=2)

        seen: list[tuple[object, object]] = []

        def hook(ctx: FieldHookContext) -> None:
            seen.append((ctx.left_pool, ctx.right_pool))

        differ = MessageDifferencer()
        differ.register_validate_hook(hook)
        differ.compare(left, right)
        assert len(seen) == 1
        left_pool, right_pool = seen[0]
        assert left_pool is left.DESCRIPTOR.file.pool
        assert right_pool is right.DESCRIPTOR.file.pool
