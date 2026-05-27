---
title: "`protobuf>=4.21,<6` upper-bound pin is load-bearing because protobuf 6+ removed FieldDescriptor.label"
date: 2026-05-27
category: docs/solutions/tooling-decisions
module: protokit
problem_type: tooling_decision
component: tooling
severity: high
applies_when:
  - Adding or relaxing the protobuf dependency bound in pyproject.toml
  - Code introspects FieldDescriptor.label or other descriptor attributes removed in protobuf 6+
  - Shipping a package with optional [compiler] extra where two install paths must both resolve to a tested combo
  - "Bumping a project's upper bound on a library whose major version drops public API surface"
tags:
  - protobuf
  - dependency-pin
  - fielddescriptor
  - descriptor-introspection
  - upper-bound
  - protoxy
  - compiler-extra
  - silently-broken-install
  - python-packaging
related_components:
  - tooling
---

# `protobuf>=4.21,<6` upper-bound pin is load-bearing because protobuf 6+ removed FieldDescriptor.label

## Context

protokit's lint rule packs and compatibility checker introspect `FileDescriptor` / `FieldDescriptor` / `MessageDescriptor` objects via `.label`, `.type`, and similar attributes. The `google.protobuf` Python package shipped these as the public API surface from 4.21 through 5.x. **protobuf 6+ removed several of them** (`FieldDescriptor.label` notably) as part of a descriptor API restructuring. Code that calls `field.label == FieldDescriptor.LABEL_REPEATED` either `AttributeError`s mid-walk or silently fails to produce findings, depending on the call site.

The asymmetric problem: protokit's optional `[compiler]` extra installs `protoxy`, which transitively pins `protobuf<6`. So users who run `pip install protokit[compiler]` were always safe — pip resolved to protobuf 5.x and everything worked. But users running plain `pip install protokit==0.7.0` had no upper bound, and pip's "give the user the latest compatible version" resolver picked protobuf 7.x. Result: same protokit version, same install command shape, two completely different runtime behaviors depending on whether `[compiler]` was specified.

This was a silently-broken install. The user got 0 lint findings on protos they'd previously seen findings for, OR an `AttributeError` deep inside the descriptor walker when a rule tried to read `field.label`. Neither failure mode points back to "protobuf version mismatch" — they look like protokit bugs.

## Guidance

Pin the protobuf upper bound explicitly in your own `pyproject.toml` `dependencies` even when an optional extra transitively pins it for some users. From `pyproject.toml:29-37`:

```toml
dependencies = [
    # Upper bound: protobuf 6+ removed several FieldDescriptor /
    # MessageDescriptor attributes (notably ``.label``) that protokit's
    # lint rule packs and the compatibility checker rely on. Adopting
    # the new API is planned for a future release; for now we pin to
    # the same range the [compiler] extra's protoxy 0.7.x package
    # transitively pins (``protobuf<6``), so users get a working
    # install whether or not they install [compiler].
    "protobuf>=4.21.0,<6",
    "click>=8.0",
    # ... other deps ...
]
```

Three properties matter:

1. **Match the range your optional-extra transitively pins.** If `[compiler]` users get `protobuf<6` via protoxy, base users should get the same. Otherwise the two install paths produce different runtime behavior on the same protokit version — debugging nightmare.
2. **Leave a code comment that names the broken attributes.** Future maintainers need to know what specifically breaks so they don't reflexively bump the pin when CVEs land in protobuf 6/7. The comment should also note the planned API migration as a release-cycle TODO so the pin doesn't become permanent by accident.
3. **Test both install paths in CI.** The `has_protoxy: {true, false}` matrix axis is what makes this discoverable; without it, the no-extra path would fail silently in production for users not running CI.

The CI matrix that catches this (`.github/workflows/ci.yml`):

```yaml
strategy:
  matrix:
    python: ["3.10", "3.12"]
    has_protoxy: [true, false]

# ... later, in install steps:
- name: Install package + dev deps (with protoxy)
  if: matrix.has_protoxy
  run: pip install -e ".[compiler,dev]"

- name: Install package + dev deps (without protoxy)
  if: ${{ !matrix.has_protoxy }}
  run: pip install -e ".[dev]"
```

