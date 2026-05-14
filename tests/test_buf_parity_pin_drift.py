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
from typing import NoReturn

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CLI_PY = _REPO_ROOT / "src" / "protokit" / "schema" / "lint" / "cli.py"
_CI_YAML = _REPO_ROOT / ".github" / "workflows" / "ci.yml"

#: Captures the version string from
#: ``_BUF_PARITY_PIN: <ANNOTATION> = "v1.69.0"``.
#: The annotation segment uses ``[^=]+`` so the regex tolerates any
#: shape between ``:`` and ``=`` (``str``, ``Final[str]``, etc.) —
#: the constant's annotation is incidental to the pin discipline, and
#: anchoring on the literal token ``str`` would silently break this
#: test (and the matching bash grep in buf-release-watch.yml) on a
#: future contributor's hardening pass. The ``v`` prefix on the
#: quoted value is the load-bearing anchor: it pins the format
#: against typos like ``"1.69.0"`` that would otherwise pass an
#: equality check against the CI YAML.
_CLI_PIN_RE = re.compile(
    r'^_BUF_PARITY_PIN\s*:[^=]+=\s*"(v[^"]+)"',
    re.MULTILINE,
)

#: Captures the version string from the parity job's tarball URL,
#: e.g. ``releases/download/v1.69.0/buf-Linux-x86_64.tar.gz``.
_CI_PIN_RE = re.compile(
    r"releases/download/(v[^/]+)/buf-Linux-x86_64\.tar\.gz",
)

#: Captures the version string from the parity job's sha256 URL,
#: e.g. ``releases/download/v1.69.0/sha256.txt``. A partial bump that
#: updates the tarball URL but leaves this URL unchanged would
#: otherwise pass the tarball-only drift check and only fail at CI
#: runtime with a confusing checksum mismatch.
_CI_SHA256_RE = re.compile(
    r"releases/download/(v[^/]+)/sha256\.txt",
)


def _fail(msg: str) -> NoReturn:
    """``pytest.fail`` typed as ``NoReturn`` so callers don't depend
    on pytest's stub annotation for the unreachable-fallthrough contract.

    Mirrors the ``_fail_subprocess`` pattern at
    ``tests/parity/conftest.py:313-317`` so the two
    parity-infrastructure modules use the same idiom.
    """
    pytest.fail(msg)
    raise AssertionError("unreachable")  # pragma: no cover -- defense vs stub rot


def _extract_cli_pin() -> str:
    text = _CLI_PY.read_text(encoding="utf-8")
    match = _CLI_PIN_RE.search(text)
    if not match:
        _fail(
            f"could not extract _BUF_PARITY_PIN from {_CLI_PY} "
            f"(regex {_CLI_PIN_RE.pattern!r} found no match). "
            f"If the constant was reformatted, update the regex in "
            f"this test to match the new line shape — DO NOT just "
            f"remove the test. The constant exists to be the single "
            f"source of truth for the parity CI job's buf version pin."
        )
    return match.group(1)


def _extract_ci_pins() -> tuple[str, str]:
    """Return ``(tarball_version, sha256_version)`` from ci.yml.

    Both URLs MUST reference the same version — a partial bump where
    the tarball URL says v1.70.0 but the sha256.txt URL still says
    v1.69.0 would silently pass the tarball-only drift check while
    failing at CI runtime with a misleading hash mismatch.
    """
    if not _CI_YAML.is_file():
        _fail(
            f"could not read {_CI_YAML} (parity job not yet wired into "
            f"CI?). The drift-check test exists to enforce the link "
            f"between _BUF_PARITY_PIN in cli.py and the curl URLs in "
            f"the parity job. If the parity job has been removed, "
            f"delete this test and the _BUF_PARITY_PIN constant in "
            f"the same commit."
        )
    text = _CI_YAML.read_text(encoding="utf-8")
    tarball_matches = _CI_PIN_RE.findall(text)
    sha256_matches = _CI_SHA256_RE.findall(text)
    if not tarball_matches:
        _fail(
            f"could not extract buf parity pin from {_CI_YAML} "
            f"(regex {_CI_PIN_RE.pattern!r} found no match). The parity "
            f"job's curl URL must follow the form "
            f"``releases/download/v<X>/buf-Linux-x86_64.tar.gz``. "
            f"If the asset name format changed (e.g., buf moved off "
            f"the capital-L convention), update both regexes in this "
            f"file AND the sha256.txt grep filter in the parity job."
        )
    if not sha256_matches:
        _fail(
            f"could not extract buf sha256 URL from {_CI_YAML} "
            f"(regex {_CI_SHA256_RE.pattern!r} found no match). The "
            f"parity job's checksum URL must follow the form "
            f"``releases/download/v<X>/sha256.txt``."
        )
    tarball_unique = set(tarball_matches)
    sha256_unique = set(sha256_matches)
    if len(tarball_unique) > 1:
        _fail(
            f"{_CI_YAML} contains multiple distinct tarball pin versions: "
            f"{sorted(tarball_unique)!r}. The parity job must reference a "
            f"single version; reconcile before landing."
        )
    if len(sha256_unique) > 1:
        _fail(
            f"{_CI_YAML} contains multiple distinct sha256.txt pin versions: "
            f"{sorted(sha256_unique)!r}. The parity job must reference a "
            f"single version; reconcile before landing."
        )
    return tarball_matches[0], sha256_matches[0]


class TestBufParityPinDrift:
    """Pin _BUF_PARITY_PIN (cli.py), parity job's tarball URL, and
    parity job's sha256.txt URL together."""

    def test_constant_and_yaml_reference_same_buf_version(self) -> None:
        """Bumping one without the others is the failure this test prevents.

        If this test fails, the fix is to update every site to the
        same version string in the SAME commit. Do not silence the
        test by suppressing one side — that defeats the entire
        purpose of the drift guard.

        Three pin sites are checked:
        - `_BUF_PARITY_PIN` constant in `cli.py`
        - tarball curl URL in `ci.yml` (``releases/download/<X>/buf-Linux-x86_64.tar.gz``)
        - sha256.txt curl URL in `ci.yml` (``releases/download/<X>/sha256.txt``)
        """
        cli_pin = _extract_cli_pin()
        ci_tarball_pin, ci_sha256_pin = _extract_ci_pins()
        assert cli_pin == ci_tarball_pin == ci_sha256_pin, (
            f"buf parity pin drift detected: "
            f"_BUF_PARITY_PIN in {_CLI_PY} = {cli_pin!r}; "
            f"tarball URL in {_CI_YAML} = {ci_tarball_pin!r}; "
            f"sha256.txt URL in {_CI_YAML} = {ci_sha256_pin!r}. "
            f"Update every site to the same version in one commit "
            f"(and refresh fixtures if buf deprecated / renamed any "
            f"BASIC rule between versions)."
        )
