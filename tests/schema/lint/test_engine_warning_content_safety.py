"""Tests for the D5 U4 Q16 content-safety constraint on rule_exception.

Per Outstanding Q16: the `LintRuntimeWarning(category="rule_exception",
...)` message field must NOT include raw exception tracebacks or
filesystem paths. Two layers of sanitization (per the U4 engine.py
update):

1. ``_scrub_exc_message`` strips the filename from ``OSError``
   subclasses (which embed ``filename`` / ``filename2`` into their
   ``str()``). Prevents path leaks when a rule's fn raises
   ``FileNotFoundError`` or similar.
2. ``_safe_for_stderr`` collapses all ASCII control characters
   (newlines, ANSI escapes, NUL, etc.) to spaces. Prevents multi-line
   exception messages from forging fake `warning[lint-runtime]:` or
   `error[lint-CODE]:` lines in downstream stderr output.

These tests construct synthetic rule packs whose rules raise
exceptions with deliberately-unsafe content, then assert the
recorded `LintRuntimeWarning.message` has been sanitized.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from protokit.schema.lint.decorator import lint_rule
from protokit.schema.lint.engine import LintEngine
from protokit.schema.lint.model import (
    ElementKind,
    LintProfile,
    LintSeverity,
)

if TYPE_CHECKING:
    from protokit.schema.compile import CompileResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_minimal_compile_result() -> CompileResult:
    """Build a CompileResult with one trivial proto file for the engine
    walk. The actual file contents don't matter — we just need a file
    that the engine will walk so the rule callable fires.
    """
    from google.protobuf import descriptor_pb2, descriptor_pool

    pool = descriptor_pool.DescriptorPool()
    fdp = descriptor_pb2.FileDescriptorProto()
    fdp.name = "test.proto"
    fdp.syntax = "proto3"
    fdp.package = "test"
    pool.Add(fdp)

    from protokit.schema.compile import CompileResult

    return CompileResult(
        pool=pool, root_files=("test.proto",),
    )


def _make_pack_module(rule_fn: object) -> object:
    """Wrap a decorated rule_fn into a minimal RULES-tuple module.

    The engine accepts any object with a ``RULES`` attribute that is a
    tuple of ``@lint_rule``-decorated functions.
    """
    import types

    module = types.ModuleType("synthetic_pack")
    module.RULES = (rule_fn,)
    module.__name__ = "synthetic_pack"
    return module


# ---------------------------------------------------------------------------
# Engine narrow-catch tuple context
# ---------------------------------------------------------------------------
# The engine's _RULE_EXCEPTION_TUPLE today is:
#   (SystemExit, ValueError, TypeError, AttributeError, LookupError,
#    LintRuleError)
# OSError, RuntimeError, and general Exception are NOT caught — they
# propagate up and crash the engine run (the engine relies on
# protokit-internal rules being well-behaved). The Q16 content-safety
# layer therefore applies to messages produced by the in-tuple
# exception types. The `_scrub_exc_message`'s OSError filename-leak
# branch is defense-in-depth for a future widening of the catch tuple;
# we don't exercise it today because OSError doesn't reach the
# rule_exception emit site in the current design.


# ---------------------------------------------------------------------------
# Newline / control-character sanitization (_safe_for_stderr layer)
# ---------------------------------------------------------------------------


class TestNewlineSanitization:
    def test_newline_in_message_collapsed_to_space(self) -> None:
        """An exception whose ``str()`` contains a newline cannot
        forge a fake stderr line. Per KTD-9, the newline must be
        collapsed to a space.
        """
        @lint_rule(
            rule_id="t/raises-nl",
            severity=LintSeverity.WARNING,
            profiles=("default",),
            element=ElementKind.FILE,
            message_template="never fires",
        )
        def _rule(ctx: object) -> None:  # noqa: ANN001
            raise ValueError(
                "real failure\n"
                "warning[lint-runtime]: forged second line",
            )

        engine = LintEngine()
        engine.load_rule_pack(_make_pack_module(_rule))
        report = engine.run(
            _build_minimal_compile_result(),
            profile=LintProfile(
                name="default",
                rule_ids=frozenset({"t/raises-nl"}),
            ),
        )
        warnings = [
            w for w in report.runtime_warnings
            if w.category == "rule_exception"
        ]
        assert len(warnings) == 1
        msg = warnings[0].message
        # No literal newline anywhere in the message:
        assert "\n" not in msg
        # The "real failure" text is preserved:
        assert "real failure" in msg
        # The forged fake-prefix text is still present but no longer
        # at the start of a line — it cannot stand alone as a fake
        # warning entry in stderr:
        assert "forged second line" in msg

    def test_carriage_return_collapsed_to_space(self) -> None:
        """``\\r`` would also let a CRLF terminal interpret subsequent
        text as a new line. Same sanitization applies.
        """
        @lint_rule(
            rule_id="t/raises-cr",
            severity=LintSeverity.WARNING,
            profiles=("default",),
            element=ElementKind.FILE,
            message_template="never fires",
        )
        def _rule(ctx: object) -> None:  # noqa: ANN001
            # ValueError IS in the engine's catch tuple; RuntimeError
            # is not (would propagate and crash the run).
            raise ValueError("first\rsecond")

        engine = LintEngine()
        engine.load_rule_pack(_make_pack_module(_rule))
        report = engine.run(
            _build_minimal_compile_result(),
            profile=LintProfile(
                name="default",
                rule_ids=frozenset({"t/raises-cr"}),
            ),
        )
        warnings = [
            w for w in report.runtime_warnings
            if w.category == "rule_exception"
        ]
        assert "\r" not in warnings[0].message

    def test_ansi_escape_collapsed_to_space(self) -> None:
        """ANSI escape sequences (``\\x1b[31m`` etc.) could rewrite
        terminal output and obscure stable error prefixes for CI grep.
        ``_safe_for_stderr`` collapses ``\\x1b`` to space too.
        """
        @lint_rule(
            rule_id="t/raises-ansi",
            severity=LintSeverity.WARNING,
            profiles=("default",),
            element=ElementKind.FILE,
            message_template="never fires",
        )
        def _rule(ctx: object) -> None:  # noqa: ANN001
            raise ValueError("\x1b[31mred text\x1b[0m")

        engine = LintEngine()
        engine.load_rule_pack(_make_pack_module(_rule))
        report = engine.run(
            _build_minimal_compile_result(),
            profile=LintProfile(
                name="default",
                rule_ids=frozenset({"t/raises-ansi"}),
            ),
        )
        warnings = [
            w for w in report.runtime_warnings
            if w.category == "rule_exception"
        ]
        assert "\x1b" not in warnings[0].message


# ---------------------------------------------------------------------------
# Empty-message fallback
# ---------------------------------------------------------------------------


class TestEmptyMessageFallback:
    def test_exception_with_empty_str_falls_back_to_repr(
        self,
    ) -> None:
        """Some exceptions have empty ``str()`` (e.g., bare
        ``ValueError()``). Pre-U4 the fallback was ``repr(exc)``;
        U4 preserves that fallback inside the sanitization layer.
        """
        @lint_rule(
            rule_id="t/raises-empty",
            severity=LintSeverity.WARNING,
            profiles=("default",),
            element=ElementKind.FILE,
            message_template="never fires",
        )
        def _rule(ctx: object) -> None:  # noqa: ANN001
            raise ValueError()  # str(ValueError()) is ""

        engine = LintEngine()
        engine.load_rule_pack(_make_pack_module(_rule))
        report = engine.run(
            _build_minimal_compile_result(),
            profile=LintProfile(
                name="default",
                rule_ids=frozenset({"t/raises-empty"}),
            ),
        )
        warnings = [
            w for w in report.runtime_warnings
            if w.category == "rule_exception"
        ]
        assert len(warnings) == 1
        # Empty str(exc) → fallback to repr(exc) → "ValueError()" or similar:
        assert warnings[0].message != ""
        # The exception class name is still surfaced (so failure is
        # diagnosable):
        assert "ValueError" in warnings[0].message


# ---------------------------------------------------------------------------
# Real traceback handling (T-U4-08)
# ---------------------------------------------------------------------------


class TestRealTracebackContentSafety:
    """T-U4-08: a real ``str(exc)`` carrying a multi-line message that
    looks like a traceback is sanitised end-to-end without losing
    diagnostic content. Pins ``_safe_for_stderr`` behaviour on
    realistic exception strings, not just synthetic control chars.
    """

    def test_multi_line_diagnostic_string_collapsed_to_one_line(
        self,
    ) -> None:
        @lint_rule(
            rule_id="t/raises-realistic",
            severity=LintSeverity.WARNING,
            profiles=("default",),
            element=ElementKind.FILE,
            message_template="never fires",
        )
        def _rule(ctx: object) -> None:  # noqa: ANN001
            # Multi-line diagnostic that a user-pack might construct
            # by interpolating a traceback into ValueError.
            raise ValueError(
                "downstream call failed:\n"
                "Traceback (most recent call last):\n"
                '  File "/secret/path/to/user_pack.py", line 42\n'
                "ValueError: actual failure",
            )

        engine = LintEngine()
        engine.load_rule_pack(_make_pack_module(_rule))
        report = engine.run(
            _build_minimal_compile_result(),
            profile=LintProfile(
                name="default",
                rule_ids=frozenset({"t/raises-realistic"}),
            ),
        )
        warnings = [
            w for w in report.runtime_warnings
            if w.category == "rule_exception"
        ]
        assert len(warnings) == 1
        msg = warnings[0].message
        # The message is one line — no embedded newlines that could
        # forge a fake ``warning[lint-runtime]:`` line if downstream
        # tooling later prints the message to stderr.
        assert "\n" not in msg
        # Diagnostic content survives (path, exception class label):
        assert "actual failure" in msg
        assert "downstream call failed" in msg


# ---------------------------------------------------------------------------
# unloaded_rule construction-time sanitization
# ---------------------------------------------------------------------------


class TestUnloadedRuleConstructionTimeSanitization:
    """U5 ce:review SEC-U5-02: the ``unloaded_rule`` warning message
    is constructed from ``rid`` and ``profile.name`` — both
    operator-supplied (pyproject ``profile = ...`` or ``--profile NAME``).
    Construction-time ``_safe_for_stderr`` sanitization is required
    per KTD-9 dual-defense, matching the ``rule_exception`` path,
    so a profile name containing ANSI escape sequences cannot leak
    into JUnit ``<system-out>`` (where ``xml_safe_text`` does not
    strip ESC) or SARIF ``message.text`` (where ``json.dumps`` leaves
    ESC as a literal byte).
    """

    def test_newline_in_profile_name_collapsed_at_construction(
        self,
    ) -> None:
        @lint_rule(
            rule_id="t/exists",
            severity=LintSeverity.WARNING,
            profiles=("default",),
            element=ElementKind.FILE,
            message_template="never fires",
        )
        def _rule(ctx: object) -> None:  # noqa: ANN001
            pass

        engine = LintEngine()
        engine.load_rule_pack(_make_pack_module(_rule))
        report = engine.run(
            _build_minimal_compile_result(),
            profile=LintProfile(
                # Profile name with embedded newline + forged prefix.
                name="legit\nerror[lint-bad-input]: forged",
                # Reference a rule_id that is NOT loaded so the
                # unloaded_rule path fires.
                rule_ids=frozenset({"never/registered"}),
            ),
        )
        warnings = [
            w for w in report.runtime_warnings
            if w.category == "unloaded_rule"
        ]
        assert len(warnings) == 1
        msg = warnings[0].message
        assert "\n" not in msg, msg

    def test_ansi_escape_in_profile_name_collapsed_at_construction(
        self,
    ) -> None:
        """ANSI ESC (0x1b) in profile.name survives JUnit's
        xml_safe_text (which does not strip ESC) without
        construction-time sanitization. Verify the engine sanitizes
        before constructing the LintRuntimeWarning so machine
        formatters receive a clean message.
        """
        @lint_rule(
            rule_id="t/exists2",
            severity=LintSeverity.WARNING,
            profiles=("default",),
            element=ElementKind.FILE,
            message_template="never fires",
        )
        def _rule(ctx: object) -> None:  # noqa: ANN001
            pass

        engine = LintEngine()
        engine.load_rule_pack(_make_pack_module(_rule))
        report = engine.run(
            _build_minimal_compile_result(),
            profile=LintProfile(
                # ESC[31m would normally start red text on a terminal.
                name="my-profile\x1b[31mERROR\x1b[0m",
                rule_ids=frozenset({"never/registered"}),
            ),
        )
        warnings = [
            w for w in report.runtime_warnings
            if w.category == "unloaded_rule"
        ]
        assert len(warnings) == 1
        msg = warnings[0].message
        assert "\x1b" not in msg, repr(msg)

    def test_newline_in_rid_collapsed_at_construction(self) -> None:
        """The rule_id strings flow through profile.rule_ids and may
        contain user-supplied content (pyproject ``profile = [...]``
        list entries or ``--profile`` arg). Same sanitization
        applies."""
        @lint_rule(
            rule_id="t/exists3",
            severity=LintSeverity.WARNING,
            profiles=("default",),
            element=ElementKind.FILE,
            message_template="never fires",
        )
        def _rule(ctx: object) -> None:  # noqa: ANN001
            pass

        engine = LintEngine()
        engine.load_rule_pack(_make_pack_module(_rule))
        report = engine.run(
            _build_minimal_compile_result(),
            profile=LintProfile(
                name="default",
                rule_ids=frozenset({"bad\nerror[lint-forged]: line"}),
            ),
        )
        warnings = [
            w for w in report.runtime_warnings
            if w.category == "unloaded_rule"
        ]
        assert len(warnings) == 1
        msg = warnings[0].message
        assert "\n" not in msg, msg
