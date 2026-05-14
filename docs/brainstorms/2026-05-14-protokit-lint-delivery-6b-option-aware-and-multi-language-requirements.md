# protokit-lint Delivery 6b — option-aware capability validated + multi-language migration target

**Status:** brainstorm (requirements). Next step: `/ce:plan`.
**Date:** 2026-05-14.
**Origin:** D6a deferred-to-D6b items finalized at the D6a delivery boundary (commit `1b59cae`, 0.2.0 release, 2026-05-13/14).
**Predecessor:** `docs/brainstorms/2026-05-12-protokit-lint-delivery-6a-rule-library-requirements.md` framed the D6a/D6b split; D6a's plan at `docs/plans/2026-05-12-001-feat-protokit-lint-d6a-rule-library-plan.md` enumerated "Deferred to Separate Tasks"; `TODOS.md` "D6b backlog items surfaced during D6a" is the running source-of-truth.

## TL;DR

D6b ships protokit's first comment-aware lint rule and unblocks multi-language teams for buf BASIC migration. **The headline is option-aware capability operational** — R6 is the first rule using SourceCodeInfo introspection, validating the path the option-aware pack (D6c+) will grow against. Pre-1.0 stance: R6's worked example demonstrates the path; the full differentiator claim ("protokit reads custom options AND comments to enforce schema policy") lands when the option-aware pack grows in D6c. Multi-language migration via the PACKAGE_SAME_* family is the larger user-impact surface in D6b by rule count.

Three product surfaces:

1. **Option-aware path operational** — `options/deprecated/{field,enum-value,method,message,enum}-must-have-replacement-comment` (5 rules sharing a comment-introspection helper, one per `*Options.deprecated` ElementKind) fires in `default` profile. Supporting infrastructure: `SourceCodeInfo` preservation as an opt-in parameter on `compile_protos_to_result(..., include_source_info=...)` (default `False`; lint sets `True` when loaded), `CompileResult.source_locations` index that survives `pool.Add()`, and a module-level `leading_comment(source_locations, file_name, path)` free function. Comment-derived param values pass through the existing `_safe_for_stderr` sanitizer (already covers U+2028 / U+2029 / control chars per D5 U5).
2. **Buf BASIC parity for cross-language teams** — 7 PACKAGE_SAME_* rules (`go_package`, `java_package`, `csharp_namespace`, `php_namespace`, `ruby_package`, `swift_prefix`, `java_multiple_files`) ship under `recommended` + `default`, sharing an engine-managed per-package option-value accumulator built in a pre-walk pass over `CompileResult.root_files`. Multi-language teams can now drop-in migrate from buf for the rule-set parity layer (other migration touchpoints — `buf.yaml` config import, `buf:lint:ignore` comments, `buf breaking` parity — remain post-D6b).
3. **`severities_unloaded_rule` category split** — additive Literal value closing the U9 KTD-2 trip-wire; consumers switch on `category` instead of message substring. Wire-format `schema_version` bumps `"0.2"` → `"0.3"` (scoped to the new enum value only — new rule_ids in `findings` do NOT bump).

Explicit non-goals (deferred to D6c or post-1.0): **`package/same-directory`** (the 18th buf BASIC rule — requires a cross-file rule kind in the engine; deferred for its own architectural delivery so D6b stays focused), `strict` profile, R9b per-rule disable/enable lists, expanded option-aware pack beyond R6's deprecated-replacement family.

## Problem Frame

D6a (0.2.0, shipped 2026-05-13/14) made protokit-lint a credible buf BASIC competitor **for single-language teams**. Two product gaps remain visible to users right now:

- **Multi-language teams are blocked on the rule-set layer.** Buf's BASIC tier includes the cross-language `PACKAGE_SAME_*` family by default. A team running `buf lint` with `PACKAGE_SAME_GO_PACKAGE` (or any sibling) enabled cannot drop-in migrate to protokit's `recommended` profile — protokit silently doesn't fire those rules, so the migration appears to succeed while quietly weakening the policy. (Other migration touchpoints — `buf.yaml` config import, `buf:lint:ignore` comment parity, `buf breaking`, IDE integrations — are separate gaps not addressed by D6b. The rule-set layer is the highest-impact single gap.)
- **The option-aware path is unproved.** Protokit's strategic differentiation (per the D6a brainstorm: "nothing in the industry can directly replicate" custom-option-aware rules) is currently theoretical. No rule in `BUILTIN_PACKS` reads custom options or source comments today. Without at least one rule demonstrating the path end-to-end, the differentiator claim is unbacked by code. D6b's R6 family validates the *plumbing* (SourceCodeInfo preservation + leading_comment helper + sanitizer reuse); the broader claim ("custom-option-aware rules across protokit's pack") matures in D6c+ when the pack grows beyond the deprecated-replacement family.

D6b closes the rule-set parity gap for multi-language teams AND lands the option-aware plumbing with its first 5-rule consumer (one rule per `*Options.deprecated` ElementKind, all sharing a comment-introspection helper). The headline is "option-aware path operational" because that capability is the durable strategic asset that compounds across future deliveries; parity completion is the larger user-impact surface but is by definition a checkbox the project will eventually clear regardless of strategic positioning.

## Requirements

### Option-aware path

