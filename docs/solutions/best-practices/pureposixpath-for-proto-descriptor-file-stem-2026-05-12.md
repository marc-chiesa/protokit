---
title: "Use PurePosixPath for proto descriptor file-stem extraction; multi-dot basenames fire on the inner dot"
date: 2026-05-12
category: best-practices
module: protokit.schema.lint.rules.naming
problem_type: best_practice
component: tooling
severity: medium
applies_when:
  - "Writing FILE-element lint rules that inspect the proto file basename or extension"
  - "Extracting a file stem or extension from a FileDescriptor's name field"
  - "Advising users whose proto file-naming convention encodes version info as dots in the basename"
tags:
  - pureposixpath
  - pathlib
  - protobuf-descriptor
  - file-element-rules
  - file-naming
  - cross-platform
  - buf-parity
  - naming
---

# Use PurePosixPath for proto descriptor file-stem extraction; multi-dot basenames fire on the inner dot

## Context

`check_snake_case_files` (buf parity: `FILE_LOWER_SNAKE_CASE`) — and any future `ElementKind.FILE` rule that inspects the proto file's basename — must extract the stem of a `.proto` filename from the descriptor pool's `fd.name` field. Two non-obvious behaviors govern the extraction:

1. **The descriptor pool stores `fd.name` with POSIX separators by protobuf convention**, regardless of host OS. The convention was established empirically and documented in [[matcher-backend-path-resolution-skew-silently-empties-output-2026-05-02]] — both backends (protoxy and protoc) compute `fd.name` by walking `-I` include directories and emitting the input path relative to that directory's literal-string form, using forward slashes. Neither backend calls `realpath`, so `fd.name` is a pure POSIX string regardless of the input path's representation on the host filesystem.
2. **Multi-dot filenames like `acme.v1.proto` produce stems with inner dots** (`acme.v1`) under any `Path.stem` flavor, since `stem` strips only the final extension. The inner dot is not in the snake_case regex's character class, so the rule fires on the stem — intentional and matching buf's FILE_LOWER_SNAKE_CASE behavior.

Neither behavior is documented in the protobuf Python API surface. The D6a plan for U3 specified the rule's intent ("file basename only, ignore directory path; `Foo_Bar.proto` fires, `foo_bar.proto` is clean") but left the extraction mechanism as an implementation choice. (Prior-session search confirmed no predecessor: no prior plan or brainstorm in the session history addressed file-basename extraction from protobuf descriptors — session history.)

## Guidance

**Use `PurePosixPath` from the standard library for proto file-stem extraction.** Not `Path`, not `os.path.splitext` — the descriptor pool stores POSIX-separated strings, and `PurePosixPath` is purely lexical (no filesystem touch, no host-OS conditional behavior):

```python
from pathlib import PurePosixPath

def check_snake_case_files(ctx: FileLintContext) -> None:
    stem = PurePosixPath(ctx.file.name).stem
    if not _SNAKE_CASE_RE.match(stem):
        ctx.emit(
            violation_kind="naming/snake-case-files",
            params={"name": stem},
        )
```

**Document the multi-dot stripping behavior in the rule's docstring** so future readers understand why `acme.v1.proto` fires on the stem `acme.v1`:

```python
def check_snake_case_files(ctx: FileLintContext) -> None:
    """Fire on .proto file basenames that don't match snake_case.

    ... [main behavior description] ...

    Multi-dot filenames (e.g., ``acme.v1.proto``) resolve to a stem
    containing the inner dot (``acme.v1``) because ``PurePosixPath``
    strips only the final extension. The dot is not in the
    ``_SNAKE_CASE_RE`` character class, so such filenames fire. This
    matches buf's FILE_LOWER_SNAKE_CASE behavior: a ``.proto`` file
    is expected to have a single dot before its extension. Users
    encoding version segments in the filename should put them in
    the directory path (e.g., ``acme/v1/users.proto``) rather than
    the basename.
    """
```

## Why This Matters

**Cross-platform correctness.** The descriptor pool records file names with POSIX separators even on Windows or macOS. A rule using `pathlib.Path` on Windows could misinterpret a path with backslashes (none exist in `fd.name`, but the conceptual hazard remains: `Path` is host-OS-aware, which is the wrong contract for a lexical lookup against a known-POSIX string). `PurePosixPath` is unconditionally correct because it is unconditionally POSIX — its behavior does not depend on `sys.platform`. Using it makes the rule deterministic across CI matrix cells (linux/macOS/Windows × multiple Python versions).

**Multi-dot filename behavior is buf-parity.** Encoding API version segments as dots in the basename (`api.v1.proto`, `service.v2alpha.proto`) is an anti-pattern that buf actively flags via FILE_LOWER_SNAKE_CASE — the canonical form puts version segments in the directory path. The fact that `PurePosixPath.stem` leaves inner dots in the stem is not a bug to work around; it is the property that makes the rule fire on the anti-pattern. Stripping all extensions (`.partition(".")`) would *suppress* the buf-parity finding rather than surface it.

