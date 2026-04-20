# Vendored SARIF 2.1.0 JSON Schema

**File:** `sarif-2.1.0.json`
**Source:** https://json.schemastore.org/sarif-2.1.0.json
**Original `$id`:** https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json
**Vendored on:** 2026-04-19
**License:** OASIS standard (publicly published)

OASIS Static Analysis Results Interchange Format (SARIF) 2.1.0 — the
format consumed by GitHub Code Scanning, GitLab security dashboards,
and many static analysis tools.

protokit's `sarif` formatters for the COMPAT, COMPAT_HISTORY, and
COMPAT_BISECT kinds target this schema. Test validation uses the
`jsonschema` library (Draft 7) against this vendored copy.

## Vendoring policy — vendored snapshot vs. emitted `$schema`

SARIF output from protokit carries a `$schema` property pointing at
the live schemastore.org URL (see
`SARIF_SCHEMA_URL` in `src/protokit/formatters/_sarif_json.py`).
That's what downstream consumers resolve when they validate the
document in place. Our tests, however, validate against the
**vendored** snapshot here — a pinned-in-time copy.

These two schemas **can drift**. The live schemastore.org copy is
occasionally updated (new optional fields, tightened patterns);
the vendored copy only changes when someone refreshes this file.
The intended policy:

1. **Test-time**: always validate against the vendored snapshot.
   Tests are deterministic regardless of schemastore.org
   availability.
2. **Air-gapped CI**: consumers that resolve `$schema` may fail to
   fetch it. They either vendor their own schema or skip
   `$schema`-directed validation. This is their problem, not
   protokit's — but it's worth knowing.
3. **Refreshing this file**: when SARIF 2.2 lands or schemastore
   updates 2.1.0, fetch the new copy (see the curl command this
   file was produced from), bump the `Vendored on` date, and run
   the SARIF test suite. Failures signal either a real
   incompatibility in our emission code or a tightening of the
   schema we need to accommodate.
