---
title: "Use the same enum string representation across all sibling output formats"
date: 2026-05-08
category: docs/solutions/best-practices
module: tooling/cli
problem_type: best_practice
component: tooling
severity: medium
applies_when:
  - "A domain enum (LintSeverity, FormatterKind, ChangeType, Direction) is serialized by two or more sibling output formatters (JSON, SARIF, JUnit, CSV) that downstream consumers may aggregate or compare side-by-side"
  - "A new sibling formatter is being written and the enum field's string form has not been pinned to a canonical value (`.value` vs `.name` vs a format-specific mapping)"
  - "An agent, CI dashboard, or script consumes output from multiple sibling formats and must reconcile the same domain concept across them"
  - "A sibling format uses a format-mandated mapping (e.g., SARIF `level` enum) that differs from the enum's `.value` — requiring a decision about which canonical string the OTHER siblings should align to"
  - "The enum's `.value` differs from its `.name` (e.g., `LintSeverity.WARNING = 'warning'` where `.value` is lowercase but `.name` is `'WARNING'`)"
tags:
  - enum-serialization
  - sibling-formats
  - output-parity
  - wire-format
  - formatter
  - cross-format-consistency
  - discipline
---

# Use the same enum string representation across all sibling output formats

## Context

protokit ships multiple machine output formats — JSON
(`lint_json`), JUnit XML (`lint_junit`), and SARIF
(`lint_sarif`) — for the same domain types (findings,
severities, locations). Each format is an independent output
channel, but all three consume the same `LintFinding` objects
with the same `LintSeverity` enum. When a single domain enum
flows through three formatters, all three must emit the same
canonical string for the same enum value, or downstream
consumers aggregating the formats see inconsistency.

When `lint_json` was first shipped in commit `e547bff` (D3
Unit 4b feat), a one-line choice in the `findings_payload`
list comprehension emitted `finding.severity.name` instead of
`finding.severity.value`. This rendered `"WARNING"` (the Python
identifier) instead of `"warning"` (the enum's designed string
value) — diverging from what `lint_sarif` had emitted correctly
since its first ship.

(session history) Three independent reviewers caught the
divergence at first-ship review:

- `correctness-reviewer`: casing inconsistency between two
  output formats for the same field.
- `agent-native-reviewer`: cross-format consumer breakage —
  an agent merging both outputs would need per-format
  normalization.
- `api-contract-reviewer`: stable-contract bug at first ship —
  the moment the first consumer reads the field, the casing
  becomes a breaking change to fix.

The fix landed in commit `6356cc8` (U4b ce:review follow-ups):
one character changed, `finding.severity.name` →
`finding.severity.value`. Plus one updated test assertion. The
bug class generalizes to any domain enum exposed across
multiple sibling output formats.

