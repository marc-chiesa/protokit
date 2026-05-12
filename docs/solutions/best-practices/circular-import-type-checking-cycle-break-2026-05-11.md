---
title: "Break annotation-only import cycles with TYPE_CHECKING when PEP 563 is on — avoid lazy imports inside except arms"
date: 2026-05-11
category: docs/solutions/best-practices
module: python/imports
problem_type: best_practice
component: tooling
severity: medium
applies_when:
  - "Two Python modules import each other, creating a cycle that you currently work around with a lazy import (`from x import y` inside a function body or except arm)"
  - "The cycle-creating import is used ONLY as a parameter annotation, return type, or other typing-context reference — never as a runtime constructor, isinstance check, or attribute access on the class"
  - "The importing module has `from __future__ import annotations` (PEP 563) enabled"
  - "The lazy import sits inside a `try/except` arm that is *containing* exceptions (converting them into structured warnings without re-raising), where an ImportError escaping the arm would silently drop the original exception"
  - "ce:review adversarial or reliability reviewers flag a lazy-import-inside-except-arm as a contract-breaking surface"
related_components:
  - tooling
tags:
  - type-checking
  - circular-import
  - pep-563
  - lazy-import
  - importerror
  - except-arm
  - exit-code-contract
  - python
---

# Break annotation-only import cycles with `TYPE_CHECKING` when PEP 563 is on — avoid lazy imports inside `except` arms

## Context

A common workaround for an import cycle in Python is the **lazy import inside an `except` arm or function body**: defer the offending import until runtime so the top-level import order does not deadlock. The pattern looks harmless because it usually works — but it has a brittle failure mode when used inside a `try/except` arm that is catching exceptions *for containment* (i.e., converting them into structured warnings without re-raising). If the lazy import itself ever raises, the new exception propagates out of the arm with `__context__` set to the original — but the original exception is **not** re-raised. Any contract that depended on the original being contained silently breaks.

This pattern appeared in protokit D5 U4. `LintEngine._invoke_rule` (`src/protokit/schema/lint/engine.py`) catches `_RULE_EXCEPTION_TUPLE` to convert in-rule exceptions into a `LintRuntimeWarning` instead of crashing the whole lint run. Before U4, the arm used a lazy import for `_safe_for_stderr`:

```python
except _RULE_EXCEPTION_TUPLE as exc:
    from protokit.schema.lint._cli_utils import (  # noqa: PLC0415
        _safe_for_stderr,
    )
    scrubbed = _scrub_exc_message(exc) or repr(exc)
    safe_message = _safe_for_stderr(scrubbed)
    self._runtime_warnings.append(...)
```

The lazy import existed because `_cli_utils.py` imported `LintEngine` from `engine.py` at module top, and `engine.py` needed `_safe_for_stderr` from `_cli_utils.py` — a direct cycle.

The adversarial reviewer (`ADV-P2-A`) walked the crash scenario step by step:

1. A user rule pack misbehaves and raises a caught exception (e.g., `ValueError`).
2. The `except _RULE_EXCEPTION_TUPLE` arm begins executing.
3. The lazy import `from protokit.schema.lint._cli_utils import _safe_for_stderr` runs. It raises `ImportError` (broken transitive dep, partial install, packaging error).
4. Python propagates `ImportError` out of the `except` arm. Python sets the original `ValueError` as `__context__` but does **not** re-raise it.
5. No `LintRuntimeWarning` is appended.
6. `ImportError` escapes `engine.run`, escapes `_main_impl` in `cli.py` (neither has an `ImportError` handler).
7. The CLI exits with a traceback at exit code **1**, not **2**.
8. CI scripts filtering for `error[lint-` see nothing. The original `ValueError` is silently dropped.

The "lint-internal failure uses exit 2 with `error[lint-...]` prefix" contract — the load-bearing guarantee for every CI consumer of `protokit lint` — was silently breakable until U4.

Four reviewers independently flagged this surface (4-way convergence): adversarial `ADV-P2-A`, correctness residual risk, cli-readiness `RR-U4-02`, kieran-python `RR-KP-U4-02`.

## Guidance

When a lazy import was added **only** to break a cycle that exists **only** because of an annotation, check whether `from __future__ import annotations` (PEP 563) is enabled on the importing module. If it is, the annotation evaluates to a string at runtime and the class does not need to be imported at all — move the import under `if TYPE_CHECKING:` and eager-import everything that is actually used at runtime.

**Before — fragile lazy import inside an exception arm:**

