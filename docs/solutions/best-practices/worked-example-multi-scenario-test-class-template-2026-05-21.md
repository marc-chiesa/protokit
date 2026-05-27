---
title: "Multi-scenario test-class template for strategic-differentiator worked-example fixtures"
date: 2026-05-21
category: docs/solutions/best-practices
module: tests/schema/lint/cli/test_d6d_custom_annotation_example.py
problem_type: best_practice
component: testing
severity: medium
applies_when:
  - "Shipping a worked-example fixture that demonstrates a user-facing feature end-to-end in CI (S2-style hardening — provable in CI, not rhetorical documentation prose)"
  - "The feature has multiple configuration surfaces (presence, value-set, severity overlay, error path) that need independent coverage"
  - "The fixture is the canonical README example users will copy-paste — drift between the README snippet and the fixture must be detected at CI time"
  - "Agent-native consumers (GitHub Code Scanning, VS Code SARIF Viewer, MCP runtimes) need machine-readable contract verification, not just text-output substring matches"
tags:
  - worked-example
  - integration-test
  - fixture-pattern
  - agent-native
  - strategic-differentiator
  - multi-scenario
  - test-class-template
  - copy-paste-verification
  - cli-integration
---

# Multi-scenario test-class template for strategic-differentiator worked-example fixtures

## Context

Strategic-differentiator features — features whose value proposition is "users do X without needing Y" — need a CI-runnable worked example that proves the differentiator claim, not just documents it. D6d's `custom/<suffix>` synthetic-rule path is the canonical case: the claim is "users declare option-aware lint rules in pyproject without writing Python," and the worked-example fixture has to make that claim observable in CI.

A single happy-path scenario is insufficient. The fixture must exercise the feature's actual surface area:

- **Canonical case** with the documented full configuration (closed-value-set + severity override).
- **Reduced-configuration variant** that drops optional fields (presence-only, no `allowed_values`).
- **Override behavior** via the project's general override mechanism (`[severities]` table demotion).
- **Failure modes** the user is likely to encounter (extension unresolved, malformed pyproject).
- **Machine-readable output** an agent will consume (SARIF rules catalog, JSON params discriminators).

The naive shape is one test function per scenario in a flat module, but that loses the structure that lets a future reader (or agent) understand which surface each test covers. The multi-scenario test-class template makes the structure visible at the class-name level: one class per surface, one or two tests per class, with the class docstring explicitly naming what's under test.

The template emerged from the D6d new-U3 9-reviewer ce:review pass (2026-05-21) where multiple reviewers converged on the same structural improvements:

- agent-native reviewer flagged 4 missing surfaces (params dict, extension_unresolved, SARIF catalog, error paths).
- testing reviewer flagged 5 missing assertions across the existing happy-path scenarios.
- maintainability + project-standards reviewers flagged that the existing TestCopyPasteContract class duplicated TestCanonicalWorkedExample without adding distinct coverage.

The follow-up commit replaced the original 4-class structure with a 6-class structure, dropped the duplicate, and added the three missing surfaces. The new structure is the template captured here.

## Guidance

**Organize a worked-example test file as one class per feature surface, with each class's docstring naming the surface explicitly. Add a module-level smoke test that catches fixture-tree drift at collection time.**

The canonical layout, with the D6d new-U3 fixture as the worked example:

```
test_<feature>_example.py
├── (module docstring)                    — feature description + fixture overview
├── _module-level path constants          — single-source the fixture paths
├── _module-level identity constants      — _RULE_ID, _FIXTURE_RULE_SUFFIX, _FIXTURE_OPTION
├── _run_<cli>(...) helper                — centralized invocation with catch_exceptions=False
├── _run_<cli>_raw(...) helper            — separate helper for exit-2 paths
├── _<entity>_for(...) extractors         — parsers for finding/warning/output shapes
│
├── class TestCanonical<Feature>          — happy path with documented full config
├── class Test<Reduced>Variant            — happy path with one optional field dropped
├── class TestSeverityOverrideVia...      — overlay/override behavior
├── class TestExtensionUnresolvedWarning  — feature-specific error path (runtime warning)
├── class TestConfigErrorPaths            — fixture-misconfiguration exit-2 paths
├── class Test<Format>FormatExposes...    — machine-readable output (SARIF, JUnit, etc.)
│
└── def test_fixture_<root>_structure_is_intact()  — module-level smoke at collection time
```

