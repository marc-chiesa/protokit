---
title: "CLI test FileDescriptorProto fixtures must satisfy every active BUILTIN_PACKS rule"
date: 2026-05-13
category: best-practices
module: protokit.schema.lint
problem_type: best_practice
component: testing_framework
severity: medium
applies_when:
  - "Adding a new lint rule to BUILTIN_PACKS that fires on file-shape properties (package, syntax, filename path, dependency presence)"
  - "Authoring or updating CLI integration tests in tests/schema/lint/cli/ that construct FileDescriptorProto fixtures via descriptor_pb2 directly"
  - "Any test that exercises the CLI lint pipeline against manually-constructed proto fixtures rather than real .proto files compiled through the standard backends"
tags:
  - cli-tests
  - fixtures
  - file-descriptor-proto
  - builtin-packs
  - lint-rules
  - proto-hygiene
  - fixture-drift
---

# CLI test FileDescriptorProto fixtures must satisfy every active BUILTIN_PACKS rule

## Context

CLI integration tests in protokit-lint construct `FileDescriptorProto`
fixtures manually via `descriptor_pb2.FileDescriptorSet()` to test
*feature* behavior — exclude logic, profile resolution, output format
— rather than lint correctness. The fixtures live in
`tests/schema/lint/cli/*.py`. The CLI invokes the lint engine with
the full default profile (all of `BUILTIN_PACKS`), so every field the
engine inspects — `fd.syntax`, `fd.package`, `fd.name`, dependency
arrays — is a potential firing site for any rule in the growing pack
list.

When a new rule lands in `BUILTIN_PACKS` and a fixture field doesn't
satisfy it, the CLI feature test breaks with a confusing failure
pointing at the new rule rather than the feature under test. The
failure mode is silent under normal review: unit tests pass, the
fixture compiles, the feature still works — but the *integration*
test sees the new finding and exits non-zero.

(Session history confirmed this pattern was *not anticipated* in
D5: the fixtures in `test_config_flags.py` (D5 U1), `test_exclude.py`
(D5 U3), and `test_human_stderr_render.py` (D5 U5) were all written
with `fd.package = "test"` because the default-profile rule set at
the time was the lone D2 canary which didn't care about packages.
The first break happened at D6a U6 when `package/directory-match`
landed and the exclude-feature tests started firing
`expected="api"` on fixtures declaring `package="test"`. The fix
was applied immediately at implementation time; this learning
codifies the discipline so future contributors don't have to
rediscover the pattern.)

## Guidance

**Each manually-constructed CLI fixture's fields must satisfy every
rule active in the default profile at the time CI runs.** As of D6a
U6 (14 rules across 5 packs), the invariants are:

```python
# Default-profile-clean fixture template:
fds = descriptor_pb2.FileDescriptorSet()
fd = fds.file.add()
fd.name = "acme/api/v1/users.proto"   # POSIX-separator path
fd.syntax = "proto3"                   # not "" or "proto2"
fd.package = "acme.api.v1"             # matches directory parts
# No imports unless the test exercises imports rules.
# Package + nested types must be snake_case / PascalCase.
```

Per-rule constraints to honor (current as of D6a U6):

| Rule | Constraint |
|---|---|
| `file/syntax-specified` | `fd.syntax = "proto3"` (or `"editions"`). Avoid `""` and `"proto2"` unless the test specifically targets syntax handling. |
| `package/defined` | `fd.package` must be non-empty. |
| `package/directory-match` | `fd.package` segments must match `fd.name` directory parts. Top-level files (no directory) are exempt for package/directory-match but still need non-empty package for package/defined. |
| `naming/snake-case-packages` | Every package segment must match `^[a-z][a-z0-9]*(_[a-z0-9]+)*$`. No `MyService` or `userAPI`. |
| `naming/snake-case-files` | `fd.name` basename stem must be snake_case (after stripping `.proto`). |
| `imports/no-public` / `imports/no-weak` | No `public_dependency` / `weak_dependency` entries. |
| `imports/unused` | Every entry in `fd.dependency` must be referenced by a field or method type. |
| All other naming rules | If `fd.message_type` / `fd.enum_type` / `fd.service` lists are populated, names must match the rule's case style. |

**Alternative: narrow the test's profile.** If the test deliberately
doesn't care about lint compliance (e.g., pure CLI flag exercising),
invoke with an explicit narrow profile (`--profile essentials`) or —
once D6a Unit 9 lands `--no-builtin-rules` — with that flag plus a
minimal user pack. The fixture-alignment approach is preferred for
tests that *do* run through the real engine, because it keeps the
integration test realistic while avoiding spurious noise.

**Rule-author checklist** (cheap to run before opening a PR adding
a new rule to a default-profile pack):

```bash
# Find every manually-constructed FileDescriptorProto fixture:
grep -rn "descriptor_pb2.FileDescriptorSet\|fds\.file\.add\|fd\.package\s*=" \
  tests/schema/lint/cli/

# For each match, verify the fixture's fd.package / fd.syntax /
# fd.name / dependencies satisfy the new rule's constraint.
```

When a fixture *does* need updating, prefer aligning the field
value over downgrading the rule's severity in tests — the alignment
is durable and the comment documents the constraint for the next
reader.

## Why This Matters

