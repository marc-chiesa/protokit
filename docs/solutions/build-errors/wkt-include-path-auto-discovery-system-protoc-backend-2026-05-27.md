---
title: WKT include-path auto-discovery for the system-protoc backend
date: 2026-05-27
category: docs/solutions/build-errors
module: protokit._cli_utils
problem_type: build_error
component: tooling
severity: high
symptoms:
  - "`protoc` exits non-zero with `google/protobuf/descriptor.proto: File not found.` when compiling any input proto that imports a well-known type, despite WKT files being installed on the host"
  - "`pip install protokit` works on macOS (protoxy bundles WKT in-process) but `protokit lint` fails on Debian/Ubuntu against apt-installed protoc"
  - "Binary-release protoc tarballs work; only split-package distributions (apt's `protobuf-compiler`, some Conda packages, certain Homebrew formulae) break"
  - "Tests pass locally but cross-backend byte-equivalence tests fail with `CalledProcessError exit 1` immediately on first CI run"
root_cause: incomplete_setup
resolution_type: code_fix
tags:
  - protoc
  - well-known-types
  - wkt
  - include-path
  - apt-protobuf-compiler
  - debian
  - ubuntu
  - shutil-which
  - functools-cache
  - cross-backend
related_components:
  - tooling
---

# WKT include-path auto-discovery for the system-protoc backend

## Problem

`_compile_with_protoc` shells out to `protoc` to compile `.proto` files into a `FileDescriptorSet`. On systems where the protoc distribution does not add the well-known-type (WKT) directory to protoc's default search path — most notably Debian/Ubuntu's `apt install protobuf-compiler`, which puts protoc at `/usr/bin/protoc` and the WKT `.proto` files at `/usr/include/google/protobuf/*.proto` — any input proto with `import "google/protobuf/any.proto"` (or any other WKT) fails immediately with `File not found.` until the caller manually passes `-I /usr/include` for every invocation.

The protoxy backend (Rust bindings, `pip install protokit[compiler]`) bundles WKT in-process and is unaffected. So a `pip install protokit` install on a host without `[compiler]` is silently more brittle than the same install with `[compiler]` — failing the moment any real-world proto (with timestamps, durations, anys, etc.) hits the protoc fallback.

## Symptoms

- `subprocess.CalledProcessError: Command '['protoc', '--descriptor_set_out', '/tmp/...', '--include_imports', '-I', '/path/to/protos', '...']' returned non-zero exit status 1.` with `google/protobuf/<wkt>.proto: File not found` in `exc.stderr`.
- Affects only the protoc-shell-out backend; protoxy keeps working.
- First-CI-run failures on apt-installed protoc even when local-dev tests are uniformly green.
- The argv looks "correct" — `-I` includes the input parents — but doesn't include the WKT directory because protoc doesn't add `/usr/include` to its default search path on apt installs.

## What Didn't Work

- **Documenting "users must pass `-I /usr/include` themselves"** — punts the problem onto every consumer of the API, defeating the value of an in-process compile helper. Documentation as a fix-shape is the wrong shape when the right answer is for the helper to find the WKT files itself.
- **Pinning a newer protoc binary release on CI** — protoc binary tarballs ship WKT in `<install>/include/` adjacent to the binary, which protoc auto-finds. Pinning v25.3 binary on CI fixed the WKT-resolution failure but introduced descriptor-encoding skew with protoxy 0.7.2's embedded protoc, causing ~10 lint-rule tests to fail with different (but equally real) errors. See [[protoc-version-skew-between-system-and-embedded-breaks-descriptor-tests-2026-05-27]] and [[dont-pin-binary-protoc-when-test-suite-cross-checks-protoxy-2026-05-27]].
- **Adding `-I /usr/include` unconditionally** — works on apt installs but pollutes the include path on systems where `/usr/include` doesn't contain protobuf at all (or contains a different version), risking surprising override behavior if a user has a protoc-version-specific WKT elsewhere.

## Solution

Add a `_discover_wkt_include_paths()` helper that probes a small set of canonical locations, validates each by stat-ing the sentinel file `google/protobuf/descriptor.proto`, and returns only the validated paths. Thread the result into the `protoc -I` argv **after** caller-supplied paths and proto-file parents so explicit user overrides always win.

From `src/protokit/_cli_utils.py:81-146`:

