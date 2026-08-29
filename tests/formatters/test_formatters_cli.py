"""End-to-end CLI tests for the formatter wire-up.

Covers ``--format`` validation, ``--formatter-module`` pack
loading, the widened ``--quiet`` mutex, formatter exception
fail-fast, and the stdout-write guard.
"""

from __future__ import annotations

import itertools
import sys
import textwrap
import warnings
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn

import pytest
from click.testing import CliRunner, Result
from google.protobuf import descriptor_pb2, descriptor_pool, message_factory

from protokit._cli_utils import run_formatter_safely
from protokit.formatters import FormatterContext, clear_user_formatters
from protokit.message.cli import main as diff_main
from protokit.schema.cli import main as compat_main

if TYPE_CHECKING:
    from collections.abc import Callable


@pytest.fixture(autouse=True)
def _isolate_formatter_registry() -> None:
    """Wipe user formatters around every test.

    Built-ins survive (they're in the reservation set);
    user-supplied packs from ``--formatter-module`` get cleared
    so one test's load doesn't leak into another's lookup.
    """
    clear_user_formatters()
    yield
    clear_user_formatters()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_msg_class(pool: descriptor_pool.DescriptorPool) -> type:
    fdp = descriptor_pb2.FileDescriptorProto()
    fdp.name = "cli_test.proto"
    fdp.syntax = "proto3"
    msg = fdp.message_type.add()
    msg.name = "M"
    fld = msg.field.add()
    fld.name = "name"
    fld.number = 1
    fld.type = descriptor_pb2.FieldDescriptorProto.TYPE_STRING
    fld.label = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
    pool.Add(fdp)
    return message_factory.GetMessageClass(pool.FindMessageTypeByName("M"))


def _write_descriptor_set(path: Path, type_name: str, value: str = "x") -> None:
    """Build a single-message FileDescriptorSet, serialize, and write to disk."""
    fdp = descriptor_pb2.FileDescriptorProto()
    fdp.name = f"{path.stem}.proto"
    fdp.syntax = "proto3"
    msg = fdp.message_type.add()
    msg.name = type_name
    fld = msg.field.add()
    fld.name = "name"
    fld.number = 1
    fld.type = descriptor_pb2.FieldDescriptorProto.TYPE_STRING
    fld.label = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
    fds = descriptor_pb2.FileDescriptorSet()
    fds.file.append(fdp)
    path.write_bytes(fds.SerializeToString())


def _binary_message(pool: descriptor_pool.DescriptorPool, name: str) -> bytes:
    cls = _build_msg_class(pool)
    return cls(name=name).SerializeToString()


# ---------------------------------------------------------------------------
# protokit diff — --format and --formatter-module
# ---------------------------------------------------------------------------


class TestDiffFormatFlag:
    def test_default_format_is_human(self, tmp_path: Path) -> None:
        pool = descriptor_pool.DescriptorPool()
        cls = _build_msg_class(pool)
        left = tmp_path / "a.pb"
        right = tmp_path / "b.pb"
        left.write_bytes(cls(name="A").SerializeToString())
        right.write_bytes(cls(name="A").SerializeToString())
        desc = tmp_path / "schema.descriptor_set"
        _write_descriptor_set(desc, "M")
        result = CliRunner().invoke(diff_main, [
            str(left), str(right),
            "--desc", str(desc), "--message-type", "M",
        ])
        assert result.exit_code == 0
        assert "Messages are equal" in result.output

    def test_unknown_format_exits_2(self, tmp_path: Path) -> None:
        pool = descriptor_pool.DescriptorPool()
        cls = _build_msg_class(pool)
        left = tmp_path / "a.pb"
        right = tmp_path / "b.pb"
        left.write_bytes(cls(name="A").SerializeToString())
        right.write_bytes(cls(name="A").SerializeToString())
        desc = tmp_path / "schema.descriptor_set"
        _write_descriptor_set(desc, "M")
        result = CliRunner().invoke(diff_main, [
            str(left), str(right),
            "--desc", str(desc), "--message-type", "M",
            "--format", "nonsense",
        ])
        assert result.exit_code == 2
        assert "unknown formatter 'nonsense'" in result.output
        # Error names the available formatters for DIFF.
        assert "human" in result.output
        assert "json" in result.output
        assert "junit" in result.output

    def test_case_insensitive_format(self, tmp_path: Path) -> None:
        pool = descriptor_pool.DescriptorPool()
        cls = _build_msg_class(pool)
        left = tmp_path / "a.pb"
        right = tmp_path / "b.pb"
        left.write_bytes(cls(name="A").SerializeToString())
        right.write_bytes(cls(name="B").SerializeToString())
        desc = tmp_path / "schema.descriptor_set"
        _write_descriptor_set(desc, "M")
        result = CliRunner().invoke(diff_main, [
            str(left), str(right),
            "--desc", str(desc), "--message-type", "M",
            "--format", "JSON",  # uppercase
        ])
        assert result.exit_code == 1
        assert '"equal": false' in result.output

    def test_quiet_plus_junit_rejected(self, tmp_path: Path) -> None:
        pool = descriptor_pool.DescriptorPool()
        cls = _build_msg_class(pool)
        left = tmp_path / "a.pb"
        right = tmp_path / "b.pb"
        left.write_bytes(cls(name="A").SerializeToString())
        right.write_bytes(cls(name="A").SerializeToString())
        desc = tmp_path / "schema.descriptor_set"
        _write_descriptor_set(desc, "M")
        result = CliRunner().invoke(diff_main, [
            str(left), str(right),
            "--desc", str(desc), "--message-type", "M",
            "--quiet", "--format", "junit",
        ])
        assert result.exit_code == 2
        assert "--quiet" in result.output
        assert "junit" in result.output


