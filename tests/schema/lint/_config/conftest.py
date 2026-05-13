"""Shared fixtures + helpers for ``tests/schema/lint/_config/`` (D6a U2 ce:review).

The ``_expect_invalid`` helper was previously duplicated verbatim across
``test_schema_validation.py``, ``test_severities.py``, and
``test_no_builtin_rules.py``. Lifted into a conftest fixture so the
error-prefix string and the SystemExit-with-stderr-substring assertion
shape live in one place. Drift on the error prefix (e.g., changing
``error[lint-pyproject-config-invalid]:`` to a new code) now updates
once, not three times.
"""

from __future__ import annotations

import pytest

from protokit.schema.lint._config import ResolvedLintConfig

#: Stable stderr prefix for R3 / R3a / KTD-5 violations. Mirrors the
#: ``error_exit_with_code("pyproject-config-invalid", ...)`` call sites
#: in ``_config.py``. The full prefix shape is documented in U1's loader
#: tests; this constant exists so config-validation tests can assert
#: the same prefix without duplicating the literal string per file.
INVALID_PREFIX: str = "error[lint-pyproject-config-invalid]:"


def expect_invalid(
    table: dict[str, object] | None,
    cli_overrides: dict[str, object],
    capsys: pytest.CaptureFixture[str],
    *,
    substring: str,
) -> None:
    """Assert ``from_dict`` exits 2 with INVALID_PREFIX + the named substring.

    Used by config-validation tests to verify both the structural
    error envelope (exit code + prefix) AND a specific substring of
    the message body. Per the ``source-aware-error-messages``
    learning, callers should pass a substring that names the
    offending key/value/source so the test pins user-actionable
    error content.

    Args:
        table: The pyproject table being validated, or ``None`` to
            simulate "no [tool.protokit.lint] section in file".
        cli_overrides: CLI override dict passed to ``from_dict``.
        capsys: pytest stderr-capture fixture.
        substring: A substring that MUST appear in the error message
            body after the INVALID_PREFIX. Use literal text from the
            relevant ``_coerce_*`` helper's error wording.
    """
    with pytest.raises(SystemExit) as excinfo:
        ResolvedLintConfig.from_dict(table, cli_overrides)
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert err.startswith(INVALID_PREFIX), err
    assert substring in err, err
