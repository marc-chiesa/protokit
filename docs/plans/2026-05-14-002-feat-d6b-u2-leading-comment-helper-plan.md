---
title: "feat: D6b Unit 2 — leading_comment + descriptor_path helpers + 5 ElementKind context wiring + CompileResult consumer audit"
type: feat
status: active
date: 2026-05-14
origin: docs/plans/2026-05-14-001-feat-protokit-lint-d6b-option-aware-and-multi-language-plan.md
---

# feat: D6b Unit 2 — leading_comment + descriptor_path helpers + 5 ElementKind context wiring + CompileResult consumer audit

## Overview

D6b Unit 1 (commits `d6b6713` → `f33fb2a` → `9fe9404`) shipped the
opt-in `include_source_info` parameter, the 3-tuple backend return
shape, and the `CompileResult.source_info_descriptors` field that
preserves `FileDescriptorProto` instances before `pool.Add()`
discards their `source_code_info`. The mapping exists and is
populated when callers opt in — but no consumer reads it yet.

U2 closes the consumer side of the R6/R6a/R6b/R6c chain so that U3's
5 deprecated-replacement rules can land cleanly:

1. **5 ElementKind context fields** — `source_info_descriptors`
   added to `FieldLintContext`, `EnumValueLintContext`,
   `MethodLintContext`, `MessageLintContext`, and `EnumLintContext`
   (the 5 contexts R6's rule family will dispatch through). The
   3 sibling contexts (`FileLintContext`, `ServiceLintContext`,
   `OneofLintContext`) are intentionally NOT touched per YAGNI —
   no current or planned rule needs comment access through them.
2. **Engine wiring** — `LintEngine.run` threads
   `compile_result.source_info_descriptors` to the 5 builder
   methods via instance state (mirrors `_current_profile`
   precedent), so dispatch helpers and the 3 untouched builders
   are unchanged.
3. **Two helpers in `_comments.py`** —
   `descriptor_path(descriptor) -> tuple[int, ...]` (the
   descriptor-to-source_code_info path encoder, dispatching across
   the 5 ElementKinds) and `leading_comment(source_info_descriptors,
   file_name, path) -> str | None` (the leaf lookup that walks
   `source_code_info.location[]`). Both module-level free functions
   in `src/protokit/schema/lint/rules/options/_comments.py`.
4. **CompileResult consumer audit** — enumerate all 7 production +
   6 test instantiation sites, confirm each path either passes the
   correct value or harmlessly accepts the `None` default.

After U2, R6's rules in U3 can call:

```python
path = descriptor_path(ctx.field)  # or ctx.method, ctx.message, etc.
comment = leading_comment(ctx.source_info_descriptors, ctx.file.name, path)
```

end-to-end with real data, and the lint CLI wire-up in U3 (passing
`include_source_info=True`) flips the entire R6 family on.

## Problem Frame

R6a (U1) preserves comment data on `CompileResult`. R6 (U3) needs to
read comment data inside rule bodies. R6b (this unit) is the bridge.

The brainstorm's original framing assumed contexts "already reference
`compile_result`" so a free function could read directly from the
context. Parent plan KTD-2 verified that claim was wrong: contexts
have `file`, `pool`, `profile`, plus three engine-injected fields,
but no `compile_result`. The resolution: add the field DIRECTLY to
the contexts that need it.

**Which contexts need it?** R6's 5 deprecated-replacement rules
dispatch one per `*Options.deprecated` ElementKind, per the
brainstorm's R6 rule table and the parent plan's U3 section:

| Rule | ElementKind | LintContext |
|---|---|---|
| `deprecated-field-must-have-replacement-comment` | FIELD | `FieldLintContext` |
| `deprecated-enum-value-must-have-replacement-comment` | ENUM_VALUE | `EnumValueLintContext` |
| `deprecated-method-must-have-replacement-comment` | METHOD | `MethodLintContext` |
| `deprecated-message-must-have-replacement-comment` | MESSAGE | `MessageLintContext` |
| `deprecated-enum-must-have-replacement-comment` | ENUM | `EnumLintContext` |

U2 wires those 5 contexts (not `FileLintContext`, which was the
initial-draft mistake caught at the document-review pass on
2026-05-15). The 3 untouched contexts (`FileLintContext`,
`ServiceLintContext`, `OneofLintContext`) stay clean — D6c+
deliveries that need comment access in those scopes can extend
the pattern then.

**Why two helpers in `_comments.py`?** `source_code_info.location[i].path`
is a `tuple[int, ...]` of descriptor-graph coordinates (e.g.,
`[4, msg_idx, 2, field_idx]` for "field N of message M"). The
coordinates come from `descriptor.proto`'s wire-tag numbers
(4 = `message_type`, 5 = `enum_type`, 6 = `service`, 2 = field /
method / value / enum_value, 3 = `nested_type`). Computing the
path requires walking the descriptor's `containing_type` chain.

This is **descriptor introspection**, distinct from **comment lookup**.
Splitting into two helpers (`descriptor_path` + `leading_comment`)
keeps each function policy-free and independently unit-testable.
Co-locating in `_comments.py` keeps the U3 callers' import surface
single-line.

**The audit deliverable** matters because U1's rename
(`source_locations` → `source_info_descriptors`) means the parent
plan's "5 CompileResult instantiation sites" enumeration is now
known to be incomplete — there are 7 production sites and 6 test
sites. The audit closes a known gap rather than rediscovering it
mid-implementation.

## Supersedes parent plan U2 section in these specifics

The parent plan's U2 section (lines 334-379 of
`docs/plans/2026-05-14-001-feat-protokit-lint-d6b-option-aware-and-multi-language-plan.md`)
was written before U1 shipped and before the document-review pass
on this per-unit plan surfaced two structural design errors. This
per-unit plan supersedes the parent on:

- **CompileResult field + `__post_init__` snapshot.** Parent plan
  lines 343-344 list these as U2 work. U1 absorbed them (commit
  `d6b6713` shipped the field; commit `f33fb2a` shipped the
  no-raise-contract `__post_init__` wrapper). U2's `compile.py`
  modifications are now zero.
- **Number of LintContext fields.** Parent plan KTD-2 says
  "single new field on `FileLintContext`." Per-unit document-review
  surfaced that R6 dispatches as FIELD / ENUM_VALUE / METHOD /
  MESSAGE / ENUM — so the field must land on those 5 contexts,
  not `FileLintContext`.