# ---------------------------------------------------------------------------
# Formatter pack loading
# ---------------------------------------------------------------------------


_pack_counter = itertools.count(1)


def _write_pack(tmp_path: Path, body: str) -> str:
    """Write a small formatter-pack module under ``tmp_path`` and return its dotted name.

    Each call creates a fresh subdirectory and uses a unique
    module name so sys.modules caching doesn't conflate test
    runs. importlib's caches are invalidated so the new file
    is discoverable on the path. The test's autouse cleanup
    wipes the user-registered formatters afterwards; the on-
    disk module stays under ``tmp_path`` and is cleaned up by
    pytest.
    """
    import importlib
    seq = next(_pack_counter)
    pack_dir = tmp_path / f"pack_dir_{seq}"
    pack_dir.mkdir()
    name = f"protokit_test_pack_{seq}"
    (pack_dir / f"{name}.py").write_text(body)
    sys.path.insert(0, str(pack_dir))
    importlib.invalidate_caches()
    # Drop any stale cache entry from a prior test run.
    sys.modules.pop(name, None)
    return name


class TestFormatterModule:
    def test_loads_user_pack(self, tmp_path: Path) -> None:
        pack = _write_pack(tmp_path, textwrap.dedent("""
            from protokit.formatters import FormatterKind
            def my_format(report, ctx):
                return "USER-FORMATTER " + str(report.has_changes())
            FORMATTERS = [("my-format", my_format, FormatterKind.DIFF)]
        """))
        pool = descriptor_pool.DescriptorPool()
        cls = _build_msg_class(pool)
        left = tmp_path / "a.pb"
        right = tmp_path / "b.pb"
        left.write_bytes(cls(name="A").SerializeToString())
        right.write_bytes(cls(name="A").SerializeToString())
        desc = tmp_path / "schema.descriptor_set"
        _write_descriptor_set(desc, "M")
        result = CliRunner().invoke(diff_main, [
            str(left), str(right),
            "--desc", str(desc), "--message-type", "M",
            "--formatter-module", pack,
            "--format", "my-format",
        ])
        assert result.exit_code == 0
        assert "USER-FORMATTER False" in result.output

    def test_pack_cannot_shadow_built_in(self, tmp_path: Path) -> None:
        pack = _write_pack(tmp_path, textwrap.dedent("""
            from protokit.formatters import FormatterKind
            def fake(report, ctx):
                return "fake"
            FORMATTERS = [("junit", fake, FormatterKind.COMPAT)]
        """))
        old = tmp_path / "old.descriptor_set"
        new = tmp_path / "new.descriptor_set"
        _write_descriptor_set(old, "M")
        _write_descriptor_set(new, "M")
        result = CliRunner().invoke(compat_main, [
            "check", str(old), str(new), "--type", "M",
            "--formatter-module", pack,
        ])
        assert result.exit_code == 2
        # Distinct error prefix per the 2026-04-19 review (CR-02):
        # built-in shadowing is its own conceptual failure, not
        # a generic "failed to load" import problem.
        assert "conflicts with a reserved built-in name" in result.output
        assert "junit" in result.output

    def test_repeated_formatter_module_flag_is_idempotent(
        self, tmp_path: Path,
    ) -> None:
        # ``--formatter-module`` is ``multiple=True``; naming the same
        # pack twice (shell history, a wrapper script that appends the
        # flag unconditionally) must not hard-fail on the pack's own
        # second registration. Matches the lint side's ``--rule-pack``
        # early-return on an already-loaded module.
        pack = _write_pack(tmp_path, textwrap.dedent("""
            from protokit.formatters import FormatterKind
            def my_format(report, ctx):
                return "USER-FORMATTER " + str(report.has_changes())
            FORMATTERS = [("my-format", my_format, FormatterKind.DIFF)]
        """))
        pool = descriptor_pool.DescriptorPool()
        cls = _build_msg_class(pool)
        left = tmp_path / "a.pb"
        right = tmp_path / "b.pb"
        left.write_bytes(cls(name="A").SerializeToString())
        right.write_bytes(cls(name="A").SerializeToString())
        desc = tmp_path / "schema.descriptor_set"
        _write_descriptor_set(desc, "M")
        result = CliRunner().invoke(diff_main, [
            str(left), str(right),
            "--desc", str(desc), "--message-type", "M",
            "--formatter-module", pack,
            "--formatter-module", pack,
            "--format", "my-format",
        ])
        assert result.exit_code == 0
        assert "USER-FORMATTER False" in result.output

    def test_duplicate_name_across_packs_is_not_labelled_reserved(
        self, tmp_path: Path,
    ) -> None:
        # A collision between two user packs is a duplicate, not a
        # built-in shadow — it must not borrow the reserved-name
        # prefix that agents branch on.
        body = textwrap.dedent("""
            from protokit.formatters import FormatterKind
            def mine(report, ctx):
                return "mine"
            FORMATTERS = [("dup-format", mine, FormatterKind.DIFF)]
        """)
        first = _write_pack(tmp_path, body)
        second = _write_pack(tmp_path, body)
        pool = descriptor_pool.DescriptorPool()
        cls = _build_msg_class(pool)
        left = tmp_path / "a.pb"
        right = tmp_path / "b.pb"
        left.write_bytes(cls(name="A").SerializeToString())
        right.write_bytes(cls(name="A").SerializeToString())
        desc = tmp_path / "schema.descriptor_set"
        _write_descriptor_set(desc, "M")
        result = CliRunner().invoke(diff_main, [
            str(left), str(right),
            "--desc", str(desc), "--message-type", "M",
            "--formatter-module", first,
            "--formatter-module", second,
            "--format", "dup-format",
        ])
        assert result.exit_code == 2
        assert "conflicts with a reserved built-in name" not in result.output
        assert "failed to load formatter pack" in result.output
        assert "already registered" in result.output

    def test_pack_partial_load_rolls_back(self, tmp_path: Path) -> None:
        pack = _write_pack(tmp_path, textwrap.dedent("""
            from protokit.formatters import FormatterKind
            def good(report, ctx):
                return "good"
            # Last entry is malformed (2-tuple instead of 3-tuple).
            FORMATTERS = [
                ("good", good, FormatterKind.DIFF),
                ("bad-entry", good),
            ]
        """))
        pool = descriptor_pool.DescriptorPool()
        cls = _build_msg_class(pool)
        left = tmp_path / "a.pb"
        right = tmp_path / "b.pb"
        left.write_bytes(cls(name="A").SerializeToString())
        right.write_bytes(cls(name="A").SerializeToString())
        desc = tmp_path / "schema.descriptor_set"
        _write_descriptor_set(desc, "M")
        result = CliRunner().invoke(diff_main, [
            str(left), str(right),
            "--desc", str(desc), "--message-type", "M",
            "--formatter-module", pack,
        ])
        assert result.exit_code == 2
        assert "failed to load formatter pack" in result.output
        # Verify the "good" entry didn't land — try to use it
        # in a fresh invocation (no --formatter-module this time).
        result2 = CliRunner().invoke(diff_main, [
            str(left), str(right),
            "--desc", str(desc), "--message-type", "M",
            "--format", "good",
        ])
        assert result2.exit_code == 2
        assert "unknown formatter 'good'" in result2.output

    def test_missing_module_exits_2(self, tmp_path: Path) -> None:
        pool = descriptor_pool.DescriptorPool()
        cls = _build_msg_class(pool)
        left = tmp_path / "a.pb"
        right = tmp_path / "b.pb"
        left.write_bytes(cls(name="A").SerializeToString())
        right.write_bytes(cls(name="A").SerializeToString())
        desc = tmp_path / "schema.descriptor_set"
        _write_descriptor_set(desc, "M")
        result = CliRunner().invoke(diff_main, [
            str(left), str(right),
            "--desc", str(desc), "--message-type", "M",
            "--formatter-module", "no.such.module",
        ])
        assert result.exit_code == 2
        assert "failed to import formatter pack" in result.output

    @staticmethod
    def _invoke_diff_with_pack(
        tmp_path: Path, pack: str,
    ) -> Result:
        """Helper: build minimal diff inputs and invoke ``protokit diff``.

        All of the load-phase ``--formatter-module`` regression tests
        share the same fixture shape (two minimal proto messages, a
        descriptor set, a ``CliRunner`` invocation) — extract once
        rather than repeat per-test.
        """
        pool = descriptor_pool.DescriptorPool()
        cls = _build_msg_class(pool)
        left = tmp_path / "a.pb"
        right = tmp_path / "b.pb"
        left.write_bytes(cls(name="A").SerializeToString())
        right.write_bytes(cls(name="A").SerializeToString())
        desc = tmp_path / "schema.descriptor_set"
        _write_descriptor_set(desc, "M")
        return CliRunner().invoke(diff_main, [
            str(left), str(right),
            "--desc", str(desc), "--message-type", "M",
            "--formatter-module", pack,
        ])

    def test_pack_module_body_sys_exit_does_not_false_green(
        self, tmp_path: Path,
    ) -> None:
        # U5 sibling-parity hardening: a formatter pack whose module
        # body calls ``sys.exit(0)`` at import time used to raise
        # ``SystemExit`` past compat's broad ``except Exception``,
        # silently terminating the CLI with code 0 — false-greening
        # CI pipelines that depended on the diff's verdict. The
        # explicit ``except SystemExit`` guard now routes the same
        # failure through ``error_exit`` (exit 2, ``Error:`` prefix),
        # mirroring lint's ``_load_user_rule_pack`` pattern.
        pack = _write_pack(tmp_path, textwrap.dedent("""
            import sys
            sys.exit(0)
        """))
        result = self._invoke_diff_with_pack(tmp_path, pack)
        # Must NOT silently exit 0 — that's the regression we're
        # closing. Compat surfaces this through its legacy
        # ``Error:`` prefix (exit 2), distinct from lint's
        # ``error[lint-rule-pack-load]:`` code-prefix.
        assert result.exit_code == 2, result.output
        assert "Error:" in result.output
        assert "failed to import formatter pack" in result.output
        assert "called sys.exit" in result.output
        # The actual exit code argument propagates so operators can
        # see what value the pack tried to force.
        assert "sys.exit(0)" in result.output

    def test_pack_module_body_sys_exit_nonzero_also_caught(
        self, tmp_path: Path,
    ) -> None:
        # The guard catches every ``SystemExit``, regardless of code
        # value — a non-zero exit would have produced exit-2 even
        # without the fix (since ``sys.exit(2)`` would have happened
        # to match the CLI's error-path code), but the false-green
        # vulnerability was specifically about exit 0. We pin the
        # broader guard to prevent a future "narrow to exit==0"
        # regression.
        pack = _write_pack(tmp_path, textwrap.dedent("""
            import sys
            sys.exit("custom message")
        """))
        result = self._invoke_diff_with_pack(tmp_path, pack)
        assert result.exit_code == 2, result.output
        assert "called sys.exit('custom message')" in result.output

    def test_pack_module_body_keyboard_interrupt_does_not_bypass_guard(
        self, tmp_path: Path,
    ) -> None:
        # U5 ce:review follow-up: parity with U3's KeyboardInterrupt
        # guard on ``_load_user_rule_pack``. Without an explicit
        # ``except KeyboardInterrupt`` arm a pack body that raises
        # ``KeyboardInterrupt`` (legitimate Ctrl-C during import OR
        # an adversarial ``raise KeyboardInterrupt()`` to escape the
        # exit-2 contract) propagates past ``except Exception``
        # (KeyboardInterrupt is BaseException, not Exception) and
        # exits via Click's ``Aborted!`` banner at code 1 —
        # indistinguishable from a legitimate "diff found
        # incompatibilities" exit 1 by the CI grep contract.
        # Per the keyboardinterrupt-baseexception-bypass learning,
        # both SystemExit AND KeyboardInterrupt are required on
        # trust-delegation surfaces (anywhere user-supplied Python
        # is loaded and executed).
        pack = _write_pack(tmp_path, textwrap.dedent("""
            raise KeyboardInterrupt()
        """))
        result = self._invoke_diff_with_pack(tmp_path, pack)
        assert result.exit_code == 2, result.output
        assert "Error:" in result.output
        assert "failed to import formatter pack" in result.output
        assert "KeyboardInterrupt" in result.output

    def test_pack_name_with_embedded_newline_does_not_forge_stderr_lines(
        self, tmp_path: Path,
    ) -> None:
        # U5 ce:review follow-up: closes the module-name newline-
        # injection vector documented in
        # docs/solutions/security-issues/module-name-newline-injection-stderr-forge-2026-05-07.md
        # Bare f-string interpolation of the user-supplied
        # ``--formatter-module`` argument let a name like
        # ``no.such.module\nError: schema is compatible (forged)``
        # forge a second physical line beginning with ``Error:``
        # on stderr, fooling CI parsers that key on the prefix.
        # The fix uses ``{name!r}`` (Python's repr escaping) which
        # converts embedded newlines to the literal escape sequence
        # ``\\n`` rather than passing the raw byte through to
        # ``click.echo``. The lint sibling closes the same vector
        # via ``_safe_module_name``.
        forged = "no.such.module\nError: schema is compatible (forged)"
        result = self._invoke_diff_with_pack(tmp_path, forged)
        assert result.exit_code == 2
        # Exactly one line on stderr begins with ``Error:`` — the
        # legitimate one. The forged continuation line must NOT
        # appear as its own line.
        error_lines = [
            line for line in result.output.splitlines()
            if line.startswith("Error:")
        ]
        assert len(error_lines) == 1, (
            f"newline injection: expected one Error: line, got "
            f"{len(error_lines)}: {error_lines!r}"
        )
        # Repr's escape sequence appears in the (single) error line —
        # proving the scrub took effect — and the forged content is
        # NOT a standalone line.
        assert "\\n" in result.output
        assert "schema is compatible (forged)" not in result.output.splitlines()

    # -- Deferred-FORMATTERS-evaluation guard -------------------------------
    #
    # The import-phase guard chain above only wraps
    # ``importlib.import_module``. ``load_formatter_pack`` is a separate
    # statement, and it evaluates ``module.FORMATTERS`` (``list(...)``,
    # i.e. ``__iter__``) AFTER import returns — so a pack can defer its
    # payload into an iterator and reach a guard chain that used to catch
    # only ``FormatterError`` / ``(AttributeError, TypeError)``. That is
    # the same trust boundary (user-supplied Python executing during
    # pack load) the formatter-systemexit-exit-code-bypass and
    # keyboardinterrupt-baseexception-bypass-rule-pack-load learnings
    # cover, one level deferred.

    def test_pack_formatters_iter_sys_exit_does_not_false_green(
        self, tmp_path: Path,
    ) -> None:
        # A ``FORMATTERS`` object whose ``__iter__`` calls
        # ``sys.exit(0)`` used to terminate the CLI with code 0 and no
        # error output — the exact false-green CI bypass the
        # module-body ``except SystemExit`` arm closes, smuggled past
        # it by deferring the call to iteration time.
        pack = _write_pack(tmp_path, textwrap.dedent("""
            import sys
            class _Deferred:
                def __iter__(self):
                    sys.exit(0)
            FORMATTERS = _Deferred()
        """))
        result = self._invoke_diff_with_pack(tmp_path, pack)
        assert result.exit_code == 2, result.output
        assert "Error:" in result.output
        assert "failed to load formatter pack" in result.output
        assert "called sys.exit(0)" in result.output

    def test_pack_formatters_iter_keyboard_interrupt_does_not_bypass_guard(
        self, tmp_path: Path,
    ) -> None:
        # Sibling arm: ``KeyboardInterrupt`` from the deferred
        # evaluation used to escape past ``except (AttributeError,
        # TypeError)`` and exit via Click's ``Aborted!`` banner at code
        # 1 — indistinguishable from a legitimate "diff found
        # incompatibilities" verdict by the CI grep contract.
        pack = _write_pack(tmp_path, textwrap.dedent("""
            class _Deferred:
                def __iter__(self):
                    raise KeyboardInterrupt()
            FORMATTERS = _Deferred()
        """))
        result = self._invoke_diff_with_pack(tmp_path, pack)
        assert result.exit_code == 2, result.output
        assert "Error:" in result.output
        assert "failed to load formatter pack" in result.output
        assert "KeyboardInterrupt" in result.output

    def test_pack_formatters_iter_runtime_error_exits_2(
        self, tmp_path: Path,
    ) -> None:
        # Non-adversarial variant: a plain ``RuntimeError`` raised
        # during deferred evaluation is neither ``AttributeError`` nor
        # ``TypeError``, so it used to escape the load guard entirely
        # and crash the CLI with a raw traceback instead of the
        # documented exit-2 + ``Error:`` one-liner.
        pack = _write_pack(tmp_path, textwrap.dedent("""
            class _Deferred:
                def __iter__(self):
                    raise RuntimeError("deferred boom")
            FORMATTERS = _Deferred()
        """))
        result = self._invoke_diff_with_pack(tmp_path, pack)
        assert result.exit_code == 2, result.output
        assert result.exception is None or isinstance(
            result.exception, SystemExit,
        ), result.exception
        assert "failed to load formatter pack" in result.output
        assert "deferred boom" in result.output

    def test_empty_formatters_under_strict_warnings_exits_2(
        self, tmp_path: Path,
    ) -> None:
        # Third, entirely non-adversarial manifestation: the registry
        # warns (``UserWarning``) on an empty ``FORMATTERS`` list. Under
        # ``PYTHONWARNINGS=error`` (common in strict CI) that warning is
        # raised as an exception from inside ``load_formatter_pack`` and
        # used to escape the narrow ``(AttributeError, TypeError)``
        # catch, crashing the CLI with a traceback.
        pack = _write_pack(tmp_path, textwrap.dedent("""
            FORMATTERS = []
        """))
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            result = self._invoke_diff_with_pack(tmp_path, pack)
        assert result.exit_code == 2, result.output
        assert "failed to load formatter pack" in result.output


