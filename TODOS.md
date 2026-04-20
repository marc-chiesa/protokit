# TODOS

Phase-scoped roadmap for protokit. Each entry has **What / Why / Fix
approach (when known) / Effort / Priority / Depends-on / Discovered**.
Items within a phase should generally land before the next phase
starts, but the groupings are intent, not strict gates.

---

## Phase 1 completeness

Gaps surfaced during Phase 1 adversarial review that were deferred
out of scope. Close these on the next branch after merging
`schema-checker` to main — the diff is small and each is independent.

## Phase 1.5b — CI release (formatter system)

CEO-plan accepted-scope items #3 and #4 from
`~/.gstack/projects/python_message_differencer/ceo-plans/2026-04-12-schema-compat-engine.md`:

### Pluggable formatter system + JUnit built-ins — ✅ landed 2026-04-19

Shipped as ``protokit.formatters`` with four ``FormatterKind``
values, ``register_formatter`` / ``load_formatter_pack`` /
``clear_user_formatters`` API, and the CLI's
``--formatter-module`` flag. Built-ins per kind: ``human`` and
``json`` (extracted from the prior CLI rendering); ``junit``
across all four kinds (binary-result for DIFF, per-finding for
the three compat kinds); ``sarif`` for the three compat kinds
(SARIF for DIFF intentionally omitted — diffs don't fit SARIF's
rule/result model). 15 built-ins total.

JUnit output validated against the vendored Apache Ant JUnit
xsd (``tests/fixtures/junit-xml/JUnit.xsd``) — the canonical
reference Jenkins, GitLab, GitHub Actions, CircleCI, and
TeamCity all consume. SARIF output validated against the
vendored OASIS 2.1.0 schema
(``tests/fixtures/sarif/sarif-2.1.0.json``) consumed by GitHub
Code Scanning and GitLab security dashboards.

Built-in names are reserved against ``--formatter-module``
shadowing — a third-party pack can't silently replace the
built-in ``junit`` and let downstream CI consumers ingest
drift. ``--quiet`` mutex was widened to reject every
non-``human`` format (was ``json``-only). Formatter exceptions
fail fast (exit 2 with the formatter name + exception type);
a stdout-write guard catches the contract violation when a
formatter writes directly to stdout instead of returning a
string.

Plan + brainstorm: ``docs/plans/2026-04-18-001-feat-pluggable-formatters-junit-plan.md``
(in repo) ← ``~/.gstack/projects/python_message_differencer/marc-main-brainstorm-phase-1.5b-ci-release-20260418-115400.md`` (gstack).

### Schema diff report (CEO plan item #1) — deferred to Phase 3 docgen

The plan accepted ``Schema diff report (all structural changes,
not just breaking)`` but the ce:brainstorm pressure test
concluded the same descriptor-traversal engine produces
changelogs in Phase 3, so delivering a standalone schema-diff
now would duplicate work. Roll into Phase 3 docgen when
changelogs are built.

### Linting (CEO plan item #2) — deferred to its own brainstorm

The plan accepted ``register_lint_rule`` + ``lint()`` + a
``protokit compat lint`` subcommand. Deferred because (a) the
lint thesis (custom-option-aware Python-native rules) needs
its own product framing distinct from compat checking, and
(b) the descoped form (no inline ``protokit:ignore``, no fix
suggestions) is still phase-sized, not a small follow-up.
Earn the scope via a standalone brainstorm before committing.



## Phase 1.5 — Differ hook system

The schema checker (Phase 1) detects that an option *changed* between
schema versions. This phase adds per-value hooks to the runtime
differ so custom option metadata can drive comparison logic itself.
Full design lives in the approved design doc's "Phase 1.5" section;
the following is a planning summary.

### Implement MessageDifferencer hook pipeline

**What:** Three-stage hook pipeline on ``MessageDifferencer``:

- ``HookStage.VALIDATE`` — pre-compare, flag constraint violations on either side.
- ``HookStage.COMPARE`` — override equality for specific fields.
- ``HookStage.REPORT`` — post-compare, annotate diffs with option-aware context.

Registration API:

```python
differ.register_validate_hook(constraint_checker)
differ.register_compare_hook(custom_equality_override)
differ.register_report_hook(diff_annotator)
differ.register_message_validate_hook(schema_drift_checker)
```

Context objects (``FieldHookContext`` / ``MessageHookContext``) carry both descriptors, both values, both parent messages, both pools, plus ``warn()`` / ``override_equal()`` / ``annotate()`` methods. Engine wires everything through one new ``_compare_field_with_hooks()`` helper; the zero-hooks fast path preserves current performance for all 228 differ tests.

