"""Optional PyHamcrest adapter over the framework-agnostic proto matcher.

``equals_proto(expected)`` returns a `hamcrest <https://pyhamcrest.readthedocs.io>`_
``BaseMatcher`` usable directly with ``assert_that`` — and it exposes the same
fluent knobs as :func:`protokit.message.matchers.expect_proto`
(``.partially()`` / ``.ignoring()`` / ``.as_set()`` / ``.with_presence()`` /
``.strict_presence()`` / ``.approximately()``), so::

    assert_that(actual, equals_proto(expected).partially())

is policy-equivalent to ``proto_match(actual, expected, partial=True)`` (R3, AE7).

This is a *front-end* over the same single source as the agnostic matcher: it
builds a :class:`~protokit.message.matchers.MatchPolicy`, runs the *same*
``MatchPolicy → MessageDifferencer → compare → DiffResult`` path via
:func:`~protokit.message.matchers._build_differ`, and renders any mismatch with
the *same* :func:`~protokit.message.pytest_plugin.render_diff_lines` formatter
(SWI-1, KTD-4). It never reaches into private differ state.

Optional-extra idiom (mirrors ``protokit.storage._columnar``'s ``[parquet]``
guard, KTD-3): PyHamcrest lives behind the ``protokit[hamcrest]`` extra. A
``importlib.util.find_spec`` probe + a lazy in-function ``import hamcrest`` keep
this module importable WITHOUT the extra installed; using ``equals_proto``
without it raises :class:`HamcrestExtraNotInstalledError` (naming the install)
rather than a bare ``ImportError``.

**Lazy ``BaseMatcher`` (the load-bearing difference from ``[parquet]``, F1):**
unlike the columnar adapter — which never subclasses a ptars type — this adapter
MUST return a ``hamcrest.BaseMatcher`` subclass. That subclass is defined
*lazily inside* the guarded factory (:func:`_proto_matcher_class`), never at
module top, so importing this module (and, transitively, ``protokit.message``)
does not eagerly import ``hamcrest``. The actionable error therefore fires only
on *use*, not at package import (R3).

This module is strict-typed (``mypy --strict``) and gated by
``tests/meta/test_static_analysis.py``. The ``import hamcrest`` resolves to ``Any``
under the ``[[tool.mypy.overrides]]`` ``ignore_missing_imports`` block in
``pyproject.toml``, so ``hamcrest.BaseMatcher`` is an ``Any`` base at type-check
time.
"""

from __future__ import annotations

import dataclasses
import importlib.util
from typing import TYPE_CHECKING, Any

from protokit.message.matchers import (
    MatcherError,
    MatchPolicy,
    _build_differ,
    _match_failure_header,
    _PolicyChain,
)
from protokit.message.pytest_plugin import render_diff_lines

if TYPE_CHECKING:  # pragma: no cover — typing-only import
    from google.protobuf.message import Message


__all__ = [
    "HamcrestExtraNotInstalledError",
    "equals_proto",
]


class HamcrestExtraNotInstalledError(MatcherError):
    """``equals_proto`` was used without the ``protokit[hamcrest]`` extra.

    Subclasses :class:`~protokit.message.matchers.MatcherError` so the matcher
    exception family stays coherent (a *configuration* problem, not a match
    failure). Raised in place of a raw ``ImportError`` so the remedy is
    actionable.

    Attributes:
        missing: The name of the missing distribution (``"hamcrest"``).
    """

    missing: str

    def __init__(self, missing: str = "hamcrest") -> None:
        self.missing = missing
        super().__init__(
            f"equals_proto requires the optional {missing!r} package; install it "
            f"with `pip install protokit[hamcrest]`"
        )


def _require_hamcrest() -> None:
    """Raise :class:`HamcrestExtraNotInstalledError` if the extra is absent.

    Probes with ``importlib.util.find_spec`` (no import side effect) so the check
    is cheap and monkeypatchable, mirroring
    ``protokit.storage._columnar._require_parquet``.
    """
    if importlib.util.find_spec("hamcrest") is None:
        raise HamcrestExtraNotInstalledError("hamcrest")


def _has_hamcrest() -> bool:
    """Return whether the ``protokit[hamcrest]`` extra is importable (internal)."""
    try:
        _require_hamcrest()
        return True
    except HamcrestExtraNotInstalledError:
        return False


