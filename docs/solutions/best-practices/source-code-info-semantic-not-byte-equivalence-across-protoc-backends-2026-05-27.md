---
title: Compare source_code_info across protoc backends by semantic mapping, not SerializeToString bytes
date: 2026-05-27
category: docs/solutions/best-practices
module: protokit.schema.compile
problem_type: best_practice
component: testing_framework
severity: medium
applies_when:
  - Writing parity tests that compare descriptor output across two protoc backends
  - Asserting on FileDescriptorProto.source_code_info content
  - Backend protoc versions differ and may encode Location.span differently
  - "Cross-backend test pinned `SerializeToString()` equality and started failing only when one backend's protoc bumped"
  - "Refactoring a `*ByteEquivalence` test class that compares descriptor wire bytes across compilers"
tags:
  - source-code-info
  - byte-equivalence
  - semantic-equivalence
  - protoc-backend-parity
  - descriptor-comparison
  - cross-backend-testing
  - location-span
  - parity-gate
  - test-invariant-granularity
related_components:
  - testing_framework
  - tooling
---

# Compare source_code_info across protoc backends by semantic mapping, not SerializeToString bytes

## Context

protokit supports two compile backends (`protoxy`, system `protoc`) and asserts cross-backend equivalence in tests so the lint engine produces the same findings regardless of which backend ran. The original equivalence test pinned **byte-equivalence** on `source_code_info.SerializeToString()` — a strong invariant that held as long as both backends shipped the same protoc version.

Different protoc versions encode `source_code_info.Location` slightly differently. protoxy 0.7.2 embeds an older protoc; the host system's protoc (whether 3.21 from apt or 25.3 from a binary release) may differ. The differences are in `Location.span` encoding (numeric packing details) and in whether protoc emits empty Locations for paths with no comments — neither of which is visible to production code, which only reads `(descriptor-path → leading_comments, trailing_comments, leading_detached_comments)` via the `leading_comment()` / `trailing_comment()` helpers.

The byte-equivalence test failed across protoc-version skew despite the production-code-visible contract being identical on both sides. The diagnostic cost was high: engineers chase phantom byte-diffs in serialized `source_code_info` payloads instead of reading the production code to understand what contract actually matters.

## Guidance

Replace `SerializeToString()` byte-equivalence with **semantic equivalence** on the contract the production code actually consumes. Build a `dict[tuple[int, ...], tuple[str, str, tuple[str, ...]]]` keyed by descriptor-path, valued by `(leading_comments.strip(), trailing_comments.strip(), tuple-of-detached.strip())`. Skip empty-value entries. Compare the two dicts.

From `tests/schema/lint/test_compile_include_source_info.py:209-235`:

```python
def _path_comment_map(
    fd: object,
) -> dict[tuple[int, ...], tuple[str, str, tuple[str, ...]]]:
    # Reduce source_code_info to the (path → comments) mapping
    # that leading_comment / trailing_comment / detached_comment
    # helpers actually consume. Both helpers strip whitespace at
    # the call site; do the same normalization here so the
    # comparison is invariant to backend-specific trailing-newline
    # encoding decisions.
    out: dict[tuple[int, ...], tuple[str, str, tuple[str, ...]]] = {}
    for loc in fd.source_code_info.location:
        key = tuple(loc.path)
        value = (
            loc.leading_comments.strip(),
            loc.trailing_comments.strip(),
            tuple(s.strip() for s in loc.leading_detached_comments),
        )
        # Only record paths that carry any comment content; backends
        # may differ on whether they emit empty Locations for
        # comment-less spans.
        if value != ("", "", ()):
            out[key] = value
    return out

protoxy_map = _path_comment_map(protoxy_fd)
protoc_map = _path_comment_map(protoc_fd)
assert protoxy_map == protoc_map
```

Three load-bearing properties:

1. **Key by descriptor-path tuple.** `loc.path` is a repeated int field that uniquely identifies which element of the descriptor tree the location refers to. `tuple(loc.path)` makes it hashable for dict-key use.
2. **Strip whitespace at extraction time.** Both production helpers (`leading_comment`, `trailing_comment`) strip at their call sites; mirror that here so backend-specific trailing-newline encoding doesn't trigger false positives.
3. **Skip empty-value entries.** Backends may legitimately differ on whether they emit a `Location` for a path with no comment content. Filtering empty values from both maps eliminates that as a false-positive source.

Rename the test class to reflect the new contract (`...ByteEquivalence` → `...SemanticEquivalence`) and update cross-references in companion tests that mentioned the class by name (e.g., `tests/schema/lint/test_compile_pool_file_names.py:30` carried a `:class:` reference that became stale on rename).

