---
title: "Document both the bump contract and the field-absence semantic when introducing a wire-format schema_version"
date: 2026-05-13
last_updated: 2026-05-17
category: docs/solutions/best-practices
module: src/protokit/formatters/_builtin_lint.py
problem_type: best_practice
component: tooling
severity: medium
applies_when:
  - "A new ``schema_version``-style field is being introduced to an existing wire-format output (JSON, SARIF, YAML, etc.) for the first time"
  - "Pre-introduction output exists in the wild — older binaries are already shipped, installed in CI, or cached in artifact stores — so consumers will see output WITHOUT the new field"
  - "The versioning scheme uses a string constant (e.g., ``\"0.2\"``) with a documented increment policy"
  - "Two or more sibling formatters carry the same version signal under structurally different key paths (e.g., JSON top-level ``schema_version`` vs SARIF ``runs[].properties.lint_schema_version``)"
  - "Consumers may switch on the version field to route parsing logic and must have a defined fallback for a missing field"
tags:
  - wire-format
  - schema-version
  - api-contract
  - absence-semantic
  - forward-compatible
  - bump-contract
  - lint-json
  - sarif
---

# Document both the bump contract and the field-absence semantic when introducing a wire-format schema_version

## Context

D6a Unit 9 introduced ``_LINT_JSON_SCHEMA_VERSION = "0.2"`` — the
first wire-format schema_version field in protokit. It surfaces in
two sibling formatters: ``lint_json`` carries the value at top level
under ``schema_version``, and ``lint_sarif`` carries it under
``runs[0].properties.lint_schema_version`` (the key is namespaced
to avoid collision with SARIF's own reserved ``schema`` property,
but the value is identical per the
[[cross-format-enum-string-parity-2026-05-08]] discipline).

The initial Unit 9 commit (``c7a426b``) documented only when to
bump the version — "(a) addition of new top-level keys, (b) change
in meaning of an existing field, (c) removal of a previously
documented field; enum-value additions don't bump". The api-contract
reviewer caught a P1 gap (confidence 0.82): the constant did NOT
document what an absent ``schema_version`` key means. Pre-Unit-9
output emits no key at all. A consumer that switches on
``payload.get("schema_version")`` sees ``None`` for old output and
``"0.2"`` for new output — and has no contract telling it whether
``None`` means "older version" or "malformed response".

The ce:review follow-up commit (``3c828a4``) added the field-absent
semantic to the constant's docstring as an explicit clause:
**absence = implicit ``"0.1"`` = one bump below the first documented
value; consumers should treat it as a known-older release, NOT as an
error**. Without this clause the consumer contract is unspecified
and downstream parsers must guess.

## Guidance

**When introducing a ``schema_version`` field to a wire-format
output for the first time, document BOTH the bump contract AND
the field-absence semantic on the module-level constant that
holds the version string. The constant is the single source of
truth; formatter-level inline comments collapse to one-line
pointers to the constant.**

The dual-clause structure exists because the two questions are
inseparable:

1. **Bump contract** — "When should I increment?" Without a written
   policy, contributors will either bump unnecessarily (e.g., on
   enum-value additions to an existing field) or forget to bump
   when they should (meaning changes, field removals).
2. **Field-absence semantic** — "What does ``None`` mean?" Pre-
   introduction output is in the wild. Consumers MUST be told
   whether absence = "known-older release" or "malformed
   response". Choosing "implicit ``0.1``" — one bump below the
   first documented value — gives consumers a well-formed
   comparison value rather than special-casing ``None``.

Sub-rules:

1. **Place both clauses on the module-level constant**, not in a
   README or separate doc that can drift from the emit site.
   The constant's docstring is the only place that future
   maintainers reading the formatter source will encounter.
2. **Define which formats carry the field and which don't.**
   Machine-consumed formats (JSON, SARIF) carry it.
   Human-rendered (``lint_human``) and standards-compliant
   downstream formats (``lint_junit`` — JUnit consumers expect
   the standard XML schema without protokit extensions)
   deliberately don't.
