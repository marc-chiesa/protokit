"""Tests for protokit.schema.plugins (emit-style plugin API)."""

from __future__ import annotations

import warnings
from types import ModuleType

import pytest
from google.protobuf import descriptor_pool

from protokit.message.model import FieldPath
from protokit.schema import (
    CompatibilityLevel,
    Direction,
    FieldRuleContext,
    MessageRuleContext,
    SchemaChecker,
    Severity,
)
from protokit.schema.plugins import iter_rule_pack, make_emit
from tests.schema.helpers import T, build_message


ROOT = FieldPath(segments=())


# ---------------------------------------------------------------------------
# make_emit closure behavior
# ---------------------------------------------------------------------------


class TestMakeEmit:
    def test_appends_finding_with_rule_id(self) -> None:
        sink: list = []
        emit = make_emit("my_rule", sink)
        emit(path=ROOT, severity=Severity.WIRE, message="msg",
             direction=Direction.BOTH)
        assert len(sink) == 1
        assert sink[0].rule_id == "my_rule"
        assert sink[0].severity is Severity.WIRE
        assert sink[0].direction is Direction.BOTH
        assert sink[0].message == "msg"

    def test_carries_descriptor_refs(self) -> None:
        sink: list = []
        old_d = object()
        new_d = object()
        emit = make_emit("r", sink, old_descriptor=old_d, new_descriptor=new_d)
        emit(path=ROOT, severity=Severity.SEMANTIC, message="",
             direction=Direction.BOTH)
        assert sink[0].old_descriptor is old_d
        assert sink[0].new_descriptor is new_d


# ---------------------------------------------------------------------------
# Field plugin end-to-end via SchemaChecker
# ---------------------------------------------------------------------------


def _identical_pair() -> tuple[descriptor_pool.DescriptorPool, descriptor_pool.DescriptorPool]:
    old = descriptor_pool.DescriptorPool()
    new = descriptor_pool.DescriptorPool()
    for p in (old, new):
        build_message(p, "t.M", fields=[
            {"name": "x", "number": 1, "type": T.TYPE_STRING},
        ])
    return old, new


