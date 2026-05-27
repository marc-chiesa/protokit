---
title: protoc 25+ rejects the `--` end-of-options separator
date: 2026-05-27
category: docs/solutions/build-errors
module: protokit._cli_utils
problem_type: build_error
component: tooling
severity: medium
symptoms:
  - "protoc exits non-zero with stderr `Unknown flag: --` on protoc v25 and later"
  - "The same argv worked unchanged on protoc 3.21 / 21.x / 22.x / 23.x / 24.x"
  - "Failure surfaces BEFORE any include-path resolution or parse, so WKT auto-discovery and `-I` paths look correct but compile still fails"
  - "Sanity-step output shows `Unknown flag: --` immediately when a minimal WKT-importing proto is compiled inline"
root_cause: wrong_api
resolution_type: code_fix
tags:
  - protoc
  - argv
  - end-of-options
  - cross-version-compatibility
  - cli-flags
  - separator
  - posix-convention
related_components:
  - tooling
---

# protoc 25+ rejects the `--` end-of-options separator

## Problem

The standard Unix convention is that `--` on a command line terminates flag parsing: every token after it is treated as a positional argument, even if it starts with `-`. `_compile_with_protoc` originally appended `--` between the flag block and the input proto paths as a hardening measure against the rare case of a `.proto` path beginning with `--`. This worked on every protoc version through 24.x.

protoc 25+ removed support for the separator. It now fails with `Unknown flag: --` BEFORE doing any include-path resolution, parse, or descriptor generation. The failure looked maddeningly unrelated to a project debugging WKT resolution: the auto-discovery code was correctly threading `/usr/local/include` into the argv, but protoc was exiting non-zero before it could even read the include flags.

## Symptoms

- `subprocess.CalledProcessError: Command '['protoc', ..., '--', '/path/to/file.proto']' returned non-zero exit status 1.`
- `exc.stderr` (when captured) contains literally `Unknown flag: --` and nothing else useful.
- pytest renders the failure as `assert 0 == 1` because the test's stderr-extraction layer doesn't surface `exc.stderr` in the assertion message.
- The argv that worked on protoc 24.x — exactly the same bytes — now fails on protoc 25+.
- Affects every invocation; not data-dependent.

## What Didn't Work

- **Adding `-I /usr/local/include` more aggressively** — initial assumption was that WKT resolution was still broken even after the auto-discovery helper landed. The auto-discovery WAS working (the path appeared in the argv), but protoc was failing before reaching include-path resolution.
- **Adding a CI sanity step that compiles a WKT-importing proto inline** — this was the right diagnostic (it's what surfaced `Unknown flag: --` with visible stderr in the CI logs), but it's a diagnostic, not a fix. The fix is to drop the `--` separator.
- **Gating on `protoc --version` output to decide whether to emit the separator** — adds parsing complexity (matching `libprotoc 3.21.x` vs `libprotoc 25.3` vs whatever protoc 26 will print), breaks the moment protoc reintroduces support for `--` (unlikely but worth considering), and creates a maintenance burden across protoc release cycles. The simpler "drop it unconditionally" fix has tiny blast radius.

## Solution

Remove the `--` separator from the protoc argv builder. Pass file paths positionally after the flag block.

From `src/protokit/_cli_utils.py:494-516`:

```python
cmd = ["protoc", "--descriptor_set_out", str(tmp_path), "--include_imports"]
if include_source_info:
    cmd.append("--include_source_info")
for inc in includes:
    cmd.extend(["-I", inc])
# NOTE: protoc 25+ rejects the standard ``--`` end-of-options
# separator with ``Unknown flag: --``. The separator was a
# hardening measure for input paths starting with ``--`` (a
# rare-but-real foot-gun) and was accepted by earlier protoc
# versions. The blast radius of dropping it is tiny — a proto
# path beginning with ``--`` would be misinterpreted as a flag
# — and the alternative (gating on protoc version) adds
# complexity for marginal benefit. Users with such paths can
# rename or pass an absolute path containing ``./``.
for p in proto_paths_in:
    cmd.append(str(p))
```

For paths that genuinely begin with `--` (rare in practice), two workarounds exist without the separator:

- Pass the path with an explicit `./` prefix: `./--weird.proto` doesn't look like a flag to protoc's parser.
- Use absolute paths: `/abs/path/--weird.proto` is always interpreted positionally.

Both work across all protoc versions.

## Why This Works

Newer protoc versions consider `--` itself an unknown flag and exit before parsing any subsequent arguments. Earlier versions accepted it silently as a standard POSIX end-of-options marker. By dropping the token from the argv, the command builds without any token protoc considers a flag — every non-flag token is a positional input path, parsed by protoc as such.

The fix is unconditional (not version-gated) because:

- The blast radius of dropping the separator is small in practice: proto paths beginning with `--` are rare-to-nonexistent. Users with such paths can rename or prefix with `./`.
- The blast radius of leaving the separator in is large in practice: every install on a host with protoc 25+ breaks immediately on the first compile.
- Version-gating logic adds maintenance cost across protoc releases without solving a real user problem.

## Prevention

- **Audit argv-builders against the current major version of every upstream CLI tool you shell out to.** Pinned binary releases give you control; system-installed binaries vary by host distribution.
- **Surface subprocess stderr in test failures.** A test that uses `subprocess.run(..., check=True, capture_output=True)` captures stderr into `exc.stderr` but doesn't surface it in the default `CalledProcessError` repr. Either re-raise with stderr in the message, or add a CI sanity step that exercises the critical path with stderr visible (see [[first-public-push-plan-for-ci-iteration-debugging-2026-05-27]]).
- **Treat defensive hardening flags as opt-in audit candidates.** Flags added "just in case" tend to become active bugs when upstream removes them. Track the reason each defensive flag exists; when the originating concern is no longer load-bearing, remove the flag.
- **Prefer "drop the flag" over "gate the flag on version" when an upstream removes a previously-standard feature.** Version-gating is correct in principle but expensive in practice — each new upstream release is another version branch to maintain.

## Related

- [[wkt-include-path-auto-discovery-system-protoc-backend-2026-05-27]] — the WKT fix landed first; this separator fix is the second protoc-cross-version concern surfaced by the same CI iteration.
- [[matcher-backend-path-resolution-skew-silently-empties-output-2026-05-02]] — sibling protoc-quirk learning: protoxy and protoc both don't resolve symlinks in `-I` paths.
- [[subprocess-exit-code-validation-test-harness-2026-05-13]] — same "shelling out to an external binary; must validate behavior across versions" mental class.
- [[first-public-push-plan-for-ci-iteration-debugging-2026-05-27]] — the meta-learning. The CI sanity step pattern added in `e0bcd25` is what surfaced `Unknown flag: --` with visible stderr instead of `assert 0 == 1`.
- Canonical commit: `b857e45` ("fix: drop protoc `--` end-of-options separator (rejected by protoc 25+)").
