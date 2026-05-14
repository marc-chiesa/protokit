"""Drift guard: ``_BUF_PARITY_PIN`` in ``cli.py`` matches the buf
URL pinned in ``.github/workflows/ci.yml``.

The buf-parity infrastructure has two pin sites:

- ``src/protokit/schema/lint/cli.py`` —
  ``_BUF_PARITY_PIN: str = "v<VERSION>"``. Consumed at runtime by
  the release watcher's grep, and (Unit 9, deferred) by
  ``protokit lint --version`` output.
- ``.github/workflows/ci.yml`` — the parity job's curl URL
  ``releases/download/v<VERSION>/buf-Linux-x86_64.tar.gz``.
  Consumed at CI time by the parity job's binary-install step.

Bumping one without the other is a silent class of break: the
release watcher reports "behind upstream" via one version while
CI exercises a different version, with the rule-id mapping and
fixture expectations potentially drifting between them. This
test runs in the default ``pytest tests/`` invocation (no buf
required) so the drift fails locally before push, in CI's `test`
job before the parity job runs, and via the release-watcher
workflow before any pin bump lands.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CLI_PY = _REPO_ROOT / "src" / "protokit" / "schema" / "lint" / "cli.py"
_CI_YAML = _REPO_ROOT / ".github" / "workflows" / "ci.yml"

#: Captures the version string from
#: ``_BUF_PARITY_PIN: str = "v1.69.0"`` (with whitespace tolerance).
_CLI_PIN_RE = re.compile(
    r'^_BUF_PARITY_PIN\s*:\s*str\s*=\s*"(v[^"]+)"',
    re.MULTILINE,
)

#: Captures the version string from the parity job's curl URL,
#: e.g. ``releases/download/v1.69.0/buf-Linux-x86_64.tar.gz``.
_CI_PIN_RE = re.compile(
    r"releases/download/(v[^/]+)/buf-Linux-x86_64\.tar\.gz",
)


def _extract_cli_pin() -> str:
    text = _CLI_PY.read_text(encoding="utf-8")
    match = _CLI_PIN_RE.search(text)
    if not match:
        pytest.fail(
            f"could not extract _BUF_PARITY_PIN from {_CLI_PY} "
            f"(regex {_CLI_PIN_RE.pattern!r} found no match). "
            f"If the constant was reformatted, update the regex in "
            f"this test to match the new line shape — DO NOT just "
            f"remove the test. The constant exists to be the single "
            f"source of truth for the parity CI job's buf version pin."
        )
    return match.group(1)


def _extract_ci_pin() -> str:
    if not _CI_YAML.is_file():
        pytest.fail(
            f"could not read {_CI_YAML} (parity job not yet wired into "
            f"CI?). The drift-check test exists to enforce the link "
            f"between _BUF_PARITY_PIN in cli.py and the curl URL in "
            f"the parity job. If the parity job has been removed, "
            f"delete this test and the _BUF_PARITY_PIN constant in "
            f"the same commit."
        )
    text = _CI_YAML.read_text(encoding="utf-8")
    matches = _CI_PIN_RE.findall(text)
    if not matches:
        pytest.fail(
            f"could not extract buf parity pin from {_CI_YAML} "
            f"(regex {_CI_PIN_RE.pattern!r} found no match). The parity "
            f"job's curl URL must follow the form "
            f"``releases/download/v<X>/buf-Linux-x86_64.tar.gz``. "
            f"If the asset name format changed (e.g., buf moved off "
            f"the capital-L convention), update this regex AND the "
            f"sha256.txt grep filter in the parity job in the same commit."
        )
    unique = set(matches)
    if len(unique) > 1:
        pytest.fail(
            f"{_CI_YAML} contains multiple distinct buf version pins: "
            f"{sorted(unique)!r}. The parity job must reference a single "
            f"version (the tarball URL and the sha256.txt URL should "
            f"use the same v<X>); reconcile before landing."
        )
    return matches[0]


class TestBufParityPinDrift:
    """Pin _BUF_PARITY_PIN (cli.py) and the parity job's curl URL together."""

    def test_constant_and_yaml_reference_same_buf_version(self) -> None:
        """Bumping one without the other is the failure this test prevents.

        If this test fails, the fix is to update both files to the
        same version string in the SAME commit. Do not silence the
        test by suppressing one side — that defeats the entire
        purpose of the drift guard.
        """
        cli_pin = _extract_cli_pin()
        ci_pin = _extract_ci_pin()
        assert cli_pin == ci_pin, (
            f"buf parity pin drift detected: "
            f"_BUF_PARITY_PIN in {_CLI_PY} = {cli_pin!r}; "
            f"releases/download/<X>/buf-Linux-x86_64.tar.gz in "
            f"{_CI_YAML} = {ci_pin!r}. Update both to the same "
            f"version in one commit (and refresh fixtures if buf "
            f"deprecated / renamed any BASIC rule between versions)."
        )
