"""For tests that need a schema whose editions features the runtime applies.

protobuf 4.25, the oldest line protokit supports, loads an editions file and
reads every feature in it as unset; protokit's loaders refuse such a file
there (``_pools.EditionsNotImplementedError``). A test that builds an editions
schema by hand calls :func:`requires_editions` where it builds it, so on that
line it is skipped at the point of need instead of failing on a schema the
runtime misread. ``tests/core/test_pools.py`` holds the answer to the installed
version, so a probe that went wrong cannot quietly skip these everywhere.
"""

from __future__ import annotations

import pytest

from protokit import _pools


def requires_editions() -> None:
    """Skip the calling test on a protobuf runtime that does not implement editions."""
    if not _pools._implements_editions():
        pytest.skip("this protobuf runtime does not implement editions (5.26 and later do)")
