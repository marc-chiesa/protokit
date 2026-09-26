"""Pluggable output formatter system for ``protokit``.

Built-in formatters render :class:`protokit.message.DiffResult`,
the schema-side report dataclasses (``CompatibilityReport``,
``HistoryReport``, ``BisectReport``), and (for ``LINT_REPORT``)
:class:`protokit.schema.lint.LintReport` into ``human``, ``json``,
``junit``, and (for compat + lint kinds) ``sarif`` output. User-
supplied formatters register through :func:`register_formatter`
or via the ``--formatter-module`` CLI flag.

Public surface:

- :class:`FormatterKind` — discriminator for the five report
  shapes (``DIFF``, ``COMPAT``, ``COMPAT_HISTORY``,
  ``COMPAT_BISECT``, ``LINT_REPORT``).
- :class:`FormatterContext` — frozen dataclass carrying CLI
  invocation context (subcommand, target type, level, range,
  refs, proto file).
- :func:`register_formatter` / :func:`get_formatter` /
  :func:`list_formatters` — registry primitives.
- :func:`load_formatter_pack` — load a user pack module
  exposing a ``FORMATTERS = [(name, fn, kind), ...]`` list.
- :func:`clear_user_formatters` — test/dev helper that wipes
  non-built-in entries.
- :class:`FormatterError` — raised for duplicate registrations,
  and base class for :class:`ReservedFormatterNameError`, the
  narrower error raised for built-in shadowing.

Built-in names (``human``, ``json``, ``junit``, ``sarif``) are
RESERVED — third-party packs cannot shadow them, by design.
"""

from __future__ import annotations

from protokit.formatters._registry import (
    Formatter,
    FormatterContext,
    FormatterError,
    FormatterKind,
    ReservedFormatterNameError,
    clear_user_formatters,
    get_formatter,
    list_formatters,
    load_formatter_pack,
    register_formatter,
)

#: Root Python ``logging`` namespace recommended for
#: formatter-pack authors. Attach sub-loggers under this
#: namespace (e.g. ``logging.getLogger(f"{FORMATTER_LOG_NAMESPACE}.my_pack")``)
#: so downstream filtering and level control is uniform across
#: packs. Formatter functions themselves must stay pure
#: ``(report, ctx) -> str`` — all diagnostic output from a
#: pack should route through ``logging`` rather than ``print``
#: or ``sys.stdout.write`` (see README "Diagnostics from a
#: custom formatter" section).
FORMATTER_LOG_NAMESPACE: str = "protokit.formatters"

# Ordering within this tuple does not matter. `from protokit.formatters import
# _junit_xml` in a _builtin_* module names a submodule, so on first use the
# import system loads that submodule fresh; it never reads a name this __init__
# has yet to bind. That holds only while no submodule imports this package
# itself: the shared helpers (_junit_xml, _sarif_json, _registry) are leaves,
# and no _builtin_* module has a back-edge either. One that did would see the
# package half-built. test_formatters_package_init_shape_is_present_and_not_a_cycle
# (tests/meta/test_import_layers.py) fails if any submodule gains that import.
from protokit.formatters import (  # noqa: F401, E402
    _builtin_bisect,
    _builtin_compat,
    _builtin_diff,
    _builtin_history,
    _junit_xml,  # noqa: F401, E402
    _sarif_json,  # noqa: F401, E402
)

__all__ = [
    "FORMATTER_LOG_NAMESPACE",
    "Formatter",
    "FormatterContext",
    "FormatterError",
    "FormatterKind",
    "ReservedFormatterNameError",
    "clear_user_formatters",
    "get_formatter",
    "list_formatters",
    "load_formatter_pack",
    "register_formatter",
]
