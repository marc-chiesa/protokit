"""Tests for the formatter registry primitives."""

from __future__ import annotations

import types

import pytest

from protokit.formatters import (
    FormatterContext,
    FormatterError,
    FormatterKind,
    clear_user_formatters,
    get_formatter,
    list_formatters,
    load_formatter_pack,
    register_formatter,
)


def _identity_formatter(report: object, ctx: FormatterContext) -> str:
    return f"{report!r}@{ctx.subcommand}"


@pytest.fixture(autouse=True)
def _isolate_registry() -> None:
    """Wipe user formatters around every test.

    Built-ins (none registered yet in Unit 2 — they land in
    Unit 3) survive across the wipe by construction; user
    formatters land via ``register_formatter`` or the pack
    loader and must not leak between tests.
    """
    clear_user_formatters()
    yield
    clear_user_formatters()


class TestFormatterKind:
    def test_all_kinds_present(self) -> None:
        # D3 added LINT_REPORT for the protokit lint subcommand.
        # Adding new kinds requires updating this assertion AND
        # adding a corresponding entry to the FormatterKind enum
        # docstring's Members list.
        assert {k.value for k in FormatterKind} == {
            "DIFF", "COMPAT", "COMPAT_HISTORY", "COMPAT_BISECT",
            "LINT_REPORT",
        }

    def test_is_plain_enum_not_intenum(self) -> None:
        # Plain Enum lets us add future members without
        # re-numbering existing ones.
        from enum import Enum, IntEnum
        assert issubclass(FormatterKind, Enum)
        assert not issubclass(FormatterKind, IntEnum)


class TestFormatterContext:
    def test_subcommand_required_others_optional(self) -> None:
        ctx = FormatterContext(subcommand="diff")
        assert ctx.subcommand == "diff"
        assert ctx.target_type is None
        assert ctx.old_target_type is None
        assert ctx.new_target_type is None
        assert ctx.level is None
        assert ctx.range_spec is None
        assert ctx.old_ref is None
        assert ctx.new_ref is None
        assert ctx.proto_file is None

    def test_is_frozen(self) -> None:
        ctx = FormatterContext(subcommand="diff")
        with pytest.raises(Exception):
            ctx.subcommand = "compat-check"  # type: ignore[misc]

    def test_full_population(self) -> None:
        ctx = FormatterContext(
            subcommand="compat-bisect",
            target_type="acme.User",
            old_target_type="acme.UserV1",
            new_target_type="acme.UserV2",
            level="consumer-safe",
            range_spec="HEAD~5..HEAD",
            old_ref="abc",
            new_ref="def",
            proto_file="acme/user.proto",
        )
        assert ctx.target_type == "acme.User"
        assert ctx.proto_file == "acme/user.proto"


class TestRegisterAndGet:
    def test_basic_register_and_get(self) -> None:
        register_formatter("foo", _identity_formatter, kind=FormatterKind.COMPAT)
        fn = get_formatter("foo", FormatterKind.COMPAT)
        assert fn is _identity_formatter

    def test_case_insensitive_register(self) -> None:
        register_formatter("FOO", _identity_formatter, kind=FormatterKind.COMPAT)
        assert get_formatter("foo", FormatterKind.COMPAT) is _identity_formatter
        assert get_formatter("Foo", FormatterKind.COMPAT) is _identity_formatter

    def test_case_insensitive_get(self) -> None:
        register_formatter("bar", _identity_formatter, kind=FormatterKind.DIFF)
        assert get_formatter("BAR", FormatterKind.DIFF) is _identity_formatter

    def test_get_missing_raises_keyerror(self) -> None:
        with pytest.raises(KeyError):
            get_formatter("nope", FormatterKind.COMPAT)

    def test_register_in_one_kind_does_not_leak_to_another(self) -> None:
        register_formatter("foo", _identity_formatter, kind=FormatterKind.COMPAT)
        with pytest.raises(KeyError):
            get_formatter("foo", FormatterKind.DIFF)


