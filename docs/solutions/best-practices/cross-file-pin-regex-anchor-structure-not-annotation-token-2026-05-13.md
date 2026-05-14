---
title: "Anchor cross-file pin regexes on structure (``:[^=]+=``), not on the type-annotation token (``: str``), when both a test and a CI script grep the same Python constant"
date: 2026-05-13
category: best-practices
module: tests/test_buf_parity_pin_drift.py
problem_type: best_practice
component: testing_framework
severity: medium
applies_when:
  - "A regex or bash grep extracts a value from a Python source constant in more than one consumer (e.g., a test file + a CI workflow + a release watcher)"
  - "The matched line includes Python syntax tokens (``: str``, ``: int``, ``: Final[str]``, ``= ...``) beyond the bare value"
  - "The constant's type annotation could be legitimately refactored without changing the constant's identity or value (str → Final[str], ClassVar[str], TypeAlias-driven types)"
  - "The regex consumers are not co-located — a change to one consumer does not prompt reviewing the other"
  - "Both consumers' failure messages blame the regex pattern, not the annotation token, when the match fails"
tags:
  - regex
  - cross-file-pin
  - annotation-token
  - type-annotation
  - drift-check
  - grep
  - ci-workflow
  - python-source-parsing
  - silent-coupling
---

# Anchor cross-file pin regexes on structure, not on the type-annotation token

## Context

When a regex/grep matches a Python constant definition across multiple
independent consumers — for example, a Python test that parses `cli.py`
and a bash grep in a GitHub Actions workflow that parses the same
`cli.py` — anchoring on the literal annotation token (`: str`) creates
a silent breakage class. A future contributor's natural hardening
refactor — `str` → `Final[str]`, `: ClassVar[str]`, or an annotation
involving a type alias — silently breaks every consumer with no
compile-time or test-time signal pointing at the annotation as the
cause:

- The Python test fails with `"could not extract _BUF_PARITY_PIN
  (regex {pattern!r} found no match)"` — a diagnostic that blames
  the regex, not the annotation that changed.
- The bash grep fails with `"could not extract _BUF_PARITY_PIN from
  cli.py; aborting"` and exit 1 — again, no signal that the annotation
  is the cause.
- Neither consumer mentions "annotation" anywhere in its failure
  surface. A contributor who changes `: str` to `: Final[str]` for
  mypy strictness has to trace two separate tool failures back to the
  annotation change with no automated pointer.

This is the **silent coupling trap**: two consumers stay in lockstep
not because the coupling is enforced, but because both happen to
require the same incidental syntactic detail.

## Guidance

**Anchor multi-consumer regexes on structure, not literal annotation
tokens.** The type annotation is incidental to the pin discipline;
the load-bearing constraints are:

1. The constant's NAME (`_BUF_PARITY_PIN`).
2. The value FORMAT (the `v` prefix on the quoted version string —
   catches typos like `"1.69.0"` that would otherwise pass an
   equality check).
3. The line's overall STRUCTURE (name, then `:`, then annotation, then
   `=`, then quoted value).

The fix replaces `\s*:\s*str\s*=` with `\s*:[^=]+=`. The character
class `[^=]+` matches any annotation between `:` and `=` — `str`,
`Final[str]`, `ClassVar[str]`, even multi-line annotations within
the same line. The structural anchors (`:`, `=`, the quoted value's
opening) carry the load.

Same change in the bash consumer:

```bash
# BEFORE
grep -E '^_BUF_PARITY_PIN\s*:\s*str\s*=\s*"v[^"]+"' src/...

# AFTER
grep -E '^_BUF_PARITY_PIN\s*:[^=]+=\s*"v[^"]+"' src/...
```

The Python regex and bash grep MUST use the same line-shape contract —
add a cross-reference comment on each consumer pointing at the other
so future edits are coordinated. The contract is now:

> The constant is `_BUF_PARITY_PIN`, any annotation, value starts with `v`.

## Why This Matters

When two consumers depend on a regex matching a Python source line,
the failure mode for naive over-specification is catastrophic only
in slow-motion: the breakage doesn't surface until someone makes
a refactor that's plainly correct in isolation (`Final[str]` for
mypy strictness). The refactor passes local typing checks, lands,
and either:

- Makes the drift-check test fail with a diagnostic that points at the
  regex (technically true but unhelpful) and forces the contributor
  to trace back through the indirection layer; OR
- Breaks a CI workflow scheduled job (release watcher) that fires
  weekly, so the failure surfaces only on a future Monday with no
  obvious recent commit to point at.

Neither path provides a fast signal back to the actual cause. The
structural-anchor fix is a one-time relaxation that future-proofs
both consumers against any legal annotation refactor with zero
runtime cost.

## When to Apply

Apply this discipline whenever:

- A regex or bash grep extracts a value from a Python source constant
  in more than one consumer (test file + CI script + release watcher
  + plugin loader — wherever multiple sites parse the same line).
- The matched line includes Python syntax tokens beyond the bare value.
- The constant's type annotation is incidental to the regex's purpose
  (the regex cares about the value, not the annotation; the annotation
  is just along for the ride).

