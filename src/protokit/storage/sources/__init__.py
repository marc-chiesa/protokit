"""Reference ``Source`` adapters for :func:`protokit.storage.scan`.

These are *examples* of the adapter boundary, not protokit's framing taxonomy:

- :func:`length_delimited` — the file default (varint-prefixed frames).
- :func:`per_message_view` — the pybind11 reference (per-message ``memoryview``).

Users are expected to write their own ``Source`` for any other storage layout.
"""

from __future__ import annotations

from protokit.storage.sources.length_delimited import length_delimited
from protokit.storage.sources.per_message_view import per_message_view

__all__ = [
    "length_delimited",
    "per_message_view",
]