class TestReregistration:
    def test_duplicate_without_replace_raises(self) -> None:
        register_formatter("foo", _identity_formatter, kind=FormatterKind.COMPAT)
        with pytest.raises(FormatterError, match="already registered"):
            register_formatter("foo", _identity_formatter, kind=FormatterKind.COMPAT)

    def test_replace_true_overwrites(self) -> None:
        def first(report: object, ctx: FormatterContext) -> str:
            return "first"

        def second(report: object, ctx: FormatterContext) -> str:
            return "second"

        register_formatter("foo", first, kind=FormatterKind.COMPAT)
        register_formatter("foo", second, kind=FormatterKind.COMPAT, replace=True)
        ctx = FormatterContext(subcommand="x")
        assert get_formatter("foo", FormatterKind.COMPAT)(None, ctx) == "second"


class TestBuiltinReservation:
    # Use real built-in names registered at package import (Unit 3+).
    # This avoids the previous cleanup hack that was destructive once
    # the built-ins became real.

    def test_cannot_shadow_builtin_without_replace(self) -> None:
        # `human` is a built-in for every kind.
        with pytest.raises(FormatterError, match="built-in"):
            register_formatter(
                "human", _identity_formatter, kind=FormatterKind.COMPAT,
            )

    def test_cannot_shadow_builtin_even_with_replace(self) -> None:
        # `junit` is a built-in for COMPAT.
        with pytest.raises(FormatterError, match="built-in"):
            register_formatter(
                "junit", _identity_formatter,
                kind=FormatterKind.COMPAT, replace=True,
            )

    def test_case_insensitive_shadowing_check(self) -> None:
        # The reservation lowercases names; uppercase still rejects.
        with pytest.raises(FormatterError, match="built-in"):
            register_formatter(
                "HUMAN", _identity_formatter, kind=FormatterKind.DIFF,
            )


class TestListFormatters:
    def test_returns_built_ins_when_no_user_formatters(self) -> None:
        # Built-ins for DIFF / COMPAT / COMPAT_HISTORY / COMPAT_BISECT
        # are registered at ``protokit.formatters`` import (eager-load
        # tuple at ``__init__.py:60-71``). Each ships at least
        # ``human`` and ``json`` (Phase 1.5b).
        #
        # ``LINT_REPORT`` is intentionally NOT in the eager-load tuple
        # (cold-import preservation per D1's P0 finding); D3 ships
        # only ``human`` and registers it via ``_builtin_lint`` which
        # the lint subcommand module imports at its top. This test
        # only verifies the eagerly-loaded kinds — ``LINT_REPORT``
        # registration is covered in
        # ``tests/test_builtin_lint_formatter.py`` and the cold-import
        # contract is verified by the CI YAML smoke step extended in
        # D3 Unit 5.
        eagerly_loaded_kinds = (
            FormatterKind.DIFF,
            FormatterKind.COMPAT,
            FormatterKind.COMPAT_HISTORY,
            FormatterKind.COMPAT_BISECT,
        )
        for kind in eagerly_loaded_kinds:
            names = list_formatters(kind)
            assert "human" in names, f"missing human for {kind.value}"
            assert "json" in names, f"missing json for {kind.value}"

    def test_user_formatters_appear_alongside_built_ins(self) -> None:
        register_formatter("alpha", _identity_formatter, kind=FormatterKind.COMPAT)
        register_formatter("Zeta", _identity_formatter, kind=FormatterKind.COMPAT)
        names = list_formatters(FormatterKind.COMPAT)
        # Built-ins survive; user names are included; ordering is sorted.
        assert names == sorted(set(names))
        assert {"alpha", "human", "json", "zeta"}.issubset(set(names))