# ---------------------------------------------------------------------------
# Formatter exception & stdout-write guard
# ---------------------------------------------------------------------------


class TestFormatterFailFast:
    def test_formatter_exception_exits_2(self, tmp_path: Path) -> None:
        pack = _write_pack(tmp_path, textwrap.dedent("""
            from protokit.formatters import FormatterKind
            def crashy(report, ctx):
                raise RuntimeError("intentional crash")
            FORMATTERS = [("crashy", crashy, FormatterKind.DIFF)]
        """))
        pool = descriptor_pool.DescriptorPool()
        cls = _build_msg_class(pool)
        left = tmp_path / "a.pb"
        right = tmp_path / "b.pb"
        left.write_bytes(cls(name="A").SerializeToString())
        right.write_bytes(cls(name="B").SerializeToString())
        desc = tmp_path / "schema.descriptor_set"
        _write_descriptor_set(desc, "M")
        result = CliRunner().invoke(diff_main, [
            str(left), str(right),
            "--desc", str(desc), "--message-type", "M",
            "--formatter-module", pack,
            "--format", "crashy",
        ])
        assert result.exit_code == 2
        assert "formatter 'crashy' raised RuntimeError" in result.output
        assert "intentional crash" in result.output

    def test_systemexit_in_formatter_does_not_flip_exit_code(
        self, tmp_path: Path,
    ) -> None:
        # Regression test for the 2026-04-19 adversarial review's
        # P0: a formatter calling sys.exit(0) used to escape the
        # except-Exception handler (SystemExit is a BaseException),
        # flipping the CI exit code from 1 (incompatible) to 0
        # (compatible). The fix catches SystemExit explicitly and
        # routes through error_exit so exit code stays the
        # report's verdict.
        pack = _write_pack(tmp_path, textwrap.dedent("""
            import sys
            from protokit.formatters import FormatterKind
            def evil(report, ctx):
                sys.exit(0)
            FORMATTERS = [("evil", evil, FormatterKind.DIFF)]
        """))
        pool = descriptor_pool.DescriptorPool()
        cls = _build_msg_class(pool)
        left = tmp_path / "a.pb"
        right = tmp_path / "b.pb"
        left.write_bytes(cls(name="A").SerializeToString())
        right.write_bytes(cls(name="B").SerializeToString())
        desc = tmp_path / "schema.descriptor_set"
        _write_descriptor_set(desc, "M")
        result = CliRunner().invoke(diff_main, [
            str(left), str(right),
            "--desc", str(desc), "--message-type", "M",
            "--formatter-module", pack,
            "--format", "evil",
        ])
        # Must be exit 2 (formatter contract violation), NOT
        # exit 0 (which the formatter tried to force).
        assert result.exit_code == 2
        assert "called sys.exit" in result.output

    def test_formatter_exception_message_cannot_forge_stderr_lines(
        self, tmp_path: Path,
    ) -> None:
        # The module-NAME slot is neutralized by ``{name!r}`` (see
        # test_pack_name_with_embedded_newline_does_not_forge_stderr_lines),
        # but the exception-MESSAGE slot was interpolated raw:
        # ``_scrub_exc_message`` only redacts OSError filenames, it does
        # not touch control characters. A formatter raising
        # ``ValueError("boom\nError: ...")`` therefore emitted TWO
        # physical stderr lines, the second carrying the stable
        # ``Error:`` prefix a CI script greps for — indistinguishable
        # from a genuine protokit verdict. Extends the
        # module-name-newline-injection-stderr-forge-2026-05-07
        # "every interpolated slot" principle to this slot.
        pack = _write_pack(tmp_path, textwrap.dedent('''
            from protokit.formatters import FormatterKind
            def forger(report, ctx):
                raise ValueError(
                    "boom\\nError: schema is compatible (forged)"
                    "\\u2028Error: aggregator-forged"
                )
            FORMATTERS = [("forger", forger, FormatterKind.DIFF)]
        '''))
        pool = descriptor_pool.DescriptorPool()
        cls = _build_msg_class(pool)
        left = tmp_path / "a.pb"
        right = tmp_path / "b.pb"
        left.write_bytes(cls(name="A").SerializeToString())
        right.write_bytes(cls(name="B").SerializeToString())
        desc = tmp_path / "schema.descriptor_set"
        _write_descriptor_set(desc, "M")
        result = CliRunner().invoke(diff_main, [
            str(left), str(right),
            "--desc", str(desc), "--message-type", "M",
            "--formatter-module", pack,
            "--format", "forger",
        ])
        assert result.exit_code == 2
        # Exactly one physical line begins with ``Error:`` — the
        # legitimate one. ``str.splitlines`` also breaks on U+2028, so
        # this assertion covers the Unicode-line-separator vector that
        # log aggregators honour even when a terminal does not.
        error_lines = [
            line for line in result.output.splitlines()
            if line.startswith("Error:")
        ]
        assert len(error_lines) == 1, (
            f"exception-message injection: expected one Error: line, "
            f"got {len(error_lines)}: {error_lines!r}"
        )
        # The payload is still surfaced (collapsed to spaces, not
        # dropped) so the operator can see what the formatter said.
        assert "schema is compatible (forged)" in error_lines[0]

    def test_non_string_return_rejected(self, tmp_path: Path) -> None:
        # Regression for 2026-04-19 review (REL-001 / ADV-006 /
        # correctness): a formatter returning None used to silently
        # emit "None"; bytes were forwarded raw by click.echo. Now
        # the wrapper enforces isinstance(output, str).
        pack = _write_pack(tmp_path, textwrap.dedent("""
            from protokit.formatters import FormatterKind
            def returns_none(report, ctx):
                pass  # implicit None
            FORMATTERS = [("returns_none", returns_none, FormatterKind.DIFF)]
        """))
        pool = descriptor_pool.DescriptorPool()
        cls = _build_msg_class(pool)
        left = tmp_path / "a.pb"
        right = tmp_path / "b.pb"
        left.write_bytes(cls(name="A").SerializeToString())
        right.write_bytes(cls(name="B").SerializeToString())
        desc = tmp_path / "schema.descriptor_set"
        _write_descriptor_set(desc, "M")
        result = CliRunner().invoke(diff_main, [
            str(left), str(right),
            "--desc", str(desc), "--message-type", "M",
            "--formatter-module", pack,
            "--format", "returns_none",
        ])
        assert result.exit_code == 2
        assert "returned NoneType" in result.output
        assert "expected str" in result.output

    def test_stdout_write_guard(self, tmp_path: Path) -> None:
        pack = _write_pack(tmp_path, textwrap.dedent("""
            import sys
            from protokit.formatters import FormatterKind
            def leaky(report, ctx):
                sys.stdout.write("LEAKED STDOUT BYTES")
                return "returned-value"
            FORMATTERS = [("leaky", leaky, FormatterKind.DIFF)]
        """))
        pool = descriptor_pool.DescriptorPool()
        cls = _build_msg_class(pool)
        left = tmp_path / "a.pb"
        right = tmp_path / "b.pb"
        left.write_bytes(cls(name="A").SerializeToString())
        right.write_bytes(cls(name="A").SerializeToString())
        desc = tmp_path / "schema.descriptor_set"
        _write_descriptor_set(desc, "M")
        result = CliRunner().invoke(diff_main, [
            str(left), str(right),
            "--desc", str(desc), "--message-type", "M",
            "--formatter-module", pack,
            "--format", "leaky",
        ])
        assert result.exit_code == 2
        assert "wrote to sys.stdout directly" in result.output


