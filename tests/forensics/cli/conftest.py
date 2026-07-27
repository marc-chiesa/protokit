"""Shared fixtures for ``protokit forensics`` CLI tests.

The CLI is invoked through the top-level group (``protokit.cli.main``) with
``catch_exceptions=False`` so a crash surfaces as a real exception rather than a
masked ``exit_code=1``. Candidate schemas are written as ``.desc``
``FileDescriptorSet`` files so the CLI path needs no compiler backend.
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()
