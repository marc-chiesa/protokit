---
title: "Atomic CLI file publish: sibling temp + umask-honoring mode + os.replace for all-or-nothing output"
date: 2026-06-10
category: docs/solutions/design-patterns
module: protokit.storage.cli
problem_type: design_pattern
component: tooling
severity: medium
applies_when:
  - "A CLI command writes a user-visible output file that must never be left in a partially-written state on failure or interruption"
  - "A pre-existing file at the output path must survive any fault and be replaced only by a complete result"
  - "The published file must carry normal umask-honoring permissions, not the 0600 that mkstemp creates"
  - "Concurrent invocations may target the same output path (last completed publish must win without corruption)"
  - "The write is delegated to a library sink that manages its own file handle, so the caller cannot control every byte"
tags:
  - atomic-write
  - file-publish
  - os-replace
  - mkstemp
  - umask
  - sibling-temp
  - cli-output
  - partial-file-guard
---

# Atomic CLI file publish: sibling temp + umask-honoring mode + os.replace for all-or-nothing output

## Context

CLI tools that produce output files carry an implicit contract that users
rarely articulate until it breaks: either the file at the output path is
complete and correct, or nothing happened. A partially written file is worse
than no file — a partial Parquet can have valid magic bytes and a header,
pass an existence check, and only surface its truncated footer at read time.

When protokit gained `scan --format parquet -o OUT` (PR #26, issue #24), no
existing learning covered atomic file publish, and an existing learning's
incomplete description of the library's partial-file disposal produced
conflicting research during planning — ground truth had to be re-established
by reading `src/protokit/storage/_columnar.py` directly (the library's
`BaseException` close-and-unlink covers mid-write faults, not just pre-open
handler failures). During review, three independent reviewers converged on a
missing defensive `Exception` arm, and an adversarial pass caught that `-o`
pointing at the input file would silently destroy the source, since a
successful publish replaces the output path. This learning documents the full
pattern so future file-writing commands reach the same design without
re-deriving every piece.

## Guidance

The pattern has five interlocking pieces. The reference implementation is
`_write_parquet` in `src/protokit/storage/cli.py`.

### 1. Sibling temp, not system temp

```python
fd, temp = tempfile.mkstemp(
    dir=output.parent,          # same filesystem as the output
    prefix=f".{output.name}.",  # dot-prefix keeps *.parquet globs off it
    suffix=".partial",
)
os.close(fd)
```

`os.replace` is atomic only within one filesystem — a temp in `$TMPDIR`
raises `EXDEV` on a cross-mount rename, so the temp must be a sibling of the
output. `mkstemp` randomness makes the name unique per process, so concurrent
runs to the same output cannot corrupt each other's in-flight temp (last
completed rename wins). The dot-prefix plus `.partial` suffix keep
`*.parquet`-style globs from matching the temp during the write window.

### 2. Restore the mode mkstemp strips

```python
umask = os.umask(0)
os.umask(umask)               # read the umask without destroying it
try:
    os.chmod(temp, 0o666 & ~umask)
    os.replace(temp, output)
except OSError as exc:
    error_exit(f"failed to publish {output}: {exc}")
```

`mkstemp` deliberately creates the temp at mode `0600`, and `os.replace`
preserves the *temp's* mode — so without the chmod, the published file
silently locks out group/world readers that a plain `open()` would have
allowed. No error is raised; the gap surfaces only when an unrelated process
(a cron job, another user in a shared data directory) hits a permission
error. Pin it with a test that compares the published file's mode against a
sibling created normally in the same test — the right oracle regardless of
the environment's umask:

```python
sibling.write_text("x")
assert stat.S_IMODE(out.stat().st_mode) == stat.S_IMODE(sibling.stat().st_mode)
```

### 3. Atomic visibility, not durability

`os.replace` makes the output path transition from absent (or the previous
complete file) to the new complete file in one operation — no reader ever
observes a half-written file. It is not a durability guarantee: without an
fsync, a power loss in the rename window can lose the publish. For a CLI
export that trade-off is right; record it as a code comment so it reads as a
decision, not an omission. Same for symlinks: `os.replace` replaces a
symlinked output rather than writing through it.

### 4. Split the cleanup ownership

When a library sink produces the file (here `to_parquet` in
`src/protokit/storage/_columnar.py`), let it own in-write disposition — it
closes and unconditionally unlinks the file *it* created on any
`BaseException`, including Ctrl-C. The CLI wrapper owns only the rename
window:

```python
temp_pending: str | None = temp
try:
    rows = to_parquet(source, registry, temp, ...)
    # chmod + os.replace (see above)
    temp_pending = None   # published: the temp IS the output now
    return rows
finally:
    if temp_pending is not None:
        with contextlib.suppress(OSError):
            os.unlink(temp_pending)
```

