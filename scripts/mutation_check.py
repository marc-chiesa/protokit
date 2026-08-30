#!/usr/bin/env python3
"""Prove a test is non-vacuous: it must FAIL when its guarded code is mutated.

A test that pins a cost ceiling, a sanitizer, or a defensive branch is worthless
unless it actually fails when that code is broken. The prior audit's harness was
wrong four times (zsh word-splitting on unquoted vars; wrong file/test scope),
producing false "this is covered" readings. So this harness asserts the mutation
really landed in the file before it trusts any test result, and always restores
the file — even on exception.

    python3 scripts/mutation_check.py <file> <old> <new> <pytest-target>...

Exit 0 = the target FAILED under mutation (the test is real).
Exit 1 = the target PASSED under mutation (the test is VACUOUS) or setup failed.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

VENV_PY = ".venv/bin/python"


def main() -> int:
    if len(sys.argv) < 5:
        print(__doc__)
        return 1
    path, old, new, targets = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:]
    p = pathlib.Path(path)
    original = p.read_text()

    if old not in original:
        print(f"SETUP FAILED: {old!r} not found in {path}")
        return 1
    if original.count(old) != 1:
        print(f"SETUP FAILED: {old!r} appears {original.count(old)}x in {path}; "
              "make the anchor unique")
        return 1

    mutated = original.replace(old, new, 1)
    if mutated == original:
        print("SETUP FAILED: replacement produced an identical file")
        return 1

    try:
        p.write_text(mutated)
        # Re-read from disk: proves the write landed, not just that we built a
        # different string in memory.
        on_disk = p.read_text()
        if new not in on_disk or old in on_disk:
            print("SETUP FAILED: mutation not present on disk after write")
            return 1
        print(f"mutation applied to {path}:\n  - {old}\n  + {new}\n")

        result = subprocess.run(
            [VENV_PY, "-m", "pytest", *targets, "-q", "--no-header", "-p", "no:randomly"],
            capture_output=True,
            text=True,
        )
        tail = result.stdout.strip().splitlines()[-6:]
        print("\n".join(tail))
        if result.returncode == 0:
            print("\nVACUOUS — the target passed with the code broken.")
            return 1
        print("\nNON-VACUOUS — the target failed under mutation, as it must.")
        return 0
    finally:
        p.write_text(original)
        assert p.read_text() == original, f"FAILED TO RESTORE {path}"
        print(f"restored {path}")


if __name__ == "__main__":
    raise SystemExit(main())