class TestFieldPlugin:
    def test_context_carries_descriptors_and_pools(self) -> None:
        old, new = _identical_pair()
        captured: dict = {}

        def plugin(ctx: FieldRuleContext) -> None:
            captured["path"] = ctx.path
            captured["old"] = ctx.old_field
            captured["new"] = ctx.new_field
            captured["old_pool"] = ctx.old_pool
            captured["new_pool"] = ctx.new_pool

        checker = SchemaChecker()
        checker.register_field_rule("capture", plugin)
        checker.check(old, "t.M", new, "t.M")
        assert str(captured["path"]) == "x"
        assert captured["old"] is not None
        assert captured["new"] is not None
        assert captured["old_pool"] is old
        assert captured["new_pool"] is new

    def test_emit_appears_in_report(self) -> None:
        old, new = _identical_pair()

        def plugin(ctx: FieldRuleContext) -> None:
            ctx.emit(severity=Severity.WIRE, message="custom flag",
                     direction=Direction.BOTH)

        checker = SchemaChecker(level=CompatibilityLevel.WIRE)
        checker.register_field_rule("plugin_a", plugin)
        report = checker.check(old, "t.M", new, "t.M")
        assert any(f.rule_id == "plugin_a" for f in report.findings)

    def test_emit_default_direction_is_both(self) -> None:
        old, new = _identical_pair()

        def plugin(ctx: FieldRuleContext) -> None:
            ctx.emit(severity=Severity.WIRE, message="m")

        checker = SchemaChecker(level=CompatibilityLevel.WIRE)
        checker.register_field_rule("p", plugin)
        report = checker.check(old, "t.M", new, "t.M")
        f = next(f for f in report.findings if f.rule_id == "p")
        assert f.direction is Direction.BOTH

    def test_silent_plugin_emits_nothing(self) -> None:
        old, new = _identical_pair()

        def quiet(ctx: FieldRuleContext) -> None:
            return

        checker = SchemaChecker(level=CompatibilityLevel.WIRE)
        checker.register_field_rule("quiet", quiet)
        report = checker.check(old, "t.M", new, "t.M")
        assert report.is_compatible

    def test_plugin_exception_recorded_and_traversal_continues(self) -> None:
        """A broken plugin must not abort subsequent plugins.

        Exception is captured into ``report.errors``; later plugins
        still run.
        """
        old, new = _identical_pair()

        def boom(ctx: FieldRuleContext) -> None:
            raise RuntimeError("kaboom")

        def follow_up(ctx: FieldRuleContext) -> None:
            ctx.emit(severity=Severity.WIRE, message="still ran")

        checker = SchemaChecker(level=CompatibilityLevel.WIRE)
        checker.register_field_rule("boom", boom)
        checker.register_field_rule("follow_up", follow_up)
        report = checker.check(old, "t.M", new, "t.M")
        assert any("boom" in w.message for w in report.errors)
        assert any("RuntimeError" in w.message for w in report.errors)
        assert any(f.rule_id == "follow_up" for f in report.findings)

    def test_plugin_exception_surfaces_in_report_warnings(self) -> None:
        """CI safety: CLI uses ``report.errors`` for exit-code 2."""
        old, new = _identical_pair()

        def boom(ctx: FieldRuleContext) -> None:
            raise RuntimeError("kaboom")

        checker = SchemaChecker(level=CompatibilityLevel.WIRE)
        checker.register_field_rule("boom", boom)
        report = checker.check(old, "t.M", new, "t.M")
        assert report.errors
        assert any("boom" in w.message for w in report.errors)
        assert any("RuntimeError" in w.message for w in report.errors)
        # Path is the field path where the plugin fired.
        assert any(w.path == "x" for w in report.errors)

    def test_plugin_does_not_also_emit_python_warning(self) -> None:
        """Plugin failures are recorded only in ``report.errors``.

        Pre-fix the engine also called ``warnings.warn`` which
        produced duplicate CLI output and a confusing stacklevel.
        Single source of truth now.
        """
        old, new = _identical_pair()

        def boom(ctx: FieldRuleContext) -> None:
            raise RuntimeError("kaboom")

        checker = SchemaChecker(level=CompatibilityLevel.WIRE)
        checker.register_field_rule("boom", boom)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            report = checker.check(old, "t.M", new, "t.M")
        # No Python-level warnings were emitted.
        assert len(w) == 0
        # But the failure is recorded in the report for CLI consumption.
        assert report.errors

    def test_plugin_emit_validation_error_surfaces_in_warnings(self) -> None:
        """TypeErrors from emit validation propagate as report warnings."""
        old, new = _identical_pair()

        def bad(ctx: FieldRuleContext) -> None:
            ctx.emit(severity="WIRE", message="oops",   # type: ignore[arg-type]
                     direction=Direction.BOTH)

        checker = SchemaChecker(level=CompatibilityLevel.WIRE)
        checker.register_field_rule("bad", bad)
        report = checker.check(old, "t.M", new, "t.M")
        assert any("TypeError" in w.message for w in report.errors)


# ---------------------------------------------------------------------------
# Message plugin
# ---------------------------------------------------------------------------