```python
_WKT_SENTINEL = Path("google") / "protobuf" / "descriptor.proto"


@functools.cache
def _discover_wkt_include_paths() -> tuple[str, ...]:
    """Locate well-known-type (WKT) include directories for the protoc backend.

    Different protoc distributions place the WKT ``.proto`` files in
    different locations and do NOT consistently add them to protoc's
    default search path:

    - Protobuf binary releases ship them in ``<install>/include/``
      adjacent to ``<install>/bin/protoc``. protoc auto-finds these.
    - apt-installed ``protobuf-compiler`` on Debian/Ubuntu places them
      at ``/usr/include/google/protobuf/`` but does NOT add
      ``/usr/include`` to protoc's search path.
    - Homebrew installs place them under the brew prefix
      (``/opt/homebrew/include/`` or ``/usr/local/include/``).
    - Conda installs place them under the env's ``include/``.

    Returns a tuple of validated include directories (each one
    contains ``google/protobuf/descriptor.proto``) in priority order:
    the directory adjacent to the resolved ``protoc`` binary first,
    then ``/usr/include`` and ``/usr/local/include`` as system
    fallbacks. The result is cached for the process lifetime since
    discovery involves filesystem stats and the answer is stable
    across calls.
    """
    candidates: list[Path] = []
    protoc_path = shutil.which("protoc")
    if protoc_path is not None:
        protoc_install_include = Path(protoc_path).resolve().parent.parent / "include"
        candidates.append(protoc_install_include)
    candidates.append(Path("/usr/include"))
    candidates.append(Path("/usr/local/include"))

    validated: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        try:
            resolved = str(candidate.resolve())
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        if (candidate / _WKT_SENTINEL).is_file():
            validated.append(str(candidate))
    return tuple(validated)
```

Caller integration in `_compile_with_protoc` (`src/protokit/_cli_utils.py:478-489`):

```python
parents = list(dict.fromkeys(str(p.parent) for p in proto_paths_in))
# Auto-discovered WKT paths come LAST so caller-supplied paths and
# proto-file parents always take precedence. Users who do not
# import any WKT see no behavioral change; users importing
# google/protobuf/* on systems with split-package protoc installs
# (apt's protobuf-compiler is the canonical example) no longer
# need to pass -I /usr/include themselves.
wkt_includes = [
    p for p in _discover_wkt_include_paths()
    if p not in include_paths and p not in parents
]
includes = [*include_paths, *parents, *wkt_includes]
```

## Why This Works

Three load-bearing properties:

1. **Sentinel-file validation** — `google/protobuf/descriptor.proto` is the most fundamental WKT and ships with every protoc distribution. Stat-ing it (rather than just listing the candidate directory) gives necessary-and-sufficient evidence the directory actually contains protobuf includes, not just a same-named empty directory.
2. **Argv ordering** — auto-discovered paths come **after** caller `include_paths` and proto-file parents in the argv. protoc resolves imports against the FIRST matching `-I` directory, so caller overrides always win. Users who have a project-specific WKT version (rare but real for vendored protobuf trees) get exactly what they asked for.
3. **Dedup against the explicit caller set** — prevents `-I /usr/include -I /usr/include` when the caller has already passed the same path. Keeps the argv minimal and avoids any chance of duplicate-include warnings from protoc.

The `@functools.cache` decorator is also load-bearing for performance: discovery involves three `Path.resolve()` calls + three `Path.is_file()` calls per process, all of which are stable across calls. Caching once per process means the cost is paid at first compile, not at every lint invocation.

## Prevention

- **Audit every shell-out to an external compiler** for the same class of issue: does the host distribution add the compiler's WKT/standard-library to its default search path? If not, auto-discover.
- **Validate candidate paths with a sentinel-file stat**, not just directory existence. A directory named `include/` that doesn't actually contain the expected protos shouldn't be added to `-I`.
- **Cache discovery results** with `@functools.cache` (or equivalent in non-Python ecosystems) — the answer is stable across calls within a process.
- **Place auto-discovered paths AFTER caller-supplied paths** in the argv so explicit user overrides always win. Auto-discovery is a fallback, not a primary configuration.
- **Test the helper in isolation** with a fake filesystem (see `tests/test_cli_utils.py::TestWktIncludePathDiscovery` for the 4-test pattern: empty-no-WKT, populated-include, argv-ordering, no-duplicate-entry). Cross-backend integration tests are the higher-level validation but don't catch unit-level regressions in the helper itself.

## Related

- [[matcher-backend-path-resolution-skew-silently-empties-output-2026-05-02]] — sibling pattern: protoxy and protoc both don't `realpath` include paths, so symlinked include directories silently produce empty descriptor output. Same family of "system-protoc surprises us" failure modes.
- [[pureposixpath-for-proto-descriptor-file-stem-2026-05-12]] — already cites the matcher-backend doc as foundational; same `-I` mental model.
- [[dont-pin-binary-protoc-when-test-suite-cross-checks-protoxy-2026-05-27]] — the operational counterpart: when test suite cross-validates backends, the WKT auto-discovery helper makes apt's split-package layout viable so CI can stay on protoc-3.21 (matching protoxy's embedded version) without manual `-I /usr/include`.
- [[protoc-25-rejects-end-of-options-separator-2026-05-27]] — sibling protoc cross-version-compatibility learning.
- [[first-public-push-plan-for-ci-iteration-debugging-2026-05-27]] — the meta-learning that surfaced this whole cluster.
- Canonical commit: `469af3d` ("fix: WKT include-path auto-discovery for system-protoc backend (0.7.1)").