**Single-source the fixture identity.** Extract three module-level constants:

```python
_FIXTURE_RULE_SUFFIX = "audit-required"
_FIXTURE_OPTION = "example.audit_level"
_RULE_ID = f"custom/{_FIXTURE_RULE_SUFFIX}"
```

These appear in TOML overlay strings, in finding assertions, and in spec-level contracts. A fixture rename touches only the constants; every test follows automatically. Three repetitions of the same literal string in the same test file is the rule-of-thumb extraction trigger.

**Centralize the CLI invocation with two helpers, not one.** The happy-path helper asserts `exit_code in (0, 1)`; the raw helper does not. Both pass `catch_exceptions=False` per [[clirunner-catch-exceptions-false-explicit-discipline-2026-05-21]].

```python
def _run_lint(pyproject, *, extra_args=(), format_="json"):
    """Asserts exit_code in (0, 1). Use for happy paths + warning paths."""
    ...

def _run_lint_raw(pyproject, *, extra_args=()):
    """No exit-code post-condition. Use for exit-2 (malformed config) paths."""
    ...
```

This separation matters because the exit-2 path is fundamentally different. The happy-path helper's `assert exit_code in (0, 1)` would mask a regression where a deliberately-broken config silently succeeded. Two helpers, one contract each.

**Per-class scope rules:**

- **Canonical** — the test asserts on EVERY agent-native field: `rule_id`, `severity`, `location_kind`, `location_file`, `violation_kind`, `params['option']`, `params['actual_value']` (when applicable), plus `runtime_warnings == []` to catch silent-warning regression. This is the spec-level contract for the fixture; every other scenario assumes this passes and tests one variation.
- **Reduced** — only the assertions that differ from canonical. Don't re-assert the full per-finding shape; that's the canonical's job.
- **Override** — assertions on the OVERRIDE-AFFECTED field (e.g., `severity` post-demotion) AND `exit_code` (because the override usually changes the gate behavior).
- **Error path (runtime warning)** — `len(findings) == 0` + exactly-one warning in `runtime_warnings` with the right `category` + `rule_id`.
- **Error path (exit-2)** — `exit_code == 2` + structured error code substring in `stderr` (e.g., `error[lint-pyproject-config-invalid]:`) + the offending key/value substring in `stderr` for triage.
- **Machine-readable format** — assertions on the SARIF/JUnit/etc. structural keys agents read. Don't re-test the rule's behavior; test the FORMAT shape.

**Module-level smoke test.** A bare `def test_<fixture>_structure_is_intact()` outside any class catches fixture-tree drift at collection time. Each `assert _FIXTURE_<X>.is_file()` uses a module-level constant — a rename updates the constant and the smoke follows. This is the "fast-fail at collect-time" discipline applied to fixtures.

**Pin the violation_kind ↔ identifying-field pairing per finding.** Set-equality assertions like `{f["violation_kind"] for f in findings} == {KIND_A, KIND_B}` leave swap-regressions invisible. Pin each finding individually:

```python
by_method = {_method_name(f): f for f in custom}
assert by_method["BareAudit"]["violation_kind"] == _KIND_ABSENT
assert by_method["DisallowedAudit"]["violation_kind"] == _KIND_VALUE_MISMATCH
```

## Why This Matters

**The differentiator claim has to be falsifiable at CI time.** A claim that lives only in README prose drifts silently. A claim that's pinned by an integration test against a self-contained fixture survives indefinitely: the fixture IS the claim. When the underlying machinery changes, the test surfaces the divergence; when the README changes, the fixture remains the canonical reference. The 6-class structure makes the surface boundaries visible to a reader scanning the file's class list — they can find the test for "what happens when X" by scanning class names rather than reading every test body.

