# TODOS

Phase-scoped roadmap for protokit. Each entry has **What / Why / Fix
approach (when known) / Effort / Priority / Depends-on / Discovered**.
Items within a phase should generally land before the next phase
starts, but the groupings are intent, not strict gates.

Completed phases (1, 1.5, 2, 1.5b) and protokit-lint Deliveries 1
(foundation, 2026-05-02), 2 (engine + canary, 2026-05-03), and 3
(`protokit lint` CLI subcommand, 2026-05-09) are not listed here
— see `CHANGELOG.md` and git history. D4 (formatters) was
absorbed into D3 U4a/U4b and shipped with D3. D5–D7 are still
ahead and tracked in their own section below.

---

## Phase 1.5b — CI release (formatter system)

Pluggable formatter system + JUnit/SARIF built-ins (CEO #3+#4)
landed 2026-04-19. Remaining items from that brainstorm below.

### Schema diff report (CEO plan item #1) — deferred to Phase 3 docgen

The plan accepted ``Schema diff report (all structural changes,
not just breaking)`` but the ce:brainstorm pressure test
concluded the same descriptor-traversal engine produces
changelogs in Phase 3, so delivering a standalone schema-diff
now would duplicate work. Roll into Phase 3 docgen when
changelogs are built.

### Unify CLI diagnostic output through ``logging``

**What:** protokit's internal diagnostic paths currently emit
via ``click.echo(f"...", err=True)`` — writes land on stderr,
which is correct, but the pattern is ad-hoc and doesn't give
embedding callers a way to route diagnostics through standard
Python ``logging`` config.

Phase 1.5b recommended ``logging`` to third-party formatter
pack authors (see README "Diagnostics from a custom formatter"
section and the ``FORMATTER_LOG_NAMESPACE`` constant). For
consistency, protokit's own diagnostic callsites in
``schema/cli.py`` (``_run_check_pipeline``, history and bisect
loops), ``_cli_utils.error_exit``, and ``message/cli.py``
should route through ``logging`` too — sub-loggers under a
top-level ``protokit`` namespace.

**Why:** Embeddable-library story (external callers can
redirect via ``logging.config``); coherent pattern with the
recommendation we give pack authors; unlocks a trivial
``--log-level`` / ``--verbose`` flag addition later.

**Fix approach:**
- Introduce ``protokit._log`` module exposing a ``logger =
  logging.getLogger("protokit")`` and convenience wrappers for
  ``error_exit``-style fatal path.
- Map existing prefixes: ``click.echo("Error: ...", err=True)`` →
  ``logger.error("...")`` (plus ``sys.exit(2)``).
- Preserve the current wall-clock-free plain-text format so
  existing stderr snapshot assertions don't churn (use a
  minimal formatter without timestamps/level prefixes by
  default; gate richer formatting behind a future
  ``--log-format`` flag).
- Update ``tests/schema/test_cli.py`` and ``tests/test_cli.py``
  assertions that grep stderr content. The ``caplog`` fixture
  is the standard pattern; Click's ``CliRunner`` captures
  stderr separately.

**Effort:** M (CC: ~45 min — 50+ callsites + test updates).
**Priority:** P3 — consistency win, not a correctness fix.
Ship if/when we add ``--verbose`` or ``--log-level``.
**Depends on:** Phase 1.5b (``FORMATTER_LOG_NAMESPACE`` already
in place).
**Discovered:** 2026-04-19 ce:review residual / design
discussion around the stdout-write guard.

---

## protokit-lint — remaining deliveries (D6c, D7)

