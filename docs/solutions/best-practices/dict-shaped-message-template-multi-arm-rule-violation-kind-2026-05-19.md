---
title: Use dict-shaped message_template keyed by violation_kind when a rule has multiple textually-distinct emit arms
date: 2026-05-19
category: docs/solutions/best-practices
module: protokit.schema.lint.rules.package + protokit.schema.lint.decorator + protokit.formatters._builtin_lint
problem_type: best_practice
component: tooling
severity: medium
applies_when:
  - "A `@lint_rule` callable emits via two or more structurally distinct `violation_kind` values whose message text shares no common template structure"
  - "Downstream formatters (`lint_sarif`'s rules catalog, IDE plugins, CI dashboards) consume `LintRuleSpec.message_template` as a rule-level description"
  - "Structured-output consumers need to programmatically branch on the rule's emit arm without parsing rendered `message.text`"
  - "The temptation is to write `message_template=\"{payload}\"` (identity-template) and compose the full message inline as `params[\"payload\"]`"
related_components:
  - development_workflow
tags:
  - lint-rule
  - message-template
  - multi-kind
  - violation-kind
  - sarif
  - rule-design
  - shortdescription
  - structured-output
  - buf-parity
  - package-rules
---

# Use dict-shaped message_template keyed by violation_kind when a rule has multiple textually-distinct emit arms

## Context

R8b (`package/directory-same-package`, D6c U2) ships with **two structurally distinct emit arms** empirically locked against buf v1.69.0:

- **Standard arm**: `Multiple packages "X,Y[,Z]" detected within directory "Z".` — fires when all packages in a directory are declared.
- **Empty-mixed arm**: `Package "X" and file with no package detected within directory "Y".` — fires when declared and packageless files co-occur in the same directory.

The two arms share no template structure: the first wraps a comma-separated package list; the second wraps a single declared package + a fixed prose clause. There is no shared prefix, suffix, or pluralization gate; the entire sentence shape differs.

The initial U2 drop used a single identity template + payload key:

```python
@lint_rule(
    rule_id="package/directory-same-package",
    severity=LintSeverity.ERROR,
    message_template="{payload}",   # identity-template
    ...
)
def check_directory_same_package(ctx):
    ...
    payload = f'Package "{declared}" and file with no package detected within directory "{current_dir}".'
    ctx.emit(
        violation_kind="package/directory-same-package",  # same kind for BOTH arms
        params={"payload": payload, "packageless_present": True, ...},
    )
```

ce:review caught two distinct downstream problems with this shape (2-way convergence: maintainability + api-contract, P2/0.82 boosted):

1. **SARIF rules catalog corruption**: `_lint_rules_catalog` at `_builtin_lint.py:530` derives `tool.driver.rules[].shortDescription.text` from `spec.message_template`. The literal string `"{payload}"` shipped to GitHub Code Scanning's rules index as R8b's description.
2. **Agent discrimination opacity**: with both arms sharing `violation_kind="package/directory-same-package"`, agents reading structured output couldn't programmatically branch between arms. The semantic discriminator existed (`packageless_present: bool` in params) but the canonical wire-format discriminator (`violation_kind`) was identical across arms.

## Guidance

When a `@lint_rule` callable emits via two or more structurally distinct message shapes, use a **dict-shaped `message_template`** keyed by `violation_kind`. Pair it with a **dict-shaped `severity`** carrying the same keys. Emit each arm with a distinct `violation_kind` value. Define module-level constants for the kind strings + the per-kind template/severity dicts.

### Concrete pattern (D6c U2 R8b post-fix, commit `808189b`)

```python
# Module-level constants for the kind strings.
_R8B_STANDARD_KIND = "package/directory-same-package"
_R8B_EMPTY_MIXED_KIND = "package/directory-same-package/empty-mixed"

# Dict-shaped templates keyed by violation_kind.
_R8B_MESSAGE_TEMPLATES: dict[str, str] = {
    _R8B_STANDARD_KIND: (
        'Multiple packages "{packages}" '
        'detected within directory "{directory}".'
    ),
    _R8B_EMPTY_MIXED_KIND: (
        'Package "{package}" and file with no package '
        'detected within directory "{directory}".'
    ),
}

# Dict-shaped severities keyed by violation_kind — must match
# message_template's key set per LintRuleSpec.__post_init__'s
# dual-shape pairing invariant.
_R8B_SEVERITIES: dict[str, LintSeverity] = {
    _R8B_STANDARD_KIND: LintSeverity.ERROR,
    _R8B_EMPTY_MIXED_KIND: LintSeverity.ERROR,
}


@lint_rule(
    rule_id="package/directory-same-package",
    severity=_R8B_SEVERITIES,           # dict-shaped
    profiles=("recommended", "default"),
    element=ElementKind.FILE,
    message_template=_R8B_MESSAGE_TEMPLATES,   # dict-shaped
    source_spec="buf:DIRECTORY_SAME_PACKAGE",
)
def check_directory_same_package(ctx: FileLintContext) -> None:
    ...
    if packageless_present and declared_pkgs:
        ctx.emit(
            violation_kind=_R8B_EMPTY_MIXED_KIND,
            params={
                "file": safe_file,
                "directory": safe_dir,
                "package": declared,
                "packageless_present": True,
            },
        )
    else:
        ctx.emit(
            violation_kind=_R8B_STANDARD_KIND,
            params={
                "file": safe_file,
                "directory": safe_dir,
                "packages": pkg_list,
                "packageless_present": False,
            },
        )
```

