---
title: "New parametrized matrix tests for a wire-format variant must inherit the sibling class's schema validators"
date: 2026-05-12
category: docs/solutions/best-practices
module: protokit.schema.lint
problem_type: best_practice
component: testing_framework
severity: high
applies_when:
  - "A new parametrized test class covers a new variant of an existing wire format (SARIF, JUnit XML, JSON Schema, OpenAPI)"
  - "The sibling test class uses a schema-validator fixture (sarif_validator, junit_validator, JSON Schema, XSD) in its parametrized cells"
  - "The plan or specification explicitly requires schema validation for the new variant"
tags:
  - parametrized-tests
  - schema-validation
  - sarif-validator
  - junit-validator
  - matrix-tests
  - test-coverage
  - protokit-lint
---

# New parametrized matrix tests for a wire-format variant must inherit the sibling class's schema validators

## Context

When a feature adds a new variant to an existing wire format — a new SARIF `propertyBag` entry, a new `<system-out>` line shape, a new JSON Schema array, a new XML element type — the natural test pattern is to add a new parametrized class alongside the existing ones. The trap is that pytest does not inherit fixture *usage* automatically. A fixture declared at module scope is available, but it must be explicitly listed in each test method's signature to actually run. A new test class that copies the parametrize decorator and assertion shape from a sibling but omits the validator fixture parameter from each method's signature produces a test class that asserts field presence without validating structural correctness.

In this codebase, U5 created `tests/test_builtin_lint_runtime_warnings.py` as a new file containing two parametrized matrix classes — `TestLintJunitRuntimeWarningSystemOut` and `TestLintSarifRuntimeWarningProperties` — covering the four `LintRuntimeWarning` categories rendered through `lint_junit` and `lint_sarif`. The sibling file `tests/test_builtin_lint_formatter.py` already had `junit_validator` (Apache Ant XSD via `xmlschema`) and `sarif_validator` (SARIF 2.1.0 schema via `jsonschema`) fixtures declared at module scope and used in every parametrized cell of `TestLintJunit` / `TestLintSarif`. The new U5 file did not import or use these fixtures; instead, it used `ET.fromstring(out)` (XML well-formedness only) and direct JSON key indexing — both of which pass on output that is well-formed but schema-invalid.

Plan U5 line 651 explicitly required schema validation. The U5 ce:review caught the gap as two P1 findings (testing T-U5-01 at 0.95 + T-U5-02 at 0.92), and the follow-up commit added the validator fixtures + calls to every cell.

## Guidance

### When adding a parametrized class for a new wire-format variant, inherit the validator fixture by listing it in every method signature

```python
import jsonschema
import xmlschema


@pytest.fixture(scope="module")
def junit_validator() -> xmlschema.XMLSchema:
    """Vendored Apache Ant JUnit xsd loaded once per module."""
    return xmlschema.XMLSchema(str(_JUNIT_XSD))


@pytest.fixture(scope="module")
def sarif_validator() -> jsonschema.Draft7Validator:
    """Vendored SARIF 2.1.0 schema loaded once per module."""
    with open(_SARIF_SCHEMA) as f:
        return jsonschema.Draft7Validator(json.load(f))


def _validate_junit(validator: xmlschema.XMLSchema, xml: str) -> None:
    ET.fromstring(xml)  # well-formedness first
    validator.validate(xml)


class TestLintSarifRuntimeWarningProperties:
    @pytest.mark.parametrize("category", _CATEGORIES)
    def test_category_renders_in_runs_properties(
        self, category: str,
        sarif_validator: jsonschema.Draft7Validator,  # ← list the fixture
    ) -> None:
        report = LintReport(
            runtime_warnings=(warning_for_category(category),),
        )
        doc = json.loads(lint_sarif(report, _ctx()))
        sarif_validator.validate(doc)  # ← run the validator on every cell
        # Then specific-key assertions for the new variant's shape:
        rw = doc["runs"][0]["properties"]["runtime_warnings"]
        assert rw[0]["properties"]["category"] == category
```

### Run the validator on every parametrized cell — not just one representative

A test class that runs the validator on one cell but not the others provides false coverage. Each cell exercises a different category / shape / level; a schema gap in one cell does not surface from a green run of another. The cheap fix is to put the validator call before the specific-key assertions in every test method.

