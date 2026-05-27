---
title: "Matcher-vs-backend path resolution skew silently empties root_files on symlinked workspaces"
date: 2026-05-02
last_updated: 2026-05-27
category: docs/solutions/logic-errors
module: protokit/_cli_utils
problem_type: logic_error
component: tooling
symptoms:
  - "CompileResult.root_files is empty even when caller passed non-empty paths"
  - "No diagnostics emitted — compile reports clean success"
  - "Downstream lint engine silently lints nothing (zero findings, zero error)"
  - "Reproduces on macOS, Bazel bazel-out, container bind-mounts; passes on Ubuntu CI without symlinks"
  - "Unit tests using `tmp_path` pass; production checkouts under symlinked paths fail silently"
root_cause: wrong_api
resolution_type: code_fix
severity: high
tags:
  - path-resolution
  - symlink
  - matcher-skew
  - descriptor-pool
  - protobuf
  - protoxy
  - protoc
  - silent-failure
  - protoc-distribution-quirks
---

# Matcher-vs-backend path resolution skew silently empties `root_files` on symlinked workspaces

## Problem

`compile_protos_to_result(paths, proto_paths)` returns a `CompileResult` whose `root_files` tuple should contain the `fd.name` strings emitted by the protobuf backend (`protoxy` or `protoc`) for each user-passed root path. The lint engine iterates `root_files` to know which files to lint; transitive imports stay in the descriptor pool but are excluded from `root_files`.

The matcher that computes "which `fd.name` strings correspond to user-passed inputs" lives in `_resolve_expected_name` (`src/protokit/_cli_utils.py`). The original implementation called `Path(p).resolve()` on each input AND `Path(inc).resolve()` on each include directory, then computed `relative_to` against the resolved forms. The intent was reasonable: canonicalize paths so the matcher works regardless of how the caller spelled them.

The bug: protobuf backends do NOT resolve symlinks. They take the LITERAL include strings the caller passed and emit `fd.name` as the input path string-relative-to-include against the LITERAL include directory. When the literal path and the resolved path differ — which happens on macOS (`/var` → `/private/var`), Bazel `bazel-out` symlinks, container bind-mounts, project workspaces under `~/work` symlinked elsewhere — the matcher's `expected_set` and the backend's `emitted` set don't intersect. Result: `root_files = ()` even though compilation succeeded and the pool is fully populated.

**The failure is silent.** No diagnostic is emitted; the function returns `CompileResult(pool=<populated>, root_files=(), diagnostics=())`. A downstream lint engine sees zero roots, lints nothing, reports zero findings, exits 0. Looks healthy. Isn't.

## Symptoms

- A user runs the lint pipeline against a real proto file in a real workspace; pipeline reports zero findings and exits clean.
- Repeat the run after `cd $(pwd -P)` (force resolve symlinks before invocation): suddenly findings surface.
- `tmp_path`-based tests in CI Ubuntu containers pass cleanly; the bug only manifests where `Path(p).resolve() != Path(p)` for some input.
- Verbose tracing shows the descriptor pool is populated correctly — `pool.FindFileByName` for the user's input succeeds — but `result.root_files == ()`.

## What Didn't Work

- **Calling `.resolve()` on both sides of the comparison.** This was the original approach. The thinking: canonicalize both the include directory and the input path, then `relative_to` against canonicalized forms. The flaw: protobuf backends DON'T canonicalize. The matcher and the backend must agree on the resolution policy; canonicalizing the matcher half breaks the agreement.
- **Stripping `.resolve()` from one side only.** Same root cause: any divergence between matcher's resolution and backend's resolution produces the skew. Both sides must use the same policy.
- **Falling back to `p.name` (basename) on `relative_to` ValueError.** Masks the bug. The matcher returns a basename that the backend may also have emitted (basenames often coincide), producing the illusion of correct behavior in some cases and silently wrong behavior in others.

## Solution

Match backends **literally**. Strip `.resolve()` everywhere from the matcher; walk includes in declared order; use literal-string `relative_to`. The matcher and the backend now use the same resolution policy (none).

```python
# src/protokit/_cli_utils.py — fixed shape

def _resolve_expected_name(p: Path, includes: Sequence[str]) -> str:
    """Compute the expected ``fd.name`` for one input proto path.

    Walks ``includes`` in declared order; the first include that is a
    prefix of ``p`` determines the relative form (which is what
    protoxy/protoc emit as ``fd.name``). Falls back to ``p.name`` if
    no include is a prefix (rare; caller convention is to include
    ``p.parent``).

    Path components are matched LITERALLY — neither ``p`` nor the
    includes are passed through ``Path.resolve()``. Both backends
    resolve ``-I`` arguments and input paths against the literal
    string the user passed (no symlink expansion of the include
    against the input). Calling ``.resolve()`` here would diverge
    from the backend on macOS (``/var`` -> ``/private/var``), Bazel
    ``bazel-out`` symlinks, and any container bind-mount where the
    user-passed path does not byte-match the realpath. The skew
    silently empties ``CompileResult.root_files`` for compiles
    that otherwise succeed.
    """
    for inc in includes:
        inc_path = Path(inc)
        try:
            return str(p.relative_to(inc_path))
        except ValueError:
            continue
    return p.name
```