**Agent-native consumers depend on the per-field assertions.** GitHub Code Scanning reads `runs[0].tool.driver.rules` from SARIF output to render the rule-metadata side panel. MCP runtimes parse `findings[].params['option']` to correlate findings to configuration entries without text parsing. If the worked-example test only asserts on `rule_id` and `severity`, a rename of `params['actual_value']` to `params['value']` would not surface as a test failure — but every downstream agent would break silently. The canonical scenario's job is to be the contract for the full machine-readable shape; subsequent scenarios test variations of behavior, not variations of shape.

**The error-path scenarios are the load-bearing teaching tools.** A user copy-pasting the fixture often makes one of the documented errors (typo in `rule_suffix`, parenthesized `option` value, missing required key). The error-path test classes serve double duty: they pin the CLI's exit-2 + structured-error-code contract, AND they document the expected failure modes inline. A user encountering a regex-invalid suffix can find the error path test class by name (`TestConfigErrorPaths`) and see exactly what the CLI should emit. This is the "test as documentation" property the multi-scenario structure enables.

**Duplicate test classes are worse than no test class.** The original D6d new-U3 commit had a `TestCopyPasteContract` class that was a strict assertion subset of `TestCanonicalWorkedExample`. Five reviewers independently flagged this (5-way convergence: testing T-03, maint MAINT-1, project-std PS-01, kieran KP-2, adv ADV-2). The duplicate class silently divergence-risks the canonical assertions: when the canonical class gains new assertions, the duplicate doesn't, and developers reading the duplicate get a false signal about "what's in scope." Either delete the duplicate or make it test a distinct property.

## When to Apply

Apply this template when shipping any of the following:

1. **Strategic-differentiator feature with multiple configuration paths.** D6d's `custom/<suffix>` is the canonical case — pyproject-declared rules with optional `allowed_values`, optional `severity`, mandatory `option` + `element_kinds`. Apply when the feature has 3+ user-facing knobs that can vary independently.

2. **Public-surface API exposed via a CLI** that produces machine-readable output (JSON, SARIF, JUnit). The integration test is the contract agents will read.

3. **Worked-example fixture committed under `tests/.../cli_fixtures/`** that the README references. The fixture IS the snippet; the test IS the contract.

4. **Features where misconfiguration is a likely user error path** (annotation extension not in pool, regex-invalid identifier, missing required key). The error-path classes pin the structured-error contract.

**Do NOT apply** when:

- The feature is internal-only (no public CLI surface, no machine-readable output).
- The feature has a single happy path and no meaningful variations (in which case a single test function suffices).
- The integration test is already covered by unit tests at the appropriate layer (engine + loader). Worked-example tests are integration-layer; they should not duplicate unit-layer coverage.

**Scope discipline.** The worked-example file is integration-test layer. It should NOT:

- Bypass the CLI layer to inspect engine internals directly (relocate that test to the engine/loader test file — see [[ce:review project-standards PS-02 — D6d new-U3]] for an example of this relocation).
- Reach into private attributes like `engine._loaded_specs`. Use the engine's public accessors (`engine.get_spec(rule_id)`, `engine.has_rules`).
- Duplicate fixture-construction logic that already lives in `tests/.../cli/_helpers.py` or `conftest.py`.

## Examples

### Template skeleton (apply to your feature)

