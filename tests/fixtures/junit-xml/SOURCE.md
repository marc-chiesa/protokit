# Vendored JUnit XML Schema

**File:** `JUnit.xsd`
**Source:** https://raw.githubusercontent.com/windyroad/JUnit-Schema/master/JUnit.xsd
**Vendored on:** 2026-04-19
**License:** Apache License 2.0

This is the Windy Road maintained reference for the Apache Ant JUnit
XML format — the format that Jenkins, GitLab CI, GitHub Actions Test
Results (via `publish-test-results`), CircleCI, TeamCity, and
essentially every JUnit-consuming CI system understand.

protokit's `junit` formatters target this schema. Schema validation
in tests uses the `xmlschema` library against this vendored copy.

The original GitHub Actions `publish-test-results` xsd cited in the
2026-04-18 plan returned 404 at vendor time; the Windy Road xsd is
the canonical Apache Ant reference and is stricter (requires
`time`, `timestamp`, `hostname` attributes), so output that
validates against it also satisfies the more permissive consumers.
