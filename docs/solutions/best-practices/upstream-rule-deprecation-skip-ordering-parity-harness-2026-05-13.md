---
title: "Skip parity tests for upstream-deprecated rules before subprocess invocation, not inside the assertion function"
date: 2026-05-13
category: best-practices
module: tests/parity
problem_type: best_practice
component: testing_framework
severity: medium
applies_when:
  - "A parity test harness invokes an external tool that can deprecate rules independently of your local tool's release cadence"
  - "Your tool retains a rule that the upstream tool has deprecated (product judgment divergence, not behavioral divergence)"
  - "The external tool's deprecated-rule invocation returns a non-success exit code (e.g., buf's 'resultRules was empty' / exit 1)"
  - "The harness has both a subprocess exit-code guard and a deprecated-rule skip mechanism (the two interact)"
tags:
  - buf-parity
  - deprecated-rules
  - pytest-skip
  - subprocess
  - parity-harness
  - skip-ordering
  - import-no-weak
  - external-tool
  - cross-tool-divergence
---

# Skip parity tests for upstream-deprecated rules before subprocess invocation

## Context

In a cross-tool parity test harness — protokit's `tests/parity/`
exercises every protokit lint rule against its `source_spec="buf:<ID>"`
equivalent — the upstream tool may deprecate rules that the local
tool retains.

Specifically: **buf v1.69.0 deprecated `IMPORT_NO_WEAK`** (verified
via `buf config ls-lint-rules --include-deprecated --format json`:
`categories: []`, `deprecated: true`). Protokit retained
`imports/no-weak` because the `weak` import keyword is still in the
protobuf descriptor format — buf's deprecation reflects buf's product
judgment, not a change in the underlying protobuf semantics.

When the harness invokes `buf lint` with a `buf.yaml` containing
`use: [IMPORT_NO_WEAK]`, buf exits 1 with stderr:

```text
Failure: it looks like you have found a bug in buf. Please file an
issue at https://github.com/bufbuild/buf/issues and provide the
command you ran, as well as the following message: resultRules was
empty
```

The subprocess exit-code guard (see
[[subprocess-exit-code-validation-test-harness-2026-05-13]]) correctly
treats this as a buf-side failure. But the test should not fail —
the rule is upstream-deprecated, not divergent — it should **skip
gracefully** with a reason naming the deprecation.

The subtle requirement: the skip must happen **before** the buf
subprocess is invoked. If the skip lives inside `assert_parity` (after
buf has already been called), the exit-code guard fires first and
the test fails with a misleading
`"buf lint exited 1 (expected 0 or 100)"` message before reaching
the skip-on-deprecation logic.

## Guidance

1. **Maintain a registry of upstream-deprecated rules** as a module-
   level `frozenset[str]` of upstream rule IDs, with inline
   documentation citing the upstream version that deprecated each
   rule and the reason the local tool retains it:

   ```python
   #: Buf rules deprecated upstream. Invoking buf lint with these
   #: rules triggers "resultRules was empty" (exit 1) rather than
   #: a clean run. Protokit retains imports/no-weak because the
   #: proto2 ``weak`` import keyword is still in the descriptor
   #: format; buf's deprecation reflects buf's product judgment.
   _BUF_DEPRECATED_RULES: frozenset[str] = frozenset({"IMPORT_NO_WEAK"})
   ```

2. **Provide a `skip_if_<upstream>_deprecated(upstream_id, local_id)`
   helper** that calls `pytest.skip()` with a human-readable reason
   string:

   ```python
   def skip_if_buf_deprecated(buf_rule_id: str, protokit_rule_id: str) -> None:
       """Skip the current test cleanly when buf_rule_id is upstream-deprecated.

       Call BEFORE any subprocess invocation. Skipping early avoids buf
       returning exit 1 with "resultRules was empty" — which the
       run_buf_lint exit-code guard surfaces as a failure.
       """
       if buf_rule_id in _BUF_DEPRECATED_RULES:
           pytest.skip(
               f"buf:{buf_rule_id} is deprecated in the pinned buf version "
               f"(categories=[], deprecated=true); protokit's "
               f"{protokit_rule_id!r} is protokit-only for this buf pin. "
               f"See _BUF_DEPRECATED_RULES in tests/parity/conftest.py."
           )
   ```

