"""Live-mode buf-smoke regression gate — D6b U4a.

When ``$BUF_BINARY`` is set, re-invokes ``buf lint --error-format=json``
against each of the 21 smoke fixtures under
``tests/schema/lint/rules/fixtures/package_same/_buf_smoke/`` and asserts
the live output byte-matches the corresponding ``recorded/*.json``
snapshot. Detects buf-version drift on every CI parity-job run; gates
``_BUF_PARITY_PIN`` bumps.

When ``$BUF_BINARY`` is unset (typical local dev without buf installed,
or CI runners without the parity job), the test is SKIPPED entirely.
Snapshot integrity is verified independently by
``test_buf_smoke_recorded_checksums.py`` (which runs by default — no
BUF_BINARY dependency).

The dropped "snapshot-consistency mode" from earlier plan iterations
was tautological: asserting that committed snapshots encode what the
plan claims they encode adds no information beyond what the SHA-256
checksum test catches. Architectural assumptions are independently
verified in ``test_engine_pre_walk.py`` (accumulator construction +
structural pin) and ``tests/schema/lint/rules/test_package_same.py``
(emit-shape tests in U4b).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from tests._buf_helpers import discover_buf_binary, run_buf_subprocess

# ce:review follow-up (Finding #12 / subprocess-exit-code-validation-
# test-harness-2026-05-13): module-level constant rather than inline
# tuple, so the contract is verifiable in one place and downstream test
# additions cannot silently drift the accepted set.
# - 0: buf lint clean (no findings)
# - 100: buf lint found violations
# Anything else (1=error, 2=usage, 127=binary missing) indicates a
# buf-side failure that would silently produce false-pass via empty
# stdout fall-through.
_BUF_OK_EXIT_CODES: frozenset[int] = frozenset({0, 100})

# All 21 smoke fixtures under _buf_smoke/. Each has a corresponding
# recorded/<name>.json snapshot.
_SMOKE_FIXTURES: tuple[str, ...] = (
    # Initial 7 (core architecture).
    "all-agree",
    "mixed-value",
    "mixed-presence",
    "empty-package-mixed",
    "wkt-only",
    "googleapis-import",
    "wkt-conflict",
    # Supplementary 7 (cross-rule + sort + bool).
    "mixed-value-java-package",
    "mixed-value-csharp-namespace",
    "mixed-value-php-namespace",
    "mixed-value-ruby-package",
    "mixed-value-swift-prefix",
    "mixed-value-java-multiple-files",
    "reverse-order-go",
    # Deferred-question-resolution 7 (quote-character + mixed-presence per non-go).
    "mixed-value-with-inner-quote",
    "mixed-presence-java-package",
    "mixed-presence-csharp-namespace",
    "mixed-presence-php-namespace",
    "mixed-presence-ruby-package",
    "mixed-presence-swift-prefix",
    "mixed-presence-java-multiple-files",
)


def _smoke_root() -> Path:
    return (
        Path(__file__).resolve().parent
        / "rules"
        / "fixtures"
        / "package_same"
        / "_buf_smoke"
    )


def _normalize_buf_output(text: str) -> Iterator[str]:
    """Yield non-empty stripped lines from buf's NDJSON output."""
    for raw in text.splitlines():
        line = raw.strip()
        if line:
            yield line


@pytest.mark.slow
@pytest.mark.parametrize("fixture", _SMOKE_FIXTURES)
def test_buf_v1_69_0_matches_recorded_snapshot(fixture: str) -> None:
    """Live buf invocation byte-matches the committed ``recorded/<fixture>.json``."""
    buf = discover_buf_binary()  # skips if BUF_BINARY unset + buf not on PATH
    smoke_root = _smoke_root()
    fixture_dir = smoke_root / fixture
    recorded_path = smoke_root / "recorded" / f"{fixture}.json"

    assert fixture_dir.is_dir(), f"smoke fixture missing: {fixture_dir}"
    assert recorded_path.is_file(), f"recorded snapshot missing: {recorded_path}"

    result = run_buf_subprocess(
        [str(buf), "lint", "--error-format=json", "."],
        cwd=fixture_dir,
        label=f"buf lint ({fixture})",
    )
    if result.returncode not in _BUF_OK_EXIT_CODES:
        pytest.fail(
            f"buf lint exited {result.returncode} on {fixture} "
            f"(expected one of {sorted(_BUF_OK_EXIT_CODES)}). "
            f"stderr: {result.stderr!r}, stdout: {result.stdout!r}"
        )

    recorded_text = recorded_path.read_text()
    live_lines = sorted(_normalize_buf_output(result.stdout))
    recorded_lines = sorted(_normalize_buf_output(recorded_text))

    assert live_lines == recorded_lines, (
        f"buf v1.69.0 output for fixture {fixture!r} diverged from "
        f"recorded snapshot at {recorded_path}. If buf's emit-shape "
        f"intentionally changed, regenerate snapshots via "
        f"'cd {fixture_dir} && buf lint --error-format=json . > "
        f"{recorded_path}' and audit the diff. If unintentional, "
        f"investigate _BUF_PARITY_PIN drift."
    )