class TestMessagePlugin:
    def test_message_context_carries_descriptors(self) -> None:
        old, new = _identical_pair()
        seen: list = []

        def plugin(ctx: MessageRuleContext) -> None:
            seen.append((ctx.path, ctx.old_descriptor, ctx.new_descriptor))

        checker = SchemaChecker()
        checker.register_message_rule("see", plugin)
        checker.check(old, "t.M", new, "t.M")
        assert len(seen) == 1
        path, old_d, new_d = seen[0]
        assert old_d is not None
        assert new_d is not None

    def test_message_plugin_never_sees_a_one_sided_visit(self) -> None:
        """Both descriptors are always present — the walk is pair-driven.

        Characterization, and the reason ``MessageRuleContext``'s docstring no
        longer promises one-sided visits. The traversal only ever pushes
        ``(old_message_type, new_message_type)`` pairs, so a message type
        reachable from just one side is never visited at all: it is reported by
        the built-in field rules as an added/removed *field*, not handed to a
        message plugin with ``None`` on a side. Delivering one-sided visits
        would take a traversal redesign, deliberately not done here.
        """
        old = descriptor_pool.DescriptorPool()
        new = descriptor_pool.DescriptorPool()
        # Old: M { Inner inner = 1; }  New: M { Inner inner = 1; Extra e = 2; }
        for pool in (old, new):
            build_message(pool, "t.Inner", fields=[
                {"name": "a", "number": 1, "type": T.TYPE_STRING},
            ])
        build_message(new, "t.Extra", fields=[
            {"name": "b", "number": 1, "type": T.TYPE_STRING},
        ])
        build_message(old, "t.M", fields=[
            {"name": "inner", "number": 1, "type": T.TYPE_MESSAGE,
             "type_name": ".t.Inner"},
        ])
        build_message(new, "t.M", fields=[
            {"name": "inner", "number": 1, "type": T.TYPE_MESSAGE,
             "type_name": ".t.Inner"},
            {"name": "extra", "number": 2, "type": T.TYPE_MESSAGE,
             "type_name": ".t.Extra"},
        ])

        seen: list[tuple[str | None, str | None]] = []

        def plugin(ctx: MessageRuleContext) -> None:
            seen.append((
                None if ctx.old_descriptor is None else ctx.old_descriptor.full_name,
                None if ctx.new_descriptor is None else ctx.new_descriptor.full_name,
            ))

        checker = SchemaChecker()
        checker.register_message_rule("see", plugin)
        checker.check(old, "t.M", new, "t.M")

        assert seen  # the plugin did run
        assert all(o is not None and n is not None for o, n in seen)
        # t.Extra exists only on the new side, so it is never visited at all.
        assert all("t.Extra" not in (o, n) for o, n in seen)

    def test_message_plugin_emit(self) -> None:
        old, new = _identical_pair()

        def plugin(ctx: MessageRuleContext) -> None:
            ctx.emit(severity=Severity.WIRE, message="msg-level finding",
                     direction=Direction.BOTH)

        checker = SchemaChecker(level=CompatibilityLevel.WIRE)
        checker.register_message_rule("m", plugin)
        report = checker.check(old, "t.M", new, "t.M")
        assert any(f.rule_id == "m" for f in report.findings)

    def test_message_plugin_exception_recorded(self) -> None:
        old, new = _identical_pair()

        def boom(ctx: MessageRuleContext) -> None:
            raise ValueError("bad rule")

        checker = SchemaChecker()
        checker.register_message_rule("boom", boom)
        report = checker.check(old, "t.M", new, "t.M")
        assert any("boom" in w.message for w in report.errors)
        assert any("ValueError" in w.message for w in report.errors)
        # Built-in rules still ran (no findings here since pair is identical
        # at the message level; report.errors is the sole signal).
        assert not report.findings


# ---------------------------------------------------------------------------
# Rule pack loading
# ---------------------------------------------------------------------------


def _make_pack(rules: list) -> ModuleType:
    mod = ModuleType("test_pack")
    mod.RULES = rules
    return mod


class TestIterRulePack:
    def test_returns_pairs(self) -> None:
        def r(ctx): return None
        pack = _make_pack([("a", r), ("b", r)])
        out = iter_rule_pack(pack)
        assert [name for name, _ in out] == ["a", "b"]

    def test_missing_rules_attr_raises(self) -> None:
        mod = ModuleType("empty_pack")
        with pytest.raises(AttributeError, match="RULES"):
            iter_rule_pack(mod)

    def test_non_pair_entry_raises(self) -> None:
        pack = _make_pack(["just_a_string"])
        with pytest.raises(TypeError, match="not a"):
            iter_rule_pack(pack)

    def test_wrong_type_pair_raises(self) -> None:
        pack = _make_pack([(123, lambda ctx: None)])
        with pytest.raises(TypeError, match="wrong"):
            iter_rule_pack(pack)


