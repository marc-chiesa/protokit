# protokit-lint D6b U4 — R7 PACKAGE_SAME_* family (7 rules) + engine pre-walk accumulator + FileLintContext.package_options

**Status:** brainstorm (requirements). Next step: `/ce:plan`.
**Date:** 2026-05-15.
**Scope:** per-unit. Refines parent D6b U4 section.
**Parent brainstorm:** `docs/brainstorms/2026-05-14-protokit-lint-delivery-6b-option-aware-and-multi-language-requirements.md` (R7 section + Open Questions).
**Parent plan:** `docs/plans/2026-05-14-001-feat-protokit-lint-d6b-option-aware-and-multi-language-plan.md:442-491` (Unit 4 section).
**Predecessors shipped:** U1 (`include_source_info` parameter + both backends), U2 (`source_info_descriptors` field on 5 ElementKind contexts + `leading_comment` helper), U3 (R6 5-rule deprecated-replacement family + lint CLI source-info wire-up across both input modes; commits `db44515` docs / `313e04a` U3a / `864dddf` U3b / `94dd389` ce:review follow-ups). Suite at 1650 lint+core passing + 39 skips + 17 parity passing.

## TL;DR

U4 closes the **cross-language buf BASIC parity gap for multi-language teams** — 7 PACKAGE_SAME_* rules ship under `recommended` + `default`, bringing protokit-lint to 17-of-18 buf BASIC rules (the 18th, `package/same-directory`, lands at D6c per the parent brainstorm). Multi-language teams running `buf lint` with BASIC enabled can migrate the rule-set layer to `protokit lint --profile recommended` without silently weakening cross-file option enforcement. **Architectural footnote:** U4 also adds protokit-lint's first cross-file rule infrastructure (the engine pre-walk accumulator) — this is delivery scaffolding, not the user-facing headline; the next obvious cross-file consumer (`package/same-directory`) needs a different shape so U4's accumulator is bespoke for R7, not general-purpose infrastructure.

Three deliverables:

