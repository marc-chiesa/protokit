---
title: "When a resolved value can come from multiple sources, error messages must name the actual source — not assume one"
date: 2026-05-11
category: docs/solutions/best-practices
module: protokit.schema.lint.cli
problem_type: best_practice
component: tooling
severity: medium
applies_when:
  - "A validation check fires on a value that could have been set by a CLI flag, an environment variable, a config file, or a built-in default"
  - "An error or warning message hard-codes a CLI flag name (e.g., '--format=json') but the value may have come from a config file or envvar instead"
  - "A precedence-aware check moves from before-config-load to after-config-load and the message wording is not revisited"
  - "CI scripts or agents grep stderr for specific error-message substrings that include source attribution"
  - "ce:review api-contract, cli-readiness, or agent-native reviewers flag that an error message names a flag the user never typed"
tags:
  - error-attribution
  - source-aware
  - cli-config-precedence
  - user-visible-errors
  - ci-grep-contract
  - mutex-check
  - protokit-lint
  - ce-review
---

# Source-aware error messages for resolved values with multiple sources

## Context

When a CLI tool gains a config-file layer, every validation check
that was written when the only source was a CLI flag becomes
silently wrong: the check still references the flag name in its
error message even when the offending value actually came from the
config file. The validation logic remains correct — the check
correctly identifies the incompatible value — but the **attribution
in the message is wrong**, pointing users to a flag they never typed
and sending them down the wrong diagnostic path.

In protokit-lint D5 U2, the `--quiet` vs `--format` mutex check
illustrates this precisely. Before U2, the check ran before config
loading and necessarily saw only CLI values. U2 introduced
`[tool.protokit.lint] format = "json"` as a config-file-sourced
value, making `resolved.format` potentially pyproject-sourced. The
mutex check was moved to after `ResolvedLintConfig.from_dict()` so
it would catch pyproject-driven formats too — but its error message
continued to hard-code `format=...` attribution that no longer
matched the actual source.

This gap was caught by **3-way convergence** in the D5 U2 ce:review
(api-contract reviewer AC-U2-03, cli-readiness reviewer, agent-native
reviewer — each flagging from a different angle: CI grep stability,
operator UX, and agent stderr parsing respectively). The convergence
was itself the signal that this was a load-bearing contract change,
not a cosmetic wording preference. See
[`apply-institutional-learnings-postdating-plan-during-ce-review`](./apply-institutional-learnings-postdating-plan-during-ce-review-2026-05-09.md)
for the convergence-as-signal doctrine.

This learning is distinct from but adjacent to
[`shared-error-helper-source-label-caller-attribution-2026-05-11`](./shared-error-helper-source-label-caller-attribution-2026-05-11.md):

| Dimension | shared-error-helper-source-label | this learning |
|---|---|---|
| **Structural trigger** | Shared helper called from 2+ code paths | Single error site, value resolved from 2+ runtime sources |
| **What "source" refers to** | Code path / call site identity | Invocation source (CLI flag / env var / config file / default) |
| **Detection mechanism** | Caller injects `source_label: str` parameter | Inspect `ctx.get_parameter_source()` at runtime |
| **Scope of prevention rule** | When extracting a shared helper, add `source_label` | When composing an error for a multi-source value, branch on a pre-computed source boolean |
| **Pairs with** | Code-architecture review (spot shared helpers) | [click-parameter-source-detection-cli-config-precedence](./click-parameter-source-detection-cli-config-precedence-2026-05-11.md) (source detection must precede source attribution) |

Both learnings address the same user harm — wrong source attribution
in error messages — but the structural trigger and the mechanical
fix differ.

## Guidance

### Branch on the source boolean before constructing the error string

The source-detection boolean computed during `cli_overrides` assembly
(see the
[parameter-source-detection learning](./click-parameter-source-detection-cli-config-precedence-2026-05-11.md))
is the canonical signal. Reuse it in any validation check that fires
on the resolved value:

```python
if quiet and resolved.format != "human":
    if format_explicit:
        # Value came from CLI --format flag OR PROTOKIT_FORMAT envvar
        source_desc = f"--format={resolved.format!r}"
    else:
        # Value came from [tool.protokit.lint] format in pyproject
        source_desc = (
            f"[tool.protokit.lint] format={resolved.format!r}"
        )
    raise click.UsageError(
        f"--quiet is incompatible with {source_desc}; "
        "use --quiet only with the human format (the default).",
    )
```

### Placement: after the merge, while the source boolean is still in scope

The check must run AFTER `from_dict()` so it catches all sources, but
BEFORE `_main_impl()` exits with the resolved config. The
`format_explicit` (or equivalent) boolean is still accurate at that
point — it was computed from `ctx.get_parameter_source()` during
`cli_overrides` assembly and does not change.

### Attribution position: lead, don't trail

Lead the message with the source descriptor, not trail it. `--format='json'`
as a leading token mirrors how the user would type or grep for it. A
trailing parenthetical like `format='json' (set by pyproject)` buries
the attribution and makes grep contracts fragile (CI scripts that
match `^.*pyproject` would catch it; scripts matching just the value
prefix would not).