class TestEmitValidation:
    def test_non_enum_severity_raises(self) -> None:
        old, new = _identical_pair()

        def bad(ctx: FieldRuleContext) -> None:
            ctx.emit(severity="WIRE", message="bad",
                     direction=Direction.BOTH)  # type: ignore[arg-type]

        checker = SchemaChecker(include_builtin=False)
        checker.register_field_rule("bad", bad)
        report = checker.check(old, "t.M", new, "t.M")
        assert any("TypeError" in w.message for w in report.errors)

    def test_non_enum_direction_raises(self) -> None:
        old, new = _identical_pair()

        def bad(ctx: FieldRuleContext) -> None:
            ctx.emit(severity=Severity.WIRE, message="bad",
                     direction="BOTH")  # type: ignore[arg-type]

        checker = SchemaChecker(include_builtin=False)
        checker.register_field_rule("bad", bad)
        report = checker.check(old, "t.M", new, "t.M")
        assert any("TypeError" in w.message for w in report.errors)


class TestAsyncPluginRejection:
    def test_register_field_rule_rejects_async_def(self) -> None:
        """async def plugins would silently skip fail-closed behavior."""

        async def sneaky(ctx: FieldRuleContext) -> None:
            ctx.emit(severity=Severity.WIRE, message="never emitted")

        checker = SchemaChecker(include_builtin=False)
        with pytest.raises(TypeError, match="async"):
            checker.register_field_rule("sneaky", sneaky)

    def test_register_message_rule_rejects_async_def(self) -> None:
        async def sneaky(ctx: MessageRuleContext) -> None:
            ctx.emit(severity=Severity.WIRE, message="never emitted")

        checker = SchemaChecker(include_builtin=False)
        with pytest.raises(TypeError, match="async"):
            checker.register_message_rule("sneaky", sneaky)

    def test_dispatch_catches_dynamically_wrapped_coroutine(self) -> None:
        """Wrapped async callables bypass iscoroutinefunction.

        A user could register ``functools.partial(async_fn, ...)`` or
        a callable class that returns a coroutine. ``register_*`` won't
        detect those, so the dispatcher must catch the coroutine
        return value and record a fail-closed warning.
        """
        old, new = _identical_pair()

        class AsyncWrapper:
            def __call__(self, ctx: FieldRuleContext):
                async def _impl():
                    return None
                return _impl()

        checker = SchemaChecker(include_builtin=False)
        # Registration accepts the wrapper (it's not a coroutinefunction).
        checker.register_field_rule("wrapped_async", AsyncWrapper())
        report = checker.check(old, "t.M", new, "t.M")
        assert report.errors
        assert any("awaitable" in w.message.lower()
                   or "async" in w.message.lower()
                   for w in report.errors)

    def test_dispatch_catches_asyncio_future_return(self) -> None:
        """Plugins returning an asyncio.Future also fail-closed.

        ``inspect.iscoroutine`` returns False for Futures. The
        engine uses ``inspect.isawaitable`` to catch all awaitable
        shapes.
        """
        import asyncio
        old, new = _identical_pair()

        def plugin(ctx: FieldRuleContext):
            loop = asyncio.new_event_loop()
            try:
                return loop.create_future()
            finally:
                loop.close()

        checker = SchemaChecker(include_builtin=False)
        checker.register_field_rule("future_return", plugin)
        report = checker.check(old, "t.M", new, "t.M")
        assert any("awaitable" in w.message.lower()
                   for w in report.errors)

    def test_dispatch_catches_custom_await_object(self) -> None:
        """Custom objects with ``__await__`` are awaitable but not coroutines."""
        old, new = _identical_pair()

        class AwaitableOnly:
            def __await__(self):
                if False:
                    yield
                return 1

        def plugin(ctx: FieldRuleContext):
            return AwaitableOnly()

        checker = SchemaChecker(include_builtin=False)
        checker.register_field_rule("custom_await", plugin)
        report = checker.check(old, "t.M", new, "t.M")
        assert any("awaitable" in w.message.lower()
                   for w in report.errors)

    def test_dispatch_catches_legacy_generator_coroutine(self) -> None:
        """@types.coroutine-style awaitables slip past inspect.iscoroutine.

        These ARE caught by ``inspect.isawaitable`` (they implement
        __await__ via the iterator protocol).
        """
        import types as _types
        old, new = _identical_pair()

        @_types.coroutine
        def legacy():
            yield

        def plugin(ctx: FieldRuleContext):
            return legacy()

        checker = SchemaChecker(include_builtin=False)
        checker.register_field_rule("legacy_coro", plugin)
        report = checker.check(old, "t.M", new, "t.M")
        assert any("awaitable" in w.message.lower()
                   for w in report.errors)

    def test_cleanup_falls_through_to_cancel_when_close_raises(self) -> None:
        """If close() raises, _cleanup_awaitable must still try cancel().

        Modeled on asyncio.Task semantics: a task has both close (from
        coroutine inheritance) and cancel. An object that exposes both
        where close raises should still get cancel called.
        """
        cancel_called: list[bool] = []

        class HybridAwaitable:
            def __await__(self):
                if False:
                    yield
                return 1

            def close(self):
                raise RuntimeError("close exploded")

            def cancel(self):
                cancel_called.append(True)

        old, new = _identical_pair()

        def plugin(ctx: FieldRuleContext):
            return HybridAwaitable()

        checker = SchemaChecker(include_builtin=False)
        checker.register_field_rule("hybrid", plugin)
        report = checker.check(old, "t.M", new, "t.M")
        assert cancel_called == [True]
        assert report.errors

    def test_cleanup_of_coroutine_that_raises_on_close_does_not_crash(self) -> None:
        """A coroutine that re-raises on GeneratorExit must not abort the check.

        Pre-fix the engine called ``result.close()`` outside a
        try/except, so a pathological coroutine could take down the
        entire traversal. ``_cleanup_awaitable`` swallows cleanup
        errors.
        """
        old, new = _identical_pair()

        async def nasty_coro():
            try:
                import asyncio
                await asyncio.sleep(0)
            except GeneratorExit:
                raise RuntimeError("close exploded")

        def plugin(ctx: FieldRuleContext):
            coro = nasty_coro()
            coro.send(None)  # start the coroutine so close() triggers its except
            return coro

        checker = SchemaChecker(include_builtin=False)
        checker.register_field_rule("nasty", plugin)
        # Must not raise; must record a failure.
        report = checker.check(old, "t.M", new, "t.M")
        assert report.errors
        assert any("awaitable" in w.message.lower()
                   for w in report.errors)