The failure is silent under normal review. Each ce:review cycle when
a new pack lands, "test_X.py is failing — investigate" appears and
looks like a rule bug. Both D5 U5 and D6a U6 ce:review cycles spent
non-trivial time updating these fixtures. The pattern is sustainable
but invisible: a contributor adding a new rule has no signal that
`test_exclude.py` will break until CI runs. The cycle is:

1. New rule lands in a default-profile pack.
2. Existing CLI fixture doesn't satisfy the rule.
3. CI fails with a lint finding rather than a fixture assertion
   error — the failure message points at the new rule, not at the
   fixture.
4. Author has to trace the failure back to fixture drift rather than
   their new rule code.

Codifying the rule-author checklist + the fixture invariants moves
the catch to PR-author time, which is the cheapest moment to fix.

**Latent risk** (session history): `test_human_stderr_render.py`
still carries `fd.package = "test"` with `fd.name = "api/user.proto"`
in two inline fixtures (lines 415-417, 514-516). These survive only
because those tests use `--exclude '**/*'` (engine short-circuits)
or monkeypatched engine runs. They are not yet aligned and remain a
future breakage risk if the short-circuit paths ever change.
`test_config_flags.py` line 53 has a similar `fd.package = "test"`
fixture surviving for the same reason (test exercises the
config-loading step, not the engine run). These two files are not
broken today but they are time bombs.

## When to Apply

- **Rule-author time** — when adding any structural rule (one that
  fires on `fd.syntax`, `fd.package`, `fd.name`, import fields, or
  naming fields) to `BUILTIN_PACKS`. Run the rule-author checklist
  above and verify each fixture satisfies the new rule.
- **CLI test author time** — when writing any new CLI integration
  test that constructs `FileDescriptorProto` manually. Pre-check
  against the current default profile.
- **ce:review time** — when reviewing a PR that adds to
  `BUILTIN_PACKS`, look for fixture changes (or *lack of* fixture
  changes when they would be required) as a P2 finding.
- **Latent-risk audit** — at delivery boundaries (e.g., D6a U10
  final sweep), grep for `fd.package = "test"` and similar
  non-conforming literals in `tests/schema/lint/cli/` and align
  them proactively before the next rule causes a break.

## Examples

**Before (D5-era `test_exclude.py`, broken after D6a U6):**

```python
fds = descriptor_pb2.FileDescriptorSet()
for name in ["api/user.proto", "vendor/external.proto"]:
    fd = fds.file.add()
    fd.name = name
    fd.syntax = "proto3"
    fd.package = "test"  # ← mismatches directory; fires
                        #   package/directory-match after U6
```

**After (D6a U6 ce:review fix, with inline comment):**

```python
fds = descriptor_pb2.FileDescriptorSet()
# Each fixture file's package matches its directory path so the
# D6a U6 ``package/directory-match`` rule (now in BUILTIN_PACKS)
# does not fire on this exclude-feature test. The exclude logic
# is what's under test here; aligning the packages avoids
# coupling this test to the directory-match rule.
for name, pkg in [("api/user.proto", "api"),
                  ("vendor/external.proto", "vendor")]:
    fd = fds.file.add()
    fd.name = name
    fd.syntax = "proto3"
    fd.package = pkg
```

The same pattern applies in `test_no_exclude.py` with the same
inline comment naming the constraint.

**Single-file fixture** (`single_vendor_descriptor_set` in
`test_exclude.py`):

```python
fd = fds.file.add()
fd.name = "vendor/external.proto"
fd.syntax = "proto3"
fd.package = "vendor"  # match directory for package/directory-match (U6)
```

The trailing comment is a permanent record of the constraint — when
a future rule introduces a new field-shape requirement, this
fixture's audit point is already named.

## Related

- [[perf-smoke-profile-compose-across-builtin-packs-2026-05-13]] — structural twin: that doc covers the *profile-composition* side of the same BUILTIN_PACKS-growth failure mode (perf-smoke profile pinned to `BUILTIN_PACKS[0]` silently drops new pack rules as the registry grows). This doc covers the *fixture* side (CLI fixtures constructed before new rules existed silently break under them). Both share the "BUILTIN_PACKS growth as invisible update obligation" core insight; the appropriate response differs (profile composition vs. fixture field alignment) but the discipline of "audit when adding a pack member" is the same.
- [[rule-pack-extension-ssot-rule-ids-and-test-class-naming-2026-05-12]] — the rule-pack-extension checklist this learning extends. Adding "audit CLI fixtures in tests/schema/lint/cli/ for default-profile compliance" to the existing checklist is the operational follow-through; the cross-reference makes the connection discoverable.
- [[parametrized-matrix-tests-inherit-schema-validators-2026-05-12]] — the parallel principle for parametrized matrix tests: fixtures must be inherited (not re-declared per cell) so they stay in sync with the canonical schema. Same "test fixtures must stay in sync with a growing rule surface" pattern at a different layer.
- [[fail-closed-ci-matrix-coverage-meta-test-2026-05-12]] — parallel silent-degeneration failure mode at the CI-yaml layer (skipif predicate evolves out of sync with the matrix). Both this doc and the meta-test learning are about "silently passing a test that no longer exercises what it claims to exercise"; they cover different artifact types but compose into the broader discipline.
- [[smoke-not-benchmark-loose-threshold-calibration-2026-05-12]] — adjacent: the perf smoke fixture also needed to remain lint-clean under BUILTIN_PACKS growth; that doc's "fixture should produce zero findings" note touches this same domain.
