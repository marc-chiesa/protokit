"""Regression pins for deferred cycle-2 audit findings (family C07, checker plugins).

Every ``xfail`` in this module pins a LIVE defect that a later release owns.
Each pin is ``@pytest.mark.xfail(strict=True, raises=...)`` on the test
function itself, with a ``reason`` that begins with the finding ID and names
the owning release. The suite stays green while the defect exists and the pin
flips to a hard failure (XPASS under strict mode) the day the mechanism is
fixed, so a fix cannot land silently and no pin can rot into a
permanently-red test.

Each pin asserts the correct outcome, and ``raises=`` names the exception that
was observed with ``--runxfail --tb=line`` under both protobuf backends. A
passing control sits beside every pin and shares its construction: a red
control says the harness broke, a red pin says the defect moved.

Both findings are about how ``SchemaChecker`` dispatches the emit-style
plugins registered with ``register_field_rule`` and ``register_message_rule``.
Every run here passes ``include_builtin=False``, so the plugin under test is
the only rule and what the report holds has one cause.

Pinned here:

* **C07-C1** — cyclic type pairs are re-walked once per path.
  ``register_message_rule`` and ``register_field_rule`` promise that a plugin
  fires once per ``(old, new)`` message type pair. ``SchemaChecker._traverse``
  leaves a pair whose subtree the cycle guard cut against an ancestor out of
  its cache and walks it again at the next path, so on
  ``Root{m: M, n: N}, M{n: N}, N{m: M}`` the message plugin runs twice for
  ``(t.M, t.M)``. The pin holds the three-type contract only; on a 24-type
  ring the same mechanism costs 150,048 dispatches and seconds per check.
  Owner U4 (0.18.0).
* **C07-C3** — plugins whose body never runs are accepted and reported clean.
  An ``async def`` with ``yield`` (an async generator function), a ``def``
  with ``yield`` (a generator function) and a lambda returning an async
  generator pass ``_reject_async`` at registration, and at dispatch their
  return value is not an awaitable, so nothing records them: the report has
  no finding and no error, and ``is_compatible`` is True. The pin accepts
  either fix, refused at registration (``TypeError``) or refused at dispatch
  (an error diagnostic). Owner U4 (0.18.0).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from typing import Any

import pytest
from google.protobuf import descriptor_pb2, descriptor_pool

from protokit.schema import SchemaChecker, Severity

_F = descriptor_pb2.FieldDescriptorProto


def _pool(messages: dict[str, list[tuple[str, int, str | None]]]) -> descriptor_pool.DescriptorPool:
    """Build proto2 package ``t`` holding ``messages`` into a fresh pool.

    ``messages`` maps a message name to its fields as ``(name, number,
    type_name)``; ``type_name`` is the referenced message (``".t.M"``), or
    ``None`` for an ``int32`` field.
    """
    fdp = descriptor_pb2.FileDescriptorProto(name="c07.proto", package="t", syntax="proto2")
    for message_name, fields in messages.items():
        message = fdp.message_type.add(name=message_name)
        for name, number, type_name in fields:
            if type_name is None:
                message.field.add(
                    name=name, number=number, type=_F.TYPE_INT32, label=_F.LABEL_OPTIONAL
                )
            else:
                message.field.add(
                    name=name,
                    number=number,
                    type=_F.TYPE_MESSAGE,
                    type_name=type_name,
                    label=_F.LABEL_OPTIONAL,
                )
    pool = descriptor_pool.DescriptorPool()
    pool.Add(fdp)
    return pool


# ---------------------------------------------------------------------------
# C07-C1 — cyclic type pairs re-walked once per path
# ---------------------------------------------------------------------------

#: ``Root{m: M, n: N}, M{n: N, leaf}, N{m: M, tag}``: M and N reference each
#: other, and Root reaches the cycle from both sides.
_CYCLE = {
    "Root": [("m", 1, ".t.M"), ("n", 2, ".t.N")],
    "M": [("n", 1, ".t.N"), ("leaf", 2, None)],
    "N": [("m", 1, ".t.M"), ("tag", 2, None)],
}

#: ``Outer{a: Shared, b: Shared}``: one type shared at two paths, no cycle.
_SHARED = {
    "Shared": [("x", 1, None)],
    "Outer": [("a", 1, ".t.Shared"), ("b", 2, ".t.Shared")],
}


def _message_plugin_calls(messages: dict, root: str) -> Counter[tuple[str, str]]:
    """Check the schema against itself; count message-plugin calls per type pair."""
    calls: Counter[tuple[str, str]] = Counter()

    def count(ctx: Any) -> None:
        calls[(ctx.old_descriptor.full_name, ctx.new_descriptor.full_name)] += 1

    checker = SchemaChecker(include_builtin=False)
    checker.register_message_rule("count", count)
    report = checker.check(_pool(messages), root, _pool(messages), root)
    if report.errors:
        pytest.fail(f"the counting plugin failed, so it counts nothing: {report.errors}")
    return calls


def test_c07_c1_acyclic_shared_type_is_dispatched_once_per_pair_control() -> None:
    """A type shared at two paths, without a cycle, is dispatched once."""
    calls = _message_plugin_calls(_SHARED, "t.Outer")

    assert calls == {("t.Outer", "t.Outer"): 1, ("t.Shared", "t.Shared"): 1}


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "C07-C1: owned by U4 (0.18.0). SchemaChecker._traverse does not cache a "
        "type pair whose subtree the cycle guard cut against an ancestor and "
        "walks it again at the next path, so on Root{m:M,n:N}, M{n:N}, N{m:M} the "
        "message plugin runs twice for (t.M, t.M) (a 24-type ring: 150,048 "
        "dispatches, 3.4 s upb, 4.2 s pure-Python)"
    ),
)
def test_c07_c1_cyclic_type_pairs_are_dispatched_once_per_pair() -> None:
    """``register_message_rule``: "Fires once per ``(old, new)`` message type pair".

    One finding per path is the documented path-complete default and is not
    asserted against here; the pin counts plugin calls, which the docstrings
    bound at one per pair.
    """
    calls = _message_plugin_calls(_CYCLE, "t.Root")

    # Every pair has to be visited at all: a change that skips one is not the fix.
    if set(calls) != {("t.Root", "t.Root"), ("t.M", "t.M"), ("t.N", "t.N")}:
        pytest.fail(f"premise lost: the walk did not reach each pair -> {dict(calls)}")

    assert all(count == 1 for count in calls.values()), (
        f"a type pair on the M <-> N cycle was dispatched more than once -> {dict(calls)}"
    )


# ---------------------------------------------------------------------------
# C07-C3 — plugins whose body never runs are accepted and reported clean
# ---------------------------------------------------------------------------

#: ``t.M { int32 x = 1; }`` checked against itself: every finding here comes
#: from the plugin under test.
_ONE_FIELD = {"M": [("x", 1, None)]}


def _emit(ctx: Any) -> None:
    ctx.emit(severity=Severity.WIRE, message="x is forbidden")


def _sync_plugin(ctx: Any) -> None:
    _emit(ctx)


async def _coroutine_plugin(ctx: Any) -> None:
    _emit(ctx)


async def _async_generator_plugin(ctx: Any) -> Any:
    _emit(ctx)
    yield


def _generator_plugin(ctx: Any) -> Any:
    _emit(ctx)
    yield


#: The shapes whose body never runs. An un-iterated generator or async
#: generator is dropped without a warning, so none of them needs cleaning up.
_SILENT_SHAPES: dict[str, Callable[[Any], Any]] = {
    "async-generator-function": _async_generator_plugin,
    "lambda-returning-an-async-generator": lambda ctx: _async_generator_plugin(ctx),
    "generator-function": _generator_plugin,
}

_SCOPES = pytest.mark.parametrize("scope", ["field", "message"])


def _register(checker: SchemaChecker, scope: str, plugin: Callable[[Any], Any]) -> None:
    getattr(checker, f"register_{scope}_rule")("forbid_x", plugin)


def _check(checker: SchemaChecker) -> Any:
    return checker.check(_pool(_ONE_FIELD), "t.M", _pool(_ONE_FIELD), "t.M")


@_SCOPES
def test_c07_c3_sync_plugin_runs_and_reports_control(scope: str) -> None:
    """The same body as a plain function runs: one finding, no error."""
    checker = SchemaChecker(include_builtin=False)
    _register(checker, scope, _sync_plugin)

    report = _check(checker)

    assert [f.rule_id for f in report.findings] == ["forbid_x"]
    assert report.errors == ()


@_SCOPES
def test_c07_c3_async_def_plugin_is_refused_at_registration_control(scope: str) -> None:
    """An ``async def`` without ``yield`` is what ``_reject_async`` already refuses."""
    checker = SchemaChecker(include_builtin=False)

    with pytest.raises(TypeError, match="async function"):
        _register(checker, scope, _coroutine_plugin)


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "C07-C3: owned by U4 (0.18.0). _reject_async refuses only "
        "inspect.iscoroutinefunction and dispatch refuses only an awaitable "
        "return, so a generator or async-generator plugin is accepted, its body "
        "never runs, and the report has no finding and no error "
        "(is_compatible True)"
    ),
)
@_SCOPES
@pytest.mark.parametrize("shape", list(_SILENT_SHAPES))
def test_c07_c3_plugin_whose_body_never_runs_is_refused(scope: str, shape: str) -> None:
    """A plugin whose body cannot run must be refused, not reported clean.

    The register docstrings say ``async def`` plugins are rejected at
    registration and that dynamically wrapped async callables are caught at
    dispatch. Either refusal counts as fixed: a ``TypeError`` at registration
    (as ``schema/lint/decorator.py`` does for the lint twin), or an error
    diagnostic on the report. A lambda returning an async generator cannot be
    seen at registration, so for that shape only the second can hold.
    """
    checker = SchemaChecker(include_builtin=False)
    try:
        _register(checker, scope, _SILENT_SHAPES[shape])
    except TypeError:
        return

    report = _check(checker)

    # The body emits a finding; a fix that runs it instead of refusing it is
    # neither outcome above.
    if report.findings:
        pytest.fail(f"the {shape} plugin's body ran: {report.findings}")
    assert report.errors, (
        f"{scope} plugin of shape {shape} never ran and the report is clean: "
        f"findings={report.findings} errors={report.errors} "
        f"is_compatible={report.is_compatible}"
    )