3. **Call the helper at the TOP of every per-rule `test_parity`
   method, before any subprocess invocation.** Not inside
   `assert_parity` (too late — buf has already been called and the
   exit-code guard has already fired):

   ```python
   def test_parity(self, rule_id, ..., rule_id_map, ...):
       buf_rule_id = rule_id_map[rule_id]
       skip_if_buf_deprecated(buf_rule_id, rule_id)   # <-- BEFORE any subprocess
       fixture_dir = fixtures_root / fixture_subdir
       protokit_findings = run_protokit_lint(fixture_dir, proto_relpath)
       buf_findings = run_buf_lint(buf_binary, fixture_dir)
       assert_parity(...)
   ```

4. **Document the deprecation in the LOCAL rule's docstring** with a
   pointer at the deprecation registry, so the next reader of the
   rule module knows the rule is protokit-only for this buf pin and
   where to look:

   ```python
   def check_no_weak_imports(ctx: FileLintContext) -> None:
       """Fire on every ``import weak "...";`` declaration in the file.

       **Buf-parity status:** As of buf v1.69.0, ``IMPORT_NO_WEAK`` is
       *deprecated upstream* (``categories=[]``, ``deprecated=true``).
       The protokit rule is retained because the ``weak`` import keyword
       is still in the descriptor format. The parity test harness at
       ``tests/parity/conftest.py`` skips this rule via
       ``_BUF_DEPRECATED_RULES`` rather than misreporting the upstream-
       deprecation as drift.
       """
   ```

## Why This Matters

Without the **skip-before-subprocess** discipline, the interaction
between the new exit-code guard and the deprecated-rule skip creates
a catch-22:

- The exit-code guard correctly fires on buf's exit 1 for
  `IMPORT_NO_WEAK`.
- The skip inside `assert_parity` never gets reached because the
  guard already failed the test.
- The CI failure reports `"buf lint exited 1 (expected 0 or 100)"`
  with stderr `"resultRules was empty"` — accurate but misleading; the
  real diagnosis is "this rule is upstream-deprecated; we expected to
  skip."

This was discovered during D6a U8 Phase A ce:review: the exit-code
guard was added (correct fix), and the IMPORT_NO_WEAK tests
immediately started failing loudly. The fix was to extract
`skip_if_buf_deprecated` as a standalone helper and call it before
any subprocess invocation in every per-family `test_parity` method.

The two disciplines are complementary, not in tension: the exit-code
guard is what makes buf's deprecation visible (rather than letting it
silently return `[]`); the skip helper is what makes the response
graceful (skip rather than fail). Together they cover both halves of
the deprecation lifecycle.

The pattern generalizes beyond protokit ↔ buf parity. Any cross-tool
parity harness — language linter ↔ another linter, code-coverage tool
↔ another tool, formatter ↔ formatter — has the same potential
divergence between local-tool retention and upstream tool deprecation,
and the same ordering requirement.

## When to Apply

Apply this discipline whenever **all** of these conditions hold:

1. A cross-tool parity test invokes an external tool via subprocess.
2. The tools have independent release cadences and may diverge on
   which rules they retain.
3. The external tool's response to a deprecated-rule invocation is
   a non-success exit code (not a clean "this rule is deprecated"
   message on stdout).
4. The harness has a subprocess exit-code guard that would fail the
   test on the non-success exit code.

When all four hold, the skip-before-subprocess pattern is required.
If condition 4 doesn't hold (no exit-code guard yet), the pattern is
still recommended for future-proofing — adding the exit-code guard
later will then "just work" without needing to refactor every test
module's skip ordering.

## Examples

The full pattern in protokit's harness, with all the call sites
that depend on it:

```python
# tests/parity/conftest.py — module-level registry + helper

_BUF_DEPRECATED_RULES: frozenset[str] = frozenset({"IMPORT_NO_WEAK"})


def skip_if_buf_deprecated(buf_rule_id: str, protokit_rule_id: str) -> None:
    if buf_rule_id in _BUF_DEPRECATED_RULES:
        pytest.skip(
            f"buf:{buf_rule_id} is deprecated in the pinned buf version "
            f"(categories=[], deprecated=true); protokit's "
            f"{protokit_rule_id!r} is protokit-only for this buf pin. "
            f"See _BUF_DEPRECATED_RULES in tests/parity/conftest.py."
        )
```

