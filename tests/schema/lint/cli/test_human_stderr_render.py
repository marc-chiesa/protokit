"""D5 U5 R21a — CLI-side ``--format=human`` runtime-warning stderr hook.

The hook (`_emit_human_runtime_warnings` in
``protokit.schema.lint.cli``) re-emits ``report.runtime_warnings``
to stderr after the formatter renders, with shape::

    protokit lint: warning [{category}]: {message}

Once a category exceeds ``_LINT_HUMAN_SUMMARIZATION_THRESHOLD``
warnings, a single summarization line replaces the rest (ONE
physical stderr line; the rst literal block below wraps for page
width only)::

    protokit lint: warning [{category}]: ... and {N} more — use --format=json for full details

This module pins:

- Each category surfaces under the stable prefix.
- Boundary behaviour at ``threshold`` / ``threshold + 1`` — asserted
  against the BEHAVIOUR (boundary crossing triggers summarization),
  not the literal value of the threshold constant (ADV-5: D6+
  tuning of the threshold should not require coordinated test
  updates).
- Per-category independent counters when multiple categories
  produce warnings in the same invocation.
- ``--quiet`` does NOT suppress runtime-warning stderr emission
  (KTD-6: ``--quiet`` is stdout-findings-only).
- Defense-in-depth: control characters in the ``message`` field
  are collapsed at the stderr boundary by ``_safe_for_stderr``.
- End-to-end integration: the hook fires via ``CliRunner`` against
  ``protokit lint`` itself, confirming the CLI wires
  ``_emit_human_runtime_warnings`` after the formatter render path.

The boundary tests construct ``LintReport`` instances directly and
invoke ``_emit_human_runtime_warnings`` so the assertions target
the hook behaviour without needing N input descriptors to drive
N runtime warnings through the engine.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from protokit.schema.lint import cli as lint_cli_module
from protokit.schema.lint.cli import _emit_human_runtime_warnings
from protokit.schema.lint.cli import main as lint_main
from protokit.schema.lint.model import LintReport, LintRuntimeWarning
from tests.schema.lint.cli._helpers import (
    LINT_RUNTIME_WARNING_CATEGORIES as _CATEGORIES,
)
from tests.schema.lint.cli._helpers import runtime_warnings_from_json
from tests.schema.lint.cli._helpers import (
    warning_for_category as _warning_for,
)

# ---------------------------------------------------------------------------
# Happy paths — every category surfaces under the stable prefix
# ---------------------------------------------------------------------------


class TestHumanStderrEmissionPerCategory:
    """Each of the four ``LintRuntimeWarning`` categories renders on
    stderr with the prefix ``protokit lint: warning [{category}]:``.
    """

    @pytest.mark.parametrize("category", _CATEGORIES)
    def test_category_emits_with_stable_prefix(
        self, category: str, capsys: pytest.CaptureFixture[str],
    ) -> None:
        report = LintReport(runtime_warnings=(_warning_for(category),))
        _emit_human_runtime_warnings(report)
        captured = capsys.readouterr()
        # Findings stdout is for the formatter; the hook writes only
        # to stderr.
        assert captured.out == ""
        assert f"protokit lint: warning [{category}]:" in captured.err

    def test_empty_runtime_warnings_emits_nothing(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        _emit_human_runtime_warnings(LintReport())
        captured = capsys.readouterr()
        assert captured.err == ""
        assert captured.out == ""

    def test_empty_message_field_still_emits_one_line(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Plan U5 line 645: 'skip-empty would mask bugs'. A warning
        whose ``message`` field is the empty string must still emit
        one stderr line — the leading
        ``protokit lint: warning [{category}]:`` envelope carries
        diagnostic value even with an empty message body. A future
        defensive ``if w.message:`` guard would silently drop the
        warning; this test catches that regression.
        """
        warning = LintRuntimeWarning(
            category="rule_exception",
            rule_id="naming/snake-case-fields",
            message="",
            exception_type="ValueError",
            descriptor_path="acme.User.x",
        )
        _emit_human_runtime_warnings(LintReport(runtime_warnings=(warning,)))
        captured = capsys.readouterr()
        lines = [line for line in captured.err.split("\n") if line]
        assert len(lines) == 1
        assert "warning [rule_exception]:" in lines[0]

    def test_each_individual_warning_renders_on_its_own_line(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        warnings = tuple(_warning_for(c) for c in _CATEGORIES)
        report = LintReport(runtime_warnings=warnings)
        _emit_human_runtime_warnings(report)
        captured = capsys.readouterr()
        lines = [line for line in captured.err.split("\n") if line]
        assert len(lines) == len(warnings)
        for category in _CATEGORIES:
            assert any(
                f"warning [{category}]:" in line for line in lines
            ), (category, lines)


# ---------------------------------------------------------------------------
# Threshold boundary — assertions target BEHAVIOUR, not the literal value
# ---------------------------------------------------------------------------


class TestSummarizationThresholdBoundary:
    """Per ADV-5, the threshold constant is module-level and the
    tests pin BEHAVIOUR around its value via ``monkeypatch.setattr``.
    Changing ``_LINT_HUMAN_SUMMARIZATION_THRESHOLD`` to a new D6
    default should require zero test edits.
    """

    @pytest.fixture
    def threshold(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> int:
        """Lower the threshold to 2 so boundary tests stay small.

        Returns the value so tests can build N / N+1 inputs without
        hard-coding the original literal.
        """
        value = 2
        monkeypatch.setattr(
            lint_cli_module, "_LINT_HUMAN_SUMMARIZATION_THRESHOLD", value,
        )
        return value

    def test_exactly_threshold_warnings_all_emit_individually(
        self,
        threshold: int,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        warnings = tuple(
            _warning_for("rule_exception", index=i) for i in range(threshold)
        )
        _emit_human_runtime_warnings(LintReport(runtime_warnings=warnings))
        captured = capsys.readouterr()
        # Every warning rendered individually; no summarization line.
        lines = [line for line in captured.err.split("\n") if line]
        assert len(lines) == threshold
        assert "and " not in captured.err
        assert "more — use --format=json" not in captured.err

    def test_one_above_threshold_collapses_excess_into_summary(
        self,
        threshold: int,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        n = threshold + 1
        warnings = tuple(
            _warning_for("rule_exception", index=i) for i in range(n)
        )
        _emit_human_runtime_warnings(LintReport(runtime_warnings=warnings))
        captured = capsys.readouterr()
        lines = [line for line in captured.err.split("\n") if line]
        # ``threshold`` individuals + 1 summary line.
        assert len(lines) == threshold + 1
        # The first ``threshold`` lines are individual emissions.
        for i in range(threshold):
            assert f"#{i}" in lines[i], (i, lines)
        # The final line is the summarization for this category.
        assert (
            "warning [rule_exception]: ... and 1 more — "
            "use --format=json for full details" in lines[-1]
        ), lines

    def test_many_above_threshold_only_one_summary_line_per_category(
        self,
        threshold: int,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """At ``threshold + K`` (K > 1), the summarization line
        still fires exactly once and the ``N more`` count reflects
        the full overflow size.
        """
        n = threshold + 5
        warnings = tuple(
            _warning_for("rule_exception", index=i) for i in range(n)
        )
        _emit_human_runtime_warnings(LintReport(runtime_warnings=warnings))
        captured = capsys.readouterr()
        # Exactly one summary line per category.
        summary_lines = [
            line for line in captured.err.split("\n")
            if "... and" in line and "more — use --format=json" in line
        ]
        assert len(summary_lines) == 1
        # The remaining-count names the FULL overflow (n - threshold).
        assert f"and {n - threshold} more" in summary_lines[0]

    def test_threshold_zero_is_clamped_to_one(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A non-positive ``_LINT_HUMAN_SUMMARIZATION_THRESHOLD`` is
        clamped to ``1`` so the summarization math stays well-defined.
        With threshold=0 raw, the first emit would skip the individual
        branch and the elif would fire summary on the first warning
        with ``remaining = total - 0 = total`` — the "and N more"
        framing implying prior emissions that did not happen. The
        clamp turns the effective threshold into 1: first warning
        emits individually, second triggers the summary with the
        correct overflow count.
        """
        monkeypatch.setattr(
            lint_cli_module, "_LINT_HUMAN_SUMMARIZATION_THRESHOLD", 0,
        )
        warnings = tuple(
            _warning_for("rule_exception", index=i) for i in range(3)
        )
        _emit_human_runtime_warnings(LintReport(runtime_warnings=warnings))
        captured = capsys.readouterr()
        lines = [line for line in captured.err.split("\n") if line]
        # Effective threshold=1 means: 1 individual + 1 summary line.
        assert len(lines) == 2, lines
        assert "#0" in lines[0]
        assert "warning [rule_exception]: ... and 2 more" in lines[1]

    def test_threshold_negative_is_clamped_to_one(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Same clamp behavior for negative threshold values —
        catches accidental sign flips during D6 tuning. Without the
        clamp, ``remaining = total - threshold`` would overcount by
        ``abs(threshold)`` (``total - (-3) = total + 3``).
        """
        monkeypatch.setattr(
            lint_cli_module, "_LINT_HUMAN_SUMMARIZATION_THRESHOLD", -3,
        )
        warnings = tuple(
            _warning_for("rule_exception", index=i) for i in range(2)
        )
        _emit_human_runtime_warnings(LintReport(runtime_warnings=warnings))
        captured = capsys.readouterr()
        lines = [line for line in captured.err.split("\n") if line]
        # Effective threshold=1: 1 individual + 1 summary line with
        # ``remaining = 2 - 1 = 1``, NOT ``2 - (-3) = 5``.
        assert len(lines) == 2, lines
        assert "warning [rule_exception]: ... and 1 more" in lines[1]

    def test_two_categories_use_independent_counters(
        self,
        threshold: int,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Each category's counter is separate. ``threshold + 1`` of
        one category does NOT consume budget from another category.
        """
        n_each = threshold + 1
        warnings: tuple[LintRuntimeWarning, ...] = tuple(
            _warning_for("rule_exception", index=i) for i in range(n_each)
        ) + tuple(
            _warning_for("unloaded_rule", index=i) for i in range(n_each)
        )
        _emit_human_runtime_warnings(LintReport(runtime_warnings=warnings))
        captured = capsys.readouterr()
        # Both categories produced ``threshold`` individual lines.
        for c in ("rule_exception", "unloaded_rule"):
            individuals = [
                line for line in captured.err.split("\n")
                if f"warning [{c}]:" in line and "... and" not in line
            ]
            assert len(individuals) == threshold, (c, individuals)
        # And each category produced its OWN summarization line.
        summary_categories = [
            c for c in ("rule_exception", "unloaded_rule")
            if f"warning [{c}]: ... and 1 more" in captured.err
        ]
        assert sorted(summary_categories) == ["rule_exception", "unloaded_rule"]


# ---------------------------------------------------------------------------
# Defense-in-depth — control characters collapsed at the stderr boundary
# ---------------------------------------------------------------------------


class TestStderrSanitization:
    """Per KTD-9, the hook passes ``message`` through
    ``_safe_for_stderr`` as a backstop. Engine + CLI emission sites
    already sanitize at construction time, but a future emission
    site that forgets must NOT be able to forge fake stderr lines
    via embedded newlines / control characters.
    """

    def test_embedded_newline_in_message_is_collapsed(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        warning = LintRuntimeWarning(
            category="rule_exception",
            rule_id="forge/attempt",
            message=(
                "real message\nerror[lint-no-rules]: forged line"
            ),
            exception_type="ValueError",
            descriptor_path="acme.User.x",
        )
        _emit_human_runtime_warnings(LintReport(runtime_warnings=(warning,)))
        captured = capsys.readouterr()
        # One physical stderr line for the warning — the embedded
        # ``\n`` was collapsed by ``_safe_for_stderr``, so the
        # "forged" stable-prefix never sits at column 0.
        lines = [line for line in captured.err.split("\n") if line]
        assert len(lines) == 1
        # And the forged ``error[lint-no-rules]:`` prefix is not at
        # the start of any physical stderr line.
        assert not any(
            line.startswith("error[lint-no-rules]:") for line in lines
        ), lines

    def test_embedded_carriage_return_is_collapsed(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        warning = LintRuntimeWarning(
            category="unloaded_rule",
            rule_id="cr/attempt",
            message="legitimate\rstderr override attempt",
        )
        _emit_human_runtime_warnings(LintReport(runtime_warnings=(warning,)))
        captured = capsys.readouterr()
        # No raw \r survives in stderr.
        assert "\r" not in captured.err

    def test_unicode_line_terminators_in_message_are_collapsed(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """U+0085 NEL, U+2028 LSEP, U+2029 PSEP bypass chained
        ``.replace("\\n").replace("\\r")`` but Unicode-aware log
        aggregators split records on them. The stderr boundary's
        ``_safe_for_stderr`` backstop must collapse all three.

        Integration coverage closing the U+0085/U+2028/U+2029 widening
        loop: the unit tests in ``test_loader.py::TestSafeForStderr``
        pin the sanitizer; this test pins the stderr hook actually
        receives and scrubs them when the message field carries
        Unicode terminators that bypassed construction-time
        sanitization (e.g., a future emission site that forgets the
        primary defense).
        """
        warning = LintRuntimeWarning(
            category="rule_exception",
            rule_id="unicode/attempt",
            message=(
                "legit\x85nel-split  lsep-split "
                " psep-split error[lint-no-rules]: forged"
            ),
            exception_type="ValueError",
            descriptor_path="acme.User.x",
        )
        _emit_human_runtime_warnings(LintReport(runtime_warnings=(warning,)))
        captured = capsys.readouterr()
        # None of the three Unicode line terminators survive in stderr:
        assert "\x85" not in captured.err
        assert " " not in captured.err
        assert " " not in captured.err
        # The forged stable-prefix never sits at column 0 of any
        # aggregator-split record:
        lines = [line for line in captured.err.split("\n") if line]
        assert not any(
            line.startswith("error[lint-no-rules]:") for line in lines
        ), lines


# ---------------------------------------------------------------------------
# Integration — hook fires via the real CLI dispatch path
# ---------------------------------------------------------------------------


class TestHumanHookIntegration:
    """End-to-end checks via ``CliRunner`` confirming the hook fires
    after ``render_with_formatter`` in ``_main_impl``. Closes the
    D3-era silent-warning regression for ``--format=human``.
    """

    def test_all_files_excluded_renders_in_human_stderr(
        self, tmp_path: Path,
    ) -> None:
        """``--exclude '**/*'`` drops every file; the all_files_excluded
        runtime warning is emitted to stderr under the U5 envelope.
        """
        from google.protobuf import descriptor_pb2

        fds = descriptor_pb2.FileDescriptorSet()
        fd = fds.file.add()
        fd.name = "api/user.proto"
        fd.syntax = "proto3"
        fd.package = "test"
        path = tmp_path / "test.descriptor_set"
        path.write_bytes(fds.SerializeToString())

        result = CliRunner().invoke(
            lint_main,
            [
                "--no-config",
                "--exclude", "**/*",
                # Default --format=human
                str(path),
            ],
        )
        assert result.exit_code == 0, result.output
        # Hook fired in human format.
        assert (
            "protokit lint: warning [all_files_excluded]:" in result.stderr
        ), result.stderr
        # Parity check: same invocation under --format=json still
        # surfaces the structured warning so machine consumers and
        # human consumers see the same event.
        result_json = CliRunner().invoke(
            lint_main,
            [
                "--no-config",
                "--exclude", "**/*",
                "--format", "json",
                str(path),
            ],
        )
        assert result_json.exit_code == 0, result_json.output
        warnings = runtime_warnings_from_json(result_json.stdout)
        afe = [w for w in warnings if w["category"] == "all_files_excluded"]
        assert len(afe) == 1

    def test_min_severity_relaxed_renders_in_human_stderr(
        self, bad_naming_descriptor_set: Path,
    ) -> None:
        result = CliRunner().invoke(
            lint_main,
            [
                "--no-config",
                "--min-severity", "info",
                str(bad_naming_descriptor_set),
            ],
        )
        assert result.exit_code == 0, result.output
        assert (
            "protokit lint: warning [min_severity_relaxed]:" in result.stderr
        ), result.stderr
        assert "relaxes profile floor" in result.stderr

    def test_rule_exception_renders_in_human_stderr(
        self, bad_naming_descriptor_set: Path,
    ) -> None:
        """Closes the D3-era silent-warning regression: a user pack
        rule that raises now surfaces in ``--format=human`` stderr
        instead of vanishing.
        """
        result = CliRunner().invoke(
            lint_main,
            [
                "--no-config",
                "--rule-pack",
                "tests.schema.lint.cli.user_packs.pack_rule_raises",
                str(bad_naming_descriptor_set),
            ],
        )
        assert result.exit_code == 0, result.output
        assert (
            "protokit lint: warning [rule_exception]:" in result.stderr
        ), result.stderr

    def test_unloaded_rule_renders_in_human_stderr(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``unloaded_rule`` surfaces in ``--format=human`` stderr via the
        same CLI dispatch path as the other three categories.

        Triggering ``unloaded_rule`` from the standard CLI flow requires
        ``profile.rule_ids`` to exceed loaded specs, which the CLI's
        composition pass does not naturally produce (``LintProfile.from_pack``
        only adds rule_ids it just registered). The direct-hook
        ``TestHumanStderrEmissionPerCategory`` coverage proves the
        formatter contract; this test pins the CLI INTEGRATION boundary
        by monkeypatching ``LintEngine.run`` to inject a synthetic report
        that contains an ``unloaded_rule`` warning, then asserting the
        post-format hook fires for that category just like it does for
        the other three.
        """
        from google.protobuf import descriptor_pb2

        from protokit.schema.lint.engine import LintEngine
        from protokit.schema.lint.model import LintReport, LintRuntimeWarning

        fds = descriptor_pb2.FileDescriptorSet()
        fd = fds.file.add()
        fd.name = "api/user.proto"
        fd.syntax = "proto3"
        fd.package = "test"
        path = tmp_path / "test.descriptor_set"
        path.write_bytes(fds.SerializeToString())

        synthetic = LintReport(
            runtime_warnings=(
                LintRuntimeWarning(
                    category="unloaded_rule",
                    rule_id="missing/rule-id",
                    message=(
                        "rule 'missing/rule-id' is named in profile "
                        "'default' but not loaded into the engine"
                    ),
                ),
            ),
        )

        def _fake_run(self: LintEngine, *args: object, **kwargs: object) -> LintReport:
            return synthetic

        monkeypatch.setattr(LintEngine, "run", _fake_run)

        result = CliRunner().invoke(
            lint_main,
            ["--no-config", str(path)],
        )
        assert result.exit_code == 0, result.output
        assert (
            "protokit lint: warning [unloaded_rule]:" in result.stderr
        ), result.stderr
        assert "missing/rule-id" in result.stderr, result.stderr

    def test_quiet_does_not_suppress_runtime_warning_stderr(
        self, tmp_path: Path,
    ) -> None:
        """Per KTD-6: ``--quiet`` suppresses findings on stdout only.
        Runtime warnings on stderr remain visible regardless.
        """
        from google.protobuf import descriptor_pb2

        fds = descriptor_pb2.FileDescriptorSet()
        fd = fds.file.add()
        fd.name = "api/user.proto"
        fd.syntax = "proto3"
        fd.package = "test"
        path = tmp_path / "test.descriptor_set"
        path.write_bytes(fds.SerializeToString())

        result = CliRunner().invoke(
            lint_main,
            [
                "--no-config",
                "--quiet",
                "--exclude", "**/*",
                str(path),
            ],
        )
        assert result.exit_code == 0, result.output
        # Stdout: zero findings (quiet semantics preserved).
        assert result.stdout == ""
        # Stderr: hook still emits warning.
        assert (
            "protokit lint: warning [all_files_excluded]:" in result.stderr
        ), result.stderr

    def test_machine_format_skips_human_hook(
        self, tmp_path: Path,
    ) -> None:
        """``--format=json`` does not produce the ``protokit lint:
        warning [...]:`` stderr envelope — the JSON payload already
        carries the warning. The hook is human-format-only.
        """
        from google.protobuf import descriptor_pb2

        fds = descriptor_pb2.FileDescriptorSet()
        fd = fds.file.add()
        fd.name = "api/user.proto"
        fd.syntax = "proto3"
        fd.package = "test"
        path = tmp_path / "test.descriptor_set"
        path.write_bytes(fds.SerializeToString())

        result = CliRunner().invoke(
            lint_main,
            [
                "--no-config",
                "--exclude", "**/*",
                "--format", "json",
                str(path),
            ],
        )
        assert result.exit_code == 0, result.output
        assert "protokit lint: warning [" not in result.stderr, (
            "Human-format hook leaked into a machine-format run. "
            f"stderr was:\n{result.stderr}"
        )
