#!/usr/bin/env python3
"""Prove a test is non-vacuous: it must FAIL when its guarded code is mutated.

A test that pins a cost ceiling, a sanitizer, or a defensive branch is worthless
unless it actually fails when that code is broken. The prior audit's harness was
wrong four times (zsh word-splitting on unquoted vars; wrong file/test scope),
producing false "this is covered" readings. So this harness asserts the mutation
really landed in the file before it trusts any test result, and always restores
the file — even on exception.

Three more ways a mutation can lie, each closed here:

* **A red target proves nothing.** A target that already fails on the
  unmutated source fails under any mutation. The target is run on the
  original first and must pass, or the proof is refused.
* **Only pytest exit 1 is a verdict.** Exit 0 means the tests passed with the
  code broken (VACUOUS). Exit 1 means tests failed (NON-VACUOUS). Anything
  else — 2 interrupted, 3 internal error, 4 usage error (a bad option, a
  missing target file), 5 no tests collected (a misspelled node id, a ``-k``
  that selects nothing) — is not a verdict and is refused, where it used to
  print NON-VACUOUS.
* **Bytecode.** CPython validates a cached ``.pyc`` against the source's
  *whole-second* mtime and its size, so a mutation whose replacement is the
  same length as its anchor, applied and restored within one second, leaves
  the cache "valid" for the wrong text: the mutated run can execute the
  ORIGINAL bytecode (a false VACUOUS), and every run after restore can execute
  the MUTATED bytecode until something else touches the file — measured
  2026-09-14, when a restored differ.py kept raising for the accessor the
  source no longer called. So the target's cache is dropped before each run
  and again after restore — for every interpreter tag, under
  ``PYTHONPYCACHEPREFIX`` as well as ``__pycache__`` — and pytest runs with
  ``-B`` so the mutated source never writes one. A grandchild interpreter
  spawned by a test does not inherit ``-B``; the post-restore drop is what
  catches what it wrote.

The file is handled as bytes so a CRLF source is restored byte-for-byte.

    python3 scripts/mutation_check.py <file> <old> <new> <pytest-target>...

Exit 0 = the target FAILED under mutation (the test is real).
Exit 1 = the target PASSED under mutation (the test is VACUOUS) or setup failed.

``MUTATION_CHECK_TIMEOUT`` (seconds, default 900) bounds each pytest run.
"""

from __future__ import annotations

import importlib.util
import os
import pathlib
import subprocess
import sys

VENV_PY = ".venv/bin/python"
TIMEOUT_SECONDS = float(os.environ.get("MUTATION_CHECK_TIMEOUT", "900"))


def _drop_bytecode(source: pathlib.Path) -> None:
    """Remove every cached ``.pyc`` for ``source`` so the next import recompiles.

    ``cache_from_source`` names this interpreter's cache file and honours a
    ``PYTHONPYCACHEPREFIX``; the globs beside it catch every other
    interpreter tag and pytest's assertion-rewrite caches in that directory,
    and the default ``__pycache__`` location even when this interpreter
    caches under a prefix.
    """
    cache = pathlib.Path(importlib.util.cache_from_source(str(source)))
    candidates = {cache}
    candidates.update(cache.parent.glob(f"{source.stem}.*.pyc"))
    candidates.update(source.parent.glob(f"__pycache__/{source.stem}.*.pyc"))
    for pyc in candidates:
        pyc.unlink(missing_ok=True)


def _run_pytest(targets: list[str]) -> subprocess.CompletedProcess[str] | None:
    """Run the target under ``-B``; ``None`` on timeout."""
    try:
        return subprocess.run(
            [VENV_PY, "-B", "-m", "pytest", *targets, "-q", "--no-header", "-p", "no:randomly"],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return None


def _tail(result: subprocess.CompletedProcess[str]) -> str:
    lines = (result.stdout.strip() or result.stderr.strip()).splitlines()
    return "\n".join(lines[-6:])


def main() -> int:
    if len(sys.argv) < 5:
        print(__doc__)
        return 1
    path, old, new, targets = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:]
    p = pathlib.Path(path)
    original = p.read_bytes()
    old_b, new_b = old.encode(), new.encode()

    if old_b not in original:
        print(f"SETUP FAILED: {old!r} not found in {path}")
        return 1
    if original.count(old_b) != 1:
        print(f"SETUP FAILED: {old!r} appears {original.count(old_b)}x in {path}; "
              "make the anchor unique")
        return 1

    mutated = original.replace(old_b, new_b, 1)
    if mutated == original:
        print("SETUP FAILED: replacement produced an identical file")
        return 1

    # A target that is red on the unmutated source would "fail under
    # mutation" whatever the mutation. Prove the baseline is green first.
    _drop_bytecode(p)
    baseline = _run_pytest(targets)
    if baseline is None:
        print(f"SETUP FAILED: baseline run timed out after {TIMEOUT_SECONDS:.0f}s")
        return 1
    if baseline.returncode != 0:
        print(_tail(baseline))
        print(f"\nSETUP FAILED: target is not green on the unmutated source "
              f"(pytest exit {baseline.returncode}); a proof needs a passing baseline")
        return 1

    try:
        p.write_bytes(mutated)
        # Re-read from disk: proves the write landed, not just that we built a
        # different string in memory. Equality, not substring checks: a
        # replacement that contains its own anchor is a legitimate mutation.
        if p.read_bytes() != mutated:
            print("SETUP FAILED: mutation not present on disk after write")
            return 1
        print(f"mutation applied to {path}:\n  - {old}\n  + {new}\n")
        _drop_bytecode(p)

        result = _run_pytest(targets)
        if result is None:
            print(f"SETUP FAILED: mutated run timed out after {TIMEOUT_SECONDS:.0f}s")
            return 1
        print(_tail(result))
        if result.returncode == 0:
            print("\nVACUOUS — the target passed with the code broken.")
            return 1
        if result.returncode != 1:
            print(f"\nSETUP FAILED: pytest exited {result.returncode} under mutation "
                  "(1 = tests failed; 2 = interrupted, 3 = internal error, "
                  "4 = usage error, 5 = no tests collected): not a verdict")
            return 1
        print("\nNON-VACUOUS — the target failed under mutation, as it must.")
        return 0
    finally:
        p.write_bytes(original)
        assert p.read_bytes() == original, f"FAILED TO RESTORE {path}"
        _drop_bytecode(p)
        print(f"restored {path}")


if __name__ == "__main__":
    raise SystemExit(main())