**Why:** Enables option-aware runtime behavior (validate ``validate.rules`` constraints, cross-schema option drift detection, annotation of diffs that cross custom-option boundaries). Complements the schema checker's static option detection.

**Fix approach:** Follow the design doc's "Phase 1.5 Implementation Integration" section verbatim — single new private method, three integration points in ``_compare_leaf`` / ``_compare_repeated`` / ``_compare_map``, optional ``annotations`` field on ``Difference``. Wrap every hook invocation in ``try/except Exception`` with a ``Warning`` on failure (same pattern as schema plugin dispatch).

**Effort:** L (CC: ~90 min including tests)
**Priority:** P1 (this is the committed next-phase work)
**Depends on:** Phase 1 schema checker landed. Benefits from a shared ``protokit.options.get_option_value`` helper (see below).
**Discovered:** 2026-04-06 original design doc

---

### Shared `protokit.options` module for plugin/hook option access

**What:** A small shared module housing ``get_option_value(fd, option_path, pool=None)`` with tiered fallback: ``Extensions[]`` first (protoc-compiled descriptor sets), then ``uninterpreted_option`` parsing (always available), then ``None``.

**Why:** Both schema plugins and differ hooks need to read custom options from descriptors. Today the schema checker has no helper and plugin authors reinvent it; Phase 1.5 hooks will need the same thing. Putting it in one place avoids drift.

**Effort:** S (CC: ~15 min)
**Priority:** P2
**Depends on:** Nothing. Could even land before Phase 1.5 starts.
**Discovered:** 2026-04-06 design doc

---

## Phase 2 — Git-integrated schema evolution

Makes the checker git-aware: discover schema versions from commit
history, compare consecutive revisions, bisect for the first
breaking commit, gate CI on merge-base.

### Protoc replacement via protoxy (Rust bindings) — ✅ landed 2026-04-14

Shipped as an optional backend in ``_cli_utils.compile_proto`` via
``pip install protokit[compiler]``. Also required a protobuf 5.x
compatibility pass (added ``is_repeated`` / ``is_required``
helpers in ``protokit._descriptors``).

---

## Phase 3 — Ecosystem plays

Each is independent and can parallelize. Priority ordering within
Phase 3 depends on which ecosystem pain the builder hits first.

### Proto source parser integration (proto-schema-parser)

**What:** Integrate [proto-schema-parser](https://github.com/criccomini/proto-schema-parser) (`pip install proto-schema-parser`) for `.proto` source-level manipulation. Pure Python, ANTLR-based, uses buf's grammar. Parses `.proto` → AST and generates AST → `.proto` text (round-trip).

**Why:** Unlocks auto-fix for lint findings. Currently lint can only suggest fixes as text. With a source parser, the engine can apply fixes to the AST and write corrected `.proto` files. Also enables source-level analysis (comment extraction, formatting checks) without `source_code_info`.

**Effort:** M (CC: ~30 min to integrate + build fix-apply pipeline)
**Priority:** P2
**Depends on:** Phase 1 linting must exist first (not yet scoped — separate effort).
**Discovered:** 2026-04-12 CEO review, web search

---

### Inline rule suppression via `protokit:ignore` comments

**What:** Parse proto source comments for `protokit:ignore <rule_id>` directives. Suppress specific rules on specific fields/messages. Requires `--include_source_info` on descriptor compilation. Alternative: use proto-schema-parser to read comments directly from `.proto` source.

**Why:** The `# noqa` equivalent for proto schemas. Users want to silence specific warnings on specific fields without disabling rules globally.

**Effort:** M (CC: ~30 min)
**Priority:** P2
**Depends on:** Phase 1 linting (core lint must exist first). May benefit from proto-schema-parser integration (alternative to source_code_info).
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

### pytest integration for schema compatibility checks — ✅ landed 2026-04-14

Shipped as ``protokit.schema.pytest_plugin`` with ``schema_checker``
/ ``schema_policy`` fixtures and ``assert_compatible`` helper.
Users opt in by importing the plugin in ``conftest.py`` (matches
the ``protokit.message.pytest_plugin`` pattern). Cross-type
comparison works since the fixture returns a fresh
``SchemaChecker`` the user calls directly.

---

### CompatibilityPolicy supporting message plugins — ✅ landed 2026-04-14

Shipped as ``CompatibilityPolicy.message_rules``. Tuple-frozen
in ``__post_init__`` alongside ``custom_rules`` /
``ignore_paths``; ``check()`` loops and calls
``register_message_rule`` on the fresh ``SchemaChecker``.

---

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