## Why This Matters

Byte-equivalence is a tempting test invariant because it's mechanical, deterministic, and one-line. But it conflates **"the production code sees the same thing"** with **"the wire encoding is identical."** Different protoc versions can produce different wire encodings of equivalent semantic content. If your production code only consumes the semantic content, your test should only assert the semantic content.

Asserting on the wire encoding ties the test to the protoc version the test author happened to run against. The test passes on one machine, fails on another, and the failure looks like a real regression when in fact the production code's behavior is identical. The diagnostic cost is high — engineers chase phantom differences in serialized bytes instead of reading the production code to understand what contract actually matters.

This pattern generalizes to any cross-backend or cross-version protobuf comparison: identify the slice of the descriptor that production code consumes, build a normalized representation of that slice, and assert on the normalized form. The companion pool-file-names cross-backend test (in `tests/schema/lint/test_compile_pool_file_names.py`) gets to keep byte-equivalence because tuple-of-strings comparison has no version-sensitive encoding — but anything involving `source_code_info`, `Options`, or extension fields should use the semantic pattern.

A related contract-shape question: this learning argues for **loosening** the granularity of a cross-backend assertion when byte-equivalence isn't load-bearing. The sibling learning [[parity-gate-must-assert-at-design-claim-granularity-2026-05-22]] argues for **tightening** the granularity when the design claim is at line-column precision but the assertion was coarser. The unifying rule: **the assertion's granularity should match the design claim's granularity, no tighter and no looser.** A byte-equivalence assertion on `source_code_info` was tighter than the design claim (which is about `leading_comment(path)` lookups); the semantic mapping matches it exactly.

## When to Apply

- Always when comparing serialized protobuf output across backend implementations or protoc versions.
- Always when comparing `source_code_info`, `Options` fields, or any descriptor field whose wire encoding has historically varied across protoc versions.
- When the production code only consumes a subset of a serialized payload's fields, assert on that subset's content, not on the full serialized bytes.
- Byte-equivalence is still fine for: tuple-of-strings comparisons, lists of `fd.name` values, anything where the comparison surface has no version-sensitive encoding.
- Does NOT apply to wire-format compatibility tests where the assertion is genuinely "the bytes on the wire are identical between version A and version B" — those exist precisely to catch wire-format drift and should stay byte-strict.

## Examples

**Before (failed cross-backend when protoc versions differed):**

```python
class TestSourceInfoDescriptorsCrossBackendByteEquivalence:
    def test_protoxy_and_protoc_produce_identical_source_code_info(
        self, tmp_path: Path,
    ) -> None:
        # ... compile with both backends ...
        assert protoxy_fd.source_code_info.SerializeToString() == (
            protoc_fd.source_code_info.SerializeToString()
        )
```

**After (semantic equivalence on the contract the consumer uses):**

```python
class TestSourceInfoDescriptorsCrossBackendSemanticEquivalence:
    def test_protoxy_and_protoc_produce_equivalent_path_comment_mapping(
        self, tmp_path: Path,
    ) -> None:
        # ... compile with both backends ...
        protoxy_map = _path_comment_map(protoxy_fd)
        protoc_map = _path_comment_map(protoc_fd)
        assert protoxy_map == protoc_map
```

The full implementation lives at `tests/schema/lint/test_compile_include_source_info.py:145-235`.

## Related

- [[parity-gate-must-assert-at-design-claim-granularity-2026-05-22]] — the complementary half of the rule. That doc argues for tightening when the assertion was coarser than the design claim; this doc argues for loosening when the assertion is stricter. Unifying rule: assertion granularity must match design-claim granularity.
- [[audit-wire-format-before-claiming-sibling-parity-2026-05-03]] — same "verify wire format before claiming parity" instinct, scoped to backend version drift.
- [[buf-parity-divergence-documentation-discipline-2026-05-13]] — same "when exact parity isn't achievable, document the divergence" family.
- [[empirical-parity-gate-surfaces-latent-helper-bug-at-implementation-time-2026-05-18]] — parity-gate pattern that this learning protects (the helper-bug detection relied on byte-equivalence only because both backends shipped the same encoder).
- [[changelog-readme-snippet-fixture-byte-equivalence-2026-05-21]] — uses byte-equivalence in a different domain (doc fixtures) where there is no version-sensitive encoding; helpful contrast.
- [[dont-pin-binary-protoc-when-test-suite-cross-checks-protoxy-2026-05-27]] — the operational counterpart that keeps both backends in lockstep so the semantic-equivalence test is the LAST resort, not the first.
- Canonical commit: `f3ecd69` ("test: cross-backend source_code_info — semantic equivalence, not byte equivalence").
