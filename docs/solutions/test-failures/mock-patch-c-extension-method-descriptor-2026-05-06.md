---
title: "unittest.mock.patch silently no-ops on protobuf-python C-extension methods (DescriptorPool.Add)"
date: "2026-05-06"
category: docs/solutions/test-failures
module: protokit-lint
problem_type: test_failure
component: testing_framework
severity: medium
symptoms:
  - "unittest.mock.patch on DescriptorPool.Add silently does not intercept calls"
  - "Test asserts result.exit_code == 2 but observes exit_code == 0 (no-op patch)"
  - "No SystemExit raised; the helper's error_exit_with_code path never executes"
root_cause: wrong_api
resolution_type: test_fix
tags:
  - mock
  - patch
  - c-extension
  - descriptor-pool
  - protobuf
  - unittest-mock
  - MagicMock
  - CliRunner
  - pytest-raises
  - capsys
  - SystemExit
  - patch-object
  - test-isolation
---

# `unittest.mock.patch` silently no-ops on protobuf-python C-extension methods (DescriptorPool.Add)

## Problem

When testing `_load_descriptor_sets_to_result` (in
`src/protokit/schema/lint/_cli_utils.py`) via the natural pattern
`unittest.mock.patch("google.protobuf.descriptor_pool.DescriptorPool.Add",
side_effect=TypeError(...))`, the patch context silently fails to
intercept the call. `pool.Add(fd)` runs the real C-extension method
against the (clean) test fixture, succeeds, and the helper's error
path never executes. The test asserts `result.exit_code == 2` but
observes `exit_code == 0` because no `sys.exit(2)` ever fired.

## Symptoms

- The mock's `side_effect` never triggers; no synthetic TypeError
  surfaces in the helper.
- `result.exit_code` is 0 instead of the expected 2.
- `result.output` / `result.stderr` contain none of the expected
  `error[lint-pool-conflict]:` stable-prefix line.
- The fixture is a valid (clean) descriptor set, so the real
  `pool.Add()` succeeds — making the patch's no-op invisible until
  the assertion fires at the end of the test.
- The test fails with `assert 0 == 2` rather than any exception
  from the patching machinery itself.

## What Didn't Work

The natural first-instinct approach:

```python
with unittest.mock.patch(
    "google.protobuf.descriptor_pool.DescriptorPool.Add",
    side_effect=TypeError("synthetic novel TypeError text"),
):
    result = CliRunner().invoke(lint_main, [str(clean_descriptor_set)])
assert result.exit_code == 2  # FAILS: exit_code is 0
```

Silently no-ops because `descriptor_pool.DescriptorPool.Add` is a
C-extension method (the protobuf-python package wraps the protobuf
C++ runtime). `unittest.mock.patch` ultimately calls
`setattr(target_class, target_attr, mock)` to install the mock.
For C-extension method slots, that `setattr` either raises
`AttributeError` (which the patch context manager's cleanup logic
swallows in some configurations) or appears to succeed at the
Python-namespace level while the underlying C dispatch ignores
the override entirely. There is no Python-accessible method
object to replace.

A variant attempt — patching via the full dotted-path string in
`patch("...")` rather than `patch.object(class, "Add", ...)` — hits
the same wall for the same reason. The target is still the method
slot on a C-extension type; the indirection layer doesn't change
the underlying `setattr` failure mode.

A second confounder layered on top: invoking the helper through
`CliRunner().invoke(...)` adds a `SystemExit`-catching boundary.
CliRunner intercepts `SystemExit` and converts it to
`result.exit_code`, then exposes captured streams via
`result.output` / `result.stderr` — but stderr handling has shifted
across Click versions (Click 8.3 dropped `mix_stderr` from the
constructor; older versions defaulted to merging stderr into
output). When the patch fails to fire, the real `pool.Add` succeeds
and no SystemExit happens at all — the test sees exit_code 0 and
empty output, which is genuinely ambiguous.

## Solution

Patch at the **class accessor level** on the helper's imported
namespace, and call the helper **directly** (bypassing CliRunner)
so `pytest.raises(SystemExit)` and `capsys.readouterr()` capture
the exit code and stderr cleanly:

