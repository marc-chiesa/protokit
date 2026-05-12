"""Tests for ``load_pyproject_config`` and ``_parse_toml_bytes`` (D5 U1).

Covers:

- ``no_config=True`` bypass.
- Walk-up discovery (silent fallback on missing table).
- Explicit-path mode (R5a strict shadow paths).
- ``tomllib.TOMLDecodeError`` content-safety: error messages echo only
  ``path:line:col``, never raw file bytes (R5a).
- ``SystemExit`` from a malicious config body → ``pyproject-config-load``
  exit 2 (triple-arm guard per KTD-9).
- ``KeyboardInterrupt`` propagation (catch-and-reraise per KTD-9 +
  scope-guardian F5).
- Stderr newline sanitization for paths with embedded ``\\n``/``\\r``
  (KTD-9).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from protokit.schema.lint._config import (
    _extract_lint_table,
    _parse_toml_bytes,
    _safe_for_stderr,
    load_pyproject_config,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_pyproject(directory: Path, contents: str) -> Path:
    path = directory / "pyproject.toml"
    path.write_text(contents)
    return path


# ---------------------------------------------------------------------------
# Bypass: --no-config
# ---------------------------------------------------------------------------


class TestNoConfigBypass:
    def test_no_config_returns_none_regardless_of_cwd(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``no_config=True`` short-circuits before walk-up runs."""
        _write_pyproject(tmp_path, "[tool.protokit.lint]\nprofile = 'strict'\n")
        (tmp_path / ".git").mkdir()
        monkeypatch.chdir(tmp_path)

        result = load_pyproject_config(explicit_path=None, no_config=True)

        assert result is None

    def test_no_config_bypasses_explicit_path(self, tmp_path: Path) -> None:
        """When ``no_config=True``, ``explicit_path`` is ignored.

        Note: per R13a-precedence, the CLI rejects the combination at
        Click-parse time. ``load_pyproject_config`` itself prioritizes
        ``no_config`` for defense-in-depth.
        """
        path = _write_pyproject(tmp_path, "[tool.protokit.lint]\n")

        result = load_pyproject_config(explicit_path=path, no_config=True)

        assert result is None


# ---------------------------------------------------------------------------
# Walk-up: happy paths
# ---------------------------------------------------------------------------