```python
"""<Feature> — worked-example integration test for ``<feature-namespace>``.

Proves the differentiator end-to-end in CI: a downstream user
declares <feature> via <config-surface>, points the CLI at their
data, and sees <expected-behavior>. Satisfies <plan-requirement>
of the <plan-doc> (differentiator claim "provable in CI, not just
documentation prose").
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from <project>.cli import main as cli_main

# Module-level fixture paths
_FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "<feature>"
_FIXTURE_CONFIG = _FIXTURE_ROOT / "config.toml"

# Module-level identity constants (single-source for 10+ literal sites)
_FIXTURE_KEY = "<canonical-key>"
_ENTITY_ID = f"<prefix>/{_FIXTURE_KEY}"
_KIND_PRIMARY = "<primary-violation-kind>"
_KIND_SECONDARY = "<secondary-violation-kind>"


def _run_cli(
    config: Path,
    *,
    extra_args: tuple[str, ...] = (),
    format_: str = "json",
) -> tuple[int, dict[str, Any], str, str]:
    """Centralized invocation. catch_exceptions=False per
    [[clirunner-catch-exceptions-false-explicit-discipline-2026-05-21]]."""
    result = CliRunner().invoke(
        cli_main, [...], catch_exceptions=False,
    )
    assert result.exit_code in (0, 1), (
        f"expected exit 0/1, got {result.exit_code!r}\n"
        f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
    )
    payload = (
        json.loads(result.stdout)
        if format_ in ("json", "sarif")
        else {}
    )
    return result.exit_code, payload, result.stdout, result.stderr


def _run_cli_raw(config, *, extra_args=()):
    """Use for exit-2 paths. No exit-code post-condition."""
    ...


class TestCanonicalWorkedExample:
    """The fully-configured documented happy path."""

    def test_end_to_end_produces_expected_output(self) -> None:
        # Pin EVERY agent-native field per finding.
        # Pin violation_kind ↔ identifying-field pairing per finding.
        # Pin runtime_warnings == [] (catch silent-warning regression).
        ...


class TestReducedVariant:
    """Happy path with optional fields dropped."""

    def test_<reduced-shape>_fires_on_<subset-only>(self, tmp_path):
        # Only assert on what differs from canonical.
        ...


class TestOverrideMechanism:
    """The project's general override mechanism applies to this feature."""

    def test_override_changes_<affected-field>(self, tmp_path):
        # Assert on the override-affected field AND exit_code.
        ...


class TestExpectedFailureMode:
    """Feature-specific error path (runtime warning, not exit-2)."""

    def test_<specific-misconfig>_emits_structured_warning(self, tmp_path):
        # len(findings) == 0 + exactly-one warning with the right category.
        ...


class TestConfigErrorPaths:
    """Fixture misconfiguration produces structured exit-2."""

    def test_missing_required_key_exits_2(self, tmp_path):
        # exit_code == 2 + structured error code + offending key in stderr.
        ...

    def test_invalid_regex_value_exits_2(self, tmp_path):
        ...


class TestSarifFormatExposes<Feature>:
    """Machine-readable output surfaces the entity in the structural catalog."""

    def test_sarif_runs_tool_driver_rules_includes_<entity>(self) -> None:
        # Assert on SARIF catalog shape, not on rule behavior.
        ...


def test_fixture_<root>_structure_is_intact() -> None:
    """Module-level smoke — catches fixture-tree drift at collection time."""
    assert _FIXTURE_ROOT.is_dir()
    assert _FIXTURE_CONFIG.is_file()
    # ... use the module-level path constants for every is_file() check.
```

### Per-class assertion patterns

**Canonical (pin everything):**

```python
exit_code, payload, _, _ = _run_lint(_FIXTURE_PYPROJECT)
custom = _findings_for_rule(payload, _RULE_ID)
assert len(custom) == 2

# Pin per-finding pairing — set-equality misses swap regressions.
by_method = {_method_name(f): f for f in custom}
assert set(by_method) == {"BareAudit", "DisallowedAudit"}

bare = by_method["BareAudit"]
assert bare["rule_id"] == _RULE_ID
assert bare["severity"] == "error"
assert bare["location_kind"] == "method"
assert bare["location_file"] == "example/service.proto"
assert bare["violation_kind"] == _KIND_ABSENT
assert bare["params"]["option"] == _FIXTURE_OPTION
assert "actual_value" not in bare["params"]

# ... per-finding for "DisallowedAudit" similarly ...

assert exit_code == 1
assert payload["runtime_warnings"] == []  # silent-warning regression guard
```

**Override (severity demotion to info):**