# ---------------------------------------------------------------------------
# protokit compat — formatter dispatch on every subcommand
# ---------------------------------------------------------------------------


class TestCompatFormatDispatch:
    def test_check_unknown_format(self, tmp_path: Path) -> None:
        old = tmp_path / "old.descriptor_set"
        new = tmp_path / "new.descriptor_set"
        _write_descriptor_set(old, "M")
        _write_descriptor_set(new, "M")
        result = CliRunner().invoke(compat_main, [
            "check", str(old), str(new), "--type", "M",
            "--format", "nonsense",
        ])
        assert result.exit_code == 2
        assert "unknown formatter 'nonsense'" in result.output
        assert "COMPAT" in result.output  # kind is in error
        assert "junit" in result.output
        assert "sarif" in result.output

    def test_check_junit_succeeds(self, tmp_path: Path) -> None:
        old = tmp_path / "old.descriptor_set"
        new = tmp_path / "new.descriptor_set"
        _write_descriptor_set(old, "M")
        _write_descriptor_set(new, "M")
        result = CliRunner().invoke(compat_main, [
            "check", str(old), str(new), "--type", "M",
            "--format", "junit",
        ])
        assert result.exit_code == 0
        assert '<?xml' in result.output
        assert '<testsuite' in result.output

    def test_check_sarif_succeeds(self, tmp_path: Path) -> None:
        old = tmp_path / "old.descriptor_set"
        new = tmp_path / "new.descriptor_set"
        _write_descriptor_set(old, "M")
        _write_descriptor_set(new, "M")
        result = CliRunner().invoke(compat_main, [
            "check", str(old), str(new), "--type", "M",
            "--format", "sarif",
        ])
        assert result.exit_code == 0
        assert '"version": "2.1.0"' in result.output
        assert '"protokit"' in result.output

    def test_diff_sarif_unknown_for_diff_kind(self, tmp_path: Path) -> None:
        # SARIF intentionally not registered for DIFF — error
        # message reflects that.
        pool = descriptor_pool.DescriptorPool()
        cls = _build_msg_class(pool)
        left = tmp_path / "a.pb"
        right = tmp_path / "b.pb"
        left.write_bytes(cls(name="A").SerializeToString())
        right.write_bytes(cls(name="A").SerializeToString())
        desc = tmp_path / "schema.descriptor_set"
        _write_descriptor_set(desc, "M")
        result = CliRunner().invoke(diff_main, [
            str(left), str(right),
            "--desc", str(desc), "--message-type", "M",
            "--format", "sarif",
        ])
        assert result.exit_code == 2
        assert "unknown formatter 'sarif'" in result.output
        assert "DIFF" in result.output


