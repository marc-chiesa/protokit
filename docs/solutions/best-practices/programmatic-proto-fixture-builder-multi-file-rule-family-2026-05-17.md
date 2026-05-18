---
title: "Programmatic `dict[filename, source]` proto-fixture builder for multi-file rule families — avoids 26+ near-identical static .proto files"
date: 2026-05-17
category: docs/solutions/best-practices
module: tests/schema/lint/rules/fixtures
problem_type: best_practice
component: testing_framework
severity: medium
applies_when:
  - "A lint or analyzer rule family fires on relationships between 2+ .proto files in the same package (cross-file rules like PACKAGE_SAME_*, package/same-directory)"
  - "The test matrix is a Cartesian product (N rules × M scenario shapes) producing 10+ near-identical .proto fixtures"
  - "The fixture set must be extended whenever a new attribute/rule is added to the rule family"
  - "Fixture compilation invokes a real compiler (protoxy/protoc/buf) that requires syntactically valid proto3 source"
related_components:
  - tooling
tags:
  - proto-fixtures
  - programmatic-fixtures
  - multi-file-rules
  - symbol-collision
  - fixture-builder
  - ascii-only
  - protokit-lint
---

# Programmatic `dict[filename, source]` proto-fixture builder for multi-file rule families — avoids 26+ near-identical static .proto files

## Context

When a rule family requires many near-identical `.proto` fixture files — as the R7 PACKAGE_SAME_* family does (7 rules × 3 base scenario shapes × 2 modes = ~42 combinations plus 5 edge-case shapes) — committing static `.proto` files dwarfs the rule code, obscures cross-rule symmetry, and creates maintenance rot whenever rule-id namespace conventions or package naming evolve. Static fixtures also require a parallel update whenever any of the 7 attrs is renamed.

D6b U4b introduced a programmatic builder module at `tests/schema/lint/rules/fixtures/package_same/proto_templates.py` that generates all source files as Python `dict[filename, source]` objects. The approach was scaled up from the inline-fixture-string pattern used in `tests/schema/lint/rules/options/test_deprecated_replacement.py` (which suffices for 5 single-file rules), generalized for the cardinality of the 7-rule cross-file family.

## Guidance

**Return `dict[filename, source]` from every builder.** The dict is immediately materializable into `tmp_path` via:

```python
for fname, text in sources.items():
    (tmp_path / fname).write_text(text)
```

The dict carries the filename metadata that per-rule test assertions need to identify which file produced which finding, which a flat list of source strings would not.

**Separate three layers of builder functions:**

1. *Per-attr emit helper* (e.g., `_option_line`) encapsulates type-dispatch and proto3 literal rendering (boolean `true`/`false` vs. quoted string). Any correctness constraint on the raw value belongs here as an `assert`.

2. *Base scenario builders* (`all_agree`, `mixed_value`, `mixed_presence`) — each produces an N-file package covering one scenario shape. Three shapes cover the full decision tree of the shared `_check_package_option` helper: all-declare-same, multiple-declare-different, some-declare-some-omit.

3. *Edge-case builders* — one per structural edge case (single-file package, empty package declaration, multi-package isolation, transitive import, reverse declaration order, three-distinct values). Each edge-case builder targets one specific decision arm or sort invariant in the production helper.

**Keep a LOCAL attribute tuple in the fixture builder, NOT an import from production.** `proto_templates.py` declares its own `ALL_ATTRS`, `STRING_ATTRS`, `BOOL_ATTR` constants rather than importing `_PACKAGE_SAME_OPTION_ATTR_NAMES` from production. This decouples fixture ordering from production ordering: a future re-ordering of the production tuple does NOT silently shuffle test parametrization. A separate cross-check test (`test_all_attrs_constant_matches_production`) enforces set equality between the fixture tuple and the production tuple — drift is caught explicitly, not silently.