Every per-family test module's `test_parity` follows the same
ordering — skip first, subprocess second:

```python
# tests/parity/test_parity_imports.py
class TestParityImports:
    @pytest.mark.parametrize(...)
    def test_parity(
        self, rule_id, fixture_subdir, proto_relpath, expected_fires,
        buf_binary, fixtures_root, rule_id_map, parity_exceptions,
    ):
        buf_rule_id = rule_id_map[rule_id]
        skip_if_buf_deprecated(buf_rule_id, rule_id)   # <-- BEFORE subprocesses
        fixture_dir = fixtures_root / fixture_subdir
        protokit_findings = run_protokit_lint(fixture_dir, proto_relpath)
        buf_findings = run_buf_lint(buf_binary, fixture_dir)
        assert_parity(...)
```

The same ordering is required in `test_parity_naming.py`,
`test_parity_enum.py`, `test_parity_file.py`, and
`test_parity_package.py` — every per-family test module — so a future
buf deprecation in any rule family is covered without needing
per-module refactoring.

When the next buf release deprecates a new rule (e.g., a future buf
v1.80.0 might deprecate `IMPORT_NO_PUBLIC`), the update is a
one-liner:

```python
_BUF_DEPRECATED_RULES: frozenset[str] = frozenset({
    "IMPORT_NO_WEAK",      # buf v1.69.0
    "IMPORT_NO_PUBLIC",    # buf v1.80.0 (hypothetical)
})
```

Plus a docstring update on `check_no_public_imports` mirroring the
`check_no_weak_imports` template. No other code changes needed.

## Related

- [[subprocess-exit-code-validation-test-harness-2026-05-13]] —
  direct companion. That doc establishes the exit-code guard that
  surfaces upstream-deprecated invocations as failures; this doc
  establishes the skip mechanism that makes those failures graceful.
  The two are paired: exit-code guard makes deprecation visible;
  skip-before-subprocess makes the response correct.
- [[buf-parity-divergence-documentation-discipline-2026-05-13]] —
  the sibling discipline for a different class of divergence.
  Divergence-discipline covers cases where protokit and buf
  intentionally produce different findings on the same input (e.g.,
  `file/syntax-specified` on explicit-proto2). Upstream-deprecation
  covers cases where buf no longer ships the rule at all. The two
  taxonomies are: **behavioral divergence** (both tools have the
  rule, they disagree on when it fires — use `_PARITY_EXCEPTIONS` +
  four-site documentation) vs. **lifecycle divergence** (only one
  tool has the rule — use `_BUF_DEPRECATED_RULES` + per-test
  skip). When in doubt, classify: does the rule still exist
  upstream? If yes → behavioral divergence; if no → lifecycle
  divergence.
- [[audit-wire-format-before-claiming-sibling-parity-2026-05-03]] —
  the planning-time parity audit discipline. This doc is the
  runtime / harness enforcement complement. The planning-time audit
  catches divergences before implementation; this doc handles
  upstream deprecations that surface after implementation.
- Commit `c270489` — Phase A: `_BUF_DEPRECATED_RULES` set existed
  but the skip logic was inside `assert_parity`, which raced with
  the exit-code guard.
- Commit `5eba36b` — ce:review follow-up: extracted
  `skip_if_buf_deprecated` as a standalone helper called at the top
  of each `test_parity` method; updated `imports.py:check_no_weak_imports`
  docstring with the deprecation notice and a pointer at the registry.
- `tests/parity/conftest.py:113-127` — `_BUF_DEPRECATED_RULES`
  registry with inline documentation.
- `tests/parity/conftest.py:251-266` — `skip_if_buf_deprecated`
  helper.
- `src/protokit/schema/lint/rules/imports.py` —
  `check_no_weak_imports` docstring with the deprecation notice.
- [[cross-file-pin-regex-anchor-structure-not-annotation-token-2026-05-13]] —
  the test-layer regex discipline that keeps the drift-check
  infrastructure (which enforces the pinned buf version across cli.py,
  the CI tarball URL, and the sha256.txt URL) robust against
  legitimate annotation refactors. Both this doc and the cross-ref
  doc describe disciplines that keep the parity infrastructure
  honest as it evolves: this doc covers upstream rule lifecycle
  (when buf deprecates rules); the cross-ref doc covers the test
  regex that anchors on the pin constant whose buf version drives
  the deprecation check.