Add a regression test that exercises the symlinked-include path so the invariant is locked:

```python
def test_literal_prefix_no_resolve(self, tmp_path: Path) -> None:
    """Symlinked include should NOT be resolved through to realpath.

    Locks the matcher's literal-prefix semantics so it agrees with the
    backends, which pass include directories to protoxy/protoc verbatim.
    A regression that re-introduces ``.resolve()`` would break this test.
    """
    real = tmp_path / "real"
    real.mkdir()
    (real / "file.proto").write_text("syntax = \"proto3\";")
    link = tmp_path / "link"
    link.symlink_to(real)

    # Pass the symlinked include path; expect fd.name to be relative
    # to the LITERAL include (not the resolved realpath).
    result = _cli_utils._resolve_expected_name(
        link / "file.proto", [str(link)],
    )
    assert result == "file.proto"
```

## Why This Works

The protobuf backends (both `protoxy` 0.7+ and `protoc` 3.21+) use a simple algorithm to compute `fd.name`: for each input file, walk the `-I` include directories in declared order, find the first one that is a literal-string prefix of the input file path, and emit `fd.name` as the input path relative to that include directory's literal-string form. Neither backend calls `realpath`/`lstat`/`os.path.realpath` on the include or the input.

If the matcher and the backend use the same algorithm, their results agree by construction. The bug was an asymmetric resolution policy: the matcher canonicalized via `.resolve()`, the backend didn't. Removing `.resolve()` from the matcher restores the symmetry.

The deeper lesson: **the matcher must use the same resolution policy as the source of truth**. Whenever you write code that computes "what string will external tool X emit for input Y?", the matcher and X must agree on every transformation. The asymmetry is invisible in the matcher's source — `.resolve()` looks like good defensive hygiene — and only manifests in environments where the resolution actually changes the path (i.e., where symlinks exist).

## Prevention

1. **When writing a matcher against external-tool output, document the resolution policy explicitly in the matcher's docstring.** A future contributor adding `.resolve()` "for safety" must see the policy contract before they touch the line. The fixed `_resolve_expected_name` docstring names the policy ("matched LITERALLY") and explains the failure mode.

2. **Test with a symlink in the path.** `tmp_path` returns a non-symlinked path on most platforms; a regression test that creates a symlink and passes the symlinked path through the matcher catches the bug class. Add at least one test of this shape for any matcher that consumes paths.

3. **Add a `realpath` mismatch check to the production assertion.** If the matcher and the backend agree, `expected_set` and `emitted` should intersect non-trivially. When they don't, the function returns `root_files = ()` silently. A defensive assertion like `if proto_paths_in and not root_names: warn(...)` would have surfaced the bug. Optional, but cheap insurance against silent failures.

4. **Audit other matchers in the same codebase.** Any code that does `Path(...).resolve()` and compares against an external-tool output is suspect. In this codebase: search for `.resolve()` calls in `src/protokit/`; each one is a candidate for review.

5. **Generalize the rule:** "Matcher and source-of-truth must use identical resolution policies." Applies beyond paths — JSON key ordering, URL canonicalization, hostname matching (`example.com` vs `EXAMPLE.COM`), email normalization (Gmail dots), Unicode NFC/NFD, **enum serialization (`Enum.name` vs `Enum.value`) across sibling output formats**. Any matcher that pre-processes input one way while the source-of-truth processes it another way produces silent mismatches. Two in-codebase instances of this class are documented separately: input-boundary case normalization in `docs/solutions/best-practices/normalize-at-input-boundary-2026-05-07.md` and output-boundary enum-string parity in `docs/solutions/best-practices/cross-format-enum-string-parity-2026-05-08.md`.

## Related Issues