class TestRunFormatterSafelyErrorExitFn:
    """Direct unit tests for the U4a additive ``error_exit_fn`` kwarg.

    The shared body's four guards (SystemExit, generic Exception,
    stdout-leak, non-str return) all route through ``error_exit_fn``
    when set; default preserves the legacy ``error_exit`` prefix
    used by compat callsites.
    """

    def _make_ctx(self) -> FormatterContext:
        return FormatterContext(subcommand="diff")

    def _record_calls(self) -> tuple[list[str], Callable[[str], NoReturn]]:
        calls: list[str] = []

        def custom(msg: str) -> NoReturn:
            calls.append(msg)
            raise SystemExit(99)

        return calls, custom

    def test_default_uses_error_exit_when_kwarg_omitted(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        def boom(report: object, ctx: object) -> str:
            raise RuntimeError("raised RuntimeError")

        with pytest.raises(SystemExit) as exc_info:
            run_formatter_safely(boom, object(), self._make_ctx(), name="boom")
        assert exc_info.value.code == 2
        captured = capsys.readouterr()
        assert captured.err.startswith("Error: ")
        assert "raised RuntimeError" in captured.err

    def test_custom_error_exit_fn_replaces_default_on_exception(
        self,
    ) -> None:
        calls, custom = self._record_calls()

        def boom(report: object, ctx: object) -> str:
            raise RuntimeError("boom")

        with pytest.raises(SystemExit) as exc_info:
            run_formatter_safely(
                boom, object(), self._make_ctx(),
                name="boom", error_exit_fn=custom,
            )
        assert exc_info.value.code == 99
        assert len(calls) == 1
        assert "raised RuntimeError" in calls[0]

    def test_custom_error_exit_fn_replaces_default_on_systemexit(
        self,
    ) -> None:
        calls, custom = self._record_calls()

        def evil(report: object, ctx: object) -> str:
            sys.exit(0)

        with pytest.raises(SystemExit) as exc_info:
            run_formatter_safely(
                evil, object(), self._make_ctx(),
                name="evil", error_exit_fn=custom,
            )
        assert exc_info.value.code == 99
        assert "called sys.exit" in calls[0]

    def test_custom_error_exit_fn_replaces_default_on_stdout_leak(
        self,
    ) -> None:
        calls, custom = self._record_calls()

        def leaky(report: object, ctx: object) -> str:
            sys.stdout.write("leaked")
            return "ok"

        with pytest.raises(SystemExit) as exc_info:
            run_formatter_safely(
                leaky, object(), self._make_ctx(),
                name="leaky", error_exit_fn=custom,
            )
        assert exc_info.value.code == 99
        assert "wrote to sys.stdout directly" in calls[0]

    def test_custom_error_exit_fn_replaces_default_on_non_str_return(
        self,
    ) -> None:
        calls, custom = self._record_calls()

        def bad(report: object, ctx: object) -> str:
            return 42  # type: ignore[return-value]

        with pytest.raises(SystemExit) as exc_info:
            run_formatter_safely(
                bad, object(), self._make_ctx(),
                name="bad", error_exit_fn=custom,
            )
        assert exc_info.value.code == 99
        assert "returned int" in calls[0]