Apply the discipline ATOMICALLY across all consumers in the same
commit. A regex-relaxation fix in one consumer without the matching
fix in the other consumer maintains the silent-coupling trap at the
asymmetric site.

## Examples

The originating case is `_BUF_PARITY_PIN` in protokit, where the
constant has three consumers:

1. The Python `_CLI_PIN_RE` regex in
   `tests/test_buf_parity_pin_drift.py` — the drift-check test.
2. The bash `grep -E` in `.github/workflows/buf-release-watch.yml` —
   the release-watcher pin-extraction step.
3. (Future, Unit 9) The `protokit lint --version` output — will
   import the constant directly via Python attribute access; no
   regex required, so no annotation coupling at this consumer.

Before (commit `f81f408`):

```python
# tests/test_buf_parity_pin_drift.py
_CLI_PIN_RE = re.compile(
    r'^_BUF_PARITY_PIN\s*:\s*str\s*=\s*"(v[^"]+)"',
    re.MULTILINE,
)
```

```bash
# .github/workflows/buf-release-watch.yml
grep -E '^_BUF_PARITY_PIN\s*:\s*str\s*=\s*"v[^"]+"' src/protokit/schema/lint/cli.py
```

After (commit `b425954`):

```python
# tests/test_buf_parity_pin_drift.py
#: The annotation segment uses ``[^=]+`` so the regex tolerates any
#: shape between ``:`` and ``=`` (``str``, ``Final[str]``, etc.) —
#: the constant's annotation is incidental to the pin discipline, and
#: anchoring on the literal token ``str`` would silently break this
#: test (and the matching bash grep in buf-release-watch.yml) on a
#: future contributor's hardening pass. The ``v`` prefix on the
#: quoted value is the load-bearing anchor.
_CLI_PIN_RE = re.compile(
    r'^_BUF_PARITY_PIN\s*:[^=]+=\s*"(v[^"]+)"',
    re.MULTILINE,
)
```

```bash
# .github/workflows/buf-release-watch.yml
# Greps `_BUF_PARITY_PIN: <ANNOTATION> = "v1.69.0"` and extracts
# the quoted version. The annotation segment uses ``[^=]+`` so
# the grep tolerates any shape between ``:`` and ``=`` (str,
# Final[str], etc.) — matches the regex in
# tests/test_buf_parity_pin_drift.py so both consumers agree on
# the same line shape.
grep -E '^_BUF_PARITY_PIN\s*:[^=]+=\s*"v[^"]+"' src/protokit/schema/lint/cli.py
```

The same commit (`b425954`) also added `_CI_SHA256_RE` alongside
`_CI_PIN_RE` in the drift test, extending the multi-site discipline:
the constant + tarball URL + sha256.txt URL must all reference the
same version. Both the constant-side relaxation and the
multi-site coverage are instances of the same broader rule:
**a drift-check test's regexes must enforce exactly the contract
they care about — no more, no less.**

The verification test ran successfully against a simulated
`_BUF_PARITY_PIN: Final[str] = "v1.69.0"` annotation after the fix,
confirming the relaxation is correct.

## Related

- [[normalize-at-input-boundary-2026-05-07]] — the broader "matcher
  and source must use identical transformation policies" principle.
  That doc covers case-normalisation skew at the registry-lookup
  boundary; this doc covers regex-anchor-token coupling at the
  multi-consumer source-parsing boundary. Both are instances of
  "don't let the matcher and the source independently drift on
  incidental representational choices."
- [[matcher-backend-path-resolution-skew-silently-empties-output-2026-05-02]] —
  the foundational version of the same axiom ("matcher and source-of-
  truth must use identical resolution policies"). The new doc extends
  the axiom to regex-pattern design: when a regex's specificity exceeds
  the contract it's meant to enforce, every future legal-but-unanticipated
  refactor of the unrelated specificity breaks the regex.
- [[subprocess-exit-code-validation-test-harness-2026-05-13]] — the
  protokit-internal companion at the subprocess-call layer. Both
  patterns target "silent breakage from incidental coupling": the
  exit-code validation doc covers subprocess returncode semantics
  that change incidentally with the wrapped tool's release; this doc
  covers regex anchors that depend incidentally on Python annotation
  style.
- [[buf-parity-divergence-documentation-discipline-2026-05-13]] — the
  four-site documentation discipline for buf-parity rules. The drift-
  check pattern from this doc is the test-layer enforcement counterpart;
  both are about "multiple sites must stay in sync with a single
  underlying contract." Different layers (rule documentation vs. test
  regex), same principle.
- [[upstream-rule-deprecation-skip-ordering-parity-harness-2026-05-13]] —
  the Phase A learning that established `_BUF_DEPRECATED_RULES` + the
  skip-before-subprocess ordering. The drift-check test that motivated
  this doc is the same harness's pin-discipline guard; both docs
  describe disciplines that keep the parity infrastructure honest as
  it evolves.
- Commit `f81f408` — original regex anchored on `: str`.
- Commit `b425954` — relaxed to `:[^=]+=` in both consumers atomically.