- `docs/solutions/best-practices/pytest-static-analysis-gate-ratchet-2026-05-02.md` — the static-analysis gate that would have caught some `.resolve()`-related type issues but not this logic bug; static analysis can't see across the boundary to "what does the external tool actually do."
- `docs/solutions/test-failures/pytestmark-does-not-guard-module-top-imports-2026-05-02.md` — companion bug from the same review pass; both are "code looks correct AND unit tests pass AND CI passes, but production fails silently" cases. The shared lesson is that `tmp_path` and clean Ubuntu CI hide environment-specific bugs.
- `docs/brainstorms/2026-04-30-protokit-lint-delivery-1-foundation-requirements.md` (F1 false-positive section) — the requirements doc flagged the original `endswith("/" + p.name)` matcher as wrong because of basename collisions, and proposed pre-computing expected `fd.name` via resolution. The proposal landed; the resolution policy was the half that needed more thought.
- `docs/solutions/best-practices/normalize-at-input-boundary-2026-05-07.md` — concrete in-codebase instance of the same transformation-skew class (Prevention #5) applied to a registry lookup: the formatter registry normalized names to lowercase at lookup while CLI comparisons did not, silently suppressing `--statistics` and misfiring the `--quiet` mutex. Same root cause, different transformation (`.lower()` instead of `.resolve()`); same fix shape (normalize at the input boundary so caller and consumer agree).
- `docs/solutions/best-practices/cross-format-enum-string-parity-2026-05-08.md` — second in-codebase instance of the Prevention #5 class, on the output side: `lint_json` emitted `LintSeverity.name` (uppercase `"WARNING"`) while `lint_sarif` mapped to lowercase `"warning"`, forcing per-format normalization on downstream agents. Same root cause (two emission sites use different transformations of the same enum value), different transformation (`.name` vs `.value`), same fix shape (every sibling format uses the same canonical string).
- `docs/solutions/best-practices/pureposixpath-for-proto-descriptor-file-stem-2026-05-12.md` — downstream consequence of the `fd.name` POSIX-separator convention this doc established. The lint-rule side of the convention: when reading `fd.name` for basename/stem extraction in a FILE-element rule, use `PurePosixPath` so the read matches the descriptor pool's POSIX-string contract regardless of host OS.
- [[subprocess-exit-code-validation-test-harness-2026-05-13]] — same "silent-green on a broken pipeline" symptom class at a different boundary. This doc covers path-resolution skew between protoc and protoxy producing `root_files = ()`. That doc covers subprocess exit-code skew producing `findings = []` from a crashed external tool. Together they map two distinct mechanisms for the same symptom — a test reports a green run on a pipeline that never produced real output.
- [[cross-file-pin-regex-anchor-structure-not-annotation-token-2026-05-13]] — same axiom ("matcher and source-of-truth must use identical resolution policies") applied to regex-pattern design instead of path resolution. When a regex's specificity exceeds the contract it's meant to enforce (anchoring on a Python type annotation when only the value matters), every future legal refactor of the over-specified token silently breaks consumers. Same root cause family at a different layer: this doc covers backend resolution skew; that doc covers regex-anchor skew across multi-consumer source parsing.
- [[capture-setup-without-dispatch-false-test-confidence-2026-05-17]] — third member of the "silent-green" symptom family at a different boundary. This doc covers path-resolution skew producing `root_files = ()`; `subprocess-exit-code-validation-test-harness` covers exit-code skew producing `findings = []`; the capture-setup learning covers dispatch-walk skip producing `captured = []`. All three are test-author traps where infrastructure is set up correctly but the observed signal is silently missing.

## Sibling protoc/protoxy backend-quirk learnings (added 2026-05-27)

This doc was the foundational entry in what has since become a cluster of related learnings about how protoc and protoxy backends disagree in small-but-load-bearing ways. The 0.7.1 hotfix series added three more siblings; the full cluster (tagged `protoc-distribution-quirks` for discoverability) now covers:

- **[[wkt-include-path-auto-discovery-system-protoc-backend-2026-05-27]]** — system-protoc distributions disagree on whether the WKT include directory is on protoc's default search path. apt's `protobuf-compiler` puts WKTs at `/usr/include/google/protobuf/` but does not add `/usr/include` to protoc's search path; protoxy bundles WKTs in-process. Auto-discovery helper that probes `<protoc-install>/include`, `/usr/include`, `/usr/local/include` makes apt's split-package layout work.
- **[[protoc-25-rejects-end-of-options-separator-2026-05-27]]** — protoc 25+ rejects the standard `--` end-of-options separator with `Unknown flag: --`. Earlier versions accepted it as a POSIX-standard hardening measure. Cross-version protoc compatibility for any code shelling out to protoc.
- **protoc-version-skew-between-system-and-embedded-breaks-descriptor-tests-2026-05-27** — when test suites cross-validate between an in-process backend (protoxy) and a system binary backend (protoc), the protoc versions must be kept in lockstep. Bumping one out-of-sync introduces descriptor-encoding differences (proto2 `required` handling, enum `allow_alias` permissiveness, mixed-case enum value rejection, control-char tolerance, `Location.span` encoding) that break ~10 lint-rule tests in this codebase.
- **[[source-code-info-semantic-not-byte-equivalence-across-protoc-backends-2026-05-27]]** — the second-line defense for the one cross-backend test that genuinely needs to tolerate version-encoding skew. Replace `SerializeToString()` byte-equivalence with semantic equivalence on the `(path → comments)` mapping the consumer actually uses.

The shared axiom from this doc — **the matcher and the source-of-truth must use identical resolution policies** — generalizes across the cluster: WKT search paths must match between the helper and protoc (Learning #1), argv separator semantics must match between the builder and the protoc version (Learning #2), descriptor encoding must match between cross-validated backends (Learning #3), and the parity test must assert at the granularity production code actually consumes (Learning #4 / the inverse-loosening case at [[parity-gate-must-assert-at-design-claim-granularity-2026-05-22]]).

The unifying tag `protoc-distribution-quirks` is added to this doc's frontmatter so future ce-compound-refresh runs and ce-learnings-researcher queries can find the whole cluster from any entry point.
