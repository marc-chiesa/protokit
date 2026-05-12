"""Tests for ``compile_exclude_patterns`` (D5 U3).

Covers:

- **Happy paths**: simple globs, multi-pattern, gitignore-style
  negation (``!path``), and the empty-pattern edge case.
- **Match semantics**: pathspec ``gitwildmatch`` matches
  ``FileDescriptorProto.name``-shaped paths (no leading slash;
  forward-slash separators).
- **Pathological patterns**: pathspec is permissive — empty
  strings, whitespace-only strings, and even bracket-malformed
  patterns parse without error and match nothing.
- **Error surface**: when pathspec DOES reject a pattern, the
  helper exits 2 with ``error[lint-exclude-pattern-invalid]:``
  (the D5 U3 stable prefix, distinct from the U1
  ``pyproject-config-load`` and U2 ``pyproject-config-invalid``
  prefixes).
"""

from __future__ import annotations

import pytest

from protokit.schema.lint._config import compile_exclude_patterns

# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


class TestHappyPaths:
    def test_simple_vendor_pattern(self) -> None:
        spec = compile_exclude_patterns(("vendor/**",))
        assert spec.match_file("vendor/foo.proto") is True
        assert spec.match_file("vendor/sub/bar.proto") is True
        assert spec.match_file("api/user.proto") is False

    def test_multiple_patterns_or_together(self) -> None:
        spec = compile_exclude_patterns(("vendor/**", "third_party/**"))
        assert spec.match_file("vendor/foo.proto") is True
        assert spec.match_file("third_party/bar.proto") is True
        assert spec.match_file("api/user.proto") is False

    def test_gitignore_negation(self) -> None:
        """``!path`` re-includes a previously-excluded path. This is
        the gitwildmatch negation semantic; useful for excluding a
        whole directory except for one file.
        """
        spec = compile_exclude_patterns(
            ("vendor/**", "!vendor/important.proto"),
        )
        assert spec.match_file("vendor/foo.proto") is True
        # Negation re-includes the named file:
        assert spec.match_file("vendor/important.proto") is False

    def test_specific_file_extension(self) -> None:
        spec = compile_exclude_patterns(("**/test/*.proto",))
        assert spec.match_file("api/test/example.proto") is True
        assert spec.match_file("test/example.proto") is True
        # Non-matching extension or path:
        assert spec.match_file("api/example.proto") is False
        assert spec.match_file("api/test/example.go") is False


# ---------------------------------------------------------------------------
# Empty / edge-case inputs
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_pattern_list_matches_nothing(self) -> None:
        """An empty pattern iterable returns an empty PathSpec; every
        ``match_file`` call returns False. Callers can pass `()`
        unconditionally as the "no exclude" sentinel.
        """
        spec = compile_exclude_patterns(())
        assert spec.match_file("foo.proto") is False
        assert spec.match_file("vendor/anything.proto") is False

    def test_empty_string_patterns_are_ignored(self) -> None:
        """pathspec treats empty strings as comments / no-op lines.
        They neither match nor cause errors.
        """
        spec = compile_exclude_patterns(("", "   ", "vendor/**"))
        assert spec.match_file("vendor/foo.proto") is True
        assert spec.match_file("api/foo.proto") is False

    def test_pathspec_is_permissive_about_bracket_chars(self) -> None:
        """Patterns that look like malformed character classes
        (``[``, ``[[[``) parse cleanly under gitwildmatch and match
        nothing in practice. pathspec is permissive by design;
        confirming that prevents false-positive failure reports in
        tests that try to exercise the error path.
        """
        spec = compile_exclude_patterns(("[", "[[[[["))
        assert spec.match_file("foo.proto") is False


# ---------------------------------------------------------------------------
# Match semantics on FileDescriptorProto.name shapes
# ---------------------------------------------------------------------------


class TestFileDescriptorProtoNameShapes:
    def test_no_leading_slash_paths(self) -> None:
        """``FileDescriptorProto.name`` is a relative path like
        ``"acme/user.proto"`` — never absolute. gitwildmatch handles
        this shape correctly.
        """
        spec = compile_exclude_patterns(("acme/**",))
        assert spec.match_file("acme/user.proto") is True
        assert spec.match_file("acme/sub/user.proto") is True
        assert spec.match_file("other/user.proto") is False

    def test_leading_dotslash_normalized_by_pathspec(self) -> None:
        """When the user passes ``protoc -I.`` the resulting
        ``FileDescriptorProto.name`` can carry a leading ``./``.
        Patterns should still match — pathspec normalizes the path
        components internally.
        """
        spec = compile_exclude_patterns(("vendor/**",))
        # Without leading ./ — matches as expected:
        assert spec.match_file("vendor/foo.proto") is True
        # With leading ./ — pathspec normalizes:
        assert spec.match_file("./vendor/foo.proto") is True


