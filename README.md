# protokit

Python toolkit for Protocol Buffers — four pillars: message diffing, schema compatibility, linting (buf BASIC parity), and data-at-rest scan/filter.

`protokit diff` — structural, filterable message diffs with cross-descriptor-pool comparison, schema evolution detection, and a pytest hook.

`protokit compat` — descriptor-level schema compatibility checks with 18 built-in rules, four profiles, and a pluggable rule API.

`protokit lint` — descriptor-level linting with full **buf BASIC parity** (26/26 rules), AIP-122 naming, a `[tool.protokit.lint]` pyproject table, and pluggable rule packs.

`protokit storage` — schema-aware scan/filter over **stored** protobuf (length-delimited files, a pybind11 `memoryview`, any buffer source): `scan` / `head` / `count` with a minimal `--where` filter, presence-faithful field selection (`--fields`), dense full-record JSON (`--explicit-defaults`), typed Parquet output (`--format parquet -o`, via the optional `protokit[parquet]` extra), and safe concurrent multi-version scanning via isolated per-stream descriptor pools.

## Installation

```bash
pip install protokit
```

## Message Diffing

### Library

```python
from protokit.message import diff_messages, ChangeType

result = diff_messages(msg1, msg2)

if result.has_changes():
    for diff in result:
        print(f"{diff.path}: {diff.left_value} -> {diff.right_value}")

# Filter by path prefix
user_changes = result.filter(path="user.address")

# Filter by change type
additions = result.filter(change_type=ChangeType.ADDED)

# Combine filters
new_address_fields = result.filter(path="user.address", change_type=ChangeType.ADDED)
```

### CLI

Compare two binary protobuf messages:

```bash
# Same-schema mode
protokit diff left.pb right.pb --desc schema.descriptor_set --message-type myapp.User

# Cross-schema mode (schema evolution)
protokit diff left.pb right.pb \
  --left-desc v1.descriptor_set --right-desc v2.descriptor_set \
  --left-type v1.User --right-type v2.User

# JSON input
protokit diff left.json right.json --desc schema.descriptor_set --message-type myapp.User --json

# Text format input
protokit diff left.textproto right.textproto --desc schema.descriptor_set --message-type myapp.User --text-format

# From .proto files (requires protoc on PATH)
protokit diff left.pb right.pb --proto schema.proto --message-type myapp.User
```

Example output:

```
Found 3 differences:

  ~ user.name: 'Alice' -> 'Bob'
  + user.address.city: 'New York'
  - user.phone: '+1-555-0100'
```

JSON output for scripting:

```bash
protokit diff left.pb right.pb --desc schema.descriptor_set --message-type myapp.User --format json
```

```json
{
  "schema_version": "0.1",
  "equal": false,
  "differences": [
    {
      "path": "user.name",
      "change_type": "MODIFIED",
      "left_value": "Alice",
      "right_value": "Bob",
      "old_value": "Alice",
      "new_value": "Bob",
      "field_type": "TYPE_STRING"
    }
  ],
  "diagnostics": []
}
```

> **Terminology — left/right vs old/new.** The message differ uses
> **left/right** (`diff.left_value`/`diff.right_value`, JSON keys `left_value`/
> `right_value`): two arbitrary messages are compared and neither side is
> privileged, so there is no inherent "old" or "new". The schema compatibility
> checker (`protokit compat`) uses **old/new** because it answers a directional
> question — is the *new* schema a safe successor to the *old* one. The split is
> intentional. The differ's previous `old_value`/`new_value` names (both the
> Python attributes and the JSON keys) remain as deprecated aliases until
> protokit 1.0; reading `diff.old_value`/`diff.new_value` emits a
> `UserWarning`.
>
> The JSON object is **open/additive** — ignore unknown keys rather than
> validating a closed set. Gate on the top-level `schema_version` to detect the
> shape change when `old_value`/`new_value` are removed at 1.0; output from
> protokit versions before `schema_version` existed simply omits the key.

Quiet mode for CI (exit code only):

```bash
protokit diff left.pb right.pb --desc schema.descriptor_set --message-type myapp.User --quiet
echo $?  # 0 = equal, 1 = different, 2 = error
# An error-level diagnostic (a hook or plugin raised) is 2 in EVERY format,
# even when no differences were found: the comparison is not trustworthy,
# so there is no verdict to report.
```

### pytest Integration

Add the hook to your `conftest.py`:

```python
from protokit.message.pytest_plugin import pytest_assertrepr_compare  # noqa: F401
```

Now `assert msg1 == msg2` shows a structured diff on failure:

```
assert msg1 == msg2
E     myapp.User != myapp.User
E       2 difference(s):
E       ~ name: 'Alice' -> 'Bob'
E       ~ address.city: 'SF' -> 'NYC'
```

### Features

**Cross-descriptor-pool comparison** — Compare messages from different `.descriptor_set` files. Field matching is name-based, not descriptor-identity-based.

**Schema evolution detection** — Detects field number changes, type changes, and cardinality changes across schema versions. Reported as first-class diff entries.

**Queryable diff objects** — `DiffResult` is immutable and filterable. Filter by path prefix, exact path, or change type. Chain filters freely.

**`treat_as_map`** — Match repeated message fields by a key field instead of index, ignoring order.

```python
from protokit.message import MessageDifferencer

differ = MessageDifferencer()
differ.treat_as_map("items", key="id")
result = differ.compare(msg1, msg2)
# Paths use key notation: items[id="abc"].name
```

**Float comparison** — Exact (IEEE 754) or approximate (fraction + margin) modes.

```python
from protokit.message import MessageDifferencer, FloatComparison

differ = MessageDifferencer()
differ.set_float_comparison(FloatComparison.APPROXIMATE, fraction=1e-6, margin=1e-9)
```

**Ignore fields**

```python
differ = MessageDifferencer()
differ.ignore_fields("timestamp", "request_id")  # bare name = global
differ.ignore_fields("user.internal_id")          # dotted path = scoped
```

**Max depth**

```python
differ = MessageDifferencer()
differ.max_depth = 3
result = differ.compare(msg1, msg2)
assert not result.is_complete  # truncated subtrees exist
```

### CLI Options (`protokit diff`)