1. **Engine pre-walk accumulator** — a new Step 3.5 inside `LintEngine.run` that iterates the FULL `compile_result.pool` (via a new `CompileResult.pool_file_names` field) ONCE before the per-file dispatch walk and builds `package_options: dict[str, dict[str, dict[str, str | None]]]` (3-level: keyed at level 1 by `package_name`, level 2 by `option_attr`, level 3 by `filename`). **Walking the full pool — including transitively-imported protos — is load-bearing for buf-parity:** buf walks the entire module per PACKAGE_SAME_*; if protokit walked only `root_files`, partial-package lints would silently weaken cross-file enforcement vs buf. Findings still emit only on files in `root_files` via the existing Step 4 per-file dispatch gate. Iteration is `sorted()` for OS/CI determinism per [[structural-pin-inspect-getsource-untestable-collision-branch]]. Reads each file's options via `pool.FindFileByName(name).GetOptions()` — **does NOT depend on `--include_source_info`** (FileOptions are first-class `FileDescriptor` attributes, not source-info payload). Built unconditionally when `pool_file_names` is non-empty (lazy-gating dismissed on complexity grounds — see Resolved Here). The pre-walk's `pool.FindFileByName(...)` call **matches the existing Step 4 defensive `try/except KeyError: continue` pattern at `engine.py:407-412`** so a compile-failure path that Step 4 tolerates doesn't crash the pre-walk pass; the accumulator simply omits the unresolvable file.
2. **FileLintContext.package_options field** — single dataclass addition (no other contexts touched). `Mapping[str, Mapping[str, Mapping[str, str | None]]] | None`. Engine-injected via `_build_file_ctx`. Wrapped at all 3 nesting levels via `MappingProxyType` at the engine boundary as **defense-in-depth against accidental mutation by co-authored rule code** (not a security-trust boundary — user-pack code via `--rule-pack` runs in-process with full Python introspection capability; the wrap protects correctness, not isolation).
3. **7 R7 rules** under `src/protokit/schema/lint/rules/package_same.py` (NEW sibling module, NOT a subdirectory inside `package.py`). All 7 share a `_check_package_option(ctx, option_attr, rule_id, message_template)` helper. Severity `error`, profiles `("recommended", "default")`, `source_spec="buf:PACKAGE_SAME_<NAME>"`. All `params` string values pass through `_safe_for_stderr(...)` AND are truncated to **500 chars** (matches R6's precedent at `src/protokit/schema/lint/rules/options/deprecated_replacement.py` per [[module-name-newline-injection-stderr-forge]]).

Explicit non-goals: R7 parity-test fixtures + parity-job verification (U6 — needs harness extension for multi-file invocation). `package/same-directory` (the 18th buf BASIC rule — deferred to D6c per parent brainstorm). R9 schema_version bump (U5).

## Problem Frame

After U3 (R6 family + CLI source-info wire-up) shipped, protokit's option-aware path is operational. The remaining D6b user-impact gap is **cross-language rule-set parity**. Today, multi-language teams running `buf lint` with the BASIC tier enabled rely on:

- `PACKAGE_SAME_GO_PACKAGE` — every file in a package agrees on `option go_package`
- `PACKAGE_SAME_JAVA_PACKAGE`, `PACKAGE_SAME_CSHARP_NAMESPACE`, `PACKAGE_SAME_PHP_NAMESPACE`, `PACKAGE_SAME_RUBY_PACKAGE`, `PACKAGE_SAME_SWIFT_PREFIX` — same shape for the other 5 language-specific package options
- `PACKAGE_SAME_JAVA_MULTIPLE_FILES` — every file agrees on the boolean `option java_multiple_files`

Without these 7 rules, a team migrating from `buf lint` to `protokit lint --profile recommended` silently weakens its cross-language policy (the migration "succeeds" with no errors, but enforcement at this layer disappears). That's a footgun for the multi-language migration scenario the parent brainstorm called out as the larger user-impact surface in D6b.

The architectural blocker that has held R7 back through D2-D6a is **cross-file state**. Today's `LintEngine.run` dispatches FILE-element rules one file at a time with no shared state across files (the `Step 4` walk at `engine.py:401-431` builds a fresh `FileLintContext` per file via `_build_file_ctx`). PACKAGE_SAME_* rules need to know every file's option value before deciding whether the *current* file's value disagrees with the package's canonical. U4 closes the gap by adding ONE pre-walk pass that builds the accumulator once, then injecting it into each `FileLintContext` for per-file consumption. No new ElementKind, no new LintLocation variant — the rules stay FILE-element; only the context grows one engine-injected field.

`package/same-directory` (the 18th buf BASIC rule) needs a *different* architectural shape (cross-file disagreement detection + cross-file emit-shape with per-package finding aggregation). Per parent brainstorm: deferred to D6c as its own focused architectural delivery. D6b ships **17 of 18 buf BASIC rules**.

## Requirements

### R7-engine — Pre-walk file-options accumulator

Add a new "Step 3.5" inside `LintEngine.run` between the existing Step 3 (filter+bucket specs at `src/protokit/schema/lint/engine.py:389`) and Step 4 (per-file walk at `engine.py:401-431`). The pre-walk pass:

1. Iterates `sorted(pool_files, key=lambda f: (os.path.basename(f), f))` where `pool_files` enumerates ALL files registered in `compile_result.pool` (not just `compile_result.root_files`). **Walking the full pool — including transitively-imported protos — is load-bearing for buf-parity:** buf walks the entire module per `PACKAGE_SAME_*`; if protokit walked only `root_files`, partial-package lints (where the user names only some files of a multi-file package on the CLI) would silently weaken cross-file enforcement vs buf, breaking the drop-in parity claim. **Emit-time filter:** R7 rules emit findings ONLY on files in `compile_result.root_files` (each rule's per-file dispatch is already gated by the Step 4 walk, which iterates `root_files`); transitively-imported files contribute to the canonical computation but never receive findings themselves. This preserves the "emit only on user-named files" contract while computing canonical over the full package.
2. **Pool enumeration:** uses `compile_result.pool` directly. The descriptor-pool API for iterating registered files is `pool._internal_db.FindAllFileByName(...)` (or equivalent — `/ce:plan` finalizes the exact enumeration call; the protobuf-Python pool doesn't expose a documented public iteration method, so `/ce:plan` may need to thread a `pool_file_names: tuple[str, ...]` field on `CompileResult` populated at `compile_protos_to_result(...)` construction time alongside `root_files`). Determinism is load-bearing: the lexicographic-smallest-filename rule below depends on stable iteration across OS, CI, and Python iteration order per [[structural-pin-inspect-getsource-untestable-collision-branch]].
3. For each `fname`, calls `pool.FindFileByName(fname)` to obtain the `FileDescriptor`, reads `file.GetOptions()`, and records `(go_package, java_package, csharp_namespace, php_namespace, ruby_package, swift_prefix, java_multiple_files)` values into the accumulator.
4. Accumulator shape: `dict[str, dict[str, dict[str, str | None]]]` (3-level: keyed at level 1 by `package_name`, level 2 by `option_attr` from `_PACKAGE_SAME_OPTION_ATTRS` defined below in R7-rules, level 3 by `filename`). The innermost dict stores each file's value so each rule can compute the canonical and find disagreers in one pass per file.
5. **Pre-walk freeze (3-level wrap):** at construction time the engine wraps EACH level of the accumulator via `MappingProxyType` — the outermost dict, each per-package dict, AND each per-attr dict — so rules cannot mutate at ANY nesting depth (`ctx.package_options[pkg][attr][fname] = ...` raises `TypeError` just as `ctx.package_options[pkg][attr] = ...` does). This is **defense-in-depth against accidental mutation by co-authored rule code**, not a security-trust boundary; user-pack code via `--rule-pack` runs in-process with full Python introspection capability so the wrap cannot prevent adversarial mutation. (Mirrors U1's `_populate_pool_with_capture` + `MappingProxyType` pattern at `src/protokit/_cli_utils.py` and U2's `source_info_descriptors` MappingProxyType wrap pattern; extends to 3-level depth.)
6. **Built unconditionally when `pool_file_names` is non-empty.** Lazy-build (only when an R7 rule is loaded) is a micro-optimization deferred to D6c. Rationale: lazy-gating requires loaded-spec-set detection which adds engine complexity for a marginal savings; the eager-build cost is asserted as cheap (one `FindFileByName` hash lookup + 7 `HasField` calls per pool file, minus WKT files filtered at the prefix check) but **not measured at scale** — Success Criterion 11b adds a benchmark-target gate so the assertion is verified before ship.
7. **Defensive `pool.FindFileByName` lookup.** Each per-file lookup wraps in `try: fd = pool.FindFileByName(fname); except KeyError: continue` — matching the existing Step 4 defensive pattern at `engine.py:407-412` ("Defensive: root_files name not in pool (compile-failure path). Skip; no descriptor → no walk for this file."). On `KeyError`, the file is omitted from the accumulator. Fail-loud would regress compile-failure-path users who today get partial lint reports from Step 4 but would crash at Step 3.5.
8. **No `include_source_info` dependency.** Reads via `pool.FindFileByName(...)` give `FileOptions` directly. The pre-walk pass works in `--proto` mode AND `--descriptor-set` mode regardless of whether `--include_source_info` was set when the descriptor set was built. **Correction to parent plan `:454`:** the plan's "populate from `compile_result.source_info_descriptors`" is wrong — `source_info_descriptors` is None when `include_source_info=False`, but R7 must still work. The accumulator MUST walk via `pool.FindFileByName(...)` instead.

**Pseudocode** (final shape finalized at `/ce:plan`):

```python
# engine.py — between Step 3 (line 389) and Step 4 (line 401-431)
# Step 3.5: pre-walk file-options accumulator for cross-file rules.
# Walks the FULL pool (not just root_files) so transitive imports
# contribute to the canonical computation, matching buf's behavior.
# Emit-time filter in Step 4 ensures findings only land on root_files.
# _PACKAGE_SAME_OPTION_ATTR_NAMES is defined in R7-rules below.
_WKT_PATH_PREFIX = "google/protobuf/"  # matches buf's scope (user module, not WKT)
package_options: dict[str, dict[str, dict[str, str | None]]] = {}
for fname in sorted(
    compile_result.pool_file_names,
    key=lambda f: (os.path.basename(f), f),
):
    # Skip protobuf well-known-types (descriptor.proto, any.proto,
    # timestamp.proto, etc.). These appear in pool_file_names because
    # both compile backends use include_imports=True, but buf does not
    # enforce PACKAGE_SAME_* across them and protokit follows suit.
    if fname.startswith(_WKT_PATH_PREFIX):
        continue
    try:
        fd = compile_result.pool.FindFileByName(fname)
    except KeyError:
        # Defensive: match Step 4's existing pattern at engine.py:407-412
        # (file in pool_file_names but not resolvable — compile-failure path).
        # Omit from accumulator.
        continue
    pkg = fd.package
    opts = fd.GetOptions()
    per_pkg = package_options.setdefault(pkg, {})
    for attr in _PACKAGE_SAME_OPTION_ATTR_NAMES:
        # HasField correctly distinguishes "declared" from "absent"
        # on FileOptions in protobuf 4+. Boolean attrs (java_multiple_files)
        # are captured via str() cast for type uniformity (str | None across
        # all 7 attrs) — resolved per Resolved Here.
        per_attr = per_pkg.setdefault(attr, {})
        if opts.HasField(attr):
            per_attr[fname] = str(getattr(opts, attr))
        else:
            per_attr[fname] = None
# 3-level freeze: outer + per-package + per-attr, all wrapped.
```

**`CompileResult.pool_file_names` (NEW field):** populated at `compile_protos_to_result(...)` construction time as `tuple(fd.name for fd in fdset.file)` (the descriptor-set's full file list, including transitively-resolved imports). Sibling of `root_files`; both fields are present on every `CompileResult`. The pre-walk uses `pool_file_names` for accumulator construction; downstream rule dispatch uses `root_files` for per-file walking.

**Backend construction (4-tuple return shape, locked):** both compile backends (`_compile_with_protoxy` at `src/protokit/_cli_utils.py:273-346` and `_compile_with_protoc` at `:349+`) grow to a 4-tuple return: `(pool, root_names, source_info_descriptors, pool_file_names)`. Each backend emits `tuple(fd.name for fd in fdset.file)` from its local `fdset` before returning. `compile_protos_to_result` tuple-unpacks the 4th element into the new `CompileResult` field. The `_load_descriptor_sets_to_result` path at `src/protokit/schema/lint/_cli_utils.py:259-403` populates `pool_file_names` symmetrically from its own per-fd loop. **Field default:** `pool_file_names: tuple[str, ...] = ()` — empty-tuple default for the test-helper / direct-construction backward-compat path (test fixtures that construct `CompileResult(pool=..., root_files=...)` without the new kwarg silently get `()` and the pre-walk early-returns; explicit positional callers across the 5 internal construction sites at `compile.py:513-651` are audited at U4a per the test-helper update strategy in Open Questions).

**WKT (well-known-types) filter at pre-walk:** files whose path begins with `google/protobuf/` are skipped during accumulator construction (see pseudocode). Both backends pass `include_imports=True`, so WKTs (descriptor.proto, any.proto, timestamp.proto, etc.) appear in `pool_file_names`; without filtering they'd pollute `package_options["google.protobuf"]` with WKT option values that disagree across protobuf-runtime installations. Buf operates on the user's module manifest (not the full descriptor pool), so excluding WKTs matches buf-scope semantics. Add a new smoke fixture variant (`wkt-only.proto` — file that imports `google/protobuf/any.proto` and declares no own options) to verify zero R7 findings.

`_PACKAGE_SAME_OPTION_ATTRS: tuple[str, ...] = ("go_package", "java_package", "csharp_namespace", "php_namespace", "ruby_package", "swift_prefix", "java_multiple_files")`.

**Single source of truth for `_PACKAGE_SAME_OPTION_ATTRS`:** the constant is defined ONCE in `src/protokit/schema/lint/rules/package_same.py` (alongside the 7 rules that need its per-attr metadata triples `(attr, rule_id, buf_alias)`). The engine pre-walk imports the simple `tuple[str, ...]` view via `_PACKAGE_SAME_OPTION_ATTR_NAMES = tuple(attr for attr, _, _ in _PACKAGE_SAME_OPTION_ATTRS)` (computed once at module load). Avoids the "defined twice with same name in two scopes" pitfall.

### R7-context — FileLintContext.package_options field

Add ONE field to `FileLintContext` at `src/protokit/schema/lint/model.py:965-994` (the dataclass definition):

```python
@dataclass(frozen=True)
class FileLintContext(_LintContextEmitMixin):
    file: proto_descriptor.FileDescriptor
    pool: descriptor_pool.DescriptorPool
    profile: str
    package_options: Mapping[str, Mapping[str, Mapping[str, str | None]]] | None  # NEW
    _emit_fn: EmitFn
    _rule_id: str
    _effective_severity: Callable[[str], LintSeverity]
```

Position: BEFORE the engine-injected `_emit_fn`/`_rule_id`/`_effective_severity` triple (matches U2's positioning convention for `source_info_descriptors` on the 5 ElementKind contexts).

**Type annotation defers to TYPE_CHECKING-style import** if `Mapping` introduces a new transitive dependency on the cold-import path. The existing `from collections.abc import Mapping` at `model.py` top is already cheap (stdlib); no new imports needed.

**Engine-injected via `_build_file_ctx` at `engine.py:635-648`:** the method grows one kwarg parameter. Before-and-after signatures:

```python
# Before (current at engine.py:635-648)
def _build_file_ctx(
    self,
    fd: proto_descriptor.FileDescriptor,
    spec: LintRuleSpec,
    profile: LintProfile,
) -> FileLintContext: ...

# After (U4a)
def _build_file_ctx(
    self,
    fd: proto_descriptor.FileDescriptor,
    spec: LintRuleSpec,
    profile: LintProfile,
    *,
    package_options: Mapping[str, Mapping[str, Mapping[str, str | None]]] | None = None,
) -> FileLintContext: ...
```

The `package_options` kwarg defaults to `None` for test-helper / direct-construction backward compatibility; the engine's per-file walk (line 401-431) always passes a non-None accumulator. The `| None` typing exists for the test-helper path (e.g., `tests/schema/lint/test_model.py`'s `_make_file_ctx` constructor) where direct construction without the engine pre-walk is convenient.

**No `__post_init__` invariant** — the field is purely engine-injected; user rules treat it as read-only. The `MappingProxyType` wrap at the pre-walk site is the enforcement mechanism (mutation attempts raise `TypeError`).

**`source_info_descriptors` is NOT added to `FileLintContext`** — R7 rules don't read source-code comments. (R6 only needed it on the 5 ElementKind contexts that consume comments via the `descriptor_path(...)` helper. Keeping FileLintContext's source-info surface minimal preserves U2's scope discipline per [[scope-guardian-resists-context-bloat-add-when-needed]].)

**Public Surface DRAFT classification:** `FileLintContext.package_options` enters as **INTERNAL** (engine-injected accumulator; consumers are R7 rules, not external callers). Per [[public-surface-draft-discipline-source-audit]] the DRAFT row updates at U7 alongside the other D6b additions.

### R7-rules — 7 PACKAGE_SAME_* rules

Ship 7 `@lint_rule`-decorated callables in a single new module `src/protokit/schema/lint/rules/package_same.py`. Module is a SIBLING of `package.py`, NOT a subdirectory inside it. Justification:

- `package.py:29-34` already documents this defer explicitly: "The `package/same-directory` rule (`buf:PACKAGE_SAME_DIRECTORY`) is deferred to D6b alongside the rest of the cross-language `PACKAGE_SAME_*` family — it is a cross-file rule that requires comparing multiple files' package declarations…"
- Cross-file rules (R7) live separately from single-file rules (`package_defined`, `package_directory_match`) for clearer module boundaries.
- Single module with 7 rules sharing one helper mirrors `imports.py` (3 FILE-element rules in one module per the Explore scan) and `naming.py` (8 rules in one module).

**Per-rule shape** (mirrors `imports.py:64-92`'s `check_no_public_imports`):

```python
# src/protokit/schema/lint/rules/package_same.py
from __future__ import annotations
import os
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING
from protokit.schema.lint.decorator import lint_rule
from protokit.schema.lint.model import ElementKind, LintSeverity
from protokit.schema.lint._cli_utils import _safe_for_stderr

if TYPE_CHECKING:
    from protokit.schema.lint.model import FileLintContext


_PACKAGE_SAME_OPTION_ATTRS: tuple[tuple[str, str, str], ...] = (
    # (option_attr_on_FileOptions, rule_id, BUF_RULE_ID)
    ("go_package", "package/same-go-package", "PACKAGE_SAME_GO_PACKAGE"),
    ("java_package", "package/same-java-package", "PACKAGE_SAME_JAVA_PACKAGE"),
    ("csharp_namespace", "package/same-csharp-namespace", "PACKAGE_SAME_CSHARP_NAMESPACE"),
    ("php_namespace", "package/same-php-namespace", "PACKAGE_SAME_PHP_NAMESPACE"),
    ("ruby_package", "package/same-ruby-package", "PACKAGE_SAME_RUBY_PACKAGE"),
    ("swift_prefix", "package/same-swift-prefix", "PACKAGE_SAME_SWIFT_PREFIX"),
    ("java_multiple_files", "package/same-java-multiple-files", "PACKAGE_SAME_JAVA_MULTIPLE_FILES"),
)


def _canonical(per_file: Mapping[str, str | None]) -> tuple[str, str | None] | None:
    """Return ``(canonical_file, canonical_value)`` or None when empty.

    Canonical = the value declared by the lexicographically-smallest
    filename in the per-file map. Determinism is the only criterion;
    "smallest filename wins" is simple to explain and matches the
    sorted iteration order in engine.run's pre-walk pass.
    """
    if not per_file:
        return None
    canonical_file = min(per_file)  # lexicographic min of dict keys
    return canonical_file, per_file[canonical_file]


def _check_package_option(
    ctx: FileLintContext,
    option_attr: str,
    rule_id: str,
) -> None:
    if ctx.package_options is None:
        return  # test-helper path with no accumulator injected — skip
    per_pkg = ctx.package_options.get(ctx.file.package)
    if per_pkg is None:
        return
    per_file = per_pkg.get(option_attr)
    if per_file is None or len(per_file) <= 1:
        return  # single-file package or option-attr unrecorded
    canonical = _canonical(per_file)
    if canonical is None:
        return
    canonical_file, canonical_value = canonical
    my_value = per_file.get(ctx.file.name)
    if my_value == canonical_value:
        return  # this file agrees with canonical
    if all(v is None for v in per_file.values()):
        return  # all-omit: silent (no disagreement to flag)
    # All 4 string params: sanitize (collapse control chars + U+2028/U+2029)
    # then truncate to 500 chars (matches R6's adversarial DoS bound).
    ctx.emit(
        violation_kind=rule_id,
        params={
            "option_attr": _safe_for_stderr(option_attr)[:500],
            "value": _safe_for_stderr(str(my_value) if my_value is not None else "<unset>")[:500],
            "canonical_value": _safe_for_stderr(
                str(canonical_value) if canonical_value is not None else "<unset>"
            )[:500],
            "canonical_file": _safe_for_stderr(canonical_file)[:500],
        },
    )


@lint_rule(
    rule_id="package/same-go-package",
    severity=LintSeverity.ERROR,
    profiles=("recommended", "default"),
    element=ElementKind.FILE,
    message_template=(
        "file declares option go_package={value} but package canonical "
        "(from {canonical_file!r}) is {canonical_value}"
    ),
    source_spec="buf:PACKAGE_SAME_GO_PACKAGE",
)
def check_same_go_package(ctx: FileLintContext) -> None:
    """Every file in a package must agree on ``option go_package``.

    Buf parity: ``buf:PACKAGE_SAME_GO_PACKAGE``. See
    https://buf.build/docs/lint/rules#package_same_go_package.
    """
    _check_package_option(ctx, "go_package", "package/same-go-package")


# ... 6 more @lint_rule definitions for the other 6 options


RULES: tuple[Callable[..., None], ...] = (
    check_same_go_package,
    check_same_java_package,
    check_same_csharp_namespace,
    check_same_php_namespace,
    check_same_ruby_package,
    check_same_swift_prefix,
    check_same_java_multiple_files,
)
```

**API alignment** (mirrors U3's post-review API correction):
- `@lint_rule` requires `message_template` per `src/protokit/schema/lint/decorator.py:58`. Each rule carries its own template; `/ce:plan` finalizes per-rule wording so U7's presence ratchets have known substrings.
- `ctx.emit(violation_kind=..., params=...)` per `src/protokit/schema/lint/model.py:918-923`. No `message=` kwarg.
- `params` keys: `option_attr`, `value`, `canonical_value`, `canonical_file`. All passed through `_safe_for_stderr` per R7-sanitize below.

**Pack membership** at `src/protokit/schema/lint/rules/__init__.py:94-101` (BUILTIN_PACKS tuple):

```python
from protokit.schema.lint.rules import enum, file, imports, naming, package, package_same  # NEW import
from protokit.schema.lint.rules.options import deprecated_replacement

BUILTIN_PACKS: tuple[ModuleType, ...] = (
    naming,
    enum,
    imports,
    package,
    file,
    deprecated_replacement,
    package_same,  # NEW (positioned at end; ratcheted via test_builtin_packs.py)
)
```

The membership-pin test at `tests/schema/lint/test_builtin_packs.py:79` ratchets the `expected` tuple to include `package_same`. Per the [[pytest-static-analysis-gate-ratchet]] discipline.

**`include_source_info` independence:** R7 works regardless of whether the lint CLI sets `include_source_info=True` (which U3 wired ON for both `--proto` mode AND `--descriptor-set` mode). The accumulator is built from `pool.FindFileByName(...).GetOptions()`, which doesn't depend on source_code_info. This means R7 rules fire correctly even on legacy descriptor sets built without `--include_source_info` — a clean contrast with R6.

### R7-sanitize — Defense-in-depth on string `params`

All four string `params` values (`option_attr`, `value`, `canonical_value`, `canonical_file`) pass through `_safe_for_stderr` at the emit site per the helper imported from `src/protokit/schema/lint/_cli_utils.py:198-245`. Threat model:

- `option_attr` is hardcoded ("go_package" etc.) — defense-in-depth only; cost is trivial.
- `value` and `canonical_value` are arbitrary user-controlled string content from `option go_package = "..."`. A maliciously-crafted proto could embed `\n error[lint-evil]: forged finding` to spoof additional findings on the human-stderr path. **Load-bearing sanitization** per [[module-name-newline-injection-stderr-forge]].
- `canonical_file` is the `fname` from `compile_result.root_files`, which originates from `pool.Add()` calls keyed on `FileDescriptorProto.name`. Adversarial `.proto` files can carry arbitrary `name` strings. **Load-bearing sanitization.**

**Mandatory adversarial test fixture** per [[module-name-newline-injection-stderr-forge]]: a `.proto` with `option go_package = "foo\n error[lint-evil]: forged"` (and similar U+2028/U+2029/control-char variants) must produce a finding whose `params["value"]` is sanitized to a single-line literal. P0 plan requirement, not a `/ce:review` surprise.

**Truncation cap (500 chars) — P0 plan requirement.** All 4 string `params` values are truncated to 500 chars after `_safe_for_stderr` sanitization. R7's canonical option-value strings are typically short (<200 chars), but a malicious proto could declare `option go_package = "aaa..." * 100KB` to inflate finding payloads against memory + JSON/SARIF emit costs. The 500-char cap matches R6's precedent at `src/protokit/schema/lint/rules/options/deprecated_replacement.py` (D6b U3) and bounds the DoS amplification factor to ~200× against multi-MB adversarial inputs. Mandatory adversarial test fixture verifies the cap fires.

### R7-canonical — Emit-shape contract

For each (package, option_attr) pair where the per-file value map has 2+ entries with disagreement (and not all-None):

1. **Canonical** = the value declared by the **lexicographically-smallest filename** in the package's per-file value map. Deterministic across OS / CI / Python iteration order.
2. **Each file whose value disagrees with the canonical emits ONE finding.** The smallest file itself never emits (it IS the canonical). Other files whose value matches canonical also don't emit.
3. **All-None case** (no file declares the option) is silent. Buf's documented behavior matches: "if a given file option is used in one file in a given package, it's used in every file."
4. **All-same case** (every file declares the same value) is silent. Trivial.
5. **Mixed case** (some declare X, some omit, some declare Y) — every file whose value differs from the canonical emits. Includes both "declared a different value" AND "omitted while canonical declared something" disagreers.

**Buf-divergence handling:** buf's actual emit-shape on mixed-presence is documented in buf's published rules but not empirically verified at brainstorm time (buf binary not on this machine). U6's parity-test infrastructure runs buf at the pinned `v1.69.0` against R7 fixtures. If buf flags differently (e.g., flags ALL files including the canonical, OR flags only the minority), document the divergence in `tests/parity/conftest.py:_PARITY_EXCEPTIONS` per [[buf-parity-divergence-documentation-discipline]] and either match buf's emit (parity-first) or document protokit's deterministic divergence at the four-site discipline (module docstring + rule docstring + `message_template` + per-branch test).

### R7-CLI — No CLI changes required

Unlike U3's R6 family (which required `cli.py:731` proto-mode wire-up + `_cli_utils.py:259-403` descriptor-set-mode wire-up), R7 needs **zero CLI changes**. FileOptions are first-class `FileDescriptor` attributes; they survive `pool.Add(fd)` regardless of `--include_source_info`; the existing CLI invocation path delivers them to the engine for free.

This is a clean architectural contrast worth documenting: R6 = comment-aware (needs source_code_info preservation); R7 = option-aware (FileOptions live on the descriptor itself). The U7 CHANGELOG section can use this contrast to make the option-aware story tangible.

## Non-Goals (deferred)

- **R7 parity-test fixtures + parity-job verification.** U6 ships these. The harness's `run_protokit_lint(fixture_dir, proto_relpath)` at `tests/parity/conftest.py:424-491` is **single-file invocation mode** — it lints ONE `.proto` file. R7 fundamentally requires **multi-file invocation** because the rule's domain is "all files in a package." U6's scope includes (a) extending `run_protokit_lint` to support a multi-file or directory-glob mode AND (b) creating the 21 fixture sets (7 rules × 3 fixtures: good + bad-value + bad-presence). Splitting U4 (rules + unit tests) from U6 (parity + harness extension) keeps each unit's blast radius bounded; U4 ships rules that work; U6 ships the buf-parity coverage.

- **`package/same-directory` (the 18th buf BASIC rule).** Deferred to D6c per parent brainstorm (different architectural shape — cross-file disagreement detection + per-package finding aggregation; needs a new rule kind in the engine). D6b ships 17 of 18 buf BASIC rules.

- **R9 `severities_unloaded_rule` category split + schema_version bump.** U5. Independent of R6/R7.

- **Lazy-build pre-walk gating.** Skipping the pre-walk pass when no R7 rule is loaded is a micro-optimization. Build-cost is O(N_files) with cheap proto field reads; rule-set load detection adds complexity. Defer to D6c if measurement shows the pre-walk is a hot path.

- **Boolean-typed `java_multiple_files` special handling.** `/ce:plan` decides whether to capture all 7 attrs as `str | None` (via `str(getattr(opts, attr))` cast for the bool case) or use a typed-union shape. The hand-written disagreement check (`my_value == canonical_value`) works on either; the question is purely formatter ergonomics. Lean toward `str | None` uniformity (booleans render as `"True"`/`"False"`/`"<unset>"`).

- **Per-rule disable via `[severities]`.** Already supported by the D5 U2 severities engine — users can demote any of the 7 R7 rule_ids to `info` to suppress findings. No new mechanism needed.

- **README worked example.** Lands at U7 (delivery boundary unit) per the parent plan; U4 lands the rules + unit tests, U7 lands the README "Schema Linting" section update.

- **CHANGELOG content.** Lands at U7. U4 ships the rules; U7 enumerates them in the D6b CHANGELOG section.

- **Public Surface DRAFT row update** (`FileLintContext.package_options` INTERNAL row). Lands at U7 per [[public-surface-draft-discipline-source-audit]] alongside the other D6b additions. U4 ships the field; U7 documents it.

## Open Questions

### Deferred to Planning

- **Per-rule `message_template` wording.** Each of the 7 rules has its own template. `/ce:plan` finalizes wording so U7's presence ratchet has known substrings. Suggested base shape: `"file declares option {option_name}={value} but package canonical (from {canonical_file!r}) is {canonical_value}"` — adapted per-rule with the specific option name in prose.

- **Adversarial fixture composition.** Multi-KB option string + control-char variant + U+2028 variant + newline variant — share one `.proto` file with multiple files in different packages, OR split per-rule? Lean toward shared fixture for test density (mirrors U3's R6 adversarial fixture decision).

- **`MappingProxyType` invariant test scope.** Should U4 add an invariant test that `ctx.package_options[pkg][attr]` AND `ctx.package_options[pkg][attr][fname]` mutations raise at all 3 levels? Or test only the outermost mutation? `/ce:plan` decides; lean toward 3-level mutation-raises tests (covers SC10 + SC10a invariants — defense-in-depth comes from the wraps, not from runtime checks).

- **Pre-walk pass placement contract test.** Add a structural pin via `inspect.getsource(LintEngine.run)` that asserts the `sorted(...)` pattern AND the pre-walk-before-Step-4 ordering per [[structural-pin-inspect-getsource-untestable-collision-branch]]? The plan calls for it; `/ce:plan` finalizes the exact assertion shape.

- **NULL semantic edge case — single-declaring file in a multi-file package.** `a.proto` declares `go_package = "X"`, `b.proto` and `c.proto` omit. Per buf docs, this should fire (b and c disagree with a's declaration). The current `_check_package_option` logic handles this: canonical = a.proto's value "X"; b and c have None values; None ≠ "X" → both fire. But the "all-None" silent case (`if all(v is None for v in per_file.values()): return`) only triggers when EVERY file omits. Boundary verified at `/ce:plan` time with explicit test.

- **Test-helper update strategy for FileLintContext field addition.** `tests/schema/lint/test_model.py:81-107` defines `_DEFAULT_INJECTED` shared across 8 context-builder helpers (`_make_file_ctx`, `_make_service_ctx`, etc.). Adding `package_options` to `_DEFAULT_INJECTED` would forward it to the other 7 helpers as an unexpected kwarg. `/ce:plan` decides: (a) split `_DEFAULT_INJECTED` per-context-type; (b) add `package_options=None` keyword default directly to `_make_file_ctx` (cleaner — single-helper-scoped change). Lean toward (b).

- **`CompileResult.pool_file_names` field definition.** R7's pre-walk needs to enumerate ALL pool-registered files (including transitive imports). Two paths: (a) add `CompileResult.pool_file_names: tuple[str, ...]` populated at `compile_protos_to_result(...)` construction from `tuple(fd.name for fd in fdset.file)` — explicit field, decouples engine from pool internals; (b) enumerate pool-registered files via `pool._internal_db` or equivalent at engine-time — risky (protobuf-Python doesn't document a stable public enumeration API). `/ce:plan` finalizes the field shape + construction sites (must populate at both compile-mode AND descriptor-set-mode paths in `_cli_utils.py`). Lean toward (a).

- **Pre-U4 buf smoke test fixtures (gates `/ce:plan` with contingency).** `/ce:plan` installs buf v1.69.0 locally (or via `BUF_BINARY=...`) and runs **5 smoke fixtures** BEFORE U4 ships to lock canonical-value semantics: (1) `all-agree` (3 files, all declare `go_package = "github.com/x/y"`); (2) `mixed-value` (3 files: `a` → `"X"`, `b` → `"Y"`, `c` → `"X"`); (3) `mixed-presence` (3 files: `a` declares `"X"`, `b` + `c` omit); (4) `empty-package-mixed` (3 no-package files with disagreeing `go_package` — verifies whether buf treats `""` as a real namespace or skips no-package files; SC 8b's skip behavior depends on buf-actual); (5) `wkt-only` (single file importing `google/protobuf/any.proto` with no own options — verifies protokit's WKT-filter doesn't diverge from buf). Records buf's exact emit-shape (which files buf flags, message format, exit code) into `tests/schema/lint/rules/fixtures/package_same/_buf_smoke/recorded/`. `/ce:plan` documents the observed behavior + adjusts canonical-value rule + per-rule docstrings + SC 5/8b/8c to match. **Contingencies:** (a) if buf v1.69.0 binary is unavailable, `/ce:plan` blocks U4 with an actionable install pathway — add `scripts/install-buf.sh` aligned with `tests/parity/conftest.py:298-300` BUF_BINARY discovery + the parity job's tarball URL; (b) if buf's actual emit-shape contradicts the lex-smallest-wins SC 5 hardcode (e.g., buf flags ALL files including the canonical, or buf uses majority-value as canonical), `/ce:plan` **reopens this brainstorm** for canonical-rule revision before plan freezes — DO NOT proceed to implementation with a known-divergent canonical rule. If buf diverges in a clean way, document via [[buf-parity-divergence-documentation-discipline]] OR match buf's exact emit-shape (parity-first when buf has a clear answer).

### Resolved Here

- **Module shape: SINGLE FILE.** `src/protokit/schema/lint/rules/package_same.py` contains all 7 rules + `_check_package_option` helper + `_canonical` helper + `_PACKAGE_SAME_OPTION_ATTRS` tuple + `RULES` tuple. Mirrors `imports.py` (3 rules) + `naming.py` (8 rules) precedent. Resolves parent brainstorm Open Question on R7 module shape.

- **Module location: SIBLING of `package.py`** at `src/protokit/schema/lint/rules/package_same.py`. NOT inside `package.py` (which is reserved for single-file `package/*` rules per `package.py:29-34`'s explicit defer comment).

- **Pre-walk pass data source: `pool.FindFileByName(...)`**, NOT `compile_result.source_info_descriptors`. R7 works regardless of `--include_source_info`. **Corrects parent plan `:454` mis-step.**

- **Pre-walk pass placement: between Step 3 (L389) and Step 4 (L401-431)** in `LintEngine.run`. **Corrects parent plan `:454`'s "between line 377 and line 379" line citation** (stale; current file walk is at L401-431, with sorted-iteration setup at L401-406 and dispatch loop at L407-413).

- **`MappingProxyType` 3-level freeze at engine boundary.** Outer dict + each per-package dict + each per-attr dict are ALL wrapped before injection into `FileLintContext`, so mutation at ANY of the 3 nesting depths raises `TypeError`. Reframed from "security/isolation mechanism" to **defense-in-depth against accidental rule mutation** — user-pack code via `--rule-pack` runs in-process with full Python introspection capability, so this is correctness protection, not adversarial isolation. Mirrors U1's `_populate_pool_with_capture` and U2's `source_info_descriptors` MappingProxyType wrap pattern, extended to 3-level depth.

- **Built unconditionally when `compile_result.pool_file_names` is non-empty.** No lazy gating in U4. Rationale: lazy-build requires loaded-spec-set detection (engine complexity for marginal savings). Success Criterion 11b adds a benchmark-target gate (pre-walk pass adds <X ms to lint invocation on a 1K-file fixture) so the eager-build cost is verified, not asserted; if measurement shows the pre-walk is hot at scale, ship lazy-gating in D6c with measured evidence.

- **Accumulator iterates the FULL pool, not just `root_files`.** A new `CompileResult.pool_file_names` field (populated at construction time from `tuple(fd.name for fd in fdset.file)`) is the iteration source for the pre-walk. Findings still emit ONLY on `root_files` (Step 4's per-file dispatch is the emit gate). Transitive imports contribute to canonical computation but never receive findings. **Load-bearing for the buf-parity claim:** if protokit iterated only `root_files`, partial-package lints would silently weaken cross-file enforcement vs buf (which walks the full module). Resolves the adversarial-reviewer's "R7 silently skips cross-file disagreements" finding per [[audit-wire-format-before-claiming-sibling-parity]].

- **Canonical = lexicographically-smallest filename's value, locked at `/ce:plan` post-smoke-test.** `/ce:plan` installs buf v1.69.0 locally and runs 3 smoke fixtures (all-agree / mixed-value / mixed-presence) to record buf's actual emit-shape BEFORE U4 ships (see Deferred to Planning). If buf flags the lex-smallest file's canonical the same way protokit does, the decision locks as-is. If buf differs, `/ce:plan` adjusts the canonical-value rule + per-rule docstrings to match (parity-first) OR documents the chosen divergence per [[buf-parity-divergence-documentation-discipline]]. Either way the decision is empirically grounded before U4 ships, not deferred to U6's parity tests.

- **Boolean attr capture shape: `str | None` uniformity** (`str(getattr(opts, attr))` cast in the pre-walk for `java_multiple_files` — renders as `"True"`/`"False"`/`"<unset>"`). Simplifies `_check_package_option`'s `==` check across all 7 attrs (single-typed comparison).

- **Sanitization length cap: 500 chars** per [[module-name-newline-injection-stderr-forge]] + R6 precedent. Promoted from "/ce:plan decides" to P0 plan requirement.

- **`pool.FindFileByName` failure handling: defensive `try/except KeyError: continue`** matching the existing Step 4 pattern at `engine.py:407-412`. Fail-loud was leaned-toward in an earlier draft but contradicts the existing engine behavior on the compile-failure path; matching Step 4 preserves the partial-lint-report contract.

- **Commit shape: U4a/U4b split** per the U3 precedent + Output Structure commitment. U4a = engine pre-walk + FileLintContext field + accumulator unit tests. U4b = 7 R7 rules + RULES tuple + BUILTIN_PACKS extension + adversarial fixture. Bisectability earns its keep when U4b's regex/rule defects need to be isolated from U4a's engine plumbing. **Cost-of-revert if U4b slips >1 sprint:** U4a is dead-weight engine surface (pre-walk + FileLintContext field with no consumers); accept revert burden as the price of bisectability per [[delivery-boundary-unit-commit-composition]].

- **All-None case is silent.** Matches buf's documented behavior.

- **Severity: ERROR + U7 CHANGELOG migration section.** Locked at parent brainstorm + plan. Matches buf BASIC severity. **Acknowledged upgrade impact:** existing protokit 0.2.0 users upgrading to 0.3.0 may see up to 7 new error-severity findings per disagreeing file. U7 scope adds (a) a pre-upgrade migration section in CHANGELOG enumerating the 7 new error sources + the `[severities]` demotion escape hatch + example pyproject snippets; (b) a README "upgrading from 0.2.0" subsection mirroring the same content per [[pre-1.0-version-bump-as-communication-contract]]. The 0.2.0 → 0.3.0 version bump itself is the documented breaking-change signal. **Recovery-signal limitation acknowledged:** the project has no telemetry; if CI users revert silently to 0.2.0 in their lockfiles after hitting R7 errors, the project never learns. Mitigation paths considered + rejected for U4 scope: (i) `--new-rules-as-warnings-for-N-days` graceful-rollout flag — adds a new wire-format surface + state-dependent rule severity, scope creep beyond U4 and complicates the `[severities]` resolution chain; (ii) opt-in telemetry — out of scope for a CLI tool that doesn't ship a server. Recovery via passive signal (PyPI download trends, GitHub issues mentioning "lint errors after upgrade"); U7 release notes explicitly invite "if R7 produces false positives on your protos, please open an issue with a reproducer." Re-evaluate in D6c if user reports surface a real false-positive epidemic.

- **Rule decomposition: 7 SEPARATE rules.** All 7 rules ship as individual `@lint_rule` callables sharing the `_check_package_option` helper. Alternative (1 rule + 7 buf rule_id aliases via a severities-engine alias resolver) was considered and rejected: direct 1:1 mapping to buf rule_ids matches how users currently configure `[tool.protokit.lint.severities]` per-rule under buf, and the alias-resolver landing cost (~30-50 LOC in the severities engine) doesn't justify the maintenance-surface savings for a 7-rule one-off family. Accepts the cost: 7× docstring + 7× message_template + 7× presence ratchet + 21 parity fixtures.

- **Empty-package (`""`) handling: skip R7 entirely.** When `ctx.file.package == ""` (file declares no `package` statement), `_check_package_option` returns immediately without emitting. Rationale: file-without-package is too weak a grouping signal for cross-file enforcement; aggregating all no-package files across a lint run under the `""` key would produce cross-namespace false-positive findings (an adversarial proto with unusual option values could force findings on every other no-package file). Resolves the security-lens cross-namespace contamination concern. Add explicit Success Criterion 8b verifying zero R7 findings on a multi-file no-package fixture regardless of option disagreement.

- **Profiles: `("recommended", "default")`.** Locked at parent brainstorm + plan.

- **`source_spec="buf:PACKAGE_SAME_<NAME>"`.** Auto-discovered by `tests/parity/conftest.py:139-188` `RULE_ID_MAP` walker — no manual harness wiring needed.

- **All 4 string `params` values pass through `_safe_for_stderr(...)[:500]`.** Defense-in-depth per [[module-name-newline-injection-stderr-forge]]. Mandatory adversarial test fixture.

- **R7 needs zero CLI changes.** FileOptions are first-class `FileDescriptor` attributes; they survive `pool.Add(fd)` regardless of `--include_source_info`. Clean contrast with R6.

- **`source_info_descriptors` is NOT added to FileLintContext.** R7 doesn't need it. Keeps FileLintContext's surface minimal per [[scope-guardian-resists-context-bloat-add-when-needed]].

- **Parity tests deferred to U6** (NOT U4). U4 ships rules + unit tests; U6 ships the harness extension (multi-file invocation) + parity fixtures + parity-job verification. The decoupling is forced by the harness's current single-file `run_protokit_lint(fixture_dir, proto_relpath)` shape.

- **README + CHANGELOG + Public Surface DRAFT updates deferred to U7.** U4 ships code; U7 ships docs per [[delivery-boundary-unit-commit-composition]].

- **Single source of truth for `_PACKAGE_SAME_OPTION_ATTRS`.** Defined once in `src/protokit/schema/lint/rules/package_same.py` as a tuple of `(attr, rule_id, buf_alias)` triples. The engine imports `_PACKAGE_SAME_OPTION_ATTR_NAMES = tuple(attr for attr, _, _ in _PACKAGE_SAME_OPTION_ATTRS)` (computed once at module load) for the pre-walk loop, avoiding the "defined twice with the same name in two scopes" pitfall.

## Success Criteria

### User-outcome criteria (these answer "did we deliver value?")

1. **7 R7 rules registered and visible** under `protokit lint --profile recommended --format=json <fixture>`. All 7 fire on multi-file fixtures with disagreeing/missing options.

2. **7 R7 rules fire under `default` profile too.** Same fixtures; identical findings.

3. **All-agree happy path: zero findings.** A 3-file package where every file declares `go_package = "github.com/x/y"` produces zero `package/same-go-package` findings. Verified per ElementKind option attr (7 rules × happy-path fixture).

4. **All-omit happy path: zero findings.** A 3-file package where no file declares `option go_package` produces zero findings (silent — matches buf's documented behavior).

5. **Mixed-value sad path: N-1 findings.** A 3-file package (all 3 in `root_files`, none transitively-imported) where `a.proto`, `b.proto`, `c.proto` declare `"X"`, `"Y"`, `"X"` respectively produces ONE `package/same-go-package` finding on `b.proto` (canonical = lex-smallest filename across the full pool, which here is `a.proto`'s value `"X"`; `b.proto` is the disagreer). Verified per ElementKind option attr. **Note:** the canonical-selection rule is "lex-smallest filename across `pool_file_names`," NOT "lex-smallest across `root_files`" — SC 8c covers the case where the lex-smallest is a transitively-imported file outside `root_files`.

6. **Mixed-presence sad path: N-1 findings.** A 3-file package where `a.proto` declares `"X"` and `b.proto`+`c.proto` omit produces TWO findings (b and c disagree with canonical). Verified per ElementKind option attr.

7. **Single-file package: zero findings.** A 1-file package produces zero findings regardless of option presence/absence (no disagreement possible).

8. **Multi-package isolation.** A fixture with two packages `foo.bar` and `foo.baz` — disagreement in `foo.bar` does NOT fire findings on files in `foo.baz`. Per-package scoping verified.

8b. **Empty-package skip (no-package file is never grouped).** A multi-file fixture where 3 files lack a `package` statement AND declare different `option go_package` values produces zero R7 findings. Verifies that `ctx.file.package == ""` early-returns from `_check_package_option`. Resolves the security-lens cross-namespace contamination concern.

8c. **Transitive-import canonical computation.** A fixture where `aa.proto` is named on the CLI (in `root_files`) declaring `option go_package = "Y"`, AND `b.proto` is transitively imported via `import "b.proto";` from `aa.proto` (so `b.proto` lands in `pool_file_names` but NOT in `root_files`) declaring `option go_package = "X"`. Both declare `package foo.bar`. **Lex-smallest filename:** `b.proto` (canonical comes from the transitively-imported file). **Expected:** R7 emits ONE finding on `aa.proto` whose `params["canonical_value"] == "X"` and `params["canonical_file"] == "b.proto"` (a path the user did NOT name on the CLI). Verifies (a) the partial-package lint scenario matches buf's full-module-walk behavior, and (b) the emit-shape correctly resolves `canonical_file` to a transitive-import path. The transitively-imported `b.proto` itself does NOT receive a finding (Step 4's emit gate limits dispatch to `root_files`). **UX note for U7 docstrings:** users will see `canonical_file` paths they didn't name on the CLI when transitive imports drive canonical — each R7 rule's docstring documents this so the finding isn't surprising.

9. **`include_source_info` independence.** R7 rules fire identically whether `compile_protos_to_result(include_source_info=True)` or `include_source_info=False`. Verified by a test that lints the same multi-file fixture under both settings.

10. **Adversarial sanitization.** A fixture with `option go_package = "foo\n error[lint-evil]: forged"` (and U+2028/U+2029/control-char variants) produces a finding whose `params["value"]` is sanitized to a single-line literal AND truncated to ≤500 chars. Mandatory per [[module-name-newline-injection-stderr-forge]].

11. **Per-rule demotion via `[tool.protokit.lint.severities]` works** for any of the 7 R7 rule_ids — verified by a fixture pyproject + a runtime test.

11b. **Pre-walk benchmark gate: <50ms cost on 1K-file fixture.** Verified by a `pytest-benchmark` target so the "always-built is cheap" claim is measured, not asserted. The 1K-file fixture is generated programmatically at test time by `tests/schema/lint/rules/fixtures/package_same/_benchmark/conftest.py` (avoids committing 1K real `.proto` files; generator emits a tempdir corpus where each proto declares `package fixture_pkg.subN` with disagreeing-by-design `go_package` values to stress the accumulator). If measured cost exceeds 50ms on real corpora, ship lazy-gating in U4 (skip pre-walk when no R7 rule is loaded — one-line check: `any(spec.rule_id.startswith("package/same-") for spec in active_specs)`) instead of deferring to D6c.

12. **D6b U1+U2+U3 regressions: zero.** The 1650-test baseline continues to pass. Tests asserting `FileLintContext` field count or shape need updating for the new `package_options` field (single-field addition; mechanical update). Estimated affected test sites: ~3-5 (model.py invariant tests + engine pre-walk integration tests). `/ce:plan` enumerates per-line.

13. **Integration: end-to-end lint invocation.** `protokit lint --profile recommended --format json <multi-file fixture dir>/*.proto` produces expected R7 findings in JSON output. `protokit lint --no-builtin-rules <same fixture>` produces zero R7 findings (verifies pack-loading gate).

14. **`--descriptor-set` mode parity with `--proto` mode.** R7 rules fire identically when the lint CLI is invoked with `--descriptor-set <set>` vs `--proto <files>` for the same fixture. Verified by a CLI-mode test.

### Engineering invariants to preserve (these answer "did we avoid regression?")

These are existing-pattern ratchets and structural pins — they don't measure user value, but they catch silent regressions of decisions made elsewhere in the codebase. Surface separately so the success-criteria list isn't conflated with user outcomes per [[delivery-boundary-unit-commit-composition]].

E1. **Pre-walk pass iteration determinism.** A structural test asserts `inspect.getsource(LintEngine.run)` contains the `sorted(compile_result.pool_file_names, key=lambda f: (os.path.basename(f), f))` pattern at the pre-walk pass per [[structural-pin-inspect-getsource-untestable-collision-branch]]. (Note the pin asserts `pool_file_names`, NOT `root_files` — the iteration source distinction is load-bearing for the transitive-import handling decision.)

E2. **`MappingProxyType` 3-level immutability invariant.** A test asserts that mutation attempts at all 3 nesting depths raise `TypeError`: `ctx.package_options[pkg] = ...` (level 1), `ctx.package_options[pkg][attr] = ...` (level 2), and `ctx.package_options[pkg][attr][fname] = ...` (level 3). All three depths must raise so accidental rule mutation is caught at any nesting level.

E3. **BUILTIN_PACKS membership-pin test passes** with the extended `expected` tuple that includes `package_same`.

E4. **Cold-import contract holds.** `import protokit.schema` does NOT transitively load `protokit.schema.lint.rules.package_same`. The existing `tests/schema/lint/test_cold_import_extended.py` catches violations. The `import os` at the new module top is stdlib; no transitive descriptor-pb2 loads.

E5. **Static-analysis ratchet holds.** New paths (`src/protokit/schema/lint/rules/package_same.py`, `tests/schema/lint/rules/test_package_same.py`, `tests/schema/lint/rules/fixtures/package_same/`) added to `tests/test_static_analysis.py:_LINT_PATHS` in the same commit per [[pytest-static-analysis-gate-ratchet]].

E6. **Engine pre-walk accumulator shape test.** A unit test asserts the accumulator structure: `{"foo.bar": {"go_package": {"a.proto": "X", "b.proto": "Y", "c.proto": None}, "java_package": {...}, ...}}` for a known multi-file fixture. Catches accumulator-construction bugs in isolation from rule consumption.

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| `pool.FindFileByName(name)` raises KeyError on names from `compile_result.pool_file_names` | Reachable on the compile-failure path (per the existing Step 4 comment at `engine.py:407-412` — "Defensive: root_files name not in pool"). Both Step 3.5 (the new pre-walk) and Step 4 use `try/except KeyError: continue` and omit the unresolvable file from their respective work. Resolves the apparent contradiction with the old Assumption claim ("succeeds for every name") — that assumption was descriptive of the typical-case invariant but didn't account for compile-failure paths where partial pool state is exposed. |
| Boolean `java_multiple_files` capture-shape mismatch | `/ce:plan` decides type-union shape (lean toward `str | None` uniformity via str() cast for booleans). Test coverage ensures both `True`/`False`/`<unset>` cases work. |
| `MappingProxyType` wrap forgotten — rules mutate accumulator mid-walk | Invariant test asserts mutation raises TypeError. Engine boundary wrap is the enforcement. |
| Pre-walk pass placement breaks if engine refactors move Step 4 | Structural pin via `inspect.getsource(LintEngine.run)` asserts both the `sorted(...)` pattern AND the pre-walk-before-Step-4 ordering. Refactors that move the pin must update the pin (intentional friction per [[structural-pin-inspect-getsource-untestable-collision-branch]]). |
| Buf-actual emit-shape diverges from protokit's lex-smallest canonical | U6's parity tests catch divergence at `_PARITY_EXCEPTIONS` time. U4 ships protokit's deterministic choice; U6 documents divergence per [[buf-parity-divergence-documentation-discipline]] and either matches buf or marks divergence at four sites. |
| R7 false positives on legitimate cross-language differences (vendor isolation, build-system splits) | Per-rule demotion via `[severities]` available immediately. Document in each rule's docstring that the rule enforces strict per-package consistency; teams that intentionally split should demote. |
| Adversarial protos with multi-KB option strings inflate finding params | `_safe_for_stderr` collapses control chars; `/ce:plan` decides on a 500-char length cap for DoS bound. Mandatory adversarial test fixture per [[module-name-newline-injection-stderr-forge]]. |
| Pre-walk pass duplicates Step 4's `sorted(...)` work — double iteration cost | `_PACKAGE_SAME_OPTION_ATTRS` reads are cheap proto field access. The duplicate sort is O(N log N) on file count (typically <100); negligible. Defer optimization to D6c. |
| FileLintContext field addition breaks dataclass-positional callers | Audit U2's `_build_file_ctx` change pattern (mechanical kwarg threading; no positional callers found in U1 audit). Fix mechanically if any positional callers exist. |
| R7 parity coverage deferred to U6 — U4 ships rules without buf comparison | Acknowledged. Parent plan's Unit 6 explicitly covers R7 parity. U4's success criteria include functional unit tests + integration tests; parity is a U6 ratchet on top. |
| Lazy-build skip-when-no-R7-loaded micro-optimization tempting at `/ce:plan` | Resist — adds rule-set-load detection complexity for a marginal walk-time savings. Defer to D6c with measured evidence. |

## Assumptions

- **`pool.FindFileByName(name)` succeeds for every name in `compile_result.pool_file_names` in the typical case** (the pool was populated from those names). On the compile-failure path the lookup can raise `KeyError` for partial-pool-state files; both Step 3.5 and Step 4 wrap their `FindFileByName` calls in `try/except KeyError: continue` per [[delivery-boundary-unit-commit-composition]]. The U4a test suite asserts both the typical-case completion AND the defensive-skip behavior on a synthetic partial-pool fixture.
- **`FileDescriptor.GetOptions()` returns a `FileOptions` proto message.** Standard protobuf API; verified by the existing protobuf 4 + 5 cross-version test suite.
- **`FileOptions.HasField(attr)` correctly reports presence for proto3 scalar message-default detection.** Standard protobuf 4+ API. Verified by U4 unit test asserting accumulator captures `None` for omitting files and `"value"` for declaring files.
- **Proto2 `optional` syntax detection is not needed.** R7 targets proto3 file-level options; the proto2-vs-proto3 distinction doesn't apply at the FileOptions level. (proto2 syntax DOES appear inside R7 fixtures for `option java_multiple_files = false;` test cases — verify HasField semantics work for both syntaxes.)
- **`MappingProxyType` is the right freeze mechanism.** Standard library; mirrors U1+U2 patterns. Cheap O(1) wrap.
- **Lexicographic-smallest filename is a stable canonical-value choice.** Independent of OS path separator, locale, or Python version. Validated by U4's iteration-order test.
- **R7 fixtures' multi-file directory layout is supportable by U6's harness extension.** U6 design includes either a `proto_relpaths: tuple[str, ...]` parameter on `run_protokit_lint(...)` OR a `linted_dir: Path` mode that globs the fixture dir. U4 doesn't depend on which approach U6 picks; U4 ships rules that work on multi-file inputs through the existing CLI invocation.
- **`include_source_info` carries no R7 dependency.** Verified empirically by U4's test that lints the same multi-file fixture under both `include_source_info=True` and `include_source_info=False` and asserts identical R7 findings.
- **Buf's published documentation accurately describes BUILTIN PACKAGE_SAME_* behavior.** "If a given file option is used in one file in a given package, it's used in every file." U6's parity tests verify this against the pinned `buf v1.69.0` binary; if buf's actual behavior diverges from docs, document via `_PARITY_EXCEPTIONS` per [[buf-parity-divergence-documentation-discipline]].

## Output Structure (this unit's commit shape)

U4 ships in **2 commits** per the U3 split precedent (engine plumbing isolated from rule consumers):

**U4a: Engine pre-walk + FileLintContext.package_options field + CompileResult.pool_file_names field**

- **Source:**
  - `src/protokit/schema/compile.py` — `CompileResult` adds `pool_file_names: tuple[str, ...]` field; `compile_protos_to_result(...)` populates it from `tuple(fd.name for fd in fdset.file)` alongside `root_files`.
  - `src/protokit/schema/lint/_cli_utils.py:259-403` — `_load_descriptor_sets_to_result` populates `pool_file_names` symmetric with `root_files`.
  - `src/protokit/schema/lint/engine.py` — Step 3.5 pre-walk pass between L389 and L401 walking `pool_file_names` (NOT just `root_files`); `_build_file_ctx` at L635-648 grows `package_options` parameter.
  - `src/protokit/schema/lint/model.py:965-994` — `FileLintContext` adds `package_options: Mapping[str, Mapping[str, Mapping[str, str | None]]] | None` field.
- **Tests:**
  - `tests/schema/lint/test_engine_pre_walk.py` (NEW) — accumulator construction over full pool, MappingProxyType 3-level invariant, sorted iteration determinism, multi-package isolation, single-file package, all-omit, all-same, mixed-presence, mixed-value, transitive-import-contributes-to-canonical, structural pin via inspect.getsource.
  - `tests/schema/lint/test_compile_pool_file_names.py` (NEW) — `CompileResult.pool_file_names` populated symmetrically in both compile-mode AND descriptor-set-mode paths; covers transitive-import enumeration semantics.
  - `tests/schema/lint/test_model.py` (extend) — FileLintContext field-list invariant test updated for the new field.
  - `tests/test_static_analysis.py:_LINT_PATHS` (extend per ratchet).
- **No rules yet** — engine plumbing in isolation. Bisectable: U4a in isolation produces zero R7 findings (no rule consumers); test suite passes; subsequent U4b adds the consumers.

**U4b: 7 R7 rules + RULES tuple + BUILTIN_PACKS extension + pre-U4-ship buf smoke test**

- **Source:**
  - `src/protokit/schema/lint/rules/package_same.py` (NEW) — 7 rules + `_check_package_option` + `_canonical` + `_PACKAGE_SAME_OPTION_ATTRS` (triples) + `_PACKAGE_SAME_OPTION_ATTR_NAMES` (str view) + `RULES` tuple. Each rule's docstring documents buf parity per [[buf-parity-divergence-documentation-discipline]].
  - `src/protokit/schema/lint/rules/__init__.py:94-101` — extend BUILTIN_PACKS tuple to include `package_same`; new import line at L66-71.
- **Pre-U4-ship buf smoke test (gates `/ce:plan` finalization):**
  - Install `buf v1.69.0` locally (or via `BUF_BINARY` env var).
  - Run buf v1.69.0 against 5 in-tree smoke fixtures (`all-agree.proto`, `mixed-value.proto`, `mixed-presence.proto`, `empty-package-mixed.proto`, `wkt-only.proto` under `tests/schema/lint/rules/fixtures/package_same/_buf_smoke/`).
  - Record buf's actual emit-shape (which files flagged, message-template format, exit code).
  - `/ce:plan` documents the observed behavior in the per-unit plan + adjusts the canonical-value rule + per-rule docstrings + Success Criterion 5 ("Mixed-value sad path") to match. If buf flags differently than "lex-smallest = canonical", either match buf's emit-shape (parity-first) OR document the divergence per [[buf-parity-divergence-documentation-discipline]].
- **Tests:**
  - `tests/schema/lint/rules/test_package_same.py` (NEW) — 7-rule family unit tests (happy/sad/edge per rule) + adversarial sanitization fixture + empty-package skip test (SC 8b) + transitive-import-canonical test (SC 8c).
  - `tests/schema/lint/rules/fixtures/package_same/` (NEW) — multi-file `.proto` fixtures (one set per of the 7 rules + 1 adversarial + 1 no-package + 1 transitive-import).
  - `tests/schema/lint/rules/fixtures/package_same/_buf_smoke/` (NEW) — 5 smoke fixtures + `recorded/` subdirectory of buf-output snapshots for `/ce:plan` audit. **Note:** these fixtures are NOT executed by the regular pytest run (they live for `/ce:plan`-time human-mediated empirical audit); the U6 parity harness will re-execute them as part of the normal parity-test rotation once it's extended for multi-file invocation.
  - `scripts/install-buf.sh` (NEW) — install pathway for buf v1.69.0 aligned with `tests/parity/conftest.py:298-300` BUF_BINARY discovery + the parity-job tarball URL. Makes the `/ce:plan` gate runnable on fresh dev environments.
  - `tests/schema/lint/rules/fixtures/package_same/_benchmark/` (NEW) — programmatic 1K-file fixture generator for SC 11b benchmark gate (avoids committing 1K real `.proto` files to the repo; uses a `conftest.py` fixture that generates a temp-dir corpus via fstring template at test time).
  - `tests/schema/lint/test_builtin_packs.py:79` (extend `expected` tuple).
  - `tests/schema/lint/test_cli_package_same_e2e.py` (NEW) — end-to-end lint invocation tests; `--proto` mode AND `--descriptor-set` mode parity.
  - `tests/test_static_analysis.py:_LINT_PATHS` (extend per ratchet).

Estimated test count: U4a ~12-15 new tests; U4b ~40-50 new tests (7 rules × ~5 scenarios + adversarial + integration + 8b + 8c + buf smoke audit). Total ~55-65 new tests; suite goes 1650 → ~1710-1720.

**Note on U7 scope additions (deferred to U7's per-unit work, not U4):**
- U7 CHANGELOG D6b section adds a pre-upgrade migration subsection: enumerates the 7 new error sources, the `[severities]` demotion escape hatch, and example pyproject snippets for users not ready to align cross-language options.
- U7 README "upgrading from 0.2.0" subsection mirrors the CHANGELOG content per [[pre-1.0-version-bump-as-communication-contract]].
- U7 Public Surface DRAFT row added for `CompileResult.pool_file_names` (classification: **INTERNAL** per [[public-surface-draft-discipline-source-audit]] + [[scope-guardian-resists-context-bloat-add-when-needed]] — engine-injected accumulator scaffolding, only consumer is the lint engine's pre-walk; external CompileResult callers have no current use case. Reclassify to IN in a later delivery if downstream consumers articulate a need; until then it's an implementation detail subject to change).
- U7 docstring per R7 rule notes the "demote via `[severities]` for legitimate cross-language vendor isolation patterns" guidance.

## Sources & References

- **Parent brainstorm:** `docs/brainstorms/2026-05-14-protokit-lint-delivery-6b-option-aware-and-multi-language-requirements.md` (R7 section: lines 83-105; Open Questions: lines 156-159; Resolved Here: lines 184-187).
- **Parent plan:** `docs/plans/2026-05-14-001-feat-protokit-lint-d6b-option-aware-and-multi-language-plan.md` (Unit 4 section: lines 442-491).
- **U3 per-unit brainstorm:** `docs/brainstorms/2026-05-15-d6b-u3-r6-deprecated-replacement-family-requirements.md` (per-unit brainstorm shape reference; U4 mirrors structure).
- **U3 per-unit plan:** `docs/plans/2026-05-15-001-feat-d6b-u3-r6-deprecated-replacement-plan.md` (U4 mirrors per-unit plan shape).
- **`CompileResult` shape to extend:** `src/protokit/schema/compile.py:161-207` (frozen dataclass; add `pool_file_names: tuple[str, ...] = ()` field).
- **Compile backends to extend (4-tuple return):** `src/protokit/_cli_utils.py:221-269` (`_populate_pool_with_capture`), `_compile_with_protoxy` at `:273-346`, `_compile_with_protoc` at `:349+`.
- **Descriptor-set loader to extend:** `src/protokit/schema/lint/_cli_utils.py:259-403` (`_load_descriptor_sets_to_result` — populates `pool_file_names` from its per-fd loop alongside `root_files`).
- **Engine to extend:** `src/protokit/schema/lint/engine.py` (`LintEngine.run` at L275-431; `_build_file_ctx` at L635-648; per-file walk at L401-431).
- **Context to extend:** `src/protokit/schema/lint/model.py:965-994` (`FileLintContext` dataclass).
- **Pack registry to extend:** `src/protokit/schema/lint/rules/__init__.py:94-101` (BUILTIN_PACKS tuple).
- **Sanitizer to reuse:** `src/protokit/schema/lint/_cli_utils.py:198-245` (`_safe_for_stderr` + `_CONTROL_CHAR_TABLE`).
- **Pattern modules to mirror:** `src/protokit/schema/lint/rules/imports.py:64-92` (FILE-element @lint_rule shape with `_safe_for_stderr` reuse), `src/protokit/schema/lint/rules/naming.py` (8-rule shared-helper module shape), `src/protokit/schema/lint/rules/package.py` (sibling-module precedent + the explicit defer comment at L29-34).
- **Parity harness reference:** `tests/parity/conftest.py` (`run_protokit_lint` at L424-491 single-file mode — to be extended at U6; `_BUF_PARITY_PIN = "v1.69.0"` at `src/protokit/schema/lint/cli.py:149`; `_PARITY_EXCEPTIONS` at L101-112 for divergence documentation).
- **Buf documentation:** https://buf.build/docs/lint/rules#package_same_go_package — quoted rule semantics: "if a given file option is used in one file in a given package, it's used in every file."

### Institutional learnings applied

- [[buf-parity-divergence-documentation-discipline]] — each R7 rule docstring documents buf parity; U6's `_PARITY_EXCEPTIONS` covers any measured divergence at four sites.
- [[audit-wire-format-before-claiming-sibling-parity]] — R7 emit-shape canonical-value rule documented; U6 audits buf actual emit at parity-test time.
- [[module-name-newline-injection-stderr-forge]] — R7 sanitization is mandatory at the plan level; adversarial test fixture is a P0 plan requirement.
- [[pytest-static-analysis-gate-ratchet]] — new D6b paths added to `_LINT_PATHS` + BUILTIN_PACKS membership-pin extension in the same commit they're created.
- [[delivery-boundary-unit-commit-composition]] — U4 ships engine plumbing + rules + tests; README/CHANGELOG/Public Surface DRAFT updates lands at U7.
- [[structural-pin-inspect-getsource-untestable-collision-branch]] — pre-walk pass placement + sorted iteration order pinned via `inspect.getsource(LintEngine.run)`.
- [[scope-guardian-resists-context-bloat-add-when-needed]] — `source_info_descriptors` NOT added to FileLintContext; only `package_options`. Single-field addition.
- [[public-surface-draft-discipline-source-audit]] — `FileLintContext.package_options` enters as INTERNAL at U7's DRAFT row addition.
- [[plan-review-verify-prior-art-citations]] — corrects parent plan's `:454` line citation (stale; current file walk at L401-406, not L377-379) AND parent plan's "populate from `compile_result.source_info_descriptors`" mis-step (use `pool.FindFileByName(...)` instead).

### Review history

- **2026-05-15 brainstorm draft (pre-review):** drafted by initial U4 work session. 2 corrections to parent plan baked in: (1) accumulator data source = `pool.FindFileByName(...)` not `compile_result.source_info_descriptors` (FileOptions are first-class FileDescriptor attributes, not source-info payload); (2) pre-walk pass placement = between Step 3 (L389) and Step 4 (L401-431), not "between line 377 and 379" (parent plan citation is stale).

- **2026-05-16 refinement pass round 2 (4 reviewers re-dispatched + 3 user decisions applied):** Re-ran coherence + feasibility + scope-guardian + adversarial after the round 1 refinements. 21 new findings; 13 auto-fixes applied + 3 user decisions resolved. **User decisions:** (1) **WKT filter via `google/protobuf/` path prefix** — pre-walk skips files whose path begins with `google/protobuf/` to avoid polluting `package_options["google.protobuf"]` with well-known-types option values that disagree across protobuf-runtime installations. Matches buf's scope (user module manifest, not full descriptor pool). Resolves adversarial + feasibility P1 finding on WKT pollution. (2) **Backend construction via 4-tuple return** — both `_compile_with_protoxy` and `_compile_with_protoc` grow to return `(pool, root_names, source_info_descriptors, pool_file_names)`; `compile_protos_to_result` tuple-unpacks the 4th element. Resolves feasibility P1 finding on under-specified construction sites. (3) **Keep U4a/U4b 2-commit shape** — no further split into U4a-shape + U4a-engine + U4b-rules; internal coupling between `pool_file_names` field and the pre-walk that consumes it makes a 3-way split forced-feeling. **Auto-fixes:** (i) reconciled Risks + Assumptions to align with the defensive `try/except KeyError: continue` resolution from round 1 (coherence); (ii) reclassified `CompileResult.pool_file_names` from IN to INTERNAL on the U7 Public Surface DRAFT row (scope-guardian — only consumer is the engine pre-walk); (iii) added `compile.py` + `_cli_utils.py` to Sources & References list (coherence); (iv) SC 5 wording clarified — canonical is lex-smallest across full pool, not just root_files (coherence); (v) SC 8c rewritten with explicit file names (`aa.proto` lex-larger than `b.proto`) so canonical computation is unambiguous, plus UX note for U7 docstrings about user-unnamed canonical_file paths (adversarial); (vi) `pool_file_names` field default `()` specified with test-helper update strategy (feasibility); (vii) WKT filter added to pre-walk pseudocode (adversarial + feasibility); (viii) added 4th + 5th smoke fixtures (`empty-package-mixed.proto` for buf-actual no-package behavior verification per adversarial, `wkt-only.proto` for WKT-filter parity verification per feasibility); (ix) `scripts/install-buf.sh` added to U4b scope so the `/ce:plan` gate is runnable on fresh dev environments (feasibility); (x) `/ce:plan` contingencies added — block U4 if buf unavailable, reopen brainstorm if buf-actual contradicts SC 5 hardcode (adversarial); (xi) SC 11b finalized with concrete <50ms target + programmatic 1K-file fixture generator scope (scope-guardian + adversarial); (xii) terminology drift "pool enumeration yields any file" → "pool_file_names is non-empty" standardized (coherence); (xiii) severity recovery-signal limitation acknowledged with rejected mitigations (graceful-rollout flag + telemetry both rejected for scope) per adversarial. 3 residual findings deferred to U7 scope: U7 prose scope creep (CHANGELOG migration + README upgrading subsection are new U7 deliverables beyond parent plan), severity-coherence story across R6/R7 (CHANGELOG framing decision), `canonical_file` user-unnamed path UX (docstring note added to U7 scope). 1 residual concern unresolved: post-ship recovery signal for silent revert-to-0.2.0 — no telemetry available, mitigated only by passive signal (PyPI trends + GitHub issues).

- **2026-05-16 refinement pass (4 user decisions applied):** (1) **Transitive imports → walk full pool** — accumulator iterates new `CompileResult.pool_file_names` field (all pool-registered files, including transitive imports) instead of just `root_files`; findings still emit only on `root_files` via Step 4's existing dispatch gate. Resolves adversarial-reviewer's P1 finding on silent buf-parity weakening for partial-package lints. (2) **Pre-U4 buf smoke test** — `/ce:plan` installs buf v1.69.0 locally and runs 3 smoke fixtures (all-agree / mixed-value / mixed-presence) BEFORE U4 ships to lock canonical-value semantics empirically; replaces "provisional pending U6 parity audit" caveat with empirically-grounded canonical decision. Resolves feasibility + adversarial P1 finding on shipping the canonical-value rule unfalsified. (3) **Severity error + U7 CHANGELOG migration section** — keeps `severity=error` for buf-parity but adds U7 scope: pre-upgrade migration section in CHANGELOG + README enumerating 7 new error sources + `[severities]` demotion escape hatch + example pyproject snippets. Resolves product-lens P1 finding on adoption-dynamics for existing protokit 0.2.0 users. (4) **7 separate rules** — confirmed status quo over 1-rule-with-aliases alternative; per-rule mapping to buf rule_ids matches user `[severities]` configuration ergonomics; alias-resolver landing cost (~30-50 LOC) doesn't justify maintenance-surface savings for a 7-rule one-off family. Resolves product-lens P2 finding on decomposition. **Bonus auto-fix:** empty-package (`""`) early-return added to `_check_package_option` per security-lens cross-namespace contamination concern; new SC 8b + SC 8c (transitive-import canonical computation) tests added.

- **2026-05-15 document-review pass:** 6 personas (coherence + feasibility + product-lens + security-lens + scope-guardian + adversarial). 36 raw findings; 14 auto-fixes applied in-doc + 4 cross-persona convergences merged. Auto-fixes: (1) TL;DR reframed from "first cross-file rule family" architectural lede to "cross-language buf BASIC parity for multi-language teams" user-capability lede, with "drop-in migration" softened to honest "17-of-18 (with 18th in D6c)" framing per product-lens convergence with parent brainstorm; (2) accumulator dict shape resolved 2-level vs 3-level contradiction → unified on 3-level per pseudocode + Output Structure authoritativeness per coherence + scope-guardian convergence; (3) pre-walk `pool.FindFileByName` failure handling: fail-loud lean reversed to defensive `try/except KeyError: continue` matching existing Step 4 pattern at `engine.py:407-412` per feasibility + security + adversarial 3-persona convergence (the codebase pattern resolves the question); (4) `MappingProxyType` 3-level freeze depth specified explicitly + reframed from "security mechanism" to "defense-in-depth against accidental mutation" per security-lens; (5) 500-char truncation cap promoted from `/ce:plan` open question to P0 plan requirement per security-lens (R6 precedent); (6) boolean attr capture shape resolved to `str | None` uniformity per scope-guardian (lean → resolution); (7) `_PACKAGE_SAME_OPTION_ATTRS` single-source-of-truth specified to avoid two-scopes-same-name pitfall per scope-guardian deferred question; (8) `_build_file_ctx` before/after signatures added per coherence; (9) `canonical_fname` → `canonical_file` variable renamed to match params key per coherence; (10) line citations standardized to `engine.py:401-431` for Step 4 broadly per coherence; (11) imports of `Callable, Mapping` added to example rule module pseudocode per feasibility; (12) Open Questions reduced 9 → 5 (4 with strong leans moved to Resolved Here) per scope-guardian; (13) Success Criteria split into "User-outcome criteria" (1-11+11b, 12-14) and "Engineering invariants to preserve" (E1-E6) to separate user-value gates from anti-regression pins per product-lens + scope-guardian; (14) added benchmark gate SC11b ("pre-walk <50ms on 1K-file fixture") so the eager-build cost is measured not asserted per adversarial. 8 strategic findings added to Deferred to Planning for `/ce:plan` resolution: empty-package (`""`) handling (security cross-namespace contamination risk), transitive-import handling (adversarial silently-weakens-buf-parity for partial-package lints — P1 reframe), pre-U4-ship buf empirical smoke test against v1.69.0 (canonical-value decision unfalsified), 7-rules-vs-1-aliased decomposition (product-lens maintenance-surface trade-off), test-helper update strategy (`_DEFAULT_INJECTED` per-context-type split vs direct kwarg). 7 findings deferred as residual: U4a/U4b cost-of-revert if U4b slips (Resolved Here notes the acceptance), 20 Success Criteria → restructured (no loss), adoption-migration path for existing protokit users hitting 7 new error-severity findings on upgrade (deferred to U7 CHANGELOG + README scope), identity coherence of severity choices across R6/R7 (deferred to U7 CHANGELOG framing), engine pre-walk infrastructure compounding direction (deferred to U7 CHANGELOG framing), `canonical_file` path-leak documentation (deferred to U7 README), nested-package scoping (deferred to U6 parity tests).

### Next step

`/ce:plan` against this brainstorm + the parent D6b plan's U4 section + U3's per-unit plan (as the reference shape for per-unit plans in this delivery). `/ce:plan` resolves the deferred Open Questions (boolean attr capture shape, per-rule message_template wording, sanitization length cap, adversarial fixture composition, atomic-vs-split commit shape, MappingProxyType invariant test scope, `pool.FindFileByName` failure handling, structural pin shape, NULL semantic edge case verification) and produces the per-unit plan at `docs/plans/2026-05-15-002-feat-d6b-u4-r7-package-same-plan.md`.
