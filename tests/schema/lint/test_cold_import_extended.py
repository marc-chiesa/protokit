"""Pytest-runnable parallel to the CI YAML cold-import smoke step.

D1 set up an inline ``python -c "..."`` block in
``.github/workflows/ci.yml`` that asserts ``import protokit.schema``
does not transitively load ``protokit.schema.lint.*`` or
``protokit.schema.compile``. U2 adds ``protokit.schema.lint.cli``
and ``protokit.formatters._builtin_lint`` as new modules that
must also be excluded — but the YAML edit lands in U5 to keep the
CI gate change centralized with the rest of U5's gate work.

This pytest test gives local feedback before push (and before CI
catches a regression). The CI YAML extension is the authoritative
gate; this test mirrors its assertion in a developer-loop-friendly
form. Run via ``pytest tests/schema/lint/test_cold_import_extended.py``
or as part of the full suite.

The assertion runs in a subprocess to avoid pollution from other
tests that may have already imported the lint subpackage in the
parent test process.
"""

from __future__ import annotations

import subprocess
import sys


def test_import_protokit_schema_does_not_load_lint_cli_or_builtin_lint() -> None:
    """KD-10 invariant 2 — checked in a fresh interpreter."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import protokit.schema\n"
                "import sys\n"
                "forbidden = sorted(\n"
                "    k for k in sys.modules\n"
                "    if 'protokit.schema.lint.cli' in k\n"
                "    or k == 'protokit.formatters._builtin_lint'\n"
                ")\n"
                "assert not forbidden, "
                "f'cold-import contract broken: {forbidden}'\n"
                "print('cold-import OK')\n"
            ),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"stderr: {result.stderr}\nstdout: {result.stdout}"
    )
    assert "cold-import OK" in result.stdout


def test_import_protokit_schema_preserves_d1_baseline() -> None:
    """Mirror the D1 CI YAML smoke step assertion exactly.

    The existing CI YAML check substring-matches
    ``'protokit.schema.lint' in k`` (which transitively covers
    ``lint.cli``) and ``k == 'protokit.schema.compile'``. This
    pytest test mirrors that same assertion so the two gates
    stay in lockstep.
    """
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import protokit.schema\n"
                "import sys\n"
                "eager = sorted(\n"
                "    k for k in sys.modules\n"
                "    if 'protokit.schema.lint' in k\n"
                "    or k == 'protokit.schema.compile'\n"
                ")\n"
                "assert not eager, "
                "f'lazy-load contract broken: {eager}'\n"
                "print('cold-import OK')\n"
            ),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"stderr: {result.stderr}\nstdout: {result.stdout}"
    )
    assert "cold-import OK" in result.stdout
