# Contributing to protokit

## Setup

Install the project in editable mode with the development extras:

```sh
pip install -e ".[dev,compiler]"
```

## Running tests

The full test suite runs under `pytest`:

```sh
.venv/bin/pytest
```

## Tests that require `buf`

A small subset of tests verify parity with `buf v1.69.0`:

- `tests/parity/` — the multi-rule parity harness (gated by
  `@pytest.mark.parity`; opt in with `pytest -m parity`).
- `tests/schema/lint/test_buf_smoke_assumptions.py` — the D6b U4 buf
  smoke regression gate: re-invokes `buf lint --error-format=json`
  against the 22 fixtures under
  `tests/schema/lint/rules/fixtures/package_same/_buf_smoke/` and
  asserts byte-equality with the committed `recorded/*.json`
  snapshots. Skipped when `BUF_BINARY` is unset and `buf` is not on
  PATH.

To run these, install buf v1.69.0:

**Preferred (macOS — currently bottled at v1.69.0; brew handles signing
+ integrity):**

```sh
brew install buf
```

**Manual install (when brew is unavailable):** download the
platform-specific tarball from
<https://github.com/bufbuild/buf/releases/tag/v1.69.0>, **verify the
SHA-256 against the published `sha256.txt` at
<https://github.com/bufbuild/buf/releases/download/v1.69.0/sha256.txt>
BEFORE extracting**, then place the binary on PATH or:

```sh
export BUF_BINARY=/path/to/buf
```

The discovery contract lives in `tests/_buf_helpers.py:discover_buf_binary`
(shared between the parity harness + the U4 smoke test): `BUF_BINARY`
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
