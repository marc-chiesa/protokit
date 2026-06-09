"""pytest assertion hook, rendering config, and matcher fixture.

Provides three things for protobuf testing:

1. ``pytest_assertrepr_compare`` — rich diff output when a bare
   ``assert msg1 == msg2`` fails for protobuf messages. The boolean pass/fail
   is decided by proto ``==`` *before* this hook runs; the hook only enriches
   the *failure rendering* (KTD-9). It is therefore configured with
   PRESENTATION knobs only — never pass/fail-altering comparison policies.
2. ``pytest_addoption`` — registers the presentation knobs as pytest ini
   options (``protokit_message_max_diff_lines`` / ``protokit_message_enhanced_diff``).
   Values may also live in pyproject's ``[tool.protokit.message]`` table; the
   ini option wins when both are set (see :func:`_resolve_render_config`).
3. ``proto_matcher`` — a fixture yielding a configured-matcher factory so test
   authors apply NON-default policies (partial / set / ignore / presence /
   tolerance) explicitly, through the matcher facade rather than bare ``==``.

Usage — add to your project's conftest.py:

    from protokit.message.pytest_plugin import (  # noqa: F401
        pytest_addoption,
        pytest_assertrepr_compare,
        proto_matcher,
    )

Or register as a pytest plugin in pyproject.toml:

    [tool.pytest.ini_options]
    plugins = ["protokit.message.pytest_plugin"]
"""

from __future__ import annotations

import itertools
import sys
import warnings
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from google.protobuf.message import Message

from protokit.message.differ import MessageDifferencer
from protokit.message.formatting import format_value as _format_value
from protokit.message.model import ChangeType, DiffResult

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on py3.10
    import tomli as tomllib

# pytest is a TEST-only dependency (the [dev] extra), but this module is
# imported by ``protokit.message`` for the shared ``render_diff_lines``. Import
# pytest lazily/guarded so ``import protokit.message`` works in a pytest-free
# install: the ``proto_matcher`` fixture (the only thing needing pytest at
# definition time) is registered only when pytest is importable, while the hook
# functions rely on string annotations (``from __future__ import annotations``)
# and so need no runtime pytest symbol.
try:
    import pytest as _pytest
except ModuleNotFoundError:  # pragma: no cover - pytest absent only in prod installs
    _pytest = None  # type: ignore[assignment]

if TYPE_CHECKING:  # pragma: no cover - typing-only imports
    import pytest

    from protokit.message._selector import SelectorSpec
    from protokit.message.comparators import MessageFieldComparison
    from protokit.message.matchers import Approx, ProtoMatcher