- **Engine wiring mechanism.** Parent plan line 346 says
  "`_build_file_ctx` — passes `source_info_descriptors=compile_result.source_info_descriptors`"
  (parameter-threading at construction time). Per-unit K-1 uses
  the established engine-instance-state pattern instead, set
  immediately after the reentrancy guard in `run()` and cleared
  in `finally` — mirrors `_current_profile`.
- **Helper count.** Parent plan describes one helper
  (`leading_comment`). Per-unit ships two (`descriptor_path` +
  `leading_comment`) because the path computation is its own
  concern, independently testable and reusable.
- **Test file naming.** Parent plan line 352 names
  `tests/schema/test_compile_result_source_info_descriptors.py`.
  Per-unit creates `tests/schema/lint/test_engine_source_info_descriptors_injection.py`
  (engine integration) and `tests/schema/lint/rules/options/test_comments.py`
  (helper unit tests). The parent-named file is not created — its
  scope (CompileResult field correctness) was already covered by
  U1's `tests/schema/lint/test_compile_include_source_info.py`.

The parent plan's delivery-level structure (R6b's overall scope,
the U1 → U2 → U3 sequencing, the D6b boundary unit) remains the
canonical reference for understanding D6b as a whole.

## Requirements Trace

- **R6b.** `CompileResult.source_info_descriptors: Mapping[str, FileDescriptorProto] | None` field already exists (shipped in U1). U2 adds `source_info_descriptors` fields to the 5 R6 ElementKind contexts, the engine wiring that injects them, and the `descriptor_path` + `leading_comment` helpers that consume them.
- **R12 (partial).** Public Surface DRAFT additions for
  `{Field,EnumValue,Method,Message,Enum}LintContext.source_info_descriptors` (INTERNAL),
  `descriptor_path` (IN once R6 rules land in U3), and
  `leading_comment` (IN once R6 rules land in U3). Actual README row
  additions land at the D6b delivery boundary (U7) per the
  established convention — U2 lands the code; U7 lands the
  public-surface communication.
- **A1 (carry-over).** Cold-import contract holds — `import protokit.schema` must NOT transitively load `protokit.schema.lint.rules.options`. The new module sits under `protokit.schema.lint.rules.options.*`, which is already a lazy-load subtree per the existing rule-pack discipline.

## Scope Boundaries

- **U2 does NOT wire the lint CLI to pass `include_source_info=True`.** That's U3's deliverable (`src/protokit/schema/lint/cli.py:731`).
- **U2 does NOT ship any R6 rule.** The 5 deprecated-replacement rules are U3's deliverable.
- **U2 does NOT add `source_info_descriptors` to `FileLintContext`, `ServiceLintContext`, or `OneofLintContext`.** No current or planned rule reads comments through those contexts. Future deliveries may extend if needed.
- **U2 does NOT touch the `_safe_for_stderr` sanitizer.** R6c (U3) calls the existing sanitizer inline at finding-construction time; U2 ships no sanitization code.
- **U2 does NOT introduce `_safe_for_findings` as a new module.** Brainstorm 2026-05-14 document-review pass resolved this — inline reuse only.
- **U2 does NOT tune the `leading_comment` matcher regex set.** U3's `_check_replacement_comment` does the regex matching; the regex set is finalized in U3 against a fixture corpus.

### Deferred to Separate Tasks

- **Cross-protobuf-runtime byte-equivalence test** (proto 4 vs proto 5 `source_code_info.location[]`). Promised at parent plan lines 145, 308; not shipped in U1's regression suite. Deferred to U6 (parity test infrastructure) where the test-matrix infrastructure already exists.
- **Cross-backend equivalence golden** (a checked-in `FileDescriptorSet` so single-backend CI runs can verify against a known-good snapshot). Same deferral target as above.
- **`LintRuntimeWarning` for comment-aware rules running with `source_info_descriptors=None`.** Programmatic callers who run R6 rules without passing `include_source_info=True` will get false-positive findings (per K-6's accepted tradeoff). Adding a runtime warning to surface this would require a new `LintRuntimeWarning.category` Literal value, which is a wire-format change scoped to U5 (`severities_unloaded_rule` split + `schema_version` 0.2 → 0.3 bump). Defer to U5 or D6c; revisit if real-world false-positive friction emerges.

## Context & Research

### Relevant code and patterns

- **`src/protokit/schema/lint/model.py`** — 5 of 8 LintContext dataclasses gain `source_info_descriptors`:
  - `FieldLintContext` (around line 1150)
  - `EnumValueLintContext` (around line 1086)
  - `MethodLintContext` (around line 1021)
  - `MessageLintContext` (around line 1119)
  - `EnumLintContext` (around line 1055)
  Each is a `@dataclass(frozen=True)` inheriting from `_LintContextEmitMixin`. Existing field order convention: public fields (`field` / `enum_value` / `method` / `message` / `enum`, plus `file`, `pool`, `profile`) first, then underscore-prefixed engine-private fields (`_emit_fn`, `_rule_id`, `_effective_severity`). New `source_info_descriptors` is public-named (no underscore) so it goes between the last public field and the first underscore-prefixed field. Pure attribute on a frozen dataclass; no `__post_init__` work needed.
- **`src/protokit/schema/lint/model.py:878-955`** — `_LintContextEmitMixin` is **deliberately NOT a dataclass** and carries NO field annotations. The mixin's docstring (lines 903-908) documents the pass-2 codex correction that established this: declaring fields on the mixin would force dataclass field-ordering and conflict with the "engine-injected fields LAST on each concrete subclass" rule. The U2 design respects that rule by placing the new field on each concrete subclass directly.
- **`src/protokit/schema/lint/engine.py`** — 5 builder methods updated to thread `source_info_descriptors`:
  - `_build_field_ctx` (line 713)
  - `_build_enum_value_ctx` (line 677)
  - `_build_method_ctx` (line 641)
  - `_build_message_ctx` (line 696)
  - `_build_enum_ctx` (line 660)
  The 3 unmodified builders (`_build_file_ctx` line 609, `_build_service_ctx` line 624, `_build_oneof_ctx` line 732) construct their corresponding untouched contexts without the field.
- **`src/protokit/schema/lint/engine.py:261-414`** — `LintEngine.run`. Sets `_current_profile` on `self` at entry (around line 329, after the reentrancy guard at line 315); clears in `finally` (line 414). Same lifecycle for `_current_source_info_descriptors`.
- **`src/protokit/schema/lint/engine.py:118-125`** — `LintEngine.__init__`. Initializes `_current_profile = None`. Same init for `_current_source_info_descriptors`.
- **`src/protokit/schema/lint/rules/options/`** — directory does NOT exist yet. Current rule layout under `src/protokit/schema/lint/rules/` is FLAT modules (`enum.py`, `file.py`, `imports.py`, `naming.py`, `package.py`), NOT subdirectory packages — `options/` will be the first subdirectory under `rules/`. The structural deviation is intentional: U3 will land 5 R6 rules + their shared `_check_replacement_comment` helper alongside `_comments.py`, so the directory pays for itself.
- **`tests/schema/lint/rules/`** — sibling test packages mirror the source layout. U2 creates `tests/schema/lint/rules/options/__init__.py` + `tests/schema/lint/rules/options/test_comments.py`.
- **`tests/schema/lint/test_compile_include_source_info.py`** (shipped U1) — the test pattern to mirror for U2's helper tests. Uses inline `.proto` fixtures + real backend compilation, not mocks. The `_PROTO_WITH_COMMENTS` constant (around line 55) is reusable.

### Institutional learnings

- **[[frozen-dataclass-mutable-fields-need-post-init-snapshot]]** — the 5 new `source_info_descriptors` fields are `Mapping` fields on frozen dataclasses. The mapping was ALREADY wrapped in `MappingProxyType` by `CompileResult.__post_init__` at U1, so passing the same reference through the engine into the 5 contexts requires NO additional snapshot at the context layer. The frozen guarantee is preserved by the upstream wrap.
- **[[no-raise-contract-extends-to-post-init-failures]]** — none of the 5 contexts' `__post_init__` (if any — they're plain frozen dataclasses without custom `__post_init__`) does work that can raise on the new field. The field is just stored. No risk of the U1-style escape gap.
- **[[circular-import-type-checking-cycle-break]]** — annotation for `Mapping[str, FileDescriptorProto] | None` on the 5 contexts. `model.py` imports `google.protobuf.descriptor` and `google.protobuf.descriptor_pool` at runtime but NOT `descriptor_pb2`. Use TYPE_CHECKING guard (same pattern as `compile.py:43-44`) so the new annotation doesn't pull in `descriptor_pb2` and its ~8 additional protobuf modules.
- **[[matcher-backend-path-resolution-skew-silently-empties-output]]** — `leading_comment` receives `ctx.file.name` as the key into `source_info_descriptors`. Backends emit `fd.name` as the literal POSIX-separator path the user passed, NOT a resolved/absolute path. Use the literal `ctx.file.name` directly — no `Path.resolve()`, no normalization.
- **[[pytestmark-does-not-guard-module-top-imports]]** — `tests/schema/lint/rules/options/test_comments.py` doesn't depend on protoxy (`leading_comment` and `descriptor_path` are pure Python operating on already-built descriptors). No `pytest.importorskip` needed in this test file.
- **[[ce-review-cross-reviewer-agreement-shared-misreading-false-positive-amplifier]]** — written from the same D6b U1 session as the source for this plan. The plan-vs-docstring discipline applies to U2 too: any present-tense reference to U3's CLI wire-up in U2's docstrings should be qualified ("will be set in U3", not "is set").

