"""Pluggable output formatter system for ``protokit``.

Built-in formatters render :class:`protokit.message.DiffResult` and
the schema-side report dataclasses (``CompatibilityReport``,
``HistoryReport``, ``BisectReport``) into ``human``, ``json``,
``junit``, and (for compat kinds) ``sarif`` output. User-supplied
formatters register through :func:`register_formatter` or via the
``--formatter-module`` CLI flag.

Public surface:

- :class:`FormatterKind` — discriminator for the four report
  shapes (``DIFF``, ``COMPAT``, ``COMPAT_HISTORY``,
  ``COMPAT_BISECT``).
- :class:`FormatterContext` — frozen dataclass carrying CLI
  invocation context (subcommand, target type, level, range,
  refs, proto file).
- :func:`register_formatter` / :func:`get_formatter` /
  :func:`list_formatters` — registry primitives.
- :func:`load_formatter_pack` — load a user pack module
  exposing a ``FORMATTERS = [(name, fn, kind), ...]`` list.
- :func:`clear_user_formatters` — test/dev helper that wipes
  non-built-in entries.
- :class:`FormatterError` — raised for built-in shadowing and
  duplicate registrations.

Built-in names (``human``, ``json``, ``junit``, ``sarif``) are
RESERVED — third-party packs cannot shadow them, by design.
"""

from __future__ import annotations

from protokit.formatters._registry import (
    Formatter,
    FormatterContext,
    FormatterError,
    FormatterKind,
    clear_user_formatters,
    get_formatter,
    list_formatters,
    load_formatter_pack,
    register_formatter,
)

__all__ = [
    "Formatter",
    "FormatterContext",
    "FormatterError",
    "FormatterKind",
    "clear_user_formatters",
    "get_formatter",
    "list_formatters",
    "load_formatter_pack",
    "register_formatter",
]