class TestWalkupHappyPaths:
    def test_walkup_finds_lint_table(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Walk-up from CWD finds the [tool.protokit.lint] table."""
        _write_pyproject(
            tmp_path,
            "[tool.protokit.lint]\nprofile = 'default'\nmax_warnings = 0\n",
        )
        (tmp_path / ".git").mkdir()
        monkeypatch.chdir(tmp_path)

        result = load_pyproject_config(explicit_path=None, no_config=False)

        assert result == {"profile": "default", "max_warnings": 0}

    def test_walkup_silent_on_table_absent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Walk-up finds pyproject but [tool.protokit.lint] is absent →
        return None (R5 silent fallback)."""
        _write_pyproject(tmp_path, "[project]\nname = 'foo'\n")
        (tmp_path / ".git").mkdir()
        monkeypatch.chdir(tmp_path)

        result = load_pyproject_config(explicit_path=None, no_config=False)

        assert result is None

    def test_walkup_silent_on_no_pyproject_found(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """No pyproject anywhere up to .git boundary → return None silently."""
        (tmp_path / ".git").mkdir()
        deep = tmp_path / "subdir"
        deep.mkdir()
        monkeypatch.chdir(deep)

        result = load_pyproject_config(explicit_path=None, no_config=False)

        assert result is None


# ---------------------------------------------------------------------------
# Explicit path: R5a strict shadow paths
# ---------------------------------------------------------------------------


class TestExplicitPathHappyPath:
    def test_explicit_path_returns_lint_table(self, tmp_path: Path) -> None:
        """--config PATH with valid pyproject + [tool.protokit.lint] table."""
        path = _write_pyproject(
            tmp_path,
            "[tool.protokit.lint]\nmin_severity = 'warning'\n",
        )

        result = load_pyproject_config(explicit_path=path, no_config=False)

        assert result == {"min_severity": "warning"}


class TestExplicitPathR5aShadowPaths:
    """All four R5a shadow paths exit 2 with the pyproject-config-load
    error prefix and newline-sanitized stderr."""

    def test_path_does_not_exist(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        missing = tmp_path / "does_not_exist.toml"

        with pytest.raises(SystemExit) as exc_info:
            load_pyproject_config(explicit_path=missing, no_config=False)

        assert exc_info.value.code == 2
        captured = capsys.readouterr()
        assert "error[lint-pyproject-config-load]:" in captured.err
        assert "does not exist" in captured.err

    def test_path_with_no_lint_table_strict_error(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Explicit-path strict mode: missing [tool.protokit.lint] is hard error."""
        path = _write_pyproject(tmp_path, "[project]\nname = 'foo'\n")

        with pytest.raises(SystemExit) as exc_info:
            load_pyproject_config(explicit_path=path, no_config=False)

        assert exc_info.value.code == 2
        captured = capsys.readouterr()
        assert "error[lint-pyproject-config-load]:" in captured.err
        assert "no [tool.protokit.lint] table" in captured.err

    def test_path_invalid_toml(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Malformed TOML produces structured error (no raw bytes per R5a)."""
        path = tmp_path / "bad.toml"
        # Write something that's syntactically invalid TOML.
        path.write_text("this is = not = valid = toml = at all\n", encoding="utf-8")

        with pytest.raises(SystemExit) as exc_info:
            load_pyproject_config(explicit_path=path, no_config=False)

        assert exc_info.value.code == 2
        captured = capsys.readouterr()
        assert "error[lint-pyproject-config-load]:" in captured.err
        assert "TOML parse error" in captured.err
        # R5a content-safety: the raw invalid TOML line content must NOT
        # appear verbatim in stderr.
        assert "not = valid = toml = at all" not in captured.err

    def test_path_not_valid_utf8(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Non-UTF-8 bytes produce error WITHOUT echoing the bytes."""
        path = tmp_path / "binary.toml"
        # Invalid UTF-8 sequence: 0xff is never a valid start byte.
        path.write_bytes(b"\xff\xfe\x00\x01\x02 secret bytes here")

        with pytest.raises(SystemExit) as exc_info:
            load_pyproject_config(explicit_path=path, no_config=False)

        assert exc_info.value.code == 2
        captured = capsys.readouterr()
        assert "error[lint-pyproject-config-load]:" in captured.err
        assert "not valid UTF-8" in captured.err
        assert "secret bytes here" not in captured.err

    def test_path_unreadable_explicit_mode(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """File exists but read_bytes raises PermissionError → exit 2
        with strict-mode message.

        Fix #5: explicit OSError-branch coverage in ``_read_and_parse``.
        Pairs with :meth:`test_walkup_unreadable_pyproject_uses_walkup_label`
        below which verifies the Fix #1 source_label attribution.
        """
        path = _write_pyproject(tmp_path, "[tool.protokit.lint]\n")

        def raise_perm(self: Path) -> bytes:
            raise PermissionError(13, "Permission denied", str(self))

        monkeypatch.setattr(Path, "read_bytes", raise_perm)

        with pytest.raises(SystemExit) as exc_info:
            load_pyproject_config(explicit_path=path, no_config=False)

        assert exc_info.value.code == 2
        captured = capsys.readouterr()
        assert "error[lint-pyproject-config-load]:" in captured.err
        assert "unreadable" in captured.err
        # Fix #1: explicit-mode source_label.
        assert "--config path" in captured.err

    def test_walkup_unreadable_pyproject_uses_walkup_label(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Walk-up discovers an unreadable pyproject → error message
        says 'walk-up...' NOT '--config path'.

        Fix #1 attribution check: locks in that walk-up callers no
        longer mis-attribute filesystem errors as if the user passed
        ``--config``. Catches the Fix #1 attribution bug if Fix #1
        is ever regressed.
        """
        _write_pyproject(tmp_path, "[tool.protokit.lint]\n")
        (tmp_path / ".git").mkdir()
        monkeypatch.chdir(tmp_path)

        def raise_perm(self: Path) -> bytes:
            raise PermissionError(13, "Permission denied", str(self))

        monkeypatch.setattr(Path, "read_bytes", raise_perm)

        with pytest.raises(SystemExit) as exc_info:
            load_pyproject_config(explicit_path=None, no_config=False)

        assert exc_info.value.code == 2
        captured = capsys.readouterr()
        assert "error[lint-pyproject-config-load]:" in captured.err
        # KEY: walk-up errors must NOT claim '--config' was passed.
        assert "--config" not in captured.err
        assert "walk-up" in captured.err

    def test_tomllib_error_message_form_on_python_311_plus(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Document: stdlib tomllib (py3.11+) has no lineno/colno
        attributes → unstructured "in {path}" form.

        Fix #14 locks in the py-version-specific behavior so the
        structured-branch dead-code on py3.11+ isn't mistaken for a
        bug. On py<3.11 (tomli backport), lineno/colno ARE exposed
        and the structured "at {path}:line:col" form is reachable.
        """
        import sys
        if sys.version_info < (3, 11):
            pytest.skip(
                "tomli backport exposes lineno/colno; "
                "stdlib tomllib does not"
            )
        path = tmp_path / "bad.toml"
        path.write_text("[tool.protokit.lint]\nnot valid toml = = =\n")
        with pytest.raises(SystemExit):
            load_pyproject_config(explicit_path=path, no_config=False)
        captured = capsys.readouterr()
        # On py3.11+: unstructured "in {path}" form (no line:col).
        assert "TOML parse error in" in captured.err
        # NOT "at {path}:line:col" form.
        assert "TOML parse error at" not in captured.err


class TestExplicitPathContentSafety:
    """R5a content-safety: tomllib parse errors emit path:line:col only,
    NEVER the raw file content the error occurred at."""

    def test_no_sensitive_content_echoed_on_parse_error(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Pretend the file contains a sensitive token; parse error
        must not include it in the stderr message."""
        path = tmp_path / "config.toml"
        path.write_text(
            "[tool.protokit.lint]\n"
            "secret_token = SECRET-DO-NOT-LEAK\n",  # invalid TOML (unquoted)
            encoding="utf-8",
        )

        with pytest.raises(SystemExit):
            load_pyproject_config(explicit_path=path, no_config=False)

        captured = capsys.readouterr()
        assert "SECRET-DO-NOT-LEAK" not in captured.err


# ---------------------------------------------------------------------------
# _parse_toml_bytes: triple-arm exception guard
# ---------------------------------------------------------------------------


class TestParseTomlBytesTripleArmGuard:
    """Per KTD-9: SystemExit catches; KeyboardInterrupt re-raises;
    Exception routes to pyproject-config-load."""

    def test_systemexit_in_parser_routes_to_error_exit(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A malicious tomllib.loads raising SystemExit must NOT cause a
        false-clean exit. Triple-arm catches and routes to the lint
        error surface."""
        path = tmp_path / "config.toml"

        def fake_loads(_s: str) -> dict[str, object]:
            raise SystemExit(0)

        monkeypatch.setattr(
            "protokit.schema.lint._config.tomllib.loads", fake_loads,
        )

        with pytest.raises(SystemExit) as exc_info:
            _parse_toml_bytes(b"", path)

        # Must NOT be exit 0 (the malicious code argument). Must be exit 2
        # via the error_exit_with_code surface.
        assert exc_info.value.code == 2
        captured = capsys.readouterr()
        assert "error[lint-pyproject-config-load]:" in captured.err
        assert "SystemExit" in captured.err

    def test_keyboard_interrupt_propagates(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """User SIGINT must propagate to Python's default handler.
        Catch-and-reraise prevents the bare-Exception arm from
        absorbing the interrupt signal."""
        path = tmp_path / "config.toml"

        def fake_loads(_s: str) -> dict[str, object]:
            raise KeyboardInterrupt

        monkeypatch.setattr(
            "protokit.schema.lint._config.tomllib.loads", fake_loads,
        )

        with pytest.raises(KeyboardInterrupt):
            _parse_toml_bytes(b"", path)

    def test_unexpected_exception_routes_to_error_exit(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Any other Exception from tomllib (defense-in-depth) routes to
        the pyproject-config-load surface with sanitized stderr."""
        path = tmp_path / "config.toml"

        def fake_loads(_s: str) -> dict[str, object]:
            raise RuntimeError("internal corruption")

        monkeypatch.setattr(
            "protokit.schema.lint._config.tomllib.loads", fake_loads,
        )

        with pytest.raises(SystemExit) as exc_info:
            _parse_toml_bytes(b"", path)

        assert exc_info.value.code == 2
        captured = capsys.readouterr()
        assert "error[lint-pyproject-config-load]:" in captured.err
        assert "RuntimeError" in captured.err


# ---------------------------------------------------------------------------
# _extract_lint_table: schema traversal safety
# ---------------------------------------------------------------------------


class TestExtractLintTable:
    def test_extracts_nested_table(self) -> None:
        table = {"tool": {"protokit": {"lint": {"profile": "default"}}}}
        assert _extract_lint_table(table) == {"profile": "default"}

    def test_returns_none_when_tool_missing(self) -> None:
        assert _extract_lint_table({"project": {"name": "foo"}}) is None

    def test_returns_none_when_tool_protokit_missing(self) -> None:
        assert _extract_lint_table({"tool": {"black": {}}}) is None

    def test_returns_none_when_lint_missing(self) -> None:
        assert _extract_lint_table({"tool": {"protokit": {"compat": {}}}}) is None

    def test_returns_none_when_tool_is_not_dict(self) -> None:
        """Defends against pathological pyproject contents."""
        # Mypy is stricter than tomllib's runtime behavior — bypass with
        # cast/ignore. In practice tomllib coerces top-level scalars.
        table: dict[str, object] = {"tool": "not a table"}
        assert _extract_lint_table(table) is None  # type: ignore[arg-type]

    def test_returns_none_when_lint_is_not_dict(self) -> None:
        table: dict[str, object] = {"tool": {"protokit": {"lint": ["a"]}}}
        assert _extract_lint_table(table) is None  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Newline-sanitization helper
# ---------------------------------------------------------------------------


class TestSafeForStderr:
    """KTD-9 defense-in-depth: control-character sanitization on stderr-bound
    strings. Scope extended per ce:review finding #11 to cover null bytes
    and ANSI escape sequences in addition to newlines."""

    def test_collapses_linefeed(self) -> None:
        assert _safe_for_stderr("a\nb") == "a b"

    def test_collapses_carriage_return(self) -> None:
        assert _safe_for_stderr("a\rb") == "a b"

    def test_collapses_both(self) -> None:
        assert _safe_for_stderr("a\r\nb") == "a  b"

    def test_handles_path_objects(self, tmp_path: Path) -> None:
        """Path objects are stringified (no newlines in real Path values
        but the helper accepts any object)."""
        result = _safe_for_stderr(tmp_path / "foo")
        assert "\n" not in result and "\r" not in result

    def test_handles_exception_objects(self) -> None:
        exc = OSError("some\nmulti\nline\nmessage")
        result = _safe_for_stderr(exc)
        assert "\n" not in result

    def test_collapses_null_byte(self) -> None:
        """Null bytes truncate stderr lines in syslog / log-ingestion
        pipelines that treat NUL as string terminator. Must be replaced.

        Defends against attacker-controlled paths like
        ``--config /tmp/evil\\x00.toml`` flowing into the bare-Exception
        arm of `_parse_toml_bytes` and surfacing in stderr via
        `_safe_for_stderr(path)`.
        """
        result = _safe_for_stderr("before\x00after")
        assert "\x00" not in result
        assert result == "before after"

    def test_collapses_ansi_escape(self) -> None:
        """ANSI escape sequences (ESC, 0x1b) can inject terminal color
        or cursor control that obscures the `error[lint-` stable prefix
        CI scripts grep for. Must be replaced.
        """
        # ESC[31m would normally turn the following text red on an ANSI terminal.
        result = _safe_for_stderr("normal\x1b[31mred-text\x1b[0m")
        assert "\x1b" not in result

    def test_collapses_tab(self) -> None:
        """Tab characters can shift line layout in fixed-width stderr
        parsers. Same defense-in-depth posture as newlines."""
        result = _safe_for_stderr("a\tb")
        assert "\t" not in result
        assert result == "a b"

    def test_collapses_del(self) -> None:
        """The DEL character (0x7f) is the one non-0x00-0x1f control
        char in 7-bit ASCII. Helper must cover it too."""
        result = _safe_for_stderr("a\x7fb")
        assert "\x7f" not in result

    def test_preserves_printable_ascii(self) -> None:
        """Sanitization must not touch the normal printable range."""
        s = "abc XYZ 123 !@#$%^&*()_+-=[]{}|;:',.<>/?`~"
        assert _safe_for_stderr(s) == s

    def test_preserves_non_ascii_unicode(self) -> None:
        """Unicode characters above 0x7f are NOT control chars in the
        relevant sense. Paths with valid UTF-8 names containing
        non-ASCII characters should round-trip unchanged."""
        s = "/repo/プロジェクト/config.toml"
        assert _safe_for_stderr(s) == s

    def test_collapses_unicode_next_line(self) -> None:
        """U+0085 NEXT LINE (NEL) is a Unicode line terminator. Terminals
        do not break on it, but Unicode-aware log aggregators (Datadog,
        Splunk, CloudWatch) split records on it — a message containing
        NEL can inject a fake aggregator record beginning with a forged
        stable-prefix line.
        """
        result = _safe_for_stderr("legitimateerror[lint-bad]: forged")
        assert "" not in result
        assert result == "legitimate error[lint-bad]: forged"

    def test_collapses_unicode_line_separator(self) -> None:
        """U+2028 LINE SEPARATOR: same risk class as NEL."""
        result = _safe_for_stderr("legitimate error[lint-bad]: forged")
        assert " " not in result
        assert result == "legitimate error[lint-bad]: forged"

    def test_collapses_unicode_paragraph_separator(self) -> None:
        """U+2029 PARAGRAPH SEPARATOR: same risk class as NEL."""
        result = _safe_for_stderr("legitimate error[lint-bad]: forged")
        assert " " not in result
        assert result == "legitimate error[lint-bad]: forged"
