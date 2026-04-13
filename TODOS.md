# TODOS

## Proto Source Parser Integration (proto-schema-parser)

**What:** Integrate [proto-schema-parser](https://github.com/criccomini/proto-schema-parser) (`pip install proto-schema-parser`) for `.proto` source-level manipulation. Pure Python, ANTLR-based, uses buf's grammar. Parses `.proto` → AST and generates AST → `.proto` text (round-trip).

**Why:** Unlocks auto-fix for lint findings. Currently lint can only suggest fixes as text. With a source parser, the engine can apply fixes to the AST and write corrected `.proto` files. Also enables source-level analysis (comment extraction, formatting checks) without `source_code_info`.

**Effort:** M (CC: ~30 min to integrate + build fix-apply pipeline)
**Priority:** P2
**Depends on:** Phase 1 linting must exist first
**Discovered:** 2026-04-12 CEO review, web search

---

## Protoc Replacement via protoxy (Rust bindings)

**What:** Use [protoxy](https://pypi.org/project/protoxy/) (`pip install protoxy`) as an optional protoc replacement. Python bindings for the Rust `protox` compiler. Compiles `.proto` files to `FileDescriptorSet` without requiring protoc on PATH.

**Why:** Removes the external `protoc` dependency for `.proto` compilation. Faster than protoc, no scalability issues. Makes Phase 2 git integration work without any external tools. Could be an optional dependency: `pip install proto-differ[compiler]`.

**Effort:** S (CC: ~15 min to add as optional backend in `_compile_proto`)
**Priority:** P2
**Depends on:** Phase 1 CLI (reuses `_compile_proto` path)
**Discovered:** 2026-04-12 CEO review, web search

---

## Proto Documentation Generator (Phase 3)

**What:** Generate human-readable docs from proto descriptors. Versioned docs per git tag. Changelogs between schema versions. Custom filters (hide deprecated, hide internal). `doc-diff` and `doc-history` commands.

**Why:** Completes the "proto toolkit" vision. Natural Phase 3 after git integration (Phase 2) proves out.

**Effort:** L (CC: ~60 min)
**Priority:** P3
**Depends on:** Phase 1 (descriptor traversal) + Phase 2 (git ref extraction)
**Discovered:** 2026-04-12 office hours

---

## Inline Rule Suppression via source_code_info

**What:** Parse proto source comments for `proto-differ:ignore <rule_id>` directives. Suppress specific rules on specific fields/messages. Requires `--include_source_info` on descriptor compilation. Alternative: use proto-schema-parser to read comments directly from `.proto` source.

**Why:** The `# noqa` equivalent for proto schemas. Users want to silence specific warnings on specific fields without disabling rules globally.

**Effort:** M (CC: ~30 min)
**Priority:** P2
**Depends on:** Phase 1 linting (core lint must exist first). May benefit from proto-schema-parser integration (alternative to source_code_info).
**Discovered:** 2026-04-12 CEO review, descoped per outside voice

---

## pytest Integration for Schema Compatibility Checks

**What:** pytest marker (`@pytest.mark.schema_compat`) + fixture (`schema_checker`) for running compatibility checks in test suites. Supports cross-type comparison (old_type != new_type for renamed/moved messages).

**Why:** Same pytest-first developer experience as the existing message differ plugin.

**Effort:** S (CC: ~15 min)
**Priority:** P2
**Depends on:** Phase 1 core API must be stable first
**Discovered:** 2026-04-12 CEO review, deferred per outside voice