D1 (foundation, 2026-05-02), D2 (engine + canary, 2026-05-03), and
D3 (`protokit lint` CLI subcommand, 2026-05-09) all landed. D4
(formatters / `_builtin_lint.py`) was absorbed into D3 U4a/U4b and
shipped with D3 — `lint_human` / `lint_json` / `lint_junit` /
`lint_sarif` are all registered. D5 (pyproject `[tool.protokit.lint]`
config + `--exclude`, 2026-05-11/12) landed. **D6a (rule library
+ buf BASIC parity, 0.2.0 release, 2026-05-13)** landed.
**D6b (option-aware path + cross-language buf BASIC parity, 0.3.0
release, 2026-05-18)** landed across U1+U2+U3+U4a+U4b+U5+U6+U7.
**D6c (cross-file lint dispatch + 25/26 buf BASIC parity, 0.4.0
release, 2026-05-19)** landed across U1+U2+U3+U4+U5.

`protokit lint <inputs>` covers **25 of 26 buf BASIC rules** as of
0.4.0: 6 packs / 26 rules in the `recommended` profile (`naming` /
`enum` / `imports` / `package` (4 rules incl. R8 + R8b) / `file` /
`package_same`), +5 R6 deprecated-replacement rules in `default`.
The "17 of 18" framing inherited from D6a/D6b was empirically
corrected at D6c against a verified buf BASIC total of 26 rules;
see the D6c CHANGELOG `#### Corrected` subsection for the audit
trail. Per-rule severity overrides + `--no-builtin-rules` + the
5-path pre-upgrade migration recipe in CHANGELOG provide demotion
paths (path 5 covers Python API consumers via
`LintProfile.rule_severity_overrides`); `lint_json` / `lint_sarif`
carry a `schema_version` wire field at `"0.3"` (unchanged by D6c
since R8 + R8b are pure rule_id additions). The remaining
sub-deliveries fill in scope deliberately deferred from D6c:
**D6d** ships `PACKAGE_NO_IMPORT_CYCLE` (the 26th buf BASIC rule —
needs cross-file cycle-detection algorithm; not amenable to the
Arch-D accumulator pattern) + `FIELD_NOT_REQUIRED` (proto2-only,
not counted in the 26-rule baseline) + the `strict` profile + R9b
per-rule disable/enable CLI flag + option-aware pack expansion,
and **D7** closes the plugin-API story.

### D5 — pyproject `[tool.protokit.lint]` config + `--exclude` *(SHIPPED 2026-05-11/12)*

**What:** Read `[tool.protokit.lint]` from `pyproject.toml`:
profile selection, rule overrides, exclude globs. Adds `tomli` to
required deps (Python 3.10 lacks `tomllib`; 3.11+ has it). Includes
the `tests/schema/lint/test_perf_smoke.py` measurement that A5
deferred from D1. Folded in:

- R12's `LintRuntimeWarning(category="min_severity_relaxed")` emission
  — D3 R12 deferred this to "next delivery (pyproject config)"; D5
  shipped it.
- R17 `--ignore PATH` flag — D3 R17 was explicitly deferred to D5
  ("co-design with `[tool.protokit.lint] exclude` globs") and
  shipped as `--exclude`.

**Why:** Per-project config is how every other lint tool ships.
Without it, every CLI invocation needs explicit flags.

**Status:** Shipped across D5 U1–U6 between 2026-05-11 and
2026-05-12.

---

### D6 — Rule packs (built-in rules beyond the canary)

**Status:** D6a (rule library + buf BASIC parity) shipped
2026-05-13 as protokit 0.2.0; see CHANGELOG `### D6a` for the
auto-load expansion + demotion paths. **D6b (option-aware path +
cross-language buf BASIC parity) shipped 2026-05-18 as protokit
0.3.0**; see CHANGELOG `### D6b` for the auto-load expansion + the
4-path pre-upgrade migration recipe. D6c remains open (backlog
below).

**What:** First concrete rules library. The brainstorm references
AIP-style naming / linting (`naming/snake-case-fields` is the
canary that ships with D1; `naming/upper-camel-messages`,
`enum/zero-default-required`, and the rest of the AIP-122 family
land here). Rule packs land grouped by category, each with their
own `LintRuleSpec` registration.

The path forward (R7 from D3): D6 ships with a second built-in
pack so `--no-builtin-rules` becomes a non-trivial flag (D3
deferred R7 because "admitted-zero user value with one canary";
two packs unblocks it).

