# Requirements — protokit-lint Delivery 1 (Foundation)

Created: 2026-04-30
Source design: `~/.gstack/projects/python_message_differencer/marc-main-design-20260424-113550.md` (status: APPROVED)
Step in design's Next Steps: **Step 2 — Skeleton + compile module + multi-path tests + CI matrix**
Estimated effort: **~18-26 CC hours** (re-baselined twice — 2026-04-30 from 5-6 → 7-8, 2026-05-01 from 7-8 → 18-26 after pass-2 doc-review surfaced unbudgeted work). Bottom-up: ~3 hr `model.py` for 25-30 type defs incl. 8 location `__str__`; ~2 hr `compile.py` (CompileResult + LintCompileDiagnostic + 5-category dispatch); ~3 hr `_cli_utils.py` helper refactor + concrete bug fixes (set ordering via `dict.fromkeys`, root_names matcher via protoxy-resolution, BaseException posture, TimeoutExpired hierarchy); ~8 hr new tests (9 compile cases + 6 model cases × mocking ordering complexity for fallback paths); **~2-4 hr existing-test rewrites in `tests/test_cli_utils.py`** (8 tests: re-targeted at corrected layering — helper raises; one moved to CLI integration level for SystemExit assertion); **~1 hr protoxy-import audit** (per A9-1: existing tests need `pytest.importorskip("protoxy")` guards or matrix-skip for `has_protoxy: false` cells); ~3 hr CI from scratch (4-job matrix, conditional protoc install, cold-import smoke step, push-wait-debug cycles though debugging happens after remote setup).

## Goal

Land the foundational types, helper, and verification scaffolding for protokit-lint v1. **No user-visible CLI public behavior change** — `protokit compat ...` exit codes, error message ladders, and overall flow are preserved bit-for-bit (the legacy `compile_proto()` wrapper preserves the existing `error_exit` shape). Internally, the architecture corrects a long-standing layering bug: helpers move from "process-exit on error (CLI-flavored)" to "raise on error (library-shaped)" with the legacy adapter providing the CLI surface. This is a prerequisite for the library-first direction the project has been moving toward since T5. Every subsequent delivery (engine, CLI, formatters, rule packs) imports against locked types and the corrected helper signatures from this PR.

## Out of Scope (deferred to later deliveries)

- Engine implementation (Delivery 2 — step 3)
- `@lint_rule` decorator and `LintEngine` (Delivery 2)
- Any actual rules (Delivery 5+ — steps 7-8)
- CLI (`protokit lint` command) (Delivery 3 — step 4)
- Formatters / `_builtin_lint.py` (Delivery 4 — step 5)
- pyproject.toml `[tool.protokit.lint]` config + `--exclude` filtering (Delivery 5 — step 6)
- `tomli` dependency (added in step 6, not here)
- Plugin API + `--lint-rule-pack` / `--compat-rule-pack` flags (Delivery 7 — step 9)

## Acceptance Criteria

### New files

| Path | Purpose |
|---|---|
| `src/protokit/schema/lint/__init__.py` | Package marker; intra-subpackage public re-exports only |
| `src/protokit/schema/lint/model.py` | All lint-side dataclasses (see "Types to define" below) |
| `src/protokit/schema/compile.py` | NEW public module; `compile_protos_to_result()` + `CompileResult` |
| `tests/schema/lint/__init__.py` | Package marker |
| `tests/schema/lint/test_compile_multi.py` | 3 multi-path REGRESSION-CRITICAL tests (S3-3A) |
| `tests/schema/lint/test_compile_failure.py` | 4 distinct-Diagnostic tests (S3-1G items 5-8 below: protoc subprocess error, both-backends-absent, OSError, **NEW** unexpected-exception catch-all) |
| `tests/schema/lint/test_compile_protoxy_fallback.py` | 2 fallback tests (item 4 success path; **NEW** item 9 both-fail composition emitting BOTH info + error Diagnostics), mocked |
| `tests/schema/lint/test_model.py` | **NEW** structural model tests (per scope-guardian S2 + feasibility F9): `LintProfile.compose()`, `LintRuleSpec.severity_for()` for both single and multi-kind, all 8 `LintLocation.__str__` outputs, frozen-dataclass instantiation of all 8 contexts (with engine-injected fields), `DuplicateRuleError` constructibility, `LintFinding`/`LintReport` instantiation. ~6-10 small tests. |
| `tests/schema/lint/fixtures/*.proto` | Whatever the multi-path tests need |
| `.github/workflows/ci.yml` | NEW; py3.10 + py3.12 × has_protoxy: [true, false] matrix (4 jobs) — see CI workflow section for axis semantics |

### Existing files modified (corrected layering — pass-2 doc-review)

