"""Typed forensics exceptions.

Every forensics error subclasses :class:`protokit.storage.StorageError` so the
CLI's typed-error contract catches them and translates to exit 2 — never a bare
traceback or a ``SystemExit`` escaping the library layer.
"""

from __future__ import annotations

from pathlib import Path

from protokit.storage import StorageError


class ForensicsError(StorageError):
    """Base for forensics-specific errors."""


class MessageTooLargeError(ForensicsError):
    """The input message exceeds the configured ``--max-message-bytes`` cap.

    Raised before the file is read or parsed (KTD10) so a crafted or accidental
    huge blob cannot drive a large read or the N per-candidate parses.
    """

    def __init__(self, path: Path, size: int, limit: int) -> None:
        self.path = path
        self.size = size
        self.limit = limit
        super().__init__(
            f"message {path} is {size} bytes, exceeding --max-message-bytes "
            f"{limit} (raise --max-message-bytes to allow)"
        )


class CandidateSpecError(ForensicsError):
    """A ``--schema LABEL=PATH`` spec is malformed."""