**Omit stub messages from multi-file same-package fixtures.** proto3 accepts option-only files. If `message Stub {}` is added to each file in a 3-file same-package scenario, all three declare the fully-qualified symbol `<package>.Stub`, causing a pool symbol collision that masks the disagreement detection the tests target. The `make_proto` docstring should document this explicitly. When a transitive-import scenario requires cross-file symbols, use UNIQUE message names per file (e.g., `message Stub {}` in `aa.proto` and `message Imported {}` in `b.proto`).

**Document three sub-pitfalls explicitly in the builder's module docstring:**

1. *Stub symbol collision* — see above.
2. *Fixture-ordering drift* — importing the production tuple silently couples fixture order to production order. Use a local copy + cross-check test.
3. *Compiler-incompatible escape sequences in caller-supplied values* — backslashes in proto option string values must be doubly-escaped at the proto-source level. A value like `"Acme\Sub"` silently fails to compile (the proto3 escape `\S` is invalid; the compiler returns 0 findings, which can satisfy "all-agree" tests vacuously). Reject backslash-containing values via `assert "\\" not in value` in the per-attr emit helper and direct callers to use ASCII-only test values. See [[fixture-precondition-assertion-surfaces-silent-test-2026-05-17]] for the silent-test discovery angle of this precondition.

## Why This Matters

The per-rule symmetry of a multi-rule family is the key invariant: 7 rules sharing one `_check_package_option` helper with literal-identical message templates. A test grid that does not enforce this symmetry structurally (e.g., 42 static `.proto` files with inconsistent naming, or 7 hand-written test functions per scenario) cannot catch a regression where one rule's `@lint_rule` decorator is misconfigured. The builder approach lets each test parametrize over `_ATTR_TO_RULE` — a table whose shape is verified against the production tuple — so adding a new attr to the pack without extending the test table causes an explicit failure at the table lookup.

Static fixtures also tend to drift: when a test needs to verify proto-source escape behavior for a specific attr (inner-quote, empty-package, transitive-import), the static fixture for that attr may not exist yet, prompting ad-hoc inline source strings that duplicate the basic structure without sharing cross-rule invariants. The builder encodes those invariants once (in `_option_line`) and propagates them to all scenarios.

The economics: 26+ near-identical static `.proto` files weigh ~600 lines of fixture mass; the programmatic builder is ~340 lines of Python that produces every scenario the rule family will ever need, plus assertions that catch fixture-authoring foot-guns.

## When to Apply

Apply this pattern when:

- A rule family has N >= 4 rules sharing one core helper with identical message templates.
- Tests need to cover a Cartesian product of rules × scenario shapes (N × M combinations).
- The rule family's behavior depends on multi-file compiled proto packages, so fixtures must be valid proto3 sources (not just string inputs to a parser).
- Fixture structure needs to be introspectable by the test (e.g., "a.proto declares `go_package = X`, b.proto declares `go_package = Y`") — `dict[filename, source]` makes this natural.

Do NOT use this pattern when:

- The rule operates on single-file inputs with no multi-file cross-package semantics (use inline string literals in the test instead, as in `test_deprecated_replacement.py`).
- The fixture set is small enough that static `.proto` files are readable alongside the test (rule of thumb: < 5 fixtures total).
- The fixtures need to be byte-pinned for cross-runtime equivalence testing (use checked-in static files + checksum pin, as in `_buf_smoke/recorded/CHECKSUMS.sha256`).

## Examples

**Before — static `.proto` files for a 3-file scenario:**

```
tests/schema/lint/rules/fixtures/package_same/
    mixed_value_a.proto   # go_package = "github.com/x/X"
    mixed_value_b.proto   # go_package = "github.com/x/Y"
    mixed_value_c.proto   # go_package = "github.com/x/X"
    # × 7 attrs × 3 scenario shapes = 63+ files
```

**After — programmatic builder (`proto_templates.py`):**