(session history) Why this didn't surface earlier in the
codebase: compat's `Severity` enum was defined with values
matching the Python identifiers (`Severity.WIRE = "WIRE"`,
`Severity.SEMANTIC = "SEMANTIC"`), so for compat findings
`severity.name == severity.value`. Both `.name` and `.value`
produce the same string. The bug class is unreachable on the
compat side. It became reachable on the lint side specifically
because `LintSeverity` chose lowercase values
(`LintSeverity.WARNING = "warning"`) — a decision made in D1
to align with `LintCompileDiagnostic.level`'s `Literal["info",
"warning", "error"]` vocabulary. The vocabulary alignment was
correct; the downstream wire-format effect (`.name != .value`)
was not audited.

## Guidance

**When a domain enum is exposed across multiple sibling
output formats that downstream consumers may aggregate, all
formats MUST emit the same canonical string for each enum
value. Use `enum.value` across siblings — `.name` is the
Python identifier; `.value` is the string designed for wire
output.**

Note: `.value` is whatever the enum author assigned at
definition time, not a Python-enforced wire-format slot. By
this project's convention, `.value` carries the user-facing /
machine-readable string. Treating `.value` as canonical and
`.name` as introspection-only is the convention to follow.

Concrete sub-rules:

1. **Use `enum.value` not `enum.name` in JSON serialization**
   unless the domain explicitly chose `.name` as the canonical
   form.
2. **Map at boundaries, not at use sites.** When a target
   format (SARIF, JUnit) has its own level vocabulary that
   doesn't map 1:1 to the domain enum, convert through a
   single-purpose boundary helper (e.g.,
   `_lint_severity_to_sarif_level`) rather than reaching into
   `.name` or `.value` opportunistically at the call site.
3. **Pin the canonical form in tests.** Each format's tests
   must assert the EXACT string emitted for each enum value —
   not just "key is present." A regression test comparing the
   string between two siblings (`assert json_severity ==
   sarif_level`) makes divergence visible immediately.

A short checklist before shipping a new sibling formatter:

1. List every domain enum whose values flow into the new
   formatter's output.
2. For each enum, find every other sibling formatter that
   already emits it.
3. Read the existing emission sites and confirm the new
   formatter uses the SAME string form (`enum.value` for all
   sibling lint formatters; `enum.value` for all sibling
   compat formatters; etc.).
4. Add a regression test that asserts the cross-format
   equality for at least one representative enum value.

## Why This Matters

**Cross-format aggregation breaks silently.** An agent merging
`lint_json` and `lint_sarif` outputs into a unified findings
table needs the same `severity` string from both formats.
Casing divergence forces per-format normalization downstream
— a permanent complexity tax on every consumer.

**Reviewer convergence is the signal.** When three reviewers
from three different angles (correctness, agent-readiness,
stable contract) independently flag the same one-line bug,
the underlying discipline gap is structural — a recurring
class, not a one-off. The same convergence pattern surfaced
earlier learnings in this codebase (`AttributeError` uncaught
in `_load_user_rule_pack` from U3 ce:review; `format_name`
case-sensitivity from U4a ce:review). The pattern is
reliable enough to bake into the compound process.

**Stable contract = compounding value.** Each format ship
calcifies its representation into every downstream parser.
Getting the first ship right means agent authors write
parsers once.

**The bug is reachable only when `.value != .name`.** This is
the structural condition that makes the discipline non-trivial:

- Compat's `Severity.WIRE = "WIRE"` →
  `Severity.WIRE.name == Severity.WIRE.value == "WIRE"`. No
  ambiguity; whichever a formatter picks, both produce the
  same string.
- Lint's `LintSeverity.WARNING = "warning"` →
  `LintSeverity.WARNING.name == "WARNING"`,
  `LintSeverity.WARNING.value == "warning"`. They differ. Every
  emission site is a potential divergence point.

When defining a NEW domain enum, choosing `.value == .name`
makes the bug class structurally unreachable but throws away
the vocabulary-alignment win lint chose (matching
`LintCompileDiagnostic.level` lowercase). Choosing
`.value != .name` keeps the alignment but requires this
discipline at every emission site. Both choices are
defensible; neither is free.

**The discipline applies broadly.** The protokit codebase has
multiple enum families exposed across formats: `LintSeverity`,
`Severity` (compat), `Direction`, `FormatterKind`,
`LintLocation` kinds, `ChangeType`. Each is a potential repeat
of this bug class.

## When to Apply

This discipline applies when ALL of the following are true:

1. A domain enum is serialized in 2+ output emission sites
   (JSON, XML, structured text).
2. The enum's `.value` differs from its `.name` (the trigger
   condition for divergence).
3. Downstream consumers may aggregate or compare the formats
   side-by-side.

The inverse — when the discipline is not applicable:

- **Single-format domains.** If only one formatter emits the
  enum, parity isn't a concern.
- **`.value == .name` enums.** Compat's `Severity` is the
  in-codebase example. Pick whichever; output is identical.
- **Format-mandated divergent mapping.** SARIF requires
  `level: "note"` for informational severity; the domain enum
  doesn't have a `"note"` value. The boundary helper
  (`_lint_severity_to_sarif_level`) maps explicitly. Other
  siblings should NOT propagate the SARIF-specific form back
  to JSON/JUnit — they keep the canonical `.value`.

(session history) The discipline is also missing from the
existing `audit-wire-format-before-claiming-sibling-parity`
learning. That learning covers STRUCTURAL wire format (RULES
element types, method signatures, operational semantics) but
not VALUE-REPRESENTATION wire format (enum string form, case,
quoting). The two learnings are complementary axes of the same
sibling-parity discipline.

## Examples

### Anchor: the U4b severity-casing bug

`LintSeverity` definition (`src/protokit/schema/lint/model.py:75`):

```python
class LintSeverity(Enum):
    """Severity ladder for lint findings.

    The string values match LintCompileDiagnostic.level so
    formatters render findings and diagnostics through the
    same vocabulary.
    """
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"
```

`.value` is the lowercase canonical form. `.name` is the
Python identifier (`ERROR`, `WARNING`, `INFO`).

**`lint_json` — pre-fix (commit `e547bff`, BUGGY):**

```python
findings_payload: list[dict[str, Any]] = [
    {
        "rule_id": finding.rule_id,
        "severity": finding.severity.name,   # ← "WARNING" uppercase
        "location": str(finding.location),
        "violation_kind": finding.violation_kind,
        "message": _render_message(...),
    }
    for finding in report.findings
]
```

**`lint_json` — post-fix (commit `6356cc8`, ALIGNED):**

The change is a single character — `.name` → `.value`. The
surrounding fields are unchanged at this scope:

```python
findings_payload: list[dict[str, Any]] = [
    {
        "rule_id": finding.rule_id,
        "severity": finding.severity.value,  # ← "warning" lowercase
        # ... other fields unchanged
    }
    for finding in report.findings
]
```

**`lint_sarif` boundary helper (correct since first ship,
`_builtin_lint.py:403`):**

```python
# Import guard: typing.assert_never landed in 3.11; for 3.10
# fall back to typing_extensions (already a transitive dep).
import sys
if sys.version_info >= (3, 11):
    from typing import assert_never