### Add an explicit "mixed" test case — new shape variant + existing shape variant in the same document

The single highest-value test for a new variant is the *mixed* scenario: a document that exercises BOTH the existing shape and the new variant in the same payload. This is the scenario most likely to fail silently — each path is tested independently in isolation, but their interaction under the same input is a distinct code path. The mixed test catches:

- The validator accepting either shape standalone but rejecting their combination
- Output ordering invariants between the two emission paths
- Interference patterns (the new emission inadvertently mutating state the existing emission depends on)

In the snippets below, ``_ctx()`` is shown as a free function for readability — in the actual codebase it lives as ``def _ctx(self) -> FormatterContext`` on each test class, called as ``self._ctx()``. Substitute the form your test layout uses.

```python
def test_sarif_runtime_warnings_and_findings_coexist(
    self, sarif_validator: jsonschema.Draft7Validator,
) -> None:
    """Validate a SARIF document carrying BOTH findings and runtime_warnings."""
    # The actual test passes a concrete ``LintFinding`` tuple — abbreviated
    # here as ``(_some_finding,)``. The point of the snippet is the
    # validator call on a document that carries BOTH shapes.
    report = LintReport(
        findings=(_some_finding,),                                       # existing shape
        runtime_warnings=(warning_for_category("rule_exception"),),       # new shape
    )
    doc = json.loads(lint_sarif(report, _ctx()))
    sarif_validator.validate(doc)
    # Channel separation invariant: findings in results, warnings in properties.
    assert len(doc["runs"][0]["results"]) > 0
    assert len(doc["runs"][0]["properties"]["runtime_warnings"]) == 1
```

### Treat plan-explicit validator requirements as a checklist item, not a docstring

When the plan says "validate against the strict SARIF/JUnit validator", the implementing commit should include the validator call in every parametrized cell. The U5 ce:review caught this gap because two reviewers — the testing reviewer and the agent-native reviewer's OBS-2 — independently checked the plan against the implementation. A pre-commit grep for `sarif_validator\|junit_validator` against the new test file would have surfaced the gap immediately.

## Why This Matters

A property-bag-style SARIF extension is technically valid by spec — `runs[].properties` is a generic propertyBag, and adding `properties.runtime_warnings` is a permitted extension. But "permitted" is not the same as "correctly shaped". Strict SARIF consumers (GitHub Code Scanning, `sarif-tools`, Azure DevOps SARIF import) may reject the document if the shape inside the extension drifts — for example, if a future delivery accidentally renames `properties.subcategory` to `properties.sub_category`, or moves `message` to the entry root instead of `message.text`. A matrix test that asserts only specific keys catches drift on those keys but not on drift elsewhere in the document. The validator catches structural drift holistically.

The cost of adding the validator to each parametrized cell is one `validator.validate(parsed)` call — the validator is loaded once at `scope="module"`, so per-cell cost is `O(parse + jsonschema-walk)`. The cost of *not* validating is silent acceptance of a document shape that downstream consumers will reject in production, with no test signal until a user reports it. In the U5 ce:review case, the gap survived from the U5 feat commit (`816a3b9`) through the entire pre-review window — only ce:review caught it.

The "mixed" test case pinned an additional invariant: that the two emission paths do not interfere with each other's output. Each path was unit-tested in isolation in the existing class; the mixed scenario was unique to the new variant and would have gone untested without the explicit test.

## When to Apply

- Every time a new test matrix is created for a wire format (SARIF, JUnit XML, JSON Schema, OpenAPI, GraphQL) that already has a schema validator in a sibling test file
- When extending an existing wire format with a new embedded shape (a new array field, a new object structure, a new XML element type) — the extension is exactly what needs schema validation, because the base validator may accept the extension point without validating its contents
- When the plan or specification explicitly mentions schema validation as a test obligation — treat it as a checklist item that must appear in the implementation before the ce:review stage
- When creating a new test file alongside an existing one that has schema validation — import the validator fixtures rather than re-deriving the test approach from scratch
- When adding a "mixed" test that combines a new variant with an existing one in the same document — the combined document is the highest-risk path and benefits most from holistic validation

