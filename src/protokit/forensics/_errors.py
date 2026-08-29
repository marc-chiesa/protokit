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

    Raised as soon as a bounded read of ``limit + 1`` bytes comes back full
    (KTD10), so a crafted or accidental huge blob drives neither a large read
    nor the N per-candidate parses.

    Attributes:
        size: The input's size in bytes. Exact only when ``size_is_exact``;
            otherwise a lower bound, because the reported size comes from the
            bounded read rather than ``stat()``.
        size_is_exact: Whether :attr:`size` is the input's true size.
            ``stat().st_size`` is meaningful only for a regular file — it is 0
            for a FIFO, ``/dev/stdin``, or a process substitution, exactly the
            inputs a cap matters most for — so for those the bounded read's
            length is reported instead, and this is ``False``.
    """

    def __init__(
        self, path: Path, size: int, limit: int, *, size_is_exact: bool = True
    ) -> None:
        self.path = path
        self.size = size
        self.limit = limit
        self.size_is_exact = size_is_exact
        measured = f"{size} bytes" if size_is_exact else f"at least {size} bytes"
        super().__init__(
            f"message {path} is {measured}, exceeding --max-message-bytes "
            f"{limit} (raise --max-message-bytes to allow)"
        )


class CandidateSpecError(ForensicsError):
    """A ``--schema LABEL=PATH`` spec is malformed."""