### How the formatter consumes dict templates

`_render_message` at `_builtin_lint.py:73-79` already supports dict-shaped templates:

```python
template = spec.message_template
if isinstance(template, dict):
    template_str = template.get(finding.violation_kind, finding.rule_id)
else:
    template_str = template
```

`_lint_rules_catalog` at `_builtin_lint.py:547-552` renders multi-kind rules into SARIF by joining all arm descriptions:

```python
elif isinstance(spec.message_template, str):
    description = spec.message_template
else:
    # Multi-kind rule: dict template. Join all values to
    # surface every kind's prose in the SARIF rule panel.
    description = "; ".join(spec.message_template.values())
```

The dict-shaped form drops into existing formatter machinery without modifications.

### Heterogeneous params across arms

When arms carry different param keys (R8b's standard arm has `packages` plural; empty-mixed has `package` singular), annotate the `params` dict with a union type at the assignment site to document the contract:

```python
params: dict[str, str | bool] = {...}  # annotated at first assignment
```

Document the divergent keys at the rule's module header so structured-output consumers know which key to read per arm. R8b's module header lists:

> "Both arms share `file`/`directory`/`packageless_present`/`payload` but differ on `package` (singular, empty-mixed arm) vs `packages` (plural CSV, standard arm)"

## Why This Matters

1. **SARIF rules-catalog quality**: GitHub Code Scanning, Sonatype Lift, and other SARIF consumers read `run.tool.driver.rules[].shortDescription.text` to populate their rule index. An identity template `"{payload}"` produces a useless catalog entry; the dict-shaped form surfaces both arms' human-readable descriptions joined into one description string.
2. **Agent-callable discrimination via canonical fields**: with distinct `violation_kind` per arm, agents reading `lint_json` or SARIF can branch on the string-typed discriminator that is part of the rule's wire-format contract, instead of parsing rendered `message.text` (fragile) or reading a rule-specific boolean (works but rule-coupling — every multi-arm rule would need its own discriminator key).
3. **Test clarity**: assertions on rendered messages match the correct template per arm via `_render_message`'s dict-lookup. With `"{payload}"` the test asserts the pre-composed payload string matches itself — tautological for template verification. With dict-shaped templates, the test verifies the formatter actually selects the correct arm template based on `violation_kind`.
4. **Validity gates at registration time**: `LintRuleSpec.__post_init__` enforces the dual-shape pairing invariant at registration time (both `severity` and `message_template` must be dict-shaped OR both must be single-kind). A rule that ships a dict template without a dict severity raises `TypeError` at decoration time, not at first emit. This catches the half-conversion class of bug.
5. **Discriminator versioning is open-ladder, not closed-Literal**: adding a new arm to a multi-kind rule adds a new key to both dicts. `violation_kind` is treated as an open string per the `_LINT_JSON_SCHEMA_VERSION` bump contract (open ladders don't bump). New arms don't break consumers that branch on the existing arm and ignore unknowns — see [[closed-literal-discriminator-bump-trigger-2026-05-17]] for the discriminator-bump rules.

## When to Apply

- Any `@lint_rule` callable that calls `ctx.emit(violation_kind=...)` with two or more distinct `violation_kind` values whose message text differs structurally.
- Rules where the SARIF catalog entry should describe sub-arm semantics, not a catch-all identity template.
- Rules whose `params` dict has different keys across emit arms — the heterogeneous-key contract should be documented at the annotation site and in the module header.
- Cross-rule remediation patterns where the message text varies based on which sibling rule would fire on the remediation (per [[lint-rule-message-templates-must-not-recommend-actions-that-trigger-siblings-2026-05-13]]) — dict-shaped templates let each arm carry the right remediation steering.

**Anti-applicability** (when to use a single template):

- A rule has multiple emit arms that share a fixed wrapper with a varying `{payload}` substring (e.g., R7's `_check_package_option` uses one template wrapping a `{values_payload}` that switches between `'multiple values "X,Y"'` and `'both values "X" and no value'`). The single template is correct here because the wrapper structure is invariant — only the inner payload varies. The SARIF catalog renders the wrapper meaningfully; the inner payload is per-finding context.

The discriminator: does the message **structure** vary across arms, or only the **substring within a stable structure**? If structure varies, use dict-shaped templates. If only substring varies, single template with composed payload param.

## Examples

### Before (identity-template anti-pattern, D6c U2 initial drop, commit `7eb5092`)

```python
@lint_rule(
    rule_id="package/directory-same-package",
    severity=LintSeverity.ERROR,
    message_template="{payload}",   # identity passthrough
    source_spec="buf:DIRECTORY_SAME_PACKAGE",
)
def check_directory_same_package(ctx):
    ...
    payload = f'Package "{declared}" and file with no package detected within directory "{current_dir}".'
    ctx.emit(
        violation_kind="package/directory-same-package",  # same kind for both arms
        params={"payload": payload, "packageless_present": True, ...},
    )
```

**SARIF rules catalog output:**

```json
{
  "id": "package/directory-same-package",
  "name": "package/directory-same-package",
  "shortDescription": {"text": "{payload}"}   // ← rendered literally
}
```

### After (dict-shaped templates per arm, commit `808189b`)

```python
_R8B_MESSAGE_TEMPLATES: dict[str, str] = {
    "package/directory-same-package":
        'Multiple packages "{packages}" detected within directory "{directory}".',
    "package/directory-same-package/empty-mixed":
        'Package "{package}" and file with no package detected within directory "{directory}".',
}
_R8B_SEVERITIES: dict[str, LintSeverity] = {
    "package/directory-same-package": LintSeverity.ERROR,
    "package/directory-same-package/empty-mixed": LintSeverity.ERROR,
}

@lint_rule(
    rule_id="package/directory-same-package",
    severity=_R8B_SEVERITIES,
    message_template=_R8B_MESSAGE_TEMPLATES,
    source_spec="buf:DIRECTORY_SAME_PACKAGE",
)
def check_directory_same_package(ctx):
    ...
    ctx.emit(
        violation_kind="package/directory-same-package/empty-mixed",  # distinct
        params={"package": declared, "directory": safe_dir, ...},
    )
```

**SARIF rules catalog output:**

```json
{
  "id": "package/directory-same-package",
  "name": "package/directory-same-package",
  "shortDescription": {
    "text": "Multiple packages \"{packages}\" detected within directory \"{directory}\".; Package \"{package}\" and file with no package detected within directory \"{directory}\"."
  }
}
```

Both arms surface in the catalog; agents can also key on `violation_kind` for per-arm branching.

### Test updates accompanying the conversion

```python
class TestR8bRuleSpec:
    def test_spec_metadata(self) -> None:
        spec = check_directory_same_package._lint_spec
        assert spec.rule_id == "package/directory-same-package"
        # Multi-kind: severity is a dict keyed by violation_kind.
        assert spec.severity == {
            "package/directory-same-package": LintSeverity.ERROR,
            "package/directory-same-package/empty-mixed": LintSeverity.ERROR,
        }

    def test_message_templates_per_kind(self) -> None:
        """Each violation_kind has its own human-readable template."""
        spec = check_directory_same_package._lint_spec
        assert isinstance(spec.message_template, dict)
        assert spec.message_template == _R8B_MESSAGE_TEMPLATES
```

## Related

- [[expose-finding-params-lint-json-sarif-agent-native-2026-05-19]] — sibling agent-native discipline. Dict-shaped templates give agents the `violation_kind` discriminator; surfacing `params` in structured output gives them the per-finding semantic fields. Both ce:review findings (#6 + #8) shipped together at D6c U2 commit `808189b`.
- [[closed-literal-discriminator-bump-trigger-2026-05-17]] — schema-evolution rules for `violation_kind` as a discriminator. Adding a new arm to a multi-kind rule is an open-ladder extension; consumers that branch on existing kinds and ignore unknowns are forward-compatible.
- [[buf-parity-divergence-documentation-discipline-2026-05-13]] — four-site documentation discipline for parity divergences. Dict-shaped templates extend the discipline: each arm's message_template is one of the four sites, and the per-arm test methods are another.
- [[lint-rule-message-templates-must-not-recommend-actions-that-trigger-siblings-2026-05-13]] — content discipline for message remediation prose. Multi-arm rules let each arm carry the right remediation steering for its arm-specific failure mode.
- [[dual-view-prewalk-accumulator-cross-file-rule-dispatch-2026-05-19]] — the accumulator pattern that feeds R8b's two-arm dispatch. The `by_directory` view's `pkg_map` shape (with empty-string key for packageless files) is what makes the two arms structurally distinguishable.
- [[audit-wire-format-before-claiming-sibling-parity-2026-05-03]] — Layer B (data layout: are the same fields populated?). The dict-shaped template surfaces the per-arm field divergence (`package` vs `packages`) at the SARIF catalog layer.