def render_diff_lines(
    result: DiffResult, header: str, *, max_diff_lines: int | None = None
) -> list[str]:
    """Render a non-empty ``DiffResult`` into human-readable display lines.

    The single source of per-difference rendering shared by the pytest
    assertion hook and the matcher facade (``protokit.message.matchers``),
    so the two surfaces always agree on diff text (KTD-4). The header line
    is supplied by the caller (the pytest hook names the two message types;
    the matcher names ``expected``/``actual``); everything below it — the
    difference count, the per-``Difference`` rows, and any diagnostics — is
    rendered identically here.

    Reads ONLY the canonical ``Difference.left_value`` / ``right_value`` (and
    the ``left_*`` / ``right_*`` pairs) — never the deprecated ``old_value`` /
    ``new_value`` aliases, which emit ``UserWarning`` and break strict-warning
    CI (see ``docs/solutions/design-patterns/neutral-field-rename-with-deprecation-window.md``).

    ``max_diff_lines`` is a PURELY PRESENTATIONAL cap (KTD-9): it limits how
    many per-``Difference`` rows are *rendered*, never which differences the
    engine *finds*. The count line still reports the true total, and a
    ``"… N more difference(s) (capped …)"`` footer names the cap so a reader
    knows the output was truncated, not that the comparison stopped early.
    Diagnostics are always rendered in full (they are not difference rows).

    Args:
        result: A ``DiffResult`` with at least one difference. The caller is
            responsible for checking ``result.has_changes()`` first; this
            function does not special-case the empty result.
        header: The first display line (e.g. a ``"A != B"`` type summary).
        max_diff_lines: Optional cap on the number of per-``Difference`` rows
            rendered. ``None`` or a non-positive value means unlimited (no
            truncation). When positive and exceeded, the first
            ``max_diff_lines`` rows are shown followed by a truncation footer.

    Returns:
        A list of display lines: ``header``, the difference count, up to
        ``max_diff_lines`` rows (plus a truncation footer when capped), then
        one row per diagnostic.
    """
    lines = [header, f"  {len(result)} difference(s):"]

    total = len(result)
    cap = max_diff_lines if (max_diff_lines is not None and max_diff_lines > 0) else None
    # ``islice`` with stop=None means "no limit", so an uncapped render walks
    # every difference; a positive cap renders only the first ``cap`` rows.
    for diff in itertools.islice(result, cap):
        path_str = str(diff.path) if diff.path else "(root)"
        match diff.change_type:
            case ChangeType.ADDED:
                lines.append(f"  + {path_str}: {_format_value(diff.right_value)}")
            case ChangeType.REMOVED:
                lines.append(f"  - {path_str}: {_format_value(diff.left_value)}")
            case ChangeType.MODIFIED:
                left_str = _format_value(diff.left_value)
                right_str = _format_value(diff.right_value)
                lines.append(f"  ~ {path_str}: {left_str} -> {right_str}")
            case ChangeType.TYPE_CHANGED:
                lines.append(f"  T {path_str}: {diff.left_type} -> {diff.right_type}")
            case ChangeType.FIELD_NUMBER_CHANGED:
                lines.append(
                    f"  # {path_str}: field {diff.left_field_number} -> {diff.right_field_number}"
                )
            case ChangeType.CARDINALITY_CHANGED:
                lines.append(
                    f"  C {path_str}: {diff.left_label} -> {diff.right_label}"
                )

    if cap is not None and total > cap:
        lines.append(
            f"  … {total - cap} more difference(s) "
            f"(capped at max_diff_lines={cap})"
        )

    for d in result.diagnostics:
        prefix = "error" if d.level == "error" else "warning"
        lines.append(f"  {prefix}: {d}")

    return lines


# ---------------------------------------------------------------------------
# Presentation config for the bare-``==`` rich-diff rendering (KTD-9)
# ---------------------------------------------------------------------------
#
# These knobs change ONLY how a *failed* ``assert a == b`` is RENDERED — never
# whether it passes or fails (proto ``==`` decides that before the hook runs).
# Pass/fail-altering policies (ignore / partial / set / presence / tolerance)
# are reachable ONLY through the matcher facade (the ``proto_matcher`` fixture,
# ``proto_match`` / ``expect_proto``), never through this config.

# pytest ini-option names (registered in ``pytest_addoption``). These mirror the
# pyproject ``[tool.protokit.message]`` keys with a ``protokit_message_`` prefix
# so they don't collide with other plugins' ini namespace.
_INI_MAX_DIFF_LINES = "protokit_message_max_diff_lines"
_INI_ENHANCED_DIFF = "protokit_message_enhanced_diff"

# pyproject ``[tool.protokit.message]`` keys (the second source).
_PYPROJECT_MAX_DIFF_LINES = "max_diff_lines"
_PYPROJECT_ENHANCED_DIFF = "enhanced_diff"


