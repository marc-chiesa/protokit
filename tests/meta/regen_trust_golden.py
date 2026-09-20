"""Rewrite the golden renderings in ``trust_renderings.golden``.

Run it only after reading the failing diff and agreeing with every line:

    .venv/bin/python -m tests.meta.regen_trust_golden

The golden file is what stops a renderer changing what protokit says about a
run without a human seeing the change.
"""

from __future__ import annotations

from tests.meta.test_formatter_trust import _GOLDEN, _all_renderings

if __name__ == "__main__":
    _GOLDEN.write_text(_all_renderings())
    print(f"rewrote {_GOLDEN}")