| Flag | Description |
|------|-------------|
| `--desc FILE` | Descriptor set file (same-schema mode) |
| `--message-type NAME` | Fully-qualified message type name |
| `--left-desc FILE` | Left descriptor set (cross-schema mode) |
| `--right-desc FILE` | Right descriptor set (cross-schema mode) |
| `--left-type NAME` | Left message type (cross-schema mode) |
| `--right-type NAME` | Right message type (cross-schema mode) |
| `--proto FILE` | .proto file (requires `protoc` on PATH) |
| `--proto-path DIR` | Import path for protoc. Repeatable. Only valid with `--proto`; passing it in any other flag group is a usage error (exit 2) rather than being silently ignored. |
| `--text-format` | Parse input as protobuf text format |
| `--json` | Parse input as JSON-encoded protobuf |
| `--format NAME` | Output format (default: `human`). Built-in for diff: `human`, `json`, `junit`. See [Output Formatters](#output-formatters). |
| `--formatter-module MODULE` | Python module exposing a `FORMATTERS = [(name, fn, kind), ...]` list (repeatable). See [Output Formatters](#output-formatters). |
| `--quiet` | Suppress output, exit code only. Mutually exclusive with any non-`human` `--format`. |
| `--verbose` | Show warnings even when equal |
| `--filter PATH` | Filter diffs by path prefix |
| `--ignore FIELD` | Ignore field. Repeatable. |
| `--treat-as-map FIELD KEY` | Treat repeated field as map with key |
| `--float-mode exact\|approximate` | Float comparison mode |
| `--max-depth N` | Maximum comparison depth. Must be non-negative; a negative value is a usage error (exit 2). |
| `--strict-schema` | Warn on message type name changes |

## Schema Compatibility

Check whether a `.proto` schema change is safe before you merge it. Catches three kinds of breakage:

- **Wire breaks** — field-number reuse, cardinality flips, incompatible encodings.
- **Semantic breaks** — removed fields, added enum values, presence-semantics changes.
- **Policy breaks** — custom-option changes and org-specific rules (via plugins).

### Library

```python
from protokit.schema import check_compatibility, CompatibilityLevel

report = check_compatibility(
    old_pool, "acme.User",
    new_pool, "acme.User",
    level=CompatibilityLevel.CONSUMER_SAFE,
)

if not report.is_compatible:
    for f in report.findings:
        print(f"{f.severity.value}/{f.direction.value} {f.path}: {f.message}")

# Per-severity buckets
print(len(report.wire_breaks), len(report.semantic_breaks), len(report.policy_breaks))
```

Cross-type comparisons (renamed messages) pass different type names for each side:

```python
report = check_compatibility(old_pool, "acme.UserV1", new_pool, "acme.UserV2")
```

### CLI

Compare two descriptor sets:

```bash
protokit compat old.descriptor_set new.descriptor_set \
  --type acme.User \
  --level consumer-safe
```

From `.proto` sources:

```bash
protokit compat old.proto new.proto --proto --type acme.User
```

Cross-type comparison:

```bash
protokit compat old.descriptor_set new.descriptor_set \
  --old-type acme.UserV1 --new-type acme.UserV2
```

JSON output for CI:

```bash
protokit compat old.descriptor_set new.descriptor_set --type acme.User --format json --quiet
echo $?  # 0 = compatible, 1 = incompatible, 2 = error
```

### Compatibility Profiles

Four profiles control which findings surface. Each is a pair of filters: a severity threshold and a direction filter.

| Profile | Question Answered | Surfaces |
|---------|-------------------|----------|
| `WIRE` | Will deserialization crash? | Wire-level breaks only, any direction. |
| `CONSUMER_SAFE` | Can old consumers safely read new messages? | Wire + semantic with BACKWARD or BOTH direction. Excludes FORWARD-only findings like new-field-added. |
| `PRODUCER_SAFE` | Can new consumers safely read old messages? | Wire + semantic with FORWARD or BOTH direction. Excludes BACKWARD-only findings like field-removed. |
| `STRICT` | Any compatibility concern at all? | All severities (including POLICY) in all directions. |

### Built-in Rules

| Rule | Severity | Direction | Detects |
|------|----------|-----------|---------|
| `field_removed`            | SEMANTIC | BACKWARD | Field present in old, absent in new. |
| `field_added`              | SEMANTIC | BACKWARD | New field (non-required, not in a oneof). Old consumer sees unknown data. |
| `field_number_changed`     | WIRE     | BOTH     | Same name, different number. |
| `field_type_wire_incompatible` | WIRE | BOTH     | Scalar type change across wire groups (e.g. int32 ↔ sint32). |
| `field_type_semantic_change`   | SEMANTIC | BOTH | Type change within a wire group (e.g. string ↔ bytes). |
| `field_type_name_changed`  | POLICY   | BOTH     | Message/enum field points at a renamed type (shape may still match). |
| `repeated_to_singular`     | WIRE     | BOTH     | Cardinality flip between singular and repeated. |
| `map_to_repeated`          | WIRE     | BOTH     | Map ↔ repeated conversion. |
| `oneof_membership_changed` | SEMANTIC | BOTH     | Field moved in/out of a real oneof. |
| `oneof_field_added`        | SEMANTIC | BACKWARD | New alternative in a real oneof — old exhaustive switches break. |
| `required_field_added`     | WIRE     | FORWARD  | New proto2 `required` field — old producers can't satisfy. |
| `options_changed`          | POLICY   | BOTH     | Any serialized-options change. |
| `presence_changed`         | SEMANTIC | BOTH     | `has_presence` differs across schemas. |
| `enum_value_removed`       | SEMANTIC | FORWARD  | Enum value deleted — new consumer sees unknown number in old data. |
| `enum_value_added`         | SEMANTIC | BACKWARD | Enum value added — old consumer sees unknown number in new data. |
| `enum_number_reused`       | WIRE     | BOTH     | Enum number now binds a different name. |
| `enum_value_number_changed` | WIRE    | BOTH     | Same enum value name, different number — old bytes decode to no name, new bytes to an unknown one. |
| `reserved_field_reused`    | WIRE / SEMANTIC | BOTH | Reserved number reused → WIRE; reserved name reused → SEMANTIC. |

> **Note:** Directions indicate **which reader is at risk**, not which side
> of the schema changed. `BACKWARD` = old consumer fails on new data
> (breaks forward compatibility); `FORWARD` = new consumer fails on
> old data (breaks backward compatibility). This keeps profile names
> aligned with what they filter: `CONSUMER_SAFE` = BACKWARD + BOTH
> protects old consumers; `PRODUCER_SAFE` = FORWARD + BOTH protects
> against old producers.

### Custom Rules (Plugins)

Plugins inspect descriptors and call `ctx.emit(...)` to record findings. Register on a `SchemaChecker`:

```python
from protokit.schema import (
    CompatibilityLevel,
    FieldRuleContext,
    SchemaChecker,
    Severity,
)

def no_newly_deprecated_fields(ctx: FieldRuleContext) -> None:
    """Flag fields that gained a `deprecated = true` option."""
    if ctx.old_field is None or ctx.new_field is None:
        return
    old_dep = ctx.old_field.GetOptions().deprecated
    new_dep = ctx.new_field.GetOptions().deprecated
    if not old_dep and new_dep:
        ctx.emit(
            severity=Severity.POLICY,
            message="field newly marked deprecated",
        )

checker = SchemaChecker(level=CompatibilityLevel.STRICT)
checker.register_field_rule("no_newly_deprecated", no_newly_deprecated_fields)
report = checker.check(old_pool, "acme.User", new_pool, "acme.User")
```

Message-level plugins fire once per message type pair:

```python
from protokit.schema import MessageRuleContext

def require_docs(ctx: MessageRuleContext) -> None:
    # Example: enforce that new messages carry docstring comments.
    ...

checker.register_message_rule("require_docs", require_docs)
```

Both plugin kinds must be **path-independent**. A message type reachable by several paths is visited once, and the findings emitted during that visit are replayed under every other referencing path with the path rewritten — so a plugin that branches on `ctx.path`, or interpolates it into `message`, produces a finding reported at one path whose text names another.

Plugin exceptions (and misuse like returning an awaitable) are caught — the engine records a `Warning` entry in `report.warnings` and continues with subsequent plugins. No single bad plugin can take down a compatibility check. When any `report.warnings` are present, `protokit compat` exits with code 2 so CI never silently passes a broken custom policy.

### Rule Packs

A rule pack is any Python module exposing a `RULES` list of `(rule_id, plugin_fn)` pairs:

```python
# myorg/proto_rules.py
RULES = [
    ("no_newly_deprecated", no_newly_deprecated_fields),
    ("require_docs", require_docs_on_messages),
]
```

Load via CLI:

```bash
protokit compat old.descriptor_set new.descriptor_set \
  --type acme.User \
  --compat-rule-pack myorg.proto_rules
```

Or programmatically:

```python
import myorg.proto_rules
checker.load_rule_pack(myorg.proto_rules)
```

> **Note:** Rule packs are ordinary Python modules. `load_rule_pack` runs
> `importlib.import_module(...)`, which executes the module's top-level
> code. Only load rule packs from sources you trust — the same bar you'd
> apply to `pip install`.

### Composing a `CompatibilityPolicy`

Bundle a profile with custom rules and ignore paths for reuse across type pairs:

```python
from protokit.schema import CompatibilityPolicy, CompatibilityLevel

policy = CompatibilityPolicy(
    base=CompatibilityLevel.CONSUMER_SAFE,
    custom_rules=(("no_newly_deprecated", no_newly_deprecated_fields),),
    ignore_paths=("internal_debug",),
)

report = policy.check(old_pool, "acme.User", new_pool, "acme.User")
```

### CLI Options (`protokit compat`)

| Flag | Description |
|------|-------------|
| positional `OLD_INPUT NEW_INPUT` | Two descriptor sets, or two `.proto` files with `--proto`. |
| `--type NAME` | Fully-qualified type name (same on both sides). |
| `--old-type NAME` | Old-side type name (cross-type mode). |
| `--new-type NAME` | New-side type name (cross-type mode). |
| `--proto` | Treat OLD_INPUT / NEW_INPUT as `.proto` source. Requires `protoc`. |
| `-I`, `--proto-path DIR` | Import path for `protoc` (repeatable, with `--proto`). |
| `--level LEVEL` | `wire` \| `consumer-safe` (default) \| `producer-safe` \| `strict`. |
| `--format NAME` | Output format (default: `human`). Built-in for compat: `human`, `json`, `junit`, `sarif`. See [Output Formatters](#output-formatters). |
| `--formatter-module MODULE` | Python module exposing a `FORMATTERS = [(name, fn, kind), ...]` list (repeatable). See [Output Formatters](#output-formatters). |
| `--compat-rule-pack MODULE` | Dotted module name exposing a `RULES` list. Repeatable. Renamed in 0.8.0 (D7); the old name `--rule-pack` is accepted as a deprecation alias and will be removed in protokit 1.0. |
| `--ignore PATH` | Suppress findings at this dotted path prefix. Repeatable. An empty value is a usage error (exit 2): it would parse to the root path and suppress every finding — omit the flag instead. |
| `--dedupe-by-type` | Emit findings for each shared nested type only once (original behavior). Default is path-complete: findings appear at every path where the type is referenced. |
| `--quiet` | Suppress output; return exit code only. Mutually exclusive with any non-`human` `--format`. |

> **Stability.** `--compat-rule-pack` is part of `protokit compat`'s
> 0.8.0+ public CLI surface; the legacy `--rule-pack` alias is accepted
> as a deprecation path and removed in protokit 1.0. The Python API entry
> point (`SchemaChecker.load_rule_pack`) is unchanged. See CHANGELOG D7
> for the migration path.

### Git-integrated subcommands

`protokit compat` also exposes three git-aware subcommands for
Phase 2 workflows:

- `protokit compat check --since REF --proto-file PATH --type X`
  — compare HEAD against a prior ref.
- `protokit compat check --against-base [BRANCH] --proto-file PATH`
  — compare HEAD against the merge-base with BRANCH (auto-resolves
  `@{upstream}` → `origin/main` → `origin/master` when the
  argument is omitted).
- `protokit compat history --range OLD..NEW --proto-file PATH --type X`
  — walk the commits in the range that affect the proto's
  compatibility and emit per-pair findings.
- `protokit compat bisect --old REF --new REF --proto-file PATH --type X`
  — find the earliest commit in the range that broke
  compatibility.
- `protokit compat ci [--base BRANCH] --proto-file PATH --type X`
  — CI gate, same semantics as `check --against-base` with a
  distinct name for pipeline yaml.

All five support `--format json` (bisect's shape carries
resolved `old` / `new` SHAs, `commits_walked`, and aggregated
per-commit `diagnostics`), and `history` / `bisect` / `ci` accept
the same `--compat-rule-pack` / `--ignore` / `--dedupe-by-type` options
as `check`. `bisect` additionally accepts `--keep-going`, which
walks every commit in the range even after the first break — one
CI run surfaces everything rather than forcing multiple
"fix-rerun" cycles.

### `history` / `bisect` enumeration accuracy (`--fast` tradeoff)

`history` and `bisect` walk a range of commits and determine
which of them affected the root proto's compatibility. Because
proto compatibility depends on the *transitive import graph*
(not just the root file), the enumeration has to look beyond
commits that touched the root itself.

Two modes:

**Default (exact, 10/10 correctness).**
Walks every commit in the range that touched any `.proto` file.
For each candidate commit, parses the root's dep graph *at that
ref* (no compilation — just import-statement scanning) and keeps
the commit only if its changed files intersect the dep graph.
Catches every real break, including those introduced via
dependencies that existed only at intermediate refs. This mode is
the default because a bisect that silently misses a break is
worse than a bisect that took a few extra seconds — the hardest
bug to fix is the one the tool doesn't show you.

**`--fast` (E+, ~9/10 correctness, ~3x faster on monorepos).**
Unions the dep graph at the range's OLD and NEW endpoints and
issues one `git log --follow -- PATH` per file in the union,
merging results. Preserves rename tracking per-path. Misses
commits that modified a dependency which was live *only
mid-range* — e.g. if the root swapped its import from
`date.proto` to `calendar.proto` between OLD and NEW, a commit
that broke `date.proto` while it was still a dep won't appear.
This failure mode is rare in practice (dep swaps aren't a hot
path in most proto repos) but real. Use `--fast` for tight
interactive loops; stay on the default for CI gates.

In both modes, commits that touched `.proto` files *outside* the
root's dep tree are always excluded — unrelated schema churn
never inflates a bisect range.

**Known limitation — rename without importer update.** If a commit
renames a dependency (e.g. `date.proto` → `calendar.proto`)
*without* updating the root proto's import statement in the same
commit, the rename commit can be invisible to the walk even in
exact mode. The root's dep graph at the rename commit can no
longer resolve the old dependency (it's gone) and doesn't yet
know about the new one (import line still says the old name), so
the filter has nothing to intersect with. This is a rare pattern
in practice — most teams rename a file and its importers in the
same commit — but worth flagging. The workaround is to rerun the
walk against a ref where the importer has been updated.

## Schema Linting

> **Positioning**: protokit targets buf BASIC coverage; defaults reflect Python-protobuf-developer ergonomics, not buf's defaults (see `proto2-strict` for opt-in proto2 strictness).

`protokit lint` runs descriptor-level lint rules against one or
more `.proto` files (or pre-built `FileDescriptorSet` binaries).
As of `protokit 0.6.0`, `protokit lint` covers **26 of 26 buf
v1.70.0 BASIC rules**. The 26th rule, `package/no-import-cycle`,
uses a Tarjan SCC pre-walk accumulator to detect package-level
cycles where individual file imports are acyclic (file-level
cycles are caught at the protobuf COMPILE phase by both buf and
protokit's compiler). The proto2-only buf BASIC rule
`FIELD_NOT_REQUIRED` ships in the opt-in `proto2-strict` profile
as of 0.6.0 — outside the 26-rule baseline (which is
proto-syntax-agnostic) but available to proto2 shops via
`--profile proto2-strict` or pyproject
`profile = ["default", "proto2-strict"]`. The built-in packs span single-language style +
cross-language namespace consistency + cross-file directory/package
layout + AIP-203 well-formedness: `naming` (AIP-122 +
PascalCase/snake_case/UPPER_SNAKE conventions for messages, enums,
services, RPCs, oneofs, files, and packages), `enum`
(`no-allow-alias`, `first-value-zero`), `imports` (`no-public`,
`no-weak`, `unused`), `package` (`defined`, `directory-match`,
`same-directory`, `directory-same-package`, `no-import-cycle`), `file`
(`syntax-specified`), `package_same` (`go-package`,
`java-package`, `csharp-namespace`, `php-namespace`, `ruby-package`,
`swift-prefix`, `java-multiple-files`), (new in 0.5.0)
`options/field-behavior-consistent` (AIP-203 well-formedness), and
(new in 0.6.0) `package/no-import-cycle` (Tarjan SCC pre-walk).
**27 rules across 6 packs** in the `recommended` profile, **33
rules** in `default` (adds the deprecated-replacement 5-rule
family + `options/field-behavior-consistent`). Plus, as of 0.5.0, users may
declare **`custom/<user-suffix>`** synthetic rules in
`pyproject.toml` to enforce option-aware annotation requirements
without writing Python (see
[Custom annotation rules](#custom-annotation-rules) below). Lint is
intentionally orthogonal to `protokit compat` — compat answers "is
this schema change safe for consumers?", lint answers "does this
schema follow our style conventions?".

### Quick Start

A typical `pyproject.toml` configuration:

```toml
[tool.protokit.lint]
profile = "default"
exclude = ["third_party/**", "vendor/**"]
min_severity = "warning"
```

A typical invocation:

```bash
# Lint every .proto file in the project (walks pyproject.toml from CWD)
protokit lint protos/**/*.proto

# Lint a pre-built descriptor set
protokit lint schema.descriptor_set

# Override the pyproject min_severity for one run
protokit lint --min-severity error protos/**/*.proto

# Run without any pyproject configuration (use built-in defaults only)
protokit lint --no-config protos/**/*.proto

# Show the running version + the pinned buf parity reference
protokit lint --version
```

### Profiles

`protokit lint` exposes three protokit-native profile names plus two
buf-compatibility aliases. Aliases resolve at the config-load
input boundary, so user rule packs declaring an alias name (e.g.,
`profiles=("basic",)`) will never match — the alias resolves to
its target before rule-pack profile-name lookup.

| Profile | Rules | Purpose |
|---------|-------|---------|
| `essentials` | 0 (forward-placeholder) | Light-touch tier reserved for a future curation pass; no rules ship in this profile as of 0.6.0. |
| `recommended` | 27 | Buf BASIC parity (26 of 26 buf v1.70.0 BASIC rules, complete as of 0.6.0). `naming` (9), `enum` (2), `imports` (3), `package` (5; includes `package/no-import-cycle` via Tarjan SCC pre-walk), `file` (1; `file/syntax-specified` demoted to WARNING in 0.6.0 — pragmatic-not-dogmatic about proto2), `package_same` (7). |
| `default` | 33 | Buf BASIC parity (`recommended`'s 27 rules) + the deprecated-replacement family (5 **error-severity** option-aware rules in `options/deprecated_replacement` — promoted from WARNING in 0.7.0; demotable via `[severities]` / `disabled_rules` / `--disable-rule`) + AIP-203 well-formedness (1 warning-severity rule in `options/field_behavior`: `options/field-behavior-consistent`). |
| `proto2-strict` (0.6.0+) | 1 | Opt-in proto2-specific strictness. Currently ships `field/not-required` (the proto2-only `buf:FIELD_NOT_REQUIRED` rule at ERROR severity). Activate via `--profile proto2-strict` or pyproject `profile = ["default", "proto2-strict"]`. Proto2-specific anti-pattern rules ship here rather than in `recommended`/`default` so proto2 shops opt in explicitly. |
| `minimal` (alias) | → `essentials` | Buf-compatibility alias resolved at `_coerce_profile`. |
| `basic` (alias) | → `recommended` | Buf-compatibility alias resolved at `_coerce_profile`. |

The buf-parity rule library ships at the `error` severity floor
(matching buf's BASIC severity posture), with one deliberate
divergence: `file/syntax-specified` is demoted to `warning` in
`recommended` + `default` as of 0.6.0 under the
pragmatic-not-dogmatic UX philosophy — proto3-only shops who
relied on the prior ERROR enforcement can re-promote via
`[tool.protokit.lint.severities] "file/syntax-specified" = "error"`.
The deprecated-replacement family in `default` originally shipped
at `warning` to bound the leading-comment-regex heuristic's blast
radius; the 0.7.0 release flips it to `error` after empirical
validation confirmed a 0.0% noisy hit-rate on a googleapis sample
(see the 0.7.0 entry in the CHANGELOG). To soften the floor without
dropping rules: use `--min-severity=warning` globally, or
`[tool.protokit.lint.severities]` per-rule (see below). To
suppress one or more rules entirely, see the new
[Disabling and re-enabling rules](#disabling-and-re-enabling-rules)
section.

### Disabling and re-enabling rules

As of 0.7.0, `protokit lint` exposes a full per-rule disable /
enable surface across three interfaces — pyproject, CLI, and
programmatic `from_dict`. Five mechanisms total; all unified at
the config-resolution layer so the engine hot path sees only an
effective rule set.

**Disable mechanisms:**

| Mechanism | Where | Example |
|-----------|-------|---------|
| `"off"` severity (sentinel) | `[tool.protokit.lint.severities]` | `"naming/snake-case-fields" = "off"` |
| `disabled_rules` list | `[tool.protokit.lint]` | `disabled_rules = ["naming/snake-case-fields"]` |
| `--disable-rule` flag | CLI (repeatable; env-var `PROTOKIT_DISABLE_RULE`) | `--disable-rule naming/snake-case-fields` |

**Enable mechanisms:**

| Mechanism | Where | Example |
|-----------|-------|---------|
| `enabled_rules` list | `[tool.protokit.lint]` | `enabled_rules = ["package/no-import-cycle"]` |
| `--enable-rule` flag | CLI (repeatable; env-var `PROTOKIT_ENABLE_RULE`) | `--enable-rule package/no-import-cycle` |

**Composition precedence (polarity-first / tier-second):**

1. Any disable at any tier wins over any enable (polarity-first).
   `--enable-rule R` does NOT override pyproject
   `disabled_rules ⊇ R` — a `LintRuntimeWarning(category="contradictory_disable_config")`
   fires on the contradiction.
2. Within the same polarity, CLI overrides pyproject
   (tier-second). `--disable-rule R` wins over pyproject
   `enabled_rules ⊇ R`.

**Custom-rule prefix expansion**: for user-declared
`[[custom_annotation_rules]]` entries, the bare form
`disabled_rules = ["custom/<suffix>"]` suppresses every kind
of `<suffix>` (multi-kind expansion at config-resolution).
The same expansion applies to `enabled_rules` and to
`[tool.protokit.lint.severities]` keys, so
`"custom/<suffix>" = "warning"` retunes every kind just as
`= "off"` disables every kind. Per-kind targeting still works
via the explicit mangled form (`"custom/<suffix>__method"`),
which takes precedence over the bare family entry.

**Escape hatch**: `--no-config` bypasses the entire pyproject
table (profile, exclude, severities, custom_annotation_rules,
AND `disabled_rules` / `enabled_rules`). Users who want to
override ONE disabled rule without losing the rest of their
pyproject config MUST edit the pyproject directly. The
`contradictory_disable_config` warning text names `--no-config`
as the blunt-instrument escape hatch with this caveat.

**Severity filtering interaction**: `--min-severity` is a
display filter, NOT a disable mechanism. A rule at
`--min-severity warning` still LOADS and runs, but its INFO
findings are dropped post-`engine.run`. Use one of the disable
mechanisms above to skip loading the rule entirely.

**Unknown rule_ids**: entries in `disabled_rules` /
`enabled_rules` that don't match any loaded rule_id fire one
`LintRuntimeWarning(category="unknown_rule_id")` per id
(lenient-with-warning; the rest of the config still applies).
Carries the normalized rule_id so case-sensitivity / typo
issues are visible.

### Upgrade notes (0.4.x → 0.5.0)

0.5.0 ships option-aware pack expansion as the strategic-
differentiator headline: users now declare option-aware annotation
requirements via `[[tool.protokit.lint.custom_annotation_rules]]`
in `pyproject.toml` without writing Python (synthetic
`custom/<user-suffix>` rules). 0.5.0 also adds the first AIP-203
well-formedness validator (`options/field-behavior-consistent`) to
the `default` profile.

Migration impact:

- **`recommended` users** — zero new findings on upgrade.
- **`default` users without `(google.api.field_behavior)`** — zero
  new findings on upgrade.
- **`default` users consuming `(google.api.field_behavior)`** —
  may see new warning-severity findings on duplicate values, the
  `FIELD_BEHAVIOR_UNSPECIFIED` zero value, or 5 curated
  contradictory pairs. Demote to `info` via `[severities]` or fix
  the schema per AIP-203 guidance.

The buf BASIC parity numerator at 0.5.0 ship time was **25 of 26 + 1
scheduled** (the +1 scheduled rule was `FIELD_NOT_REQUIRED`,
originally scoped for 0.5.0 but deferred to a later release).
0.6.0 closes both: `FIELD_NOT_REQUIRED` lands in the opt-in
`proto2-strict` profile, and `PACKAGE_NO_IMPORT_CYCLE` (the 26th)
lands in `recommended` + `default` — see the 0.5.x → 0.6.0
upgrade notes below.

See the 0.5.0 entry in `CHANGELOG.md` for:

- Full additions enumeration (`custom/<suffix>` synthetic rule
  infrastructure + `options/field-behavior-consistent` 3-arm
  dict-template rule + dynamic-pool extension-access helper +
  worked-example integration fixture).
- Wire-format changes (`schema_version` `0.3` → `0.5` via two
  closed-Literal `LintRuntimeWarning.category` additions:
  `custom_annotation_extension_unresolved` + `extension_unresolved`).
- **Pre-upgrade migration recipe** (2 numbered demotion paths;
  schema-fix preferred).
- Worked-example walkthrough (synthetic `custom/<suffix>`).
- Consumer migration (Python API audit for `LintRuntimeWarning.
  category` switch tables; `_extension_access` + `_custom_rules`
  + `CustomAnnotationRuleSpec` INTERNAL classifications).

### Upgrade notes (0.5.x → 0.6.0)

0.6.0 closes the buf-parity arc: `protokit lint` now covers
**26 of 26 buf v1.69.0 BASIC rules** + ships the
`proto2-strict` opt-in profile + revises the UX philosophy.

**New rules:**

- **`package/no-import-cycle`** (the 26th buf BASIC rule).
  ERROR severity in `recommended` + `default` profiles. Detects
  package-level import cycles where individual file imports are
  acyclic (file-level cycles are caught at the protobuf COMPILE
  phase). Emits one finding per cycle-closing `import` statement
  at the import's line/column.
- **`field/not-required`** (the proto2-only
  `buf:FIELD_NOT_REQUIRED` rule). ERROR severity in the new
  opt-in `proto2-strict` profile only. Activate via
  `--profile proto2-strict` or pyproject
  `profile = ["default", "proto2-strict"]`.

**Behavior changes:**

- **`file/syntax-specified` demoted from ERROR to WARNING** in
  `recommended` + `default` profiles under the
  pragmatic-not-dogmatic-about-proto2 UX philosophy. Re-promote
  via `[tool.protokit.lint.severities] "file/syntax-specified" =
  "error"` if your project is proto3-only.

**Migration impact by `--max-warnings` posture:**

| Posture | Pre-0.6.0 | Post-0.6.0 |
|---|---|---|
| `--max-warnings` unset | proto2 file: exit 1 (ERROR) | proto2 file: exit 0 (WARNING; not counted) — **silent CI-pass regression risk** |
| `--max-warnings 0` | proto2 file: exit 1 | proto2 file: exit 1 (counted as warning instead of error) |
| `--min-severity error` | proto2 file: exit 1 (ERROR passes severity floor) | proto2 file: exit 0 (WARNING filtered by severity floor) |

**Pre-upgrade migration recipe** (full text in the 0.6.0 entry of
`CHANGELOG.md`):

- Want explicit ERROR enforcement of `file/syntax-specified`?
  `[tool.protokit.lint.severities] "file/syntax-specified" = "error"`
- Want proto2-strict checks?
  `[tool.protokit.lint] profile = ["default", "proto2-strict"]`
- Have package-level import cycles you're not ready to fix?
  `[tool.protokit.lint.severities] "package/no-import-cycle" = "warning"`
- Want to demote `field/not-required` after opting in?
  `[tool.protokit.lint.severities] "field/not-required" = "warning"`
- Pin to 0.5.0 indefinitely? `pip install protokit==0.5.0`

### Upgrade notes (0.6.x → 0.7.0)

0.7.0 ships two paired changes: a **deprecated-replacement
promotion** that flips all 5 rules in
`options/deprecated_replacement` from WARNING to ERROR in the
`default` profile only, and a **per-rule disable surface** (see
the new
[Disabling and re-enabling rules](#disabling-and-re-enabling-rules)
section above). The per-rule disable surface shipped first as the
safety net so the migration recipe is real on day one.

**Behavior change — deprecated-replacement promotion:**

All 5 rules in `options/deprecated_replacement` now fire at
`error` severity in the `default` profile. Deprecated elements
MUST carry a replacement reference in their leading comment
OR be explicitly suppressed via one of the disable mechanisms
above. The heuristic regex is UNCHANGED — only the severity
flips. `recommended` is unaffected (the
deprecated-replacement family has no buf BASIC analogue and
ships `default`-only).

**Migration impact by `--max-warnings` posture:**

| Posture | Pre-0.7.0 | Post-0.7.0 |
|---|---|---|
| `--max-warnings` unset | finding: exit 0 (WARNING; not counted) | finding: exit 1 (ERROR; `has_error` short-circuits) — **silent CI-pass regression risk** |
| `--max-warnings 0` | finding: exit 1 (counted as warning) | finding: exit 1 (ERROR; `has_error` short-circuits before `max_warnings` gate) |
| `--min-severity error` | finding: exit 0 (WARNING filtered by floor) | finding: exit 1 (ERROR passes floor) |

The posture-1 row is the dominant concern: projects that
previously ignored deprecated-replacement WARNINGs will see CI
flip from green to red on upgrade.

**Empirical validation** (hard gate before promotion): 200 random
`.proto` files from googleapis (`random.seed(42)`) returned
19 deprecated-replacement findings; manual classification per a
documented noisy-vs-load-bearing rubric returned 0 noisy hits
(0.0%). Gate threshold was >10% OR >5 absolute noisy hits → STOP.
Result: gate passed with substantial margin. Full audit trail
in the 0.7.0 CHANGELOG entry.

**Pre-upgrade migration recipe** (full text in the 0.7.0 entry of
`CHANGELOG.md`):

1. **Fix the schema** (recommended). Add a replacement
   reference to the leading comment of every deprecated
   element.
2. **Demote one rule back to WARNING**:
   `[tool.protokit.lint.severities] "options/deprecated-field-must-have-replacement-comment" = "warning"`
3. **Disable one rule via `"off"`** (new in 0.7.0):
   `[tool.protokit.lint.severities] "options/deprecated-field-must-have-replacement-comment" = "off"`
4. **Disable the whole deprecated-replacement family via
   `disabled_rules`** (new in 0.7.0):
   `[tool.protokit.lint] disabled_rules = [...]` with the 5
   rule_ids. See the CHANGELOG for the full 5-rule family-list
   form.
5. **Pin to 0.6.0 indefinitely**: `pip install protokit==0.6.0`.

**Wire-format change**: `_LINT_JSON_SCHEMA_VERSION` bumps
`"0.5"` → `"0.6"` for the two new `LintRuntimeWarning.category`
Literal values (`"contradictory_disable_config"` +
`"unknown_rule_id"`). Consumers parsing the schema against
`"0.5"` MUST update. The pyproject `[project] version`
bumps `0.6.0` → `0.7.0` independently per the version-bump
communication contract.

### Custom annotation rules

Declare option-aware annotation requirements in `pyproject.toml`
via the `[[tool.protokit.lint.custom_annotation_rules]]` array-of-
tables. Each entry materializes a synthetic `custom/<rule_suffix>`
rule that participates in profile composition + `[severities]`
overlay exactly like a built-in rule.

```toml
[[tool.protokit.lint.custom_annotation_rules]]
rule_suffix    = "audit-required"
option         = "example.audit_level"
element_kinds  = ["method"]
allowed_values = ["LOW", "HIGH", "CRITICAL"]
severity       = "error"
```

Fields:

- `rule_suffix` (required) — kebab-case identifier matching
  `[a-z][a-z0-9]*(-[a-z0-9]+)*`. The synthetic rule_id is
  `custom/<rule_suffix>`. Must NOT collide with another entry or
  with a built-in `custom/*` rule_id (none ship today; the prefix
  is reserved for user declarations).
- `option` (required) — fully-qualified extension name in
  descriptor-pool form (bare; e.g., `example.audit_level`). NOT
  the parenthesized proto-source syntax (`(example.audit_level)`);
  `pool.FindExtensionByName` accepts only the bare form, and
  passing the parenthesized form silently emits one
  `LintRuntimeWarning(category="custom_annotation_extension_unresolved")`
  per file instead of firing the rule. Duplicate `rule_suffix`
  across entries is rejected at config-load with exit code 2
  (`error[lint-pyproject-config-invalid]:`).
- `element_kinds` (required) — non-empty subset of `ElementKind`
  values: `"field"`, `"method"`, `"message"`, `"enum"`,
  `"enum_value"`, `"service"`, `"file"`, `"oneof"`.
- `allowed_values` (optional) — homogeneous scalar list (all
  strings OR all ints OR all bools). When present, the rule fires
  both on presence absence AND on values outside the set. Floats
  and mixed-type lists are rejected at config-load.
- `severity` (optional) — `"error"` / `"warning"` / `"info"`;
  defaults to `"warning"`. As of 0.7.0, `"off"` is also
  accepted at `[tool.protokit.lint.severities]` and unloads the
  rule entirely; equivalent to
  `disabled_rules = ["custom/<rule_suffix>"]`. See the
  [Disabling and re-enabling rules](#disabling-and-re-enabling-rules)
  section for multi-kind prefix-expansion semantics.

Behavior:

- The rule fires when the option is **absent** OR (when
  `allowed_values` is set) when its value is **outside the set**.
- Each finding's `violation_kind` is one of
  `"custom-annotation-absent"` (option not present) or
  `"custom-annotation-value-mismatch"` (value not in
  `allowed_values`). `params` carries `"option"` + `"rule_id"`
  on every finding, plus `"actual_value"` on the value-mismatch
  arm (string-coerced enum identifier or raw scalar).
- When `pool.FindExtensionByName` raises `KeyError` (the extension
  is not registered in any input proto), the rule emits one
  structured `LintRuntimeWarning(category="custom_annotation_extension_unresolved")`
  per `(rule_id, file)` pair and skips firing.

A CI-runnable worked example lives at
`tests/schema/lint/cli/test_d6d_custom_annotation_example.py` (with
fixtures under `tests/schema/lint/cli/cli_fixtures/d6d_custom_annotation/`).

### Upgrade notes (0.3.x → 0.4.0)

0.4.0 adds the first cross-file lint dispatch infrastructure
(a pre-walk package-options accumulator) and two rules to consume
it: `package/same-directory` and `package/directory-same-package`.
Combined with the audit-trail correction of the inherited "buf
BASIC = 18 rules" claim (actual: 26 rules), `protokit lint` now
covers **25 of 26 buf BASIC rules**. Teams with cross-directory
package scattering or mixed-package directories will see new
error-severity findings on first 0.4.0 invocation.

See the 0.4.0 entry in `CHANGELOG.md` for:

- Full additions enumeration (the two new rules + the pre-walk
  accumulator + 9-fixture parity gate + three-arm
  `assert_parity_multi_file`).
- Audit-trail correction (`17 of 18` → `25 of 26`; the 0.3.0
  CHANGELOG retains its original numerator framing as audit
  trail).
- Behavior changes (the two new rules firing default-on as error
  severity; wire format unchanged at `schema_version: "0.3"`).
- **Pre-upgrade migration recipe** with 5 numbered TOML demotion
  paths (path 5 covers Python API consumers via
  `LintProfile.rule_severity_overrides`).
- Upgrade-notes triage recipe (5-step adoption walkthrough,
  including co-fire-resolution-order guidance).
- Consumer migration (`FileLintContext.directory_packages` +
  `directory_packages_by_dir` + `LintEngine._build_directory_package_accumulator`
  INTERNAL classifications).

### Upgrade notes (0.2.x → 0.3.0)

0.3.0 adds the first option-aware rules (deprecated-replacement
family) + cross-language buf-BASIC parity (PACKAGE_SAME_*
family). Multi-language teams will see new error-severity findings
on cross-file option disagreement.

See the 0.3.0 entry in `CHANGELOG.md` for:

- Full additions enumeration (the two new rule families + a
  runtime-warning addition + parity gate + multi-file harness).
- Wire-format changes (`schema_version` `0.2` → `0.3`).
- Behavior changes (PACKAGE_SAME_* firing default-on as error
  severity).
- **Pre-upgrade migration recipe** with 4 numbered TOML demotion
  paths + worst-case adoption math (up to 140 findings on a 20-file
  no-package legacy corpus) + 3 accepted-tradeoff scenarios
  (`""`-package aggregation, transitive-import supply chain, WKT
  enforcement).
- Upgrade-notes triage recipe (5-step adoption walkthrough).
- Consumer migration (Python API audit for `LintRuntimeWarning.
  category` switch tables; `CompileResult.source_info_descriptors`
  INTERNAL classification).

### Upgrade notes (0.1.x → 0.2.0)

Upgrading from `protokit 0.1.x` to `0.2.0` expands `BUILTIN_PACKS`
from 1 pack (`naming`, 9 rules) to 5 packs (17 rules total).
Existing users will see new ERROR-severity findings on
previously-green CI.

Triage path:

1. Upgrade `protokit` (`pip install -U protokit` or equivalent).
2. Enumerate the new findings:

   ```bash
   protokit lint --format=json <inputs> | jq '.findings[] | {rule_id, severity, location}'
   ```

3. Decide per finding: fix the schema, or demote the rule (next
   section). Per-rule demotion in `pyproject.toml` is the
   lowest-cost option for category-wide noise (e.g.,
   `imports/unused` on vendored protos — pair with `exclude` for
   the vendored paths themselves).
4. For an emergency revert, pin `protokit~=0.1.0` (which means
   `>=0.1.0, <0.2.0`) and file an issue describing any
   false-positives. Pre-1.0 is the right time to surface rule
   heuristic gaps.

### Demotion paths

The 0.2.0 release ships rules at `error` severity (buf BASIC
parity). Four demotion paths are available, in increasing
specificity:

1. **Pin to 0.1.x** (`protokit~=0.1.0`) — defers the upgrade
   entirely.
2. **Full opt-out** — `--no-builtin-rules` (CLI) or
   `[tool.protokit.lint] no_builtin_rules = true` (pyproject)
   skips `BUILTIN_PACKS` entirely. Pair with `--rule-pack
   MODULE` to provide a custom rule set; an empty rule set
   exits 2 via the `no-rules` error code.
3. **Global severity floor** — `--min-severity=warning` or
   `[tool.protokit.lint] min_severity = "warning"` raises the
   floor across every rule. Cheapest if you want to keep
   visibility without blocking CI on the new categories.
4. **Per-rule severity overrides** —
   `[tool.protokit.lint.severities] "imports/unused" = "warning"`
   demotes one rule without touching the rest. Multiple keys
   compose; user overrides always win on collision with profile
   defaults. Unknown rule_ids fire a `severities_unloaded_rule`
   runtime warning naming each id (typo surfacing without blocking).

```toml
[tool.protokit.lint]
profile = "recommended"

[tool.protokit.lint.severities]
"imports/unused" = "warning"
"file/syntax-specified" = "info"
```

### `[tool.protokit.lint]` configuration

`protokit lint` discovers `pyproject.toml` by walking up from the
current working directory until it reaches the first `.git`
directory or file (worktree-safe — both `.git/` directories and
`.git` pointer files terminate the walk-up). The first
`pyproject.toml` encountered is used; if it lacks a
`[tool.protokit.lint]` table, built-in defaults apply silently.

Recognized keys (every key is optional):

| Key | Type | Description |
|-----|------|-------------|
| `profile` | string or list of strings | Profile name(s) to compose. Single profile is the common case; multi-profile composition lifts the strictest floor and union-merges rule_ids. Buf aliases (`minimal` → `essentials`, `basic` → `recommended`) resolve at the input boundary. |
| `exclude` | list of strings | Gitignore-style globs matched against `FileDescriptorProto.name`. Patterns are additive with CLI `--exclude`. |
| `min_severity` | string (`"info"`, `"warning"`, `"error"`) | Minimum severity to emit. Relaxing the composed profile floor fires a `min_severity_relaxed` runtime warning. |
| `max_warnings` | integer | Non-error exit threshold for warning-level findings. |
| `format` | string | Default output formatter (`"human"`, `"json"`, `"junit"`, `"sarif"`, or a `--formatter-module` name). |
| `no_builtin_rules` | boolean | When `true`, skip loading `BUILTIN_PACKS` (the auto-loaded `naming` / `enum` / `imports` / `package` / `file` packs). User packs supplied via `--rule-pack MODULE` become load-bearing; an empty rule set exits 2 via the `no-rules` error code. |
| `disabled_rules` (0.7.0+) | list of strings | Per-rule disable directives. Accepts canonical `pack/rule-suffix`, bare `custom/<suffix>`, or mangled `custom/<suffix>__<kind>` forms. Bare custom suffixes prefix-expand to every kind of the matching rule. See [Disabling and re-enabling rules](#disabling-and-re-enabling-rules). |
| `enabled_rules` (0.7.0+) | list of strings | Per-rule enable directives. Same accepted formats as `disabled_rules`. Disable wins across all tiers (polarity-first precedence); a contradictory disable+enable fires a `contradictory_disable_config` runtime warning. |
| `[tool.protokit.lint.severities]` | table (rule_id → severity string) | Per-rule severity overrides applied AFTER profile composition. Accepted values: `"error"`, `"warning"`, `"info"`, and (0.7.0+) `"off"` (unloads the rule, equivalent to `disabled_rules`). User overrides always win on collision via post-compose dict-spread. Unknown rule_ids fire a `severities_unloaded_rule` runtime warning (typo surfacing without blocking the run). |

Unknown keys and type mismatches produce a hard error (exit 2)
that names the recognized keys and offending field. List-valued
keys also reject heterogeneous arrays — `exclude = ["a", 1, "b"]`
fails at the element-type check, not silently coerced.

### CLI flags

In addition to the pyproject keys, the CLI carries:

| Flag | Purpose |
|------|---------|
| `--config PATH` | Use a pinned config file; bypasses CWD walk-up. Strict mode: missing/unreadable/table-absent/invalid-TOML all exit 2. |
| `--no-config` | Skip the `[tool.protokit.lint]` table entirely; built-in defaults apply. Mutually exclusive with `--config`. |
| `--exclude PATTERN` | Append a gitignore-style glob to the resolved exclude list (repeatable). |
| `--no-exclude` | Override every pyproject + CLI exclude pattern; lint every input file. Wins at apply-time over `--exclude`. |
| `--profile NAME` | Override the pyproject `profile` key for one run. |
| `--min-severity LEVEL` | Override the pyproject `min_severity` key for one run. |
| `--max-warnings N` | Override the pyproject `max_warnings` key for one run. |
| `--format NAME` | Override the pyproject `format` key for one run. Also reads `PROTOKIT_FORMAT` envvar. |
| `--rule-pack MODULE` | Load a user rule pack on top of the built-ins (repeatable). |
| `--no-builtin-rules` | Skip `BUILTIN_PACKS` for this run. Pair with `--rule-pack MODULE` to supply a custom rule set; empty rule sets exit 2 via the `no-rules` error code. Mirrors `[tool.protokit.lint] no_builtin_rules = true`. |
| `--disable-rule RULE_ID` (0.7.0+) | Per-rule disable directive (repeatable; env-var `PROTOKIT_DISABLE_RULE` uses space-separated values per Click `multiple=True` semantics — `PROTOKIT_DISABLE_RULE="naming/snake-case-fields imports/unused"` — comma-separation is NOT supported). Wins over pyproject `enabled_rules` within polarity (CLI > pyproject); always wins over any enable (polarity-first). Bad values exit 2 via `lint-cli-option-invalid`. |
| `--enable-rule RULE_ID` (0.7.0+) | Per-rule enable directive (repeatable; env-var `PROTOKIT_ENABLE_RULE` uses space-separated values; comma-separation is NOT supported). Same precedence rules apply — `--enable-rule R` does NOT override pyproject `disabled_rules ⊇ R`; a `contradictory_disable_config` warning fires on the contradiction. Use `--no-config` to bypass the entire pyproject (with the caveat that this drops every other pyproject key too). |
| `--version` | Print `protokit <version> (parity: buf <pin>)` and exit. The pinned buf version is `_BUF_PARITY_PIN` in `src/protokit/schema/lint/cli.py`; the parity CI job uses the same pin. |
| `--proto` | Treat inputs as `.proto` source files instead of pre-built descriptor sets; invokes the in-process compile path. |
| `--proto-path DIR` / `-I DIR` | Add an include directory to the `--proto` compile path (repeatable). |
| `--statistics` / `--no-statistics` | Show / suppress the trailing statistics line (filtered count, runtime warnings). |
| `--quiet` | Suppress findings on stdout; structured stderr warnings remain visible. Mutually exclusive with non-`human` `--format`. |

CLI flags replace the pyproject value for their key, except
`--exclude`, which appends. `--no-exclude` clears the resolved
exclude list (CLI + pyproject) entirely.

### JSON output shape (`--format=json`)

The `--format=json` output is a stable wire format for CI integrations
and agents. Top-level keys:

| Key | Type | Description |
|-----|------|-------------|
| `schema_version` | string | Wire-format version (currently `"0.6"` as of 0.7.0; bumped from `"0.5"` for two new `LintRuntimeWarning.category` Literal values per the closed-Literal-discriminator bump policy). Bumps any time JSON/SARIF wire shapes change in a consumer-detectable way. Absence of the key (output from `protokit < 0.2.0`) is the implicit `"0.1"`. The matching SARIF field is `runs[].properties.lint_schema_version`. |
| `findings` | list of objects | One per emitted finding. Per-finding keys: `rule_id`, `severity` (`"error"` / `"warning"` / `"info"`), `location` (rendered string), `location_file`, `location_kind` (lowercased `LintLocation` variant — `"field"`, `"message"`, `"enum"`, etc.), `violation_kind`, `message`. |
| `filtered_count` | int | Findings dropped by `--min-severity` filtering. Mirrored in `summary.filtered_count` for convenience. |
| `runtime_warnings` | list of objects | One per `LintRuntimeWarning`. Per-warning keys: `category` (`"rule_exception"` / `"unloaded_rule"` / `"severities_unloaded_rule"` / `"min_severity_relaxed"` / `"all_files_excluded"` / `"custom_annotation_extension_unresolved"` / `"extension_unresolved"` / `"contradictory_disable_config"` (0.7.0+) / `"unknown_rule_id"` (0.7.0+)), `rule_id` (populated for rule-scoped categories — `rule_exception`, `unloaded_rule`, `severities_unloaded_rule`, `custom_annotation_extension_unresolved`, `extension_unresolved`, `contradictory_disable_config`, `unknown_rule_id` — and `null` for non-rule-scoped categories — `min_severity_relaxed`, `all_files_excluded`), `message`, `exception_type` (string or `null`), `descriptor_path` (string or `null`). |
| `diagnostics` | list of objects | Compile-time diagnostics surfaced by `--proto` mode (level, category, message). Empty for `--input` descriptor-set mode. |
| `summary` | object | Aggregate counts. Keys: `errors`, `warnings`, `info`, `total`, `filtered_count`, `runtime_warning_count`. |

A non-JSON-serializable rule param (e.g., a `pathlib.Path`) renders via
`repr()` rather than failing the entire emission — this guarantees one
broken param value never suppresses every other finding.

### Multi-profile attribution note

When `profile = ["a", "b"]` composes multiple profiles, the
resolved profile floor reported in `min_severity_relaxed`
messages is the composed floor — a single value after the
composition step. The message does not name which contributing
profile set the relaxed floor. If attribution matters, consult
the composed-profile result via the public API rather than
reading it out of the warning message text.

### Security Considerations

`protokit lint` reads `pyproject.toml` files discovered via CWD
walk-up. The walk-up terminates at the **first** `.git` directory
or file encountered, which is the typical project-root boundary
for any code-bearing repository.

**Bypass channels.** The following configuration keys can relax
lint policy and therefore should be reviewed alongside any other
policy-affecting change:

- `exclude` — drops files from the lint pool.
- `min_severity` — raises the emission floor (hides findings).
- `max_warnings` — raises the non-error threshold (turns failures
  into passes).
- `profile` — switches the active rule set; a less-strict profile
  exercises fewer rules.

Changes to these keys should go through the same code-review
discipline as source-level changes; CI gates that enforce lint
policy should be aware that `[tool.protokit.lint]` edits are
policy-affecting.

**Walk-up trust assumptions.** The walk-up uses `Path.exists()` on
the `.git` candidate (not `Path.is_dir()`), which covers standard
checkouts AND git worktrees / submodules. The `.git` path is
checked for existence only; its contents (the `gitdir: ...`
pointer in worktree `.git` files) are NEVER read, parsed, or
followed by `protokit lint`.

**No-`.git` CI caveat.** If the working tree is not a git
checkout — e.g., a shallow-clone-replacement that strips `.git`,
or a CI environment that materializes sources outside any
repository — the walk-up runs to the filesystem root. In that
configuration, an attacker who controls a parent directory of the
CWD can plant a `pyproject.toml` containing
`[tool.protokit.lint]` keys that relax the lint policy. For
untrusted-parent-CWD environments, use `--no-config` (to disable
pyproject reading entirely) or `--config <pinned-path>` (to read
a specific, vetted config) instead of the default walk-up.

### Pre-1.0 stability disclaimer

`protokit` is pre-1.0. Minor-version releases may include
breaking changes to public Python APIs and machine output formats
(JSON, JUnit, SARIF). Breaking changes are documented in the
CHANGELOG — historically via `BREAKING:`-prefixed section
headings (pre-0.2.0), and from 0.2.0 onward via plain
delivery-named sections that describe the user-visible impact
without a ceremonial prefix. The version bump itself is the
authoritative signal; the CHANGELOG section is the communication
contract. Consumers should pin to a specific minor version
(e.g., `protokit~=0.5.0`) until 1.0 ships. The 1.0 release will
**define the stable public surface** and commit to semver
compatibility for that surface.

### Public Surface (DRAFT — frozen at 1.0)

The candidate stable surface, listed here so consumers can
anticipate what 1.0 will commit to. Each row is marked
tentatively `IN` (under consideration for the stable surface) or
`INTERNAL` (deliberately not under consideration; subject to
change without notice). This appendix is maintained each delivery
so 1.0 inherits a defined surface rather than discovering it via
accumulation.

| Surface | Element | Status |
|---------|---------|--------|
| Python dataclass | `LintReport` (fields, ordering, frozen-ness) | IN |
| Python dataclass | `LintRuntimeWarning` (`category: Literal["rule_exception", "unloaded_rule", "severities_unloaded_rule", "min_severity_relaxed", "all_files_excluded", "custom_annotation_extension_unresolved", "extension_unresolved", "contradictory_disable_config", "unknown_rule_id"]` — **CLOSED DISCRIMINATOR**: consumer switch statements should be exhaustive; additions trigger a `_LINT_JSON_SCHEMA_VERSION` minor bump per the bump-contract at `_builtin_lint.py:227-312`. Last two values added in 0.7.0. Contrast with `LintSeverity` open ladder), `rule_id: str \| None`, message, exception_type, descriptor_path | IN |
| Python module | `BUILTIN_PACKS` (auto-loaded rule packs; includes `package_same` as of 0.3.0 → 7 `PACKAGE_SAME_*` rules default-on under `recommended` + `default` profiles) | IN |
| Python function | `leading_comment(source_info_descriptors, file_name, path)` (free function in `protokit.schema.lint.rules.options._comments`; reads `[replaced-by: <X>]` and similar leading-comment annotations from the indexed source-info descriptors) | IN |
| Python class field | `CompileResult.source_info_descriptors: Mapping[str, FileDescriptorProto] \| None` (the source-locations index built from `FileDescriptorSet` before `pool.Add()` discards `source_code_info`; consumed by leading-comment introspection) | INTERNAL |
| Python class field | `FileLintContext.package_options: Mapping[str, Mapping[str, Mapping[str, str \| None]]] \| None` (the pre-walk accumulator for cross-file `PACKAGE_SAME_*` option-consistency rules; outer key `package_name`, second-level key `option_attr`, inner map `{file_name: value}`) | INTERNAL |
| Python method | `LintEngine._build_package_options_accumulator` (single-pass file-scan over `compile_result.pool_file_names` producing the per-package option-value view; threaded into `FileLintContext.package_options`) | INTERNAL |
| Python class field | `FileLintContext.directory_packages: Mapping[str, Mapping[str, str]] \| None` (per-package view of the pre-walk accumulator; outer key `package_name`, inner map `{file_name: dirname}`; sibling-pattern reference to `FileLintContext.package_options`) | INTERNAL |
| Python class field | `FileLintContext.directory_packages_by_dir: Mapping[str, Mapping[str, frozenset[str]]] \| None` (inverted per-directory view of the pre-walk accumulator; outer key `dirname`, inner map `{package_name: frozenset(file_names)}`; provides O(1) lookup for `package/directory-same-package`) | INTERNAL |
| Python method | `LintEngine._build_directory_package_accumulator` (single-pass file-scan over `compile_result.root_files`; dual-view return shape may extend pre-1.0) | INTERNAL |
| Python dataclass | `LintFinding` (rule_id, severity, location, violation_kind, params) | IN |
| Python dataclass | `LintProfile` (name, rule_ids, min_severity, rule_severity_overrides) | IN |
| Python dataclass | `LintRuleSpec` (rule_id, severity, profiles, source_spec, element, message_template, fn) | IN |
| Python class | `LintEngine.run(compile_result, *, profile)` signature | IN |
| Python helper | `LintProfile.compose(*profiles)`, `LintProfile.from_pack(module, profile_name)` | IN |
| JSON wire | `lint_json` output shape (top-level keys + per-finding/per-warning shapes) | IN |
| JSON wire | `lint_json["schema_version"]: "0.6"` (top-level wire-format version; absence → implicit "0.1"; bumped from `"0.5"` in 0.7.0 for two new `LintRuntimeWarning.category` Literal values) | IN |
| SARIF wire | `runs[].properties.runtime_warnings` shape (level, message, properties.category, properties.subcategory; 0.7.0 adds `properties.rule_id` for `contradictory_disable_config` + `unknown_rule_id` categories only — pre-existing rule-scoped categories (`rule_exception`, `unloaded_rule`, `severities_unloaded_rule`, `custom_annotation_extension_unresolved`, `extension_unresolved`) do NOT carry `rule_id` in the SARIF propertyBag despite being rule-scoped; SARIF consumers needing complete rule_id attribution should use `--format=json` where `rule_id` is populated uniformly) | IN |
| SARIF wire | `runs[].invocations[].toolExecutionNotifications` (compile-stage diagnostics) | IN |
| SARIF wire | `runs[].properties.lint_schema_version: "0.6"` (parity with `lint_json["schema_version"]`) | IN |
| SARIF wire | `tool.driver.rules[].defaultConfiguration.level` (added in 0.7.0; pre-flight rule severity for IDE consumers) | IN |
| JUnit wire | `<system-out>` dual line format (compile diagnostics, then runtime warnings) | IN |
| Profile names | `essentials` / `recommended` / `default` (protokit-native names; `default` extends `recommended` with the deprecated-replacement family (5 error-severity option-aware rules as of 0.7.0 — promoted from `warning`) + `options/field-behavior-consistent`) | IN |
| Profile aliases | `minimal` → `essentials`, `basic` → `recommended` (resolved at `_coerce_profile` input boundary) | IN |
| CLI flags | `--config`, `--no-config`, `--exclude`, `--no-exclude`, `--profile`, `--min-severity`, `--max-warnings`, `--format`, `--rule-pack`, `--no-builtin-rules`, `--disable-rule` (0.7.0+), `--enable-rule` (0.7.0+), `--version` | IN |
| Exit codes | 0 (clean), 1 (findings exceeded threshold), 2 (configuration/setup error, or — 0.15.1+ — an incomplete analysis: a rule raised or a profile-named rule never loaded) | IN |
| Error codes (stderr `error[lint-<code>]:` prefix) | `no-rules`, `unknown-profile`, `format-unavailable`, `compile-failed`, `formatter-exception`, `bad-input`, `pool-conflict`, `missing-imports`, `rule-collision`, `rule-pack-load`, `pyproject-config-load`, `pyproject-config-invalid`, `exclude-pattern-invalid`, `no-rules-after-disable` (0.7.0+), `cli-option-invalid` (0.7.0+), `analysis-incomplete` (0.15.1+) (full set in `_LINT_ERROR_CODES`) | IN |
| Stderr formatter envelopes | `protokit lint: warning [<category>]: <message>` (human format) | IN |
| Internal module | `protokit.schema.lint._config` (loader + `ResolvedLintConfig`) | INTERNAL |
| Internal module | `protokit.schema.lint._cli_utils` | INTERNAL |
| Threshold constants | `_LINT_HUMAN_SUMMARIZATION_THRESHOLD` (per-category human-stderr summarization) | INTERNAL |
| Python function | `protokit.storage.scan(source, registry, *, predicate=None, on_error='raise', error_sink=None) -> ScanResult` (the data-at-rest scan engine; eager `on_error`/`error_sink` validation) | IN |
| Python protocol | `protokit.storage.Source` (`runtime_checkable`; `__iter__` yields `(stream_id, bytes \| memoryview)`; optional `close()`/context-manager cleanup. **`isinstance` is presence-only** — not a record-shape gate) | IN |
| Python dataclass | `protokit.storage.ScanRecord` (frozen: `stream_id: str`, `record_index: int` (GLOBAL feed position), `message: Message`) | IN |
| Python class | `protokit.storage.ScanResult` (iterate once for `ScanRecord`s; `.errors -> tuple[FrameError, ...]` readable only AFTER exhaustion, else `RuntimeError`) | IN |
| Python type alias | `protokit.storage.OnError` = `Literal['raise', 'skip', 'collect', 'route']` (`route` pairs with a required `error_sink` callback; a raising sink propagates) | IN |
| Python class | `protokit.storage.StreamRegistry` (`register_stream(stream_id, schema_source)` resolves once into an isolated pool; `get(stream_id) -> ResolvedSchema \| None`; `stream_id in registry`) | IN |
| Python protocol | `protokit.storage.SchemaSource` (`resolve() -> ResolvedSchema`, self-contained — no `name` arg) + `ResolvedSchema` NamedTuple `(pool, message_class)` | IN |
| Python class | `protokit.storage.FileDescriptorSetSchema(fds, message_type_name)` / `EmbeddedSchema((fds_bytes, fq_name))` / `ProtoFileSchema(proto_path, message_type_name, *, proto_paths=())` (the three schema forms; the last compiles `.proto` via the non-exiting compile path) | IN |
| Python exception | `protokit.storage.StorageError` (base) / `FrameError(stream_id, record_index, offset, reason)` / `DuplicateStreamError(stream_id)` / `SchemaCompileError(proto_path, detail)` / `WhereError(expr, reason)` / `FieldSelectionError(spec, reason)` | IN |
| Python function | `protokit.storage.compile_fields(spec, descriptor) -> CompiledSelection` then `protokit.storage.project(message, selection) -> dict` (the two-step `--fields` projection: `compile_fields` validates a comma-separated dotted-path spec against a message descriptor — an invalid path raises `FieldSelectionError`; `project` prunes a parsed message to the faithful nested view — snake_case keys; no-presence fields filled, presence-bearing by presence) | IN |
| Python function | `protokit.storage.sources.length_delimited(file, *, stream_id, max_frame_size=64*1024*1024)` / `per_message_view(buffers, *, stream_id)` (reference frame adapters — examples of the boundary, not protokit's framing taxonomy) | IN |
| CLI | `protokit storage scan\|head\|count <file> (--desc\|--proto) --type <fqn> [--where EXPR] [--on-error raise\|skip\|warn]` — `scan`/`head` add `--format human\|json`, `--fields PATHS` (snake_case faithful view), `--explicit-defaults` (JSON-only dense full record, camelCase; mutually exclusive with `--fields`); `scan` alone adds `--format parquet` with `-o/--output PATH` (typed Parquet via the `protokit[parquet]` extra; all-or-nothing, atomic overwrite-on-success; rejects `--on-error skip\|warn`, `--fields`, `--explicit-defaults`, and env-sourced `PROTOKIT_FORMAT=parquet`); `head` adds `-n`, `count` adds `--quiet`. Exit `0`/`2` (+ `count --quiet` grep-like `1`) | IN |
| Internal modules | `protokit.storage.{engine,source,registry,schema_source,cli,_where,_fields}` (implementation modules; import the public names from `protokit.storage`, never these directly; `_where.compile_where` is internal — only `WhereError` is public for `--where` — whereas the `--fields` projection exports `compile_fields` / `CompiledSelection` / `project` / `FieldSelectionError`) | INTERNAL |

The surface above is a working draft. Names and signatures may
shift before 1.0; the version bump + CHANGELOG section for each
delivery is the authoritative signal for any individual change.
Historical `BREAKING:`-prefixed sections (pre-0.2.0) carry the
same weight as plain delivery sections (0.2.0 onward).

## Output Formatters

`--format NAME` selects how `protokit diff` and every `protokit
compat` subcommand render their output. Built-in names cover the
common CI-integration formats; the `--formatter-module` flag
loads user-supplied packs for anything else.

### Built-in formatters

| Kind | Names | Notes |
|------|-------|-------|
| `DIFF` | `human`, `json`, `junit` | `junit` uses a binary-result single-testcase pattern (one assertion per comparison); per-difference detail goes in the failure body. SARIF intentionally omitted — message diffs don't fit SARIF's rule/result model. |
| `COMPAT` | `human`, `json`, `junit`, `sarif` | `junit` is per-finding; empty checks emit a synthetic passing testcase so CI doesn't read the suite as "no tests ran." `sarif` is a single SARIF 2.1.0 `run` with one `result` per finding; `tool.driver.rules` declares every fired rule_id. |
| `COMPAT_HISTORY` | `human`, `json`, `junit`, `sarif` | `junit` wraps per-commit suites under `<testsuites>`; each suite carries the commit subject as `package` and a sequential `id`. `sarif` aggregates results into one `run` with `partialFingerprints.commit` per result. |
| `COMPAT_BISECT` | `human`, `json`, `junit`, `sarif` | `junit` carries `range_spec`, `old_sha`, `new_sha`, and `breaking_commit` in a `<properties>` block. `sarif` exposes the same in `run.properties`. |

15 built-in formatters in total. Built-in names are reserved —
third-party packs cannot register under `(kind, "human")`,
`(kind, "json")`, `(COMPAT, "junit")`, `(COMPAT, "sarif")`,
etc. (See [Trust model](#trust-model).)

### JUnit example

```bash
protokit compat ci --base origin/main \
  --proto-file acme/user.proto --type acme.User \
  --format junit
```

Produces output that validates against the Apache Ant JUnit XML
reference (the format Jenkins, GitLab CI, GitHub Actions test
result actions, CircleCI, and TeamCity all consume):

```xml
<?xml version='1.0' encoding='utf-8'?>
<testsuite name="protokit-compat-acme.User"
           tests="1" failures="1" errors="0"
           timestamp="1970-01-01T00:00:00" hostname="localhost" time="0">
  <properties/>
  <testcase classname="field_removed" name="user.email" time="0">
    <failure type="SEMANTIC/BACKWARD"
             message="field present in old, absent in new">field present in old, absent in new</failure>
  </testcase>
  <system-out/>
  <system-err/>
</testsuite>
```

The vendored xsd lives at `tests/fixtures/junit-xml/JUnit.xsd`
(Windy Road's Apache Ant reference, Apache 2.0 licensed).

### SARIF example

```bash
protokit compat ci --base origin/main \
  --proto-file acme/user.proto --type acme.User \
  --format sarif > findings.sarif
```

Produces a SARIF 2.1.0 document consumable by GitHub Code
Scanning, GitLab security dashboards, and any OASIS SARIF
consumer:

```json
{
  "version": "2.1.0",
  "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
  "runs": [{
    "tool": {
      "driver": {
        "name": "protokit",
        "version": "0.1.0",
        "rules": [
          {"id": "field_removed", "name": "field_removed",
           "shortDescription": {"text": "Field present in old, absent in new."}}
        ]
      }
    },
    "results": [
      {
        "ruleId": "field_removed",
        "level": "error",
        "message": {"text": "field present in old, absent in new"},
        "locations": [{
          "logicalLocations": [{"fullyQualifiedName": "user.email"}],
          "physicalLocation": {"artifactLocation": {"uri": "acme/user.proto"}}
        }]
      }
    ],
    "invocations": [{"executionSuccessful": true}]
  }]
}
```

Severity mapping: `WIRE` and `SEMANTIC` findings map to SARIF
`"error"`; `POLICY` findings map to `"warning"`. The vendored
schema lives at `tests/fixtures/sarif/sarif-2.1.0.json`
(OASIS 2.1.0 via SchemaStore).

### Custom formatters via `--formatter-module`

A formatter pack is any Python module exposing a `FORMATTERS`
list of `(name, fn, kind)` tuples. The function signature is
`(report, FormatterContext) -> str`:

```python
# myorg/formatters.py
from protokit.formatters import FormatterContext, FormatterKind
from protokit.schema import CompatibilityReport


def slack_summary(report: CompatibilityReport, ctx: FormatterContext) -> str:
    # ctx.target_type is None on cross-type runs (--old-type X
    # --new-type Y); fall back to old->new so the suite still
    # identifies what's being checked.
    if ctx.target_type is not None:
        target = ctx.target_type
    elif ctx.old_target_type or ctx.new_target_type:
        target = f"{ctx.old_target_type}->{ctx.new_target_type}"
    else:
        target = "(unknown type)"
    verdict = "COMPATIBLE" if report.is_compatible else "INCOMPATIBLE"
    lines = [f"*protokit compat — {target}*", f"{len(report)} finding(s) · {verdict}"]
    for f in report:
        lines.append(f"• [{f.severity.value}] {f.path}: {f.message}")
    return "\n".join(lines)


FORMATTERS = [
    ("slack", slack_summary, FormatterKind.COMPAT),
]
```

Load it via the CLI:

```bash
protokit compat check old.descriptor_set new.descriptor_set \
  --type acme.User \
  --formatter-module myorg.formatters --format slack
```

Or programmatically:

```python
from protokit.formatters import register_formatter, FormatterKind
register_formatter("slack", slack_summary, kind=FormatterKind.COMPAT)
```

A complete runnable example lives at `examples/custom_formatter.py`.

### Trust model

`--formatter-module` follows the same trust model as the rule-pack
flags (`protokit lint --rule-pack` and `protokit compat
--compat-rule-pack`): protokit imports the named module and reads
its `FORMATTERS` attribute. **A formatter pack runs with your full process
privileges.** It can:

- Read environment variables (including `GITHUB_TOKEN`, AWS
  credentials, anything in the CI environment).
- Make network calls — exfiltrate data or fetch second-stage
  payloads.
- Read or modify any file the invoking user has access to,
  including `.git/` and source code.
- Spawn subprocesses.

Treat formatter packs as `pip install`-grade trust. Only load
packs from sources you already audit for `pip install`. Do not
load a pack just because a GitHub Action config suggests it.

Within that trust model, three things protokit enforces:

1. **Exit code stays the report's verdict.** The CLI exit code
   (0 / 1 / 2) is determined by the compat report itself
   (compatibility verdict + diagnostic levels), not by formatter
   output. A buggy formatter can corrupt the rendered document
   but cannot flip CI gating. A formatter that calls `sys.exit()`
   is caught and routed through the contract-violation error
   path.
2. **Built-in names are reserved.** Third-party packs cannot
   register under `(kind, "human")`, `(kind, "json")`,
   `(COMPAT, "junit")`, `(COMPAT, "sarif")`, etc. Attempts to
   shadow a built-in fail with `conflicts with a reserved
   built-in name` at registration time, regardless of
   `replace=True`.
3. **Best-effort stdout-write guard.** The CLI redirects
   `sys.stdout` to an in-memory buffer for the duration of each
   formatter call and exits 2 if any bytes land there. This
   catches the common accidental footgun — a forgotten
   `print()` or `sys.stdout.write()` in a debug statement.
   **Limitations**: `os.write(1, ...)`, C-extension stdio,
   `sys.__stdout__.write`, and a `sys.stdout` reference
   captured at module-import time all bypass the guard. It is
   a bug-catcher for honest formatters, not a sandbox against
   hostile ones.

> **Note:** Pack import side-effects persist beyond the two-phase
> registry rollback. A pack module that mutates `sys.path`, pokes
> `sys.modules`, or calls `register_formatter` at import time
> leaves those mutations in place even if a later entry in its
> `FORMATTERS` list is malformed and the registry rolls back.
> `protokit.formatters` cannot undo arbitrary Python state. Pack
> authors should keep module-import-time code to a minimum and
> put all registrations in the `FORMATTERS` list; mixing the two
> is undefined behavior. See [Trust model](#trust-model) for the
> broader point: treat packs as `pip install`-grade trust.

### Diagnostics from a custom formatter

Formatters are pure `(report, ctx) -> str` functions — the
returned string is the entire output. If your formatter needs
to emit progress notes, debug lines, or non-fatal warnings,
use Python's standard `logging` module rather than `print()`:

```python
import logging

logger = logging.getLogger("protokit.formatters.my_pack")

def my_formatter(report, ctx):
    logger.info("rendering %d findings", len(report))
    # ... build output ...
    return output
```

Python's `logging` defaults to stderr when `basicConfig` is
called, which keeps debug output off the stdout stream the CLI
uses for structured output. It never interacts with the
stdout-write guard. The protokit-namespaced logger root
`protokit.formatters` is a convention — name your sub-logger
whatever helps downstream filtering.

> **Note:** `register_formatter` rejects re-registration of an
> existing non-built-in name unless `replace=True` is passed
> explicitly. This makes accidental name collisions loud rather
> than silent.

## Storage (data-at-rest scan engine)

`protokit.storage` scans **stored** protobuf — a file of length-delimited
frames, a pybind11 library's per-message `memoryview`, any buffer source —
routing each record to its stream's **isolated** descriptor pool, parsing it,
and yielding the materialized message. It is the data-at-rest counterpart to
the message differ and schema-compatibility pillars, exposed as both a Python
API and the `protokit storage` command line (see below).

The architecture is an *adapter boundary*: your code yields stream-tagged
record bytes through a `Source` (any iterable of `(stream_id, record_bytes)`);
the engine owns routing, parsing, and filtering.

```python
from protokit.storage import StreamRegistry, FileDescriptorSetSchema, scan
from protokit.storage.sources import length_delimited, per_message_view

# Register each stream's schema up front (resolved once into an isolated pool).
registry = StreamRegistry()
registry.register_stream("orders", FileDescriptorSetSchema(fds, "myapp.Order"))

# A Source is any iterable of (stream_id, record_bytes). Two references ship:
#   length_delimited(file, stream_id=...)   varint-prefixed file frames
#   per_message_view(buffers, stream_id=...) memoryview source (pybind11)
source = length_delimited(open("orders.bin", "rb"), stream_id="orders")

for record in scan(source, registry, predicate=lambda m: m.total > 100):
    print(record.stream_id, record.record_index, record.message)
```

**Multi-version scanning is safe by construction.** Register two streams whose
schemas define the same fully-qualified type *differently* — each resolves into
its own isolated pool, so a single interleaved `scan` routes every record to the
right definition with no cross-contamination. Records carry their `stream_id`,
so correlating across related channels is a join on that tag plus a domain key.

**Error policy is fail-loud by default** (`on_error='raise'`). Opt into
tolerance explicitly:

```python
result = scan(source, registry, on_error="collect")
clean = list(result)            # every well-formed record
errors = result.errors          # tuple[FrameError, ...] — read AFTER exhausting
```

`on_error` is `'raise'` (propagate the first `FrameError`), `'skip'` (drop
faulting records), `'collect'` (drop them but report each in `result.errors`),
or `'route'` (deliver each `FrameError` live to a required `error_sink`
callback and continue — a raising sink propagates, and `.errors` raises since
nothing is collected). Reading `.errors` before the iterator is exhausted raises
`RuntimeError` rather than returning a silent partial. The raw record bytes (a
`memoryview` may come straight from a C++-owned buffer) are parsed inside a
confined step and never retained — upb copies into its arena, so the caller may
free the buffer the instant a record is consumed.

**Field selection is available to Python too.** The CLI's `--fields` view is
backed by a public two-step projection API. First compile a comma-separated
dotted-path spec against a message descriptor with
`protokit.storage.compile_fields(spec, descriptor) -> CompiledSelection` (paths
are validated up front; an invalid path raises the typed
`protokit.storage.FieldSelectionError`). Then prune a parsed message with
`protokit.storage.project(message, selection) -> dict`, which returns the same
faithful nested view as the CLI (snake_case keys; no-presence fields filled at
their default, presence-bearing fields by presence):

```python
from protokit.storage import compile_fields, project

selection = compile_fields("header.error_code,source", Order.DESCRIPTOR)
view = project(order, selection)  # {"header": {"error_code": 0}, "source": "svc"}
```

### Command line: `protokit storage`

`scan` / `head` / `count` put a command line over the engine — the `protoc
--decode` replacement (many records, pipeable, filterable):

```bash
# Dump every record readably (text), or as compact JSONL.
protokit storage scan orders.bin --desc orders.desc --type myapp.Order
protokit storage scan orders.bin --proto order.proto -I proto/ \
    --type myapp.Order --format json

# Filter with the minimal --where grammar.
protokit storage count orders.bin --desc orders.desc --type myapp.Order \
    --where 'header.error_code != 0'
protokit storage head orders.bin --desc orders.desc --type myapp.Order -n 5

# Tolerate corruption: warn reports each bad record to stderr and continues.
# For a large sweep, lead with --on-error warn (the default is fail-loud raise).
protokit storage scan big.bin --desc s.desc --type myapp.Event --on-error warn
```

**Schema source:** one of `--desc` (a `FileDescriptorSet`) or `--proto`
(compiled, with `--proto-path`/`-I` import dirs), plus `--type` (the
fully-qualified message name; `--message-type` is an alias).

`-I`/`--proto-path` applies to `--proto` compilation only. A descriptor set
passed with `--desc` carries its imports already resolved, so combining the two
is a usage error (exit 2) rather than an import path that is accepted and
silently dropped.

**`--where`** is deliberately minimal — `path == scalar` / `path != scalar`
(enums by name or number) and `has:path` for field presence. Anything richer
(`and`/`or`, `<`/`>`, functions) is rejected with a pointer back to the Python
`predicate=` API. An empty `--where ''` is an error too, not "no filter" — you
asked to filter, so silently returning every record would be the wrong answer. Traversal through an unset intermediate message reads
defaults, so `header.code == 0` matches a record with no `header`. A literal for
a 32-bit `float` field is narrowed to single precision so it comes from the same
value set as the field (`score == 0.1` matches the stored 0.10000000149011612);
a literal too large for that field, and `nan` for any float/double field (it
never compares equal), are rejected at compile time rather than compiled into a
filter that matches nothing.

**`--on-error`** is `raise` (default, fail-loud), `skip`, or `warn` (report each
fault to stderr and continue). **Recovery limit:** with the length-delimited
reader a *framing* fault (a truncated/oversized frame) ends the scan even under
`skip`/`warn` — only *decode* and *unknown-stream* faults are recovered past.

#### Project to specific fields: `--fields`

`--fields` (on `scan` / `head`; not `count`) emits a faithful nested view of just
the named fields — a comma-separated list of dotted paths — with snake_case keys
that match the paths you typed:

```bash
# Just two fields, as compact JSONL.
protokit storage scan orders.bin --desc orders.desc --type myapp.Order \
    --fields header.error_code,source --format json
# {"header":{"error_code":0},"source":"web"}

# --fields composes with --where (the predicate runs on the FULL message first,
# so it may reference fields you didn't select).
protokit storage scan orders.bin --desc orders.desc --type myapp.Order \
    --fields source --where 'internal_flag == true' --format json
```

**Defaulted fields survive selection (the key point).** Faithfulness is split by
*presence class*. **No-presence fields** — implicit (proto3) scalars, repeated,
map, and enum fields — are shown at their default when defaulted, so
`--fields error_code` emits `{"error_code": 0}` rather than dropping the field and
returning `{}`. **Presence-bearing fields** — proto3 `optional` scalars, `oneof`
members, and singular submessages — are shown only when actually set, and are
never fabricated: an unset `optional`, an inactive `oneof` member, or a leaf under
an unset submessage simply does not appear.

**Selecting a whole submessage** (`--fields header`) emits a *dense-filled* nested
object — every no-presence sub-field at its default — not a sparse echo of only
the set sub-fields. The same presence-class rule applies recursively inside it
(nested no-presence fields fill; nested presence-bearing fields appear only when
set). Leaf values reuse proto's JSON type-mapping (enums by name, int64 as string,
bytes as base64). `--fields` may name a scalar, a whole singular submessage, a
whole repeated or map field, or a `oneof` member, but may not descend into
repeated/map *elements* (e.g. `tags.0` is rejected, exit 2). Under
`--format human`, the view renders as `path: value` lines built from the same
projection — so a selected defaulted field is visible there too.

#### Dense full records: `--explicit-defaults`

`--explicit-defaults` (on `scan` / `head`; **JSON only**) makes a *full* record
dense: every no-presence field is filled at its default; presence-bearing fields
stay by presence. It is a density variant of the default `--format json` — keys
stay **camelCase**, matching the plain JSON it densifies:

```bash
protokit storage scan orders.bin --desc orders.desc --type myapp.Order \
    --explicit-defaults --format json
# {"errorCode":0,"source":"web",...}   every no-presence field present
```

Without the flag, full-record JSON is unchanged (camelCase, defaults omitted).
Under `--format human` it is a clean error (exit 2), not a silent no-op.

**Key casing differs between the two flags by design:** the `--fields` view is
**snake_case** (so rendered keys match the dotted paths you select);
`--explicit-defaults` is **camelCase** (so it stays byte-aligned with the default
JSON). `--fields` and `--explicit-defaults` are **mutually exclusive** — passing
both is a clean error (exit 2).

#### Typed Parquet output: `--format parquet`

`scan` (only) can write its result as a typed Parquet file — a direct
proto→Arrow→Parquet conversion with no JSON intermediate. It needs the
optional `protokit[parquet]` extra and a real output path:

```bash
pip install "protokit[parquet]"

protokit storage scan orders.bin --desc orders.desc --type myapp.Order \
    --format parquet -o orders.parquet
# stderr: wrote 12843 rows to orders.parquet

# --where composes: only matching records are converted.
protokit storage scan orders.bin --desc orders.desc --type myapp.Order \
    --where 'header.error_code != 0' --format parquet -o bad.parquet
```

Every field of the message type maps to a column from the descriptor-derived
schema — there is no `--fields` projection because Parquet readers (pandas,
DuckDB, Spark) project columns at read time essentially for free. An empty
result (zero records, or a `--where` matching nothing) still writes a valid
zero-row file carrying the full schema.

**All-or-nothing.** A Parquet file that reads as complete must *be* complete:
conversion writes a hidden sibling temp file and atomically renames it onto
`-o` only after a complete, fault-free scan. On any fault the command exits
`2` reporting the fault count and first fault location, no output file is
left behind, and a pre-existing file at `-o` is preserved (it is overwritten
only by a complete result). `--on-error skip`/`warn` are rejected up front
with `--format parquet` — a tolerant mode could silently write a file that
under-represents the input. `--fields` and `--explicit-defaults` are rejected
too (full-record output only), and `head`/`count` do not take Parquet at all.
`PROTOKIT_FORMAT=parquet` is not honored: file-writing output must be
explicit on the command line.

**Recursive schemas are rejected.** A message type that references itself —
directly, mutually, or through a map / group / oneof message field — has no
finite columnar representation, so it is rejected up front with `exit 2` and an
error naming the cycle, leaving no output file. This includes the recursive
well-known types `google.protobuf.Struct`/`Value`/`ListValue`; the
non-recursive WKTs (`Timestamp`, `Any`, `Duration`, `FieldMask`, wrappers)
convert normally.

**Fidelity signal (`--fidelity ignore | warn | error`).** A descriptor-driven
Parquet conversion can silently diverge from what a protobuf consumer sees, two
ways: a record may carry wire data the descriptor does not model (a proto2
out-of-range closed enum, or an undeclared field), and the descriptor may declare
a proto2 extension `ptars` cannot columnize — both dropped from the output.
`--fidelity` surfaces both classes: `warn` (the default) writes the file and
prints a stderr line per class; `error` fails the conversion (`exit 2`, nothing
written) — a declared-extension drop fails fast before any record is read;
`ignore` skips the check. The library mirrors this: `to_parquet` returns a
`FidelityReport`, and `to_arrow_batches(..., fidelity=...)` exposes the same
report on its result once the stream is consumed.

**Value encoding is Arrow-native, not the JSON view.** Parquet leaf values
deliberately diverge from the JSON output's encodings: `bytes` → Arrow binary
(not base64 strings), enums → their int32 number (not names), int64 → int64
(not decimal strings), and proto `Timestamp`s land at **microsecond**
resolution (sub-microsecond nanos truncate). Presence semantics match the
faithful view: no-presence fields appear at their default; presence-bearing
fields are null when unset.

**Exit codes:** `0` success, `2` error (a bad flag, an unresolved schema, a
malformed `--where`, or a data fault under `--on-error raise`). `count --quiet`
adds the grep-like signal — `1` when zero records match, `0` otherwise
(mirroring `diff --quiet`); a bare `count` always prints the number (including
`0`) and exits `0`.

Cross-channel correlation (one `scan` over multiple related streams) is a
library capability — register several streams and read `record.stream_id` — and
is not yet exposed on the single-stream CLI.

## Supported Field Types

- Scalars (int32/64, uint32/64, sint32/64, fixed32/64, sfixed32/64, float, double, bool, string, bytes)
- Nested messages (arbitrary depth)
- Repeated fields (index-based or key-based via `treat_as_map`)
- Map fields (native protobuf maps)
- Oneof fields (including proto3 `optional`)
- Enum fields (same-pool and cross-pool with wire-compatibility)

## Requirements

- Python 3.10+
- `protobuf` >= 4.21.0
- `click` >= 8.0

## Acknowledgments

`protokit lint` tracks rule-set parity with [`buf lint`](https://buf.build/product/cli),
the lint subcommand of the [buf](https://buf.build/) CLI by
[Buf Technologies, Inc.](https://buf.build/) — a comprehensive protobuf
tooling suite covering lint, formatting, breaking-change detection,
code generation, the Buf Schema Registry, and the Connect RPC
framework. protokit is an independent project, not affiliated with
or endorsed by Buf Technologies.

The functional overlap is intentionally narrow:

- **`protokit lint` ↔ `buf lint`**: closely tracked. `protokit lint`
  matches 26 of 26 buf v1.70.0 BASIC rules, with deliberate
  divergences where Python-protobuf-developer ergonomics differ
  (see the [Schema Linting](#schema-linting) section's positioning
  statement).
- **`protokit compat` ↔ `buf breaking`**: both detect schema
  compatibility breaks, with different framing — protokit ships four
  named profiles (`WIRE`, `CONSUMER_SAFE`, `PRODUCER_SAFE`, `STRICT`)
  and a pluggable Python rule-pack API.
- **`protokit diff`**: binary protobuf message diffing — no equivalent
  in buf.
- **Everything else buf provides** (`buf format`, `buf generate`,
  `buf push`, the Buf Schema Registry, Connect, protovalidate, etc.):
  protokit does not replicate.

protokit uses Google's official `protobuf` Python library at runtime
and does not depend on any Buf-authored Python package. The `buf` CLI
itself is optional — install via `brew install buf` to cross-verify
protokit's lint output against buf's reference implementation. The
parity test suite (`tests/parity/`) uses an installed `buf` binary
when available and skips cleanly when not.

`buf` is open source under Apache 2.0.

## License

MIT