| Path | What changes | Why |
|---|---|---|
| `src/protokit/_cli_utils.py` | Refactor `_compile_with_protoxy` and `_compile_with_protoc` to multi-path + raising signature (per F1=A). Legacy `compile_proto()` becomes thin wrapper preserving `error_exit` behavior for compat callers. Catch-order: FileNotFoundError → CalledProcessError → OSError → TimeoutExpired (under SubprocessError) → Exception (BaseException not caught per A2-1). Use `dict.fromkeys()` for include-path dedup (NOT `set` — set ordering is non-deterministic per F1-1). | Single source of truth between legacy compat and new lint; corrects layering (library raises, CLI exits). |
| `tests/test_cli_utils.py` | Rewrite 8 tests to target corrected layering: 3 protoxy-backend tests now construct via `_compile_with_protoxy([path], ip)` and assert raising semantics on failure; `test_compile_failure_exits_with_code_2` MOVES to a CLI integration test (`tests/schema/test_cli_integration.py` — assert `protokit compat <bad.proto>` exits 2 — covers the same surface but at the right layer); `TestProtoxyBackend` class gets `pytestmark = pytest.mark.skipif(not _has_protoxy(), reason="optional [compiler] extra not installed")` for the `has_protoxy: false` CI cell. | Pass 2 found these tests assert wrong-layer behavior (helper-level SystemExit). Refactor exposes the layering bug; rewrite corrects it. |
| `tests/test_*.py` (any others importing protoxy at module top) | Audit + add `pytest.importorskip("protoxy")` at module top OR `pytestmark` skipif guards. | A9-1: `has_protoxy: false` CI cells fail at collection if any test module has `import protoxy` without a guard. |

### Types to define in `src/protokit/schema/lint/model.py`

Per the locked design (codex-verified APPROVED):