**Why:** Foundation isn't useful without rules to fire. This is
where the lint thesis (custom-option-aware Python-native rules)
becomes a product. After D6 ships, `protokit lint` produces
genuinely useful output on real proto schemas, not just the
canary.

**Sub-discipline — per-rule parity tests against industry tools:**
Each rule landing in D6 with a clear analogue in `buf lint`,
`protolint`, or Google's `api-linter` should ship with a parity
fixture: same `.proto` input piped through both protokit and the
analogue tool, asserting verdict equivalence on the agreed
surface. Rules without analogues (e.g., custom-option-aware
rules that only protokit supports) don't owe anyone parity.
Pay-as-you-go discipline like the static-analysis ratchet —
grows incrementally as each rule lands, not as a separate
delivery. Standalone audit work belongs in the Phase 3
"Cross-tool parity audit" entry below.

**Effort:** L (depends on rule scope). **Priority:** P1.
**Depends on:** D2 + D3 (both landed). **Discovered:**
brainstorm steps 7–8; parity sub-discipline added 2026-05-09.

**D6b backlog (resolved in 0.3.0 release 2026-05-18):**

- **`severities_unloaded_rule` category split**: Shipped in D6b
  0.3.0 (U5, 2026-05-17). Closed the D6a U9 KTD-2 accepted-
  conflation trip-wire; consumers now switch on `category` directly.
  Schema_version bumped 0.2 → 0.3 as the consumer-facing wire-format
  signal.
- **Cross-language `PACKAGE_SAME_*` rule family**: Shipped in D6b
  0.3.0 across U4a + U4b + U6 + U7 (2026-05-17/18). 7 rules
  (CSHARP_NAMESPACE, GO_PACKAGE, JAVA_MULTIPLE_FILES, JAVA_PACKAGE,
  PHP_NAMESPACE, RUBY_PACKAGE, SWIFT_PREFIX) default-on under
  `recommended` + `default` profiles. Empirical parity gate against
  21 buf v1.69.0 NDJSON snapshots. (D6b shipped 23 of 26 buf BASIC
  rules; the inherited "17 of 18" framing was corrected at D6c.)
- **Cross-file lint dispatch (R8 + R8b)**: Shipped in D6c 0.4.0
  across U1-U5 (2026-05-19). Arch-D pre-walk accumulator
  (`LintEngine._build_directory_package_accumulator` + dual-view
  `FileLintContext.directory_packages` / `directory_packages_by_dir`)
  + R8 `package/same-directory` + R8b
  `package/directory-same-package` (with 3 message-template arms
  discriminating standard / empty-mixed-single / empty-mixed-multi
  per buf v1.69.0 byte-parity). 10-fixture empirical parity gate at
  `tests/parity/test_parity_package_directory.py`. Brings protokit
  lint to 25 of 26 buf BASIC rules.
- **Option-aware differentiator path** (R6 family): Shipped in D6b
  0.3.0 (U3a, 2026-05-15). 5 deprecated-replacement rules in
  `default` profile at `warning` severity; first leading-comment-
  introspection consumer via `leading_comment(source_info_descriptors,
  file_name, path)` free function. `CompileResult.source_info_descriptors`
  (the renamed-from-`source_locations` index) landed at U2 and is
  classified INTERNAL in the Public Surface DRAFT.

**D6d backlog items deferred from D6c:**

- **`PACKAGE_NO_IMPORT_CYCLE` (26th buf BASIC rule)**: deferred to
  D6d — cross-file cycle-detection algorithm (DAG construction +
  cycle detection); not amenable to the Arch-D accumulator pattern
  established in D6c. Brainstorm Verification Step 5 records the
  empirical investigation that unblocks D6d planning.
- **`FIELD_NOT_REQUIRED` (proto2-only BASIC rule, not counted in
  the 26-rule baseline)**: deferred to D6d alongside — trivial
  single-unit add via existing `ElementKind.FIELD` check
  (`field.label == LABEL_REQUIRED`).
