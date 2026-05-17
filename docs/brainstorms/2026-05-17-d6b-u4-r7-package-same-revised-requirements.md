# protokit-lint D6b U4 — R7 PACKAGE_SAME_* family (REVISED against buf v1.69.0 empirical evidence)

**Status:** brainstorm (requirements). Next step: `/ce:plan`.
**Date:** 2026-05-17.
**Scope:** per-unit. Supersedes `docs/brainstorms/2026-05-15-d6b-u4-r7-package-same-family-requirements.md` after `/ce:work` U0 preflight revealed Outcome C (material divergence from the original architecture).
**Predecessor brainstorm:** `docs/brainstorms/2026-05-15-d6b-u4-r7-package-same-family-requirements.md` (architecture invalidated; structure + scope + engine plumbing decisions preserved).
**Predecessor plan:** `docs/plans/2026-05-17-001-feat-d6b-u4-r7-package-same-plan.md` (engine plumbing units U4a still valid; R7-rules + R7-canonical + R7-sanitize sections need revision per this brainstorm).
**Parent brainstorm:** `docs/brainstorms/2026-05-14-protokit-lint-delivery-6b-option-aware-and-multi-language-requirements.md` (R7 section + Open Questions).
**Parent plan:** `docs/plans/2026-05-14-001-feat-protokit-lint-d6b-option-aware-and-multi-language-plan.md:442-491` (Unit 4 section).
**Empirical foundation:** 21 buf v1.69.0 NDJSON snapshots committed at `tests/schema/lint/rules/fixtures/package_same/_buf_smoke/recorded/` — 7 initial + 7 supplementary (cross-rule homogeneity, sort order, bool rendering) + 7 additional (1 quote-character byte-parity + 6 mixed-presence per non-go_package rule, added after plan document-review's 4-question deferred-resolution pass). Every architectural decision below cites the corresponding recorded snapshot.
**Predecessors shipped:** U1 (`include_source_info` parameter + both backends), U2 (`source_info_descriptors` field on 5 ElementKind contexts + `leading_comment` helper), U3 (R6 5-rule deprecated-replacement family + lint CLI source-info wire-up across both input modes). Suite at 1650 lint+core passing + 39 skips + 17 parity passing.

## TL;DR

U4 still closes the **cross-language buf BASIC parity gap for multi-language teams** (7 PACKAGE_SAME_* rules under `recommended` + `default` profiles, bringing protokit-lint to 17-of-18 buf BASIC rules). What changes vs the original brainstorm: the **rule-helper architecture** is replaced with buf v1.69.0's actual emit semantics, empirically captured via 7 `/ce:work` U0 preflight smoke fixtures. The engine plumbing in U4a (`CompileResult.pool_file_names` field, engine Step 3.5 pre-walk accumulator, `FileLintContext.package_options` field) is **unchanged** — only the per-rule consumer logic and the 3 affected Success Criteria are rewritten.

Three architectural corrections from the original brainstorm, each empirically grounded:

1. **All-disagreers-fire semantics** (was: lex-smallest-canonical, single-finding-on-disagreer). Empirical evidence: `recorded/mixed-value.json` shows buf fires on ALL 3 files (`a.proto`, `b.proto`, `c.proto`) in a 3-file package with disagreeing `go_package = X/Y/X`. Buf has no canonical-file concept; any 2+ distinct values in a `(package, option_attr)` pair flags every participating file equally. Replaces `_canonical(per_file)` + `canonical_file`/`canonical_value` params with a simple `len(set(per_file.values())) > 1` disagreement check + `(package, values_csv, option_attr)` params matching buf's message format.

2. **Empty-package (`""`) enforcement** (was: skip R7 entirely when `ctx.file.package == ""`). Empirical evidence: `recorded/empty-package-mixed.json` shows buf fires on all 3 no-package files with disagreeing `go_package`, with message `"Files in package \"\" have multiple values \"X,Y,Z\" for option \"go_package\" and all values must be equal."` Buf treats `""` as a real namespace; protokit matches. SC 8b's "no-package files skip" deleted.

3. **No WKT filter** (was: skip files whose path begins with `google/protobuf/`). Empirical evidence: `recorded/wkt-conflict.json` shows buf fires on 2 vendored stubs at `google/protobuf/extension_{a,b}.proto` with disagreeing `go_package`. Buf has no special WKT-namespace treatment. The filter was solving a non-problem (real WKTs have consistent `go_package` across the WKT corpus, so real-world imports never trigger findings in the `google.protobuf` package), and keeping it would create a protokit-looser divergence in the exotic user-vendored-WKT-stub case. Drop `_WKT_PATH_PREFIX` constant + the pre-walk filter entirely.

**Architectural footnote (preserved from original):** U4 also adds protokit-lint's first cross-file rule infrastructure (the engine pre-walk accumulator) — this is delivery scaffolding, not the user-facing headline; the next obvious cross-file consumer (`package/same-directory`) needs a different shape so U4's accumulator is bespoke for R7, not general-purpose infrastructure.

Three deliverables (revised):

1. **Engine pre-walk accumulator (UNCHANGED from original brainstorm)** — a new Step 3.5 inside `LintEngine.run` that iterates the FULL `compile_result.pool` (via the new `CompileResult.pool_file_names` field) ONCE before the per-file dispatch walk and builds `package_options: dict[str, dict[str, dict[str, str | None]]]` (3-level: `package_name → option_attr → filename → value`). Walks the full pool (including transitively-imported protos) for buf-parity. **No WKT filter — every file in `pool_file_names` participates.** Findings still emit only on files in `root_files` via the existing Step 4 per-file dispatch gate (preserves protokit's "emit only on user-named files" contract). Iteration is `sorted()` for OS/CI determinism per [[structural-pin-inspect-getsource-untestable-collision-branch]]. Reads each file's options via `pool.FindFileByName(name).GetOptions()` — does NOT depend on `--include_source_info`. Built unconditionally when `pool_file_names` is non-empty. Defensive `try/except KeyError: continue` matches existing Step 4 pattern at `engine.py:407-412`.

2. **FileLintContext.package_options field (UNCHANGED)** — single dataclass addition. `Mapping[str, Mapping[str, Mapping[str, str | None]]] | None`. Engine-injected via `_build_file_ctx`. Frozen via 3-level `MappingProxyType` wraps. Defense-in-depth against accidental mutation by co-authored rule code (NOT a security-trust boundary).

3. **7 R7 rules (REVISED helper architecture)** under `src/protokit/schema/lint/rules/package_same.py`. All 7 share a `_check_package_option(ctx, option_attr, rule_id)` helper that detects per-package disagreement (≥2 distinct values, treating None as a distinct value) and fires on every file in `root_files` that participates in the disagreeing package. Severity `error`, profiles `("recommended", "default")`, `source_spec="buf:PACKAGE_SAME_<NAME>"`. All 3 string `params` values (`package`, `values_payload`, `option_attr`) pass through `_safe_for_stderr(...)[:500]` per [[module-name-newline-injection-stderr-forge]]. Message_template mirrors buf's exact format for parity.

Explicit non-goals (UNCHANGED from original): R7 parity-test fixtures + parity-job verification (U6 — needs harness extension for multi-file invocation). `package/same-directory` (the 18th buf BASIC rule — deferred to D6c per parent brainstorm). R9 schema_version bump (U5).

## Problem Frame

After D6b U3 (R6 deprecated-replacement family + lint CLI source-info wire-up) shipped, protokit's option-aware path is operational. The remaining D6b user-impact gap is cross-language rule-set parity. Today, multi-language teams migrating from `buf lint` to `protokit lint --profile recommended` silently weaken cross-file option enforcement: protokit doesn't fire `PACKAGE_SAME_*`, so the migration "succeeds" with no errors while the policy disappears.

The **architectural blocker** that held R7 back through D2-D6a is cross-file state — today's `LintEngine.run` dispatches FILE-element rules one file at a time. R7 needs to know every file's option value across a package before deciding whether any file disagrees. U4's engine pre-walk closes this gap.

The **architectural revision** in this brainstorm corrects a planning-time assumption error: the original brainstorm assumed buf's emit semantics were "lex-smallest filename = canonical; flag every file that disagrees with canonical." Empirical evidence from `/ce:work` U0 preflight (7 buf v1.69.0 smoke fixtures) showed buf actually does "all disagreers fire; no canonical concept." This is **simpler** than the original architecture but invalidates 3 Success Criteria + the `_canonical` helper + the `canonical_file`/`canonical_value` params + the empty-package skip + the WKT filter.

`package/same-directory` (the 18th buf BASIC rule) needs a different architectural shape and is deferred to D6c. D6b ships **17 of 18 buf BASIC rules**.

## Empirical Foundation (NEW SECTION — buf v1.69.0 smoke-test evidence)

All architectural decisions below cite specific recorded NDJSON snapshots from `tests/schema/lint/rules/fixtures/package_same/_buf_smoke/recorded/` (committed as foundational research artifacts, not part of the regular test run). The 21 fixtures are (14 from the initial + supplementary smoke; 7 added during deferred-question resolution):

| Fixture | Scenario | Buf v1.69.0 emit | Decision impact |
|---|---|---|---|
| `all-agree` | 3 files, all declare `go_package = "github.com/x/y"` | Silent (exit 0) | All-agree = silent. Confirmed. |
| `mixed-value` | 3 files: `a → X, b → Y, c → X` | Fires on **all 3 files** with message `"Files in package "smoke.mixed_value" have multiple values "X,Y" for option "go_package" and all values must be equal."` | **Replaces lex-smallest canonical with all-disagreers-fire.** Drops `_canonical` helper. |
| `mixed-presence` | 3 files: `a` declares X, `b`+`c` omit | Fires on **all 3 files** with message `"Files in package "smoke.mixed_presence" have both values "X" and no value for option "go_package" and all values must be equal."` | **Mixed-presence uses a DIFFERENT message template** ("both values X and no value") than the multi-value case ("multiple values X,Y"). Helper needs to detect which case applies. |
| `empty-package-mixed` | 3 no-package files with `go_package = X/Y/Z` | Fires on **all 3 files** with message `"Files in package "" have multiple values "X,Y,Z" for option "go_package" and all values must be equal."` | **Empty-package (`""`) is a real namespace.** Drops the empty-package skip. |
| `wkt-only` | Single user file in `smoke.wkt_only` importing `google/protobuf/any.proto` | Silent (exit 0) | Single-file-package = silent. Confirmed. Does NOT verify WKT-filter scope (only 1 file in user package). |
| `googleapis-import` | User file in `smoke.googleapis_import` + 2 vendored `google.api` stubs with disagreeing `go_package` | Fires on **2 `google.api` files** with message `"Files in package "google.api" have multiple values "X,Y" for option "go_package" and all values must be equal."` (user file silent — it's in a different package and only 1 file there) | **Non-WKT google.* IS in scope.** Buf doesn't filter `google/api/*`. |
| `wkt-conflict` | 2 vendored stubs at `google/protobuf/extension_{a,b}.proto` with disagreeing `go_package` + user file importing one | Fires on **2 `google/protobuf/extension_*.proto` files** with message `"Files in package "google.protobuf" have multiple values "X,Y" for option "go_package" and all values must be equal."` | **WKT scope is NOT special-cased by buf.** Drops the WKT filter entirely. |
| `mixed-value-java-package` | 3 files, `java_package = "com.example.X/Y/X"` | Fires on **all 3 files** with `"multiple values "com.example.X,com.example.Y" for option "java_package""` | **Identical message template** to PACKAGE_SAME_GO_PACKAGE; cross-rule homogeneity confirmed for `java_package`. |
| `mixed-value-csharp-namespace` | 3 files, `csharp_namespace = "Foo.X/Y/X"` | Fires on all 3 with `"multiple values "Foo.X,Foo.Y" for option "csharp_namespace""` | Cross-rule homogeneity confirmed for `csharp_namespace`. |
| `mixed-value-php-namespace` | 3 files, `php_namespace = "Foo\\X/Y/X"` | Fires on all 3 with `"multiple values "Foo\\X,Foo\\Y" for option "php_namespace""` (in actual message text — JSON escapes backslashes to `\\\\`) | Cross-rule homogeneity confirmed for `php_namespace`. PHP namespace backslashes pass through as-is (no special escaping needed in protokit beyond standard JSON encoding at emit time). |
| `mixed-value-ruby-package` | 3 files, `ruby_package = "Foo::X/Y/X"` | Fires on all 3 with `"multiple values "Foo::X,Foo::Y" for option "ruby_package""` | Cross-rule homogeneity confirmed for `ruby_package`. |
| `mixed-value-swift-prefix` | 3 files, `swift_prefix = "FX/FY/FX"` | Fires on all 3 with `"multiple values "FX,FY" for option "swift_prefix""` | Cross-rule homogeneity confirmed for `swift_prefix`. |
| `mixed-value-java-multiple-files` | 3 files, `java_multiple_files = true/false/true` | Fires on all 3 with `"multiple values "false,true" for option "java_multiple_files""` | **Cross-rule homogeneity confirmed for `java_multiple_files`. CRITICAL: buf renders boolean as LOWERCASE (`"false,true"`), NOT Python title-case (`"False,True"`).** Protokit must use `str(value).lower()` or `json.dumps(value)` for the boolean attr render to byte-match buf. Also empirically confirms alphabetic-by-value sort: input order `true/false/true` produces output `"false,true"` (alphabetic) not `"true,false"` (filename-order). |
| `reverse-order-go` | 3 files, `go_package = "github.com/x/Y/X/Y"` (a=Y, b=X, c=Y) | Fires on all 3 with `"multiple values "github.com/x/X,github.com/x/Y""` | **DECISIVE: buf sorts alphabetic-by-value, NOT filename-order or first-encountered.** Protokit's `sorted(declared_values)` decision is empirically locked. |
| `mixed-value-with-inner-quote` | 3 files, `go_package = "github.com/x/X\"quoted/Y\"quoted/X\"quoted"` | Fires on all 3 with `"multiple values \"github.com/x/X\\\"quoted,github.com/x/Y\\\"quoted\""` — JSON decodes to literal `\"` in message text | **CRITICAL: buf escapes inner `"` characters as `\"` (literal backslash-quote) in the message text.** Protokit's helper MUST apply `value.replace('"', '\\"')` per declared value BEFORE composition, else byte-parity breaks. The `_safe_for_stderr` sanitizer does NOT do this (it only handles control chars). New helper step REQUIRED. |
| `mixed-presence-java-package` | 3 files: a declares `java_package = "com.example.X"`, b+c omit | Fires on all 3 with `"both values "com.example.X" and no value for option "java_package""` | Cross-rule mixed-PRESENCE template confirmed for `java_package` — identical template to `go_package` mixed-presence. |
| `mixed-presence-csharp-namespace` | 3 files: a declares `csharp_namespace = "Foo.X"`, b+c omit | Fires on all 3 with `"both values "Foo.X" and no value for option "csharp_namespace""` | Cross-rule mixed-PRESENCE template confirmed for `csharp_namespace`. |
| `mixed-presence-php-namespace` | 3 files: a declares `php_namespace = "Foo\\X"`, b+c omit | Fires on all 3 with `"both values "Foo\\X" and no value for option "php_namespace""` | Cross-rule mixed-PRESENCE template confirmed for `php_namespace`. PHP backslashes pass through via standard JSON escaping. |
| `mixed-presence-ruby-package` | 3 files: a declares `ruby_package = "Foo::X"`, b+c omit | Fires on all 3 with `"both values "Foo::X" and no value for option "ruby_package""` | Cross-rule mixed-PRESENCE template confirmed for `ruby_package`. |
| `mixed-presence-swift-prefix` | 3 files: a declares `swift_prefix = "FX"`, b+c omit | Fires on all 3 with `"both values "FX" and no value for option "swift_prefix""` | Cross-rule mixed-PRESENCE template confirmed for `swift_prefix`. |
| `mixed-presence-java-multiple-files` | 3 files: a declares `java_multiple_files = true`, b+c omit | Fires on all 3 with `"both values "true" and no value for option "java_multiple_files""` | **Cross-rule mixed-PRESENCE template confirmed for `java_multiple_files`.** Boolean LOWERCASE render confirmed for mixed-presence too (`"true"`, not `"True"`). |

**Cross-fixture invariants observed (empirically confirmed across all 14 fixtures):**

- **Cross-rule homogeneity confirmed for all 7 PACKAGE_SAME_* rules.** Every rule emits the identical message template `'Files in package "{package}" have {payload} for option "{attr}" and all values must be equal.'` with the rule-specific `option` name. The shared `_check_package_option` helper + identical literal `message_template` across all 7 rules is empirically justified, not assumed.
- **`values_csv` sort: alphabetic-by-value (DECISIVE).** `reverse-order-go.json` input `a→Y, b→X, c→Y` produces `"github.com/x/X,github.com/x/Y"`, NOT `"Y,X"`. Protokit's `sorted(declared_values)` is empirically locked.
- **Boolean rendering: LOWERCASE.** `mixed-value-java-multiple-files.json` emits `"false,true"` for the bool attr (NOT Python's title-case `"False,True"`). Protokit must use `str(value).lower()` for `java_multiple_files` to byte-match buf.
- **PHP namespace backslashes: pass-through.** `mixed-value-php-namespace.json` emits backslashes via standard JSON escaping; helper composes raw Python strings, JSON encoding handles wire escaping.
- **Inner `"` characters: ESCAPED as `\"` by buf.** `mixed-value-with-inner-quote.json` (added in the deferred-question-resolution pass) shows buf renders `X"quoted` in the values_csv as `X\"quoted` (literal backslash-quote in message text). **Protokit helper MUST escape inner quotes per-value before composition** via `value.replace('"', '\\"')`. The `_safe_for_stderr` sanitizer does NOT do this. Without the escape, protokit's values_payload contains ambiguous/malformed `"X"quoted,Y"quoted"` and byte-parity breaks.
- **Cross-rule mixed-PRESENCE template uniformity CONFIRMED.** 6 supplementary `recorded/mixed-presence-{rule}.json` snapshots (added in the deferred-question-resolution pass) verify all 6 non-go_package rules emit the identical mixed-presence template `'both values "X" and no value for option "ATTR"'`. Combined with mixed-value uniformity, the shared literal `message_template` across all 7 rules is empirically grounded at both template variants.
- Buf's emit-shape is uniform: when `len(set(per_file.values())) > 1`, fire on every file in the package with the same disagreement message. No exception for any namespace, no "canonical file" concept.
- Two distinct message templates: `"multiple values \"X,Y,Z\""` (when ≥2 distinct non-None values exist) vs `"both values \"X\" and no value"` (when exactly 1 declared value + at least 1 omitter). The latter is buf's special phrasing for mixed-presence; protokit must mirror it.
- All-agree (every file declares same value) = silent. All-omit (every file omits) = silent (would require a separate smoke fixture to verify directly, but the rule "if any file declares" implies it).
- Package name `""` (no package declaration) is treated like any other package name in the message.

**Unverified assumptions (narrowed scope — supplementary smoke confirmed previously-deferred items):**

- ~~Cross-rule homogeneity for the other 6 PACKAGE_SAME_* rules~~ **CONFIRMED** by 6 supplementary smoke fixtures (mixed-value-{java-package,csharp-namespace,php-namespace,ruby-package,swift-prefix,java-multiple-files}.json). All emit the identical message template with the rule-specific `option` name.
- ~~Boolean `java_multiple_files` rendering convention~~ **CONFIRMED LOWERCASE** by `mixed-value-java-multiple-files.json`.
- ~~`values_csv` sort order~~ **CONFIRMED alphabetic-by-value** by `reverse-order-go.json`.
- ~~Cross-rule mixed-presence template~~ **CONFIRMED** by 6 supplementary `recorded/mixed-presence-{rule}.json` snapshots in the deferred-question-resolution pass.
- **Buf's behavior on simultaneous mixed-value + omitters** (4 files: `a→X, b→Y, c→omit, d→omit`) — no smoke fixture covers this. Helper currently falls through to mixed-value path when `len(declared_values) >= 2`. `/ce:plan` decides whether to add a 15th smoke fixture OR accept the fallthrough as approximation.

## Requirements (REVISED)

### R7-engine — Pre-walk file-options accumulator (UNCHANGED from original brainstorm)

Add a new "Step 3.5" inside `LintEngine.run` between Step 3 (filter+bucket specs at `engine.py:389`) and Step 4 (per-file walk at `engine.py:401-431`). The pre-walk pass:

1. Iterates `sorted(compile_result.pool_file_names, key=lambda f: (posixpath.basename(f), f))` — the FULL pool including transitive imports. **Uses `posixpath.basename` (NOT `os.path.basename`) for cross-platform determinism:** protobuf-canonical paths use forward slashes regardless of host OS; `os.path.basename` on Windows would split on `\\` and produce different sort keys on Windows vs POSIX. Findings still emit only on `root_files` via Step 4's existing dispatch gate.
2. **No WKT filter.** Every file in `pool_file_names` participates in the accumulator. (Real WKTs have consistent options across the corpus, so they contribute uniform values to `google.protobuf` and never trigger findings in practice. Synthetic disagreement cases — like the `wkt-conflict` smoke fixture — correctly fire to match buf.)
3. Defensive `try/except KeyError: continue` matches existing Step 4 pattern at `engine.py:407-412`.
4. Accumulator shape: `dict[str, dict[str, dict[str, str | None]]]` (3-level: `package_name → option_attr → filename → value`). Stored per-file value is `str` for declared options OR `None` for omitted options. **Boolean attr `java_multiple_files` is captured as `str(getattr(opts, attr)).lower()` → `"true"` / `"false"`** (LOWERCASE per `recorded/mixed-value-java-multiple-files.json` — buf emits lowercase booleans, not Python's title-case). All other 6 attrs are already string-typed and pass through unmodified.
5. 3-level `MappingProxyType` wrap — outer dict + each per-package dict + each per-attr dict. Defense-in-depth against accidental mutation by co-authored rule code.
6. Always built when `pool_file_names` is non-empty. Lazy-gating deferred to D6c per [[delivery-boundary-unit-commit-composition]]. Benchmark gate per SC E7 (target: pre-walk pass < 50ms on 1K-file synthetic fixture).

### R7-context — FileLintContext.package_options field (UNCHANGED)

Single field addition to `FileLintContext` at `src/protokit/schema/lint/model.py:965-994`. `package_options: Mapping[str, Mapping[str, Mapping[str, str | None]]] | None`. Engine-injected via `_build_file_ctx` kwarg (with default `None` for test-helper / direct-construction backward-compat). Position before the engine-injected `_emit_fn`/`_rule_id`/`_effective_severity` triple, matching U2's positioning convention.

Public Surface DRAFT classification: INTERNAL (engine-injected; consumers are R7 rules, not external callers). Docstring caveat: "subject to change pre-1.0; consumers should not depend on this field."

### R7-rules — 7 PACKAGE_SAME_* rules (REVISED helper architecture)

Ship 7 `@lint_rule`-decorated callables in a single new module `src/protokit/schema/lint/rules/package_same.py`. Module is a SIBLING of `package.py`, NOT a subdirectory inside it (per `package.py:29-34`'s explicit defer comment).

**Per-rule shape** (revised — drops `_canonical`, uses buf's all-disagreers-fire semantics):

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
    # (option_attr_on_FileOptions, rule_id, buf_alias)
    ("go_package", "package/same-go-package", "PACKAGE_SAME_GO_PACKAGE"),
    ("java_package", "package/same-java-package", "PACKAGE_SAME_JAVA_PACKAGE"),
    ("csharp_namespace", "package/same-csharp-namespace", "PACKAGE_SAME_CSHARP_NAMESPACE"),
    ("php_namespace", "package/same-php-namespace", "PACKAGE_SAME_PHP_NAMESPACE"),
    ("ruby_package", "package/same-ruby-package", "PACKAGE_SAME_RUBY_PACKAGE"),
    ("swift_prefix", "package/same-swift-prefix", "PACKAGE_SAME_SWIFT_PREFIX"),
    ("java_multiple_files", "package/same-java-multiple-files", "PACKAGE_SAME_JAVA_MULTIPLE_FILES"),
)

_PACKAGE_SAME_OPTION_ATTR_NAMES: tuple[str, ...] = tuple(
    attr for attr, _, _ in _PACKAGE_SAME_OPTION_ATTRS
)


def _check_package_option(
    ctx: FileLintContext,
    option_attr: str,
    rule_id: str,
) -> None:
    """Fire on every file in root_files participating in a disagreeing package.

    Buf v1.69.0 semantics (empirically verified via _buf_smoke/recorded/):
    if a package has 2+ distinct values for `option_attr` across its files
    (treating "declared" as one value-class and "omitted" as another),
    fire on every file in that package. No canonical-file concept.
    """
    if ctx.package_options is None:
        return  # test-helper path with no accumulator injected
    per_pkg = ctx.package_options.get(ctx.file.package)
    if per_pkg is None:
        return
    per_file = per_pkg.get(option_attr)
    if per_file is None or len(per_file) <= 1:
        return  # single-file package or option-attr unrecorded
    declared_values = {v for v in per_file.values() if v is not None}
    has_omitter = any(v is None for v in per_file.values())
    if len(declared_values) <= 1 and not (has_omitter and declared_values):
        return  # all-agree (single declared value, no omitters) OR all-omit (silent)
    # Disagreement detected — fire on this file (it's in root_files per Step 4 gate).
    # Escape inner `"` characters per declared value to match buf's emit format
    # (empirical: recorded/mixed-value-with-inner-quote.json shows buf renders
    # `X"quoted` as `X\"quoted` with a literal backslash-quote in message text).
    # _safe_for_stderr does NOT do this escaping; it only handles control chars.
    def _escape_inner_quotes(v: str) -> str:
        return v.replace('"', '\\"')
    if len(declared_values) >= 2:
        # Multi-value disagreement: "multiple values "X,Y,Z""
        values_csv = ",".join(_escape_inner_quotes(v) for v in sorted(declared_values))
        message_payload = f'multiple values "{values_csv}"'
    else:
        # Mixed-presence: "both values "X" and no value" (1 declared + omitters)
        single_value = _escape_inner_quotes(next(iter(declared_values)))
        message_payload = f'both values "{single_value}" and no value'
    ctx.emit(
        violation_kind=rule_id,
        params={
            "package": _safe_for_stderr(ctx.file.package)[:500],
            "option_attr": _safe_for_stderr(option_attr)[:500],
            "values_payload": _safe_for_stderr(message_payload)[:500],
        },
    )


@lint_rule(
    rule_id="package/same-go-package",
    severity=LintSeverity.ERROR,
    profiles=("recommended", "default"),
    element=ElementKind.FILE,
    message_template=(
        'Files in package "{package}" have {values_payload} for option '
        '"{option_attr}" and all values must be equal.'
    ),
    source_spec="buf:PACKAGE_SAME_GO_PACKAGE",
)
def check_same_go_package(ctx: FileLintContext) -> None:
    """Every file in a package must agree on `option go_package`.

    Buf parity: buf:PACKAGE_SAME_GO_PACKAGE. Empirically verified against
    buf v1.69.0 in tests/schema/lint/rules/fixtures/package_same/_buf_smoke/recorded/.
    No canonical-file concept; any disagreement flags every file in the
    package equally. Demote via [severities] for legitimate cross-language
    vendor isolation patterns.
    """
    _check_package_option(ctx, "go_package", "package/same-go-package")


# 6 siblings for java_package, csharp_namespace, php_namespace, ruby_package,
# swift_prefix, java_multiple_files.

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

**Message template — uniform across all 7 rules.** The template `'Files in package "{package}" have {values_payload} for option "{option_attr}" and all values must be equal.'` exactly mirrors buf's emit. The `values_payload` param carries the variable phrasing (`"multiple values \"X,Y\""` vs `"both values \"X\" and no value"`) — computed in the helper, not in the template. This keeps each rule's `message_template` literal-identical across the 7 rules (good for grep, good for U7's presence-ratchet test which can assert one substring `'Files in package "'` across all 7 rule_ids).

**Per-rule `option_attr` is hardcoded in the helper call**, not parametrized into the message_template — the template uses `{option_attr}` interpolation. This means every rule's message includes the option name explicitly (`option "go_package"` vs `option "java_package"`) even though the template literal is identical.

**Pack membership: BUILTIN_PACKS registration deferred to U7** per the original brainstorm's U7-deferral decision (preserves the [[pre-1.0-version-bump-as-communication-contract]] — R7 fires as ERROR only after the 0.2.0 → 0.3.0 version bump signals the breaking change). U4b ships R7 as dormant code: importable, fully tested via `--rule-pack=protokit.schema.lint.rules.package_same` explicit opt-in, but NOT in BUILTIN_PACKS by default.

### R7-sanitize — Defense-in-depth on string `params`

All 3 string `params` values pass through `_safe_for_stderr(...)[:500]` at the emit site:

- `package` — user-controlled (proto `package` declaration). Includes `""` for no-package files (empirically observed). 500-char cap bounds DoS amplification.
- `option_attr` — hardcoded protokit constant (e.g., `"go_package"`); defense-in-depth only.
- `values_payload` — synthesized from user-controlled `option go_package = "..."` string values. Multi-KB option strings could inflate; 500-char cap applies after the helper composes the payload.

**Per-value sanitization BEFORE composition** (defense against multi-value injection edge cases): each declared value is individually sanitized via `_safe_for_stderr(v)` AND truncated to a per-value sub-cap (e.g., 100 chars) BEFORE the helper composes them into `values_payload`. Then the composed `values_payload` is sanitized + truncated again at emit time as defense-in-depth. This prevents an adversarial proto from staging a multi-value composition where individual values appear benign but the composed payload contains injected control chars near the 500-char truncation boundary (where the truncation could split a multi-byte UTF-8 line separator).

Mandatory adversarial test fixtures per [[module-name-newline-injection-stderr-forge]]:
- **Single-value injection:** `.proto` with `option go_package = "foo\n error[lint-evil]: forged"` → `params["values_payload"]` sanitized to single-line literal.
- **Multi-value injection:** `.proto` with 2 files declaring `option go_package = "<99 chars>\\n evil"` + `option go_package = "<99 chars>\\n evil2"` → composed `values_payload` has each injection neutralized AT the per-value step, not relying on post-composition sanitization to catch them.
- **Truncation-boundary edge case:** `.proto` whose composed `values_payload` is exactly 499 chars + U+2028 (3 UTF-8 bytes) at position 500 → no malformed truncation; `_safe_for_stderr` collapses U+2028 to a space BEFORE the cap applies.

**Difference from original brainstorm:** the `canonical_file` adversarial vector is no longer relevant (no canonical_file param). The empty-string package name `""` IS now a valid attacker-controlled string in `params["package"]`, but `_safe_for_stderr` on `""` is a no-op (no control chars). The `values_payload` is the primary attack surface — addressed via per-value + composed-payload double-sanitization.

### R7-emit-shape — Emit contract (REVISED — replaces R7-canonical)

For each `(package, option_attr)` pair where the per-file value dict has 2+ entries with disagreement:

1. **Disagreement detection:** `len(set(v for v in per_file.values() if v is not None)) >= 2` OR (`len(distinct_declared_values) == 1` AND `any(v is None for v in per_file.values())`).
2. **All-agree case** (every file declares the same single value) = silent.
3. **All-omit case** (every file omits) = silent. (No declared values to disagree about.)
4. **Mixed-value case** (≥2 distinct declared values): emit on every file in `root_files` participating in this `(package, option_attr)` pair. `values_payload` = `'multiple values "X,Y,Z"'` (comma-joined, sorted-for-determinism).
5. **Mixed-presence case** (exactly 1 declared value + at least 1 omitter): emit on every file in `root_files` participating in this `(package, option_attr)` pair. `values_payload` = `'both values "X" and no value'`.
6. **`root_files` filter is load-bearing:** transitively-imported files (in `pool_file_names` but NOT `root_files`) contribute to the disagreement detection but do NOT receive findings. Preserves protokit's "emit only on user-named files" contract. Buf walks the full module and fires on every package file; protokit's narrower emit is acceptable when the user invokes protokit on a subset of their module (per the partial-package divergence documented in `/ce:plan` Open Questions).
7. **Empty-package (`""`) participates in enforcement.** No skip. Matches buf-actual.
8. **Sorted-for-determinism:** the `values_payload` in `values_payload` is sorted alphabetically (`"X,Y,Z"`, not `"Z,X,Y"`) so the message is byte-stable across iteration orders. Note: buf v1.69.0's `recorded/mixed-value.json` shows `"X,Y"` (a → X declared first, b → Y second). Whether buf sorts or uses first-encountered order is an open question for U6 parity. **Protokit chooses alphabetic sort for determinism;** if U6 reveals buf's order, document the divergence in `_PARITY_EXCEPTIONS` per [[buf-parity-divergence-documentation-discipline]].

### R7-CompileResult — pool_file_names field (UNCHANGED)

`CompileResult.pool_file_names: tuple[str, ...] = ()` between `root_files` and `diagnostics`. Populated via 4-tuple backend return from `_compile_with_protoxy` + `_compile_with_protoc`. Descriptor-set-mode loader populates symmetrically.

**Invariant mechanism — diagnostic emission, NOT `assert`** (per [[no-raise-contract-extends-to-post-init-failures]]): `__post_init__` checks `pool_file_names == () OR set(pool_file_names) >= set(root_files)`. On violation, append a `LintCompileDiagnostic(level="error", message="...")` to `diagnostics` and force `pool_file_names = ()` (so the pre-walk early-returns and R7 silently no-ops on the broken input rather than mis-firing on partial state). **Why not `assert`:** `assert` is stripped under `python -O`, converting the invariant into silent rule-disablement. **Why not `raise ValueError`:** violates `CompileResult`'s documented no-raise contract (`compile.py:165-169` — "Always returned (never raised)"). Diagnostic-emission matches the existing pattern: the field is populated alongside `root_files` at the same backend boundary; any inconsistency between them is a backend bug surfacable to the caller via `diagnostics` (the same channel U1's `_populate_pool_with_capture` already uses for capture failures).

### R7-CLI — Zero CLI changes (UNCHANGED)

R7 needs no CLI changes. FileOptions are first-class `FileDescriptor` attributes; they survive `pool.Add(fd)` regardless of `--include_source_info`. Both `--proto` mode AND `--descriptor-set` mode work identically.

## Non-Goals (deferred — UNCHANGED from original)

- **R7 parity-test fixtures + parity-job verification** — U6. The 7 buf-smoke recorded snapshots already provide empirical grounding, but parity fixtures + harness extension for multi-file invocation are U6 scope.
- **`package/same-directory`** — D6c. Different architectural shape (cross-file disagreement detection + per-package finding aggregation).
- **R9 `severities_unloaded_rule` category split + schema_version bump** — U5.
- **R11 CHANGELOG D6b section + R12 Public Surface DRAFT additions + README refresh + 0.2.0 → 0.3.0 version bump** — U7.
- **Pre-upgrade migration section in CHANGELOG + README "upgrading from 0.2.0" subsection** — U7. **Pre-specified content scope (must cover):** (1) **+7 new ERROR-severity rules** enumerated with rule_ids + buf_alias mapping + which profile (`recommended`+`default`); (2) **N-not-N-1 per-package emit cardinality** — explicit quantification: "each PACKAGE_SAME_* violation now produces one finding per file in the package, not one finding per disagreer. A 5-file package with disagreement produces 5 findings per affected rule × 7 rules = up to 35 findings"; (3) **`""`-package monorepo aggregation behavior** — explicit explanation that protos lacking `package` declarations are treated as a single synthetic `""` namespace and ALL no-package files contribute to disagreement detection, with mitigation recipe (declare `package` on all protos, OR demote per-rule via `[severities]` for known-no-package file globs); (4) **Transitive-import supply-chain note** — third-party library imports contribute to disagreement detection; pin dependency versions OR demote PACKAGE_SAME_* when third-party imports introduce conflicts; (5) **WKT enforcement note** — exotic but possible; users with non-standard WKT vendoring should demote or rename; (6) **Example pyproject `[tool.protokit.lint.severities]` snippets** showing per-rule demotion to `warning` or `info`; (7) **`--rule-pack` opt-in pattern** for users who want R7 before the 0.3.0 upgrade lands.
- **`canonical_file` path-leak docs note** — DELETED (no canonical_file param exists).
- **Lazy-build pre-walk gating** — D6c if SC E7 benchmark gate measurement shows the pre-walk is hot at scale.
- **Cross-rule verification for the other 6 PACKAGE_SAME_* rules** — U6 parity tests. The 7 buf-smoke fixtures verified `PACKAGE_SAME_GO_PACKAGE` only; the other 6 are assumed-homogeneous-with-go_package and will be empirically verified at U6.

## Open Questions

### Deferred to Planning

- **Per-rule `message_template` literal wording** — all 7 rules use the identical template `'Files in package "{package}" have {values_payload} for option "{option_attr}" and all values must be equal.'` — `/ce:plan` confirms the literal string (whitespace, punctuation) matches buf v1.69.0's exact emit format. The U7 presence-ratchet test asserts the substring `'Files in package "'` appears in every R7 rule's message_template.
- **Adversarial fixture composition** — single shared `.proto` file with multiple files in different packages containing newline-injection / U+2028/U+2029 / control-char / multi-KB option values. Mirrors U3 R6 adversarial fixture density.
- **`MappingProxyType` 3-level invariant test scope** — 3-level mutation-raises tests (covers `[pkg] =`, `[pkg][attr] =`, `[pkg][attr][fname] =`).
- **Pre-walk pass placement contract test** — `inspect.getsource(LintEngine.run)` structural pin asserts `sorted(compile_result.pool_file_names, key=lambda f: (os.path.basename(f), f))` substring + that the pre-walk loop appears BEFORE the Step 4 file walk. **No WKT-filter substring to pin** (filter dropped).
- **Test-helper update strategy** — direct kwarg `package_options=None` on `_make_file_ctx` (NOT added to `_DEFAULT_INJECTED`).
- **NULL semantic edge case test scenarios** — explicit tests for: single-declaring file (1 declared + 2 omitters → all 3 fire); mixed-value (2 declared values → all participating files fire); empty-package (3 no-package files with disagreement → all 3 fire); all-omit (3 files all omit → silent); single-file package (1 file in package → silent regardless).
- **`values_payload` sort order vs buf-actual** — `/ce:plan` confirms whether buf sorts alphabetically (deterministic) or uses first-encountered order. The empirical evidence (`recorded/mixed-value.json` shows `"X,Y"` from a→X, b→Y, c→X) is ambiguous between "alphabetic sort" and "first-encountered." A 2-fixture supplementary test (`recorded/reverse-order.json`: a→Y, b→X, c→Y to see if buf emits `"X,Y"` or `"Y,X"`) could disambiguate. Lean: protokit picks alphabetic for determinism; document divergence at U6 if buf uses different order.
- **Boolean `java_multiple_files` rendering** — **RESOLVED (empirically): LOWERCASE.** Per `recorded/mixed-value-java-multiple-files.json`, buf emits `"false,true"` (lowercase). Protokit's pre-walk capture uses `str(getattr(opts, attr)).lower()` for the `java_multiple_files` attr to byte-match buf; alternative `json.dumps(value)` also works (produces lowercase booleans + handles None as `null` though None is captured separately in protokit's pipeline). The 6 string attrs pass through unmodified.

### Resolved Here (REVISED — adds new resolutions, removes obsolete)

- **All-disagreers-fire semantics.** Empirical (`recorded/mixed-value.json`, `recorded/mixed-presence.json`). Drops `_canonical(per_file)` helper. Drops `canonical_file`/`canonical_value` params.
- **Empty-package (`""`) participates in R7 enforcement.** Empirical (`recorded/empty-package-mixed.json`). Drops the empty-package skip in `_check_package_option`. SC 8b deleted.
- **No WKT filter at `google/protobuf/` prefix.** Empirical (`recorded/wkt-conflict.json` shows buf fires on disagreeing google.protobuf files). Drops `_WKT_PATH_PREFIX` constant + the pre-walk filter. Real WKTs have consistent options across the corpus and never trigger findings in practice; the synthetic disagreement case correctly fires to match buf.
- **Two distinct message templates needed.** Empirical: buf uses `"multiple values \"X,Y\""` (≥2 declared) vs `"both values \"X\" and no value"` (1 declared + omitters). Protokit's `_check_package_option` selects the right phrasing based on declared-value count + omitter presence; the per-rule `message_template` carries the variable payload via `{values_payload}` interpolation. All 7 rules use the identical literal template.
- **Inner `"` escape: helper applies `value.replace('"', '\\"')` per declared value BEFORE composition.** Empirical (`recorded/mixed-value-with-inner-quote.json` — added in the deferred-question-resolution pass). Buf renders inner quotes as literal backslash-quote in message text; protokit must match for byte-parity. `_safe_for_stderr` does NOT do this escaping; the helper applies it explicitly. Adversarial test fixture verifies the round-trip.
- **3 string `params` values** (was 4): `package`, `option_attr`, `values_payload`. Drops `canonical_file` and `canonical_value` (no longer exist). Drops `value` (replaced by `values_payload` containing the disagreement summary, not the per-file value).
- **Engine pre-walk: walk FULL pool, emit on root_files only.** Unchanged from original brainstorm + user's transitive-imports decision in refinement round 2. Re-confirmed: buf-actual confirms full-package enforcement is correct; protokit's emit-only-on-root_files is a documented divergence in partial-package lints.
- **`CompileResult.pool_file_names`: 4-tuple backend return + `__post_init__` invariant.** Unchanged from refinement round.
- **Module shape: SINGLE FILE** `src/protokit/schema/lint/rules/package_same.py` (UNCHANGED).
- **Module location: SIBLING of `package.py`** (UNCHANGED).
- **`MappingProxyType` 3-level freeze** (UNCHANGED, defense-in-depth).
- **`pool.FindFileByName` defensive `try/except KeyError: continue`** matches Step 4 pattern (UNCHANGED).
- **Built unconditionally when `pool_file_names` is non-empty** + benchmark gate (UNCHANGED — SC E7 still applies).
- **Boolean attr capture shape: `str | None` uniformity** via `str(getattr(opts, attr))` cast (UNCHANGED).
- **Sanitization length cap: 500 chars** per [[module-name-newline-injection-stderr-forge]] + R6 precedent (UNCHANGED).
- **Severity: ERROR + U7 CHANGELOG migration section** (UNCHANGED — registration deferred to U7).
- **Profiles: `("recommended", "default")`** (UNCHANGED — locked at parent brainstorm + plan, registration via BUILTIN_PACKS at U7).
- **`source_spec="buf:PACKAGE_SAME_<NAME>"`** auto-discovered by parity harness (UNCHANGED).
- **R7 needs zero CLI changes** (UNCHANGED).
- **`source_info_descriptors` NOT added to FileLintContext** (UNCHANGED).
- **Parity tests deferred to U6** (UNCHANGED — but U4a's preflight smoke fixtures provide the empirical foundation U6 builds on).
- **README + CHANGELOG + Public Surface DRAFT updates deferred to U7** (UNCHANGED).
- **`CompileResult.pool_file_names` INTERNAL classification** with explicit docstring caveat (UNCHANGED).
- **Single source of truth for `_PACKAGE_SAME_OPTION_ATTRS`** in `package_same.py` (UNCHANGED).
- **BUILTIN_PACKS registration deferred to U7** alongside the 0.2.0 → 0.3.0 version bump (UNCHANGED from refinement round).
- **Rule decomposition: 7 SEPARATE rules** (UNCHANGED — 1:1 mapping to buf rule_ids).
- **Commit shape: U4a/U4b 2-commit** (UNCHANGED).
- **U0 preflight smoke fixtures + test_buf_smoke_assumptions.py + CONTRIBUTING.md note** (UNCHANGED).

## Success Criteria (REVISED — SC 5/6/8b/8c rewritten)

### User-outcome criteria (these answer "did we deliver value?")

1. **7 R7 rules registered and visible** under `protokit lint --rule-pack=protokit.schema.lint.rules.package_same --profile recommended --format=json <fixture>`. BUILTIN_PACKS registration deferred to U7; U4b ships rules as opt-in via `--rule-pack`.

2. **All 7 rules fire under `default` profile too** (same `--rule-pack` opt-in). Same fixtures; identical findings.

3. **All-agree happy path: zero findings.** 3-file package where every file declares the same option value → silent. Verified per ElementKind option attr (7 rules × happy-path fixture).

4. **All-omit happy path: zero findings.** 3-file package where no file declares the option → silent (matches `recorded/all-agree.json` invariant; verifiable as inverse).

5. **Mixed-value sad path: all files in package fire** (REVISED — was "N-1 findings on disagreer"). 3-file package: `a → "X", b → "Y", c → "X"`. **ALL 3 files emit findings** with `params["values_payload"] = 'multiple values "X,Y"'`. Matches `recorded/mixed-value.json`. Verified per ElementKind option attr.

6. **Mixed-presence sad path: all files in package fire** (REVISED — was "N-1 findings on omitters"). 3-file package: `a` declares `"X"`, `b` and `c` omit. **ALL 3 files emit findings** with `params["values_payload"] = 'both values "X" and no value'`. Matches `recorded/mixed-presence.json`. Verified per ElementKind option attr.

7. **Single-file package: zero findings.** A 1-file package produces zero findings (no disagreement possible).

8. **Multi-package isolation.** Fixture with two packages `foo.bar` + `foo.baz`; disagreement in `foo.bar` does NOT fire findings on files in `foo.baz`. Per-package scoping verified.

8b. **Empty-package (`""`) enforcement** (REVISED — was "empty-package skip"). 3 no-package files with disagreeing `go_package` → **ALL 3 files emit findings** with `params["package"] = ""` and `params["values_payload"] = 'multiple values "X,Y,Z"'`. Matches `recorded/empty-package-mixed.json`. Resolves the security-lens cross-namespace contamination concern by matching buf-actual.

8c. **Transitive-import canonical computation** (REVISED — was "emit on root_files with canonical from transitive"). Fixture where `a.proto` is named on the CLI (in `root_files`) declaring `go_package = "X"`, and `b.proto` is transitively imported (in `pool_file_names` but NOT `root_files`) declaring `go_package = "Y"`. **ONE finding on `a.proto`** with `params["values_payload"] = 'multiple values "X,Y"'`. The transitively-imported `b.proto` does NOT receive a finding (Step 4's emit gate limits dispatch to `root_files`). Verifies that transitive imports contribute to disagreement detection but don't receive findings.

8d. **WKT enforcement** (NEW — replaces the deleted WKT filter SC). Fixture with 2 stubs at `google/protobuf/extension_{a,b}.proto` declaring disagreeing `go_package`, both in `root_files`. **BOTH files emit findings** with `params["package"] = "google.protobuf"` and `params["values_payload"] = 'multiple values "X,Y"'`. Matches `recorded/wkt-conflict.json`. Verifies no WKT special-case treatment.

9. **`include_source_info` independence.** R7 rules fire identically whether `compile_protos_to_result(include_source_info=True)` or `include_source_info=False`. (UNCHANGED.)

10. **Adversarial sanitization.** Fixture with `option go_package = "foo\n error[lint-evil]: forged"` produces a finding whose `params["values_payload"]` is sanitized to single-line literal AND truncated to ≤500 chars. Mandatory per [[module-name-newline-injection-stderr-forge]].

11. **Per-rule demotion via `[tool.protokit.lint.severities]` works** for any of the 7 R7 rule_ids — verified by a fixture pyproject + a runtime test using `--rule-pack` opt-in.

12. **D6b U1+U2+U3 regressions: zero.** The 1650-test baseline continues to pass.

13. **Integration: end-to-end lint invocation with explicit opt-in.** `protokit lint --rule-pack=protokit.schema.lint.rules.package_same --profile recommended --format json <multi-file fixture dir>` produces expected R7 findings; `protokit lint --profile recommended <same fixture>` WITHOUT `--rule-pack` produces ZERO R7 findings (verifies U4b→U7 dormancy contract).

14. **`--descriptor-set` mode parity with `--proto` mode.** R7 rules fire identically when invoked with `--descriptor-set <set>` vs `--proto <files>` (with `--rule-pack` opt-in) on the same fixture.

15. **Buf-smoke regression gate (dual-mode).** `test_buf_smoke_assumptions.py` operates in two modes per [[audit-wire-format-before-claiming-sibling-parity]]: **(a) live mode** (when `BUF_BINARY` env is set) — re-invokes buf at test time against the 7 smoke fixtures and asserts live output byte-matches the recorded `recorded/*.json` snapshots; detects buf-version drift on every CI parity-job run. **(b) snapshot-consistency mode** (when `BUF_BINARY` is unset) — loads the recorded snapshots and asserts they encode the plan's architectural assumptions (all-disagreers-fire for mixed-value/mixed-presence/empty-package/wkt-conflict; silence for all-agree/wkt-only/single-file); catches accidental snapshot corruption + documents the contract. Both modes always run; BUF_BINARY presence determines which invariant is validated. Converts the U0 cognitive gate into a binary pass/fail with real regression detection.

### Engineering invariants to preserve (these answer "did we avoid regression?")

E1. **Pre-walk pass iteration determinism.** Structural test asserts `inspect.getsource(LintEngine.run)` contains `sorted(compile_result.pool_file_names, key=lambda f: (os.path.basename(f), f))` substring + that the pre-walk loop appears BEFORE the Step 4 file walk. **No WKT-filter substring to pin** (filter dropped from architecture).

E2. **`MappingProxyType` 3-level immutability invariant** (UNCHANGED). Mutation attempts at all 3 nesting depths raise `TypeError`.

E3. **BUILTIN_PACKS membership-pin test passes** with the unchanged `expected` tuple at U4b (R7 not in BUILTIN_PACKS until U7). **At U7**, the test extends to include `package_same`.

E4. **Cold-import contract holds.** `import protokit.schema` does NOT transitively load `protokit.schema.lint.rules.package_same`. Existing `tests/schema/lint/test_cold_import_extended.py` extended at U4b to explicitly forbid the new module path.

E5. **Static-analysis ratchet holds** (UNCHANGED).

E6. **Engine pre-walk accumulator shape test.** Unit test asserts the accumulator structure for a known multi-file fixture (UNCHANGED).

E7. **Pre-walk benchmark gate: <50ms cost on 1K-file fixture** (UNCHANGED). Uses `time.perf_counter()` + `pytest.mark.slow` pattern; 1K-file corpus generated programmatically in the test via tmp_path.

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Original brainstorm's lex-smallest canonical architecture invalidated mid-work | **Resolved by this revision.** Buf smoke-test preflight detected the divergence; this brainstorm captures the corrected architecture before any production code lands. |
| Other 6 PACKAGE_SAME_* rules behave differently than PACKAGE_SAME_GO_PACKAGE | **U6 parity tests catch divergence.** Lean: buf's rule family is homogeneous (all 7 follow the same pattern in buf's source); if measurement reveals divergence, document per [[buf-parity-divergence-documentation-discipline]] + `_PARITY_EXCEPTIONS`. |
| `values_payload` sort order divergence (alphabetic vs first-encountered) | `/ce:plan` runs supplementary smoke fixture (`reverse-order` with `a → Y, b → X`) if needed; alphabetic-sort decision locked here with U6 verification gate. |
| Boolean `java_multiple_files` rendering divergence | **RESOLVED:** empirically locked to lowercase (`recorded/mixed-value-java-multiple-files.json`). Pre-walk uses `str(value).lower()` for `java_multiple_files`. |
| `values_csv` sort-order divergence (alphabetic vs filename vs first-encountered) | **RESOLVED:** empirically locked to alphabetic-by-value (`recorded/reverse-order-go.json`). Pre-walk uses `sorted(declared_values)`. |
| Cross-rule homogeneity assumption (other 6 PACKAGE_SAME_* rules) | **RESOLVED:** confirmed by 6 supplementary smoke fixtures (`recorded/mixed-value-{java-package,csharp-namespace,php-namespace,ruby-package,swift-prefix,java-multiple-files}.json`). Shared `_check_package_option` helper + identical `message_template` literal across all 7 rules is empirically justified. |
| Empty-package (`""`) cross-namespace contamination in multi-tenant monorepos | **Accepted tradeoff per buf-parity.** Original security-lens concern (an adversarial or accidentally-included no-package proto can force findings on every other no-package file in a lint run) is real but inherited from buf-actual behavior. U7 CHANGELOG explicitly documents this aggregation and recommends mitigation: (a) declare `package` on all protos, OR (b) demote PACKAGE_SAME_* per-rule via `[severities]` for known-no-package file globs. Per-package severities overrides + per-import scoping deferred to D6c. |
| Transitive-import supply-chain finding injection | **Acknowledged.** The pre-walk iterates the FULL pool including transitively-imported third-party library protos. A dependency's `option go_package` change can inject findings on user-owned protos; no way to scope suppression to a single transitive dep (only global per-rule demotion via `[severities]`). U7 CHANGELOG documents this with a recommendation: pin dependency versions OR demote PACKAGE_SAME_* when third-party imports introduce conflicts. Per-import scoping deferred to D6c. |
| WKT enforcement creates exotic-but-legal attack surface (`google/protobuf/` files in user's pool with disagreeing `go_package`) | **Acknowledged.** Real WKTs from the protobuf-runtime corpus have consistent `go_package` values, so this never fires in practice. Synthetic disagreement cases (vendored WKT stubs, accidental `package google.protobuf` declarations) DO fire to match buf. U7 CHANGELOG documents this; users with non-standard WKT vendoring should demote PACKAGE_SAME_* or rename to a private namespace. |
| R7 false positives on legitimate cross-language differences | Per-rule demotion via `[severities]` available immediately. U7 README documents the demotion pattern. |
| Adversarial protos with multi-KB option strings inflate finding params | 500-char cap on `values_payload`; mandatory adversarial test fixture. |
| 4-tuple backend return breaks existing 3-tuple callers | Audit during U4a (grep for `_compile_with_protoxy(` + `_compile_with_protoc(` callers). |
| `FileLintContext.package_options` field addition breaks dataclass-positional callers | Audit during U4a (grep gate for `FileLintContext(` constructors). |
| Existing protokit 0.2.0 users see 7 new error-severity findings on upgrade to 0.3.0 | **Resolved at refinement round 2 + preserved here:** BUILTIN_PACKS registration deferred from U4b to U7 alongside the 0.2.0 → 0.3.0 version bump per [[pre-1.0-version-bump-as-communication-contract]]. R7 dormant in U4b (only accessible via `--rule-pack` opt-in). |
| Engine pre-walk infrastructure justified by one delivery; D6c's `package/same-directory` needs different shape | Accepted; CHANGELOG framing at U7 honestly describes this as bespoke R7 infrastructure, not generic cross-file-rule foundation. |
| Buf v1.69.0 emit-shape changes in a future buf version | `_BUF_PARITY_PIN` documents the pinned version. Recorded NDJSON snapshots regenerated when buf-pin bumps (documented in U7 CHANGELOG note). |
| Cross-protobuf-runtime (4 vs 5) `pool_file_names` divergence | U4a cross-runtime verification step mirrors U1's pattern. |

## Assumptions

- **Buf v1.69.0's PACKAGE_SAME_GO_PACKAGE semantics are representative of the other 6 PACKAGE_SAME_* rules.** Verified at U6 parity tests; if U6 reveals divergence (e.g., `java_multiple_files` uses different message template), document via `_PARITY_EXCEPTIONS`.
- **`pool.FindFileByName(name)` succeeds for every name in `compile_result.pool_file_names` in the typical case.** On the compile-failure path the lookup can raise `KeyError`; both Step 3.5 and Step 4 wrap defensively.
- **`FileOptions.HasField(attr)` correctly reports presence for proto3 scalar message-default detection.** Standard protobuf 4+ API.
- **`MappingProxyType` 3-level wrap is the right freeze mechanism.** Mirrors U1+U2 patterns.
- **`include_imports=True` on both compile backends means `pool_file_names` contains transitive imports.** Verified by `googleapis-import.proto` smoke fixture (the user file imports `google/api/annotations.proto`; both `annotations.proto` and `http.proto` appear in the pool and contribute to `google.api` package accumulation).
- **`values_payload`'s comma-joined-sorted format byte-matches buf's output** when buf uses the same sort order. If buf uses first-encountered, U6 detects the divergence.

## Output Structure (this unit's commit shape — UNCHANGED)

**U4a: Engine plumbing + buf smoke-test preflight (already partially completed via `/ce:work` U0)** — 1 commit.

The 7 buf-smoke recorded NDJSON snapshots + 7 fixture subdirectories are already committed to main (commits `68f4a93` + the wkt-conflict supplementary commit). U4a's remaining scope:

- Source:
  - `src/protokit/schema/compile.py` — `CompileResult.pool_file_names` field + `__post_init__` invariant.
  - `src/protokit/_cli_utils.py` — `_compile_with_protoxy` + `_compile_with_protoc` 4-tuple return.
  - `src/protokit/schema/compile.py:_compile_protos_to_result` — tuple-unpack 4th element.
  - `src/protokit/schema/lint/_cli_utils.py:_load_descriptor_sets_to_result` — populate `pool_file_names` symmetric with `root_files`.
  - `src/protokit/schema/lint/engine.py` — Step 3.5 pre-walk pass + `_build_file_ctx` kwarg + 3-level `MappingProxyType` wrap. **NO WKT filter.**
  - `src/protokit/schema/lint/model.py:965-994` — `FileLintContext.package_options` field.
  - `CONTRIBUTING.md` — buf install note (3 lines pointing at `BUF_BINARY` env discovery + v1.69.0 release tarball).
- Tests:
  - `tests/schema/lint/test_compile_pool_file_names.py` (NEW).
  - `tests/schema/lint/test_engine_pre_walk.py` (NEW) — accumulator construction, 3-level `MappingProxyType` invariant, sorted iteration determinism, multi-package isolation, single-file, all-omit, all-same, mixed-presence, mixed-value, transitive-import-contributes-to-disagreement-detection, empty-package-fires, **wkt-fires (no special-case)**, structural pin via `inspect.getsource`, benchmark gate.
  - `tests/schema/lint/test_buf_smoke_assumptions.py` (NEW) — **dual-mode design** per [[audit-wire-format-before-claiming-sibling-parity]]: (a) when `BUF_BINARY` env var is set, re-invokes buf at test time against the 7 smoke fixtures and asserts the live output byte-matches the recorded `recorded/*.json` snapshots (detects buf-version drift; gates buf-pin bumps in CI); (b) when `BUF_BINARY` is unset, loads the recorded snapshots + asserts they match the plan's architectural assumptions documented in this brainstorm (catches accidental snapshot corruption + documents the contract the snapshots encode). Mode (a) is the real regression gate; mode (b) is the docs-consistency check. Both modes run by default; the BUF_BINARY presence determines which mode validates which invariant. Uses the existing parity-harness BUF_BINARY discovery pattern at `tests/parity/conftest.py:283-302`.
  - `tests/schema/lint/test_model.py` (extend) — `_make_file_ctx` kwarg.
  - `tests/test_static_analysis.py:_LINT_PATHS` (extend per ratchet).

Estimated test count: ~15-20 new tests in U4a.

**U4b: 7 R7 rules + adversarial fixture + integration tests** — 1 commit.

- Source:
  - `src/protokit/schema/lint/rules/package_same.py` (NEW) — 7 rules + `_check_package_option` + `_PACKAGE_SAME_OPTION_ATTRS` (triples) + `_PACKAGE_SAME_OPTION_ATTR_NAMES` + `RULES` tuple. **NO `_canonical` helper.**
  - `src/protokit/schema/lint/rules/__init__.py:66-71` — import `package_same` module (DOES NOT extend BUILTIN_PACKS — deferred to U7).
  - `tests/schema/lint/test_cold_import_extended.py:48-54` — extend forbidden-modules check.
  - `tests/test_static_analysis.py:_LINT_PATHS` — extend.
- Tests:
  - `tests/schema/lint/rules/test_package_same.py` (NEW) — 7-rule family tests (happy/sad/edge per rule) + adversarial sanitization + per-rule `[severities]` demotion (folded inline per R6 precedent).
  - `tests/schema/lint/rules/fixtures/package_same/proto_templates.py` (NEW) — programmatic fixture builder.
  - `tests/schema/lint/rules/fixtures/package_same/adversarial.proto` (NEW) — adversarial sanitization fixture.
  - `tests/schema/lint/test_cli_package_same_e2e.py` (NEW) — end-to-end with explicit `--rule-pack` opt-in.

Estimated test count: ~50-70 new tests in U4b. Total suite count: 1650 → ~1720-1740.

## Sources & References

- **Predecessor brainstorm:** `docs/brainstorms/2026-05-15-d6b-u4-r7-package-same-family-requirements.md` (architecture invalidated; structure preserved).
- **Predecessor plan:** `docs/plans/2026-05-17-001-feat-d6b-u4-r7-package-same-plan.md` (U4a engine plumbing valid; R7-rules/R7-canonical/R7-sanitize need revision).
- **Parent brainstorm:** `docs/brainstorms/2026-05-14-protokit-lint-delivery-6b-option-aware-and-multi-language-requirements.md` (R7 section).
- **Parent plan:** `docs/plans/2026-05-14-001-feat-protokit-lint-d6b-option-aware-and-multi-language-plan.md:442-491` (Unit 4 section).
- **Empirical foundation (7 buf v1.69.0 NDJSON snapshots):** `tests/schema/lint/rules/fixtures/package_same/_buf_smoke/recorded/{all-agree,mixed-value,mixed-presence,empty-package-mixed,wkt-only,googleapis-import,wkt-conflict}.json`. Fixture sources at `tests/schema/lint/rules/fixtures/package_same/_buf_smoke/{name}/`.
- **U3 per-unit brainstorm:** `docs/brainstorms/2026-05-15-d6b-u3-r6-deprecated-replacement-family-requirements.md` (per-unit brainstorm shape reference).
- **Engine to extend:** `src/protokit/schema/lint/engine.py` (`LintEngine.run` at L275-431; per-file walk at L401-431).
- **CompileResult to extend:** `src/protokit/schema/compile.py:161-220`.
- **Compile backends to extend:** `src/protokit/_cli_utils.py:221-269` (`_populate_pool_with_capture`; helper signature unchanged), `_compile_with_protoxy` at L273-346, `_compile_with_protoc` at L349+ (4-tuple return).
- **Descriptor-set loader to extend:** `src/protokit/schema/lint/_cli_utils.py:259-403`.
- **FileLintContext to extend:** `src/protokit/schema/lint/model.py:965-994`.
- **Pack registry:** `src/protokit/schema/lint/rules/__init__.py:66-71, 94-101` (BUILTIN_PACKS — UNCHANGED at U4b; extended at U7).
- **Sanitizer to reuse:** `src/protokit/schema/lint/_cli_utils.py:198-245` (`_safe_for_stderr`).
- **Pattern modules to mirror:** `src/protokit/schema/lint/rules/imports.py:64-92`, `src/protokit/schema/lint/rules/naming.py`, `src/protokit/schema/lint/rules/package.py:29-34`, `src/protokit/schema/lint/rules/options/deprecated_replacement.py` (R6).
- **Parity harness reference:** `tests/parity/conftest.py:31-36, L283-302` (`BUF_BINARY` env discovery), `_BUF_PARITY_PIN = "v1.69.0"` at `src/protokit/schema/lint/cli.py:149`.
- **Buf documentation:** <https://buf.build/docs/lint/rules#package_same_go_package>.
- **Buf release pin:** <https://github.com/bufbuild/buf/releases/tag/v1.69.0>.

### Institutional learnings applied

- [[buf-parity-divergence-documentation-discipline]] — each R7 rule docstring documents buf parity + empirical-evidence reference; U6 parity tests + `_PARITY_EXCEPTIONS` cover any measured divergence.
- [[audit-wire-format-before-claiming-sibling-parity]] — **directly applied via U0 preflight smoke-test evidence.** The 7 buf v1.69.0 NDJSON snapshots are the audit; the architectural corrections in this brainstorm are the response. Demonstrates the discipline at maximum strength.
- [[module-name-newline-injection-stderr-forge]] — R7 sanitization mandatory; adversarial fixture is a P0 plan requirement.
- [[structural-pin-inspect-getsource-untestable-collision-branch]] — pre-walk pass placement + sorted iteration pinned. **WKT-filter substring removed from pin** (filter dropped).
- [[pytest-static-analysis-gate-ratchet]] — new paths added to `_LINT_PATHS` in the same commit they're created.
- [[delivery-boundary-unit-commit-composition]] — U4a/U4b commit shape (engine plumbing isolated from rule consumers); README/CHANGELOG/Public Surface DRAFT updates land at U7.
- [[scope-guardian-resists-context-bloat-add-when-needed]] — `source_info_descriptors` NOT added to FileLintContext; single-field addition. **WKT filter REMOVED from architecture per same discipline** (the filter added complexity for a non-problem).
- [[public-surface-draft-discipline-source-audit]] — `CompileResult.pool_file_names` INTERNAL classification with docstring caveat.
- [[plan-review-verify-prior-art-citations]] — corrects parent plan's L454 mis-step (R7 walks via `pool.FindFileByName(...)`, not `source_info_descriptors`).
- [[pre-1.0-version-bump-as-communication-contract]] — BUILTIN_PACKS registration deferred to U7 alongside 0.2.0 → 0.3.0 version bump.
- [[no-raise-contract-extends-to-post-init-failures]] — `pool_file_names` populated via `__post_init__` snapshot; failures emit diagnostics.
- [[semantic-category-conflation-accepted-tradeoff-literal-widening]] — applies in reverse for U5 (R9); R7 does not bump schema_version.
- **NEW LEARNING (to propose at U7 ce:compound; full text deferred there per ce:compound's authoring discipline):** **`empirical-evidence-before-arch-claims-on-foreign-system-shape`** — when a plan claims a foreign system (buf, protoc, prettier, another runtime, an HTTP API) behaves in shape X, verify shape X empirically before building atop it. The D6b U4 case (3 architectural corrections caught by 7 buf NDJSON snapshots after a planning-time wrong-assumption cost a /ce:work cycle) is the primary instance. Broader framing (per product-lens review) covers cross-runtime assumptions, descriptor-set vs proto-mode equivalence, and any cross-system shape claim — not just smoke-test-able CLI tools. Full learning text captured at U7's ce:compound.

### Review history

- **2026-05-17 deferred-question-resolution pass (4 user decisions + 7 new smoke fixtures):** Resolved the 4 deferred questions from the plan's document-review headless pass. **User decisions:** (1) Keep R7 severity at ERROR per existing brainstorm refinement decision + U7 CHANGELOG migration section (no change). (2) Add all 3 supplementary verifications: `mixed-value-with-inner-quote` smoke fixture + 6 `mixed-presence-{rule}` smoke fixtures + cross-runtime iteration-order verification (analyzed code-side per `_compile_with_protoxy`/`_compile_with_protoc`/U1's `test_compile_include_source_info.py:154-198` — deterministic-by-construction; U4a adds a parallel cross-backend byte-equivalence test). (3) Drop `test_buf_smoke_assumptions.py` snapshot-consistency mode; ship live-mode only + a SHA-256 checksum file pinning the 21 snapshots. (4) Add CHANGELOG-DRAFT.md note + `protokit lint --help` line at U4b documenting the `--rule-pack` opt-in mechanism for the dormancy window. **Empirical findings from 7 new smoke fixtures:** (a) **CRITICAL byte-parity finding:** buf escapes inner `"` characters as `\"` (literal backslash-quote) in message text per `recorded/mixed-value-with-inner-quote.json`; protokit helper now applies `value.replace('"', '\\"')` per declared value BEFORE composition. The `_safe_for_stderr` sanitizer does NOT do this; explicit escape step required. (b) Cross-rule mixed-PRESENCE template uniformity confirmed for all 6 non-go_package rules; bool `java_multiple_files` mixed-presence emits LOWERCASE `"true"` (consistent with mixed-value bool render). The 21 total recorded snapshots are the complete empirical foundation; no more architectural assumptions remain to extrapolate.

- **2026-05-17 supplementary smoke + user-decision pass:** "Yes to all deferred questions" — 7 new supplementary smoke fixtures created + run against buf v1.69.0 to resolve the deferred questions from the document-review pass. **3 architectural decisions empirically locked:** (1) Cross-rule homogeneity CONFIRMED for all 7 PACKAGE_SAME_* rules via `mixed-value-{java-package,csharp-namespace,php-namespace,ruby-package,swift-prefix,java-multiple-files}.json` — every rule emits the identical message template `'Files in package "{package}" have {payload} for option "{attr}" and all values must be equal.'`; (2) `values_csv` sort: LOCKED alphabetic-by-value per `reverse-order-go.json` (input `a→Y, b→X, c→Y` produces `"X,Y"`, decisively NOT filename-order); (3) Boolean `java_multiple_files` rendering: LOCKED LOWERCASE per `mixed-value-java-multiple-files.json` (buf emits `"false,true"` not `"False,True"`). Helper updated to use `str(value).lower()` for the bool attr. **3 Risks rows added** for empty-package contamination, transitive-import supply-chain, and WKT enforcement — all framed as accepted-tradeoffs per buf-parity with documented mitigation paths. **U7 CHANGELOG/README scope pre-specified** with 7 mandatory content elements (rule enumeration, N-not-N-1 quantification, empty-package aggregation explanation, transitive-import note, WKT note, severities snippets, --rule-pack opt-in pattern). The 14 total recorded snapshots are the empirical foundation; no more architectural assumptions remain to extrapolate.

- **2026-05-17 document-review pass (headless mode):** 6 personas (coherence + feasibility + product-lens + security-lens + scope-guardian + adversarial). 30 raw findings; 7 auto-fixes applied + 6 cross-persona convergences merged. Auto-fixes: (1) `values_csv` → `values_payload` rename throughout TL;DR + body (coherence P1); (2) `__post_init__` invariant mechanism specified explicitly as diagnostic-emission (NOT `assert`, which is stripped under `-O`, NOR `raise ValueError`, which violates the no-raise contract) per [[no-raise-contract-extends-to-post-init-failures]] (feasibility P1 + adversarial P2); (3) `_safe_for_stderr` applied PER-VALUE before composition (defends against multi-value injection edge case at truncation boundary) + 2 new adversarial fixtures (multi-value injection + truncation-boundary U+2028) (security P1); (4) `posixpath.basename` replaces `os.path.basename` in pre-walk sort key for cross-platform determinism (feasibility residual); (5) `test_buf_smoke_assumptions.py` redesigned as dual-mode — live re-invocation of buf when BUF_BINARY set + snapshot-consistency check when unset; converts tautological self-validation into real regression gate (feasibility + adversarial + scope-guardian 3-persona convergence); (6) SC 15 updated to reflect dual-mode design (cascading from #5); (7) NEW LEARNING block slimmed from 150-word draft to a one-line "to propose at U7 ce:compound" reference with broadened framing (`empirical-evidence-before-arch-claims-on-foreign-system-shape` per product-lens — covers more than smoke-test-able CLI tools) (scope-guardian P2 + product-lens P3).

- **2026-05-17 revision (this document):** triggered by `/ce:work` U0 preflight detecting Outcome C (material divergence) against the original 2026-05-15 brainstorm. 7 buf v1.69.0 smoke fixtures + recorded NDJSON snapshots committed to main (commits `68f4a93` for 6 initial fixtures + supplementary commit for wkt-conflict). Three architectural corrections baked in: (1) all-disagreers-fire semantics replaces lex-smallest canonical; (2) empty-package (`""`) enforcement replaces skip; (3) WKT filter at `google/protobuf/` dropped entirely. Engine plumbing (CompileResult.pool_file_names, FileLintContext.package_options, engine Step 3.5 pre-walk) unchanged from refinement-round-2 of the original brainstorm. 6 corrected Success Criteria (SC 5/6/8b + new SC 8d for WKT enforcement). 3 string params (`package`, `option_attr`, `values_payload`) replace the original 4 (`option_attr`, `value`, `canonical_value`, `canonical_file`). All decisions cite specific recorded NDJSON snapshots as evidence.

### Next step

`/ce:plan` to produce the revised per-unit plan at `docs/plans/2026-05-17-002-feat-d6b-u4-r7-package-same-revised-plan.md` (or update the existing 2026-05-17-001 plan in-place if cleaner). The revised plan preserves U4a's engine-plumbing scope (with the WKT filter step removed) and rewrites U4b's R7-rules section per this brainstorm's `_check_package_option` shape + all-disagreers-fire emit + 3-param sanitization. Then resume `/ce:work` against the revised plan, picking up where U0 left off (smoke fixtures already committed; remaining work is U4a engine code + U4b rules).