- **R6 (option-aware family — 5 rules sharing one helper).** Ship 5 `@lint_rule`-decorated functions under `protokit.schema.lint.rules.options.deprecated_replacement`, one per `*Options.deprecated` ElementKind, all sharing a common `_check_replacement_comment(leading_comment_text) -> bool` helper. Decision: per-ElementKind rule_ids (not decorator widening) because (a) `@lint_rule(element: ElementKind)` stays singular, (b) users can demote per-kind via `[tool.protokit.lint.severities]`:

  | rule_id | ElementKind | Triggers on |
  |---------|-------------|-------------|
  | `options/deprecated-field-must-have-replacement-comment` | FIELD | `FieldOptions.deprecated = true` |
  | `options/deprecated-enum-value-must-have-replacement-comment` | ENUM_VALUE | `EnumValueOptions.deprecated = true` |
  | `options/deprecated-method-must-have-replacement-comment` | METHOD | `MethodOptions.deprecated = true` |
  | `options/deprecated-message-must-have-replacement-comment` | MESSAGE | `MessageOptions.deprecated = true` |
  | `options/deprecated-enum-must-have-replacement-comment` | ENUM | `EnumOptions.deprecated = true` |

  Each rule reads `*Options.deprecated`, calls `leading_comment(source_locations, file_name, path)` (free function in `protokit.schema.lint.rules.options._comments`), and passes the result to `_check_replacement_comment`. Helper signature heuristic: regex/keyword match against the `/use\s+[\w.]+\s+instead/i` family plus `/replaced\s+by\s+[\w.]+/i` and `/see\s+[\w.]+/i` as alternative phrasings (finalize regex set during `/ce:plan` against a fixture corpus). Aim: **high precision** (minimize false positives at the cost of some false negatives) — falsely flagging a legitimate deprecation comment is worse than silently missing one. Unicode handling: Python 3 `\w` is Unicode-aware by default; covers non-ASCII deprecation phrasings.

  **Severity: `warning` at launch** (per feasibility + product-lens convergence). The asymmetry of costs for a heuristic-based rule favors `warning` initially — low CI blast radius, allows users to see signal without breaking builds while the regex corpus is validated. Promotion to `error` is a D6c decision once real-world miss/hit rate is measured. (Buf has no analogue at any severity; intentional protokit-only divergence documented in each rule's docstring per [[buf-parity-divergence-documentation-discipline]].)

  Profile membership: `default` only — `recommended` stays buf BASIC parity. Param sanitization: the comment-derived `params["leading_comment"]` value (truncated to a fixed prefix length, e.g., 200 chars, to bound wire-format size) passes through the existing `_safe_for_stderr` helper at finding-construction time. The shared `_CONTROL_CHAR_TABLE` already strips U+0085 / U+2028 / U+2029 / ASCII control chars per D5 U5 — no new sanitizer module needed (see resolved-in-doc notes below).

- **R6a (SourceCodeInfo enablement — opt-in at API boundary).** Add `include_source_info: bool = False` parameter to `compile_protos_to_result(...)` in `src/protokit/schema/compile.py`. Threaded through to both compile backends: `_compile_with_protoxy` flips `include_source_info=True` at `src/protokit/_cli_utils.py:257` (currently hard-coded `False` with a byte-equivalence-between-backends comment that must update to reflect the new "both backends now carry source-location info when requested" contract), and `_compile_with_protoc` adds `--include_source_info` to the command at `src/protokit/_cli_utils.py:305`. Both backend functions' signatures grow a third return element: `tuple[DescriptorPool, tuple[str, ...], Mapping[str, FileDescriptorProto] | None]`, with the third element None when `include_source_info=False`.

  **Lint CLI sets `include_source_info=True`** in its `compile_protos_to_result` call; other consumers (`protokit compat`, codegen, direct Python API) get the pre-D6b default (False, no descriptor-size impact). This preserves the cold-path zero-cost contract for non-lint workflows — D1-D5 functionality unchanged, no 10-30% size tax imposed on consumers who never use lint. Atomic flip of BOTH backends required to preserve the byte-equivalence-between-backends invariant (just flipping one breaks the cross-backend determinism contract).

  Document the measured descriptor-size delta (under lint's `include_source_info=True` path) in CHANGELOG once `/ce:plan` benchmarks against a representative corpus. Cross-protobuf-version verification step in U1: build descriptor sets with `include_source_info=True` against protobuf 4 latest and protobuf 5 latest for the same fixture; assert `leading_comment(path)` returns byte-identical results from both backends and both runtimes (mitigates the cross-version drift risk surfaced in adversarial review).

- **R6b (CompileResult source-location index + free-function helper).** `DescriptorPool.Add(FileDescriptorProto)` discards `source_code_info` regardless of R6a's setting — this is a protobuf-library invariant, not a bug in protokit. R6b adds `CompileResult.source_locations: Mapping[str, FileDescriptorProto] | None` populated FROM the raw `FileDescriptorSet` BEFORE `pool.Add()` consumes it. The data flow: backend functions return `(pool, root_names, source_locations | None)` per R6a; `compile_protos_to_result` in `src/protokit/schema/compile.py` (the canonical instantiation site for `CompileResult`, NOT `_cli_utils.py`) populates the field. Defaults to `None` for callers that don't request source info, preserving backward compatibility.

  **`leading_comment` is a module-level free function**, NOT a method on `_LintContextEmitMixin`. Signature:

  ```python
  # src/protokit/schema/lint/rules/options/_comments.py
  def leading_comment(
      source_locations: Mapping[str, FileDescriptorProto] | None,
      file_name: str,
      path: tuple[int, ...],
  ) -> str | None:
      """Return the leading comment for ``path`` in ``file_name``, or None."""
  ```

  R6's 5 rules call it directly: `leading_comment(ctx.compile_result.source_locations, ctx.file_name, ctx.location.path)`. **No new field on the 8 LintContext dataclasses**, **no `__post_init__` paired-field invariant**, **no mixin method** — the free function reads from `compile_result` which contexts already reference. Future comment-aware rules call the same free function. (Scope-guardian convergence: this avoids 8-dataclass plumbing and 8 paired-field tests for a capability with one current consumer. If a future delivery has 5+ comment-aware rules and a mixin method earns its keep on ergonomics, extract then.)

  CompileResult shape audit (per feasibility + adversarial findings): U2 audits all CompileResult callers (internal + tests) for positional unpacking, equality comparisons against goldens, repr-based assertions, hashing. `Mapping[str, FileDescriptorProto]` is not naturally hashable — if hash usage exists, normalize to a frozen-mapping representation OR exclude the field from `__hash__` via `field(hash=False)`.

  Public Surface DRAFT classification: `CompileResult.source_locations` enters as **INTERNAL** (not IN), per security-lens concern about exposing raw comment content as a stable surface. The field is consumed by lint internals; downstream callers should treat it as an implementation detail. If a use case emerges where consumers want to read comments directly, reclassify to IN in a later delivery with explicit data-exposure documentation.

- **R6c (sanitization — inline reuse, no new module).** Comment-derived `params` values pass through the existing `_safe_for_stderr` helper at finding-construction time. The shared `_CONTROL_CHAR_TABLE` from D5 U5 already covers U+0085 / U+2028 / U+2029 / ASCII control chars — the threat model R6 cares about is identical. R6's rules call `_safe_for_stderr(leading_comment_text[:200])` directly (200-char prefix bounds the wire-format size; full comment is typically short but adversarial protos could carry multi-KB comments per security-lens DoS amplification concern).

  No new module, no `_safe_for_findings` abstraction created. If a second comment-aware rule lands in D6c with meaningfully different escaping concerns, extract a named helper then. Until then, the rename-on-extraction principle keeps the surface minimal. (Scope-guardian + adversarial 2-persona convergence on this.)

  **Open scope question for `/ce:plan`:** does R7's PACKAGE_SAME_* family — which emits `*_package` string values in `LintFinding.params` — ALSO need `_safe_for_stderr` sanitization? FileOptions string values are user-controlled proto content flowing into wire formats; the answer is likely yes (defense-in-depth), but the threat is lower (FileOptions strings are typically valid Go/Java/etc. package names, not arbitrary comment text). `/ce:plan` decides whether to apply sanitization broadly or scope to comment-derived params only.

### Cross-language parity (buf BASIC completion)

- **R7 (PACKAGE_SAME_* family).** Ship 7 cross-language namespace-consistency rules under `protokit.schema.lint.rules.package_same.*` (or `cross_language.*` — `/ce:plan` picks the module shape):

  | rule_id | buf rule | What it checks |
  |---------|----------|----------------|
  | `package/same-go-package` | `PACKAGE_SAME_GO_PACKAGE` | All files in a package agree on `option go_package` |
  | `package/same-java-package` | `PACKAGE_SAME_JAVA_PACKAGE` | All files in a package agree on `option java_package` |
  | `package/same-csharp-namespace` | `PACKAGE_SAME_CSHARP_NAMESPACE` | All files in a package agree on `option csharp_namespace` |
  | `package/same-php-namespace` | `PACKAGE_SAME_PHP_NAMESPACE` | All files in a package agree on `option php_namespace` |
  | `package/same-ruby-package` | `PACKAGE_SAME_RUBY_PACKAGE` | All files in a package agree on `option ruby_package` |
  | `package/same-swift-prefix` | `PACKAGE_SAME_SWIFT_PREFIX` | All files in a package agree on `option swift_prefix` |
  | `package/same-java-multiple-files` | `PACKAGE_SAME_JAVA_MULTIPLE_FILES` | All files in a package agree on `option java_multiple_files` |

  All 7 fire on FILE-level descriptors; each rule reads its specific `FileOptions` field. **The engine adds a per-run accumulator built in a pre-walk pass** (feasibility + scope-guardian + adversarial 3-persona convergence: the "per-file rules that don't need engine extension" framing in the original draft was misleading — the accumulator IS engine state, even if it doesn't require a new ElementKind or LintLocation variant). Mechanism:

  1. Before per-file rule dispatch, `LintEngine.run` iterates `compile_result.root_files` ONCE to build `package_options: dict[str, dict[str, str | None]]` keyed by `(package_name, option_name)` (e.g., `{"foo.bar": {"go_package": "github.com/foo/bar", "java_package": "com.foo.bar"}}`). Files that don't declare an option contribute `None` for that key — `/ce:plan` audits buf's actual NULL semantics (does buf treat "absent" as "matches" or "disagrees"?) and the rule emits accordingly per [[audit-wire-format-before-claiming-sibling-parity]].
  2. Each PACKAGE_SAME_* rule reads `package_options[ctx.package_name][option_name]` via a new `FileLintContext.package_options` field (single addition, no 8-context plumbing).
  3. **Emit-shape contract:** a rule emits one finding per file whose value disagrees with the package's *canonical* value, where canonical is defined as "the value declared by the lexicographically-smallest filename in the package" (deterministic across OS / CI / iteration order). `/ce:plan` verifies this matches buf's actual emit-shape against fixtures with mixed-presence + mixed-value cases.

  Profile membership: `recommended` + `default` (matching buf BASIC's default-on posture). Severity: `error` (matching buf BASIC). Sanitization: each rule's `params` (file_name + option_value + canonical_value strings) passes through `_safe_for_stderr` if R6c's broad-sanitization decision lands as "yes" — `/ce:plan` finalizes scope.

  Parity fixtures under `tests/parity/fixtures/package/same-{lang}/`: `good.proto` (all files agree, including all-absent case), `bad-value.proto` (files declare different values), `bad-presence.proto` (some files declare, others omit) per the buf-parity audit discipline.

  **Note:** `package/same-directory` (the 18th buf BASIC rule) is **deferred to D6c** — see Non-Goals. D6b ships 17 of 18 buf BASIC rules; the remaining gap is the one rule requiring the cross-file rule-kind engine extension, deferred for its own focused architectural delivery rather than rushed into D6b under a conditional scope-cut.

### Wire-format wrap-up

- **R9 (`severities_unloaded_rule` category split).** Widen `LintRuntimeWarning.category: Literal` to add a 5th value: `"severities_unloaded_rule"`. The CLI-synthesized emit site at `src/protokit/schema/lint/cli.py:1063-1090` (currently reusing `unloaded_rule`) switches to the new value. The engine-emitted `unloaded_rule` category remains unchanged.

  Update sites per [[semantic-category-conflation-accepted-tradeoff-literal-widening]]'s 3-site discipline:
  - Literal docstring on `LintRuntimeWarning` notes both categories
  - Emit-site comment at the CLI line range above explains the switch
  - `TODOS.md` "D6b backlog" entry resolves (deletes itself or marks SHIPPED)

  Wire format bump: `_LINT_JSON_SCHEMA_VERSION` increments from `"0.2"` → `"0.3"` per the bump-contract in [[wire-format-schema-version-bump-contract-and-absence-semantic]] (new enum-value addition to a closed discriminator is a documented bump trigger — adding a new `category` value is a consumer-detectable wire change). The constant's docstring's absence-semantic clause carries forward unchanged.

  **Bump scope clarification** (per scope-guardian + product-lens review): New `rule_id` strings in `LintFinding` output (R6, R7, R8) are NOT bump triggers — `findings` is an additive list and consumers must already tolerate unknown rule_ids. New `category` Literal values in `LintRuntimeWarning` ARE bump triggers because `category` is a closed discriminator that consumers exhaustively switch on. The CHANGELOG D6b section enumerates this distinction explicitly: the wire-format `schema_version` bump (`0.2` → `0.3`) is scoped to R9's new enum value ONLY; R6/R7/R8's new rule_ids do not affect the wire schema. Both file/SARIF emit sites in `src/protokit/formatters/_builtin_lint.py` (line 250 constant + lines 329/673 consumption) update from one constant edit.

  Public Surface DRAFT row added for the new category.

### Carried infrastructure

- **R10 (parity test expansion).** `tests/parity/fixtures/package/same-{lang}/` adds 7 fixture pairs (one per PACKAGE_SAME_* rule). `tests/parity/fixtures/package/same-directory/` adds the cross-file fixture (if R8 ships). Parity job stays advisory (J2 from D6a).

- **R11 (CHANGELOG D6b section + 0.2.0 → 0.3.0 version bump).** Pre-1.0 stance continues per [[pre-1.0-version-bump-as-communication-contract]]: plain `### D6b — ...` section, no `BREAKING:` prefix. Section enumerates the option-aware capability (headline), buf BASIC parity completion, the new category value (additive wire-format), and demotion paths for users who don't want the new R7 + R8 + R6 findings. The version bump (0.2.0 → 0.3.0) is the breaking-change signal.

- **R12 (Public Surface DRAFT additions).** New rows: `CompileResult.source_locations` (IN), `_LintContextEmitMixin.leading_comment(path)` (IN), `_safe_for_findings` (INTERNAL — implementation detail), the new R6/R7/R8 rule_ids enumerated as part of the existing rule-set row, `LintRuntimeWarning.category` Literal updated to include `severities_unloaded_rule`, `_LINT_JSON_SCHEMA_VERSION: "0.3"` row replaces the existing `"0.2"` row.

## Non-Goals (deferred to D6c)

- **`package/same-directory` (the 18th buf BASIC rule + cross-file rule kind).** Originally Tier 2 of the D6b scope; deferred to D6c after 3-persona review (scope-guardian + adversarial + product-lens) flagged the conditional defer-cut as scope ambiguity. The cross-file rule kind requires a new `ElementKind` value + a new `LintLocation` discriminant + an engine walker phase + an audit of every `match/case` over `LintLocation` in formatters per the cross-format-enum-string-parity discipline. That's a multi-module wire-format change worth its own focused delivery, not a Tier-2 add-on to D6b. **Honest framing:** D6b ships 17 of 18 buf BASIC rules; CHANGELOG documents `package/same-directory` as "the one remaining buf BASIC gap, lands in D6c." Pre-commit to this now rather than discovering it at `/ce:plan` time.

- **`strict` profile.** Shipping `strict` with placeholder rules repeats the original D6a mistake. D6b ships the option-aware path; D6c can enumerate strict-only rules (COMMENT_* family, `ENUM_ZERO_VALUE_SUFFIX`, etc.) once D6b user feedback identifies which "stricter than recommended" rules teams actually want. **Acknowledged inconsistency:** D6a shipped `essentials` as a 0-rule forward-placeholder in the Public Surface DRAFT. The "don't ship empty profiles" principle that defers `strict` here is therefore already partially violated. D6b does NOT resolve the inconsistency (out of scope); D6c should pick one stance and apply it to BOTH `essentials` and `strict` (either remove `essentials` from the surface OR ship `strict` empty alongside it).

- **R9b per-rule disable/enable lists** (`disabled_rules` / `enabled_rules`). The 4 collision-shape precedence semantics still need real-demand evidence to design against. D6a literally shipped today; D6b implementation begins immediately after this brainstorm. The R9a severity-demote-to-info workaround stays usable. Re-evaluate post-D6b based on user reports. (Asymmetry note vs R9: R9 ships in D6b despite identical "no real-demand evidence" status because R9 is a wire-format-additive change closing a known trip-wire from a prior delivery's deferred decision, not a new design space. R9b is a 4-precedence-shape design space; deferring it for evidence is more defensible than deferring R9.)

- **Expanded option-aware pack** beyond R6's deprecated-replacement family. Once R6's 5-rule family validates the plumbing, candidate D6c rules include `options/required-field-behavior` (reads googleapis `field_behavior` option), `options/required-custom-annotation` (generic, pyproject-driven), `options/json-name-respects-snake-case`. Each compounds the differentiator value; growing the pack belongs in its own delivery with user feedback shaping which rules matter.

- **Per-file rule overrides** (pyproject-level path-glob → rule-id mapping). Sibling of R9b; same real-demand-evidence rationale.

- **Per-buf-version parity matrix.** D6a pins one buf version; D6b stays pinned. Multi-version tracking is post-D6c infrastructure work.

- **D7 plugin API slice.** Worth considering as a swap for R7 in a future delivery (the long-term differentiator is user-shippable option-aware rules via plugin API, per product-lens opportunity-cost finding). Not in D6b scope; flagged here so future brainstorms can revisit the ordering.

## Open Questions

These are deferred to `/ce:plan` (the right place to resolve them with concrete file references):

### Deferred to Planning

- **R6 regex set finalization.** The `/use\s+[\w.]+\s+instead/i` family is a starting point. `/ce:plan` enumerates a fixture corpus of real-world deprecation comments (googleapis, common protobuf style guides) and finalizes the regex set with a measured precision target. Severity is `warning` at launch regardless of corpus tuning; promotion to `error` is a D6c decision.

- **R6 comment-length bound.** Inline note above suggests 200-char truncation prefix before sanitization to bound wire-format size. `/ce:plan` measures comment-length distribution against a real corpus and picks a concrete threshold (200? 500? 1000?). Adversarial protos with multi-KB deprecation comments are an explicit consideration.

- **R7 module shape.** Single module `package_same.py` exposing all 7 rules, or one module per language (`package_same/go.py`, `package_same/java.py`, ...). Single module is simpler; per-language modules give clearer parity-fixture co-location. `/ce:plan` decides.

- **R7 NULL semantics.** Does `option go_package` *absent* on file A count as "agrees with file B's declared value" (silent) or "disagrees" (fires)? `/ce:plan` audits buf's actual emit on mixed-presence fixtures and documents the chosen semantics per [[buf-parity-divergence-documentation-discipline]].

- **R7 sanitization scope.** Does the FileOptions string value (e.g., `option go_package = "..."`) flowing into `LintFinding.params` need `_safe_for_stderr` sanitization, or is it scoped to R6's comment-derived params only? `/ce:plan` decides; defense-in-depth bias suggests broad application.

- **R6 sub-rule module structure.** 5 separate `.py` files under `protokit/schema/lint/rules/options/` (one per ElementKind), OR one `deprecated_replacement.py` exposing all 5 `RULES` entries. `/ce:plan` picks based on test co-location ergonomics.

- **CompileResult shape audit findings.** U2 audits all `CompileResult` callers for positional unpacking, equality, repr, pickle, hash usage. Any required normalization (frozen-mapping for hashability, etc.) is finalized during U2.

### Resolved Here

- **Headline:** option-aware path operational (differentiator-first, honestly scoped to "first option-aware rule lands; pack expansion is D6c"). PACKAGE_SAME_* family is documented as the larger user-impact surface but secondary in framing.

- **R6 ships as 5 separate `@lint_rule` functions** (one per `*Options.deprecated` ElementKind), sharing a `_check_replacement_comment` helper. Decorator stays singular; users can demote per-kind via `[tool.protokit.lint.severities]`.

- **R6 in `default` only, not `recommended`:** the R6 family is intentionally NOT in `recommended` (which stays buf BASIC parity). Users targeting buf BASIC parity (`recommended`) don't see R6 findings; users targeting protokit's full capability (`default`) do.

- **R6 severity: `warning` at launch** (per feasibility + product-lens convergence on the heuristic-rule blast-radius asymmetry). Promotion to `error` is a D6c decision after corpus tuning.

- **`include_source_info` opt-in at the `compile_protos_to_result` API boundary** (default `False`; lint sets `True`). Non-lint consumers (compat, codegen) keep the pre-D6b zero-cost contract. Atomic flip of both backends preserves byte-equivalence-between-backends; non-shared paths unaffected.

- **`leading_comment` is a module-level free function**, NOT a method on `_LintContextEmitMixin`. Eliminates 8-dataclass plumbing, 8 paired-field invariants, 8 test additions. If a future delivery has 5+ comment-aware rules and a mixin method earns its keep, extract then.

- **No new `_safe_for_findings` module.** Reuse the existing `_safe_for_stderr` + `_CONTROL_CHAR_TABLE` inline at R6's finding-construction sites. New module deferred until a second consumer with meaningfully different escaping concerns exists.

- **`CompileResult.source_locations` enters Public Surface DRAFT as INTERNAL**, not IN. Comment content exposure is an implementation detail subject to change; reclassify if downstream callers articulate a need.

- **R7 acknowledges engine state explicitly:** the per-package option-value accumulator IS engine-managed (a pre-walk pass over `compile_result.root_files`), even though it doesn't require a new ElementKind. Files surface via a new `FileLintContext.package_options` field (single dataclass addition). Emit-shape contract pins canonical = lexicographically-smallest filename in the package for determinism.

- **`package/same-directory` deferred to D6c** (NOT a Tier-2 conditional). The cross-file rule kind is its own architectural delivery. D6b ships 17 of 18 buf BASIC rules; CHANGELOG documents the gap honestly.

- **`severities_unloaded_rule` is additive, not BREAKING in the wire-format sense:** new Literal value + new emit-site behavior, but no existing consumer's parsing breaks (a consumer expecting `unloaded_rule` still sees `unloaded_rule` from the engine emit site). Schema_version bump is the documented bump-trigger; R6/R7's new rule_ids do NOT trigger additional bumps (per the bump-scope clarification in R9).

## Success Criteria

1. **R6 family demonstrably works on a real proto.** A fixture proto with `FieldOptions.deprecated = true` (and siblings on enum-value, method, message, enum) plus comments that do/don't match the heuristic produces exactly the expected findings — one finding per ElementKind whose comment fails the check, zero findings when comments comply. Verified via the standard rule-test pattern + a worked example in README's "Schema Linting" section.

2. **17-of-18 buf BASIC parity for cross-language teams.** `tests/parity/fixtures/package/same-{lang}/` has 7 fixture sets (good + bad-value + bad-presence per rule) passing the parity job. Buf BASIC enumeration (as of the pinned version) matches protokit's `recommended` rule set 1:1 EXCEPT `package/same-directory` which is honestly documented as deferred to D6c.

3. **`severities_unloaded_rule` consumers can switch on category, not message.** A test asserts that the CLI emit path produces `category="severities_unloaded_rule"` (not `"unloaded_rule"`) for a `[tool.protokit.lint.severities]` key naming an unloaded rule. The wire-format `schema_version` increments to `"0.3"` at both consumption sites (`formatters/_builtin_lint.py:329` lint_json + `:673` lint_sarif), recorded via the single `_LINT_JSON_SCHEMA_VERSION` constant edit.

4. **Cold-import contract holds.** `import protokit.schema` does NOT transitively load `protokit.schema.lint`, even after R6a/R6b infrastructure. The existing test `tests/schema/lint/test_cold_import_extended.py` catches violations. R6b's `FileDescriptorProto` type annotation on `CompileResult.source_locations` is verified as TYPE_CHECKING-gated or via string annotation to prevent transitive protobuf-descriptor imports.

5. **Static-analysis ratchet holds.** New D6b paths (`protokit.schema.lint.rules.package_same.*`, `protokit.schema.lint.rules.options.*`) are added to `tests/test_static_analysis.py:_LINT_PATHS` in the same commit they're created per [[pytest-static-analysis-gate-ratchet]].

6. **D6a regressions:** zero. The full pre-D6b test suite (1536 tests as of D6a U10 commit `1b59cae`) continues to pass. Tests coupled to `include_source_info=False` semantics in shared backends are unaffected (the new opt-in parameter preserves the pre-D6b default). Tests that hash/equate `CompileResult` instances are audited in U2 and updated if needed.

7. **Multi-language teams can migrate at the rule-set layer.** README + CHANGELOG explicitly call out that D6b unblocks rule-set parity for multi-language teams (single-language teams' existing migration path is unchanged). The "single-language teams only" caveat from D6a's README is removed or amended. **Honest scope:** other migration touchpoints (`buf.yaml` import, `buf:lint:ignore` parity, breaking-change parity, IDE integrations) remain post-D6b and are listed as remaining gaps.

8. **Option-aware path operational with R6's worked example.** README has a worked example showing: a sample `deprecated`-tagged field, the leading comment that would (or wouldn't) satisfy `options/deprecated-field-must-have-replacement-comment`, and the resulting `warning`-severity finding. The example tangibly demonstrates the comment-aware capability; the broader "full option-aware pack" claim is explicitly scoped to D6c.

## Output Structure (delivery shape)

Expected unit count: **6-8 units** (down from 8-10 after R8 deferred to D6c and R6c collapsed into R6).

Tentative unit decomposition (`/ce:plan` refines):

1. **U1 — R6a SourceCodeInfo enablement** (opt-in parameter on `compile_protos_to_result`; both backends flipped atomically when `include_source_info=True`; backend functions return third element `Mapping[str, FileDescriptorProto] | None`; benchmark descriptor-size delta; cross-protobuf-version verification). Foundation; no rule changes yet.

2. **U2 — R6b CompileResult.source_locations + `leading_comment` free function** (CompileResult dataclass field addition + `compile_protos_to_result` integration + `protokit.schema.lint.rules.options._comments.leading_comment` module-level helper). **No LintContext field plumbing, no mixin method, no 8-context paired-field invariants** — the free function reads from `compile_result` which contexts already reference. Includes CompileResult consumer audit (positional unpacking, equality, hash, repr in callers + tests).

3. **U3 — R6 family (5 rules)** (`options/deprecated-{field,enum-value,method,message,enum}-must-have-replacement-comment`) sharing a `_check_replacement_comment` helper + inline `_safe_for_stderr` reuse for comment-derived params (200-char truncation prefix). All 5 ship in `default` profile only, severity `warning`. Option-aware path validated end-to-end at this unit's completion.

4. **U4 — R7 PACKAGE_SAME_* family (7 rules)** + engine pre-walk accumulator + `FileLintContext.package_options` field (single dataclass addition) + emit-shape contract (canonical = lexicographically-smallest filename in package). Largest rule-count unit; engine pre-walk pass is the net-new engine state but no new ElementKind or LintLocation variant. Parity fixtures (good + bad-value + bad-presence per rule) co-located.

5. **U5 — R9 `severities_unloaded_rule` category split** (Literal widening + CLI emit-site switch + `_LINT_JSON_SCHEMA_VERSION` constant bump `"0.2"` → `"0.3"` covering both `lint_json:329` + `lint_sarif:673` consumption sites). Smallest unit; additive wire-format addition.

6. **U6 — Parity test infrastructure consolidation** (R10 fixture-suite audit for new rules; parity-job verification; cross-format JUnit/SARIF/JSON matrix coverage per [[parametrized-matrix-tests-inherit-schema-validators]]). May fold into U4 if scope is small.

7. **U7 — Delivery boundary** (R11 CHANGELOG D6b + R12 Public Surface DRAFT additions + README refresh with R6 worked example + version bump 0.2.0 → 0.3.0 + KD-9 docstring increment + presence-ratchet tests per [[presence-ratchet-test-pattern-for-prose-substrings]] + stale-text sweep per [[stale-forward-looking-text-cli-help-agent-discoverability]] triage rubric). Mirrors D6a U10's shape per [[delivery-boundary-unit-commit-composition]].

`/ce:plan` finalizes unit boundaries; some units may split (R7 across two units if 7 rules cluster differently) or merge (U6 likely folds into U4 unless parity infrastructure grows).

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| `include_source_info=True` (under lint) breaks D1-D5 tests that hardcode descriptor-set bytes | Lint path opts in via the new parameter; non-lint shared-backend callers stay on the pre-D6b default. Audit affected tests in U1; verify cross-backend byte-equivalence is preserved when both backends opt in atomically. |
| R6b's source_locations index doesn't survive `pool.Add()` ordering — race between FileDescriptorSet parse and pool consumption | The D6a feasibility review verified the ordering works: index is built FROM the raw set BEFORE pool consumes it. U2 includes an explicit test asserting `source_locations` is non-None after compile when `include_source_info=True`, and a cross-backend (protoxy + protoc) byte-identical test for the indexed contents. |
| R6 false-positive epidemic on legitimate deprecation comments using non-canonical phrasings | Severity `warning` at launch limits CI blast radius. Heuristic regex set tuned during `/ce:plan` against a representative corpus with precision-as-primary-metric. Per-rule demotion via `[severities]` available. Promotion to `error` deferred to D6c. |
| R7's PACKAGE_SAME_* family fires false positives on legitimate cross-language differences (e.g., intentional vendor isolation) | Document each rule's heuristic limitations; users can demote via `[severities]` per-rule per the D6a demotion paths. NULL semantics (absence-as-disagree vs absence-as-silent) finalized at `/ce:plan` against buf's actual emit-shape. |
| `package/same-directory` deferred to D6c — buf BASIC parity is 17 of 18 rules, not full | Honest documentation in CHANGELOG + README: "the one remaining buf BASIC gap lands in D6c alongside the cross-file rule kind infrastructure." Pre-commit to deferral rather than discover at planning time. |
| Descriptor-size impact of `include_source_info=True` blocks adoption by large-corpus users | Opt-in parameter scopes the cost to lint workflows only. Non-lint consumers (compat, codegen) keep the zero-cost contract. Pre-1.0 stance ([[pre-1.0-version-bump-as-communication-contract]]) means future tightening (e.g., a comment-size cap to defend against adversarial protos) is communicated via version bump. |
| Adversarial protos with multi-KB leading comments inflate descriptor-set memory under lint | R6 truncates comment text to 200 chars at finding-construction (concrete limit finalized at `/ce:plan`). Bounds wire-format size; full comment never reaches downstream consumers. Defense-in-depth alongside sanitization. |
| Wire-format `schema_version` bump to "0.3" misleads consumers into expecting R6/R7's new rule_ids to be wire-format changes | The CHANGELOG section explicitly enumerates the bump scope: ONLY the new `category` Literal value triggers the bump; new rule_ids in `findings` are additive and consumers must tolerate unknown rule_ids per pre-existing wire-format contract. |
| Cross-protobuf-runtime (4 vs 5) source_code_info emission divergence produces different lint findings on different runtimes | U1 verifies byte-identical `source_code_info` emission across protobuf 4 + 5 against both backends (protoxy + protoc) for the same fixture. Divergence resolved or documented before R6 lands. |
| `R9b` deferred again past D6b creates pattern of indefinite deferral with no defined evidence channel | Acknowledged. D6c brainstorm explicitly enumerates the evidence channel that would unblock R9b (e.g., 2+ GitHub issues requesting per-rule disable/enable beyond severity demotion). Same explicit channel for `strict` profile rule enumeration. |

## Assumptions

- Buf's BASIC category remains stable enough that the pinned version's enumeration (17 of 18 rules in D6b's `recommended`; `package/same-directory` documented as deferred) matches D6b's targeted rule set. Verified at `/ce:plan` time by re-running the `buf lint --config '{version: v2, lint: {use: [BASIC]}}'` enumeration against the pinned binary.
- The `descriptor.proto` `FileOptions` fields needed by R7 (`go_package`, `java_package`, `csharp_namespace`, `php_namespace`, `ruby_package`, `swift_prefix`, `java_multiple_files`) are all available on protobuf 4+ runtimes. Verified by inspection: all 7 are core `descriptor.proto` fields, not extensions.
- `DescriptorPool.Add()` discarding `source_code_info` is a stable invariant in protobuf 4 AND 5 (verified by D6a brainstorm second-pass feasibility review for 4; U1's cross-version verification step extends to 5). If protobuf changes this in a future release, R6b becomes redundant but backward-compatible.
- Inline reuse of `_safe_for_stderr` is sufficient defense-in-depth for D6b's one comment-aware rule family (R6) and possibly R7's FileOptions strings (decided at `/ce:plan`). A dedicated `_safe_for_findings` module is deferred until a second consumer with meaningfully different escaping concerns emerges. The threat model (control chars + U+2028/U+2029) is identical to what `_safe_for_stderr` already handles via `_CONTROL_CHAR_TABLE`.
- `leading_comment` as a free function (not mixin method) is the right abstraction for D6b's single consumer family. If a future delivery has 5+ comment-aware rule callers and a mixin method earns its keep on ergonomics, extract then.

## Sources & References

- **Origin brainstorm:** `docs/brainstorms/2026-05-12-protokit-lint-delivery-6a-rule-library-requirements.md` (R6/R6a/R6b were originally in-D6a scope; D6a plan deferred to D6b per J1).
- **D6a plan:** `docs/plans/2026-05-12-001-feat-protokit-lint-d6a-rule-library-plan.md` ("Deferred to Separate Tasks" section enumerates D6b items).
- **TODOS.md** "D6b backlog items surfaced during D6a" — running scope tracker.
- **External:** `https://buf.build/docs/lint/rules` (buf's published BASIC rule enumeration; pin to the version `_BUF_PARITY_PIN` references).

### Institutional learnings applied

- [[pre-1.0-version-bump-as-communication-contract]] — D6b's CHANGELOG section drops the `BREAKING:` prefix; version bump 0.2.0 → 0.3.0 is the signal.
- [[delivery-boundary-unit-commit-composition]] — U7 follows the D6a U10 shape (version bump + CHANGELOG + README + Public Surface DRAFT + sweep + presence ratchets in one commit).
- [[presence-ratchet-test-pattern-for-prose-substrings]] — U7 adds new presence ratchets for the R6 worked-example section in README and the D6b CHANGELOG section.
- [[stale-forward-looking-text-cli-help-agent-discoverability]] — U7 invokes the canonical stale-text sweep with the triage rubric (refreshed at D6a U10).
- [[wire-format-schema-version-bump-contract-and-absence-semantic]] — R9's schema_version bump from `"0.2"` → `"0.3"` follows the bump-trigger contract (new enum-value addition to closed discriminator); the bump-scope clarification distinguishes Literal additions from rule_id additions.
- [[semantic-category-conflation-accepted-tradeoff-literal-widening]] — R9 resolves the U9 KTD-2 deferred decision; the 3-site discipline applies in reverse (the deferred design's three sites all get updated when the split lands).
- [[public-surface-draft-discipline-source-audit]] — R12 follows the audit discipline; new rows are grep-verified against source before shipping. `CompileResult.source_locations` enters as INTERNAL per security-lens review.
- [[audit-wire-format-before-claiming-sibling-parity]] — R7 parity claims (including NULL semantics + canonical-value emit-shape) are audited against the pinned buf version's actual emit before being documented.
- [[buf-parity-divergence-documentation-discipline]] — R6 has no buf analogue (intentional divergence); each of the 5 rule docstrings documents this explicitly.
- [[apply-institutional-learnings-postdating-plan-during-ce-review]] — `/ce:plan` and `/ce:review` apply post-brainstorm institutional learnings at every unit boundary.

### Review history

- **2026-05-14 document-review pass:** 6 personas (coherence + feasibility + product-lens + security-lens + scope-guardian + adversarial). 3 auto-fixes applied (line numbers, R6 precision-not-recall wording, R9 bump scope clarification). 10 priority findings addressed in revisions: R8 → Tier 3 (deferred to D6c), `include_source_info` → opt-in parameter, R6 reframed as 5-rule family + warning severity, R6b → free function + INTERNAL classification, R6c → inline reuse, R7 acknowledges engine accumulator state, multi-language framing softened.

### Next step

`/ce:plan` against this brainstorm, against `docs/plans/2026-05-12-001-feat-protokit-lint-d6a-rule-library-plan.md` as the reference shape, and against `TODOS.md`'s D6b backlog as the running scope tracker.
