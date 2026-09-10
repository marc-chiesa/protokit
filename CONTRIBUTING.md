# Contributing to protokit

## Setup

Install the project in editable mode with the development extras:

```sh
pip install -e ".[dev,compiler]"
```

## AI-assisted contributions

Contributions may credit AI tools via `Co-Authored-By:` trailers in
commit messages. You are responsible for correctness and license
compliance of everything you submit, regardless of tooling used.

## Running tests

The full test suite runs under `pytest`:

```sh
.venv/bin/pytest
```

### The pure-Python protobuf backend

CI also runs the full suite under protobuf's pure-Python runtime
(`test-pure-python`, advisory until its known-failure inventory is empty).
Several audit defects only show up there, because they rely on an exception
that only the default upb backend raises. To reproduce locally:

```sh
PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python .venv/bin/pytest tests/ -q -rfE
```

Known pure-Python failures live in `tests/pure_python_expected_failures.txt`,
one node id per line with the audit finding it traces to and the exception it
raises; `tests/_pure_python_inventory.py` applies them as strict,
exception-specific xfails under that backend only. The file's header records
the protobuf version the entries were measured against, and the hook refuses
to apply the inventory on a different `major.minor`. If your venv does not
match, `--pure-python-inventory-ignore-version` lets an exploratory local run
proceed — it is never the verification of record. The inventory is harvested
from the CI cell's own run (its harvest step prints every unlisted failure in
inventory format), not from a local measurement: the cell is Python 3.12 on
Linux with apt `protoc` and `.[compiler,dev]` only, which a developer venv
rarely matches.

## Tests that require `buf`

**Note:** `buf` is a parity-test-only optional dependency; `protokit`
itself has no buf runtime requirement and `pip install protokit` does
not require buf. Parity tests skip cleanly when buf is absent.

A small subset of tests verify parity with the pinned buf version
declared at `_BUF_PARITY_PIN` in `src/protokit/schema/lint/cli.py`:

- `tests/parity/` — the multi-rule parity harness (gated by
  `@pytest.mark.parity`; opt in with `pytest -m parity`).
- `tests/schema/lint/test_buf_smoke_assumptions.py` — the buf smoke
  regression gate: re-invokes `buf lint --error-format=json` against
  the 22 fixtures under
  `tests/schema/lint/rules/fixtures/package_same/_buf_smoke/` and
  asserts byte-equality with the committed `recorded/*.json`
  snapshots. Skipped when `BUF_BINARY` is unset and `buf` is not on
  PATH.

To run these, install buf v1.70.0:

**Preferred (macOS — currently bottled at v1.70.0; brew handles signing
+ integrity):**

```sh
brew install buf
```

**Manual install (when brew is unavailable):** download the
platform-specific tarball from
<https://github.com/bufbuild/buf/releases/tag/v1.70.0>, **verify the
SHA-256 against the published `sha256.txt` at
<https://github.com/bufbuild/buf/releases/download/v1.70.0/sha256.txt>
BEFORE extracting**, then place the binary on PATH or:

```sh
export BUF_BINARY=/path/to/buf
```

The discovery contract lives in `tests/_buf_helpers.py:discover_buf_binary`
(shared between the parity harness and the smoke test): `BUF_BINARY`
env var first, then PATH lookup, otherwise skip the test cleanly.

## Regenerating buf smoke snapshots

When `_BUF_PARITY_PIN` bumps in a future delivery, regenerate the
recorded NDJSON snapshots and SHA-256 checksums:

```sh
cd tests/schema/lint/rules/fixtures/package_same/_buf_smoke
for f in */buf.yaml; do
  dir=$(dirname "$f")
  (cd "$dir" && buf lint --error-format=json . > "../recorded/${dir}.json" || true)
done
cd recorded && shasum -a 256 *.json | sort > CHECKSUMS.sha256
```

Then re-run `BUF_BINARY=$(which buf) pytest tests/schema/lint/test_buf_smoke_assumptions.py`
to confirm byte-equality holds under the new buf version. If
divergence appears, audit each affected snapshot before committing — a
silent change in buf's emit format may require a rule-shape adjustment
documented in `_PARITY_EXCEPTIONS`.