```python
exit_code, payload, _, _ = _run_lint(
    pyproject, extra_args=("--min-severity", "info"),
)
custom = _findings_for_rule(payload, _RULE_ID)
assert len(custom) == 2
for f in custom:
    assert f["severity"] == "info"
# Load-bearing: exit_code == 0 because demote eliminates the gate-tripping severity.
assert exit_code == 0
```

**Runtime warning (zero findings + structured warning):**

```python
custom = _findings_for_rule(payload, _RULE_ID)
assert len(custom) == 0
warnings = [
    w for w in payload["runtime_warnings"]
    if w["category"] == "<feature>_extension_unresolved"
]
assert len(warnings) == 1
assert warnings[0]["rule_id"] == _RULE_ID
assert warnings[0]["message"]  # non-empty
```

**Exit-2 (structured error code):**

```python
exit_code, _, stderr = _run_lint_raw(pyproject)
assert exit_code == 2
assert "error[lint-pyproject-config-invalid]:" in stderr
assert "<expected-key-or-value-substring>" in stderr  # triage signal
```

**SARIF catalog (machine-readable contract):**

```python
exit_code, payload, _, _ = _run_lint(pyproject, format_="sarif")
assert payload["version"] == "2.1.0"
rules = payload["runs"][0]["tool"]["driver"]["rules"]
rule_ids = {r["id"] for r in rules}
assert _RULE_ID in rule_ids
synthetic_entry = next(r for r in rules if r["id"] == _RULE_ID)
assert synthetic_entry["name"] == _RULE_ID  # or the contract's name field
```

## Related

- [[clirunner-catch-exceptions-false-explicit-discipline-2026-05-21]] — companion: the CLI invocation discipline that the `_run_lint` helper in every scenario class depends on. The 3-way reviewer convergence that surfaced this discipline emerged from the same D6d new-U3 ce:review pass.
- documented-api-recipe-verify-runnable-2026-05-19 — companion: the README-snippet runnability discipline that the worked-example fixture satisfies. Where that doc covers the "API snippets must be runnable" claim at the README level, this doc covers the integration-test STRUCTURE that pins the claim in CI.
- [[dict-shaped-message-template-multi-arm-rule-violation-kind-2026-05-19]] — companion: the multi-arm dict-shaped message template pattern. The `violation_kind` discriminator the canonical scenario pins per-finding is documented at that doc's level; this doc covers the test-class STRUCTURE that pins each arm.
- [[expose-finding-params-lint-json-sarif-agent-native-2026-05-19]] — companion: the `params` dict agent-native discrimination pattern. The canonical scenario's `params['option']` + `params['actual_value']` assertions are the test-level pin of that pattern.
- [[empirical-parity-gate-surfaces-latent-helper-bug-at-implementation-time-2026-05-18]] — sibling: a different test-structure pattern (parity-gate vs worked-example). Parity gates compare against a reference implementation; worked examples assert internal contract. Both serve "latent bug surfaces at CI time"; choose based on whether a reference implementation exists.
- ce-review-convergence-rescues-sub-threshold-findings-2026-05-17 — meta-pattern: the multi-reviewer convergence that surfaced the template's gaps. The 5-way convergence on TestCopyPasteContract removal + the 4-way convergence on agent-native field assertions are concrete instances.
- [[cli-fixture-proto-hygiene-must-satisfy-builtin-packs-2026-05-13]] — sibling: the on-disk fixture itself must be hygienic against the default BUILTIN_PACKS profile. The worked-example fixture works under `--profile default` AND has no incidental findings from unrelated rules (the canonical fixture's `[severities]` table demotes `imports/unused` for this reason).
- Anchor commit: D6d new-U3 ce:review follow-up (2026-05-21, `c8ff42d`). See `tests/schema/lint/cli/test_d6d_custom_annotation_example.py` for the canonical 6-class structure (canonical, presence-only, severity-override, extension-unresolved, config-error-paths, sarif-format) + the `test_fixture_proto_root_structure_is_intact` module-level smoke.
