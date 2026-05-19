---
title: Surface `LintFinding.params` in `lint_json` + SARIF so agent callers can discriminate emit arms without parsing message text
date: 2026-05-19
category: docs/solutions/best-practices
module: protokit.formatters._builtin_lint
problem_type: best_practice
component: tooling
severity: medium
applies_when:
  - "A lint rule's `params` dict carries semantic fields beyond what the rendered `message.text` exposes (e.g., boolean discriminators, structured identifiers, multi-arm switches)"
  - "Wire-format consumers include agent callers, IDE plugins, CI dashboards, or any programmatic tooling that needs to branch on per-finding semantics"
  - "A rule ships with multiple emit arms whose discriminator field is critical for downstream behavior"
  - "Adding `params` to existing finding objects is forward-compatible — no `_LINT_JSON_SCHEMA_VERSION` bump required per the open-vs-closed contract"
related_components:
  - development_workflow
tags:
  - lint-json
  - sarif
  - wire-format
  - params
  - agent-native
  - semantic-discriminator
  - formatter-gap
  - structured-output
  - package-rules
---

# Surface `LintFinding.params` in `lint_json` + SARIF so agent callers can discriminate emit arms without parsing message text

## Context

`LintFinding.params` is the canonical dict of rule-level semantic fields, populated by every `ctx.emit(violation_kind=..., params={...})` call. It carries the inputs the message template interpolates plus any extra discriminator fields a rule chooses to expose (e.g., R8b's `packageless_present: bool`). Pre-D6c U2, neither `lint_json` (`_builtin_lint.py:304-321`) nor `lint_sarif` (`_lint_result_for_finding` at `_builtin_lint.py:509-527`) serialized `params` in their output payloads.

R8b's design surfaced the gap materially: the rule has two structurally distinct emit arms (standard + empty-mixed) that an agent caller needs to branch on. The `packageless_present` boolean discriminator existed in the in-memory `LintFinding.params` but was unreachable through any wire-format surface — agents either had to regex-parse the rendered `message.text` (fragile against message rewording) or call back into the Python runtime (impossible from external tooling).

ce:review's agent-native reviewer caught this as a P2 finding at D6c U2. The fix was a four-line formatter change documented in commit `808189b`. The pre-existing gap was latent until R8b made it load-bearing; future multi-arm rules would inherit the same hidden-discriminator problem if the formatter contract wasn't extended.

## Guidance

Include `"params": dict(finding.params)` in every finding entry in `lint_json` and in every SARIF `result`'s `properties` object. Use `dict(finding.params)` (shallow copy) — not direct passthrough — so callers cannot mutate the finding's internal state via the returned payload.

### `lint_json` finding shape

`_builtin_lint.py:304-321`, post-fix:

```python
findings_payload: list[dict[str, Any]] = [
    {
        "rule_id": finding.rule_id,
        "severity": finding.severity.value,
        "location": str(finding.location),
        "location_file": finding.location.file,
        "location_kind": (
            type(finding.location).__name__
            .removesuffix("Location")
            .lower()
        ),
        "violation_kind": finding.violation_kind,
        "message": _render_message(
            finding, report.specs.get(finding.rule_id),
        ),
        # Per-finding ``params`` dict (D6c U2 ce:review #8 +
        # agent-native finding). Exposes the rule's semantic
        # introspection fields so agent callers don't have to
        # string-parse the rendered ``message``. Forward-compatible:
        # consumers may ignore unknown keys; this is a per-finding
        # extension, NOT a top-level schema-version-bumping change
        # per ``_LINT_JSON_SCHEMA_VERSION``'s open-vs-closed contract.
        "params": dict(finding.params),
    }
    for finding in report.findings
]
```

### SARIF `result` shape

`_lint_result_for_finding` at `_builtin_lint.py:509-527`, post-fix:

```python
def _lint_result_for_finding(
    finding: LintFinding, message: str,
) -> dict[str, Any]:
    return {
        "ruleId": finding.rule_id,
        "level": _lint_severity_to_sarif_level(finding.severity),
        "message": {"text": message},
        "locations": [{
            "logicalLocations": [{
                "fullyQualifiedName": str(finding.location),
            }],
        }],
        # SARIF spec reserves `properties` for vendor extensions.
        "properties": {
            "params": dict(finding.params),
        },
    }
```

### Why no `_LINT_JSON_SCHEMA_VERSION` bump

The constant's docstring at `_builtin_lint.py:228-271` documents the open-vs-closed bump contract. Adding a new key to an existing object inside a top-level list (`findings[].params`) is a per-finding extension, not a top-level schema change:

- **Rule (a)** (addition of new top-level keys) — does not apply; `params` is nested inside each finding, not at the payload's top level.
- **Open ladder discriminator question** — "Can a consumer that doesn't know about the new key still produce a correct result?" Yes: consumers that read `rule_id`, `severity`, `message`, `location` can ignore `params` and produce correct human-readable output. Open extension → no bump.

This contrasts with closed-Literal discriminator changes (e.g., adding a new value to `LintRuntimeWarning.category`'s string set, which bumped 0.2 → 0.3 at D6b U5) where unknown values fall through consumer `switch`/`match` blocks to default branches the consumer didn't expect.

### Test coverage

Pin the contract at both formatter layers with explicit per-finding params assertions:

```python
def test_per_finding_params_serialized(self) -> None:
    """``params`` dict surfaces verbatim in each finding payload."""
    finding = LintFinding(
        rule_id="x/multi",
        severity=LintSeverity.ERROR,
        location=FileLocation(file="a.proto"),
        violation_kind="x/multi",
        params={
            "directory": "pkg",
            "packages": "acme.bar,acme.foo",
            "packageless_present": False,
        },
    )
    report = LintReport(findings=(finding,), specs={"x/multi": spec})
    payload = json.loads(lint_json(report, self._ctx()))
    entry = payload["findings"][0]
    assert entry["params"] == {
        "directory": "pkg",
        "packages": "acme.bar,acme.foo",
        "packageless_present": False,
    }
```

Mirror for SARIF (`test_result_properties_carries_params`) — both formatters should be locked at the test layer so a future formatter refactor that drops `params` fires loudly.

### Robustness against non-JSON-serializable values

Both formatters call `json.dumps(payload, default=str)`. Non-JSON-serializable param values (rare for properly-typed rules — `str | bool` covers protokit's current rule set — but possible if a user-pack rule stores `Path`/`datetime`/custom objects) degrade to `repr` via `default=str` rather than raising `TypeError` and suppressing the entire document. Use `dict(finding.params)` for the shallow copy; do not deep-copy.

## Why This Matters

1. **Rule-arm discrimination without message parsing**: multi-arm rules carry programmatic discriminators in `params` (e.g., R8b's `packageless_present`). Without `params` in wire output, callers must parse `"Package X and file with no package"` vs `"Multiple packages X,Y"` from rendered prose — fragile against message rewording, prone to internationalization breakage if message text is ever localized.
2. **Stable identifiers across rewording**: rendered messages can change for UX reasons (clarification, typo fixes, tone adjustments). Param field names are part of the rule's semantic contract and are more stable. Agents keying on `params["directory"]` continue working through any message-text revision.
3. **Forward-compatible extension surface**: future tooling (IDE plugins, CI dashboard aggregators, auto-fix agents) can read structured params per finding without requiring a wire-format version bump. New rules adding new param keys are open-ladder extensions; consumers ignore unknown keys.
4. **Latent-gap-made-load-bearing pattern**: this is a pre-existing formatter gap that R8b's dual-arm design surfaced. Without R8b, the formatter could ship without `params` indefinitely because no rule's behavior depended on agent-callable arm discrimination. When R8b shipped with two arms sharing the same `rule_id`, the discriminator gap moved from "latent agent-native gap" to "actively blocking discriminator-dependent consumers." This is a recognizable pattern: **formatter completeness gaps surface when the FIRST rule with the dependent shape ships, not when the formatter was designed.**

## When to Apply

- Any new rule that emits findings with params carrying user-actionable structured data beyond what the rendered message text exposes.
- Any rule with multiple emission arms that differ in param shape or meaning — the discriminator field (`packageless_present`, `arm`, etc.) must be reachable from machine-readable output.
- Any formatter that renders both human-readable and machine-readable output — both formats should carry the params dict.
- Any time a rule adds a `bool` or `enum` discriminator to `params`: verify the wire format actually surfaces it before shipping. Treat the discriminator's presence in the in-memory `LintFinding` as **necessary but not sufficient** for agent-callable consumption.

## Examples

### Before (params unreachable to agents, pre-D6c U2 ce:review)

`lint_json` output for an R8b finding:

```json
{
  "rule_id": "package/directory-same-package",
  "severity": "error",
  "location": "pkg/a.proto",
  "message": "Multiple packages \"acme.foo,acme.bar\" detected within directory \"pkg\"."
}
```

Agent wanting to discriminate the standard arm from empty-mixed: must regex-parse the message text. Looking for `"file with no package"` substring is the only viable approach — and it breaks if the message is ever localized or rephrased.

### After (params exposed, commit `808189b`)

```json
{
  "rule_id": "package/directory-same-package",
  "severity": "error",
  "location": "pkg/a.proto",
  "violation_kind": "package/directory-same-package",
  "message": "Multiple packages \"acme.foo,acme.bar\" detected within directory \"pkg\".",
  "params": {
    "file": "pkg/a.proto",
    "directory": "pkg",
    "packages": "acme.foo,acme.bar",
    "packageless_present": false
  }
}
```

Agent can now:

- Branch on `violation_kind == "package/directory-same-package/empty-mixed"` for the empty-mixed arm (per [[dict-shaped-message-template-multi-arm-rule-violation-kind-2026-05-19]]).
- Read `params.packageless_present` as a per-rule discriminator.
- Read `params.directory` and `params.packages` for downstream automation (e.g., synthesizing a fix-it action that moves files to align packages with directories).

### SARIF after

```json
{
  "ruleId": "package/directory-same-package",
  "level": "error",
  "message": {"text": "Multiple packages \"acme.foo,acme.bar\" detected within directory \"pkg\"."},
  "locations": [{
    "logicalLocations": [{
      "fullyQualifiedName": "pkg/a.proto"
    }]
  }],
  "properties": {
    "params": {
      "file": "pkg/a.proto",
      "directory": "pkg",
      "packages": "acme.foo,acme.bar",
      "packageless_present": false
    }
  }
}
```

SARIF's `properties` object is the spec-reserved vendor-extension bag; SARIF consumers that don't understand `properties.params` ignore it without error.

## Related

- [[dict-shaped-message-template-multi-arm-rule-violation-kind-2026-05-19]] — sibling agent-native discipline shipped in the same D6c U2 ce:review pass. Dict-shaped templates give agents the `violation_kind` canonical discriminator at the wire level; this doc gives agents the per-finding semantic fields via `params`. Together they form the complete agent-callable discrimination surface.
- [[wire-format-schema-version-bump-contract-and-absence-semantic-2026-05-13]] — schema-version bump rules. Explains why adding `params` to existing finding objects is an open-ladder extension that does NOT bump `_LINT_JSON_SCHEMA_VERSION`.
- [[cross-format-enum-string-parity-2026-05-08]] — sibling discipline at a different layer. That doc covers severity string consistency across `lint_json` + SARIF; this doc covers semantic-field surface consistency across the same two formatters.
- [[stale-forward-looking-text-cli-help-agent-discoverability-2026-05-12]] — sibling agent-discoverability discipline at the CLI surface. Both address "what can an agent discover from external surfaces?" — `--help` text and structured output are the two primary discovery channels.
- [[audit-wire-format-before-claiming-sibling-parity-2026-05-03]] — audit-trail discipline for wire-format contracts. The `params`-in-output addition should be reflected in any wire-format documentation that previously enumerated finding fields.
- [[multi-mechanism-fix-docstring-enumerate-each-layer-failure-mode-2026-05-18]] — the layer-enumeration discipline applies to the formatter completeness audit. Both `lint_json` and `lint_sarif` are independent layers; missing `params` from one but not the other would be a subtler version of the same gap.
