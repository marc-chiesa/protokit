---
title: "protokit-lint v1 Delivery 1 — Foundation (model + compile module + helper refactor + CI)"
type: feat
status: active
date: 2026-05-01
origin: docs/brainstorms/2026-04-30-protokit-lint-delivery-1-foundation-requirements.md
---

# protokit-lint v1 Delivery 1 — Foundation (model + compile module + helper refactor + CI)

## Overview

Land the foundational types, library-friendly compile entry point, and verification scaffolding for protokit-lint v1. **CLI public surface preserved** — `protokit compat ...` exit codes (still 2 on failure) and overall flow are unchanged. **Stderr text is best-effort preserved but may shift on previously-uncaught exception paths** (per pass-3 doc-review correction; see Unit 1 acceptance criterion for explicit per-category stderr strings). The legacy `compile_proto()` wrapper continues to call `error_exit` on failure, but it now catches a wider set of exception classes (`OSError`, `TimeoutExpired`) than the current code, which means stderr text on those previously-propagating paths will differ.

Internally, the architecture refactors helpers from "process-exit on error (CLI-flavored)" to "raise on error (library-shaped)" with the legacy adapter providing the CLI surface. The refactor is in-scope for this delivery because Delivery 2 (engine) needs library-shaped helpers — wrapping the current SystemExit-emitting helpers from a library entry point is awkward and breaks the architectural rule from `docs/solutions/security-issues/formatter-systemexit-exit-code-bypass-2026-04-19.md` ("compute verdict in core code, never let library raise SystemExit"). This is the cost-of-doing-the-correction-now choice, not a "fixing a bug" framing — the current helpers work; they just don't fit the library-first direction the project has been moving toward since the design doc's T5 decision.

Every subsequent delivery (engine, CLI stub, formatters, rule packs) imports against locked types and the corrected helper signatures from this PR.

## Problem Frame

