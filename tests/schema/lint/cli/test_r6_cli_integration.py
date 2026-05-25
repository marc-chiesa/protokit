"""End-to-end CliRunner tests for D6b U3 R6 rules.

D6b U3 ships:
- 5 R6 deprecated-replacement rules (U3a)
- Lint CLI proto-mode ``include_source_info=True`` flip at
  ``src/protokit/schema/lint/cli.py:731`` (U3a)
- Descriptor-set-mode source-info capture in
  ``_load_descriptor_sets_to_result`` (U3b)

The unit-level + engine-API tests at
``tests/schema/lint/rules/options/test_deprecated_replacement.py`` and
``tests/schema/lint/cli/test_cli_descriptor_set_source_info.py`` cover
the rule logic and loader semantics. This module adds the missing
CliRunner-level integration coverage so a regression reverting the
``cli.py:731`` flip OR breaking the descriptor-set-mode loader
extension is caught at the CLI surface.

Per the D6b U3 /ce:review findings #4 and #12: without these tests,
the proto-mode and descriptor-set-mode CLI behavior changes are only
indirectly verified through unit tests.
"""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner
from google.protobuf import descriptor_pb2

from protokit.schema.compile import compile_protos_to_result
from protokit.schema.lint.cli import main as lint_main

# ---------------------------------------------------------------------------
# Shared proto fixtures
# ---------------------------------------------------------------------------


_PROTO_DEPRECATED_SAD = """\
syntax = "proto3";
package demo;

message User {
    // Legacy field.
    string old_field = 1 [deprecated = true];
}
"""

_PROTO_DEPRECATED_HAPPY = """\
syntax = "proto3";
package demo;

message User {
    // Use new_field instead.
    string old_field = 1 [deprecated = true];
}
"""


def _make_proto(tmp_path: Path, source: str) -> Path:
    """Write source to tmp_path/demo.proto and return the path."""
    p = tmp_path / "demo.proto"
    p.write_text(source)
    return p


def _build_descriptor_set_with_source_info(
    proto_path: Path,
    proto_root: Path,
) -> bytes:
    """Compile with include_source_info=True and serialize the source-bearing
    FileDescriptorProto objects so the resulting bytes preserve source_code_info.
    """
    result = compile_protos_to_result(
        paths=[proto_path],
        proto_paths=(str(proto_root),),
        include_source_info=True,
    )
    assert result.source_info_descriptors is not None
    fds = descriptor_pb2.FileDescriptorSet()
    for fd_proto in result.source_info_descriptors.values():
        fds.file.add().CopyFrom(fd_proto)
    return fds.SerializeToString()


# ---------------------------------------------------------------------------
# Proto-mode CLI integration — verifies cli.py:731 include_source_info flip
# ---------------------------------------------------------------------------


