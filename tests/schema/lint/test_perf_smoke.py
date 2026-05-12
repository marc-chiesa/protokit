"""Perf smoke for ``protokit lint`` — catastrophic-regression canary.

D5 R22-R24 land this test as a **smoke**, not a benchmark. The
threshold is loose by design: the intent is to fail loudly when a
future change introduces an algorithmic regression (e.g. a quadratic
walker or per-field pool lookup), NOT to track micro-performance
drift. CI runners are noisy; a tight threshold would teach contributors
to ignore the test, which is worse than no test at all.

**Calibration method** (per the D5 plan / R22): generate a synthetic
fixture of 50 files × 20 messages × 10 fields = 10,000 fields, compile
via D1's ``compile_protos_to_result``, then time ``engine.run``. The
threshold is set at roughly ``max_observed × 30`` from local runs
on the developer's machine; CI cells may run faster or slower but
should never approach the threshold on healthy code. An O(n²) walker
regression at 10k fields would land in the multi-second range —
solidly inside the failure envelope.

**Cell predicate** (per the D5 plan / R23b + KTD-3): runs only on
``linux + py3.12``. Other cells skip cleanly via ``@pytest.mark.skipif``.
The companion ``test_perf_smoke_coverage.py`` parses
``.github/workflows/ci.yml`` to verify at least one matrix cell
matches this predicate (fail-closed if py3.12 leaves the matrix
without the skipif being updated).

**Slow marker** (per the D5 plan / R23a): also marked ``@pytest.mark.slow``
so ``pytest -m "not slow"`` skips it during fast-iteration loops.
The ``slow`` marker is registered in ``pyproject.toml``.

**What this test does NOT do**: this is not a benchmark suite. It
does not compare cell-to-cell baselines, track historical trends, or
record per-rule timings. Those are jobs for a dedicated benchmark
delivery; the smoke just keeps the project off the "gradual catastrophic
regression" failure mode.

**Response to a failure**: if this test fails, investigate the root
cause; do NOT widen the threshold by reflex. The smoke's value comes
from being loud-on-regression, not from passing.
"""

from __future__ import annotations

import dataclasses
import sys
import time
from pathlib import Path

import pytest

from protokit.schema.compile import compile_protos_to_result
from protokit.schema.lint.engine import LintEngine
from protokit.schema.lint.model import LintProfile, LintSeverity
from protokit.schema.lint.rules import BUILTIN_PACKS

# Synthetic fixture dimensions (per D5 plan / R22). 50 × 20 × 10 =
# 10,000 fields. Picked to exercise the walker enough that an O(n²)
# regression diverges visibly from O(n) while still completing in
# tens of milliseconds on healthy code.
_PERF_SMOKE_FILES = 50
_PERF_SMOKE_MESSAGES_PER_FILE = 20
_PERF_SMOKE_FIELDS_PER_MESSAGE = 10

# Loose smoke-not-benchmark threshold. See module docstring for the
# calibration story. Local dev (~14ms on Apple Silicon) leaves ~35×
# headroom; CI cells may run slower but should never approach this on
# healthy code. A catastrophic regression at 10k fields would land in
# the multi-second range, solidly inside the failure envelope.
_PERF_SMOKE_THRESHOLD_SECONDS = 0.5


def _generate_proto_source(file_idx: int, n_messages: int, n_fields: int) -> str:
    """Render one synthetic ``.proto`` file's source text.

    Field names use ``snake_case`` so the canonical ``naming``
    rule pack produces zero findings — the smoke times the walker
    cost, not the cost of accumulating findings. A future smoke
    variant could flip to ``camelCase`` field names to time the
    findings-emit path, but the catastrophic-regression canary
    is the walker, so the current shape is deliberate.
    """
    lines: list[str] = [
        'syntax = "proto3";',
        f"package perfsmoke.file{file_idx};",
        "",
    ]
    for m in range(n_messages):
        lines.append(f"message Msg{m} {{")
        for f in range(n_fields):
            lines.append(f"  string field_{f} = {f + 1};")
        lines.append("}")
        lines.append("")
    return "\n".join(lines)


