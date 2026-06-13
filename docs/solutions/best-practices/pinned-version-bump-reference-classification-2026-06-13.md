---
title: "Bumping a pinned version: bump current-state claims, leave historical / provenance / drift-anchor statements"
date: 2026-06-13
category: best-practices
module: schema/lint buf-parity pin
problem_type: best_practice
component: development_workflow
related_components:
  - documentation
  - tooling
  - testing_framework
severity: medium
applies_when:
  - "Bumping a pinned upstream version (a `_BUF_PARITY_PIN`-style constant, a CI download URL, a documented tool version) that appears across many code, CI, docs, and test sites"
  - "The same old version string repeats across README/CONTRIBUTING/CHANGELOG, source-code provenance annotations, and ratchet-pinned test anchors"
  - "Tempted to resolve the bump with a global find-replace across the repo"
  - "A drift test enforces lockstep between the functional pin and its CI consumers, and a separate presence-ratchet test deliberately pins an older version as a drift anchor"
  - "A version string lives in the README, which doubles as the PyPI long-description, so a stale current-state claim reads as behind upstream"
tags:
  - pinned-version-bump
  - buf-parity
  - find-replace-discipline
  - current-state-vs-historical
  - provenance-annotation
  - presence-ratchet
  - drift-anchor
  - changelog-revisionism
---

# Bumping a pinned version: bump current-state claims, leave historical / provenance / drift-anchor statements

## Context