else:
    from typing_extensions import assert_never


def _lint_severity_to_sarif_level(
    severity: LintSeverity,
) -> Literal["none", "note", "warning", "error"]:
    if severity is LintSeverity.ERROR:
        return "error"
    if severity is LintSeverity.WARNING:
        return "warning"
    if severity is LintSeverity.INFO:
        return "note"
    assert_never(severity)
```

The `Literal["none", ...]` return type widens beyond what
this three-arm helper can actually emit (`"none"` is in the
SARIF spec but `LintSeverity` has no NONE member). That's a
deliberate choice — the boundary helper's return matches the
SARIF spec's full vocabulary, so a future severity addition
that needs `"none"` can be wired in without changing the
signature.

**Agent reading both formats:**

```python
# Pre-fix: required per-format normalization
sarif_level = result["level"]                # "warning"
json_severity = entry["severity"].lower()    # "WARNING".lower() == "warning"

# Post-fix: identical reading on both formats
sarif_level = result["level"]                # "warning"
json_severity = entry["severity"]            # "warning"
```

### JUnit's `.name.lower()` as a documented exception

`lint_junit` at `_builtin_lint.py:344` uses
`finding.severity.name.lower()`:

```python
junit.append_failure(
    case,
    message=message,
    type_=finding.severity.name.lower(),   # e.g. "warning"
    body=message,
)
```

This is NOT a bug — `.name.lower()` and `.value` produce the
same string for `LintSeverity` (`"warning"`, `"error"`,
`"info"`). The U4b sibling-parity docstring explicitly
documents this as an intentional divergence from compat's
JUnit pattern, where `type_` uses
`f"{severity.value}/{direction.value}"`. **The safety test is
that the emitted string matches the canonical `.value`; the
CALL CHAIN that produces it is secondary.** Document any
deviation from the `.value` call so future reviewers don't
re-flag it as a bug.

### Compat side: the bug is unreachable

`compat_json` (`src/protokit/formatters/_builtin_compat.py:112`):

```python
"severity": f.severity.value,   # "WIRE", "SEMANTIC", or "POLICY"
```

`Severity.value` for compat is uppercase by domain design
(`WIRE = "WIRE"`). For these enums, `.name == .value`. The
divergence between `.name` and `.value` cannot manifest. If
the enum had been redefined with lowercase values
(`Severity.WIRE = "wire"`), the bug class becomes reachable on
the compat side too — every emission site would need to be
re-audited.

### Regression test pattern

A cross-format equality test makes divergence visible
immediately:

```python
def test_severity_strings_match_across_json_and_sarif(
    self,
) -> None:
    """JSON 'severity' equals SARIF 'level' for the same enum
    value. Agents reading both formats see identical strings."""
    finding = LintFinding(
        rule_id="x/y",
        severity=LintSeverity.WARNING,
        location=FieldLocation(file="x.proto", message="X", field="f"),
        violation_kind="x/y",
        params={},
    )
    spec = _make_spec(rule_id="x/y", template="msg")
    report = LintReport(findings=(finding,), specs={"x/y": spec})

    json_payload = json.loads(lint_json(report, ctx))
    sarif_payload = json.loads(lint_sarif(report, ctx))

    json_severity = json_payload["findings"][0]["severity"]
    sarif_level = sarif_payload["runs"][0]["results"][0]["level"]

    # Both should be "warning". If they ever diverge, this test
    # fires and the discipline gap is named.
    assert json_severity == sarif_level
