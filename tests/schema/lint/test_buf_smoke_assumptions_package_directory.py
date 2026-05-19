"""Live-mode buf-smoke regression gate for D6c U3 R8/R8b fixtures.

Parallel to :mod:`tests.schema.lint.test_buf_smoke_assumptions` (which
covers R7's 21 ``package_same/_buf_smoke/`` fixtures) — when
``$BUF_BINARY`` is set, re-invokes ``buf lint --error-format=json``
against each of the 10 D6c R8/R8b smoke fixtures under
``tests/schema/lint/rules/fixtures/package_directory/_buf_smoke/`` and
asserts the live output byte-matches the corresponding
``recorded/*.json`` snapshot. Detects buf-version drift on every CI
parity-job run; gates ``_BUF_PARITY_PIN`` bumps.

When ``$BUF_BINARY`` is unset (typical local dev without buf installed,
or CI runners without the parity job), the test is SKIPPED entirely.
Snapshot integrity is verified independently by
:mod:`tests.schema.lint.test_buf_smoke_recorded_checksums_package_directory`
(which runs by default — no BUF_BINARY dependency).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from tests._buf_helpers import (
    PACKAGE_DIRECTORY_SMOKE_FIXTURES,
    discover_buf_binary,
    package_directory_smoke_root,
    run_buf_subprocess,
)

#: Acceptable buf-lint exit codes for these fixtures. See sibling
#: ``test_buf_smoke_assumptions.py`` for the documented contract:
#:   - 0: buf lint clean (no findings)
#:   - 100: buf lint found violations
#: Anything else (1=error, 2=usage, 127=binary missing) indicates a
#: buf-side failure that would silently produce false-pass via empty
#: stdout fall-through.
_BUF_OK_EXIT_CODES: frozenset[int] = frozenset({0, 100})


def _normalize_buf_output(text: str) -> Iterator[str]:
    """Yield non-empty stripped lines from buf's NDJSON output."""
    for raw in text.splitlines():
        line = raw.strip()
        if line:
            yield line


@pytest.mark.slow
@pytest.mark.parametrize("fixture", PACKAGE_DIRECTORY_SMOKE_FIXTURES)
def test_buf_v1_69_0_matches_recorded_snapshot(fixture: str) -> None:
    """Live buf invocation byte-matches the committed
    ``recorded/<fixture>.json`` snapshot for the D6c R8/R8b family."""
    buf = discover_buf_binary()  # skips if BUF_BINARY unset + buf not on PATH
    smoke_root = package_directory_smoke_root()
    fixture_dir = smoke_root / fixture
    recorded_path = smoke_root / "recorded" / f"{fixture}.json"

    assert fixture_dir.is_dir(), f"smoke fixture missing: {fixture_dir}"
    assert recorded_path.is_file(), (
        f"recorded snapshot missing: {recorded_path}"
    )

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
        f"buf live output diverges from recorded snapshot for "
        f"{fixture!r}.\n"
        f"  Live: {live_lines!r}\n"
        f"  Recorded: {recorded_lines!r}\n"
        f"Buf-version drift suspected — verify _BUF_PARITY_PIN at "
        f"src/protokit/schema/lint/cli.py matches the installed buf "
        f"version (`buf --version`). If the live output is correct "
        f"and the snapshot is stale, regenerate via the same `buf "
        f"lint --error-format=json .` invocation in the fixture dir + "
        f"update CHECKSUMS.sha256 in the same commit."
    )


def test_smoke_fixtures_count() -> None:
    """``PACKAGE_DIRECTORY_SMOKE_FIXTURES`` contains the expected 10 fixtures.

    Pinned-count test rather than freeform list assertion so a future
    fixture addition is a deliberate edit at two sites (the tuple in
    ``tests/_buf_helpers.py`` and this count).
    """
    assert len(PACKAGE_DIRECTORY_SMOKE_FIXTURES) == 10, (
        f"D6c U3 ships 10 smoke fixtures (5 base + 1 OQ-4 + 3 edge-case "
        f"+ 1 Finding #3 follow-up). "
        f"Got {len(PACKAGE_DIRECTORY_SMOKE_FIXTURES)}: "
        f"{PACKAGE_DIRECTORY_SMOKE_FIXTURES!r}"
    )


def test_recorded_dir_matches_fixture_set() -> None:
    """``recorded/`` contains exactly the 10 ``<fixture>.json`` snapshots
    + the ``CHECKSUMS.sha256`` file.

    Bidirectional smoke check — runs without BUF_BINARY since it only
    inspects on-disk files. Catches orphan snapshots, missing snapshots,
    and rename drift.
    """
    smoke_root = package_directory_smoke_root()
    recorded_dir = smoke_root / "recorded"
    json_files = {p.name for p in recorded_dir.glob("*.json")}
    expected_json = {f"{fixture}.json" for fixture in PACKAGE_DIRECTORY_SMOKE_FIXTURES}
    assert json_files == expected_json, (
        f"recorded/ JSON files != expected.\n"
        f"  Only in recorded/: {sorted(json_files - expected_json)!r}\n"
        f"  Only in expected: {sorted(expected_json - json_files)!r}"
    )
    checksums_path = recorded_dir / "CHECKSUMS.sha256"
    assert checksums_path.is_file(), (
        f"CHECKSUMS.sha256 missing at {checksums_path}. Regenerate via "
        f"`shasum -a 256 *.json | sort > CHECKSUMS.sha256` in "
        f"recorded/."
    )