@dataclass(frozen=True)
class RenderConfig:
    """Resolved PRESENTATION config for the bare-``==`` diff rendering.

    Presentation-only by construction (KTD-9): the only knobs here change how a
    *failed* assertion is rendered, not the comparison's pass/fail.

    Attributes:
        enhanced: When ``True`` (default) the hook produces the rich protobuf
            diff; when ``False`` it returns ``None`` and pytest renders its own
            default representation. A global off-switch for teams that prefer
            pytest's stock output.
        max_diff_lines: Cap on the number of per-difference rows rendered.
            ``0`` (default) means unlimited. The engine still finds every
            difference; only the rendering is truncated, with a footer naming
            the cap.
    """

    enhanced: bool = True
    max_diff_lines: int = 0


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register the presentation knobs as pytest ini options.

    Makes the two knobs settable from ``[tool.pytest.ini_options]`` (or
    ``pytest.ini`` / ``setup.cfg``) so a project can configure the bare-``==``
    rendering without writing a conftest hook. The same knobs may also be set
    in pyproject's ``[tool.protokit.message]`` table; :func:`_resolve_render_config`
    defines the precedence (the pytest ini option wins when both are set).

    Args:
        parser: The pytest option parser pytest hands to the hook.
    """
    # Both options default to ``None`` (not their effective default) so the
    # resolver can tell "unset" from "explicitly set", which is what makes the
    # ini-wins-over-pyproject precedence deterministic. The effective defaults
    # (enhanced=True, max_diff_lines=0) live in ``RenderConfig`` / the resolver.
    parser.addini(
        _INI_ENHANCED_DIFF,
        help=(
            "protokit: enable the rich protobuf diff for a failed "
            "`assert a == b` (true/false; default true). Presentation only — "
            "does not change =='s pass/fail."
        ),
        default=None,
    )
    parser.addini(
        _INI_MAX_DIFF_LINES,
        help=(
            "protokit: cap the number of per-difference rows rendered for a "
            "failed `assert a == b` (0 = unlimited; default 0). Presentation "
            "only — the engine still finds every difference."
        ),
        default=None,
    )


def _coerce_max_diff_lines(value: object, source: str) -> int:
    """Coerce a configured ``max_diff_lines`` to a non-negative int.

    Args:
        value: The raw value from a config source (ini gives a string;
            pyproject gives a parsed TOML scalar).
        source: A human-readable, SOURCE-ACCURATE label for error messages —
            the ACTUAL origin of ``value`` (e.g. ``"protokit_message_max_diff_lines"``
            for the pytest ini option, or ``"[tool.protokit.message] max_diff_lines"``
            for pyproject). Per
            docs/solutions/best-practices/source-aware-error-messages-multi-source-resolved-value-2026-05-11.md
            the message must name where the value really came from, not a
            hard-coded source.

    Returns:
        The value as a non-negative ``int``.

    Raises:
        ValueError: If ``value`` is not a non-negative integer, naming
            ``source`` so the author edits the right place.
    """
    # bool is an int subclass; reject it before the int path so ``true``
    # doesn't silently coerce to 1.
    if isinstance(value, bool):
        raise ValueError(
            f"{source} must be a non-negative integer, got boolean {value!r}"
        )
    # The two real sources give an int (pyproject TOML) or a str (pytest ini);
    # narrow to those before ``int()`` so the result stays a concrete ``int``.
    if not isinstance(value, (int, str)):
        raise ValueError(
            f"{source} must be a non-negative integer, got {value!r}"
        )
    try:
        coerced = int(value)
    except ValueError:
        raise ValueError(
            f"{source} must be a non-negative integer, got {value!r}"
        ) from None
    if coerced < 0:
        raise ValueError(
            f"{source} must be a non-negative integer, got {coerced!r}"
        )
    return coerced


def _coerce_enhanced(value: object, source: str) -> bool:
    """Coerce a configured ``enhanced`` toggle to a bool.

    Accepts a real bool (pyproject TOML) or a truthy/falsy string (ini), so
    both sources resolve consistently. ``source`` is the SOURCE-ACCURATE label
    used in the error message (see :func:`_coerce_max_diff_lines`).

    Args:
        value: The raw value from a config source.
        source: Source-accurate label for the error message.

    Returns:
        The value as a ``bool``.

    Raises:
        ValueError: If ``value`` is not a recognized boolean, naming ``source``.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
    raise ValueError(
        f"{source} must be a boolean (true/false), got {value!r}"
    )


