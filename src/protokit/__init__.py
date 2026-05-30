"""protokit — protobuf message and schema tools.

The package is split into three cohesive subpackages:

- ``protokit.message`` — runtime message comparison
  (``MessageDifferencer``, ``diff_messages``, the ``protokit diff`` CLI, the
  pytest assertion hook).
- ``protokit.schema`` — descriptor-level schema compatibility
  checking (``SchemaChecker``, ``check_compatibility``, built-in rules,
  the ``protokit compat`` CLI with ``check`` / ``history`` /
  ``bisect`` / ``ci`` subcommands).
- ``protokit.storage`` — schema-aware scan/filter engine for protobuf
  data at rest (``scan``, ``Source``, ``StreamRegistry``, the reference
  frame adapters in ``protokit.storage.sources``).

Import directly from those subpackages — there are intentionally no
top-level re-exports, to keep the namespace explicit.
"""