3. **Use the same value across sibling machine formats** per
   [[cross-format-enum-string-parity-2026-05-08]]. Key names
   may differ (``schema_version`` vs ``lint_schema_version``)
   when one format reserves the obvious name, but values are
   identical.
4. **Pin co-existence with other properties via tests.** A test
   that constructs a report with BOTH ``runtime_warnings`` AND
   ``schema_version`` populated (in SARIF, both live under
   ``runs[0].properties``) catches regressions where one stomps
   on the other during ``setdefault``-based property assembly.
5. **Add a DRAFT-table row** for the new field per
   [[public-surface-draft-discipline-source-audit-2026-05-12]].
   The README schema-linting section must enumerate the
   new field with its bump policy summary before the delivery
   boundary commit.

## Why This Matters

**Without the field-absence semantic, consumers can't safely
distinguish "older output" from "malformed response".** A
consumer comparing ``"0.2" >= "0.1"`` works; comparing ``"0.2" >=
None`` raises. Naming absence as "implicit ``0.1``" lets the
consumer write a single comparison path instead of branching on
``is None``.

**Without the bump contract, the version field drifts toward
meaninglessness.** A field that bumps on every enum-value
addition becomes noise (consumers re-route parsing on every
release); a field that doesn't bump on meaning changes lies
silently (consumers parse newer output with older assumptions).
The four-clause policy (top-level key add, meaning change, field
removal; NOT enum-value add) makes the bump decision
deterministic.

**Both clauses must land in the same commit as the field
introduction.** Retrofitting the absence semantic later is
impossible — by then, downstream consumers have already encoded
their guess. The ce:review pattern caught the gap before any
external consumer existed; in a published-API world, that gap
would have shipped.

**The constant is the single source of truth.** A README
section, a separate spec doc, or a comment on the JSON emit
site can drift independently. Co-locating both clauses on the
constant means a contributor editing the value (``"0.2"`` →
``"0.3"``) literally cannot avoid reading the policy.

## When to Apply

Apply this discipline when ALL of the following are true:

1. A new ``schema_version`` (or equivalent versioning) field is
   being added to a wire-format output that already shipped
   without one.