def _read_pyproject_message_table(rootpath: Path) -> dict[str, Any]:
    """Read ``[tool.protokit.message]`` from the rootdir's pyproject.toml.

    Best-effort and non-fatal on a MISSING file or absent table (returns an
    empty mapping) — the pyproject source is optional and the pytest ini option
    can stand alone. A present-but-unparseable pyproject.toml raises, because a
    broken config the author DID write should be surfaced, not silently ignored.

    Args:
        rootpath: The pytest ``config.rootpath`` (the session root directory).

    Returns:
        The ``[tool.protokit.message]`` table as a dict, or ``{}`` if the file
        or table is absent.

    Raises:
        ValueError: If the pyproject.toml exists but cannot be parsed.
    """
    pyproject = rootpath / "pyproject.toml"
    if not pyproject.is_file():
        return {}
    try:
        parsed = tomllib.loads(pyproject.read_text("utf-8"))
    except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(
            f"protokit: could not read [tool.protokit.message] from "
            f"{pyproject}: {type(exc).__name__}"
        ) from exc
    table = parsed.get("tool", {}).get("protokit", {}).get("message", {})
    return table if isinstance(table, dict) else {}


def _resolve_render_config(config: pytest.Config) -> RenderConfig:
    """Resolve the bare-``==`` rendering config from both sources.

    Two sources, with a documented precedence:

    1. The pytest ini option (``protokit_message_*``) — the most specific,
       pytest-native source the author set for this session.
    2. The pyproject ``[tool.protokit.message]`` table — a project-wide default.

    **Precedence: the pytest ini option WINS over pyproject** when both set a
    value. (The ini option is the session-scoped, explicitly-pytest source; a
    project keeps a pyproject default and overrides it per-session via the ini
    option, mirroring how pytest's own settings layer.) An UNSET ini option
    (its registered default) does not override pyproject — only an explicitly
    set ini value does, so a pyproject value is honored when no ini value exists.

    Any coercion error names the ACTUAL source of the offending value (the
    pytest ini key vs the ``[tool.protokit.message]`` key), never a hard-coded
    one — see
    docs/solutions/best-practices/source-aware-error-messages-multi-source-resolved-value-2026-05-11.md.

    Args:
        config: The active pytest ``Config``.

    Returns:
        A resolved :class:`RenderConfig`.

    Raises:
        ValueError: If a configured value (from either source) is malformed.
    """
    pyproject = _read_pyproject_message_table(config.rootpath)

    # --- enhanced toggle (ini wins over pyproject; both default True) ---
    ini_enhanced = config.getini(_INI_ENHANCED_DIFF)  # None when unset
    if ini_enhanced is not None:
        enhanced = _coerce_enhanced(ini_enhanced, _INI_ENHANCED_DIFF)
    elif _PYPROJECT_ENHANCED_DIFF in pyproject:
        enhanced = _coerce_enhanced(
            pyproject[_PYPROJECT_ENHANCED_DIFF],
            f"[tool.protokit.message] {_PYPROJECT_ENHANCED_DIFF}",
        )
    else:
        enhanced = True

    # --- max_diff_lines cap (ini wins over pyproject; both default 0) ---
    ini_max = config.getini(_INI_MAX_DIFF_LINES)  # None when unset
    if ini_max is not None:
        max_diff_lines = _coerce_max_diff_lines(ini_max, _INI_MAX_DIFF_LINES)
    elif _PYPROJECT_MAX_DIFF_LINES in pyproject:
        max_diff_lines = _coerce_max_diff_lines(
            pyproject[_PYPROJECT_MAX_DIFF_LINES],
            f"[tool.protokit.message] {_PYPROJECT_MAX_DIFF_LINES}",
        )
    else:
        max_diff_lines = 0

    return RenderConfig(enhanced=enhanced, max_diff_lines=max_diff_lines)