- **R9b — per-rule disable/enable CLI flag** (`disabled_rules` /
  `enabled_rules` pyproject lists): deferred from D6a + D6b per
  the brainstorms; needs real-demand evidence to design the 4
  collision-shape precedence semantics against. Note that
  `[tool.protokit.lint.severities] "rule_id" = "off"` is the
  current de-facto disable mechanism documented in CHANGELOG.
- **`strict` profile**: deferred from D6a + D6b until strict-only
  rules exist (COMMENT_* family, ENUM_ZERO_VALUE_SUFFIX, etc.) —
  shipping `strict` empty would damage the public surface with a
  misleading rule count. R7's placement in `recommended` (rather
  than a future `strict`) was a deliberate D6b decision per KD-10;
  if PyPI download data shows >70% pin-to-0.2.x adoption pattern,
  revisit R7 placement in 0.4.0.
- **R6 severity promotion to `error`**: D6b shipped R6 at `warning`
  to bound the leading-comment-regex heuristic blast radius;
  promotion to `error` pending real-world experience.

---

### D7 — Plugin API + `--compat-rule-pack` rename

**What:** Closes the cross-CLI symmetric naming gap. D3 already
shipped `--rule-pack` for `protokit lint` (R8). The remaining
work is renaming compat's existing `--formatter-module` and
`--rule-pack` flags to `--compat-rule-pack` for naming
consistency, plus formalizing the plugin-API documentation in
the README.

**Why:** With both CLIs taking `--rule-pack`-shaped flags, users
get a coherent third-party-pack story. The rename is the only
remaining surface; the underlying loading machinery already exists
on both sides (with full sibling-parity hardening per the U5
ce:review).

**Effort:** S–M (rename + deprecation aliases + doc updates).
**Priority:** P2.
**Depends on:** D3 (landed). **Discovered:** brainstorm step 9.

---

### Static-analysis cleanup (incremental)

**What:** Pay-as-you-touch ratchet pattern keeps growing —
`tests/test_static_analysis.py:_LINT_PATHS` and `_TYPE_CHECK_PATHS`
add files as feature work touches them. Pre-D3 modules
(`src/protokit/message/`, older `src/protokit/schema/*.py`,
`src/protokit/formatters/_builtin_compat.py` /
`_builtin_diff.py`, plus their test files) sit outside the
ratchet and carry pre-existing static-analysis errors.

**Why:** Discipline pattern from
`docs/solutions/best-practices/pytest-static-analysis-gate-ratchet-2026-05-02.md`.
Big-bang remediation is explicitly NOT the answer; touch a file,
clean it, ratchet it.

**Fix approach:** See `docs/brainstorms/2026-05-08-static-analysis-cleanup-scope.md`
for the scoped approach when this becomes a deliberate cleanup
pass instead of an incidental discipline.

**Effort:** Continuous. **Priority:** low (not blocking).
**Depends on:** none. **Discovered:** 2026-05-08 brainstorm.

---

## Phase 3 — Ecosystem plays

Each is independent and can parallelize. Priority ordering within
Phase 3 depends on which ecosystem pain the builder hits first.

### Proto source parser integration (proto-schema-parser)