def _generate_synthetic_fixture(tmp_path: Path) -> list[Path]:
    """Write the 50-file synthetic fixture to ``tmp_path`` and return paths."""
    paths: list[Path] = []
    for i in range(_PERF_SMOKE_FILES):
        p = tmp_path / f"file_{i:03d}.proto"
        p.write_text(
            _generate_proto_source(
                file_idx=i,
                n_messages=_PERF_SMOKE_MESSAGES_PER_FILE,
                n_fields=_PERF_SMOKE_FIELDS_PER_MESSAGE,
            ),
        )
        paths.append(p)
    return paths


@pytest.mark.slow
@pytest.mark.skipif(
    sys.platform != "linux" or sys.version_info[:2] != (3, 12),
    reason=(
        "perf smoke runs on linux+py3.12 only (D5 R23b). The companion "
        "test_perf_smoke_coverage.py meta-test asserts the CI matrix "
        "contains at least one cell matching this predicate."
    ),
)
def test_lint_engine_walks_10k_fields_under_smoke_threshold(
    tmp_path: Path,
) -> None:
    """``engine.run`` on 10,000 synthetic fields stays under the smoke threshold.

    Catastrophic-regression canary. See module docstring for the
    calibration approach and the smoke-not-benchmark posture. If this
    fails: investigate the root cause; do NOT widen the threshold by
    reflex.
    """
    proto_paths = _generate_synthetic_fixture(tmp_path)

    compile_result = compile_protos_to_result(
        paths=proto_paths,
        proto_paths=(str(tmp_path),),
    )
    error_diags = [d for d in compile_result.diagnostics if d.level == "error"]
    assert not error_diags, (
        f"synthetic fixture compile produced errors: {error_diags}"
    )
    assert len(compile_result.root_files) == _PERF_SMOKE_FILES, (
        f"expected {_PERF_SMOKE_FILES} root files, got "
        f"{len(compile_result.root_files)}"
    )

    engine = LintEngine()
    for pack in BUILTIN_PACKS:
        engine.load_rule_pack(pack)
    profile = dataclasses.replace(
        LintProfile.from_pack(BUILTIN_PACKS[0], profile_name="default"),
        min_severity=LintSeverity.INFO,
    )

    start = time.perf_counter()
    report = engine.run(compile_result, profile=profile)
    elapsed = time.perf_counter() - start

    # The fixture intentionally uses snake_case field names so the
    # naming rule pack produces zero findings; this asserts the
    # fixture is exercising the walker path (not short-circuiting).
    assert not report.findings, (
        f"smoke fixture should produce zero findings; got {len(report.findings)}"
    )
    # Closes the silent-pass gap on runtime warnings: if any rule
    # raises a rule_exception, or if the profile selects an unloaded
    # rule_id (unloaded_rule), those warnings would otherwise sail
    # through while the canary passes.
    assert not report.runtime_warnings, (
        f"smoke fixture produced unexpected runtime warnings: "
        f"{report.runtime_warnings}"
    )
    # Defends against the canary timing an empty walk if a future
    # refactor accidentally empties profile.rule_ids before the smoke
    # is updated — `assert not report.findings` is satisfied trivially
    # in that case.
    assert report.rules_run, (
        "profile selected zero rules; perf smoke is timing an empty walk"
    )
    assert elapsed < _PERF_SMOKE_THRESHOLD_SECONDS, (
        f"lint engine took {elapsed:.3f}s for "
        f"{_PERF_SMOKE_FILES * _PERF_SMOKE_MESSAGES_PER_FILE * _PERF_SMOKE_FIELDS_PER_MESSAGE} "
        f"fields, exceeding the smoke threshold of "
        f"{_PERF_SMOKE_THRESHOLD_SECONDS}s. This is a catastrophic-regression "
        f"canary — investigate the root cause; do not widen the threshold "
        f"by reflex."
    )
