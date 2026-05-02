# TODOS

Phase-scoped roadmap for protokit. Each entry has **What / Why / Fix
approach (when known) / Effort / Priority / Depends-on / Discovered**.
Items within a phase should generally land before the next phase
starts, but the groupings are intent, not strict gates.

Completed phases (1, 1.5, 2, 1.5b) and protokit-lint Delivery 1
(foundation, 2026-05-02) are not listed here — see `CHANGELOG.md`
and git history. Lint deliveries 2–7 are still ahead and tracked
in their own section below.

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

## protokit-lint — deliveries 2–7

D1 (foundation) landed 2026-05-02 (commits `0b82fc3`, `e85faea`,
`31c0bb1`). The locked types live in `src/protokit/schema/lint/model.py`
and `src/protokit/schema/compile.py`; helpers in
`src/protokit/_cli_utils.py`. Six deliveries remain, sequenced per
`docs/brainstorms/2026-04-30-protokit-lint-delivery-1-foundation-requirements.md`
"Out of Scope" section.

### D2 — Engine implementation

**What:** `@lint_rule` decorator and `LintEngine`. Consumes the
locked `LintRuleSpec` / `LintFinding` / `_LintContextEmitMixin`
types from D1; walks the descriptor tree and dispatches per
`ElementKind`. Closes the loop on `_emit_fn` injection (currently
declared on every context but never invoked end-to-end).

**Why:** First delivery that produces actual lint output. Every
later delivery (CLI, formatters, config, rule packs, plugin API)
sits on top of this engine.

**Effort:** L. **Priority:** P1 (next in sequence).
**Depends on:** D1 (landed). **Discovered:** brainstorm step 3.

---

### D3 — `protokit lint` CLI subcommand

**What:** First user-visible lint surface. Mirrors the shape of
`protokit compat`: positional descriptor-set / `--proto` source
inputs, `--profile`, `--rule-pack`, `--format`, `--quiet`, exit
codes (0 clean / 1 findings / 2 diagnostics).

**Why:** Without a CLI, lint findings only surface from library
calls. The CLI is the dogfood path and the gate for D4 formatters.

**Effort:** M. **Priority:** P1.
**Depends on:** D2. **Discovered:** brainstorm step 4.

---

### D4 — Formatters / `_builtin_lint.py`

**What:** Register `_builtin_lint` formatters into the existing
formatter system. Four `FormatterKind`-equivalent shapes for
`LintReport` (human / json / junit / sarif). The
`protokit/formatters/__init__.py` eager-load block must NOT
register `_builtin_lint` until this delivery (codex P0 finding
LINT-DESIGN-COLD-IMPORT-FORMATTERS); D1 deliberately did not touch
that file.

**Why:** Same machine-readable pipeline as compat (CI gates,
SARIF for code-scanning).

**Effort:** M. **Priority:** P1.
**Depends on:** D2 (engine produces `LintReport`).
**Discovered:** brainstorm step 5.

---

### D5 — pyproject `[tool.protokit.lint]` config + `--exclude`

**What:** Read `[tool.protokit.lint]` from `pyproject.toml`:
profile selection, rule overrides, exclude globs. Adds `tomli` to
required deps (Python 3.10 lacks `tomllib`; 3.11+ has it). Includes
the `tests/schema/lint/test_perf_smoke.py` measurement that A5
deferred from D1.

**Why:** Per-project config is how every other lint tool ships.
Without it, every CLI invocation needs explicit flags.

**Effort:** M. **Priority:** P2.
**Depends on:** D3 (CLI exists to read the config).
**Discovered:** brainstorm step 6.

---

### D6 — Rule packs (built-in rules)

**What:** First concrete rules. The brainstorm references AIP-style
naming / linting (e.g., `naming/snake-case-fields`,
`naming/upper-camel-messages`, `enum/zero-default-required`). Rule
packs land grouped by category, each with their own
`LintRuleSpec` registration.

**Why:** Foundation isn't useful without rules to fire. This is
where the lint thesis (custom-option-aware Python-native rules)
becomes a product.

**Effort:** L (depends on rule scope). **Priority:** P2.
**Depends on:** D2 + D3 + D4. **Discovered:** brainstorm steps 7–8.

---

### D7 — Plugin API + `--lint-rule-pack` / `--compat-rule-pack` flags

**What:** External-pack registration parity with the compat
plugin API. Symmetric `--lint-rule-pack <module>` flag plus
matching `--compat-rule-pack` for naming consistency.

**Why:** Closes the third-party-pack story. Compat already supports
`--rule-pack`; lint should too.

**Effort:** M. **Priority:** P2.
**Depends on:** D2 + D3. **Discovered:** brainstorm step 9.

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
