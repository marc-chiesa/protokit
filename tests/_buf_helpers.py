"""Shared buf-binary helpers — used by tests/parity/ and tests/schema/lint/.

Extracted from ``tests/parity/conftest.py:270-369`` so the U4a buf
smoke-test (``tests/schema/lint/test_buf_smoke_assumptions.py``) can
reuse the same BUF_BINARY discovery + 30s-timeout subprocess wrapper
without duplicating the parity harness's Ctrl-C safety.

Two public functions:

- :func:`discover_buf_binary` — resolves the buf binary from
  ``$BUF_BINARY`` then PATH, skipping the test cleanly when unavailable.
- :func:`run_buf_subprocess` — runs ``buf`` with a 30s wall-clock cap
  and triple-arm guard (``KeyboardInterrupt``/``SystemExit``/``Exception``)
  so a hung tool invocation surfaces cleanly to pytest.

The parity conftest's ``buf_binary`` session fixture wraps
:func:`discover_buf_binary` so the parity harness keeps its session-
scoped reuse, and ``run_buf_lint`` routes through
:func:`run_buf_subprocess` for the 30s timeout + triple-arm guard.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import NoReturn

import pytest

from protokit.schema.lint.cli import _BUF_PARITY_PIN


def _fail_subprocess(msg: str) -> NoReturn:
    """``pytest.fail`` typed as ``NoReturn`` for typecheckers."""
    pytest.fail(msg)
    raise AssertionError("unreachable")  # pragma: no cover -- defense vs stub rot


def _stderr_repr(stderr: bytes | str | None) -> str:
    """Render ``TimeoutExpired.stderr`` regardless of bytes/str/None.

    On POSIX, ``subprocess.TimeoutExpired.stderr`` is ``bytes`` even when
    ``subprocess.run`` was called with ``text=True`` (the decode path runs
    only on the normal-exit branch). Normalize to a clean ``str`` repr so
    diagnostic messages don't show ``b'...'`` prefixes.
    """
    if stderr is None or stderr == b"" or stderr == "":
        return "(empty)"
    if isinstance(stderr, bytes):
        return repr(stderr.decode("utf-8", errors="replace"))
    return repr(stderr)


def discover_buf_binary() -> Path:
    """Resolve the buf binary from ``$BUF_BINARY`` then PATH; skip otherwise.

    Returning a ``Path`` makes downstream subprocess invocations clean
    (str-coerced at the boundary). A missing binary triggers
    ``pytest.skip(...)`` so tests are graceful on machines without buf
    installed. ``$BUF_BINARY`` pointing at a non-existent file is a
    misconfiguration, not a missing install, so it fails loudly.

    Tests that depend on buf should call this function at module-import
    time OR inside the test body. For session-scoped reuse (parity
    harness), wrap in a ``@pytest.fixture(scope='session')``.
    """
    env_var = os.environ.get("BUF_BINARY")
    if env_var:
        path = Path(env_var)
        if not path.is_file():
            pytest.fail(
                f"$BUF_BINARY is set to {env_var!r} but the file does not exist. "
                "Set BUF_BINARY to a valid buf executable, or unset it to fall "
                "back to PATH lookup."
            )
        return path
    resolved = shutil.which("buf")
    if resolved is None:
        pytest.skip(
            f"buf binary not found: $BUF_BINARY is unset and `buf` is not on "
            f"PATH. Install buf {_BUF_PARITY_PIN} from "
            f"https://github.com/bufbuild/buf/releases/tag/{_BUF_PARITY_PIN} "
            f"(or set BUF_BINARY to a local install) to run buf-dependent tests."
        )
    return Path(resolved)


def run_buf_subprocess(
    argv: list[str], cwd: Path, label: str,
) -> subprocess.CompletedProcess[str]:
    """Run a buf subprocess with a 30s wall-clock cap and triple-arm guard.

    The triple-arm guard ensures Ctrl-C mid-invocation surfaces cleanly
    to pytest rather than corrupting session state. Errors re-raise as
    pytest failures with the tool's stderr attached for diagnostic
    context.

    Args:
        argv: The subprocess argument vector. ``argv[0]`` should be the
            buf binary path (returned by :func:`discover_buf_binary`).
        cwd: Working directory for the subprocess (typically a fixture
            directory containing ``buf.yaml``).
        label: Short label for diagnostic messages (e.g., ``"buf lint"``).

    Returns:
        ``subprocess.CompletedProcess[str]`` with text-decoded stdout
        and stderr.
    """
    try:
        return subprocess.run(  # noqa: S603 -- argv is constructed in-test, never user input
            argv,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except subprocess.TimeoutExpired as exc:
        _fail_subprocess(
            f"{label} invocation exceeded 30s wall-clock cap "
            f"(cwd={cwd}, argv={argv!r}). stderr so far: {_stderr_repr(exc.stderr)}"
        )
    except KeyboardInterrupt:
        raise
    except SystemExit:
        raise
    except Exception as exc:
        _fail_subprocess(
            f"{label} subprocess raised {type(exc).__name__}: {exc} "
            f"(cwd={cwd}, argv={argv!r})"
        )


# ---- D6b U6 ce:review follow-up: shared smoke-fixture helpers -------------
#
# Moved from tests/schema/lint/test_buf_smoke_assumptions.py to break the
# cross-test-module private-symbol coupling that tests/parity/test_parity_
# package_same.py introduced (MAINT-5 + T-05 ce:review findings, 0.80
# confidence). Both the smoke-drift gate and the parity gate now import
# from this shared module — eliminating the rename-induced ImportError
# brittleness that affected pytest collection.

#: All 22 D6b U4a + D6c U4 buf-smoke fixtures. Each has a fixture
#: directory at
#: ``tests/schema/lint/rules/fixtures/package_same/_buf_smoke/<name>/``
#: and a SHA-pinned recorded snapshot at ``_buf_smoke/recorded/<name>.json``.
#: Order: 7 initial (core architecture) + 7 supplementary (cross-rule,
#: sort, bool render) + 7 deferred-question-resolution (quote escape +
#: mixed-presence per non-go rule) + 1 D6c U4 compound-escape closure.
SMOKE_FIXTURES: tuple[str, ...] = (
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
    # Deferred-question-resolution 7 (quote + mixed-presence per non-go).
    "mixed-value-with-inner-quote",
    "mixed-presence-java-package",
    "mixed-presence-csharp-namespace",
    "mixed-presence-php-namespace",
    "mixed-presence-ruby-package",
    "mixed-presence-swift-prefix",
    "mixed-presence-java-multiple-files",
    # D6c U4: compound-backslash+quote BUF_BINARY closure on R7 escape
    # path. ``a.proto``'s value ``com.foo\"bar`` (one backslash + one
    # quote in the decoded proto string) is the genuine compound case;
    # ``b.proto``'s value ``com.zaz\\qux`` (two decoded backslashes)
    # exercises the doubled-backslash-only path. Together they byte-pin
    # the two-step escape order in
    # :func:`protokit.schema.lint.rules.package_same._escape_message_value`
    # (backslash FIRST then quote) against buf v1.69.0 via a recorded
    # NDJSON snapshot. The U6 inner-quote fixture
    # (``mixed-value-with-inner-quote``) covers the quote-only path;
    # the U4b PHP-namespace fixtures cover the backslash-only path;
    # this entry's ``a.proto`` closes the compound case left open in
    # the escape-pair-aware-truncation 2026-05-17 learning (see
    # ``docs/solutions/logic-errors/`` for the captured post-mortem).
    "compound-backslash-quote",
)


def smoke_root() -> Path:
    """Return the absolute path to ``_buf_smoke/`` regardless of caller cwd.

    The fixture tree lives under ``tests/schema/lint/rules/fixtures/
    package_same/_buf_smoke/`` (frozen by D6b U4a). The path is computed
    once relative to this module's location so callers in
    ``tests/parity/`` and ``tests/schema/lint/`` share the same root.
    """
    return (
        Path(__file__).resolve().parent
        / "schema"
        / "lint"
        / "rules"
        / "fixtures"
        / "package_same"
        / "_buf_smoke"
    )


# ---- D6c U3 — package_directory parity fixtures ---------------------------
#
# Parallel ``PACKAGE_DIRECTORY_SMOKE_FIXTURES`` tuple + ``package_directory_
# smoke_root()`` helper (rather than extending ``SMOKE_FIXTURES``) so the
# R7 family's fixture list stays an independent SSOT — R7's R25 invariants
# at ``tests/parity/test_parity_package_same.py`` are byte-comparison-pinned
# to the existing 21-entry tuple, and conflating the two families would
# create cross-family drift risk. Each family has its own ``_buf_smoke/``
# subtree, its own ``recorded/`` snapshots, and its own assumption-pinning
# test module. The shared helper ``run_buf_subprocess`` covers both.

#: All 10 D6c U3 buf-smoke fixtures for the R8 + R8b parity family. Each
#: has a fixture directory at ``tests/schema/lint/rules/fixtures/
#: package_directory/_buf_smoke/<name>/`` and a SHA-pinned recorded
#: snapshot at ``_buf_smoke/recorded/<name>.json``.
#:
#: Composition (per KTD-10 + Finding #3 addition):
#:   - 5 base: matched-dir, mismatched-dir, split-package-multi-dir,
#:     single-file-dir, proto-root-mixed
#:   - 1 OQ-4: no-package-mixed (multi-declared + packageless — empty-
#:     mixed-multi arm; resolves U2 ce:review Finding #3)
#:   - 3 edge-case discriminators: n3-directories-split,
#:     n3-packages-same-dir, cofire-r8-r8b
#:   - 1 Finding #3 follow-up: single-declared-no-package (empty-mixed-
#:     single arm — 1 declared + N packageless coverage from Phase 0)
PACKAGE_DIRECTORY_SMOKE_FIXTURES: tuple[str, ...] = (
    # 5 base.
    "matched-dir",
    "mismatched-dir",
    "split-package-multi-dir",
    "single-file-dir",
    "proto-root-mixed",
    # 1 OQ-4 sub-question (multi-declared + packageless).
    "no-package-mixed",
    # 3 edge-case discriminators.
    "n3-directories-split",
    "n3-packages-same-dir",
    "cofire-r8-r8b",
    # 1 ce:review Finding #3 follow-up (1-declared + packageless).
    "single-declared-no-package",
)


def package_directory_smoke_root() -> Path:
    """Return the absolute path to the D6c R8/R8b ``_buf_smoke/`` root.

    Parallel to :func:`smoke_root` for the R7 family. The path is
    computed once relative to this module so all callers in
    ``tests/parity/`` and ``tests/schema/lint/`` share the same root.
    """
    return (
        Path(__file__).resolve().parent
        / "schema"
        / "lint"
        / "rules"
        / "fixtures"
        / "package_directory"
        / "_buf_smoke"
    )


# D6e U3 / PACKAGE_NO_IMPORT_CYCLE buf-smoke fixtures. Parallel to
# PACKAGE_DIRECTORY_SMOKE_FIXTURES per the same per-family SSOT
# rationale (independent fixture list, independent recorded snapshots,
# independent assumption-pinning). Each fixture has a directory at
# tests/schema/lint/rules/fixtures/package_no_import_cycle/_buf_smoke/
# <name>/ and a SHA-pinned recorded snapshot at _buf_smoke/recorded/
# <name>.json.
#
# Composition per U3 Phase 0 (2026-05-22):
#   - two_pkg_cycle: 2-package cycle (file-level acyclic, package-level
#     cyclic) — the canonical case the rule targets
#   - three_pkg_cycle: 3-package cycle (3 files emit, one per cycle-
#     closing import edge)
#   - no_cycle_baseline: linear chain, no cycle (zero findings)
#   - leaf_files_in_cyclic_pkg: sibling leaf files in cyclic packages
#     must NOT emit (over-emission guard per ce:review session
#     2026-05-22 user concern)
#   - root_vendor_pkg_cycle: cycle that loops through a vendor package
#     (still per-import-edge emission)
PACKAGE_NO_IMPORT_CYCLE_SMOKE_FIXTURES: tuple[str, ...] = (
    "two_pkg_cycle",
    "three_pkg_cycle",
    "no_cycle_baseline",
    "leaf_files_in_cyclic_pkg",
    "root_vendor_pkg_cycle",
)


def package_no_import_cycle_smoke_root() -> Path:
    """Return the absolute path to the D6e U3 ``_buf_smoke/`` root.

    Parallel to :func:`package_directory_smoke_root` for the D6e U3
    package-import-cycle family.
    """
    return (
        Path(__file__).resolve().parent
        / "schema"
        / "lint"
        / "rules"
        / "fixtures"
        / "package_no_import_cycle"
        / "_buf_smoke"
    )