**`os.path.splitext` is the wrong tool.** `os.path.splitext` works on POSIX strings, but it adds a *runtime* dependency on `os` for a purely lexical operation, and it returns a 2-tuple that callers must destructure. `PurePosixPath.stem` is a property: cleaner read, no destructure, no `os` import in a lint-rules module. The lint module is import-cold (the cold-import test asserts `protokit.schema.lint.*` does not import heavy modules at startup), so any avoided import compounds.

## When to Apply

- **Any `ElementKind.FILE` rule** that needs the file's basename, extension, or stem — always use `PurePosixPath(ctx.file.name)`.
- **Any descriptor-walking code** that operates on `fd.name` strings outside of the lint rules (e.g., engine instrumentation, custom formatters) where path-segment handling matters.
- **When advising users on proto repository structure** (e.g., in README copy or rule docstrings), point to directory-encoded version segments as the canonical form; the `naming/snake-case-files` rule will surface dot-encoded version anti-patterns.

The discipline does not apply when:
- The code path is processing host-filesystem paths *before* the file enters the descriptor pool (e.g., reading `.proto` files from disk via `--include` arguments). In that case, `Path` is correct because the path is host-OS-specific.
- The code path is converting *from* a descriptor file name *to* a host path for I/O. In that case, normalize through `Path(fd.name)` deliberately, knowing the source is POSIX.

## Examples

The rule implementation in `/Users/marc/projects/python_message_differencer/src/protokit/schema/lint/rules/naming.py` (lines 226-275 after the D6a U3 commits):

```python
@lint_rule(
    rule_id="naming/snake-case-files",
    severity=LintSeverity.ERROR,
    profiles=("recommended", "default"),
    element=ElementKind.FILE,
    message_template="File basename {name!r} is not snake_case",
    source_spec="buf:FILE_LOWER_SNAKE_CASE",
)
def check_snake_case_files(ctx: FileLintContext) -> None:
    """Fire on .proto file basenames that don't match snake_case.

    Checks the file's basename only (the directory portion is
    ignored); ``acme/v1/Foo_Bar.proto`` fires on the stem
    ``Foo_Bar``, ``acme/v1/foo_bar.proto`` is clean. Uses
    ``PurePosixPath`` so the rule produces identical results
    regardless of the host platform — proto file names recorded in
    the descriptor pool use POSIX separators by protobuf convention.

    Multi-dot filenames (e.g., ``acme.v1.proto``) resolve to a stem
    containing the inner dot (``acme.v1``) ...
    """
    stem = PurePosixPath(ctx.file.name).stem
    if not _SNAKE_CASE_RE.match(stem):
        ctx.emit(
            violation_kind="naming/snake-case-files",
            params={"name": stem},
        )
```

The verifying tests in `/Users/marc/projects/python_message_differencer/tests/schema/lint/rules/test_naming_extended.py`:

```python
def test_happy_path_snake_case_basename_clean(self, tmp_path):
    report = _run_single(tmp_path, {"foo_bar.proto": _FILE_GOOD_CONTENT},
                         "naming/snake-case-files")
    assert report.findings == ()

def test_directory_path_ignored_basename_only(self, tmp_path):
    """``acme/v1/Foo_Bar.proto`` fires on the stem ``Foo_Bar``."""
    report = _run_single(tmp_path, {"acme/v1/Foo_Bar.proto": _FILE_BAD_CONTENT},
                         "naming/snake-case-files")
    assert {f.params["name"] for f in report.findings} == {"Foo_Bar"}

def test_multi_dot_basename_fires_on_inner_dot(self, tmp_path):
    """``acme.v1.proto`` resolves to stem ``acme.v1`` which fails the regex."""
    report = _run_single(tmp_path, {"acme.v1.proto": _FILE_GOOD_CONTENT},
                         "naming/snake-case-files")
    assert {f.params["name"] for f in report.findings} == {"acme.v1"}
```

## Related

- [[matcher-backend-path-resolution-skew-silently-empties-output-2026-05-02]] — this learning is a downstream consequence of the `fd.name` POSIX-separator convention established there. The earlier doc covers the matcher-side: don't call `realpath` because the descriptor stores literal-string include-path prefixes. This doc covers the lint-rule side: use `PurePosixPath` to read those strings back out portably.
- [[normalize-at-input-boundary-2026-05-07]] — `PurePosixPath` is the normalization boundary on the descriptor-read side. Apply it at the point of extraction; do not pass `fd.name` strings around as `Path` instances downstream.
- [[circular-import-type-checking-cycle-break-2026-05-11]] — `PurePosixPath` lives in the standard library `pathlib` module which is part of the lint module's allowed cold-import surface; this doc validates that the import is justified rather than incidental.
- [[audit-wire-format-before-claiming-sibling-parity-2026-05-03]] — `source_spec="buf:FILE_LOWER_SNAKE_CASE"` is a parity claim; the multi-dot stem behavior is part of buf's wire-format behavior and must be tested to substantiate the parity declaration.
- [[copytoproto-round-trip-for-proto-form-only-descriptor-fields-2026-05-13]] — descriptor-introspection sibling: that doc covers the proto-form-only-field access pattern (`public_dependency`, `weak_dependency`, etc.) via `CopyToProto`; this doc covers POSIX-stem extraction from `fd.name`. Together they map the descriptor-introspection landscape for FILE-element lint rules.