The `has_protoxy: false` cell intentionally tests the no-extra install path. Without the upper-bound pin in `pyproject.toml`, that cell would (and did) resolve to `protobuf-7.35.0` and produce real test failures.

## Why This Matters

Optional dependencies that transitively pin upstream versions create an asymmetry: one install path is constrained, the other is not. Without an explicit pin in your own metadata, you're trusting pip's resolver to "do the right thing" — and the resolver's job is to give the user the latest compatible version, which on the no-extra path means whatever protobuf major just released.

The user-facing consequence is "the same `pip install <package>==X.Y.Z` produces a working install on my laptop (where I installed `[extras]`) and a broken install in production (where I didn't)." That's the worst category of bug — silent, environment-dependent, and only surfaces on the user's first real workflow invocation.

Explicit pins also document intent. When a future maintainer sees `protobuf>=4.21.0,<6` they know the upper bound is deliberate, not stale. A missing upper bound looks like an oversight; the maintainer is likely to assume "we can support newer protobuf, just bump it" without auditing every descriptor introspection call.

There's a process implication too: any time you discover an upstream library has dropped public API surface in a major version, audit your own consumption of that surface AND tighten your dependency bound. The audit might reveal you weren't actually using the dropped attribute (in which case the pin can be wider), or it might reveal a non-trivial migration path (in which case the pin should stay strict until the migration ships).

## When to Apply

- Always pin upper bounds on dependencies whose API your code introspects (descriptor walkers, AST consumers, schema readers).
- When you have an `[extra]` that transitively pins a dependency, mirror that pin in the base `dependencies` — both install paths should resolve to the same tested range.
- When upstream announces breaking API changes in a major version bump, add the upper bound preemptively even if the new major hasn't released yet.
- Does NOT apply to dependencies you only call via stable public APIs (`click>=8.0` is fine without an upper bound because click's public API is stable across majors).
- Does NOT apply to dev/test-only dependencies (those are scoped to your dev environment, not the user's runtime).

## Examples

**Before (0.7.0 — silently broken without `[compiler]`):**

```toml
dependencies = [
    "protobuf>=4.21.0",
    "click>=8.0",
]
```

User runs `pip install protokit==0.7.0`. pip resolves `protobuf-7.35.0`. First `protokit lint` invocation either fires zero findings (rules silently skip when `field.label` raises) or `AttributeError`s mid-walk.

**After (0.7.1 — both install paths land on a tested combo):**

```toml
dependencies = [
    # Upper bound: protobuf 6+ removed several FieldDescriptor /
    # MessageDescriptor attributes (notably ``.label``) ...
    "protobuf>=4.21.0,<6",
    "click>=8.0",
]
```

User runs `pip install protokit==0.7.1`. pip resolves `protobuf-5.29.6`. `protokit lint` works. Same behavior as `pip install protokit[compiler]==0.7.1` which resolves `protobuf-5.27.5` via protoxy's transitive pin.

## Related

- [[deprecationwarning-poisons-except-exception-strict-warning-ci-2026-05-11]] — same "third-party lib deprecates/removes a symbol our code uses" pattern; the `<6` pin is the **upstream-mitigation** form of the broader problem this doc treats from the **downstream-defense** side.
- pre-1.0-version-bump-as-communication-contract-2026-05-14 — same family (version semantics), but our-version-side rather than dependency-side.
- post-ship-adoption-monitoring-pre-1.0-breaking-default-change-2026-05-19 — same "what protects users from silent breakage" framing.
- [[wkt-include-path-auto-discovery-system-protoc-backend-2026-05-27]] — sibling 0.7.1 fix; both surfaced on the first public CI run.
- first-public-push-plan-for-ci-iteration-debugging-2026-05-27 — the meta-learning: this category of "matrix-cell-only failure" is exactly what a `has_extra: {true, false}` axis exists to catch.
- Canonical commit: `b22d60a` ("fix: pin protobuf<6 + restructure perf-smoke fixture per-package directory").