### CI grep contract symmetry

When the source is CLI, the pattern `--format='json'` must appear in
stderr and `[tool.protokit.lint]` must NOT appear. When the source
is pyproject, the inverse holds. Write the test as a symmetric pair
with both positive and negative assertions on each path; otherwise a
future "fix" that emits both prefixes simultaneously (the worst-of-both
case) would pass.

### Symmetric design across all multi-source surfaces

If the codebase emits one source-aware message, every multi-source
surface should follow the same convention. The U2 implementation
extends the same pattern already used by the relaxation breadcrumb:

| Source | Mutex error (F-04) | Relaxation breadcrumb |
|---|---|---|
| CLI / envvar | `--format='json'` | `protokit lint: --min-severity=info relaxes...` |
| pyproject | `[tool.protokit.lint] format='json'` | `protokit lint: [tool.protokit.lint] min_severity=info relaxes...` |

Consistency across surfaces lets users and CI scripts learn one
attribution convention instead of N.

## Why This Matters

**Diagnostic latency.** An operator who sees
`--quiet is incompatible with --format='json'` will search the CI
pipeline definition for `--format json`. When the format was actually
set in pyproject.toml, the operator looks in the wrong place and may
spend significant time before checking the config file. The wrong
attribution sends users down the wrong fix path.
`[tool.protokit.lint] format='json'` immediately points to the
right file.

**CI grep stability.** Agents and CI scripts grep stderr for
specific patterns to classify failures: `--format='json'` routes to
"wrong flag combination" alerts; `[tool.protokit.lint]` routes to
"check pyproject" alerts. When the source changes (U2 introduces
pyproject as a source) but the message does not, grep classification
breaks silently for pyproject-sourced failures.

**Symmetric with existing min_severity breadcrumb.** The U2
implementation extends a source-aware pattern already established in
the relaxation breadcrumb. Source-aware attribution becomes a
consistent design principle across all multi-source output in the
CLI, not a one-off — which lets the
[cross-format-enum-string-parity](./cross-format-enum-string-parity-2026-05-08.md)
discipline (single source-of-truth for output strings) extend
naturally to source attribution.

**Anti-patterns to avoid:**

- Do not reconstruct the source by inspecting `resolved.format`
  against known values at error-message time — the source boolean
  is already computed during `cli_overrides` assembly and is the
  canonical signal.