```python
def make_proto(*, package, options=None):
    lines = ['syntax = "proto3";']
    if package:
        lines.append(f"package {package};")
    if options:
        for attr, value in options.items():
            lines.append(_option_line(attr, value))
    # NO stub message — avoids pool symbol collision across same-package files.
    return "\n".join(lines) + "\n"


def all_agree(attr, *, value, package="smoke.all_agree",
              file_names=("a.proto", "b.proto", "c.proto")):
    return {fname: make_proto(package=package, options={attr: value})
            for fname in file_names}


def mixed_value(attr, *, values, package="smoke.mixed_value", file_names=None):
    if file_names is None:
        file_names = tuple(f"{chr(ord('a') + i)}.proto" for i in range(len(values)))
    return {fname: make_proto(package=package, options={attr: value})
            for fname, value in zip(file_names, values, strict=True)}
```

**Per-rule test parametrization (from `test_package_same.py`):**

```python
def _check_mixed_value_string(self, tmp_path: Path, attr: str) -> None:
    rule_id = _ATTR_TO_RULE[attr]
    value_x, value_y = _SAMPLE_STRING_VALUES[attr]
    sources = mixed_value(
        attr, values=(value_x, value_y, value_x),
        package=f"smoke.mv_{attr}",
    )
    report = _run_single(tmp_path, sources, rule_id, package_same)
    assert len(report.findings) == 3
```

**Cross-validation test (catches drift between builder and production):**

```python
def test_all_attrs_constant_matches_production() -> None:
    fixture_attrs = set(STRING_ATTRS) | {BOOL_ATTR}
    production_attrs = set(_PACKAGE_SAME_OPTION_ATTR_NAMES)
    assert fixture_attrs == production_attrs, (
        f"fixture coverage drifted from production: "
        f"missing {production_attrs - fixture_attrs}, "
        f"extra {fixture_attrs - production_attrs}"
    )
```

## Related

- [[fixture-precondition-assertion-surfaces-silent-test-2026-05-17]] — the precondition assertion in `_option_line` that surfaced a pre-existing silent-test bug. Companion learning to this one.
- [[per-rule-fixture-symbol-isolation-buf-v2-compile-group-2026-05-13]] — symbol-isolation discipline for buf v2 single-file fixtures. Where that learning governs symbol isolation across separately-compiled rules, this learning governs symbol isolation within multi-file same-package scenarios.
- [[capture-setup-without-dispatch-false-test-confidence-2026-05-17]] — programmatic capture-pack pattern for engine-dispatch tests. Same builder-pattern philosophy at the rule-pack level rather than the proto-source level.
- [[cli-fixture-proto-hygiene-must-satisfy-builtin-packs-2026-05-13]] — `FileDescriptorProto` programmatic construction for CLI integration tests. Complementary surface (descriptor proto vs. proto source).
- `tests/schema/lint/rules/fixtures/package_same/proto_templates.py` — the reference implementation (337 lines).
- `tests/schema/lint/rules/test_package_same.py` — full consumer with `TestPackShape`, `TestPerRuleHappyAndSadPaths`, `TestEdgeCases`, `TestInnerQuoteByteParity`, `TestAdversarialSanitization`, `TestPerRuleSeveritiesDemotion`, `TestCheckPackageOptionHelper`.
- [[empirical-parity-gate-surfaces-latent-helper-bug-at-implementation-time-2026-05-18]] — contrast: this learning governs PROGRAMMATIC fixture construction (per-test, runtime-generated, ASCII-only convenience); the D6b U6 parity gate uses COMMITTED static NDJSON snapshots (byte-pinned reference output from a real reference tool). Different fixture strategies for different verification goals. Programmatic builders verify internal self-consistency; committed snapshots verify byte-parity with an external oracle. Both are needed; neither is sufficient alone, as D6b U6 demonstrated when the parity gate caught a backslash-escape omission that the programmatic-fixture unit tests structurally could not.