def _proto_matcher_class() -> type:
    """Build (lazily, once-guarded) the ``hamcrest.BaseMatcher`` subclass.

    The subclass is defined *inside* this function — after the guard — so the
    module imports cleanly without ``hamcrest`` and ``import protokit.message``
    never eagerly imports it (F1). Returns the class; the factory
    :func:`equals_proto` instantiates it.
    """
    _require_hamcrest()
    # lazy: only when the [hamcrest] extra is present (KTD-3). ``BaseMatcher``
    # lives in the ``hamcrest.core.base_matcher`` submodule, not on the top-level
    # ``hamcrest`` package — import it directly. The mypy override covers
    # ``hamcrest.*`` so this base types as ``Any`` under --strict.
    from hamcrest.core.base_matcher import BaseMatcher

    class _ProtoMatcher(BaseMatcher, _PolicyChain):  # type: ignore[misc]  # Any base
        """A ``hamcrest`` matcher delegating to the shared policy → differ path.

        Holds the reference ``expected`` message and a frozen
        :class:`MatchPolicy`; both fluent steps and ``assert_that`` run through
        the *same* ``_build_differ`` the agnostic matcher uses, so the two
        surfaces are policy-equivalent (SWI-1). ``describe_mismatch`` renders the
        per-field diff via the shared :func:`render_diff_lines` formatter (KTD-4).

        The seven fluent steps come from the shared
        :class:`~protokit.message.matchers._PolicyChain` mixin (a PLAIN class,
        imported at module top so this lazy ``BaseMatcher`` subclass can mix it
        in without ``hamcrest`` ever being imported eagerly, F1). They each
        return a NEW ``_ProtoMatcher`` with an updated policy (immutable
        builder, mirroring ``ProtoMatcher``), so a partially-configured matcher
        can be branched without surprise.
        """

        def __init__(self, expected: Message, policy: MatchPolicy) -> None:
            self._expected = expected
            self._policy = policy

        @property
        def _policy_obj(self) -> MatchPolicy:
            """The accumulated policy (the :class:`_PolicyChain` hook)."""
            return self._policy

        # -- comparison -----------------------------------------------------

        def _matches(self, item: Any) -> bool:
            """Return whether ``item`` (the actual) matches under the policy.

            Maps ``expected`` -> the differ's ``left`` and ``item`` (actual) ->
            its ``right`` (KTD-5), so partial/presence/set directionality reads
            correctly. Predicate exceptions in ``ignore`` / ``as_set`` selectors
            propagate unchanged — author bugs, not match failures (SWI-3).
            """
            differ = _build_differ(self._policy)
            result = differ.compare(self._expected, item)
            return not result.has_changes()

        # -- descriptions ---------------------------------------------------

        def describe_to(self, description: Any) -> None:
            """Describe the expected value (the ``assert_that`` "Expected:" line)."""
            description.append_text(
                f"a proto matching {self._expected.DESCRIPTOR.full_name}"
            )

        def describe_mismatch(self, item: Any, description: Any) -> None:
            """Append the engine's per-field rich diff to the mismatch line.

            Re-runs the comparison to obtain the ``DiffResult`` and renders it
            with the SAME :func:`render_diff_lines` the agnostic matcher and the
            pytest ``==`` hook use, so the diff text is identical across surfaces
            (KTD-4, SWI-1). On the (defensive) equal case, falls back to
            hamcrest's default ``was ...`` description.
            """
            differ = _build_differ(self._policy)
            result = differ.compare(self._expected, item)
            if not result.has_changes():
                super().describe_mismatch(item, description)
                return

            header = _match_failure_header(self._expected, item)
            description.append_text("\n".join(render_diff_lines(result, header)))

        # -- fluent builder ------------------------------------------------
        # The seven chain methods come from the shared ``_PolicyChain`` mixin;
        # only the type-specific ``_with`` is provided here so each step
        # returns a new ``_ProtoMatcher`` (immutable builder).

        def _with(self, **changes: Any) -> _ProtoMatcher:
            """Return a new matcher with ``policy`` fields replaced by ``changes``."""
            new_policy = dataclasses.replace(self._policy, **changes)
            return _ProtoMatcher(self._expected, new_policy)

    return _ProtoMatcher


def equals_proto(expected: Message) -> Any:
    """Return a ``hamcrest`` matcher asserting a message equals ``expected``.

    Usable directly with ``assert_that``::

        assert_that(actual, equals_proto(expected))

    and fluently chainable with the same knobs as
    :func:`protokit.message.matchers.expect_proto`::

        assert_that(actual, equals_proto(expected).partially().as_set("tags"))

    Every form runs the SAME ``MatchPolicy → MessageDifferencer → compare`` path
    as the agnostic matcher, so it is policy-equivalent (SWI-1, AE7). On mismatch
    the matcher's ``describe_mismatch`` surfaces the engine's per-field rich diff
    via the shared formatter (KTD-4).

    Directional: ``expected`` maps to the differ's ``left`` and the value under
    test maps to its ``right`` (KTD-5), so ``.partially()`` ignores fields
    present only on the actual.

    Requires the ``protokit[hamcrest]`` extra. Calling this without it raises
    :class:`HamcrestExtraNotInstalledError` naming the install — never a bare
    ``ImportError`` — because the ``BaseMatcher`` subclass is built lazily inside
    the guarded factory (F1).

    Args:
        expected: The reference message to match a value against.

    Returns:
        A ``hamcrest.BaseMatcher`` (typed ``Any`` because ``hamcrest`` resolves
        to ``Any`` under the strict-mypy override) configured with the default
        (full, exact) policy; chain fluent methods to refine it.

    Raises:
        HamcrestExtraNotInstalledError: If the ``protokit[hamcrest]`` extra is
            not installed.
    """
    matcher_cls = _proto_matcher_class()
    return matcher_cls(expected, MatchPolicy())