def pytest_assertrepr_compare(
    config: pytest.Config | None, op: str, left: Any, right: Any
) -> list[str] | None:
    """Rich diff output for protobuf message assertions.

    Called automatically by pytest when an ``assert left == right``
    statement fails. Activates only when both operands are protobuf
    ``Message`` instances and ``op == "=="`` — all other cases fall
    back to pytest's default representation.

    The hook enriches the *failure rendering* only; it never changes
    ``==``'s pass/fail (KTD-9) — proto equality decided the boolean before
    pytest called this hook. Comparison is therefore done with a default
    ``MessageDifferencer`` (no ignore fields, no ``treat_as_map``, exact float
    comparison, unlimited depth); the resolved :class:`RenderConfig` supplies
    PRESENTATION knobs only:

    - ``enhanced=False`` returns ``None`` so pytest renders its own default.
    - ``max_diff_lines > 0`` caps the number of rendered difference rows.

    The ``not result.has_changes() -> return None`` guard is retained: a
    presentation-only differ cannot find zero differences when ``==`` already
    failed for a real difference, but a defensive fallback keeps the plugin
    from masking the failure if it somehow does.

    If config resolution OR the differencer raises for any reason, the
    exception is caught, a ``UserWarning`` is emitted, and pytest falls back to
    its default output — so a misconfigured plugin never masks a test failure.

    Args:
        config: The active pytest ``Config``, from which the presentation
            config is resolved (pytest passes it to this hook). ``None`` is
            accepted for direct invocation in unit tests and falls back to the
            default :class:`RenderConfig`.
        op: The comparison operator pytest caught (e.g. ``"=="``,
            ``"!="``, ``"<"``). Only ``"=="`` is handled.
        left: Left operand of the failing assertion.
        right: Right operand of the failing assertion.

    Returns:
        A list of display lines for pytest (header + per-difference
        rows + optional warning rows), or ``None`` to defer to the
        default representation. Returning ``None`` happens when:
        the op isn't ``"=="``; either operand isn't a ``Message``;
        the enhanced toggle is off; config resolution or the differencer
        raised; or no differences were found (which shouldn't happen since
        ``==`` failed, but we handle the edge case).
    """
    if op != "==" or not isinstance(left, Message) or not isinstance(right, Message):
        return None

    if config is None:
        render_config = RenderConfig()  # direct-call default (no pytest config)
    else:
        try:
            render_config = _resolve_render_config(config)
        except Exception as exc:
            warnings.warn(
                f"protokit plugin config invalid ({type(exc).__name__}: {exc}); "
                "falling back to default assertion output",
                stacklevel=2,
            )
            return None

    if not render_config.enhanced:
        return None  # author opted out of the enhanced rendering

    differ = MessageDifferencer()
    try:
        result = differ.compare(left, right)
    except Exception as exc:
        warnings.warn(
            f"protokit plugin failed ({type(exc).__name__}: {exc}); "
            "falling back to default assertion output",
            stacklevel=2,
        )
        return None

    if not result.has_changes():
        return None  # let pytest handle it (shouldn't happen since == failed)

    left_type = left.DESCRIPTOR.full_name
    right_type = right.DESCRIPTOR.full_name
    if left_type == right_type:
        header = f"{left_type} != {right_type}"
    else:
        header = f"{left_type} != {right_type} (cross-schema)"

    return render_diff_lines(
        result, header, max_diff_lines=render_config.max_diff_lines
    )


# ---------------------------------------------------------------------------
# Configured-matcher fixture (the supported path for NON-default policies)
# ---------------------------------------------------------------------------
#
# KTD-9: non-default comparison policies (partial / set / ignore / presence /
# tolerance) are applied through the MATCHER, never through bare ``==``. The
# ``proto_matcher`` fixture yields a small factory over U7's matchers so a test
# author opts into a policy EXPLICITLY — the rich diff still flows through the
# same shared formatter the ``==`` hook uses (KTD-4).