class TestClearUserFormatters:
    def test_removes_user_entries(self) -> None:
        register_formatter("foo", _identity_formatter, kind=FormatterKind.COMPAT)
        clear_user_formatters()
        with pytest.raises(KeyError):
            get_formatter("foo", FormatterKind.COMPAT)

    def test_preserves_builtins(self) -> None:
        # Real built-ins are registered at protokit.formatters import.
        # User entries should be wiped while built-ins stay resolvable.
        register_formatter("foo", _identity_formatter, kind=FormatterKind.COMPAT)
        clear_user_formatters()
        # Built-in is still callable (the real human formatter).
        assert callable(get_formatter("human", FormatterKind.COMPAT))
        # User entry is gone.
        with pytest.raises(KeyError):
            get_formatter("foo", FormatterKind.COMPAT)


class TestLoadFormatterPack:
    def test_loads_a_pack(self) -> None:
        mod = types.ModuleType("pack")
        mod.FORMATTERS = [
            ("a", _identity_formatter, FormatterKind.COMPAT),
            ("b", _identity_formatter, FormatterKind.DIFF),
        ]
        load_formatter_pack(mod)
        assert get_formatter("a", FormatterKind.COMPAT) is _identity_formatter
        assert get_formatter("b", FormatterKind.DIFF) is _identity_formatter

    def test_missing_attr_raises(self) -> None:
        mod = types.ModuleType("pack_no_formatters")
        with pytest.raises(AttributeError):
            load_formatter_pack(mod)

    def test_malformed_entry_raises(self) -> None:
        mod = types.ModuleType("pack_bad_entry")
        # 2-tuple instead of 3-tuple.
        mod.FORMATTERS = [("a", _identity_formatter)]
        with pytest.raises(TypeError, match="3-tuple|tuple"):
            load_formatter_pack(mod)

    def test_bad_kind_raises(self) -> None:
        mod = types.ModuleType("pack_bad_kind")
        mod.FORMATTERS = [("a", _identity_formatter, "COMPAT")]
        with pytest.raises(TypeError, match="FormatterKind"):
            load_formatter_pack(mod)

    def test_non_callable_fn_raises(self) -> None:
        # Catches the fn type-validation branch in
        # load_formatter_pack — previously untested per the
        # 2026-04-19 review.
        mod = types.ModuleType("pack_non_callable")
        mod.FORMATTERS = [("a", 42, FormatterKind.COMPAT)]
        with pytest.raises(TypeError, match="callable"):
            load_formatter_pack(mod)

    def test_empty_formatters_list_warns(self) -> None:
        # R-D7 fix: an empty FORMATTERS list used to succeed
        # silently, deferring the mistake to a misleading
        # "unknown formatter" error at lookup time. Now the
        # pack load emits a UserWarning so the mismatch
        # surfaces at the right layer.
        mod = types.ModuleType("pack_empty")
        mod.FORMATTERS = []
        with pytest.warns(UserWarning, match="empty FORMATTERS"):
            load_formatter_pack(mod)

    def test_two_phase_rollback_on_partial_failure(self) -> None:
        # Pre-populate so the third entry collides and aborts mid-load.
        register_formatter(
            "third", _identity_formatter, kind=FormatterKind.COMPAT,
        )
        mod = types.ModuleType("pack_partial")
        mod.FORMATTERS = [
            ("first", _identity_formatter, FormatterKind.COMPAT),
            ("second", _identity_formatter, FormatterKind.COMPAT),
            ("third", _identity_formatter, FormatterKind.COMPAT),  # collision
        ]
        with pytest.raises(FormatterError):
            load_formatter_pack(mod)
        # The first two must NOT be present — partial load rolled back.
        with pytest.raises(KeyError):
            get_formatter("first", FormatterKind.COMPAT)
        with pytest.raises(KeyError):
            get_formatter("second", FormatterKind.COMPAT)
        # The pre-existing entry survives.
        assert get_formatter("third", FormatterKind.COMPAT) is _identity_formatter