```python
# _cli_utils.py — annotation-only use of LintEngine creates the cycle
from protokit.schema.lint.engine import LintEngine   # eager — cycle here

def _load_user_rule_pack(
    module_name: str, engine: LintEngine,
) -> ModuleType:
    ...
    engine.load_rule_pack(module)   # method call on instance, not class
    ...
```

```python
# engine.py — lazy import works around the cycle; can crash mid-rule
except _RULE_EXCEPTION_TUPLE as exc:
    from protokit.schema.lint._cli_utils import (  # noqa: PLC0415
        _safe_for_stderr,
    )
    safe_message = _safe_for_stderr(_scrub_exc_message(exc) or repr(exc))
    self._runtime_warnings.append(...)
```

**After — `TYPE_CHECKING`-gated annotation import, eager runtime import:**

```python
# _cli_utils.py
from __future__ import annotations   # already present — load-bearing here

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from protokit.formatters import Formatter, FormatterContext
    from protokit.schema.lint.engine import LintEngine   # moved into TYPE_CHECKING

from protokit.schema.lint.decorator import get_lint_spec
from protokit.schema.lint.model import DuplicateRuleError


def _load_user_rule_pack(
    module_name: str, engine: LintEngine,
) -> ModuleType:
    ...
    engine.load_rule_pack(module)   # works at runtime — instance method call
    ...
```

```python
# engine.py — eager import at module top, no lazy import in except arm
from protokit.schema.lint._cli_utils import _safe_for_stderr

except _RULE_EXCEPTION_TUPLE as exc:
    scrubbed = _scrub_exc_message(exc) or repr(exc)
    safe_message = _safe_for_stderr(scrubbed)
    self._runtime_warnings.append(...)
```

The cycle is broken because `_cli_utils.py` no longer imports `LintEngine` at runtime — `TYPE_CHECKING` is `False` at runtime, so the import block is skipped, and PEP 563 makes the annotation a string that mypy resolves but Python never evaluates.

Three verification obligations belong with the fix:

1. **Import-smoke test** — confirm both orderings load: `python -c "import protokit.schema.lint.engine; import protokit.schema.lint._cli_utils"` and the reverse.
2. **Cold-import contract test** — if your project enforces a "package X must not transitively load module Y" contract (protokit does; see D1 `tests/schema/lint/test_cold_import_extended.py`), confirm the `TYPE_CHECKING` gate did not disturb it.
3. **Exit-code contract test** (optional, defense-in-depth) — fault-inject the previously-lazy import (e.g., by deleting `_safe_for_stderr`); the process should now fail at startup with a clear `ImportError`, not silently mid-run after a rule misbehaves.

## Why This Matters

- **Lazy imports inside except-for-containment arms are silent contract-breakers.** Any `ImportError` from the lazy import bypasses the containment and escapes to the next handler — which for CLI tools usually means exit code 1 + traceback, breaking exit-code contracts that CI depends on. This is a class of bug, not a one-off.
- **The fix removes a whole class of failures, not just one.** Once the lazy import is gone, there is no remaining "what if this import fails *now*?" surface — the import either succeeded at process start or the process never started.
- **`TYPE_CHECKING` + PEP 563 is the cheapest cycle break available** when the cycle exists only because of annotations. No `Protocol` extraction, no module reshuffling, no public API change.
- **It documents intent.** A reader sees "this import is annotation-only" without having to grep for runtime uses.
- **The crash window is invisible to the test suite.** Lazy-import failures only manifest in deployment scenarios (packaging issues, broken transitive deps) that unit tests do not exercise. The fix closes a path that may never have been observed in CI, but is real in production.

## When to Apply

Apply when **all three** preconditions hold:

1. The importing module has `from __future__ import annotations` (PEP 563) enabled.
2. The cycle-creating import is used **only** as an annotation. Verify by grepping for the class name and confirming every use is in a type hint, a `cast(...)`, or a `TypeAlias` — not as a constructor, `isinstance` check, or attribute access on the class.
3. The class is not needed for runtime `isinstance` checks, `issubclass` checks, dataclass field defaults, or `cast()` calls (those need a runtime reference even with PEP 563).

**Do not apply when:**

- The class is used at runtime (e.g., `engine = LintEngine()` at module scope). `TYPE_CHECKING` evaluates to `False` at runtime, so a real reference would `NameError`.
- The module has not enabled PEP 563. Without `from __future__ import annotations`, the annotation evaluates eagerly at function-definition time and would `NameError` exactly like the runtime case above. (Python 3.13+ may make this configurable, but the safe rule today is: PEP 563 must be on.)
- The cycle is structural rather than annotation-driven (genuine bidirectional runtime calls). Those need a different fix — extract a shared interface, dependency-inject the collaborator, or merge the modules.