class ProtoMatcherFactory:
    """Callable the ``proto_matcher`` fixture yields; wraps U7's matchers.

    Two ergonomic call shapes, dispatched by how many messages are passed:

    - **Fluent** (one message — the *expected* reference)::

          proto_matcher(expected).partially().assert_matches(actual)

      Returns a :class:`~protokit.message.matchers.ProtoMatcher` to chain
      policy knobs and terminate with ``.matches`` / ``.assert_matches``.

    - **Single-call** (two messages — *actual* then *expected*)::

          proto_matcher(actual, expected, partial=True)

      Runs :func:`~protokit.message.matchers.proto_match` immediately, raising
      ``AssertionError`` (with the rich diff) on mismatch. Accepts the same
      keyword policy knobs as ``proto_match``.

    Both shapes reuse U7's matcher facade verbatim — no comparison logic is
    reimplemented here (it is imported lazily to avoid a module-import cycle
    with ``matchers.py``, which depends on this module's ``render_diff_lines``).
    """

    def __call__(
        self,
        expected_or_actual: Message,
        expected: Message | None = None,
        *,
        partial: bool = False,
        as_set: SelectorSpec | Iterable[SelectorSpec] | None = None,
        ignore: SelectorSpec | Iterable[SelectorSpec] | None = None,
        presence: MessageFieldComparison | None = None,
        approx: Approx | None = None,
        margin: float | None = None,
        fraction: float | None = None,
    ) -> ProtoMatcher | None:
        """Build a fluent matcher or run a single-call match.

        Args:
            expected_or_actual: With no second message, the *expected*
                reference for the fluent form. With a second message, the
                *actual* message under test for the single-call form.
            expected: The *expected* reference for the single-call form;
                ``None`` selects the fluent form.
            partial: Single-call only — enable partial / sub-shape matching.
            as_set: Single-call only — repeated-field set selector(s).
            ignore: Single-call only — field selector(s) to ignore.
            presence: Single-call only — presence comparison mode.
            approx: Single-call only — explicit :class:`Approx` tolerance
                (global, or per-field via its selector). Mutually exclusive
                with the ``margin`` / ``fraction`` shorthand.
            margin: Single-call only — global absolute float tolerance.
            fraction: Single-call only — global relative float tolerance.

        Returns:
            A :class:`ProtoMatcher` for the fluent form (when ``expected`` is
            ``None``), or ``None`` after running the single-call match.

        Raises:
            AssertionError: (single-call form) if ``actual`` does not match
                ``expected`` under the policy.
            MatcherError: (single-call form) if the tolerance kwargs conflict.
        """
        # Lazy import breaks the matchers.py <-> pytest_plugin.py cycle.
        from protokit.message.matchers import expect_proto, proto_match

        if expected is None:
            # Fluent form: the single message is the expected reference. Policy
            # kwargs do not apply here — they are chained on the returned
            # matcher (.partially(), .ignoring(...), ...).
            return expect_proto(expected_or_actual)

        # Single-call form: (actual, expected, **policy).
        proto_match(
            expected_or_actual,
            expected,
            partial=partial,
            as_set=as_set,
            ignore=ignore,
            presence=presence,
            approx=approx,
            margin=margin,
            fraction=fraction,
        )
        return None


if _pytest is not None:

    @_pytest.fixture
    def proto_matcher() -> ProtoMatcherFactory:
        """Yield a configured-matcher factory (the supported non-default path).

        Per KTD-9, non-default comparison policies are applied through the
        matcher, not bare ``==``. This fixture hands a :class:`ProtoMatcherFactory`
        a test can call two ways::

            def test_partial(proto_matcher):
                proto_matcher(expected).partially().assert_matches(actual)

            def test_single_call(proto_matcher):
                proto_matcher(actual, expected, partial=True)

        Each call builds a fresh policy and a fresh ``MessageDifferencer`` under
        the hood (KTD-5), so parametrized tests don't share differ state.

        Returns:
            A :class:`ProtoMatcherFactory`.
        """
        return ProtoMatcherFactory()