```python
from unittest.mock import MagicMock, patch

import pytest

from protokit.schema.lint import _cli_utils as lint_cli_utils


# (Method on a pytest test class; the `self` parameter would be
# absent for a standalone function-style test.)
def test_unmatched_typeerror_falls_through_to_pool_conflict(
    self,
    clean_descriptor_set: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake_pool = MagicMock()
    fake_pool.Add.side_effect = TypeError("synthetic novel TypeError text")

    with patch.object(
        lint_cli_utils.descriptor_pool,
        "DescriptorPool",
        return_value=fake_pool,
    ), pytest.raises(SystemExit) as exc_info:
        lint_cli_utils._load_descriptor_sets_to_result(
            (clean_descriptor_set,),
        )
    assert exc_info.value.code == 2

    captured = capsys.readouterr()
    assert "error[lint-pool-conflict]:" in captured.err
    assert "synthetic novel TypeError text" in captured.err
```

Two seams were swapped together:

1. **Patch the class accessor, not the method.**
   `patch.object(lint_cli_utils.descriptor_pool, "DescriptorPool",
   return_value=fake_pool)` replaces the `DescriptorPool` symbol on
   the `descriptor_pool` module reference imported into the helper.
   When the helper executes `descriptor_pool.DescriptorPool()`,
   it now calls a `MagicMock` configured as a factory; the factory
   returns `fake_pool`, also a `MagicMock`. Every subsequent
   `pool.Add(fd)` routes through `MagicMock.Add`, which IS fully
   Python-controllable, and `side_effect = TypeError(...)` fires
   reliably.

2. **Bypass CliRunner for SystemExit-level tests.**
   Calling `_load_descriptor_sets_to_result` directly inside
   `pytest.raises(SystemExit)` lets the test assert on
   `exc_info.value.code` (the raw exit code) and
   `capsys.readouterr().err` (the actual stderr stream) without
   Click's version-sensitive buffering interfering. CliRunner is
   the right tool for integration tests that exercise argument
   parsing and command dispatch; it is the wrong tool when the
   test is specifically verifying a helper's `sys.exit` + stderr
   contract.

Landed as commit `dd9cfe4` on `feat/d3-protokit-lint-cli` (D3 Unit
2 ce:review follow-ups).

## Why This Works

**Root cause:** C-extension methods live in C-level type slots, not
in a Python `__dict__` entry on the class object. `setattr` on a
C-extension type either fails silently (its return path is treated
as a no-op by the dispatch machinery) or patches a Python-level
shadow that the C dispatch never consults. There is no
Python-visible method object to replace.

**Why patching the class accessor works:** The helper does
`from google.protobuf import descriptor_pool` at the top of the
module. After import, `descriptor_pool` is just a reference to a
Python module object, and `descriptor_pool.DescriptorPool` is a
normal attribute lookup on that module — a writable Python
namespace entry that happens to point at a C-extension class.
`patch.object` swaps the Python attribute, so each subsequent
`descriptor_pool.DescriptorPool()` call returns whatever we
substituted. The C-extension is bypassed entirely; we never touch
the class itself or its methods. The mock factory and resulting
`MagicMock` instance are pure Python, fully controllable.

**Why bypassing CliRunner works:** CliRunner's `invoke` catches
`SystemExit` (because click's `BaseCommand.main` itself calls
`sys.exit`) and exposes the exit code via `result.exit_code`.
When the goal of the test is "this specific helper writes
`error[lint-CODE]:` to stderr and exits 2", the runner's
catch-all is unnecessary indirection. Direct invocation +
`pytest.raises(SystemExit)` exposes `exc_info.value.code` (which
is `SystemExit.code` — the integer passed to `sys.exit`), and
`capsys.readouterr().err` returns the actual stderr stream
without Click's version-dependent buffering. The two assertions
are tighter, faster, and don't depend on click version drift
(`mix_stderr` was dropped from CliRunner's constructor in
Click 8.3; `result.stderr` works since 8.2 but behaves
differently across versions).

## Prevention

**Rule 1 — Never patch C-extension methods at method level.**

For protobuf-python (and any library wrapping a C++ or C runtime),
assume all methods on core types (`DescriptorPool`,
`FileDescriptor`, `Descriptor`, etc.) are C-extension methods.
Diagnostic check before writing the test:

```python
>>> import google.protobuf.descriptor_pool as dp
>>> type(dp.DescriptorPool.Add)
<class 'method-wrapper'>  # or 'builtin_function_or_method'
```

If the type is `method-wrapper` or `builtin_function_or_method`,
patching at method level is a no-op. Patch at the class-accessor
level on the importing module:

```python
# WRONG — no-op silently on C-extension method slots:
patch("google.protobuf.descriptor_pool.DescriptorPool.Add", side_effect=...)

# RIGHT — patches the Python class binding in the importing module.
# The MagicMock factory returns a per-call MagicMock instance whose
# `.Add` method is fully Python-controllable. Configure
# `fake_pool.Add.side_effect = ...` BEFORE entering the patch
# context if your test needs to exercise the error path.
fake_pool = MagicMock()
fake_pool.Add.side_effect = TypeError("...")
patch.object(your_module.descriptor_pool, "DescriptorPool",
             return_value=fake_pool)
```