## Examples

### Before — U5 initial commit, structural assertions without schema validation

```python
class TestLintSarifRuntimeWarningProperties:
    @pytest.mark.parametrize("category", _CATEGORIES)
    def test_sarif_has_runtime_warnings_array(self, category: str) -> None:
        report = LintReport(runtime_warnings=(warning_for_category(category),))
        doc = json.loads(lint_sarif(report, _ctx()))
        # Specific-key assertions only — no schema validation:
        rw = doc["runs"][0]["properties"]["runtime_warnings"]
        assert len(rw) == 1
        assert rw[0]["properties"]["category"] == category
```

A regression that placed the array at the wrong path (`runtimeWarnings` vs `runtime_warnings`) would fail the assertion with `KeyError` — caught. A regression that *added* an extra field with wrong nesting elsewhere in the document would pass the assertion silently. The validator is what catches the latter.

### After — U5 ce:review follow-up, validator on every cell

```python
class TestLintSarifRuntimeWarningProperties:
    @pytest.mark.parametrize("category", _CATEGORIES)
    def test_sarif_runtime_warning_schema_valid(
        self,
        sarif_validator: jsonschema.Draft7Validator,
        category: str,
    ) -> None:
        report = LintReport(runtime_warnings=(warning_for_category(category),))
        doc = json.loads(lint_sarif(report, _ctx()))
        # Schema validation FIRST — holistic structural check:
        sarif_validator.validate(doc)
        # Then specific-key assertions for the new variant's shape:
        rw = doc["runs"][0]["properties"]["runtime_warnings"]
        assert len(rw) == 1
        assert rw[0]["level"] == "warning"
        assert rw[0]["properties"]["category"] == category
        assert rw[0]["properties"]["subcategory"] == "runtime"
```

### The mixed test — combined document

```python
def test_compile_warning_and_runtime_warning_coexist_in_system_out(
    self, junit_validator: xmlschema.XMLSchema,
) -> None:
    """Compile-diagnostic lines and runtime-warning lines share the
    single <system-out> body per JUnit XSD. The documented ordering is
    compile diagnostics first, then runtime warnings — pin both
    presence and ordering so a future refactor cannot reverse them
    silently.
    """
    from protokit.schema.compile import LintCompileDiagnostic
    diag = LintCompileDiagnostic(
        level="warning",
        message="protoxy unavailable, falling back to protoc",
        category="protoxy_fallback",
    )
    rt_warning = warning_for_category("rule_exception")
    report = LintReport(
        diagnostics=(diag,),
        runtime_warnings=(rt_warning,),
    )
    out = lint_junit(report, _ctx())
    _validate_junit(junit_validator, out)  # ← validates the combined document
    root = ET.fromstring(out)
    system_out = root.find("system-out")
    text = system_out.text or ""
    # Compile diagnostic uses ``{level} [{category}]:`` shape:
    assert "warning [protoxy_fallback]:" in text
    # Runtime warning uses ``[{category}] {message}`` shape:
    assert "[rule_exception]" in text
    # Compile diagnostic precedes runtime warning:
    compile_idx = text.index("[protoxy_fallback]")
    runtime_idx = text.index("[rule_exception]")
    assert compile_idx < runtime_idx
```

## Related

- [[audit-wire-format-before-claiming-sibling-parity-2026-05-03]] — the planning-time discipline of asserting wire-format parity; this learning is the test-time counterpart that closes the loop
- [[cross-format-enum-string-parity-2026-05-08]] — value-form correctness across sibling formatters; complementary to this doc's structural-validation focus
- [[pytest-static-analysis-gate-ratchet-2026-05-02]] — the ratchet pattern; schema validators are an analogous quality gate for wire-format correctness rather than for code correctness
- [[fail-closed-ci-matrix-coverage-meta-test]] — complementary check on a different layer of matrix correctness. This doc catches **Python-side fixture-inheritance gaps** in parametrized matrix tests (a new sibling class that omits the validator parameter from method signatures runs without structural assertions). The companion doc catches **CI-yaml-side coverage gaps** (a `@pytest.mark.skipif`-gated test that runs on no cells because the matrix evolved). Together they cover the two ways a matrix can silently fail to exercise what it claims to.