The protokit-lint v1 design doc is APPROVED at `~/.gstack/projects/python_message_differencer/marc-main-design-20260424-113550.md` after multiple review rounds (codex outside-voice + 2 document-review passes on this delivery's requirements). Implementation is gated by a foundation PR that locks types and corrects layering before downstream deliveries (engine, CLI stub, formatters, rule packs) inherit them.

The requirements document captures decisions resolved across two doc-review passes (21 findings total):
- **Pass 1** (2026-04-30): scope decision (step 2 only), CI scope (create from scratch), 11 findings resolved
- **Pass 2** (2026-05-01): 10 additional findings resolved including critical empirical correction (`DescriptorPool()` does NOT contain WKTs — the upstream design's claim was empirically false), cold-import contradiction fix (`LintCompileDiagnostic` relocated to `schema/compile.py`), BaseException posture, TimeoutExpired hierarchy correction, and the user-driven reframing that kept the helper refactor in scope (the "broken" existing tests were testing the wrong layer; rewriting them is correcting an existing bug, not adding scope)

## Requirements Trace

- R1. Lock the lint type system in `src/protokit/schema/lint/model.py` (LintSeverity, LintFinding, LintReport, LintProfile, LintRuleSpec, ElementKind 8-values inc ONEOF, LintLocation 8-variant discriminated union, _LintContextEmitMixin + 8 frozen context dataclasses, DuplicateRuleError) — origin §"Types to define in `src/protokit/schema/lint/model.py`"
- R2. Create `src/protokit/schema/compile.py` as the public library compile entry point with `compile_protos_to_result()`, `CompileResult`, and `LintCompileDiagnostic` — origin §"Types/functions in `src/protokit/schema/compile.py`"
- R3. Refactor `_cli_utils._compile_with_protoxy` / `_compile_with_protoc` to multi-path + raising as canonical shape; legacy `compile_proto()` thin-wraps preserving compat — origin §"Helper refactor strategy"
- R4. Five distinct compile-failure `LintCompileDiagnostic` categories with both-fail composition; "no SystemExit, always Diagnostic" contract restated as "all `Exception` subclasses produce a `LintCompileDiagnostic`; `BaseException`-but-not-`Exception` propagates" — origin §"Five distinct compile-failure categories"
- R5. Multi-path compile is REGRESSION-CRITICAL: 3 dedicated tests covering independent multi-path, cross-file imports (input-order preservation), shared include path — origin Test #1-3
- R6. Compile-failure category coverage tests for #2-#5 (~7-9 parametrized test runs across 4 test functions, since categories #4 and #5 each fan out over multiple exception subclasses) + protoxy fallback success path + both-fail composition (2 test functions, the both-fail one parametrized over 3 reachable composition cases) — origin Test #4-9. Total: ~9 distinct test functions, ~14-16 parametrized runs.
- R7. Structural model tests in `test_model.py` covering `compose()`, `severity_for()`, all 8 LintLocation `__str__`, frozen-context instantiation, DuplicateRuleError, finding/report shapes — origin §"Plus structural model tests in `test_model.py`"
- R8. Existing tests in `tests/test_cli_utils.py` rewritten to test corrected layering (helper raises; SystemExit assertion moves to CLI integration level) — origin §"Existing files modified"
- R9. CI workflow from scratch with 4-job matrix (`python: [3.10, 3.12]` × `has_protoxy: [true, false]`); protoc installed on every cell; cold-import smoke step on every cell — origin §"CI workflow"
- R10. Protoxy-import audit across `tests/` to add skip guards for `has_protoxy: false` cells — origin §"Existing files modified" + adversarial pass-2 finding A9-1
- R11. Python 3.10 syntax floor commitment — no `except*`, no `Self` from `typing`, no `exc.add_note()` — origin §"Syntax floor commitment"

## Scope Boundaries

- No engine implementation (`@lint_rule` decorator, `LintEngine`, dispatch loop, rule_id de-duplication runtime path) — Delivery 2
- No actual lint rules (baseline pack, embedded pack) — Deliveries 5-6
- No CLI command (`protokit lint <path>`, lazy-load stub in `protokit/cli.py`) — Delivery 3
- No formatters / `_builtin_lint.py` / `FormatterKind.LINT` — Delivery 4
- No `[tool.protokit.lint]` pyproject config or `--exclude` filtering — Delivery 5
- No plugin API (`@lint_rule`, `--lint-rule-pack`, `--compat-rule-pack` rename, `--rule-pack` deprecation alias) — Delivery 7

### Deferred to Separate Tasks

- `tomli` conditional dependency — added in Delivery 5 when `pyproject.toml` config consumer lands. Not needed in Delivery 1.
- `LintCompileDiagnostic.source_file` field — speculative future-formatter field per scope-guardian #5; add when the first formatter PR needs it.
- `tests/test_perf_smoke.py` benchmark fixture for closure-allocation cost (`_LintContextEmitMixin`) — Delivery 5 step 11.

## Context & Research

### Relevant Code and Patterns

- **Frozen-dataclass + engine-injected `_emit_fn` pattern** — `src/protokit/schema/plugins.py:79-208`. `FieldRuleContext` and `MessageRuleContext` declare `_emit_fn: EmitFn` as the LAST field (with leading underscore signaling "engine-injected, do not call directly"). `EmitFn = Callable[..., None]` typedef at `plugins.py:44`. Each context's `emit()` is `*, kw-only` and delegates to `self._emit_fn(...)` after running `_validate_emit_args(...)` (`plugins.py:47-71, 139-145`). Mirror this for the 8 lint contexts; add `_rule_id: str` and `_effective_severity: Callable[[str], LintSeverity]` as additional engine-injected fields per the requirements doc.
- **Tuple snapshot pattern for frozen dataclasses with sequence fields** — `src/protokit/schema/profiles.py:138-153`. `field(default_factory=tuple)` + `__post_init__` doing `object.__setattr__(self, "name", tuple(self.name))` to defend against caller-supplied lists. Apply to `LintProfile.rule_ids` and any other tuple-typed frozen field.
- **Existing compile helpers (subjects of refactor)** — `src/protokit/_cli_utils.py:71-177`. `_has_protoxy()` (line 71), `compile_proto()` (line 116), `_compile_with_protoxy()` (line 121), `_compile_with_protoc()` (line 147). All currently single-path; both compile helpers call `error_exit()` on failure.
- **Existing `Diagnostic` shape (NOT reused for compile-time)** — `src/protokit/message/model.py:78-125`. `path: str | None`, `message: str`, `level: DiagnosticLevel = "warning"` where `DiagnosticLevel = Literal["error", "warning", "info"]`. The new `LintCompileDiagnostic` follows the same `level` field shape but adds structured fields for compile-specific metadata.
- **Cross-subpackage `Diagnostic` import pattern** — `src/protokit/schema/__init__.py:35`, `src/protokit/schema/model.py:14`, `src/protokit/schema/checker.py:55`, `src/protokit/schema/plugins.py:33`, `src/protokit/schema/rules.py:35` already import `Diagnostic` from `protokit.message.model`. New compile path follows the established pattern (verified pass-1 feasibility F5 — not a new coupling).
- **Test conventions** — `tests/__init__.py` and `tests/schema/__init__.py` are empty; no `conftest.py` exists. Function-scoped `@pytest.fixture` colocated with tests when narrow (e.g., `tests/test_cli_utils.py:28-32` defines `demo_proto_file`). `from __future__ import annotations` standard. `class TestX:` namespacing without inheritance. Type-annotate fixture params and returns.
- **Frozen-dataclass test patterns** — `tests/schema/test_model.py:23-99`. `_make_finding(...)` factory pattern with default kwargs. Frozen-instance test uses `pytest.raises(Exception)` (with `FrozenInstanceError` comment). Enum value assertions: `{e.value for e in EnumType} == {...}`.
- **CLI-level exit-code testing pattern** — `tests/schema/test_cli.py:81-86, 96-101, 122-129`. `result = CliRunner().invoke(main, [...])` then `assert result.exit_code == 2` plus `assert "expected text" in result.output`. The relocated SystemExit assertion from `test_compile_failure_exits_with_code_2` should follow this pattern.
- **Monkeypatch-style backend-absence simulation (repo convention)** — `tests/test_cli_utils.py:40-52, 131-150, 165-170`. Repo has NO existing `pytest.importorskip` or `@pytest.mark.skipif` uses; the established pattern is monkeypatching `_has_protoxy`, `importlib.util.find_spec`, or `subprocess.run`. The protoxy-fallback test follows this; the protoxy-required tests in `TestProtoxyBackend` move to `pytest.mark.skipif(not _has_protoxy(), ...)` per the new CI matrix axis (`has_protoxy: false` cell).
- **Descriptor-builder helpers** — `tests/schema/helpers.py:15-16` re-exports `T = descriptor_pb2.FieldDescriptorProto` and `M = descriptor_pb2.DescriptorProto`. New lint tests can import these for fixture-proto construction.
- **Descriptor-set-to-disk helpers** — `tests/schema/test_cli.py:23-65` defines `_pool_to_descriptor_set_bytes`, `_write_desc`, `_simple_pair`. Multi-path test fixtures may benefit from these.
- **`error_exit()` exit-2 contract** — `src/protokit/_cli_utils.py:33-45`. `click.echo(..., err=True)` then `sys.exit(2)`. Compat callers depend on this; legacy `compile_proto()` wrapper preserves it.

### Institutional Learnings

- **`docs/solutions/security-issues/formatter-systemexit-exit-code-bypass-2026-04-19.md`** — DIRECTLY RELEVANT. Three carry-overs:
  1. **`except Exception` does not catch `SystemExit`** (it's `BaseException`-rooted). New `compile_protos_to_result` uses `except Exception` — that's correct since the contract per A2-1 is "BaseException propagates by design." But: any future engine-level guard around plugin boundaries (Delivery 2) MUST use `except (SystemExit, Exception)` per the documented architectural rule (lines 240-254 of the solution doc).
  2. **The "Regression test" pattern at lines 178-200 is the project's worked example** of the correct test layering: drive the CLI via `CliRunner().invoke(...)` and assert on `result.exit_code` / `result.output`, not on `pytest.raises(SystemExit)` at the helper level. The 8-test rewrite in this delivery follows this pattern.
  3. **Compute verdict in core code, invoke plugins under guard.** Compile helpers (this delivery) raise typed exceptions only; the legacy CLI wrapper is the only layer that translates to process exit. This locks the pattern for all subsequent deliveries.

### External References

External research was skipped per ce:plan Phase 1.2 — the codebase has strong local patterns for everything (frozen dataclasses, click CLI exit-code testing, protobuf compilation, descriptor-pool manipulation). Tech stack is well-established (Python 3.10+, protobuf, click, protoxy, pytest); no emerging framework or security-sensitive surface that warrants external grounding.

## Key Technical Decisions

- **F1=A: Refactor existing helpers to multi-path + raising; legacy `compile_proto()` thin-wraps.** Single source of truth from day one. Legacy public CLI behavior preserved bit-for-bit. Reasoning: per the user's reframing (2026-05-01), the alternative (descope refactor) defers correcting a layering bug that the project's library-first direction demands. (see origin: §"Helper refactor strategy")
- **A3: Define new `LintCompileDiagnostic` with structured fields** rather than reuse `message.model.Diagnostic`. Distinct semantics (compile-time vs diff-time); structured access for downstream consumers (formatters, plugins). (see origin: §"Types/functions in `src/protokit/schema/compile.py`")
- **S2-2: `LintCompileDiagnostic` lives in `schema/compile.py`**, NOT `schema/lint/model.py`. Co-locating with `CompileResult` (its sole consumer) eliminates the transitive import that would break the cold-import contract for `protokit compat`. (see origin: §"Cold-import smoke step")
- **A2-1 BaseException posture: explicit "Exception only" catch chain.** Category #5 catches `Exception` subclasses; `KeyboardInterrupt`, `SystemExit`, `GeneratorExit` propagate by design. Restated contract: "all `Exception` subclasses produce a `LintCompileDiagnostic`; `BaseException`-but-not-`Exception` propagates." (see origin: §"BaseException posture")
- **F3 catch-order: `FileNotFoundError` → `CalledProcessError` → `OSError` → `subprocess.TimeoutExpired` → `Exception`.** `subprocess.TimeoutExpired` is NOT an `OSError` subclass — both are siblings under `subprocess.SubprocessError`/parent. Verified empirically. (see origin: §"Catch-order matters")
- **F1-1 + F1 (root_names matcher) + F2 (same-basename pre-flight) bug fixes baked in:** `dict.fromkeys()` for include-path dedup (deterministic order); pre-compute expected `fd.name` per root via include-path resolution rather than `endswith("/" + p.name)` (which false-positives on shared basenames); pre-flight check rejects same-basename roots in different parent dirs with a clear `ValueError`. (see origin: §"Helper refactor strategy")
- **Both-fail composition: info-fallback first.** When fallback path invoked AND protoc fallback also fails, the diagnostics tuple is `[info-fallback, ...backend-failure-diagnostics]`. Maximum one info-fallback per call (no recursive fallback). (see origin: §"Both-fail composition")
- **Test layering correction is in-scope.** The 8 existing `tests/test_cli_utils.py` tests assert helper-level `SystemExit`. After the refactor, helpers raise; SystemExit assertion moves to a CLI integration test using `CliRunner`. Repo convention: monkeypatch-based backend-absence simulation (no `importorskip`).
- **CI matrix axis = `has_protoxy: [true, false]`.** Protoc installed on every cell via `apt-get install protobuf-compiler`. The axis controls only whether the optional `[compiler]` extra (protoxy) is installed. Tests gate via `_has_protoxy()` and `pytest.mark.skipif`. Drops 3.11 from the matrix (load-bearing axes are 3.10 floor + 3.12 ceiling).
- **Python 3.10 syntax floor.** No `except*`, `Self` from typing, `exc.add_note()`. `[tool.ruff] target-version = "py310"` already enforces.

## Open Questions

### Resolved During Planning

- **What test conventions should the new `tests/schema/lint/` files mirror?** → Follow `tests/test_cli_utils.py` style (function-scoped `@pytest.fixture`, `class TestX:` namespacing, `from __future__ import annotations`, type-annotated fixtures). Use `tests/schema/helpers.py:T,M` for descriptor-builder imports. No new `conftest.py` unless multiple lint test files truly need shared state.
- **Should backend-absence in lint tests use `pytest.importorskip("protoxy")` or monkeypatch?** → Mostly monkeypatch (repo convention). The one exception: `TestProtoxyBackend`-style classes that rely on `protoxy` being importable at module collection time use `pytestmark = pytest.mark.skipif(not _has_protoxy(), reason="optional [compiler] extra not installed")` — a NEW pattern this delivery introduces, scoped to "test classes that integration-test the protoxy backend."
- **Where does `LintCompileDiagnostic` actually live in the codebase?** → `src/protokit/schema/compile.py` (NOT `lint/model.py`). Co-located with `CompileResult` per S2-2 cold-import fix.
- **Test count for `test_model.py`** → 10-12 tests covering `compose()` (single/multi/zero), `severity_for()` (single-kind/multi-kind/KeyError on unregistered), all 8 `LintLocation.__str__`, frozen-context instantiation × 8, frozen immutability spot-check, `DuplicateRuleError` constructibility + Exception inheritance, `LintFinding`/`LintReport` instantiation, enum value assertions for `LintSeverity` and `ElementKind`. (Resolves origin "S2-1 deferred to /ce:plan".)

### Deferred to Implementation

- **Exact algorithm for `_expected_root_names()` (the matcher fix per F1)** — depends on protoxy's `fd.name` resolution semantics in practice. Implementation: for each input path `p`, walk the include list `(*include_paths, *parents)` in declared order; the first include that is a prefix of `p` determines `p`'s relative form (which equals what protoxy emits as `fd.name`). Edge cases (paths not under any include, absolute-path inputs without includes covering them) surface during test write-up.
- **Exact pyproject.toml + apt-get protoc version constraint** — implementation will pin if Edition 2023 fixtures land in any future delivery; current fixtures are proto3, so apt's default `protobuf-compiler` (3.21.x on ubuntu-latest) is sufficient. No constraint needed in this delivery; document expectation as a comment in `ci.yml`.
- **Exact stderr scrubbing for `LintCompileDiagnostic.stderr` in tests** — existing compat module has `_scrub_exc_message()` (`_cli_utils.py:264`) but it's compat-specific. For Delivery 1 tests, snapshot stderr verbatim and use `assert "expected substring" in diagnostic.stderr` rather than full equality (avoids tmp-path fragility). Implementation discovers exact substrings during test write-up.
- *(`LintProfile.compose()` zero-arg behavior — RESOLVED in "Resolved During Planning" above as "return identity profile." No longer deferred.)*

## Output Structure

```
src/protokit/
├── _cli_utils.py                       (modified — helpers refactored)
├── schema/
│   ├── compile.py                      (NEW — public library compile module)
│   └── lint/                           (NEW subpackage)
│       ├── __init__.py
│       └── model.py                    (NEW — lint type system)
tests/
├── test_cli_utils.py                   (modified — 8 tests rewritten)
├── schema/
│   ├── (other tests unchanged)
│   └── lint/                           (NEW directory)
│       ├── __init__.py
│       ├── test_compile_multi.py       (NEW — 3 multi-path tests)
│       ├── test_compile_failure.py     (NEW — 4 distinct-failure tests)
│       ├── test_compile_protoxy_fallback.py  (NEW — 2 fallback tests)
│       ├── test_model.py               (NEW — 10-12 structural tests)
│       └── fixtures/
│           └── *.proto                 (NEW — fixture protos as needed)
.github/
└── workflows/
    └── ci.yml                          (NEW — 4-job matrix)
```

## High-Level Technical Design

> *This illustrates the intended approach and is directional guidance for review, not implementation specification. The implementing agent should treat it as context, not code to reproduce.*

### Helper refactor — single source of truth, two adapters

```
                  ┌────────────────────────────────────────────┐
                  │  _cli_utils.py (library shape)             │
                  │                                            │
                  │  _compile_with_protoxy([Path,...], (-I,..))│
                  │      → (DescriptorPool, list[str])         │
                  │      RAISES: ProtoxyError, ValueError      │
                  │                                            │
                  │  _compile_with_protoc([Path,...], (-I,..)) │
                  │      → (DescriptorPool, list[str])         │
                  │      RAISES: CalledProcessError,           │
                  │              FileNotFoundError, OSError,   │
                  │              TimeoutExpired                │
                  └─────────────────┬──────────────────────────┘
                                    │
              ┌─────────────────────┴─────────────────────┐
              │                                           │
   ┌──────────▼────────────┐           ┌──────────────────▼────────────┐
   │ compile_proto()       │           │ compile_protos_to_result()    │
   │   (legacy CLI adapter)│           │   (new library entry point)   │
   │                       │           │                               │
   │ Catches:              │           │ Catches:                       │
   │   ProtoxyError,       │           │   ProtoxyError → fallback → #1│
   │   ValueError,         │           │   CalledProcessError → #2     │
   │   CalledProcessError, │           │   FileNotFoundError → #3      │
   │   FileNotFoundError,  │           │   OSError + TimeoutExpired→#4 │
   │   OSError,            │           │   Exception → #5 (catch-all)  │
   │   TimeoutExpired      │           │                               │
   │ → error_exit() (sys.  │           │ → CompileResult(pool=...,     │
   │   exit(2))            │           │     root_files=...,           │
   │                       │           │     diagnostics=(...))        │
   │ NEVER catches         │           │ NEVER catches BaseException   │
   │ BaseException         │           │ subclasses (KeyboardInterrupt,│
   │                       │           │  SystemExit, GeneratorExit)   │
   └───────────────────────┘           └───────────────────────────────┘
```

### 5-category compile-failure dispatch (inside `compile_protos_to_result`)

```python
# Pseudocode — directional; not implementation
def compile_protos_to_result(paths, proto_paths=()):
    diagnostics = []
    pool, root_files = None, ()
    try:
        if _has_protoxy():
            try:
                pool, names = _compile_with_protoxy(paths, proto_paths)
                root_files = tuple(names)
            except (protoxy.ProtoxyError, ValueError) as exc:
                # Category #1: fallback path — info diagnostic FIRST
                diagnostics.append(LintCompileDiagnostic(
                    level="info", message="protoxy parse error; falling back to protoc",
                    exception_type=type(exc).__name__))
                # Re-attempt via protoc (may itself raise; both-fail composition)
                pool, names = _compile_with_protoc(paths, proto_paths)
                root_files = tuple(names)
        else:
            pool, names = _compile_with_protoc(paths, proto_paths)
            root_files = tuple(names)
    except FileNotFoundError as exc:                           # #3
        diagnostics.append(_diagnostic_backend_missing(exc))
    except subprocess.CalledProcessError as exc:               # #2
        diagnostics.append(_diagnostic_protoc_subprocess(exc))
    except OSError as exc:                                     # #4 (catches PermissionError, BrokenPipeError, etc.)
        diagnostics.append(_diagnostic_infrastructure(exc))
    except subprocess.TimeoutExpired as exc:                   # #4 (sibling tree under SubprocessError, NOT OSError)
        diagnostics.append(_diagnostic_infrastructure(exc))
    except Exception as exc:                                   # #5 catch-all
        diagnostics.append(_diagnostic_unexpected(exc))
    # BaseException-but-not-Exception (KeyboardInterrupt, SystemExit,
    # GeneratorExit) deliberately NOT caught — propagates by design.
    if pool is None:
        pool = descriptor_pool.DescriptorPool()                # empty pool, NOT WKTs
    return CompileResult(pool=pool, root_files=root_files,
                         diagnostics=tuple(diagnostics))
```

### `LintLocation` discriminated union shape

```python
# Pseudocode — directional; not implementation
@dataclass(frozen=True)
class FileLocation:
    file: str
    def __str__(self) -> str: return self.file

@dataclass(frozen=True)
class FieldLocation:
    file: str; message: str; field: str
    def __str__(self) -> str: return f"{self.file}:{self.message}.{self.field}"

# ... 6 more variants: ServiceLocation, MethodLocation, EnumLocation,
# EnumValueLocation, MessageLocation, OneofLocation

LintLocation = Union[
    FileLocation, ServiceLocation, MethodLocation,
    EnumLocation, EnumValueLocation, MessageLocation,
    FieldLocation, OneofLocation,
]
```

## Implementation Units

- [ ] **Unit 1: Refactor `_cli_utils.py` helpers + rewrite `tests/test_cli_utils.py`**

**Goal:** Refactor `_compile_with_protoxy` and `_compile_with_protoc` to multi-path + raising as canonical shape. Apply concrete bug fixes (set-ordering → `dict.fromkeys`, root_names matcher → expected-fd-name pre-compute, same-basename pre-flight `ValueError`). Legacy `compile_proto()` thin-wraps to preserve compat behavior bit-for-bit. Rewrite the 8 existing tests in `tests/test_cli_utils.py` to test the corrected layering.

**Requirements:** R3, R8

**Dependencies:** None (foundation; preceeds Unit 3 since compile.py uses these helpers)

**Files:**
- Modify: `src/protokit/_cli_utils.py`
- Modify: `tests/test_cli_utils.py` (8 tests rewritten)
- Modify: `tests/schema/test_cli.py` (one-test ADDITION — `test_compat_compile_failure_exit_code_2`, the relocated CLI integration test for the deleted `test_compile_failure_exits_with_code_2`)

**Approach:**
- Refactored signatures: `_compile_with_protoxy(proto_paths_in: Sequence[Path], include_paths: tuple[str, ...]) -> tuple[descriptor_pool.DescriptorPool, list[str]]`. Same shape for `_compile_with_protoc`. Both RAISE on failure (no `error_exit`). NO pre-flight responsibility (moved to `compile_protos_to_result` per pass-3 correction).
- Include-path dedup uses `dict.fromkeys()` for deterministic order: `parents = list(dict.fromkeys(str(p.parent) for p in proto_paths_in))`. Avoid `set` — non-deterministic across Python hash-randomization seeds.
- *(Same-basename pre-flight check moved to `compile_protos_to_result` in Unit 3 — see "Decision pass-3" note. The helpers themselves have NO pre-flight; they are pure backend wrappers.)*
- Root-name matching: `_expected_root_names(proto_paths_in, includes) -> set[str]` — for each input `p`, find the first include in `(*include_paths, *parents)` that is a prefix of `p`; the relative form is `p.relative_to(that_include)`. Compare emitted `fd.name` against this set. Fixes the `endswith("/" + p.name)` false-positive when transitive imports share basenames with roots.
- Legacy `compile_proto(p, ip=())`: thin wrapper around the new helpers; catches `(protoxy.ProtoxyError, ValueError, subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired, OSError)` and calls `error_exit()`. NEVER catches `BaseException` subclasses. Public exit-code-2 behavior on failure preserved.
- Test rewrites in `tests/test_cli_utils.py`:
  - `TestBackendDetection.test_has_protoxy_*` — unchanged (already at the right layer).
  - `TestProtoxyBackend.test_compile_demo_proto` — update call to `_compile_with_protoxy([demo_proto_file], ())`; assert returns `(pool, root_names)` tuple, not just `pool`.
  - `TestProtoxyBackend` class — add `pytestmark = pytest.mark.skipif(not _cli_utils._has_protoxy(), reason="optional [compiler] extra not installed")` at class scope. (NEW pattern in repo.)
  - `TestProtocBackend` tests — same multi-path signature update.
  - `test_compile_failure_exits_with_code_2` — DELETE from this file. The CLI-level equivalent moves to a new file or extends an existing CLI integration test (decision: extend `tests/schema/test_cli.py` since `compile_proto()` is consumed by `protokit compat`; add `test_compat_compile_failure_exit_code_2` using `CliRunner().invoke(main, ["compat", "check", str(bad_proto)])`).
  - `TestDispatch` tests (lines 109-150) — update `_compile_with_protoxy`/`_compile_with_protoc` fakes to accept `Sequence[Path]` instead of `Path`; counter assertions stay intact.
  - `test_compile_proto_protoc_subprocess_error` (lines 152-160) — assert `compile_proto` calls `error_exit` (i.e., `pytest.raises(SystemExit)` with `exc.value.code == 2`); the helper-level subprocess error now surfaces through the legacy wrapper.
  - `test_compile_proto_no_backends` (lines 162-174) — same shape as above.
- **Test-layer audit (per pass-3 doc-review correction).** Before rewriting any test, audit each of the 8 existing tests against this question: *"What specific behavior does this test protect, and does the new architecture have a layer where that behavior still exists?"* Possible outcomes per test:
  - **Direct rewrite** — same layer, signature update only (e.g., `_compile_with_protoxy([path], ip)` instead of `_compile_with_protoxy(path, ip)`).
  - **Relocate** — invariant moves to a different layer (e.g., `test_compile_failure_exits_with_code_2` moves to a CLI integration test).
  - **Discard** — invariant doesn't exist at the new architecture (e.g., a test asserting helper-level SystemExit when the helper now raises typed exceptions and no CLI-level path captures the exact same scenario). Surface discards explicitly in the PR description with rationale per discarded test.
  - **Redesign** — the original invariant was wrong/incomplete; the new architecture surfaces a better invariant. Surface in PR description.
  Add ~30 min for the audit. Output: a small audit table in the PR description listing each test with its outcome (rewrite/relocate/discard/redesign) and rationale.

**Execution note:** Land helper refactor and the 8 test rewrites as one atomic commit — landing them separately would create a broken-tests interim state.

**Patterns to follow:**
- `src/protokit/_cli_utils.py:121-144` (current helper structure — reshape signature, remove `error_exit`)
- `src/protokit/_cli_utils.py:33-45` (`error_exit` shape — preserved in legacy wrapper)
- `tests/test_cli_utils.py:28-32` (`demo_proto_file` fixture pattern)
- `docs/solutions/security-issues/formatter-systemexit-exit-code-bypass-2026-04-19.md` lines 178-200 (CLI-level integration test pattern for SystemExit assertion)

**Test scenarios:**
- Happy path (helper): `_compile_with_protoxy([single_path], ())` returns `(pool, [single_root_name])`; pool contains the root file.
- Happy path (multi-path): `_compile_with_protoxy([a.proto, b.proto], ())` (no cross-imports) returns `(pool, [a.proto, b.proto])` in input order; pool contains both files.
- Edge case (cross-file imports): `_compile_with_protoxy([a.proto, b.proto], ())` where `b imports a` succeeds; both names appear in `root_names` in input order regardless of import direction.
- Edge case (deduped includes): `_compile_with_protoxy([dir/a.proto, dir/b.proto], ("dir",))` — include-path dedup leaves `("dir",)`, not duplicates.
- Edge case (same-basename collision): `_compile_with_protoxy([dir1/x.proto, dir2/x.proto], ())` raises `ValueError` with both paths cited in message.
- Edge case (root_names matcher): `_compile_with_protoxy([dir/util.proto], ("vendor",))` where `vendor/util.proto` is a transitively imported file — `root_names == ["dir/util.proto"]`, NOT `["dir/util.proto", "vendor/util.proto"]`.
- Error path (protoxy parse error): `_compile_with_protoxy([bad.proto], ())` raises `protoxy.ProtoxyError` with the parser stderr; does NOT call `error_exit`.
- Error path (legacy adapter): `compile_proto(bad.proto)` raises `SystemExit` with `code=2` via `error_exit`; stderr contains "compile failed:" prefix.
- Error path (legacy adapter, both backends absent): monkeypatch `_has_protoxy` to False AND simulate protoc missing → `compile_proto(any.proto)` raises `SystemExit(2)` with stderr containing "compile failed:" prefix.
- Integration (CLI exit-2): `CliRunner().invoke(protokit_main, ["compat", "check", str(bad.proto)])` returns `result.exit_code == 2` with stderr containing the helper failure message. (Replaces the old helper-level SystemExit test.)

**Verification:**
- All existing `tests/test_cli_utils.py` tests pass with rewritten signatures.
- `compile_proto(p)` still exits 2 on failure (compat callers preserved).
- New helpers raise typed exceptions; never call `error_exit`.
- `pytest tests/test_cli_utils.py -v` passes locally.
- `pytest tests/ -v` (full suite) passes — no regression in existing compat tests.
- **Stderr-string contract for legacy `compile_proto()` (per pass-3 acceptance criterion).** The legacy adapter emits the following stderr strings via `error_exit(...)`, one per caught exception class. Tests assert exact prefix substring matches. Adversarial F1 noted that today's helpers say `"protoxy failed:\n..."` and `"protoc failed:\n..."`; the legacy adapter under refactor catches MORE classes, so previously-uncaught classes now produce new strings. Locked text:

  | Caught class | error_exit prefix |
  |---|---|
  | `protoxy.ProtoxyError` | `"protoxy compile failed: "` (via the adapter's `except` clause; preserves "protoxy" verb) |
  | `ValueError` raised inside protoxy | `"protoxy compile failed: "` (same prefix — defensive over-catch retained for protoxy 0.7's documented-but-unreliable contract) |
  | `subprocess.CalledProcessError` | `"protoc compile failed: "` |
  | `FileNotFoundError` | `"compile backend missing: "` (NEW path — previously bubbled through `error_exit("protoc failed:\n...")` in current code per `_cli_utils.py:173`; stderr text shifts on this path) |
  | `OSError` (incl. `PermissionError`, `BrokenPipeError`) | `"compile infrastructure error: "` (NEW path — previously uncaught) |
  | `subprocess.TimeoutExpired` | `"compile infrastructure error: "` (same prefix as OSError; sibling tree but same UX category) |

  Tests in `tests/test_cli_utils.py` (post-rewrite) assert these prefixes via `result.stderr.startswith(prefix)` for each catch case. This makes the "stderr is best-effort" claim auditable rather than hand-wavy.

---

- [ ] **Unit 2: Create `src/protokit/schema/lint/` package + `model.py`**

**Goal:** Create the lint subpackage skeleton and the lint type system in `model.py`. Lock the dataclass shapes that every subsequent delivery imports against.

**Requirements:** R1

**Dependencies:** None (independent of Unit 1; can be done in parallel time-wise)

**Files:**
- Create: `src/protokit/schema/lint/__init__.py` (empty package marker)
- Create: `src/protokit/schema/lint/model.py`
- Test: `tests/schema/lint/__init__.py` (empty marker), `tests/schema/lint/test_model.py` (Unit 6)

**Approach:**
- `__init__.py`: empty marker. (No public re-exports yet — engine PR adds them.)
- `model.py` contents (in order):
  1. `from __future__ import annotations` + imports
  2. `EmitFn = Callable[[LintFinding], None]` typedef
  3. `LintSeverity(Enum)` — `ERROR | WARNING | INFO`
  4. `ElementKind(Enum)` — 8 values: `FILE, SERVICE, METHOD, ENUM, ENUM_VALUE, MESSAGE, FIELD, ONEOF`
  5. 8 `LintLocation` variant dataclasses + `LintLocation = Union[...]` type alias. Each variant: frozen, has stable `__str__`. (See High-Level Technical Design for the shape sketch.)
  6. `LintFinding` (frozen): `rule_id: str`, `severity: LintSeverity`, `location: LintLocation`, `violation_kind: str`, `params: dict[str, Any]` (default empty dict). NO `message` field.
  7. `LintReport` (frozen): `findings: tuple[LintFinding, ...] = ()`, `diagnostics: tuple["LintCompileDiagnostic", ...] = ()` (string forward reference — see below), `profiles_run: tuple[str, ...] = ()`, `rules_run: tuple[str, ...] = ()`. **Forward-reference (per pass-3 doc-review correction):** the `diagnostics` field references `LintCompileDiagnostic` defined in `schema/compile.py`. Use a **string forward reference** (`tuple["LintCompileDiagnostic", ...]`). Because `from __future__ import annotations` is project convention (every module starts with it per repo conventions), the type annotation is lazy at module-load time regardless of whether quoted strings are used. The `TYPE_CHECKING` alternative was considered and dropped — it's functionally indistinguishable here and adds an import block to maintain. NO runtime import of `schema.compile` in `model.py`; the cold-import contract holds by construction.
  8. `LintProfile` (frozen): `name: str`, `rule_ids: frozenset[str]`, `min_severity: LintSeverity = LintSeverity.WARNING`, `rule_severity_overrides: dict[str, LintSeverity] = field(default_factory=dict)`. `compose(*profiles: str | LintProfile) -> LintProfile` classmethod (resolves names, unions rule_ids, most-strict-wins on overrides). Tuple-snapshot pattern via `__post_init__` for `rule_ids` (per `profiles.py:138-153`).
  9. `LintRuleSpec` (frozen): `rule_id: str`, `severity: LintSeverity | dict[str, LintSeverity]`, `profiles: tuple[str, ...]`, `source_spec: str = ""`, `element: ElementKind = ElementKind.FIELD`, `message_template: str | dict[str, str] = ""`, `fn: Callable | None = None`. `severity_for(violation_kind: str) -> LintSeverity` method (single-kind: returns `self.severity` ignoring kind; multi-kind: dict lookup, raises `KeyError` for unregistered kind).
  10. `_LintContextEmitMixin` — non-dataclass mixin with `emit(*, violation_kind, params=None)` that delegates to `self._emit_fn(LintFinding(rule_id=self._rule_id, severity=self._effective_severity(violation_kind), location=self.location(), violation_kind=violation_kind, params=params or {}))`. `location() -> LintLocation` raises `NotImplementedError`.
  11. 8 frozen context dataclasses inheriting from `_LintContextEmitMixin`. Each declares: domain fields first (e.g., `field: FieldDescriptor`, `message: MessageDescriptor`, `file: FileDescriptor`, `pool: DescriptorPool`, `profile: str`), then engine-injected fields LAST: `_emit_fn: Callable[[LintFinding], None]`, `_rule_id: str`, `_effective_severity: Callable[[str], LintSeverity]`. Each overrides `location()` to return the correct LintLocation variant.
  12. `DuplicateRuleError(Exception)` — class with `def __init__(self, rule_id, first_fn, second_fn)` capturing both source locations in the message.

**Patterns to follow:**
- `src/protokit/schema/plugins.py:79-208` (frozen-dataclass + `_emit_fn` injection pattern; `EmitFn` typedef at module top)
- `src/protokit/schema/profiles.py:138-153` (tuple-snapshot via `__post_init__` for sequence fields)
- `src/protokit/schema/model.py:116-169` (frozen dataclass `__str__` override pattern)
- `src/protokit/message/model.py:78-125` (Diagnostic shape — for `level: Literal[...]` field annotation pattern)

**Test scenarios:** Defer to Unit 6 (`test_model.py`). This unit ships type definitions only; structural test coverage lands in Unit 6.

Test expectation for THIS unit: structural tests live in Unit 6; verification here is that `from protokit.schema.lint.model import *` succeeds without ImportError and ruff/mypy pass.

**Verification:**
- `python -c "from protokit.schema.lint.model import LintSeverity, LintLocation, LintFinding, LintReport, LintProfile, LintRuleSpec, ElementKind, FieldLintContext, OneofLintContext, DuplicateRuleError, _LintContextEmitMixin"` succeeds.
- `ruff check src/protokit/schema/lint/` passes.
- `mypy src/protokit/schema/lint/` passes (frozen-dataclass field ordering correct for Python 3.10).

---

- [ ] **Unit 3: Create `src/protokit/schema/compile.py` (compile module + LintCompileDiagnostic + 5-category dispatch)**

**Goal:** Create the public library compile entry point. Defines `LintCompileDiagnostic`, `CompileResult`, and `compile_protos_to_result()` with the 5-category catch tree and both-fail composition.

**Requirements:** R2, R4

**Dependencies:** Unit 1 (uses refactored multi-path raising helpers)

**Files:**
- Create: `src/protokit/schema/compile.py`
- Test: Units 4, 5

**Approach:**
- `compile.py` contents (in order):
  1. `from __future__ import annotations` + imports including `subprocess` and `protoxy` (lazy in the dispatch — not at module top, since protoxy is an optional dep)
  2. `LintCompileDiagnostic` frozen dataclass: `level: Literal["info", "warning", "error"]`, `message: str`, `command: tuple[str, ...] | None = None`, `exit_code: int | None = None`, `stderr: str | None = None`, `exception_type: str | None = None`. (No `source_file` field — dropped per scope-guardian #5.)
  3. `CompileResult` frozen dataclass: `pool: DescriptorPool` (non-optional), `root_files: tuple[str, ...]`, `diagnostics: tuple[LintCompileDiagnostic, ...]`.
  4. Internal diagnostic factories — small private helpers that build LintCompileDiagnostic from each exception class. Keeps the dispatch tree readable.
  5. `compile_protos_to_result(paths: Sequence[Path], proto_paths: tuple[str, ...] = ()) -> CompileResult` — the dispatch tree per the High-Level Technical Design pseudocode. Empty `paths` returns `CompileResult(pool=DescriptorPool(), root_files=(), diagnostics=())` (no error — semantically "compiled nothing").
  6. `_detect_same_basename_collision(paths)` private helper + pre-flight invocation in `compile_protos_to_result` BEFORE the per-backend dispatch (per pass-3 doc-review correction). On collision: return early with `CompileResult(pool=DescriptorPool(), root_files=(), diagnostics=(LintCompileDiagnostic(level="error", message=f"multi-path roots with same basename in different parent dirs is unsupported: {colliding_paths}", exception_type="SameBasenameCollision"),))`. This treats the case as a known input-validation error — distinct from the "unexpected backend exception" #5 catch-all and from the protoxy fallback path.
- BaseException posture: `try/except` chain catches `Exception` only. `KeyboardInterrupt`, `SystemExit`, `GeneratorExit` propagate. Documented inline.
- Catch order: `FileNotFoundError` → `CalledProcessError` → `OSError` → `TimeoutExpired` → `Exception`. Each except clause builds a `LintCompileDiagnostic` of the appropriate category and appends to local `diagnostics` list.
- Both-fail composition: when `protoxy.ProtoxyError`/`ValueError` is caught, append the `level="info"` fallback Diagnostic FIRST, then re-attempt via `_compile_with_protoc()`. If that re-attempt raises, the outer exception handlers catch it and append the second (failure) Diagnostic. Tuple ordering preserved: `[info-fallback, ...backend-failure]`.
- Empty pool on irrecoverable failure: if `pool` was never assigned (all backends failed before producing one), construct `pool = descriptor_pool.DescriptorPool()` (fresh, ZERO files registered — NOT WKTs).

**Patterns to follow:**
- `docs/solutions/security-issues/formatter-systemexit-exit-code-bypass-2026-04-19.md` lines 240-254 (architectural rule: compute verdict in core code, never let library raise SystemExit)
- `src/protokit/_cli_utils.py:33-45` (NOT followed — explicitly: `compile_protos_to_result` does NOT call `error_exit`)
- `src/protokit/message/model.py:78-125` (frozen dataclass with `Literal` field annotation — for `LintCompileDiagnostic.level`)

**Test scenarios:** Defer to Units 4, 5. This unit ships the dispatch tree; tests in Units 4-5 cover all 5 categories + both-fail composition + multi-path semantics.

Test expectation for THIS unit: covered by Unit 4 (multi-path) + Unit 5 (failure categories + fallback). Verification at this unit level is that imports succeed and ruff/mypy pass.

**Verification:**
- `python -c "from protokit.schema.compile import compile_protos_to_result, CompileResult, LintCompileDiagnostic"` succeeds.
- `ruff check src/protokit/schema/compile.py` passes.
- `mypy src/protokit/schema/compile.py` passes.
- Cold-import smoke: `python -c "import protokit.schema; import sys; assert 'protokit.schema.lint' not in sys.modules"` passes (verifies S2-2 fix held — `LintCompileDiagnostic` in `compile.py` doesn't drag in `lint/`).

---

- [ ] **Unit 4: Multi-path compile tests (`test_compile_multi.py`)**

**Goal:** REGRESSION-CRITICAL coverage of the multi-path compile contract: input-order preservation, cross-file imports, shared include path with vendored protos.

**Requirements:** R5

**Dependencies:** Unit 3 (uses `compile_protos_to_result`)

**Files:**
- Create: `tests/schema/lint/test_compile_multi.py`
- Create: `tests/schema/lint/fixtures/` directory + small `.proto` files as needed

**Approach:**
- Three tests, all parametrized over backends (`@pytest.mark.parametrize("force_backend", ["protoxy", "protoc"])`) using monkeypatch to control which backend runs (mirror `tests/test_cli_utils.py:131-150` dispatch test pattern).
- Use `tests/schema/helpers.py:T,M` for proto file generation OR write small `.proto` files into `tests/schema/lint/fixtures/`. Implementation chooses based on what's clearer.
- Fixture: `multi_protos_independent` (two protos in same dir, no cross-imports), `multi_protos_with_imports` (b imports a), `multi_protos_with_vendored` (root + vendored proto resolved via `proto_paths`).

**Patterns to follow:**
- `tests/test_cli_utils.py:55-107` (TestProtoxyBackend / TestProtocBackend test class pattern)
- `tests/test_cli_utils.py:131-150` (monkeypatch-based backend selection in dispatch tests)
- `tests/schema/test_cli.py:23-65` (descriptor-set-to-disk helpers if multi-path tests need them)
- `tests/schema/helpers.py:15-16` (T, M descriptor builder aliases)

**Test scenarios:**
- Happy path (independent multi-path) — input: two `.proto` files with no cross-imports; expected output: `result.root_files == (input_order_a, input_order_b)`; `result.pool.FindFileByName(a)` and `FindFileByName(b)` both succeed; `result.diagnostics == ()`.
- Edge case (cross-file imports, input order ≠ import order) — input: `[b.proto, a.proto]` where `b` imports `a`; expected: `result.root_files == (b.proto, a.proto)` (preserves input order, NOT topological); `result.pool.FindFileByName(a)` succeeds; `b`'s message descriptor reaches `a`'s message types via pool.
- Edge case (cross-file imports, import order = input order) — input: `[a.proto, b.proto]` where `b` imports `a`; expected: `result.root_files == (a.proto, b.proto)`; both compile; descriptors interlinked.
- Edge case (shared include path with vendored proto) — input: `paths=[user/main.proto]`, `proto_paths=("vendor",)`; `vendor/util.proto` is imported by `main`; expected: `result.root_files == (main.proto,)` (NOT including `util.proto`); `result.pool.FindFileByName("vendor/util.proto")` succeeds (it's in the pool, just not a root).
- Edge case (empty input) — input: `paths=()`; expected: `result.root_files == ()`, `result.pool` is a fresh empty `DescriptorPool` (FindFileByName for any name raises KeyError), `result.diagnostics == ()`.
- Edge case (same-basename pre-flight rejection — per pass-3 correction) — input: `[dir1/x.proto, dir2/x.proto]`; expected: `compile_protos_to_result` returns early WITHOUT invoking either backend. Returned `CompileResult` has `pool=DescriptorPool()` (empty), `root_files=()`, and `diagnostics == (LintCompileDiagnostic(level="error", message=<contains both paths>, exception_type="SameBasenameCollision"),)` — exactly ONE diagnostic. The pre-flight is at the `compile_protos_to_result` layer (per Unit 3); the helpers (Unit 1) have NO pre-flight responsibility.

**Verification:**
- All 3 multi-path tests pass on both backends.
- `pytest tests/schema/lint/test_compile_multi.py -v` passes.
- Tests assert specific contract details (input-order, KeyError on missing file, exception_type field) so future refactors can't silently regress.

---

- [ ] **Unit 5: Compile-failure tests (`test_compile_failure.py` + `test_compile_protoxy_fallback.py`)**

**Goal:** REGRESSION-CRITICAL coverage of all 5 compile-failure categories + the both-fail composition contract. Locks the "all `Exception` subclasses produce a `LintCompileDiagnostic`; `BaseException`-but-not-`Exception` propagates" invariant.

**Requirements:** R4, R6

**Dependencies:** Unit 3

**Files:**
- Create: `tests/schema/lint/test_compile_failure.py` (4 tests for categories #2, #3, #4, #5)
- Create: `tests/schema/lint/test_compile_protoxy_fallback.py` (2 tests for category #1 success + both-fail composition)

**Approach:**
- All 6 tests use the repo's monkeypatch-based simulation pattern (NOT `pytest.importorskip` for these specific tests — the tests directly exercise the dispatch tree's exception handling, so monkeypatch is the right tool).
- For `test_compile_protoxy_fallback.py`, the tests need protoxy importable to construct `protoxy.ProtoxyError` instances. Add `pytestmark = pytest.mark.skipif(not _cli_utils._has_protoxy(), reason="optional [compiler] extra not installed")` at module top — this test module is skipped on the `has_protoxy: false` CI cell. (Same skip reason as `TestProtoxyBackend` in Unit 1.)
- **`protoxy.ProtoxyError` constructor (per pass-3 doc-review verification):** `ProtoxyError.__init__(self, message, details, json_details)` requires THREE positional arguments — `protoxy.ProtoxyError("synthetic")` will fail with `TypeError`. Use a small test helper: `def _make_protoxy_error(msg: str) -> protoxy.ProtoxyError: return protoxy.ProtoxyError(msg, [], "[]")`. Define once at the top of `test_compile_protoxy_fallback.py` and reuse across the 2 fallback tests.
- For `test_compile_failure.py`, the tests synthesize exceptions from non-protoxy classes (CalledProcessError, FileNotFoundError, OSError, TimeoutExpired, RuntimeError) which don't require protoxy — module runs on every CI cell.
- BaseException propagation test: synthesize `KeyboardInterrupt` from a mocked backend; assert `compile_protos_to_result(paths)` does NOT catch it (pytest.raises captures the propagation). Verifies the explicit BaseException posture.

**Patterns to follow:**
- `tests/test_cli_utils.py:131-170` (monkeypatch backend dispatch + missing-protoc simulation)
- `tests/test_cli_utils.py:165-170` (FileNotFoundError simulation via `subprocess.run` monkeypatch)

**Test scenarios:**

`test_compile_failure.py`:
- Error path (category #2 — protoc subprocess error) — monkeypatch `_has_protoxy()` to False; monkeypatch `subprocess.run` to raise `subprocess.CalledProcessError(returncode=1, cmd=["protoc", ...], stderr=b"<error msg>")`. Expected: `compile_protos_to_result(paths)` returns `CompileResult` with `root_files=()`, `pool` is empty, `diagnostics` has exactly one `LintCompileDiagnostic` with `level="error"`, `command=("protoc", ...)`, `exit_code=1`, `stderr="<error msg>"`, `exception_type="CalledProcessError"`.
- Error path (category #3 — both backends absent) — monkeypatch `_has_protoxy()` to False; monkeypatch `subprocess.run` to raise `FileNotFoundError("protoc not found")`. Expected: `level="error"`, `message` contains install hint text ("pip install protoxy" or "system protoc"), `exception_type="FileNotFoundError"`.
- Error path (category #4 — OSError + TimeoutExpired siblings) — synthesize each: `PermissionError`, `BrokenPipeError`, `subprocess.TimeoutExpired`. Three sub-cases (use `parametrize`). Expected: `level="error"` with `exception_type` matching the synthesized class; `message` contains an "infrastructure" label. **Defensive coverage note (per pass-3 doc-review):** Today's `_compile_with_protoc` does NOT pass `timeout=` to `subprocess.run` (`_cli_utils.py:164`), so `TimeoutExpired` is unreachable in current production paths. The catch clause + test are kept as defensive coverage for the future case where a `timeout=` kwarg is added. Documented inline in `compile.py` so a future contributor adding the timeout doesn't accidentally remove the catch as "dead code."
- Error path (category #5 — unexpected catch-all) — synthesize each: `RuntimeError("synthetic")`, `ImportError("synthetic")`, `MemoryError("synthetic")`, plus `pool.Add(malformed_fd)` raising `TypeError`. Four sub-cases (use `parametrize`). Expected: `level="error"`, `message=f"unexpected backend exception: {repr(exc)}"`, `exception_type=<class name>`.
- Edge case (BaseException propagates) — synthesize backend raising `KeyboardInterrupt`; assert `pytest.raises(KeyboardInterrupt)` when calling `compile_protos_to_result(paths)`. Verifies the explicit posture — KeyboardInterrupt is NOT converted to a Diagnostic.

`test_compile_protoxy_fallback.py` (module gated on `_has_protoxy()`):
- Happy path (category #1 success) — monkeypatch `protoxy.compile()` to raise `protoxy.ProtoxyError("synthetic parse error")`; let real protoc handle the fallback (or monkeypatch `_compile_with_protoc` to succeed). Expected: `compile_protos_to_result(paths)` returns `CompileResult` with `pool` populated, `root_files` populated, `diagnostics == (LintCompileDiagnostic(level="info", message=<contains "fallback">, exception_type="ProtoxyError", ...),)`. Exactly ONE info diagnostic.
- Edge case (both-fail composition: info + #2) — monkeypatch `protoxy.compile()` to raise `ProtoxyError`; monkeypatch `subprocess.run` to raise `CalledProcessError`. Expected: `result.diagnostics == (info_fallback_diag, protoc_error_diag)` IN THIS ORDER (info first per A2-2). `pool` is empty; `root_files == ()`.
- Edge case (both-fail composition: info + #4) — protoxy raises `ProtoxyError`, then `subprocess.run` raises `subprocess.TimeoutExpired`. Expected: `result.diagnostics == (info_fallback_diag, infrastructure_diag)` in order.
- Edge case (both-fail composition: info + #5) — protoxy raises `ProtoxyError`, then `_compile_with_protoc` somehow raises `RuntimeError`. Expected: `result.diagnostics == (info_fallback_diag, unexpected_diag)` in order.
- *(Both-fail composition: info + #3 — UNREACHABLE per pass-3 doc-review analysis. The fallback path is invoked only when protoxy IS available (raised ProtoxyError); but category #3 fires when neither backend is installed (`FileNotFoundError`). These preconditions are mutually exclusive — protoxy availability implies #3's precondition is false. No test needed.)*

**Verification:**
- All 6 tests pass on both `has_protoxy: true` and `has_protoxy: false` CI cells (with `test_compile_protoxy_fallback.py` skipping on the `false` cell via the module-level `pytestmark`).
- Tests assert specific `LintCompileDiagnostic` field shapes per category — formatters consuming `result.diagnostics` programmatically can rely on which fields are populated for which `level`/`exception_type`.
- Both-fail tests lock the diagnostic-ordering invariant (info first).

---

- [ ] **Unit 6: Structural model tests (`test_model.py`)**

**Goal:** Lock the contracts that downstream deliveries (engine, CLI, formatters) will load-bear on. Cover `compose()`, `severity_for()`, all 8 `LintLocation.__str__`, frozen-context instantiation, `DuplicateRuleError`, `LintFinding`/`LintReport`, and enum value assertions.

**Requirements:** R7

**Dependencies:** Unit 2 (lint model.py), Unit 3 (LintCompileDiagnostic — referenced indirectly via LintReport)

**Files:**
- Create: `tests/schema/lint/test_model.py`

**Approach:**
- 10-12 tests organized into `class TestX:` namespaces (per repo convention). Mirror `tests/schema/test_model.py:23-99` factory pattern.
- Module-level helpers: `_make_field_ctx(**user_kwargs) -> FieldLintContext` mints a context with engine-injected fields **defaulted as keyword arguments inside the helper body** so callers don't need to specify them. Per pass-3 doc-review verification: the engine-injected fields (`_emit_fn`, `_rule_id`, `_effective_severity`) have NO defaults on the dataclass itself (production engine always supplies them); the test helper provides stub defaults. Implementation: `def _make_field_ctx(**user_kwargs): defaults = {"_emit_fn": lambda f: None, "_rule_id": "TEST", "_effective_severity": lambda kind: LintSeverity.WARNING}; return FieldLintContext(**{**defaults, **user_kwargs})`. Same shape for the other 7 contexts. Domain fields (e.g., `field`, `message`, `file`, `pool`) MUST be supplied by the caller — the helper does not synthesize protobuf descriptors. Tests pass real or fake descriptors via `tests/schema/helpers.py:T,M`.

**Patterns to follow:**
- `tests/schema/test_model.py:23-99` (factory pattern, frozen-instance test, enum value test)
- `src/protokit/schema/plugins.py:79-208` (correct context shape — tests verify it matches)

**Test scenarios:**
- Happy path — `LintProfile.compose()` (zero-arg) returns identity profile (`name="composed"`, empty rule_ids, default min_severity).
- Happy path — `LintProfile.compose("default")` (single arg) returns the named profile (assumes `default` profile exists in test setup; if not, use a constructed `LintProfile` instance).
- Happy path — `LintProfile.compose(profile1, profile2)` where both are `LintProfile` instances: `rule_ids = profile1.rule_ids | profile2.rule_ids`; `rule_severity_overrides` merges with most-strict-wins (ERROR > WARNING > INFO).
- Edge case — `LintProfile.compose()` with conflicting overrides: profile1 says `{"R1": INFO}`, profile2 says `{"R1": ERROR}`; composed result has `{"R1": ERROR}`.
- Happy path — `LintRuleSpec(severity=LintSeverity.WARNING, ...).severity_for("any_kind")` returns `LintSeverity.WARNING` (single-kind ignores arg).
- Happy path — `LintRuleSpec(severity={"k1": ERROR, "k2": WARNING}, ...).severity_for("k1")` returns `LintSeverity.ERROR`.
- Error path — `LintRuleSpec(severity={"k1": ERROR}, ...).severity_for("unregistered")` raises `KeyError`.
- Happy path — `__str__` for all 8 LintLocation variants returns deterministic strings (`FileLocation("a.proto").__str__() == "a.proto"`, `FieldLocation("a.proto", "M", "f").__str__() == "a.proto:M.f"`, etc. — exact format determined by implementation, asserted by test).
- Happy path — frozen context instantiation: `_make_field_ctx(field=<desc>, message=<desc>, file=<desc>, pool=<pool>, profile="test")` succeeds with all 8 contexts.
- Edge case — frozen-context immutability: `pytest.raises(Exception)` (covers `FrozenInstanceError`) when attempting to mutate any context's domain field.
- Happy path — `DuplicateRuleError("R1", first_fn, second_fn)` constructs cleanly; `isinstance(err, Exception) is True`; `str(err)` contains both qualified function names.
- Happy path — `LintFinding(rule_id="R1", severity=ERROR, location=FileLocation("a.proto"), violation_kind="kind", params={})` and `LintReport(findings=(finding,))` both instantiate; equality semantics: identical params → equal instances.
- Happy path — enum value assertions: `{e.value for e in LintSeverity} == {"error", "warning", "info"}`; `{e.value for e in ElementKind} == {"file", "service", "method", "enum", "enum_value", "message", "field", "oneof"}`.

**Verification:**
- All 10-12 tests pass.
- `pytest tests/schema/lint/test_model.py -v` runs cleanly.
- `LintReport` instantiation with `diagnostics=tuple(LintCompileDiagnostic instances)` works at runtime — proves the string forward-reference resolves correctly when callers from `schema/compile.py` instantiate `LintReport`. Cold-import contract still holds (no circular import).

---

- [ ] **Unit 7: Protoxy-import audit (collapsed per pass-3 doc-review)**

**Goal:** Confirm there are no module-top `import protoxy` calls outside the two locations already handled by Units 1 and 5. Pass-3 review verified (`grep -rn "^import protoxy\|^from protoxy" tests/` returns zero results today) — the audit's actionable deliverable reduces to the `pytestmark` guards already specified in Units 1 (`TestProtoxyBackend`) and 5 (`test_compile_protoxy_fallback.py`).

**Requirements:** R10

**Dependencies:** Units 1 and 5 (which contain the actual skip-guard additions)

**Files:**
- Modify: none new (skip guards live in Units 1 and 5)

**Approach:**
- Run `grep -rn "^import protoxy\|^from protoxy" tests/` to confirm zero results in the production test tree (pass-3 verified). Re-run pre-merge as a check.
- ALSO grep for transitive-call sites that call refactored helpers from test code: `grep -rn "_compile_with_protoxy\|_compile_with_protoc" tests/` — any test calling these directly on a `has_protoxy: false` environment would `ImportError` at runtime when the helper does `import protoxy`. The class-level `pytestmark` on `TestProtoxyBackend` (Unit 1) covers the only existing call site.
- Document the new convention in a 4-6 line comment block at the top of `tests/test_cli_utils.py` (the canonical example). Skip `tests/CONVENTIONS.md` for this delivery — single-convention doc is overkill; revisit if a second test convention surfaces.

**Patterns to follow:** see Units 1 and 5.

**Test scenarios:**

Test expectation: none — audit unit; verification is at CI level on the `has_protoxy: false` cell.

**Verification:**
- `grep -rn "^import protoxy\|^from protoxy" tests/` returns only test files that have either a `pytestmark = pytest.mark.skipif(...)` or `pytest.importorskip("protoxy")` at module top.
- `grep -rn "_compile_with_protoxy" tests/` — every match is in a test class with the `pytestmark` guard.
- CI `has_protoxy: false` cell does NOT report collection errors.

---

- [ ] **Unit 8: CI workflow (`.github/workflows/ci.yml`)**

**Goal:** Create CI from scratch with 4-job matrix and cold-import smoke step. Lands as dormant config until a remote is configured + push happens.

**Requirements:** R9, R11

**Dependencies:** Units 1-7 (CI runs the full test suite)

**Files:**
- Create: `.github/workflows/ci.yml`

**Approach:**
- `.github/` directory does not currently exist; create it.
- `ci.yml` structure (greenfield — no existing CI to mirror):
  - Triggers: `push` to `main`, `pull_request` to `main`. (Eventually customize once remote is configured.)
  - Single `test` job with matrix: `python: ["3.10", "3.12"]` × `has_protoxy: [true, false]` = 4 jobs.
  - Steps:
    1. `actions/checkout@v4`
    2. `actions/setup-python@v5` with `python-version: ${{ matrix.python }}`
    3. `sudo apt-get update && sudo apt-get install -y protobuf-compiler` (every cell — protoc on PATH always; `sudo` is required on `ubuntu-latest` runners; pair with `apt-get update` to refresh package index since GHA runner images can have stale apt cache)
    4. Conditional install: `pip install -e ".[dev]"` if `has_protoxy: false`; `pip install -e ".[compiler,dev]"` if `has_protoxy: true`. Use `if: matrix.has_protoxy == true` in step `if` clauses.
    5. Cold-import smoke: `python -c "import protokit.schema; import sys; assert 'protokit.schema.lint' not in sys.modules, sorted(k for k in sys.modules if 'protokit' in k)"`. Runs after install, before pytest. **Note (per pass-3 doc-review):** This smoke step validates TODAY's transitive imports — it is a snapshot, not an invariant. Future deliveries that add eager imports may regress unless they also update the smoke step's assertion target. Add to `docs/solutions/` checklist for any delivery touching `schema/__init__.py` or `schema/compile.py`.
    6. **Sanity: `pip list | grep protoxy` on `has_protoxy: false` cells** (per pass-3 doc-review arm64/wheel-availability hedge) — fails the job loudly if any dev dep transitively pulls protoxy. Cheap insurance against the matrix collapsing to an effective single cell.
    7. `pytest tests/ -v` — full test suite.
- Comments in YAML explaining: matrix rationale (3.10 floor + 3.12 ceiling per A9), `has_protoxy` axis semantics (per F6/F7), cold-import smoke step purpose (per F8/S7), system protoc installation note ("apt-get default 3.21.x is sufficient for proto3 fixtures; pin to v25+ if Edition 2023 fixtures land later").

**Patterns to follow:**
- No existing CI in repo; greenfield.
- Standard GitHub Actions Python project shape (checkout → setup-python → install deps → run tests).

**Test scenarios:**

Test expectation: none — this is configuration. Verification is at CI execution level (which happens after a remote is configured + push).

**Verification:**
- `cat .github/workflows/ci.yml | yq` (or similar YAML lint) parses without errors.
- The 4 matrix combinations are explicit and complete (`(3.10, true), (3.10, false), (3.12, true), (3.12, false)`).
- Cold-import smoke step references the locked symbol path (`protokit.schema.lint`).
- The `if: matrix.has_protoxy` conditional is syntactically valid.
- Workflow file lands without breaking anything (no remote = workflow doesn't fire = no CI noise).
- Future verification: when a remote is configured and push happens, all 4 jobs pass green.

## System-Wide Impact

- **Interaction graph:** The legacy `compile_proto()` is consumed by `protokit/schema/cli.py` (compat command), `protokit/schema/git.py:830` (git ref resolution), and `protokit/message/cli.py:271` (diff command). Refactoring the underlying helpers preserves `compile_proto`'s public contract (signature unchanged, exit-on-failure preserved), so these callers see no behavior change. The new `compile_protos_to_result()` has zero existing consumers (lint engine in Delivery 2 is the first).
- **Error propagation:** Library code (`compile_protos_to_result`, lint model methods) raises `Exception`-rooted typed errors. CLI code (`compile_proto`, future `protokit lint` CLI command in Delivery 3) is the only layer that translates errors to process exit. This is the architectural rule documented in `docs/solutions/security-issues/formatter-systemexit-exit-code-bypass-2026-04-19.md` lines 240-254 — apply preventively in every layer of this delivery.
- **State lifecycle risks:** Frozen dataclasses throughout (no mutable instance state). Engine-injected callable fields are set once at construction (not mutated post-init). The tuple-snapshot pattern in `LintProfile` defends against caller-supplied lists. No partial-write or cleanup concerns.
- **API surface parity:** The `LintCompileDiagnostic` shape is the contract every Delivery 1+ consumer (engine, formatters, plugins) builds against. Field-presence guarantees are documented per category in the requirements doc and inline in code via docstrings. Adding fields later (e.g., `source_file` if a formatter eventually needs it) is strictly additive — no breaking change.
- **Integration coverage:** Multi-path tests (Unit 4) and both-fail composition tests (Unit 5) are integration tests covering the dispatch tree end-to-end. The legacy `compile_proto()`'s SystemExit behavior is covered by the relocated CLI integration test in Unit 1. Cold-import contract is covered by the CI smoke step (Unit 8) — every push validates `protokit.schema` doesn't drag `lint/` in.
- **Unchanged invariants:**
  - `protokit/__init__.py` no-top-level-reexports policy (line 13) remains intact. `compile_protos_to_result` lives in `schema/compile.py`, not re-exported through `protokit/__init__.py`.
  - `protokit/formatters/__init__.py` eager-import block (lines 63-71) is NOT modified. `_builtin_lint` registration (Delivery 4) will be lazy.
  - Existing `Diagnostic` shape at `message/model.py:79` is unchanged.
  - `compile_proto()` public signature `(proto_path: Path, proto_paths: tuple[str, ...]) -> DescriptorPool` is unchanged.

## Risks & Dependencies

| Risk | Mitigation |
|---|---|
| Helper refactor introduces subtle behavior change in `compile_proto()` (e.g., error-message text drift, set-ordering surfacing in stderr-snapshot tests) | Pre-flight: grep `tests/` for any test asserting on stderr containing `"protoxy failed"` or similar legacy strings. Update if found. The Unit 1 verification step runs the full `pytest tests/ -v` to catch any regression. |
| `_expected_root_names()` matcher edge cases (paths not under any include, absolute paths) | Documented as "Deferred to Implementation" in Open Questions. Implementation discovers exact algorithm during test write-up; the multi-path tests in Unit 4 lock the contract. |
| `apt-get install protobuf-compiler` provides protoc 3.21.x on ubuntu-latest, insufficient for Edition 2023 protos | Current fixtures are proto3; not blocking. Documented in `ci.yml` comments as a constraint. Pin to v25+ via binary install if Edition 2023 fixtures land in a future delivery. |
| GitHub Actions cannot be tested before a remote is configured | Workflow file lands with a careful design but cannot be debugged until the first push. Implementation reviews the YAML against the GitHub Actions docs; matrix syntax follows established patterns. Mitigation: run `actionlint` (Go binary or pre-commit hook) for static YAML validation before merge — catches typos, invalid action versions, expression-syntax errors at near-zero cost. Runtime validation deferred to first push. Risk-residual: accepted. |
| Effort estimate vs project's 2x historical underrun pattern (per pass-3 adversarial F9 + scope-guardian F9) | Range widened to **18-36 hr** with 36 as realistic target. Escalation threshold at 50 hr. The widened range absorbs the project's historical pattern without committing to a specific cause; mid-flight discoveries (root_names matcher edge cases, stderr-string drift, test-relocation audit findings) absorbed within range. |

## Documentation / Operational Notes

- **CHANGELOG entry:** Add a brief entry to `docs/solutions/` (or repo CHANGELOG if one exists — none does today) capturing: (a) the empirical `DescriptorPool()` + WKTs finding (corrected design assumption), (b) the layering correction (helpers now raise, legacy adapter handles error_exit), (c) the new `pytest.mark.skipif(not _has_protoxy(), ...)` test-skip convention. Per learnings-researcher recommendation (#4 in their findings).
- **`tests/CONVENTIONS.md`** (NEW) — optional. Lightweight document capturing the new test-skip convention so future contributors don't have to grep for it. Implementation chooses based on whether other test conventions also need formalization at the same time.
- **No README updates** — `README.md` updates land in Delivery 8 (step 12 — README rewrite + CHANGELOG entry per the design doc's Next Steps).
- **No rollout / monitoring concerns** — internal library code; no production deployment; no metrics to instrument. Implementation publishes to PyPI as part of the existing `gh release` + `pip upload` flow (Distribution Plan in design doc).

## Sources & References

- **Origin document:** [docs/brainstorms/2026-04-30-protokit-lint-delivery-1-foundation-requirements.md](docs/brainstorms/2026-04-30-protokit-lint-delivery-1-foundation-requirements.md)
- **Upstream design (APPROVED):** `~/.gstack/projects/python_message_differencer/marc-main-design-20260424-113550.md` (status: APPROVED after codex outside-voice + 2 document-review passes; carries 28 closed Open Questions covering S3-1A through S3-3C + T1-T6 + delivery-1 review refinements)
- **Related code:**
  - `src/protokit/_cli_utils.py:71-177` (helpers being refactored)
  - `src/protokit/schema/plugins.py:79-208` (frozen-dataclass + `_emit_fn` injection pattern to mirror)
  - `src/protokit/schema/profiles.py:138-153` (tuple-snapshot pattern)
  - `src/protokit/message/model.py:78-125` (existing `Diagnostic` shape — NOT reused for compile-time)
  - `src/protokit/__init__.py:13` (no-reexports policy honored by `schema/compile.py`)
  - `src/protokit/formatters/__init__.py:63-71` (eager-import block NOT modified)
- **Related tests:**
  - `tests/test_cli_utils.py:1-183` (8 tests rewritten in Unit 1)
  - `tests/schema/test_model.py:23-99` (frozen-dataclass test pattern to mirror in Unit 6)
  - `tests/schema/test_cli.py:23-65, 81-150` (descriptor-builder helpers + CLI integration test pattern)
  - `tests/schema/helpers.py:15-16` (`T`, `M` descriptor builder aliases)
- **Institutional learnings:**
  - `docs/solutions/security-issues/formatter-systemexit-exit-code-bypass-2026-04-19.md` (architectural rule: compute verdict in core code, never let library raise SystemExit; CLI integration test pattern; `except (SystemExit, Exception)` policy at plugin boundaries — last applies to Delivery 2)
- **External references:** None used — local patterns sufficient per ce:plan Phase 1.2 decision.