The `finally` unlink is best-effort (`suppress(OSError)`) because on library
fault paths the temp is already gone. Clearing `temp_pending` after a
successful rename keeps the `finally` from unlinking the now-live output.
Net result: the output path never holds a partial file, and a pre-existing
output survives every fault path.

### 5. Error taxonomy at the wrapper

```python
except IncompleteScanError as exc:
    error_exit(...)            # reword the domain error for CLI users
except _TYPED_CLI_ERRORS as exc:
    error_exit(str(exc))       # typed taxonomy passes through
except OSError as exc:
    # Neutral attribution: this clause sees both write-side faults (the
    # temp) and read-side faults the producer re-raises (EIO on the input).
    error_exit(f"I/O error during Parquet conversion ({data_file} -> {output}): {exc}")
except Exception as exc:       # defensive: outside the taxonomy
    # A library regression (RuntimeError, ImportError past a find_spec
    # probe) must still honor the documented 0/2 exit contract.
    error_exit(f"failed to convert records to Parquet: {exc}")
# BaseException is NOT caught: Ctrl-C must propagate (the finally still
# cleans the temp; Click's Abort owns the exit code).
```

Two companion guards close hazards that are easy to miss in review:
reject `-o` resolving to any *input* path up front (a successful publish
would otherwise atomically replace the just-read source with the output),
and probe optional dependencies before any I/O so the not-installed error
fires before work begins.

## Why This Matters

Without atomic publish, any fault between the first and last written byte
leaves a partial file at the output path — for structured binary formats,
invisible corruption that downstream readers discover late. Without the mode
fix, the code looks correct and the file is complete, yet group/world
consumers cannot read it. Without the ownership split, the wrapper either
double-manages cleanup (racing the library) or assumes the library handles a
window it does not own — the rename window is always the caller's. And
without the defensive `Exception` arm, a dependency regression converts a
documented exit-2 error into an exit-1 traceback, breaking scripted callers
that branch on exit codes.

## When to Apply

- The output is a structured binary format (Parquet, Arrow IPC, SQLite, a
  serialized descriptor set) where a partial file is silently malformed
  rather than visibly truncated.
- The output path may already exist and must be overwritten only by a
  complete result.
- The write is delegated to a library managing its own handle, so a single
  `with open(...)` cannot bracket the whole write.
- The command documents an exit-code contract that uncaught exceptions would
  violate.

Do not apply for stdout streaming (no seekable destination — a different
format problem) or for self-describing text output where truncation is
obvious to readers.

## Examples

The four fault-path tests in `tests/storage/cli/test_parquet_output.py` make
"no temp left behind" a first-class contract check via a shared helper
(`directory.glob(".*.partial")`):

```python
# Pre-existing output survives a fault:
out.write_bytes(b"precious previous output")
result = _run(runner, pq_cmd(data, desc, out))
assert result.exit_code == 2
assert out.read_bytes() == b"precious previous output"
assert _no_partial_left(tmp_path)

# Rename-window failure exits 2 and cleans the temp:
monkeypatch.setattr("protokit.storage.cli.os.replace", deny_replace)
...
assert "failed to publish" in result.stderr
assert not out.exists() and _no_partial_left(tmp_path)

# Out-of-taxonomy library error still honors the exit contract:
monkeypatch.setattr("protokit.storage.cli.to_parquet", boom)  # RuntimeError
...
assert result.exit_code == 2 and _no_partial_left(tmp_path)
```

## Related

- `docs/solutions/design-patterns/proto-to-arrow-faithful-mapping-presence-structure-arrow-native-values.md`
  — the library sink's side of the partial-file contract (a recursion
  pre-flight that rejects before ptars, handler-build fail-loud before output,
  AND mid-write `BaseException` close+unlink — three layers); this doc covers
  the CLI publish step above them.
- `docs/solutions/design-patterns/tolerant-iteration-error-taxonomy-narrow-catch-loud-completion-guard-2026-05-30.md`
  — the engine-layer taxonomy (narrow typed catches, `BaseException` always
  propagates) that the wrapper's except-chain extends to the CLI boundary.
- `docs/solutions/design-patterns/generator-source-framing-fault-exhausts-tolerant-recovery-2026-05-30.md`
  — producer-side fault behavior that motivates the all-or-nothing contract.
- `docs/solutions/tooling-decisions/ptars-over-protarrow-proto-to-arrow-isolated-descriptor-pools.md`
  — why the library sink this CLI wraps exists at all.
- Issue #24 (feature), PR #26 (this implementation), PR #17 (the library
  sink establishing the in-write cleanup layer).