2. Two or more sibling formats will carry the same version
   signal (single-format outputs still need the bump contract
   but the cross-format parity sub-rule doesn't apply).
3. Consumers may switch on the version (i.e., the field is not
   purely informational).

The inverse — when this discipline is NOT applicable:

- **Greenfield outputs** that ship the version in their first
  release. Absence is impossible (the field exists from commit
  zero), so the absence-semantic clause can be omitted. The
  bump contract still applies.
- **Per-format ad-hoc version comments** (e.g., a top-of-file
  ``# JSON output v2``) that aren't machine-readable. Those are
  developer notes, not contract surfaces.
- **Internal-only formats** that never leave the process (e.g.,
  pickle dumps for caching). No external consumer means no
  contract to maintain.

## Examples

### Constant with both clauses (the discipline anchor)

``src/protokit/formatters/_builtin_lint.py:227–250``:

```python
#: D6a U9 R9d: wire-format schema version for ``lint_json`` (top-level
#: ``schema_version``) and ``lint_sarif`` (``runs[].properties.lint_schema_version``).
#: Both formatters MUST emit the same string value per the
#: cross-format-enum-string-parity discipline. ``lint_human`` (terminal-
#: rendered text) and ``lint_junit`` (XML; downstream JUnit consumers
#: rely on the standard schema without protokit-specific extensions)
#: deliberately do NOT carry this field.
#:
#: Consumer contract:
#:   - Consumers MUST treat unknown values as forward-compatible
#:     (read what they can, ignore new keys they don't understand).
#:   - Field-absent semantic: protokit output that predates this
#:     constant (no ``schema_version`` key at all) is the implicit
#:     version ``"0.1"`` — i.e., one bump below the first
#:     documented value. Consumers comparing versions should treat
#:     absence as a known-older release, NOT as an error.
#:   - Protokit bumps this version on:
#:       (a) addition of new top-level keys
#:       (b) change in meaning of an existing field
#:       (c) removal of a previously documented field
#:   - **Bump-trigger refinement (closed Literals vs open ladders):**
#:     Adding new string values to an existing enum field has two
#:     consumer-impact regimes — open severity-string ladders
#:     (consumers tolerate unknown values gracefully) do NOT bump;
#:     closed Literal discriminators (consumers exhaustively switch
#:     on the value) DO bump. The discriminating question: can a
#:     consumer that doesn't know about the new value still produce
#:     a correct result? See [[closed-literal-discriminator-bump-trigger-2026-05-17]]
#:     for the consumer-correctness test + the D6b U5 worked example.
_LINT_JSON_SCHEMA_VERSION: str = "0.3"  # 0.2 → 0.3 in D6b U5 (closed-Literal addition)
```

The bump-trigger refinement landed in D6b U5 (commit `16b494f`)
as the first closed-Literal-discriminator addition under this
contract. Before U5 the constant docstring had a single blanket
sentence: "Adding new severity-level / category strings to an
existing enum field does NOT bump the version." That wording was
correct for `LintFinding.severity` (open ladder) but WRONG for
`LintRuntimeWarning.category` (closed discriminator) — the U5
addition of `"severities_unloaded_rule"` to `category` triggered
the 0.2 → 0.3 bump, contradicting the blanket sentence and
forcing the refinement. See [[closed-literal-discriminator-bump-trigger-2026-05-17]]
for the full distinction + when each regime applies.

### Cross-format parity — same value, different key paths

``lint_json`` emit site (top-level):

```python
"schema_version": _LINT_JSON_SCHEMA_VERSION,
```

``lint_sarif`` emit site (namespaced under ``properties`` to avoid
SARIF's reserved ``schema`` property):

```python
run_props = run.setdefault("properties", {})
run_props["lint_schema_version"] = _LINT_JSON_SCHEMA_VERSION
```

The formatter-level inline comments collapse to one-line pointers
rather than repeating the policy:

```python
# D6a U9 R9d wire-format version; see the
# ``_LINT_JSON_SCHEMA_VERSION`` constant's docstring for the
# full consumer contract (bump rules + absence semantic).
"schema_version": _LINT_JSON_SCHEMA_VERSION,
```

### Co-existence test (the regression net)

When SARIF carries both ``runtime_warnings`` and
``lint_schema_version`` under the same ``properties`` block,
``setdefault``-based assembly can race if not written carefully.
The dedicated co-existence test pins both keys' presence and
value:

``tests/test_builtin_lint_runtime_warnings.py:346–374``:

```python
def test_runtime_warnings_and_schema_version_coexist(
    self, sarif_validator,
):
    warning = LintRuntimeWarning(
        category="rule_exception",
        rule_id="naming/snake-case-fields",
        message="cosmetic test warning",
        exception_type="ValueError",
        descriptor_path="acme.User.x",
    )
    report = LintReport(runtime_warnings=(warning,))
    doc = json.loads(lint_sarif(report, _ctx()))
    sarif_validator.validate(doc)
    run = doc["runs"][0]
    properties = run["properties"]
    assert "runtime_warnings" in properties, properties
    assert "lint_schema_version" in properties, properties
    assert len(properties["runtime_warnings"]) == 1
    assert properties["lint_schema_version"] == "0.2"
```

### Format-exclusion tests

The contract names two formats that explicitly DO NOT carry the
field. Pinning their absence as positive tests prevents accidental
proliferation:

```python
def test_lint_human_does_not_emit_schema_version(self, ...) -> None:
    output = lint_human(report, ctx)
    assert "schema_version" not in output

def test_lint_junit_does_not_emit_schema_version(self, ...) -> None:
    xml_root = ET.fromstring(lint_junit(report, ctx))
    # JUnit's root is <testsuite>; no protokit-specific extension
    assert "schema_version" not in xml_root.attrib
    for child in xml_root.iter():
        assert "schema_version" not in child.attrib
```

## Related

- [[cross-format-enum-string-parity-2026-05-08]] — same
  output-boundary mechanism applied to enum string values.
  ``schema_version`` is a new field at the same sibling-format
  boundary; bumping the version requires re-auditing
  cross-format string parity for the version's own
  representation. The two learnings together define the
  "same-string-across-siblings" discipline at both the enum
  level (existing) and the schema_version level (this doc).
- [[public-surface-draft-discipline-source-audit-2026-05-12]] —
  the ``schema_version`` constant and the new CLI flags
  introduced in D6a U9 are DRAFT-table rows pending Unit 10
  stabilization. This learning is the design rationale; that
  learning is the operational discipline for keeping the
  README table accurate against the source.
- [[audit-wire-format-before-claiming-sibling-parity-2026-05-03]] —
  structural sibling-parity audit. The bump contract is itself
  a wire-format claim; the audit discipline applies to verifying
  the version field is actually emitted at both sibling sites.
- [[parametrized-matrix-tests-inherit-schema-validators-2026-05-12]] —
  schema-version-bearing payloads create new validator
  obligations; matrix tests covering all output formats must
  inherit the schema validator that knows about the new field.
- Anchor commits: ``c7a426b`` (initial U9 R9d feature commit
  introducing the field at both sites); ``3c828a4`` (ce:review
  follow-up F2 adding the absence semantic to the constant's
  docstring and consolidating the inline comments to pointers).
- Plan: ``docs/plans/2026-05-12-001-feat-protokit-lint-d6a-rule-library-plan.md``
  Unit 9 R9d.
- 11-reviewer ce:review at ``.context/compound-engineering/
  ce-review/20260513-113000-u9/`` — api-contract reviewer
  surfaced AC-1 (P1, 0.82 confidence) as the field-absence-gap
  finding.
- [[pre-1.0-version-bump-as-communication-contract]] — the
  package-version-layer parallel. This doc covers the
  wire-format `schema_version` constant's dual-clause contract
  (bump triggers + absence semantic); the package-version
  learning covers the project's version bump itself + the
  CHANGELOG section as its communication contract. Same shape
  at two different artifacts: the constant docstring is to the
  wire-format-version what the CHANGELOG section is to the
  package-version. Both eliminate ceremonial markers in favor
  of explicit dual-clause communication.
- [[delivery-boundary-unit-commit-composition]] — the
  wire-format `schema_version` field introduced in U9 surfaced
  in U10's CHANGELOG entry, README JSON-output table row, and
  README Public Surface DRAFT row. The delivery-boundary unit
  is where the wire-format version's user-facing communication
  lands; the feature-unit commit ships the field, the boundary
  commit communicates it.
- [[closed-literal-discriminator-bump-trigger-2026-05-17]] —
  EXTENDS this learning's bump contract. Replaces the original
  blanket "enum-value additions don't bump" sentence with the
  closed-vs-open distinction grounded in the consumer-correctness
  test. D6b U5 is the first worked example: adding
  `"severities_unloaded_rule"` to `LintRuntimeWarning.category`
  triggered the 0.2 → 0.3 bump because consumers exhaustively
  switch on `category` (closed discriminator). Adding a value to
  `LintFinding.severity` would NOT bump because consumers render
  / order it (open ladder).
- [[value-migrated-vs-value-added-consumer-migration-2026-05-17]] —
  CONSUMER-SIDE companion. When the bump fires, this learning
  tells the producer when to bump; the value-migrated learning
  tells the producer how to FRAME the bump in the CHANGELOG so
  consumers know whether they need to extend their switch tables
  (value-added) or AUDIT them (value-migrated). The two learnings
  together cover the full producer→consumer communication chain
  for wire-format `Literal` changes.
- D6b U5 anchor commits: `16b494f` (feat — `category` Literal
  widening + `_LINT_JSON_SCHEMA_VERSION` 0.2 → 0.3 + bump-contract
  docstring refinement), `7cd4095` (ce:review follow-ups — 6
  safe_auto stale-narrative fixes).
