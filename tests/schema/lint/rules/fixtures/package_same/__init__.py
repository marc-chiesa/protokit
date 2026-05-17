"""Package marker so :mod:`proto_templates` is importable as
``tests.schema.lint.rules.fixtures.package_same.proto_templates``.

The directory also holds the buf v1.69.0 NDJSON snapshots under
``_buf_smoke/recorded/`` (raw fixture data, not Python). The
``__init__.py`` only affects Python-module discovery; it has no
bearing on the .proto / .json file collection used by
:mod:`tests.schema.lint.test_buf_smoke_assumptions` and friends.
"""