protokit claims lint parity against a specific pinned buf CLI version, declared
once as `_BUF_PARITY_PIN` in `src/protokit/schema/lint/cli.py`. A weekly
`buf-release-watch` workflow auto-files a tracking issue whenever upstream buf
moves ahead of the pin, so this bump **recurs on every buf release** (the
instance that surfaced this learning: v1.69.0 → v1.70.0, issue #16 / PR #32,
README follow-up PR #33).

The friction: the old version string is sprinkled across roughly fifty sites —
the functional pin, CI download URLs, install docs, README claims, an upgrade
note, ~3 dozen source annotations, a deliberately-stale ratchet anchor, and
illustrative regex examples. A blind global find-replace (`s/vOLD/vNEW/g`) looks
like the obvious move and is exactly wrong: some occurrences **must** change,
some **must not**, and at least two will turn green CI red or rewrite history if
you bump them.

## Guidance

**Decision rule (the heart of this):** a version string's correct treatment
depends on what its sentence *asserts*, not on whether the text happens to match
the old version. If the sentence is a **present-tense current-state claim** —
this is the version the system runs / matches / installs *now* — track the pin
and bump it. If the sentence is **dated, historical, provenance, or a drift
anchor**, leave it; the stale string is load-bearing. Never bump a string just
because it equals the old version.

Apply this per occurrence with the seven-category table:

| # | Category | Treatment | What it looks like |
|---|----------|-----------|--------------------|
| 1 | Functional pin sites | **BUMP** | The `_BUF_PARITY_PIN` constant (`src/protokit/schema/lint/cli.py`); the parity job's tarball + `sha256.txt` download URLs (`.github/workflows/ci.yml`). A drift test (`tests/meta/test_buf_parity_pin_drift.py`) enforces these stay in lockstep. |
| 2 | Current-state operational labels | **BUMP** | The ci.yml parity-job header comment + step name ("Download buf vX tarball"); `CONTRIBUTING.md` install instructions ("install buf vX", release-tag + sha256 links, "currently bottled at vX"). The bump *falsifies* these descriptions of what the system does now. |
| 3 | Current-state user-facing claims | **BUMP** | `README.md` present-tense parity claims ("matches 26 of 26 buf vX BASIC rules"). README is the PyPI long-description (`pyproject [project] readme`), so stale claims read as "behind upstream." |
| 4 | Historical / dated statements | **LEAVE** | `README.md` "### Upgrade notes (0.5.x → 0.6.0)" ("0.6.0 … now covers 26 of 26 buf v1.69.0 BASIC rules"); CHANGELOG release records. Bumping is *revisionist* — a version that postdates the release didn't exist when that release shipped. |
| 5 | Empirical-behavior provenance | **LEAVE** | ~3 dozen source annotations across `engine.py` / `model.py` / `rules/*.py` (e.g. "buf v1.69.0 does NOT cross-fire across module boundaries"). They record the version a behavior was *verified against*; the live CI parity job re-asserts current behavior. |
| 6 | Ratchet-pinned drift anchors | **LEAVE** | The BUILTIN_PACKS docstring numerator in `src/protokit/schema/lint/rules/__init__.py` ("26 of 26 buf v1.69.0 BASIC rules"), asserted verbatim by `tests/schema/lint/test_builtin_packs.py`. The qualifier is "load-bearing for future drift detection if buf ships a new BASIC rule" — bumping it breaks the ratchet test *and* defeats its purpose. |
| 7 | Illustrative examples | **LEAVE** | Version-agnostic regex samples (the `_BUF_PARITY_PIN` grep comment in `.github/workflows/buf-release-watch.yml`; the `_CLI_PIN_RE` comment in the drift test). The regex matches `v[^"]+`; the sample value shows the *line shape*, not a tracked pin. Bumping it every release is the treadmill the agnostic regex exists to avoid. |

The split is not symmetric: only categories 1–3 bump. Everything that records
*when* something was true, or that is deliberately frozen, stays put.

## Why This Matters

Two opposite errors, both real:

- **(a) Blind bump → revisionist docs + red CI.** Find-replacing every old
  version rewrites the historical upgrade note (claiming a past release shipped
  parity against a version that didn't exist yet), corrupts the empirical
  provenance annotations (which document *when* a behavior was observed, not
  what's current), and — concretely — turns CI red: `test_builtin_packs.py`
  asserts the literal numerator substring is present in the `rules/__init__.py`
  source docstring, and that anchor is *meant* to stay stale so a new buf BASIC
  rule forces a conscious update. Bumping it both fails the test and disarms the
  drift detector.

- **(b) Leaving current-state claims stale → "looks behind upstream."** The
  README is protokit's PyPI long-description. Leaving the present-tense parity
  claims unbumped makes the package read on PyPI as if it has fallen behind
  upstream buf, even though the CI parity job now proves parity against the new
  version.

The trap is that categories 3 and 4 are *adjacent sentences in the same README
with the same substring* — one must bump, one must not. The reliable way to tell
them apart is an **adversarial-verification pass**: sweep every surface
(README / docs / src / pyproject / repo metadata) for candidates, then for each
proposed bump try to *refute* it, defaulting to keep-if-dated. That refutation
default is what catches the historical upgrade note, and it surfaced that the
parity-numerator ratchet asserts the *source docstring*, not the README — so
bumping the README claims breaks no tests, while bumping the docstring would.

## When to Apply

Any pin or dependency version bump where the version string is referenced in
**more than one place** — code, CI, install docs, README/PyPI copy, source
annotations, tests. Especially **recurring bumps** driven by a watcher or bot
(here, `buf-release-watch`), where the per-release temptation to "just
find-replace" compounds the risk. The single-reference case doesn't need this;
the moment a version appears in both a functional pin and prose, classify each
occurrence before touching it.

A useful pre-bump confirmation, orthogonal to the reference classification: prove
the bump itself is *safe* before editing claims. For the v1.70.0 bump this meant
downloading and checksum-verifying the real buf v1.70.0 binary and running the
parity suite against it (47 passed; the only behavior change was `PROTOVALIDATE`,
outside protokit's BASIC surface) — so "26 of 26" stayed true and the
current-state claims could honestly track the pin.

## Examples

**1. Two README lines, same substring, opposite treatment.**

- *Current-state claim (BUMP)* — README Schema Linting section:
  "…matches 26 of 26 buf **v1.69.0** BASIC rules…" → "…buf **v1.70.0**…". Present
  tense, describes what protokit does now, lives in the PyPI long-description.
- *Upgrade note (LEAVE)* — README "### Upgrade notes (0.5.x → 0.6.0)":
  "0.6.0 closes the buf-parity arc … now covers 26 of 26 buf **v1.69.0** BASIC
  rules." Dated to the 0.6.0 release; bumping it claims 0.6.0 targeted a version
  that didn't exist.

**2. The ratchet anchor (LEAVE — and why it bites).**

The BUILTIN_PACKS docstring numerator in `src/protokit/schema/lint/rules/__init__.py`
contains "26 of 26 buf v1.69.0 BASIC rules". That exact substring is asserted by
`tests/schema/lint/test_builtin_packs.py`, whose own docstring states the
`v1.69.0` qualifier is "load-bearing for future drift detection if buf ships a
new BASIC rule." Bumping it (a) fails the ratchet test immediately and (b)
defeats the drift-detection design — the anchor is supposed to stay stale so a
*new* buf BASIC rule forces a deliberate update, not a silent one.

**3. The illustrative regex example (LEAVE).**

`.github/workflows/buf-release-watch.yml` carries a comment: ``Greps
`_BUF_PARITY_PIN: <ANNOTATION> = "v1.69.0"` ``. The grep itself matches `v[^"]+`
(any version); the `v1.69.0` is a sample showing the line shape, not a tracked
pin. The same holds for the `_CLI_PIN_RE` comment in the drift test. Bumping
these on every release is precisely the treadmill the version-agnostic regex was
written to eliminate.

## Related

- [[stale-forward-looking-text-cli-help-agent-discoverability-2026-05-12]] —
  the closest methodological sibling: a broad-sweep-then-triage rubric for
  *temporal* prose staleness (present/future tense → rewrite; past tense →
  leave). This learning is the version-identifier analogue of that same
  default-to-leave-to-avoid-revisionism shape.
- [[cross-file-pin-regex-anchor-structure-not-annotation-token-2026-05-13]] —
  keeps the drift *test* robust (anchor on structure, not the annotation token);
  this learning is the bump-time *decision* that test enforces across the three
  lockstep pin sites.
- [[presence-ratchet-test-pattern-for-prose-substrings-2026-05-14]] — explains
  *why* the ratchet-pinned drift anchor (the `test_builtin_packs.py` numerator)
  exists; this learning tells a bumper *not to touch it*.
- [[upstream-rule-deprecation-skip-ordering-parity-harness-2026-05-13]] —
  sibling parity-infrastructure doc; a bump should re-verify the deprecated-rule
  set (the v1.70.0 bump confirmed `IMPORT_NO_WEAK` is still `deprecated=true`).
- [[buf-parity-divergence-documentation-discipline-2026-05-13]] — the four-site
  divergence docs are themselves provenance-bearing version annotations that a
  bump leaves (category 5).
