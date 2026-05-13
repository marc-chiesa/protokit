---
title: "Prefix symbol names per-fixture-branch in buf v2 parity fixture directories; module-scoped compilation merges good.proto and bad.proto"
date: 2026-05-13
category: best-practices
module: tests/parity/fixtures
problem_type: best_practice
component: testing_framework
severity: medium
applies_when:
  - "Multiple .proto files live in a single directory rooted by a buf v2 buf.yaml"
  - "A fixture directory contains both happy-path (good.proto) and sad-path (bad.proto) protos for the same lint rule"
  - "The harness invokes ``buf lint`` against the fixture directory rather than against individual .proto files"
  - "The harness filters buf's NDJSON findings to a specific rule_id and would treat 'no findings for this rule' as a clean lint"
tags:
  - buf-parity
  - fixture-hygiene
  - proto-compilation
  - symbol-collision
  - test-isolation
  - parity-harness
  - buf-v2
  - module-scope
---

# Prefix symbol names per-fixture-branch in buf v2 parity fixture directories

## Context

When a buf v2 `buf.yaml` defines a module (`modules: [{ path: . }]`),
`buf lint` compiles **every** `.proto` file in the module directory
together before running lint rules. The `lint: use: [<RULE_ID>]`
restriction only constrains which **lint rules fire** — it does not
constrain which **files are compiled**.

If `good.proto` and `bad.proto` in the same fixture directory both
declare a `Ping`, `Pong`, or `Stub` message, buf's compile phase
emits a `type: "COMPILE"` finding:

```text
{"path":"bad.proto","start_line":5,"start_column":9,"end_line":5,"end_column":13,
 "type":"COMPILE","message":"`Ping` declared multiple times"}
```

The harness's `_filter_buf_findings_by_rule(findings, "SERVICE_PASCAL_CASE",
"bad.proto")` filters on `type == "SERVICE_PASCAL_CASE"` — the COMPILE
findings have a different `type` and are silently dropped. The harness
then sees zero buf findings for the rule under test and the parity
assertion fails with a misleading
`"expected BOTH tools to fire, buf_fired=False"` message.

This was discovered during D6a U8 Phase A bring-up: the original
`pascal-case-services`, `pascal-case-rpcs`, `snake-case-files`, and
`package/directory-match` fixtures reused message names across good
and bad `.proto` files, and every sad-path test for those rules
silently failed until the symbols were prefixed.

## Guidance

**Use distinct symbol names across every `.proto` file in a buf
fixture directory.** Prefix the symbols by branch (`Good*` /
`Bad*` is the project convention) so buf's compile phase never
encounters duplicate type names.

The rule applies to: messages, enums, services, oneof groups, and any
other top-level declaration that contributes to the package's symbol
namespace.

If the rule under test fires on the **filename itself** (e.g.,
`naming/snake-case-files`), the convention extends to making each
file's contents disjoint:

```protobuf
# good_file.proto
syntax = "proto3";
package parity.naming.filenames;
message GoodFileStub {}

# BadFile.proto
syntax = "proto3";
package parity.naming.filenames;
message BadFileStub {}    # distinct from GoodFileStub
```

If the rule under test depends on **directory layout** (e.g.,
`package/directory-match`), the good and bad protos live at different
relative paths within the module — symbol-prefix discipline still
applies:

```
tests/parity/fixtures/package/directory-match/
├── buf.yaml                          # lint: use: [PACKAGE_DIRECTORY_MATCH]
├── wrongdir/
│   └── bad.proto                     # message BadStub {}
└── parity/dirmatch/
    └── good.proto                    # message GoodStub {}
```

## Why This Matters

A sad-path fixture with a COMPILE collision produces zero buf findings
**after rule filtering**. The parity test for that rule then sees
"buf did not fire on bad.proto" and either:

- fails with `"parity sad-path: expected BOTH tools to fire"` (if the
  harness is strict — the current state), or
- silently passes as if the divergence were documented (if the
  exception-handling path is lenient).

Neither outcome is what the test was meant to assert. The real
problem is invisible: the lint rule was never tested. The COMPILE
errors that masked it sit in the unparsed-by-the-harness portion of
buf's output, surfacing only when a contributor reads buf's raw
NDJSON to debug a "mysterious" parity failure.

The pattern compounds: every future buf BASIC rule shipped by D6b
will need fixtures, and every fixture with two `.proto` files in the
same directory is at risk. Documenting the symbol-prefix discipline
once — and reading it once before adding a new fixture — saves the
hour or two of debugging when the next fixture's tests fail with
this exact symptom.

## When to Apply

- Any time a fixture directory under `tests/parity/fixtures/<family>/<rule>/`
  contains 2+ `.proto` files (which it does today, every time).
- When designing fixtures for a rule whose violation is in the **message
  body** (single-symbol fixtures suffice and the rule applies vacuously,
  but the discipline is cheap to apply preemptively).
- When designing fixtures for a rule whose violation is **structural**
  (filename, directory layout, package declaration) — the discipline
  here is essential because the rule expects to fire on a specific
  file/path, and a COMPILE collision masks every other rule firing.
- When adding a third or fourth `.proto` to an existing fixture
  directory (e.g., `file/syntax-specified` has `good.proto`,
  `no_syntax.proto`, and `explicit_proto2.proto`) — verify symbol
  disjointness across **all** files, not just good-vs-bad.

## Examples

**Before — symbol collision causes COMPILE errors that mask the rule:**

```protobuf
// good.proto
syntax = "proto3";
package parity.naming.services;
message Ping {}                       // COLLIDES with bad.proto
message Pong {}                       // COLLIDES with bad.proto
service GoodService {
  rpc Echo(Ping) returns (Pong);
}