- Do not use a trailing suffix `(via pyproject)` — leading
  attribution matches user mental models (`--format` is how they'd
  type it; `[tool.X]` is how they'd find it in pyproject).
- Do not skip the check on the assumption "users won't set this in
  pyproject" — the pyproject surface exists precisely to avoid
  repeating flags on every invocation.

## When to Apply

- Any time a validation check fires on a resolved value that a
  config-file layer can supply: add `if <flag>_explicit: ... else: ...`
  attribution branching in the error message.
- When a validation check moves from "before config loading" to
  "after config loading" (because the config file can now supply the
  checked value): the source boolean MUST be carried forward and
  used in error messages.
- When adding a new config-file key that corresponds to an existing
  CLI flag with an existing validation check: audit every validation
  check on that value for source attribution.
- When writing tests for mutex or incompatibility checks: write one
  test per source path (CLI-source and pyproject-source), with
  positive assertions on the expected attribution string AND negative
  assertions that the wrong attribution does not appear. A single
  positive assertion is half coverage.

### Architectural scope: flat-config-only (D6f KD-3)

This learning's scope is two-source attribution: CLI vs. (single)
pyproject. Walk-up-discovered pyproject scenarios (parent + child
pyproject merge) are an EXPLICIT non-goal in protokit — see
[[flat-config-only-single-pyproject-tier-no-inheritance-2026-05-24]].
The "implicit path (e.g., walk-up)" and "walk-up-discovered pyproject"
phrasings in this doc apply only IF protokit ever adopts multi-tier
pyproject inheritance; under the current flat-config-only architecture
they are hypothetical. The two-source attribution contract this doc
defines is complete for the flat-config tier-count.

## Examples

### Before — D3 (pre-U2), hard-coded CLI attribution

```python
# src/protokit/schema/lint/cli.py (D3 shape, pre-config-file)
if quiet and format_name != "human":
    raise click.UsageError(
        f"--quiet is incompatible with --format={format_name!r}; "
        "use --quiet only with the human format (the default).",
    )
```

Hard-coded `--format=` prefix. Accurate when only the CLI could
supply the value. Became wrong in U2 when pyproject could supply
`format`.

### Intermediate — U2 initial (commit `3463691`), prefix dropped without source-awareness

```python
# Check moved after from_dict but message did not branch on source:
if quiet and resolved.format != "human":
    raise click.UsageError(
        f"--quiet is incompatible with format={resolved.format!r}; "
        "use --quiet only with the human format (the default).",
    )
```

Flagged by 3-way convergence in ce:review:

- **api-contract-reviewer (AC-U2-03)**: dropping `--format=` breaks
  CI scripts that grep on the old exact wording.
- **cli-readiness-reviewer (CLR-U2-04)**: operator sees `format='json'`
  in an error but never typed `--format`, giving no diagnostic trail
  to the actual pyproject source.
- **agent-native-reviewer (AN-U2-03)**: agents parsing stderr to
  classify failures cannot route the message correctly when the
  source is ambiguous.

### After — source-aware fix (commit `aa15f98`), as shipped

```python
# src/protokit/schema/lint/cli.py lines 394-407 (post-aa15f98)
if quiet and resolved.format != "human":
    if format_explicit:
        source_desc = f"--format={resolved.format!r}"
    else:
        source_desc = (
            f"[tool.protokit.lint] format={resolved.format!r}"
        )
    raise click.UsageError(
        f"--quiet is incompatible with {source_desc}; "
        "use --quiet only with the human format (the default).",
    )
```

### Tests pinning both source paths

`tests/schema/lint/cli/test_cli_ci_gating.py::TestQuietFlag`:

```python
def test_quiet_with_non_human_format_is_click_validation_error(
    self, clean_descriptor_set: Path,
) -> None:
    """D5 U2 F-04: CLI-sourced format names --format= explicitly."""
    result = CliRunner().invoke(
        lint_main,
        ["--quiet", "--format", "json", str(clean_descriptor_set)],
    )
    assert result.exit_code == 2
    assert "--format='json'" in result.stderr        # positive
    assert "[tool.protokit.lint]" not in result.stderr  # negative


def test_quiet_with_pyproject_format_names_pyproject_source(
    self, tmp_path: Path, clean_descriptor_set: Path,
) -> None:
    """D5 U2 F-04: pyproject-sourced format names [tool.protokit.lint]
    so users see the actual source of the offending value.
    """
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        "[tool.protokit.lint]\nformat = \"json\"\n",
    )
    result = CliRunner().invoke(
        lint_main,
        [
            "--config", str(pyproject),
            "--quiet",
            str(clean_descriptor_set),
        ],
    )
    assert result.exit_code == 2
    assert (
        "[tool.protokit.lint] format='json'" in result.stderr
    )                                                # positive
    assert "--format=" not in result.stderr          # negative
```

The symmetric positive + negative assertions on each path are what
make the test resistant to a regression that emits both prefixes
simultaneously (the worst-of-both case).

## Related Learnings

- [`frozen-dataclass-paired-field-invariant-post-init-2026-05-11.md`](./frozen-dataclass-paired-field-invariant-post-init-2026-05-11.md)
  — upstream guard pairing. Where this doc addresses the runtime
  *message-emission* contract (the message must name the actual
  source), the paired doc addresses the *carrier-construction*
  contract (the dataclass carrying the value-plus-source pair must
  reject states where the source defaults to "none" while the value
  is set). The two compose into a complete pipeline:
  construction-time rejection of contradictory pairs +
  emit-time source-aware branching.
- [`shared-error-helper-source-label-caller-attribution-2026-05-11.md`](./shared-error-helper-source-label-caller-attribution-2026-05-11.md)
  — adjacent discipline at a different structural shape. That doc:
  shared helper called from multiple callers, fix is `source_label`
  parameter. This doc: single error site where the resolved value
  arrives from multiple sources, fix is source-aware branching at
  the check site. Same underlying principle (errors must accurately
  attribute the source); different structural triggers and
  mechanical fixes.
- [`click-parameter-source-detection-cli-config-precedence-2026-05-11.md`](./click-parameter-source-detection-cli-config-precedence-2026-05-11.md)
  — natural pipeline partner. Source detection at the input boundary
  produces the boolean this doc consumes. Without source detection,
  there is no signal to branch on.
- [`cross-format-enum-string-parity-2026-05-08.md`](./cross-format-enum-string-parity-2026-05-08.md)
  — broader source-of-truth-for-output-strings discipline. Source-aware
  attribution is a specific instance: the message templates
  (`--format=X` vs `[tool.protokit.lint] format=X`) should be pinned
  at the CLI emission site so all consumers see identical strings.
- [`normalize-at-input-boundary-2026-05-07.md`](./normalize-at-input-boundary-2026-05-07.md)
  — incidental adjacency. That doc shows how the mutex error fires
  for the wrong reason when normalization is missing; this doc shows
  how the mutex error message itself should be constructed once the
  value is correctly resolved.

## Reference Commits

- `3463691` — D5 U2 delivery; mutex check moved after `from_dict` but
  attribution not yet source-aware.
- `aa15f98` — D5 U2 ce:review follow-ups; F-04 (gated_auto) added
  source-aware branching.
- ce:review run artifact:
  `.context/compound-engineering/ce-review/20260511-175812-997cfcc3/`
  (api-contract-reviewer.json AC-U2-03; cli-readiness-reviewer.json
  CLR-U2-04; agent-native-reviewer.json AN-U2-03 — 3-way convergence).