class TestReentrancy:
    def test_plugin_can_call_checker_check_recursively(self) -> None:
        """A plugin invoking checker.check(...) must not corrupt outer state.

        Pre-fix the checker stored pools on self and a recursive check()
        call would null them out for the outer run's remaining plugins.
        """
        from protokit.schema.model import Direction, Severity
        old, new = _identical_pair()
        other_old, other_new = _identical_pair()

        recursive_called: list[str] = []

        # An emit-style plugin that runs a nested checker.check() on a
        # different pool pair. After it returns, the outer run must
        # continue to see its own pools in subsequent plugin contexts.
        def recursive_plugin(ctx: FieldRuleContext) -> None:
            if recursive_called:
                return  # only fire the nested check once
            recursive_called.append(str(ctx.path))
            inner = SchemaChecker(include_builtin=False)
            inner.check(other_old, "t.M", other_new, "t.M")

        observed_pool_ids: list[int] = []

        def observer(ctx: FieldRuleContext) -> None:
            observed_pool_ids.append(id(ctx.old_pool))

        checker = SchemaChecker(include_builtin=False)
        checker.register_field_rule("recursive", recursive_plugin)
        checker.register_field_rule("observer", observer)
        checker.check(old, "t.M", new, "t.M")

        # The observer must have seen the OUTER pool (``old``),
        # not ``other_old`` and not ``None``.
        assert observed_pool_ids
        assert all(pid == id(old) for pid in observed_pool_ids)


class TestLoadRulePack:
    def test_registers_all_pack_rules(self) -> None:
        old, new = _identical_pair()
        seen: list[str] = []

        def make_plugin(name):
            def plugin(ctx: FieldRuleContext) -> None:
                seen.append(name)
            return plugin

        pack = _make_pack([
            ("alpha", make_plugin("alpha")),
            ("beta", make_plugin("beta")),
        ])
        checker = SchemaChecker()
        checker.load_rule_pack(pack)
        checker.check(old, "t.M", new, "t.M")
        assert "alpha" in seen
        assert "beta" in seen