- `LintSeverity` enum (`ERROR | WARNING | INFO`)
- `LintLocation` discriminated union: `FileLocation | ServiceLocation | MethodLocation | EnumLocation | EnumValueLocation | MessageLocation | FieldLocation | OneofLocation` — each frozen dataclass with stable `__str__`
- `LintFinding` (frozen dataclass): `rule_id, severity, location, violation_kind, params` — **no `message` field** (S3-1C)
- `LintReport` (frozen dataclass): `findings, diagnostics, profiles_run, rules_run`
- `LintProfile` (frozen dataclass): `name, rule_ids, min_severity, rule_severity_overrides`; `compose(*profiles)` classmethod (S3-1D)
- `LintRuleSpec` (frozen dataclass): `rule_id, severity: LintSeverity | dict[str, LintSeverity], profiles, source_spec, element, message_template: str | dict[str, str], fn`; `severity_for(violation_kind)` method (S3-1C-followup, severity authority)
- `ElementKind` enum, **8 values** including `ONEOF` (S3-1B)
- `_LintContextEmitMixin` + 8 frozen context dataclasses (`File`, `Service`, `Method`, `Enum`, `EnumValue`, `Message`, `Field`, `Oneof`); each declares `_emit_fn`, `_rule_id`, `_effective_severity` as **explicit** fields (codex P0 finding LINT-DESIGN-CTX-INJECTION fix); each overrides `location()`
- `DuplicateRuleError` (raised by `LintEngine.load_rule_pack`, ships in this delivery's model so engine PR can import without recursive churn)

(**`LintCompileDiagnostic`** is NOT in `lint/model.py` — it lives in `schema/compile.py` per S2-2 cold-import-contradiction fix 2026-05-01. See `compile.py` types section below.)

### Types/functions in `src/protokit/schema/compile.py`

- **`LintCompileDiagnostic`** (frozen dataclass, per A3 + S2-2 decisions): structured-fields dataclass for compile-time diagnostics. Located here (next to `CompileResult`, its sole consumer) instead of `lint/model.py` per S2-2 cold-import-contradiction fix — keeping it in `lint/model.py` would force `from protokit.schema.compile import CompileResult` to transitively pull in `protokit.schema.lint`, breaking the cold-import contract for `protokit compat` by construction. Distinct from `message.model.Diagnostic` (which is diff-time and uses `path` as a dotted message-tree path). Fields: `level: Literal["info","warning","error"]`, `message: str`, `command: tuple[str, ...] | None = None`, `exit_code: int | None = None`, `stderr: str | None = None`, `exception_type: str | None = None`. ~25 LOC. (No `source_file` field — dropped per scope-guardian #5 as speculative; add when first formatter consumer surfaces.)
- `CompileResult` (frozen dataclass): `pool: DescriptorPool` (non-optional but **may be a fresh pool with zero files registered** on irrecoverable failure — empirically verified 2026-04-30: `DescriptorPool()` does NOT contain WKTs by default), `root_files: tuple[str, ...]` (empty tuple on irrecoverable failure), `diagnostics: tuple[LintCompileDiagnostic, ...]` — codex P1 finding LINT-DESIGN-COMPILE-RESULT-OPTIONAL-POOL fix. The contract: engine consumers iterate `root_files` and never call `pool.FindFileByName()` when `root_files=()`, so the empty-pool failure path is safe by construction. **Other consumers** (formatters, future plugins) querying the pool directly MUST handle `KeyError` for any name they didn't load themselves. The upstream design doc claims "pool contains WKTs" — corrected in same-day update to design doc lines 19, 660.
- `compile_protos_to_result(paths: Sequence[Path], proto_paths: tuple[str, ...] = ()) -> CompileResult` — multi-path compile with runtime protoxy→protoc fallback; emits **5 distinct LintCompileDiagnostic categories** per A2 review decision 2026-05-01 (was 4 in S3-1G — added unexpected-exception catch-all + both-fail composition). `paths` is an ordered sequence of root .proto file paths (all roots batched into a single backend invocation, not iterated one-at-a-time). `proto_paths` is the include-path tuple (`-I`-style search dirs for cross-file imports). Returns CompileResult with `root_files: tuple[str, ...]` preserving input order and using the .proto-relative names protoxy/protoc emit (not absolute paths). Empty `paths` → returns `CompileResult(pool=DescriptorPool(), root_files=(), diagnostics=())` (no error — semantically "compiled nothing").

### Five distinct compile-failure categories (per A2 decision 2026-05-01; refined 2026-05-01 pass-2 doc-review)

| # | Category | Trigger (caught classes) | Populated fields | None fields |
|---|---|---|---|---|
| 1 | protoxy parse-error → protoc fallback succeeds | `protoxy.ProtoxyError`, `ValueError` from protoxy.compile | `level="info"`, `message="protoxy parse error; falling back to protoc"`, `exception_type=<protoxy exc class>` | `command`, `exit_code`, `stderr` |
| 2 | protoc subprocess error | `subprocess.CalledProcessError` (and `subprocess.SubprocessError` parent — see note below) | `level="error"`, `message="protoc compilation failed"`, `command=(argv,)`, `exit_code=N`, `stderr=verbatim`, `exception_type="CalledProcessError"` | (none — all populated) |
| 3 | Backend missing | `FileNotFoundError` (no protoxy AND no protoc on PATH) | `level="error"`, `message="<install hint: pip install protoxy or system protoc>"`, `exception_type="FileNotFoundError"` | `command`, `exit_code`, `stderr` |
| 4 | OS / subprocess infrastructure | `OSError` + subclasses (`PermissionError`, `BrokenPipeError`, etc.) AND `subprocess.TimeoutExpired` (sibling under `SubprocessError`, NOT under `OSError` — both classes caught explicitly per F3 review-pass correction) | `level="error"`, `message="<infrastructure label: backend timed out / permission denied / ...>"`, `exception_type=<exc class name>` | `command`, `exit_code`, `stderr` (TimeoutExpired's stderr/exit_code may be partial; treat as None for contract simplicity) |
| 5 | Unexpected `Exception` catch-all | Anything else inheriting from `Exception`: `RuntimeError`, `ImportError`, `MemoryError`, `ValueError` outside protoxy, `pool.Add()` failures from malformed FDS, anything else not matching categories 1-4 | `level="error"`, `message=f"unexpected backend exception: {exc!r}"`, `exception_type=<exc class name>` | `command`, `exit_code`, `stderr` |

**BaseException posture (per A2-1 review-pass decision 2026-05-01).** `BaseException`-but-not-`Exception` subclasses (`KeyboardInterrupt`, `SystemExit`, `GeneratorExit`) are **NOT caught** — they propagate uncaught by design. Rationale: `KeyboardInterrupt` should remain interruptable; `SystemExit` from a backend signals "deliberate exit, abort" and converting to a Diagnostic would suppress it; `GeneratorExit` is reserved by Python's generator protocol. The "no SystemExit, always Diagnostic" contract therefore reads more precisely as: **"all `Exception` subclasses produce a `LintCompileDiagnostic`; `BaseException`-but-not-`Exception` propagates."** Test #8's contract is updated accordingly: it asserts catch-all coverage of `Exception` subclasses, NOT `BaseException` subclasses.

**Catch-order matters (per F3 review-pass note).** The `except` chain must be ordered: (3) `FileNotFoundError` → (2) `subprocess.CalledProcessError` → (4) `OSError` → (4) `subprocess.TimeoutExpired` (or use `subprocess.SubprocessError` parent if other SubprocessError subclasses appear) → (5) `Exception`. Putting `OSError` before `FileNotFoundError` would shadow it (FileNotFoundError is an OSError subclass).

**Both-fail composition** (per A2). When category #1's fallback is invoked AND the protoc fallback ALSO fails (any of categories 2/3/4/5), emit BOTH the fallback-info Diagnostic (#1) AND the fallback-failure Diagnostic. **Diagnostic ordering is fixed: `[info-fallback, ...backend-failure-diagnostics]`** (per A2-2 review-pass decision — info comes first regardless of when the protoc failure was caught). Maximum one info-fallback Diagnostic per `compile_protos_to_result()` call (no recursive fallback). Tests #4 (info-only path), #9 (info + protoc-CalledProcessError), and at least one parametrized variant of #9 over (info + #4 OSError) and (info + #5 unexpected) cover the combinatorial cases.

### Helper refactor strategy (per F1=A decision 2026-05-01; concrete bug fixes per pass-2 doc-review 2026-05-01)

Refactor existing `protokit._cli_utils._compile_with_protoxy` and `_compile_with_protoc` to **multi-path + raising** as canonical shape. Legacy `compile_proto()` (single-path + `error_exit`) becomes a thin wrapper that catches and adapts. Single source of truth; no duplication. **Concrete bugs fixed per pass-2 review:**

- **Include-path dedup uses `dict.fromkeys()`, NOT `set`.** Set ordering is non-deterministic across Python's hash-randomization seeds; multi-path callers passing roots in different parent dirs would produce non-deterministic include-path order, causing inconsistent backend-input-order behavior. `dict.fromkeys()` preserves insertion order while still deduping. (F1-1)
- **`root_names` matcher uses protoxy's resolution rather than basename suffix.** The naive `fd.name.endswith("/" + p.name)` is wrong when transitive imports share a basename with a user-passed root. Correct approach: protoxy emits each `fd.name` as the path *relative to whichever include directory was used to resolve it*. To match a user-passed root, pre-compute its expected `fd.name` by resolving against the same `(*include_paths, *parents)` order in declared order; use that as the matching key. (F1 false-positive)
- **Reject same-basename roots in different parent dirs as unsupported.** When two roots have the same basename (e.g., `/dir1/same.proto` and `/dir2/same.proto`), passing both `dir1` and `dir2` as includes makes protoxy raise `path '...' is shadowed by '...' in the include paths`. Document this as unsupported and detect it pre-flight: raise a clear `ValueError("multi-path roots with same basename in different parent dirs is unsupported")` rather than letting the cryptic protoxy error surface. (F2)

```python
# protokit/_cli_utils.py — refactored
def _compile_with_protoxy(
    proto_paths_in: Sequence[Path],          # was: proto_path: Path
    include_paths: tuple[str, ...],
) -> tuple[descriptor_pool.DescriptorPool, list[str]]:  # was: just pool
    """Multi-path compile via protoxy. RAISES on failure (no error_exit)."""
    import protoxy
    # Pre-flight: reject same-basename roots in different parents (F2).
    _check_no_same_basename_collision(proto_paths_in)
    # Use dict.fromkeys for ordered, deterministic include-path dedup (F1-1).
    parents = list(dict.fromkeys(str(p.parent) for p in proto_paths_in))
    includes = [*include_paths, *parents]
    fds = protoxy.compile(
        files=[str(p) for p in proto_paths_in],
        includes=includes,
        include_imports=True,
        include_source_info=False,
        # Match the protoc path — keep the in-memory FileDescriptorSet
        # byte-equivalent between backends.
    )
    pool = descriptor_pool.DescriptorPool()
    # Pre-compute expected fd.name per root by resolving against the include
    # list in declared order; use as matching key (F1 false-positive fix).
    expected_root_names = _expected_root_names(proto_paths_in, includes)
    root_names: list[str] = []
    for fd in fds.file:
        pool.Add(fd)
        if fd.name in expected_root_names:
            root_names.append(fd.name)
    return pool, root_names

# Legacy compile_proto() — public CLI behavior unchanged
def compile_proto(p: Path, ip: tuple[str, ...] = ()) -> descriptor_pool.DescriptorPool:
    """Single-path compile, error_exit on failure (compat CLI callers)."""
    try:
        pool, _ = (_compile_with_protoxy([p], ip) if _has_protoxy()
                   else _compile_with_protoc([p], ip))
    except (protoxy.ProtoxyError, ValueError,
            subprocess.CalledProcessError, FileNotFoundError,
            subprocess.TimeoutExpired, OSError) as exc:
        error_exit(f"compile failed:\n{exc}")
    return pool
```

`compile_protos_to_result()` (in `schema/compile.py`) consumes the same raising helpers and adapts to `CompileResult` + `LintCompileDiagnostic` via the 5-category catch chain. **This resolves adversarial finding A7** (two compile paths with divergent failure semantics → now one source of truth with two adapters).

### Syntax floor commitment (per A9-2 review-pass note)

Code in this delivery uses **Python 3.10-compatible syntax only**. No `except*` (3.11+), no `Self` from `typing` (3.11+; use `typing_extensions` if needed), no `exc.add_note()` (3.11+). `[tool.ruff] target-version = "py310"` (already configured at `pyproject.toml:67`) lints this. Without this commitment, "3.11 is a one-line YAML change" becomes "3.11 is a one-line YAML change plus triaging whatever 3.11+-only patterns slipped in."

### Dependency on existing code

- **Does NOT reuse** `protokit.message.model.Diagnostic` for compile-time diagnostics (per A3 decision 2026-05-01). Compile-time diagnostics use the new `LintCompileDiagnostic` defined in `schema/lint/model.py`. Rationale: `message.model.Diagnostic` was designed for diff-time runtime issues (`treat_as_map` fallback, enum drift, plugin crash) and uses `path: str | None` as a dotted message-tree path. Compile failures need `command`, `exit_code`, `stderr`, `exception_type` for programmatic access by formatters and future plugins — fields that have nowhere structured to live in the existing `Diagnostic` shape.
- **Refactors `protokit._cli_utils._compile_with_protoxy` and `_compile_with_protoc`** to multi-path + raising as canonical shape (per F1=A decision 2026-05-01 — see "Helper refactor strategy" above). Legacy `compile_proto()` becomes a thin wrapper that catches and `error_exit`s, preserving compat behavior. Single source of truth; no duplication. Public signature of `compile_proto()` unchanged. **Touches compat code path; needs full compat test sweep in this PR.**
- Does **NOT modify** `protokit/__init__.py`. No top-level reexports (T5; verified at `src/protokit/__init__.py:13`).
- Does **NOT modify** `protokit/formatters/__init__.py`. No `_builtin_lint` added to eager block (codex P0 finding LINT-DESIGN-COLD-IMPORT-FORMATTERS fix; deferred to step 5).

### Test coverage

Each REGRESSION-CRITICAL test asserts the specific `LintCompileDiagnostic` shape (level, message, command, exit_code, stderr, exception_type as appropriate) and pool/root_files state, so a future refactor can't collapse the categories silently:

1. **Multi-path independent** (S3-3A.1) — two `.proto` files with no cross-imports compile in one call; both names appear in `root_files` **in input order**; pool contains both files. **Parametrized over backends** (protoxy + protoc).
2. **Multi-path with cross-file imports** (S3-3A.2) — `b.proto` imports `a.proto`; both passed as roots; both compile; `a` is reachable from `b`'s descriptor. **Test asserts input-order preservation: `root_files == (input_order)` regardless of import direction** — the backend handles import-order resolution internally; user input order is the authoritative ordering for `root_files`. **Parametrized over backends** (protoxy + protoc).
3. **Shared include path** (S3-3A.3) — root file imports a vendored proto from an `include_paths` directory; vendored proto is in the pool but NOT in `root_files` (so engine wouldn't lint it). **Parametrized over backends** (protoxy + protoc).
4. **Protoxy runtime parse error → protoc fallback succeeds** (S3-1G category #1) — mock `protoxy.compile()` to raise `protoxy.ProtoxyError`; assert `_compile_with_protoc()` is invoked next; assert `pool` is populated; assert exactly one `level="info"` `LintCompileDiagnostic` with `exception_type="ProtoxyError"` notes the fallback. **NOT parametrized** — both backends must be present; gates on `_has_protoxy() AND shutil.which("protoc")` and skips otherwise.
5. **Protoc subprocess error** (S3-1G category #2) — protoxy unavailable + protoc returns non-zero with stderr; assert `level="error"` `LintCompileDiagnostic` with `command=(argv,)`, `exit_code=N`, `stderr=verbatim`. **NOT parametrized** — explicitly tests the protoc-only path.
6. **Both backends absent** (S3-1G category #3) — patch `_has_protoxy()` to False + patch protoc lookup to raise `FileNotFoundError`; assert `level="error"` `LintCompileDiagnostic` with install-hint message. Test must use `find_spec`-style import-gating (matching `_cli_utils._has_protoxy()` at line 71) to avoid module-load `ImportError`. **NOT parametrized** — purely synthetic.
7. **Other OSError** (S3-1G category #4) — synthetic `OSError` AND at least two subclasses (`PermissionError`, `subprocess.TimeoutExpired`) from a backend; assert `level="error"` `LintCompileDiagnostic` with infrastructure label and `exception_type=<subclass>`. **NOT parametrized** — purely synthetic.
8. **NEW (per A2 decision) Unexpected exception catch-all** — synthesize backend raising `RuntimeError`, `ImportError`, `MemoryError`; ALSO synthesize `pool.Add()` raising `TypeError` on a malformed `FileDescriptorProto`. Assert `level="error"` `LintCompileDiagnostic` with `exception_type=<exc class name>` and `message=repr(exc)`. **NOT parametrized** — purely synthetic. Locks the "no SystemExit, always Diagnostic" contract — proves nothing escapes uncaught.
9. **NEW (per A2 decision) Both-fail composition** — protoxy raises `ProtoxyError` AND protoc fallback ALSO raises `subprocess.CalledProcessError`; assert TWO diagnostics are emitted: (a) `level="info"` fallback Diagnostic with `exception_type="ProtoxyError"`, (b) `level="error"` protoc-error Diagnostic with `command/exit_code/stderr`. Asserts the both-fail composition explicitly is composition, not collapse. **NOT parametrized** — purely synthetic, lives in `test_compile_protoxy_fallback.py`.

**Plus structural model tests in `test_model.py`** (per S2/F9 — added 2026-05-01 to address dead-code concern):
- `test_lint_profile_compose()` — single-profile passthrough, multi-profile rule_id union, multi-profile severity-overrides most-strict-wins
- `test_lint_rule_spec_severity_for()` — single-kind (returns spec.severity for any violation_kind), multi-kind (looks up by violation_kind, KeyError on unregistered kind)
- `test_lint_location_str()` — all 8 LintLocation variants render via stable `__str__` (covers FieldLocation `"file:Type.field"` style, etc.)
- `test_context_instantiation()` — all 8 frozen contexts construct with `_emit_fn`/`_rule_id`/`_effective_severity` engine-injected fields; immutability verified
- `test_duplicate_rule_error()` — class exists, inherits from Exception, constructible with two-source-locations message
- `test_lint_finding_lint_report()` — both frozen dataclasses instantiate with locked field shapes

### CI workflow

`.github/workflows/ci.yml` runs the full pytest suite across a **4-job matrix** (per A9/S5 decision 2026-05-01 — trimmed from the original 6-job matrix to drop 3.11; load-bearing axes are floor + ceiling Python plus both backends):

```yaml
strategy:
  matrix:
    python: ["3.10", "3.12"]
    has_protoxy: [true, false]    # was: backend: ["protoxy", "protoc"]
```

**Axis semantics (per F6/F7 decision 2026-05-01).** The original "backend: [protoxy, protoc]" axis was ambiguous (does "backend: protoc" mean protoxy is *absent* or just *unused*?). Resolved:

- **`has_protoxy: true`** — install the optional `[compiler]` extra (protoxy 0.7+) AND system protoc on PATH. Both backends present. Tests #1-3 (multi-path) parametrize over both. Test #4 (fallback) runs (gated on `_has_protoxy() AND shutil.which("protoc")`).
- **`has_protoxy: false`** — install ONLY system protoc on PATH (NOT the `[compiler]` extra). Tests #1-3 run with `backend=protoc` parametrization only (the protoxy-parametrized variants skip via `pytest.importorskip("protoxy")`). Test #4 skips (cell lacks both backends).
- Tests #5-9 (synthetic mocking, NOT parametrized) run on every cell.

**System protoc installation:** install on every cell via `apt-get install -y protobuf-compiler` (ubuntu-latest). The matrix never excludes protoc — only the optional `protoxy` extra is conditional. This makes the matrix load-bearing axes `python × has_protoxy` rather than `python × xor`.

3.11 is NOT in the matrix per A9/S5 — its only currently-load-bearing distinction (`tomllib` stdlib branch) is shared with 3.12. Adding 3.11 later if a 3.11-specific issue surfaces is a one-line YAML change. Saves ~33% CI minutes; reduces day-1 flake-debug surface.

**Note:** The repo currently has no GitHub remote configured. The workflow file is harmless dormant config until a remote is added + push happens. Lands now so it fires on day-1 of CI activation.

## Constraints

- Python 3.10 minimum (`pyproject.toml` line 67: `target-version = "py310"`, line 74: `python_version = "3.10"`).
- All file references in code/docs use repo-relative paths.
- No comments in code unless they add a non-obvious WHY (project convention from CLAUDE.md).
- Frozen dataclasses throughout (matches compat's `plugins.py:108` pattern).

## Verified codebase context (used as constraints during /ce:plan)

| Claim | Verified at | Notes |
|---|---|---|
| `Diagnostic` lives at `protokit.message.model.Diagnostic` | `src/protokit/message/model.py:79` | NOT reused for compile-time per A3 decision 2026-05-01. Compile-time uses new `LintCompileDiagnostic` in `schema/lint/model.py`. (5 existing cross-subpackage imports of Diagnostic confirm cross-subpackage import is established pattern, not new coupling — feasibility F5.) |
| Existing protoxy/protoc fallback is **install-time only**, single-path | `src/protokit/_cli_utils.py:71-118, 121-177` | Per F1=A decision 2026-05-01: REFACTORED in this delivery to multi-path + raising as canonical shape. Legacy `compile_proto()` becomes thin wrapper preserving `error_exit` behavior. Single source of truth. |
| `_compile_with_protoxy` raises `error_exit()` on protoxy failure | `src/protokit/_cli_utils.py:140` | Refactored away per F1=A; new shape raises `ProtoxyError`/`ValueError`. |
| `protoxy>=0.7` is in `[project.optional-dependencies] compiler` | `pyproject.toml:39` | Not a hard dep; `compile_protos_to_result` must work protoc-only via `pytest.importorskip("protoxy")` in tests + runtime `_has_protoxy()` gate. |
| `protokit/__init__.py` declares no-reexports policy | `src/protokit/__init__.py:13` | T5 honors this — `compile.py` lives in `schema/`. |
| No CI workflow currently exists | `.github/workflows/` does not exist | This delivery creates CI from scratch (4-job matrix per A9/S5). |
| `protokit/formatters/__init__.py` eagerly imports builtins | `src/protokit/formatters/__init__.py:63-71` | Step 5 must register `_builtin_lint` lazily; step 2 does NOT modify this file. |
| `DescriptorPool()` does NOT contain WKTs | empirically verified 2026-04-30 against this protobuf runtime | Adversarial finding A1 (pass 1); corrected in this doc + upstream design doc lines 19, 660. |
| `subprocess.CalledProcessError` and `TimeoutExpired` are NOT subclasses of `OSError` | empirically verified 2026-05-01 (pass-2 doc-review) | Both inherit from `subprocess.SubprocessError` (sibling tree). Catch-order in `compile_protos_to_result` must list FileNotFoundError → CalledProcessError → OSError → TimeoutExpired → Exception. Per F3 review-pass correction. |
| `tests/test_cli_utils.py:38` asserts `_has_protoxy() is True` unconditionally | `tests/test_cli_utils.py:36-38` | Will fail on the `has_protoxy: false` CI cell. Test must be updated in this delivery (or guarded with `pytest.importorskip("protoxy")` at module top). Per A9-1 review-pass finding. |

## Open Questions

None. All product/scope decisions resolved across two passes:

**Pass 1 (2026-04-30):** Step-2 vs bundled scope chosen (foundation-only); CI created from scratch (vs deferred).

**Pass 2 (2026-05-01, document-review skill):** 11 findings surfaced, all resolved:
- **F1 (seam choice) → A:** refactor existing `_compile_with_protoxy`/`_compile_with_protoc` to multi-path + raising; legacy `compile_proto()` thin-wraps. Single source of truth. **Resolves A7** (two compile paths) automatically.
- **A1 (WKT empirical falsification) → AUTO-FIXED:** `DescriptorPool()` does NOT contain WKTs. Both this doc and upstream design doc corrected.
- **A3 (Diagnostic reuse vs new) → New `LintCompileDiagnostic`:** explicit fields for `command`, `exit_code`, `stderr`, `exception_type`. ~30 LOC; locks contract for downstream consumers.
- **A2 (taxonomy completeness) → 5 categories + both-fail composition:** added unexpected-exception catch-all (#5) + tests #8, #9. "Never SystemExit" contract now actually holds.
- **A10 (effort estimate) → 15-18 CC hrs:** re-baselined from bottom-up.
- **F6/F7 (CI axis ambiguity) → `has_protoxy: [true, false]`:** install protoc on every cell; conditional only on protoxy `[compiler]` extra.
- **A9/S5 (CI matrix size) → trim to 4 jobs:** drop 3.11; load-bearing axes are 3.10×3.12 × has_protoxy.
- **S2 + A5 + A6 + F9 (untested types) → add `test_model.py`:** 6 structural tests cover compose/severity_for/__str__/instantiation/DuplicateRuleError/finding+report.
- **F8/S7 (cold-import gate) → AUTO-FIXED:** concrete CI smoke step `python -c "import protokit.schema; assert 'protokit.schema.lint' not in sys.modules"`.
- **C1/C2 (test file org + parametrization spec) → AUTO-FIXED:** test counts and per-test parametrization made explicit.
- **A8 (cross-subpackage rationale) → DROPPED:** feasibility F5 verified 5 existing cross-subpackage Diagnostic imports — established pattern, not new coupling.

**S6 (CI bundled with foundation)** — kept bundled per Pass 1 decision; flagged as a turbulence source if the CI yaml needs iteration mid-PR.

**A5 (closure allocation cost)** — flagged for measurement via `tests/schema/lint/test_perf_smoke.py` in Delivery 5 (Next Steps step 11), not blocking here.

**Pass 3 (2026-05-01, document-review pass 2):** 10 additional findings surfaced; cascade applied:
- **S2-2 (cold-import contradiction) → AUTO-FIX:** `LintCompileDiagnostic` relocated from `schema/lint/model.py` to `schema/compile.py` (next to `CompileResult`, its sole consumer). Eliminates transitive coupling that broke the cold-import contract by construction.
- **A2-1 (BaseException posture) → AUTO-FIX:** Category #5 catches `Exception` subclasses only; `BaseException`-but-not-`Exception` (KeyboardInterrupt, SystemExit, GeneratorExit) propagates by design. The "no SystemExit, always Diagnostic" contract restated as "all `Exception` subclasses produce a `LintCompileDiagnostic`; `BaseException`-but-not-`Exception` propagates."
- **F3 (TimeoutExpired hierarchy) → AUTO-FIX:** `subprocess.TimeoutExpired` is a sibling of `CalledProcessError` under `SubprocessError`, NOT an OSError subclass. Catch-order: FileNotFoundError → CalledProcessError → OSError → TimeoutExpired (under SubprocessError) → Exception.
- **A2-2 (both-fail invariants) → AUTO-FIX:** Diagnostic ordering fixed: `[info-fallback, ...backend-failure-diagnostics]`. Maximum one info-fallback per call (no recursive fallback).
- **A2-3 (both-fail combinatorial coverage) → AUTO-FIX:** Test #9 parametrized over the 3 reachable composition cases (info+#2, info+#4, info+#5).
- **A3-1 (per-category field-presence) → AUTO-FIX:** Per-category populated/None field table added to the 5-category section.
- **A9-1 (existing protoxy-import audit) → AUTO-FIX:** Listed in "Existing files modified" section. `tests/test_cli_utils.py:38` will fail on `has_protoxy: false` cells without `pytestmark = pytest.mark.skipif(not _has_protoxy(), ...)` on `TestProtoxyBackend`.
- **A9-2 (syntax floor commitment) → AUTO-FIX:** Explicit "Python 3.10-compatible syntax only" line added; `[tool.ruff] target-version = "py310"` already enforces.
- **A10-1 (effort estimate honest range) → AUTO-FIX:** Re-baselined again from 15-18 to 18-26 hrs after pass 2 surfaced unbudgeted work (existing-test rewrites, protoxy audit, concrete bug fixes).
- **F1-1 (set ordering non-determinism) → AUTO-FIX:** `dict.fromkeys()` for include-path dedup (preserves order, dedups). Documented in helper refactor strategy.
- **F1 (root_names matcher false positives on shared basenames) → AUTO-FIX:** Use protoxy's resolution rather than `endswith("/" + p.name)`. Pre-compute expected `fd.name` per root.
- **F2 (same-basename roots in different parent dirs) → AUTO-FIX:** Reject pre-flight with clear `ValueError`; document as unsupported.
- **F5 (existing-test sweep) → AUTO-FIX with scope confirmation:** 8 tests in `test_cli_utils.py` rewritten to test corrected layering (helpers raise; CLI integration test asserts SystemExit). Per user reframing: these tests were testing the wrong layer; rewriting is correcting an existing bug, not adding scope.
- **Coherence #2 (F1→A1 typo) → AUTO-FIX:** corrected in Verified codebase context table.

**S2-1 (structural test gaps in test_model.py) — DEFERRED to /ce:plan.** Pass 2 noted that `LintProfile.compose()` zero-arg, equality semantics across 8 contexts, `__match_args__` for LintLocation, `LintRuleSpec.severity_for("unregistered_kind")` engine-side semantic, `DuplicateRuleError` attribute shape are all worth testing. /ce:plan should expand `test_model.py` from 6 → ~10-12 tests covering these cases. ~1 hr additional effort, absorbed into the 18-26 hr range.

**Coherence #1 (terminology drift Diagnostic vs LintCompileDiagnostic) — DEFERRED to /ce:plan.** A few prose mentions of "Diagnostic" should read "LintCompileDiagnostic" for clarity. Cosmetic; doesn't affect correctness.

**Reframing note (2026-05-01).** Pass 2's "descope helper refactor" recommendation was reconsidered after user reframing: the refactor isn't discretionary scope — it corrects a layering bug that the project's library-first direction (T5+) demands. The "broken existing tests" were testing the wrong layer (helper-level SystemExit instead of CLI-level integration). Rewriting them is correcting an existing bug, not creating new work. The single-PR scope is the principled choice; the alternative defers known-correct work and contaminates downstream deliveries with a known-wrong layering.

## Handoff

Ready for `/ce:plan` against this requirements doc. The plan should produce:

1. File-level diff order (which file lands first, what each commit looks like)
2. Test ordering and shared fixture design
3. CI workflow file structure (stages, caching, conditional protoc install)
4. Concrete acceptance gates for the PR (every test in the table above passes; cold-import contract validated by a CI smoke step in this PR — `python -c "import protokit.schema; import sys; assert 'protokit.schema.lint' not in sys.modules, sys.modules.keys()"` runs after the install step on every matrix cell. The full mechanism-asserting cold-import test (which inspects `cli.py` source) lands in step 4 with the actual CLI stub; this PR's smoke step protects the foundation from accidentally creating an import path that pulls `lint/` in early).
