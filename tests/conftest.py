"""Suite-wide pytest configuration.

Registers the pure-Python known-failure inventory hook (0.16.0 U2, KTD10):
``tests/_pure_python_inventory.py`` applies ``tests/pure_python_expected_failures.txt``
as strict, exception-specific ``xfail`` markers when the suite runs under
``PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python`` and is a no-op under upb.
The hook is a separate module rather than this file's body so its own tests
can load it into a child session by name (a conftest cannot be).
"""

pytest_plugins = ["tests._pure_python_inventory"]
