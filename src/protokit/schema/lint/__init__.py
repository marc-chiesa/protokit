"""Lint subpackage for protokit schema.

The lazy-import contract for ``protokit.schema`` (no eager import of
``lint`` or ``compile``) is enforced by ``protokit.schema.__init__``
NOT importing this package, and validated by the cold-import smoke
step in ``.github/workflows/ci.yml``.
"""

from __future__ import annotations