// bad.proto
syntax = "proto3";
package parity.naming.services;
message Ping {}                       // "Ping" declared multiple times -> COMPILE
message Pong {}                       //  -> COMPILE
service lower_case_service {
  rpc Echo(Ping) returns (Pong);      // SERVICE_PASCAL_CASE never fires
}
```

**After — per-branch prefixes eliminate the collision:**

```protobuf
// tests/parity/fixtures/naming/pascal-case-services/good.proto
syntax = "proto3";
package parity.naming.services;
message GoodPing {}
message GoodPong {}
service GoodService {
  rpc Echo(GoodPing) returns (GoodPong);
}

// tests/parity/fixtures/naming/pascal-case-services/bad.proto
syntax = "proto3";
package parity.naming.services;
message BadPing {}                    // distinct symbol — no COMPILE collision
message BadPong {}
service lower_case_service {          // SERVICE_PASCAL_CASE fires correctly
  rpc Echo(BadPing) returns (BadPong);
}
```

The same prefix discipline applies to:
- `pascal-case-rpcs` — `GoodPing`/`GoodPong`/`GoodRpc` vs
  `BadPing`/`BadPong`/`lower_case_rpc`
- `snake-case-files` — `GoodFileStub` (in `good_file.proto`) vs
  `BadFileStub` (in `BadFile.proto`)
- `package/directory-match` — `GoodStub` (in
  `parity/dirmatch/good.proto`) vs `BadStub` (in `wrongdir/bad.proto`)
- `enum/no-allow-alias` — `GoodEnum` vs `BadEnum`
- `enum/first-value-zero` — `GoodEnum` vs `BadEnum` (with the
  additional twist that `bad.proto` must be `syntax = "proto2"` since
  proto3 grammar rejects non-zero first values at compile time)

For rules whose violation is in the **message body only**, single-symbol
fixtures suffice without prefix discipline — the namespaces don't
overlap because each file declares a different name:

```protobuf
// good.proto — only one symbol; the body has no rule violation
package parity.naming.pascalmessages;
message GoodMessage { int32 field = 1; }

// bad.proto — only one symbol; distinct name; body holds the violation
package parity.naming.pascalmessages;
message lower_case_message { int32 field = 1; }
```

For rules with **3+ branches in a single fixture directory**
(`file/syntax-specified` has `good.proto`, `no_syntax.proto`,
`explicit_proto2.proto`), apply the same discipline to all of them —
each file declares a distinct stub name:

```protobuf
// good.proto:               message Stub {}             # but rename if collision threatens
// no_syntax.proto:          message NoSyntaxStub { ... }
// explicit_proto2.proto:    message ExplicitProto2Stub { ... }
```

## Related

- [[cli-fixture-proto-hygiene-must-satisfy-builtin-packs-2026-05-13]] —
  sibling discipline on a different fixture layer. That doc covers
  manually-constructed `FileDescriptorProto` fixtures in
  `tests/schema/lint/cli/` where fixture **field values** must satisfy
  every active BUILTIN_PACKS rule. This doc covers source-level `.proto`
  fixtures in `tests/parity/fixtures/` where fixture **symbol names**
  must not collide across the compile group. Same overall theme
  ("fixture must be construction-correct before the harness can test
  the rule") at different compilation layers.
- [[subprocess-exit-code-validation-test-harness-2026-05-13]] — when
  buf cannot compile the fixture due to a symbol collision, the
  fall-back behavior was previously a silent-green test; that doc
  captures the exit-code guard that surfaces the COMPILE failure as
  a loud diagnostic. The two disciplines together close the loop: this
  doc prevents the collision, the exit-code guard surfaces it loudly
  if it occurs anyway.
- [[buf-parity-divergence-documentation-discipline-2026-05-13]] — for
  cases where good.proto and bad.proto must intentionally produce
  different rule outcomes (one branch fires in protokit but not buf),
  the four-site documentation protocol applies. The symbol-prefix
  discipline here is the prerequisite — the test cannot meaningfully
  assert divergence shape if a COMPILE error masks both branches.
- Commit `c270489` — Phase A: original fixtures with symbol
  collisions, debugged + fixed inline.
- Commit `5eba36b` — ce:review follow-up: hardened the exit-code
  guard so future symbol-collision regressions surface loudly.