## Examples

### Real protokit U4 fix

`_cli_utils.py` had `LintEngine` used only as a parameter annotation on `_load_user_rule_pack`. The only runtime use of the parameter was `engine.load_rule_pack(module)` — a method call on the instance, which needs no class import. Moving the import under `if TYPE_CHECKING:` and adding `from protokit.schema.lint._cli_utils import _safe_for_stderr` at the top of `engine.py` closed the cycle and eliminated the lazy import.

Verification that ran post-fix:

```bash
# Both orderings import cleanly:
.venv/bin/python -c "
import protokit.schema.lint.engine as e
import protokit.schema.lint._cli_utils as c
print('engine._safe_for_stderr:', e._safe_for_stderr.__name__)
print('cycle broken: OK')
"
# Output:
# engine._safe_for_stderr: _safe_for_stderr
# cycle broken: OK

# Cold-import contract still holds:
.venv/bin/python -c "
import sys
before = set(sys.modules.keys())
import protokit.schema
after = set(sys.modules.keys()) - before
forbidden = [m for m in after if 'lint' in m or '.compile' in m]
assert not forbidden, forbidden
print('cold-import contract: OK')
"
```

### Subtle gotcha: PEP 563 is load-bearing

If `_cli_utils.py` had `engine = LintEngine()` somewhere at runtime — or even `if isinstance(x, LintEngine):` — `TYPE_CHECKING` would not suffice. The class would have to be in scope at runtime, which means either keeping the eager import (and a different cycle break: shared interface, lazy-import-in-function-body, module restructure) or eliminating the runtime class reference. The U4 verification grepped `_cli_utils.py` for `LintEngine` and confirmed every occurrence was either an annotation or a docstring reference before applying the fix.

```bash
# The verification grep:
grep -n "LintEngine" src/protokit/schema/lint/_cli_utils.py
# 32: from protokit.schema.lint.engine import LintEngine     # the import itself
# 382: module_name: str, engine: LintEngine,                  # parameter annotation
# 415:     engine: The ``LintEngine`` to register the pack into.  # docstring
#
# No constructor call, no isinstance check, no class attribute access → safe to gate.
```

### The crash scenario the fix closes

```python
# Reproduce ADV-P2-A's failure mode (counterfactual — pre-fix shape):
#
# Step 1: A user rule pack raises ValueError matching the catch tuple.
# Step 2: The except arm begins executing.
# Step 3: The lazy import fires.
# Step 4: The lazy import raises ImportError (any reason).
# Step 5: ImportError propagates OUT of the except arm.
# Step 6: The original ValueError is set as __context__ but NOT re-raised.
# Step 7: No runtime_warning is appended.
# Step 8: ImportError escapes engine.run → escapes _main_impl → traceback.
# Step 9: Process exits with code 1 (uncaught), NOT 2 (lint-internal).
# Step 10: CI grep on `error[lint-` matches nothing. Failure is silent.
```

## Related

- [`deprecationwarning-poisons-except-exception-strict-warning-ci-2026-05-11.md`](deprecationwarning-poisons-except-exception-strict-warning-ci-2026-05-11.md) — sibling "discipline near except arms" learning. Both involve unexpected exceptions escaping a containment `except` arm with wrong attribution; this one's mechanism is `ImportError` from a lazy import, the sibling's mechanism is `DeprecationWarning` promoted to exception under `-W error::DeprecationWarning`. Different mechanism, same failure-mode family.
- [`keyboardinterrupt-baseexception-bypass-rule-pack-load-2026-05-07.md`](../security-issues/keyboardinterrupt-baseexception-bypass-rule-pack-load-2026-05-07.md) — `KeyboardInterrupt` bypassing `except Exception` arms. Different exception family (BaseException), same "containment arm assumes the exception family it caught is the only one that can fire" anti-pattern.
- [`frozen-dataclass-paired-field-invariant-post-init-2026-05-11.md`](frozen-dataclass-paired-field-invariant-post-init-2026-05-11.md) — companion learning from the same D5 U4 ce:review pass. Different surface (frozen dataclass invariants vs. import cycles) but both are construction-time-correctness disciplines that close silent-failure paths reviewers caught.
- D5 U4 ce:review run id `20260511-224330-79e6510b`. Convergence: `ADV-P2-A` + correctness residual + cli-readiness `RR-U4-02` + kieran-python `RR-KP-U4-02` (4-way).