### External references

None — this is internal Python plumbing; no external library decisions or industry research relevant. The `source_code_info.Location.path` encoding (4 = `message_type`, 5 = `enum_type`, 6 = `service`, 2 = field/method/value/enum_value, 3 = `nested_type`) comes from the [protobuf `descriptor.proto`](https://github.com/protocolbuffers/protobuf/blob/main/src/google/protobuf/descriptor.proto) wire-tag numbers — a stable contract across protobuf 4 and 5.

## Key Technical Decisions

- **K-1: Engine instance state, not parameter threading.** Store
  `source_info_descriptors` on `LintEngine` as
  `self._current_source_info_descriptors`. Initialize in `__init__`
  to `None`. Set IMMEDIATELY AFTER the reentrancy guard check at
  `engine.py:315` and following `self._current_profile`, so the
  existing guard catches reentrant `run()` calls before the new
  field can be corrupted. Clear in the `finally` block alongside
  `_current_profile`. The 5 builder methods read
  `self._current_source_info_descriptors` and pass it to their
  corresponding context constructors. Rationale: mirrors the
  existing `_current_profile` pattern; parameter-threading through
  `_dispatch_*` helpers would touch every dispatch site for marginal
  benefit. The set-after-guard ordering is load-bearing for
  reentrancy safety; do not refactor the prologue to set the new
  field above the guard check.

- **K-2: Field added to the 5 R6 ElementKind contexts (FIELD,
  ENUM_VALUE, METHOD, MESSAGE, ENUM).** Each context gets one new
  field: `source_info_descriptors: Mapping[str, descriptor_pb2.FileDescriptorProto] | None`,
  placed AFTER the last public field (`field` / `method` / etc.,
  plus `file`, `pool`, `profile`) and BEFORE the first
  underscore-prefixed engine-private field (`_emit_fn`, `_rule_id`,
  `_effective_severity`). Preserves the documented
  "engine-injected fields LAST on each concrete subclass" rule
  from the pass-2 codex correction (`model.py:903-908`).
  `FileLintContext`, `ServiceLintContext`, and `OneofLintContext`
  are deliberately NOT touched — no current or planned rule needs
  comment access through them, and extending the pattern is
  cheap if future need arises.

- **K-3: TYPE_CHECKING-gated `FileDescriptorProto` import in model.py.**
  `model.py` imports `google.protobuf.descriptor` and
  `google.protobuf.descriptor_pool` at runtime but NOT `descriptor_pb2`.
  The annotation is only needed for static type analysis — actual
  `FileDescriptorProto` instances flow through the system as values
  from already-imported callers, so runtime import of `descriptor_pb2`
  is unnecessary. Adding it would also pull in ~8 additional protobuf
  modules (`internal.builder`, `message_factory`, `pyext`, etc.)
  whose load cost is paid on every process that imports model.py.
  (Note: this is a module-weight argument, NOT a cold-import-contract
  argument — the cold-import contract is about `import protokit.schema`
  not loading the `protokit.schema.lint` package, a different boundary
  than the protobuf-internal one.) Mirror `compile.py:43-44`:
  `if TYPE_CHECKING: from google.protobuf.descriptor_pb2 import
  FileDescriptorProto`. Annotation is a string under
  `from __future__ import annotations`.

- **K-4: `leading_comment` strips whitespace; returns `str | None`.**
  Implementation:
  ```python
  text = loc.leading_comments.strip()
  return text if text else None
  ```
  Returns `None` when ANY of: `source_info_descriptors is None`,
  `file_name` not in the mapping, no `Location` matches `path`,
  the matched `Location`'s `leading_comments` is empty, OR the
  `leading_comments` is whitespace-only after stripping. Returns
  the stripped text for any non-whitespace content. **Preserves
  internal newlines and indentation** within multi-line comment
  bodies — `.strip()` only removes leading and trailing whitespace,
  not internal whitespace.
  **Contract pin:** the helper's docstring MUST state explicitly
  that the return value is UNSANITIZED (control characters, U+2028,
  etc., are preserved) and that callers emitting it into wire-format
  output (findings, JSON, SARIF) must run it through
  `_safe_for_stderr` (or equivalent) first. The `.strip()` normalization
  is a separate concern from sanitization — `strip` handles formatting
  whitespace; `_safe_for_stderr` handles adversarial control chars.

- **K-5: Two helpers in `_comments.py` — `descriptor_path` and
  `leading_comment`.** The pure-data lookup
  (`leading_comment(source_info_descriptors, file_name, path)`)
  is separated from the descriptor introspection
  (`descriptor_path(descriptor)`). Both are module-level free
  functions with no shared state.

  `descriptor_path` accepts any of the 5 R6 descriptor types
  (`FieldDescriptor`, `EnumValueDescriptor`, `MethodDescriptor`,
  `Descriptor` for message, `EnumDescriptor`) and returns the
  `tuple[int, ...]` path used by `source_code_info.Location.path`.
  The recipe is recursive over the descriptor's parent chain:

  | Descriptor type | Path recipe |
  |---|---|
  | `Descriptor` (top-level message) | `(4, msg_index_in_file)` |
  | `Descriptor` (nested message) | `parent_msg_path + (3, nested_index)` |
  | `FieldDescriptor` | `containing_msg_path + (2, field_index_in_msg)` |
  | `EnumDescriptor` (file-level) | `(5, enum_index_in_file)` |
  | `EnumDescriptor` (nested) | `parent_msg_path + (4, enum_index_in_parent)` |
  | `EnumValueDescriptor` | `enum_path + (2, value_index_in_enum)` |
  | `MethodDescriptor` | `(6, service_index, 2, method_index)` |

  The `4`/`5`/`6` numbers are wire-tag indices from `descriptor.proto`'s
  `FileDescriptorProto` message (`message_type` = 4, `enum_type` = 5,
  `service` = 6); the `2`/`3` numbers are the corresponding
  field/value/method/nested tags inside their containers. These are
  stable contract across protobuf 4 and 5.

  `leading_comment` does a literal-tuple lookup:
  `tuple(loc.path) == path`. No fuzzy matching, no prefix matching.
  If the caller passes the wrong path, the helper returns `None`
  and the rule emits without a comment-derived param. Caller-side
  responsibility to pass the right path — which is now bounded
  because the caller computes via `descriptor_path`, not by hand.

- **K-6: `source_info_descriptors` defaults to `None` everywhere;
  programmatic-caller false-positive tradeoff documented.**
  `FieldLintContext(source_info_descriptors=None)` (and the same
  for the other 4 R6 contexts) is the legitimate state for any
  `LintEngine.run()` invocation where the caller didn't pass
  `include_source_info=True` into `compile_protos_to_result`.
  Today (pre-U3 CLI wiring) ALL invocations are this state.
  `leading_comment(None, ...)` returns `None` defensively.
  **R6 rules in U3 will treat `None` return as "no comment found"
  and emit findings accordingly per the brainstorm + parent-plan
  acceptance.** This means programmatic callers who run R6 rules
  with their own `CompileResult` (built without `include_source_info=True`)
  get false-positive findings — the rules fire as if every deprecated
  element lacks a replacement comment, when in fact the rule has no
  comment data at all.

  This tradeoff is accepted per the brainstorm (line 178) and
  parent plan U3 test scenarios (line 418). The rationale: emitting
  findings is conservative — the user can suppress via
  `[tool.protokit.lint.severities]` overrides. A `LintRuntimeWarning`
  that surfaces the data-absent mode would be the cleanest signal
  but requires a new `LintRuntimeWarning.category` Literal value
  (wire-format change scoped to U5). Deferred to U5 or D6c —
  see "Deferred to Separate Tasks" above.

  **Documentation requirement:** the 5 contexts' field docstring
  and `leading_comment`'s docstring MUST state explicitly that
  `None` is the legitimate "caller didn't opt in" state, and that
  comment-aware lint rules will fire findings in this state per
  the accepted tradeoff. Programmatic callers wanting accurate
  R6 results must pass `include_source_info=True` to
  `compile_protos_to_result`.

## Open Questions

### Resolved during planning

- **Q1: Which LintContext dataclasses get `source_info_descriptors`?**
  **Resolved: 5 of 8.** `FieldLintContext`, `EnumValueLintContext`,
  `MethodLintContext`, `MessageLintContext`, `EnumLintContext` —
  matching R6's actual rule dispatch surface. `FileLintContext`,
  `ServiceLintContext`, `OneofLintContext` are not touched.
- **Q2: Should the engine pass `source_info_descriptors` as a positional parameter through `_dispatch_*` helpers, or via instance state?**
  **Resolved: Instance state** (K-1 above).
- **Q3: Do the 5 contexts need their own `__post_init__` for the new mapping field?**
  **Resolved: No.** The mapping was wrapped in `MappingProxyType` at the `CompileResult` layer in U1. Passing the same reference through the engine preserves immutability — no defensive re-wrap needed.
- **Q4: What's the correct annotation strategy for `FileDescriptorProto` in `model.py`?**
  **Resolved: TYPE_CHECKING guard** (K-3 above).
- **Q5: Does U2 need to update the test helpers that construct `CompileResult` directly?**
  **Resolved: No.** Tests pass `source_info_descriptors=None` implicitly via the field default. The audit deliverable documents this; no test edits are required.
- **Q6: Should `_comments.py` ship one helper or two?**
  **Resolved: Two** (K-5 above). `descriptor_path` is descriptor introspection; `leading_comment` is mapping lookup. Co-located; independently testable.
- **Q7: How should `leading_comment` handle empty vs whitespace-only `leading_comments`?**
  **Resolved: `.strip()` then `or None`.** Both empty and whitespace-only return `None`. Internal whitespace within real comments is preserved.
- **Q8: Should U2 emit a `LintRuntimeWarning` when comment-aware rules run with `source_info_descriptors=None`?**
  **Resolved: Defer.** Wire-format change scoped to U5; revisit if false-positive friction emerges.

### Deferred to implementation

- **Q9: What are the exact line-number anchors for inserting `source_info_descriptors` into each of the 5 contexts?**
  Resolved at edit time. Plan-time anchor: insert after the last public field and before the first underscore-prefixed engine-private field in each context dataclass.
- **Q10: How does `descriptor_path` get the index of a top-level message in its file?**
  Resolved at edit time. Python protobuf descriptor API exposes `Descriptor.index` for nested types; top-level types likely require walking `file.message_types_by_name` or `file.message_type` (the underlying `FileDescriptorProto.message_type` repeated field). Verify the available attribute names against the protobuf 4 + 5 runtime API during implementation; the implementation may need a small helper to get the file-level index across both runtimes.

## High-Level Technical Design

> *This illustrates the intended approach and is directional guidance for review, not implementation specification.*

Data flow at U2 (no rule yet — that's U3):

```
compile_protos_to_result(paths, include_source_info=True)
  └─ returns CompileResult(source_info_descriptors=MappingProxyType({...}))

LintEngine.run(compile_result, profile=...)
  ├─ self._current_source_info_descriptors = compile_result.source_info_descriptors  [NEW]
  ├─ walk root_files:
  │    ├─ fd = pool.FindFileByName(fname)
  │    └─ _dispatch_file(fd, ...)
  │         ├─ for each MESSAGE-element spec:
  │         │    ├─ ctx = _build_message_ctx(...)                     [PARENT CALLER]
  │         │    │    └─ MessageLintContext(
  │         │    │         message=m,
  │         │    │         file=fd,
  │         │    │         pool=fd.pool,
  │         │    │         profile=profile.name,
  │         │    │         source_info_descriptors=self._current_source_info_descriptors,  [NEW]
  │         │    │         _emit_fn=...,
  │         │    │         _rule_id=...,
  │         │    │         _effective_severity=...,
  │         │    │       )
  │         │    └─ rule_body(ctx)
  │         │         └─ # U3 will add:
  │         │         └─ path = descriptor_path(ctx.message)
  │         │         └─ comment = leading_comment(
  │         │              ctx.source_info_descriptors,
  │         │              ctx.file.name,
  │         │              path,
  │         │            )
  │         └─ (analogous for FIELD / ENUM / ENUM_VALUE / METHOD specs
  │             via _build_field_ctx / _build_enum_ctx /
  │             _build_enum_value_ctx / _build_method_ctx)
  └─ finally:
       └─ self._current_source_info_descriptors = None              [NEW]


Helper signatures (both module-level free functions in
src/protokit/schema/lint/rules/options/_comments.py):

  def descriptor_path(descriptor) -> tuple[int, ...]:
      """Compute source_code_info.Location.path coordinates for the
      given descriptor by walking its parent chain.
      """
      # Dispatch on descriptor type:
      #   FieldDescriptor → containing_msg_path + (2, index_in_msg)
      #   EnumValueDescriptor → enum_path + (2, index_in_enum)
      #   MethodDescriptor → (6, service_index, 2, method_index)
      #   Descriptor (message): (4, file_index) or parent_msg_path + (3, nested_index)
      #   EnumDescriptor: (5, file_index) or parent_msg_path + (4, nested_index)
      ...

  def leading_comment(
      source_info_descriptors: Mapping[str, FileDescriptorProto] | None,
      file_name: str,
      path: tuple[int, ...],
  ) -> str | None:
      """Look up the leading comment for the given descriptor path.

      Returns the stripped leading_comments string, or None when:
      source_info_descriptors is None, file_name not in mapping,
      no Location matches path, or the matched leading_comments
      is empty/whitespace-only after .strip().
      """
      if source_info_descriptors is None:
          return None
      fd_proto = source_info_descriptors.get(file_name)
      if fd_proto is None:
          return None
      for loc in fd_proto.source_code_info.location:
          if tuple(loc.path) == path:
              text = loc.leading_comments.strip()
              return text if text else None
      return None
```

## Implementation Units

- [ ] **Unit 2: R6b — `descriptor_path` + `leading_comment` helpers + 5 ElementKind context wiring + CompileResult consumer audit**

**Goal:** Land the consumer-side plumbing for R6a/R6b: 5 context-field additions, engine instance-state wiring to 5 builder methods, the `descriptor_path` + `leading_comment` free functions in `_comments.py`, and a documented audit of all existing CompileResult instantiation sites.

**Requirements:** R6b (partial), R12 (partial — public-surface code only; README rows deferred to U7).

**Dependencies:** Unit 1 (R6a — `CompileResult.source_info_descriptors` shipped in commits `d6b6713` / `f33fb2a`).

**Files:**

- Modify: `src/protokit/schema/lint/model.py` — add `source_info_descriptors: Mapping[str, descriptor_pb2.FileDescriptorProto] | None` field to each of:
  - `FieldLintContext`
  - `EnumValueLintContext`
  - `MethodLintContext`
  - `MessageLintContext`
  - `EnumLintContext`
  Add TYPE_CHECKING-guarded import for `FileDescriptorProto`. Update each class's `Attributes:` docstring section.
- Modify: `src/protokit/schema/lint/engine.py`:
  - Add `self._current_source_info_descriptors: Mapping[str, descriptor_pb2.FileDescriptorProto] | None = None` to `__init__` (alongside `_current_profile`).
  - Set `self._current_source_info_descriptors = compile_result.source_info_descriptors` immediately after the reentrancy guard check (around line 315) in `run()`.
  - Clear to `None` in the existing `finally` block (around line 414) alongside `self._current_profile = None`.
  - Modify each of the 5 builders to pass `source_info_descriptors=self._current_source_info_descriptors`:
    - `_build_field_ctx` (line 713)
    - `_build_enum_value_ctx` (line 677)
    - `_build_method_ctx` (line 641)
    - `_build_message_ctx` (line 696)
    - `_build_enum_ctx` (line 660)
  - The 3 unmodified builders (`_build_file_ctx`, `_build_service_ctx`, `_build_oneof_ctx`) are deliberately untouched.
  - Add the TYPE_CHECKING import for `FileDescriptorProto`.
- Create: `src/protokit/schema/lint/rules/options/__init__.py` — empty package marker.
- Create: `src/protokit/schema/lint/rules/options/_comments.py` — module-level `descriptor_path(descriptor) -> tuple[int, ...]` and `leading_comment(source_info_descriptors, file_name, path) -> str | None`. Pure Python; TYPE_CHECKING import for `FileDescriptorProto`.
- (No edit to `tests/test_static_analysis.py` needed — `_LINT_PATHS` already includes `src/protokit/schema/lint`, which covers the new `rules/options/` subdirectory recursively. Confirmed during feasibility review.)
- Test (NEW): `tests/schema/lint/rules/options/__init__.py` — empty test package marker.
- Test (NEW): `tests/schema/lint/rules/options/test_comments.py` — unit tests for BOTH helpers: `descriptor_path` (5 ElementKind scenarios + nested cases) and `leading_comment` (None-handling, key-miss, path-miss, happy path, empty/whitespace normalization, internal-whitespace preservation, adversarial control chars).
- Test (NEW): `tests/schema/lint/test_engine_source_info_descriptors_injection.py` — engine integration tests verifying that the 5 R6 contexts all receive `source_info_descriptors` correctly end-to-end when `compile_protos_to_result(..., include_source_info=True)` is run through `LintEngine.run`. Uses stub rules (one per ElementKind) that capture `ctx.source_info_descriptors` for inspection.

**Approach (3-phase, intended as ONE commit but logically sequenced):**

1. **Audit phase (no code changes, documented in commit message).**
   Enumerate every `CompileResult(...)` construction in the repo:
   - Production sites (already pass `source_info_descriptors=None` implicitly or via early-return paths after U1):
     - `src/protokit/schema/compile.py` — 6 sites (collision early-return; root-transitive-shadow early-return; empty-paths early-return; ImportError early-return; main success path; pool-is-None forced-reset; post_init-exception rebuild). All correctly handled after U1.
     - `src/protokit/schema/lint/_cli_utils.py:399` — `merge_descriptor_sets`. Construct passes `pool` + `root_files` + `diagnostics` only; `source_info_descriptors` defaults to `None`. Correct semantics — pre-compiled `.descriptor_set` files don't carry source_code_info, and the merge path doesn't opt-in.
   - Test sites (all use keyword args; backward-compatible):
     - `tests/schema/lint/test_engine.py:264` and `:975`
     - `tests/schema/lint/test_engine_warning_content_safety.py:59`
     - `tests/schema/lint/cli/test_cli_input_modes.py:434`
     - `tests/schema/lint/rules/test_package.py:304`
     - `tests/schema/lint/rules/test_file.py:177`
   - **Audit conclusion:** No callers need code changes. All paths accept the `None` default; only `compile_protos_to_result` populates the field when `include_source_info=True`. Document this conclusion in the U2 commit message body.

2. **Context fields + engine wiring phase.**
   - Add the TYPE_CHECKING import to `model.py`.
   - Add `source_info_descriptors` field to each of the 5 R6 contexts (`FieldLintContext`, `EnumValueLintContext`, `MethodLintContext`, `MessageLintContext`, `EnumLintContext`), placed between the last public field and the first underscore-prefixed engine-private field per K-2.
   - Update each of the 5 class docstrings' `Attributes:` section to document the new field — qualify any reference to "U3 R6 rules use this" with future tense per the forward-looking-text discipline. Note the legitimate-None state per K-6.
   - Add `self._current_source_info_descriptors = None` to `LintEngine.__init__`.
   - Set `self._current_source_info_descriptors = compile_result.source_info_descriptors` AFTER the reentrancy guard in `run()`. Clear to `None` in the existing `finally` block.
   - Modify each of the 5 builders (`_build_field_ctx`, `_build_enum_value_ctx`, `_build_method_ctx`, `_build_message_ctx`, `_build_enum_ctx`) to pass `source_info_descriptors=self._current_source_info_descriptors` into the corresponding context constructor.
   - The 3 unmodified builders (`_build_file_ctx`, `_build_service_ctx`, `_build_oneof_ctx`) are deliberately untouched.

3. **Helper module + tests phase.**
   - Create `src/protokit/schema/lint/rules/options/__init__.py` (empty).
   - Create `src/protokit/schema/lint/rules/options/_comments.py` with TWO module-level free functions:
     - `descriptor_path(descriptor) -> tuple[int, ...]` — dispatches on descriptor type per the K-5 recipe; walks parent chain for nested cases.
     - `leading_comment(source_info_descriptors, file_name, path) -> str | None` — literal-tuple match against `tuple(loc.path) == path`; `.strip()`-then-`or None` normalization.
   - Use `from __future__ import annotations`. TYPE_CHECKING import for `FileDescriptorProto`. Type-annotate `path` as `tuple[int, ...]`.
   - (No edit to `tests/test_static_analysis.py` needed — the existing `src/protokit/schema/lint` entry in `_LINT_PATHS` covers the new subdirectory.)
   - Create `tests/schema/lint/rules/options/__init__.py` (empty).
   - Create `tests/schema/lint/rules/options/test_comments.py` with the helper unit tests (see Test scenarios below).
   - Create `tests/schema/lint/test_engine_source_info_descriptors_injection.py` with the engine integration tests (see Test scenarios).

**Execution note:** Test-first for both helpers in `_comments.py`. They're pure Python with deterministic input/output and no environment dependencies — perfect for TDD. Write the test file first, watch it fail with `ImportError`, then land the helpers. The 5 context-field additions + 5 builder updates can land after the helpers are green since they have no dependency on context plumbing. The engine integration tests are the cross-layer correctness check that ties everything together — write those LAST.

**Patterns to follow:**
- `LintEngine._current_profile` lifecycle at `engine.py:118-125` (init), `engine.py:~329` (set in run after reentrancy guard), `engine.py:414` (clear in finally) — the canonical instance-state pattern.
- `compile.py:43-44` — TYPE_CHECKING-guarded `FileDescriptorProto` import + `from __future__ import annotations` for runtime annotations as strings.
- `tests/schema/lint/test_compile_include_source_info.py:55` — inline `_PROTO_WITH_COMMENTS` fixture pattern; reuse for the engine integration tests.
- Existing 5 context-builder methods (`_build_field_ctx`, etc.) — mirror their kwarg-style construction; add the new kwarg in alphabetical/conventional position.

**Test scenarios:**

For `tests/schema/lint/rules/options/test_comments.py` (helper unit tests):

`descriptor_path` scenarios:

- *FIELD (top-level message):* `descriptor_path(field_in_top_level_msg)` returns `(4, msg_index, 2, field_index)`.
- *FIELD (nested message):* `descriptor_path(field_in_nested_msg)` returns the full path walking up through the parent's index, e.g., `(4, outer_msg_idx, 3, nested_idx, 2, field_idx)`.
- *METHOD:* `descriptor_path(method_in_service)` returns `(6, service_index, 2, method_index)`.
- *MESSAGE (top-level):* `descriptor_path(top_level_message)` returns `(4, msg_index)`.
- *MESSAGE (nested):* `descriptor_path(nested_message)` returns `parent_path + (3, nested_index)`.
- *ENUM (file-level):* `descriptor_path(file_level_enum)` returns `(5, enum_index)`.
- *ENUM (nested):* `descriptor_path(nested_enum)` returns `parent_path + (4, enum_index)`.
- *ENUM_VALUE:* `descriptor_path(enum_value_in_file_level_enum)` returns `(5, enum_index, 2, value_index)`.
- *ENUM_VALUE (nested enum):* `descriptor_path(value_in_nested_enum)` returns the full path including the parent message.
- *Determinism:* Two consecutive calls with the same descriptor return identical paths.

`leading_comment` scenarios:

- *Happy path:* `leading_comment(source_info_descriptors, "demo.proto", (4, 0, 2, 0))` returns the leading comment string when the descriptor has a Location with `path=[4, 0, 2, 0]` and a non-empty `leading_comments`.
- *Edge case (None mapping):* `leading_comment(None, "demo.proto", (4, 0, 2, 0))` returns `None` without raising — defensive None handling per K-6.
- *Edge case (key miss):* `leading_comment({"other.proto": fd}, "demo.proto", (4, 0, 2, 0))` returns `None` when `file_name` not in the mapping.
- *Edge case (path miss):* `leading_comment({"demo.proto": fd}, "demo.proto", (99, 99))` returns `None` when no Location's path matches.
- *Edge case (empty comment):* When the matching Location has `leading_comments=""`, the function returns `None`.
- *Edge case (whitespace-only comment):* When the matching Location has `leading_comments="   \n  "`, the function returns `None` (`.strip()` to empty → `None`) per K-4 Option D normalization.
- *Edge case (leading/trailing whitespace stripped):* When the matching Location has `leading_comments="   Use UserV2 instead   "`, the function returns `"Use UserV2 instead"` (surrounding whitespace stripped, content preserved).
- *Edge case (multi-line, internal whitespace preserved):* When `leading_comments="   Line 1.\n   Line 2.   "`, the function returns `"Line 1.\n   Line 2."` (leading/trailing stripped, internal newlines + indentation preserved).
- *Adversarial (control chars passed through):* When `leading_comments="line1\nline2 line3"`, the function returns the raw string verbatim (`.strip()` is only whitespace; control chars survive). Sanitization is U3 caller responsibility (via existing `_safe_for_stderr`).
- *Type contract (path argument):* Passing `path=[4, 0, 2, 0]` (list) and `(4, 0, 2, 0)` (tuple) return the same result — the internal comparison `tuple(loc.path) == path` works against either iterable type for the input.
- *Determinism:* Two consecutive calls with identical inputs return identical results.

For `tests/schema/lint/test_engine_source_info_descriptors_injection.py` (engine integration):

- *Integration (5 contexts populated when opt-in):* `LintEngine.run(compile_result)` where the result came from `compile_protos_to_result(paths, include_source_info=True)` — a stub FIELD rule sees `ctx.source_info_descriptors is not None`. Repeat with stub rules for ENUM, ENUM_VALUE, METHOD, and MESSAGE contexts — each captures and asserts the same.
- *Integration (5 contexts get None when no opt-in):* Same as above but without `include_source_info=True` — all 5 stub rules see `ctx.source_info_descriptors is None`.
- *Integration (3 contexts never receive the field):* Stub rules registered against `FileLintContext`, `ServiceLintContext`, `OneofLintContext` MUST NOT have `source_info_descriptors` as an attribute — confirming the YAGNI boundary holds.
- *Integration (engine state clears after run):* After `LintEngine.run()` returns, `engine._current_source_info_descriptors` is `None`. Pins the finally-block cleanup.
- *Integration (engine state clears on exception):* If a rule body raises, the finally block still clears `_current_source_info_descriptors`.
- *Adversarial (rule re-runs the engine reentrantly):* Calling `engine.run()` recursively from within a rule must fail loudly. The existing reentrancy guard at `engine.py:315` checks `self._current_profile is not None`; the new `_current_source_info_descriptors` field is set AFTER that guard (per K-1), so the guard fires before either field can be corrupted. Verify the existing guard still triggers correctly when both fields are non-None mid-run.

**Verification:**

- `from protokit.schema.lint.rules.options._comments import descriptor_path, leading_comment` succeeds at import without triggering protobuf-descriptor imports.
- `from protokit.schema.lint.model import FieldLintContext, EnumValueLintContext, MethodLintContext, MessageLintContext, EnumLintContext` resolves with each carrying the new `source_info_descriptors` field.
- `from protokit.schema.lint.model import FileLintContext, ServiceLintContext, OneofLintContext` resolves WITHOUT the new field on these (YAGNI boundary).
- `pytest tests/schema/lint/rules/options/test_comments.py` passes all helper scenarios above.
- `pytest tests/schema/lint/test_engine_source_info_descriptors_injection.py` passes all integration scenarios.
- `pytest tests/test_static_analysis.py` passes (the new `rules/options/` path is type-checked under `mypy --strict`).
- The full `pytest tests/` suite passes (no regressions on the 1557 existing tests).
- `tests/schema/lint/test_cold_import_extended.py` still passes — `import protokit.schema` does not transitively load `protokit.schema.lint.rules.options`.
- Commit message body documents the CompileResult-instantiation audit conclusions (7 production sites — 6 in `compile.py` + 1 in `schema/lint/_cli_utils.py:399` — and 6 test sites, no edits required).

## System-Wide Impact

- **Interaction graph:** R6b's plumbing flows `compile_result.source_info_descriptors` → `LintEngine._current_source_info_descriptors` → 5 R6 ElementKind contexts → (future U3) `descriptor_path(ctx.field/method/etc.)` + `leading_comment(ctx.source_info_descriptors, ctx.file.name, path)`. The 3 untouched contexts (FILE / SERVICE / ONEOF) are unaffected.
- **Error propagation:** No new error paths. Both helpers (`descriptor_path` and `leading_comment`) return safely for every error-shaped input. The engine's existing rule-body exception handling is unchanged.
- **State lifecycle risks:** New engine instance attribute `_current_source_info_descriptors` must be cleared in the `finally` block of `run()` alongside `_current_profile`. If the clear is forgotten, a subsequent `run()` call could see stale data from a prior compile — covered by the "engine state clears after run" and "engine state clears on exception" test scenarios.
- **API surface parity:** 5 of 8 LintContext dataclasses gain the field (`FieldLintContext`, `EnumValueLintContext`, `MethodLintContext`, `MessageLintContext`, `EnumLintContext`). 3 contexts are intentionally NOT updated (`FileLintContext`, `ServiceLintContext`, `OneofLintContext`) — no current or planned rule needs comment access through them. The boundary is enforceable: an integration test pins that the 3 untouched contexts do NOT have the attribute.
- **Integration coverage:** The engine integration tests pin the cross-layer behavior for all 5 R6 contexts (`compile_protos_to_result` → `LintEngine.run` → context constructed via the right builder → rule body sees the field). Unit tests of `descriptor_path` and `leading_comment` alone would not prove the field-injection path works end-to-end for all 5 contexts.
- **Unchanged invariants:** `LintEngine.run`'s public signature, return type, and error-handling contract are unchanged. Each of the 5 touched contexts' public attribute set is widened by one — backward-compatible for keyword construction (all callers use keywords). The 3 untouched contexts are byte-identical to their pre-U2 state. The cold-import contract (`import protokit.schema` does not load lint) is preserved by TYPE_CHECKING-guarded annotations.

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Forgetting to clear `_current_source_info_descriptors` in the `finally` block causes stale state across consecutive `run()` calls | Integration tests "engine state clears after run" and "engine state clears on exception" pin this. |
| Adding the field to 5 contexts breaks an unknown positional-construction caller | Audit finding: ZERO positional `*LintContext(...)` callers in the repo. All test code uses the engine to construct contexts via the `_build_*_ctx` methods. No new code path exposes positional construction. Risk effectively zero. |
| `descriptor_path` recipe encodes the wrong wire-tag number for one of the ElementKinds | Unit tests with synthetic descriptors covering all 5 ElementKinds + nested cases pin the encoding. A bug in `descriptor_path` would cause `leading_comment` to return `None` silently (path miss) — the path-miss test catches this class of regression. |
| Protobuf 4 vs 5 expose different APIs for getting a top-level message's index in its file | Implementation discovers and chooses the right attribute (likely `descriptor.index` or walking `file.message_type`). The helper unit tests run against whatever runtime is installed; cross-runtime parity is part of the cross-protobuf-runtime test deferred to U6. |
| The new `rules/options/` package introduces a transitive protobuf-descriptor import that breaks the cold-import contract | TYPE_CHECKING guard on `FileDescriptorProto` in both `_comments.py` and `model.py` (K-3). The existing `tests/schema/lint/test_cold_import_extended.py` is the regression guard. |
| `leading_comment` is too narrow for future non-R6 callers (e.g., a comment-aware rule that needs trailing_comments or leading_detached_comments) | Acceptable — extend `_comments.py` then. For U2's R6-driven scope, the simplest possible signature wins. The deferred-tasks section captures the open extension points. |
| Programmatic callers using R6 rules without `include_source_info=True` get false-positive findings | Documented as accepted tradeoff in K-6. Mitigation via `LintRuntimeWarning` deferred to U5/D6c. |

## Documentation / Operational Notes

- README Public Surface DRAFT row updates are NOT in U2's scope per Scope Boundaries — they land at U7 (delivery boundary). U2's commit message body should note: "Public Surface DRAFT additions for the 5 contexts' `source_info_descriptors` (INTERNAL), `descriptor_path` (IN), and `leading_comment` (IN) deferred to U7 per [[delivery-boundary-unit-commit-composition]] discipline."
- CHANGELOG: U2 is a feature unit, not a boundary unit. No CHANGELOG entry at U2 — CHANGELOG `### D6b` section lands at U7.
- `docs/plans/2026-05-14-001-feat-protokit-lint-d6b-option-aware-and-multi-language-plan.md` (parent plan) Unit 2 checkbox flips from `- [ ]` to `- [x]` when U2 lands. Parent plan's U2 section preamble already documents that this per-unit plan supersedes it on specifics.

## Sources & References

- **Origin parent plan:** [docs/plans/2026-05-14-001-feat-protokit-lint-d6b-option-aware-and-multi-language-plan.md](2026-05-14-001-feat-protokit-lint-d6b-option-aware-and-multi-language-plan.md) — U2 section starts at line 334.
- **Origin brainstorm:** [docs/brainstorms/2026-05-14-protokit-lint-delivery-6b-option-aware-and-multi-language-requirements.md](../brainstorms/2026-05-14-protokit-lint-delivery-6b-option-aware-and-multi-language-requirements.md) — R6b discussion at line 55; helper signature at line 61; KTD around line 178; R6 rule-table at line 33.
- **U1 anchor commits:** `d6b6713` (feat: R6a opt-in parameter), `f33fb2a` (fix: ce:review follow-ups including the `source_locations` → `source_info_descriptors` rename), `9fe9404` (docs: ce:compound), `c37904d` (docs: plan refresh).
- **Document-review pass:** 2026-05-15 surfaced the FileLintContext-only / `ctx.location.path` design errors that this revision corrects. Reviewers: coherence + feasibility + adversarial. The shared-misreading discriminator from [[ce-review-cross-reviewer-agreement-shared-misreading-false-positive-amplifier]] was used to evaluate convergence findings on the original plan.
- **Related code:**
  - `src/protokit/schema/compile.py:163-219` — `CompileResult` dataclass with `source_info_descriptors` field shipped in U1.
  - `src/protokit/schema/lint/model.py:878-955` — `_LintContextEmitMixin` (no fields — pass-2 codex correction documented in docstring).
  - `src/protokit/schema/lint/model.py` — 5 R6 context insertion points: `FieldLintContext`, `EnumValueLintContext`, `MethodLintContext`, `MessageLintContext`, `EnumLintContext`.
  - `src/protokit/schema/lint/engine.py:118-125` — engine `__init__` (instance-state init site).
  - `src/protokit/schema/lint/engine.py:261-414` — `LintEngine.run` (set-after-guard + finally-clear sites).
  - `src/protokit/schema/lint/engine.py:641, 660, 677, 696, 713` — 5 builder methods to modify (`_build_method_ctx`, `_build_enum_ctx`, `_build_enum_value_ctx`, `_build_message_ctx`, `_build_field_ctx`).
  - `src/protokit/schema/lint/engine.py:609, 624, 732` — 3 builder methods intentionally NOT modified (`_build_file_ctx`, `_build_service_ctx`, `_build_oneof_ctx`).
  - `tests/schema/lint/test_compile_include_source_info.py` — U1 test pattern to mirror.
- **Related learnings:**
  - [[frozen-dataclass-mutable-fields-need-post-init-snapshot]]
  - [[no-raise-contract-extends-to-post-init-failures]]
  - [[circular-import-type-checking-cycle-break]]
  - [[matcher-backend-path-resolution-skew-silently-empties-output]]
  - [[pytest-static-analysis-gate-ratchet]]
  - [[pytestmark-does-not-guard-module-top-imports]]
  - [[ce-review-cross-reviewer-agreement-shared-misreading-false-positive-amplifier]]
  - [[delivery-boundary-unit-commit-composition]]