**What:** Integrate [proto-schema-parser](https://github.com/criccomini/proto-schema-parser) (`pip install proto-schema-parser`) for `.proto` source-level manipulation. Pure Python, ANTLR-based, uses buf's grammar. Parses `.proto` → AST and generates AST → `.proto` text (round-trip).

**Why:** Unlocks auto-fix for lint findings. Currently lint can only suggest fixes as text. With a source parser, the engine can apply fixes to the AST and write corrected `.proto` files. Also enables source-level analysis (comment extraction, formatting checks) without `source_code_info`.

**Effort:** M (CC: ~30 min to integrate + build fix-apply pipeline)
**Priority:** P2
**Depends on:** lint D2 (engine) — D1 foundation landed but the
fix-apply pipeline needs the engine producing findings.
**Discovered:** 2026-04-12 CEO review, web search

---

### Inline rule suppression via `protokit:ignore` comments

**What:** Parse proto source comments for `protokit:ignore <rule_id>` directives. Suppress specific rules on specific fields/messages. Requires `--include_source_info` on descriptor compilation. Alternative: use proto-schema-parser to read comments directly from `.proto` source.

**Why:** The `# noqa` equivalent for proto schemas. Users want to silence specific warnings on specific fields without disabling rules globally.

**Effort:** M (CC: ~30 min)
**Priority:** P2
**Depends on:** lint D2 (engine). May benefit from proto-schema-parser integration (alternative to source_code_info).
**Discovered:** 2026-04-12 CEO review, descoped per outside voice

---

### Proto documentation generator

**What:** Generate human-readable docs from proto descriptors. Versioned docs per git tag. Changelogs between schema versions. Custom filters (hide deprecated, hide internal). `doc-diff` and `doc-history` commands.

**Why:** Completes the "proto toolkit" vision. Natural Phase 3 after git integration (Phase 2) proves out.

**Effort:** L (CC: ~60 min)
**Priority:** P3
**Depends on:** Phase 1 (descriptor traversal) + Phase 2 (git ref extraction)
**Discovered:** 2026-04-12 office hours

---

### Cross-tool parity audit (lint + compat)

**What:** Standalone delivery that runs `protokit lint` and
`protokit compat` against the public test corpora of established
proto tools and produces a verdict-diff report. Three target tools,
in priority order:

- **buf** (`buf lint` + `buf breaking`) — dominant industry tool;
  required for credibility. Go binary; CI installs via `go install`
  or downloads the release archive.
- **protolint** — pure-Go, AIP-aligned; smaller rule surface, easier
  to install, fewer opinionated divergences.
- **Google's api-linter** — AIP-122 specifically; relevant for any
  AIP-style rules in D6.

Output: a markdown report listing (rule, fixture, protokit verdict,
peer-tool verdict, agree/diverge, divergence reason). Diverge cases
are not failures — some are intentional design choices on either
side; others are bugs in either tool. The report is the input to a
human review, not a CI gate.

**Why:** Per-rule parity tests in D6 are pay-as-you-go and prove
each rule individually. This standalone audit catches the
emergent-cross-rule behavior — e.g., when buf and protokit both
fire on the same fixture but with different severities, or when
one tool's verdict depends on rule-interaction order. Also
surfaces edge cases neither tool's own tests catch (running buf's
test corpus through protokit and vice versa is the cheapest way
to find divergent behavior on real-world proto schemas).

