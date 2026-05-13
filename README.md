# protokit

Python toolkit for Protocol Buffers: message diffing and schema compatibility checking.

`protokit diff` — structural, filterable message diffs with cross-descriptor-pool comparison, schema evolution detection, and a pytest hook.

`protokit compat` — descriptor-level schema compatibility checks with 17 built-in rules, four profiles, and a pluggable rule API.

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
        print(f"{diff.path}: {diff.old_value} -> {diff.new_value}")

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
  "equal": false,
  "differences": [
    {
      "path": "user.name",
      "change_type": "MODIFIED",
      "old_value": "Alice",
      "new_value": "Bob",
      "field_type": "TYPE_STRING"
    }
  ],
  "warnings": []
}
```

Quiet mode for CI (exit code only):

```bash
protokit diff left.pb right.pb --desc schema.descriptor_set --message-type myapp.User --quiet
echo $?  # 0 = equal, 1 = different, 2 = error
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
| `--proto-path DIR` | Import path for protoc. Repeatable. |
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
| `--max-depth N` | Maximum comparison depth |
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

Message-level plugins fire once per visited message:

```python
from protokit.schema import MessageRuleContext

def require_docs(ctx: MessageRuleContext) -> None:
    # Example: enforce that new messages carry docstring comments.
    ...

checker.register_message_rule("require_docs", require_docs)
```

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
  --rule-pack myorg.proto_rules
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
| `--rule-pack MODULE` | Dotted module name exposing a `RULES` list. Repeatable. |
| `--ignore PATH` | Suppress findings at this dotted path prefix. Repeatable. |
| `--dedupe-by-type` | Emit findings for each shared nested type only once (original behavior). Default is path-complete: findings appear at every path where the type is referenced. |
| `--quiet` | Suppress output; return exit code only. Mutually exclusive with any non-`human` `--format`. |

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
the same `--rule-pack` / `--ignore` / `--dedupe-by-type` options
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

`protokit lint` runs descriptor-level lint rules against one or
more `.proto` files (or pre-built `FileDescriptorSet` binaries).
The built-in packs cover buf BASIC naming and enum semantics —
`naming` (AIP-122 + PascalCase/snake_case/UPPER_SNAKE conventions
for messages, enums, services, RPCs, oneofs, files, and packages)
and `enum` (`no-allow-alias`, `first-value-zero`). Further packs
land in subsequent D6a deliveries (imports, package, file
structural rules). Lint is intentionally orthogonal to
`protokit compat` — compat answers "is this schema change safe
for consumers?", lint answers "does this schema follow our style
conventions?".

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
| `profile` | string or list of strings | Profile name(s) to compose. Single profile is the common case; multi-profile composition lifts the strictest floor and union-merges rule_ids. |
| `exclude` | list of strings | Gitignore-style globs matched against `FileDescriptorProto.name`. Patterns are additive with CLI `--exclude`. |
| `min_severity` | string (`"info"`, `"warning"`, `"error"`) | Minimum severity to emit. Relaxing the composed profile floor fires a `min_severity_relaxed` runtime warning. |
| `max_warnings` | integer | Non-error exit threshold for warning-level findings. |
| `format` | string | Default output formatter (`"human"`, `"json"`, `"junit"`, `"sarif"`, or a `--formatter-module` name). |

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
| `findings` | list of objects | One per emitted finding. Per-finding keys: `rule_id`, `severity` (`"error"` / `"warning"` / `"info"`), `location` (rendered string), `location_file`, `location_kind` (lowercased `LintLocation` variant — `"field"`, `"message"`, `"enum"`, etc.), `violation_kind`, `message`. |
| `filtered_count` | int | Findings dropped by `--min-severity` filtering. Mirrored in `summary.filtered_count` for convenience. |
| `runtime_warnings` | list of objects | One per `LintRuntimeWarning`. Per-warning keys: `category` (`"rule_exception"` / `"unloaded_rule"` / `"min_severity_relaxed"` / `"all_files_excluded"`), `rule_id` (string for engine-emitted categories, `null` for CLI-emitted categories), `message`, `exception_type` (string or `null`), `descriptor_path` (string or `null`). |
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
(JSON, JUnit, SARIF). Breaking changes are explicitly marked
`BREAKING:` in CHANGELOG entries; consumers should pin to a
specific minor version (e.g., `protokit~=0.5.0`) until 1.0 ships.
The 1.0 release will **define the stable public surface** and
commit to semver compatibility for that surface.

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
| Python dataclass | `LintRuntimeWarning` (category Literal, `rule_id: str \| None`, message, exception_type, descriptor_path) | IN |
| Python dataclass | `LintFinding` (rule_id, severity, location, violation_kind, params) | IN |
| Python dataclass | `LintProfile` (name, rule_ids, min_severity, rule_severity_overrides) | IN |
| Python dataclass | `LintRuleSpec` (rule_id, severity, profiles, source_spec, element, message_template, fn) | IN |
| Python class | `LintEngine.run(compile_result, *, profile)` signature | IN |
| Python helper | `LintProfile.compose(*profiles)`, `LintProfile.from_pack(module, profile_name)` | IN |
| JSON wire | `lint_json` output shape (top-level keys + per-finding/per-warning shapes) | IN |
| SARIF wire | `runs[].properties.runtime_warnings` shape (level, message, properties.category, properties.subcategory) | IN |
| SARIF wire | `runs[].invocations[].toolExecutionNotifications` (compile-stage diagnostics) | IN |
| JUnit wire | `<system-out>` dual line format (compile diagnostics, then runtime warnings) | IN |
| CLI flags | `--config`, `--no-config`, `--exclude`, `--no-exclude`, `--profile`, `--min-severity`, `--max-warnings`, `--format`, `--rule-pack` | IN |
| Exit codes | 0 (clean), 1 (findings exceeded threshold), 2 (configuration/setup error) | IN |
| Error codes (stderr `error[lint-<code>]:` prefix) | `no-rules`, `unknown-profile`, `format-unavailable`, `compile-failed`, `formatter-exception`, `bad-input`, `pool-conflict`, `missing-imports`, `rule-collision`, `rule-pack-load`, `pyproject-config-load`, `pyproject-config-invalid`, `exclude-pattern-invalid` (full set in `_LINT_ERROR_CODES`) | IN |
| Stderr formatter envelopes | `protokit lint: warning [<category>]: <message>` (human format) | IN |
| Internal module | `protokit.schema.lint._config` (loader + `ResolvedLintConfig`) | INTERNAL |
| Internal module | `protokit.schema.lint._cli_utils` | INTERNAL |
| Threshold constants | `_LINT_HUMAN_SUMMARIZATION_THRESHOLD` (per-category human-stderr summarization) | INTERNAL |

The surface above is a working draft. Names and signatures may
shift before 1.0; the BREAKING marker in CHANGELOG entries is the
authoritative signal for any individual change.

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

`--formatter-module` follows the same trust model as `--rule-pack`:
protokit imports the named module and reads its `FORMATTERS`
attribute. **A formatter pack runs with your full process
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

## License

MIT