The pattern generalizes: for any module that imports a class from a
C-extension package, patch at the IMPORTING module's namespace,
not at the source class's method level.

**Rule 2 — Use CliRunner for integration tests; use direct
invocation for unit tests on `sys.exit` behavior.**

Decision rule:

| Test goal | Use |
|-----------|-----|
| Argument parsing, command routing, full pipeline | `CliRunner().invoke(...)` |
| Specific helper exits with code N and writes string X to stderr | `pytest.raises(SystemExit)` + `capsys` |
| `--help` text rendering, click flag validation | `CliRunner` |
| Error-code dispatch within a helper | direct invocation |

For the helper-exit-code case:

```python
with pytest.raises(SystemExit) as exc_info:
    module._helper_function(args)
assert exc_info.value.code == 2
captured = capsys.readouterr()
assert "expected stderr line" in captured.err
```

**Rule 3 — Establish the pattern in conftest/test-helpers when
multiple tests need it.**

If a test suite has multiple cases that need to mock
`descriptor_pool.DescriptorPool`, define a shared fixture:

```python
@pytest.fixture()
def patched_descriptor_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> MagicMock:
    """Patch DescriptorPool at the helper's import-namespace level.

    Returns the MagicMock the helper will receive when it calls
    `descriptor_pool.DescriptorPool(...)`. Tests configure
    side_effects on `pool.Add`, `pool.FindFileByName`, etc.

    `monkeypatch` is preferred over `patch.object(...)` here
    because pytest's monkeypatch handles teardown automatically at
    fixture scope, while `patch.object` as a context manager
    requires a `yield` boilerplate to scope the cleanup.
    """
    pool = MagicMock()
    # Use `return_value=pool` (not `lambda: pool`) so the mock
    # factory absorbs any positional/keyword arguments a future
    # caller might pass to `DescriptorPool(...)`. The lambda form
    # would raise TypeError on the first such call.
    factory = MagicMock(return_value=pool)
    monkeypatch.setattr(
        lint_cli_utils.descriptor_pool, "DescriptorPool", factory,
    )
    return pool
```

This makes the pattern discoverable, documents the rationale via
the fixture's docstring, and prevents future tests from
rediscovering the C-extension patching failure.

**Rule 4 — When confused about why a mock isn't firing, assert
that the patch actually replaced the target.**

Add a runnable assertion inside the patch context — fails fast
with an actionable message instead of requiring you to eyeball
console output:

```python
from unittest.mock import MagicMock

with patch(...) as mock:
    assert isinstance(target_class.target_method, MagicMock), (
        f"patch did not fire — type is "
        f"{type(target_class.target_method).__name__}; the target "
        f"is likely a C-extension method slot. Patch at the class "
        f"accessor on the importing module instead."
    )
```

If the assertion fails, the patch isn't actually replacing the
target. Re-read the import chain and patch at a different seam
(class accessor on the importing module is the canonical
fallback).

## Related Issues

- **`docs/solutions/security-issues/formatter-systemexit-exit-code-bypass-2026-04-19.md`** —
  Companion learning on `SystemExit` handling: there, the
  formatter's `sys.exit(0)` was caught by `run_formatter_safely`
  (a try/except boundary inside the CLI) BEFORE reaching CliRunner,
  so its regression test correctly uses CliRunner to verify the
  caught-and-converted exit code. Here, the SystemExit originates
  inside the helper being tested, so CliRunner becomes
  unnecessary indirection. Both docs document related-but-distinct
  facets of "how to assert SystemExit behavior in pytest" — read
  together for the full picture.

- **`tests/schema/lint/cli/test_cli_input_modes.py`** lines
  254–293 — canonical reference implementation of this pattern.
  Future tests on similar C-extension surfaces can use this as a
  template.

- **D3 Unit 2 plan, R24 helper section** —
  `docs/plans/2026-05-04-001-feat-protokit-lint-d3-cli-plan.md`
  documents the test obligation for `_load_descriptor_sets_to_result`
  (pin against actual `descriptor_pool.Add` output for all three
  observed message shapes). This learning enabled the third shape
  (`couldn't resolve name`) to be tested without requiring a
  dedicated fixture file — the inline `FileDescriptorProto`
  construction + class-accessor patch covers what would otherwise
  need a separate `.proto` file.