class TestProtoModeR6:
    """``protokit lint --proto`` fires R6 rules end-to-end."""

    def test_proto_mode_fires_r6_field_finding(
        self, tmp_path: Path,
    ) -> None:
        """The cli.py:731 include_source_info=True flip is load-bearing
        for R6. If a future change accidentally drops the kwarg, R6 will
        silently over-report for every deprecated element (per K-9). This
        test exercises the full --proto path and asserts the EXPECTED
        finding count for the SAD fixture (1 finding).
        """
        proto = _make_proto(tmp_path, _PROTO_DEPRECATED_SAD)
        result = CliRunner().invoke(
            lint_main,
            [
                "--proto",
                str(proto),
                "-I",
                str(tmp_path),
                "--profile",
                "default",
                "--format",
                "json",
                "--min-severity",
                "warning",
            ],
        )
        # Post-D6f R6 promotion: ERROR-severity finding present →
        # exit code 1 unconditionally (has_error=True short-circuits).
        assert result.exit_code == 1, result.output
        payload = json.loads(result.stdout)
        r6_findings = [
            f for f in payload["findings"]
            if f["rule_id"].startswith("options/deprecated-")
        ]
        assert len(r6_findings) == 1, (
            f"expected 1 R6 finding, got {len(r6_findings)}: "
            f"{[f['rule_id'] for f in r6_findings]}"
        )
        assert (
            r6_findings[0]["rule_id"]
            == "options/deprecated-field-must-have-replacement-comment"
        )
        assert r6_findings[0]["severity"] == "error"

    def test_proto_mode_happy_path_no_r6_findings(
        self, tmp_path: Path,
    ) -> None:
        """When the proto has a matching replacement comment, the R6
        rule is silent. Without the cli.py:731 flip, this test would
        produce a finding instead (regression signal)."""
        proto = _make_proto(tmp_path, _PROTO_DEPRECATED_HAPPY)
        result = CliRunner().invoke(
            lint_main,
            [
                "--proto",
                str(proto),
                "-I",
                str(tmp_path),
                "--profile",
                "default",
                "--format",
                "json",
            ],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        r6_findings = [
            f for f in payload["findings"]
            if f["rule_id"].startswith("options/deprecated-")
        ]
        assert len(r6_findings) == 0

    def test_recommended_profile_silent_on_r6(
        self, tmp_path: Path,
    ) -> None:
        """R6 ships in default-only; recommended must not fire any R6."""
        proto = _make_proto(tmp_path, _PROTO_DEPRECATED_SAD)
        result = CliRunner().invoke(
            lint_main,
            [
                "--proto",
                str(proto),
                "-I",
                str(tmp_path),
                "--profile",
                "recommended",
                "--format",
                "json",
            ],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        r6_findings = [
            f for f in payload["findings"]
            if f["rule_id"].startswith("options/deprecated-")
        ]
        assert len(r6_findings) == 0


# ---------------------------------------------------------------------------
# Descriptor-set-mode CLI integration — verifies U3b loader extension
# ---------------------------------------------------------------------------


class TestDescriptorSetModeR6:
    """``protokit lint <descriptor-set.pbset>`` fires R6 rules end-to-end."""

    def test_descriptor_set_with_source_info_fires_r6(
        self, tmp_path: Path,
    ) -> None:
        """A descriptor set built with --include_source_info → R6
        rules fire identically to proto-mode."""
        proto = _make_proto(tmp_path, _PROTO_DEPRECATED_SAD)
        pbset = tmp_path / "demo.pbset"
        pbset.write_bytes(
            _build_descriptor_set_with_source_info(proto, tmp_path),
        )

        result = CliRunner().invoke(
            lint_main,
            [
                str(pbset),
                "--profile",
                "default",
                "--format",
                "json",
                "--min-severity",
                "warning",
            ],
        )
        # Post-D6f R6 promotion: descriptor-set-mode also surfaces an
        # ERROR-severity finding → exit code 1.
        assert result.exit_code == 1, result.output
        payload = json.loads(result.stdout)
        r6_findings = [
            f for f in payload["findings"]
            if f["rule_id"].startswith("options/deprecated-")
        ]
        assert len(r6_findings) == 1
        assert (
            r6_findings[0]["rule_id"]
            == "options/deprecated-field-must-have-replacement-comment"
        )
        assert r6_findings[0]["severity"] == "error"

    def test_descriptor_set_with_source_info_happy_path(
        self, tmp_path: Path,
    ) -> None:
        """A descriptor set with the matching comment produces zero R6."""
        proto = _make_proto(tmp_path, _PROTO_DEPRECATED_HAPPY)
        pbset = tmp_path / "demo.pbset"
        pbset.write_bytes(
            _build_descriptor_set_with_source_info(proto, tmp_path),
        )

        result = CliRunner().invoke(
            lint_main,
            [
                str(pbset),
                "--profile",
                "default",
                "--format",
                "json",
            ],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        r6_findings = [
            f for f in payload["findings"]
            if f["rule_id"].startswith("options/deprecated-")
        ]
        assert len(r6_findings) == 0

    def test_descriptor_set_fires_r6_at_error_without_max_warnings_post_promotion(
        self, tmp_path: Path,
    ) -> None:
        """D6f U1 — descriptor-set mode mirrors proto-mode exit-code regression.

        Mirrors ``test_cli_ci_gating.py::TestR6PromotionExitCodeRegression
        ::test_max_warnings_unset_post_promotion_exits_1`` but exercises
        the descriptor-set input path instead of ``--proto`` mode. The
        proto-mode posture-1 test pinned the silent-CI-pass regression
        risk at one entry point; this companion pins the same contract
        at the other.

        Without this test, a regression that broke the has_error short-
        circuit ONLY along the descriptor-set code path (e.g., a future
        refactor of the loader-to-engine handoff) would slip past
        proto-mode coverage. The ce:review testing reviewer flagged the
        gap (run 20260524-232840-29bb63be).
        """
        proto = _make_proto(tmp_path, _PROTO_DEPRECATED_SAD)
        pbset = tmp_path / "demo.pbset"
        pbset.write_bytes(
            _build_descriptor_set_with_source_info(proto, tmp_path),
        )
        result = CliRunner().invoke(
            lint_main,
            [
                str(pbset),
                "--profile",
                "default",
                "--format",
                "json",
            ],
            catch_exceptions=False,
        )
        assert result.exit_code == 1, (
            f"D6f R6 promotion (descriptor-set mode): --max-warnings-"
            f"unset with an R6 finding must exit 1 post-promotion "
            f"(was 0 pre-D6f). Got exit={result.exit_code}; "
            f"output={result.output!r}"
        )
        payload = json.loads(result.stdout)
        r6 = [
            f for f in payload["findings"]
            if f["rule_id"].startswith("options/deprecated-")
        ]
        assert len(r6) == 1, r6
        assert r6[0]["severity"] == "error", (
            f"D6f R6 promotion: descriptor-set-mode finding severity "
            f"must be 'error'; got {r6[0]['severity']!r}"
        )
