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

#: All 21 D6b U4a buf-smoke fixtures. Each has a fixture directory at
#: ``tests/schema/lint/rules/fixtures/package_same/_buf_smoke/<name>/``
#: and a SHA-pinned recorded snapshot at ``_buf_smoke/recorded/<name>.json``.
#: Order: 7 initial (core architecture) + 7 supplementary (cross-rule,
#: sort, bool render) + 7 deferred-question-resolution (quote escape +
#: mixed-presence per non-go rule).
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