Bonus: produces a credibility artifact ("audited against buf X.Y,
protolint Z, api-linter W on N fixtures") that's useful for
README + release notes.

**Boundaries:** This is NOT "achieve full parity with buf." Buf
has a much larger rule set and some opinionated decisions
protokit may want to diverge from intentionally. The audit
report's job is to *characterize* the divergence, not eliminate
it.

**Effort:** M-L (CI tooling install + corpus runner +
verdict-diff report generation; ~half a day initial, then
maintenance per peer-tool release).
**Priority:** P2.
**Depends on:** D6 (at least one rule pack with industry
analogues — meaningless audit when only the canary fires).
**Discovered:** 2026-05-09 user question after D3 ship.

---

## Developer experience

Orthogonal polish items. Schedule when they're painful enough to
matter; none block other phases.

### Async plugin support via `check_async()`

**What:** Add an ``async def check_async(...)`` alongside the sync ``check()`` that awaits async-def plugins natively instead of rejecting them. Library users running inside an event loop (FastAPI, Jupyter, pytest-asyncio) could then run I/O-bound rules directly without the pre-fetch / post-process dance.

**Why:** The pre-fetch pattern covers the 95% case and the rejection-at-registration keeps the sync path honest, but a first-class async entry point is the clean answer for users doing schema registry lookups, LLM-classified rules, or async telemetry in-plugin.

**Fix approach:** Separate code path that mirrors ``_traverse`` / ``_compare_fields`` / ``_dispatch_*_plugin`` in async form. Shared rule-evaluation logic factored out. Does not change sync ``check()`` behavior.

**Effort:** L (CC: ~60 min — doubling the engine's traversal surface)
**Priority:** P3 — ship only if real user demand appears, not on speculation.
**Depends on:** Phase 1 stable. Could ride on a broader async-first refactor if one is planned.
**Discovered:** 2026-04-13 user question during round-3 review.

---

## Design Decision Log

Records irreversible design calls made during Phase 1 so we don't re-litigate them.

### 2026-04-13 — Resolve design-doc Open Question #1: type-name changes

**Decision:** Add a 17th built-in rule `field_type_name_changed` at POLICY / BOTH. Fires when a `TYPE_MESSAGE` or `TYPE_ENUM` field points at a differently-named type on each side, *regardless* of whether the two types have the same shape.

**Why:** Without this rule, `status: OldStatus → NewStatus` reports clean when both enums share the same names/numbers — but downstream code that imports `OldStatus` breaks immediately. The design doc called this out as Open Question #1 and never answered it.

**Severity/direction rationale:**
- POLICY because wire format and value semantics are unaffected when the replacement type has the same shape; this is a source-level identity concern.
- BOTH because both producers and consumers may have code paths that depend on the type name.
- Only surfaces under STRICT by default, so teams that intentionally rename their types don't get noise at lower profiles.

---

### 2026-04-13 — Direction semantics: compat-risk framing

**Decision:** `Direction.FORWARD` and `Direction.BACKWARD` describe **which reader is at risk**, not which side of the schema changed.

- `BACKWARD` = old consumer fails / misinterprets **new** data (breaks forward compatibility).
- `FORWARD` = new consumer fails / misinterprets **old** data (breaks backward compatibility).
- `BOTH` = affects both readers (typically wire-format breaks).

**Why:** Aligns profile names with what they filter. `CONSUMER_SAFE` = BACKWARD + BOTH truly protects old consumers, and `PRODUCER_SAFE` = FORWARD + BOTH truly protects against old producers. The prior "direction of change" framing had `CONSUMER_SAFE` filtering out `enum_value_added` and `oneof_field_added` — exactly the kinds of additions that break exhaustive-match code in old consumers.

**Reclassified from the original design doc:**
- `field_added`: FORWARD → **BACKWARD**
- `oneof_field_added`: FORWARD → **BACKWARD**
- `enum_value_added`: FORWARD → **BACKWARD**
- `enum_value_removed`: BACKWARD → **FORWARD**
- `required_field_added`: BACKWARD → **FORWARD** (already corrected earlier in review)

`field_removed` stays BACKWARD (old consumer misses it in new data). All `BOTH` rules are unchanged.

**Source:** Codex adversarial review flagged the inconsistency. Design doc's own terminology mapping (`"Forward compatible" = no BACKWARD findings`) already implied compat-risk framing; the rule table was the bug.

---

### 2026-04-13 — Plugin failures fail-closed via `report.warnings`

**Decision:** Plugin exceptions, emit-validation errors, and async-plugin misuse are captured into ``CompatibilityReport.warnings`` — a ``tuple[Warning, ...]`` on the report. ``warnings.warn()`` is NOT called. The ``protokit compat`` CLI exits with code 2 when any warnings are present, even if the filtered report is technically COMPATIBLE.

**Why:** A broken custom policy that should have caught a break must not silently pass CI. The initial implementation emitted both a Python ``UserWarning`` and a report entry, which double-printed on the CLI and had confused stacklevel attribution. Single source of truth keeps output clean and makes the fail-closed guarantee explicit.

**Bridge for library users:** If you want Python's warnings subsystem integration after ``check()`` returns, iterate ``report.warnings`` and call ``warnings.warn(w.message)`` yourself.

**Source:** Codex round-1 flagged fail-open; round-2 fixed it but added double-output; round-3 consolidated to the single-source-of-truth design.