```

(As of commit `6356cc8` this exact test does not exist — the
fix was verified by updating the existing
`test_single_finding_renders_to_findings_list` assertion from
`"WARNING"` to `"warning"`. A dedicated cross-format equality
test is the next defense-in-depth layer.)

## Related

- `docs/solutions/best-practices/normalize-at-input-boundary-2026-05-07.md`
  — paired boundary discipline. That learning prescribes
  normalization at the INPUT boundary (callers must apply the
  same transform as the registry); this learning prescribes
  consistent serialization at the OUTPUT boundary (sibling
  formatters must use the same canonical enum representation).
  Together they define the two directions of boundary
  discipline in this codebase: **normalize early (inputs),
  serialize consistently (outputs)**.
- `docs/solutions/best-practices/audit-wire-format-before-claiming-sibling-parity-2026-05-03.md`
  — the design-time upstream discipline. That learning covers
  STRUCTURAL wire format (RULES element types, method
  signatures); this learning covers VALUE-REPRESENTATION wire
  format (enum string form). Both layers must be audited at
  every claim site, but the existing learning's checklist
  doesn't include enum-to-string serialization. This learning
  fills that gap. (session history) Specifically: the existing
  learning's checklist does not include "enum field string
  representations in serialized output" as an axis to audit.
- `docs/solutions/logic-errors/matcher-backend-path-resolution-skew-silently-empties-output-2026-05-02.md`
  — structural parent class. Its Prevention #5 generalizes
  the rule this learning instantiates: "matcher and
  source-of-truth must use identical resolution policies…
  applies beyond paths — JSON key ordering, URL canonicalization,
  hostname matching, Unicode NFC/NFD." Enum `.name` vs `.value`
  is a direct instance of that policy-skew class. Same root
  cause, different domain.
- [[wire-format-schema-version-bump-contract-and-absence-semantic-2026-05-13]] —
  sibling output-boundary discipline applied to a different
  carrier. The `schema_version` field introduced in D6a U9 is
  a new wire-format surface shared between `lint_json` (top-
  level) and `lint_sarif` (`runs[0].properties.lint_schema_version`).
  Bumping the version requires re-auditing the cross-format
  string parity for the version field's own representation;
  this learning is the discipline that catches divergence in
  the value, and that learning is the consumer-contract that
  governs when bumps are needed and what absence means.
- Anchor commits: `6356cc8` (the one-line `.name` → `.value`
  fix in `lint_json`); `e547bff` (the U4b feat where the bug
  first shipped).
- Plan: `docs/plans/2026-05-04-001-feat-protokit-lint-d3-cli-plan.md`
  Unit 4b.