# ---------------------------------------------------------------------------
# Tuple-vs-iterable input acceptance
# ---------------------------------------------------------------------------


class TestInputShapes:
    def test_accepts_tuple_input(self) -> None:
        spec = compile_exclude_patterns(("vendor/**",))
        assert spec.match_file("vendor/x.proto") is True

    def test_accepts_list_input(self) -> None:
        spec = compile_exclude_patterns(["vendor/**"])
        assert spec.match_file("vendor/x.proto") is True

    def test_accepts_generator_input(self) -> None:
        """The helper's parameter is typed Iterable[str]; passing a
        generator should work (pathspec materializes internally).
        """
        spec = compile_exclude_patterns(p for p in ("vendor/**",))
        assert spec.match_file("vendor/x.proto") is True


# ---------------------------------------------------------------------------
# Error surface (defensive — pathspec is permissive in practice)
# ---------------------------------------------------------------------------


class TestErrorSurface:
    def test_pathological_input_returns_via_defensive_catch(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When pathspec raises an unexpected exception, the
        defensive ``except Exception`` arm routes the failure through
        ``error_exit_with_code("exclude-pattern-invalid", ...)``
        rather than escaping as an uncaught traceback. We force the
        exception by monkeypatching ``PathSpec.from_lines``.
        """
        import pathspec
        from pathspec.patterns.gitwildmatch import GitWildMatchPatternError

        def _boom(*_args: object, **_kwargs: object) -> pathspec.PathSpec:
            raise GitWildMatchPatternError("synthetic invalid pattern")

        monkeypatch.setattr(
            pathspec.PathSpec, "from_lines", classmethod(_boom),
        )

        with pytest.raises(SystemExit) as exc_info:
            compile_exclude_patterns(("anything",))
        assert exc_info.value.code == 2

        captured = capsys.readouterr()
        assert (
            "error[lint-exclude-pattern-invalid]:" in captured.err
        )
        assert "invalid exclude pattern" in captured.err
        assert "synthetic invalid pattern" in captured.err

    def test_unexpected_exception_caught_by_defense_in_depth(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Any non-GitWildMatchPatternError still routes through the
        stable error prefix; defense-in-depth tail catch.
        """
        import pathspec

        def _boom(*_args: object, **_kwargs: object) -> pathspec.PathSpec:
            raise RuntimeError("unexpected pathspec internal failure")

        monkeypatch.setattr(
            pathspec.PathSpec, "from_lines", classmethod(_boom),
        )

        with pytest.raises(SystemExit) as exc_info:
            compile_exclude_patterns(("anything",))
        assert exc_info.value.code == 2

        captured = capsys.readouterr()
        assert (
            "error[lint-exclude-pattern-invalid]:" in captured.err
        )
        # The defense-in-depth catch names the exception type so
        # future-pathspec failures are diagnosable without a
        # traceback.
        assert "RuntimeError" in captured.err

    def test_newline_in_pattern_is_sanitized_via_safe_for_stderr(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Per KTD-9, if pathspec includes a user-supplied newline-
        bearing pattern in its exception message, the helper passes
        it through ``_safe_for_stderr`` before interpolation so a
        forged ``error[lint-...]:`` second line cannot appear.
        """
        import pathspec
        from pathspec.patterns.gitwildmatch import GitWildMatchPatternError

        def _boom(*_args: object, **_kwargs: object) -> pathspec.PathSpec:
            # Construct an exception whose str() contains a newline
            # plus a fake error-prefix-like line.
            raise GitWildMatchPatternError(
                "real failure\nerror[lint-forged]: bogus second line",
            )

        monkeypatch.setattr(
            pathspec.PathSpec, "from_lines", classmethod(_boom),
        )

        with pytest.raises(SystemExit):
            compile_exclude_patterns(("anything",))

        captured = capsys.readouterr()
        # The sanitized exception message collapsed the newline to a
        # space, so the forged line cannot stand alone as a fake
        # error-prefix entry. The literal substring with the embedded
        # \n must NOT appear in stderr.
        assert "\nerror[lint-forged]:" not in captured.err
        # The legitimate prefix still appears at the start of stderr:
        assert captured.err.startswith(
            "error[lint-exclude-pattern-invalid]:",
        )
