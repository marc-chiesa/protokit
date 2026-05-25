# `d6f_migration_recipe/` — byte-equivalence fixtures

These fixtures are consumed by `test_cli_d6f_migration_recipe_snippet_fixtures.py`
to enforce byte-equivalence between published TOML snippets (in `CHANGELOG.md`
and `README.md`) and a committed source-of-truth per
[[changelog-readme-snippet-fixture-byte-equivalence-2026-05-21]].

## Naming convention

- **`path2_*.toml` / `path3_*.toml` / `path4_*.toml`** — map to numbered
  paths in `CHANGELOG.md` → `### D6f — 0.7.0` → `#### Pre-upgrade migration
  recipe`. Path 1 ("fix the schema") has no TOML snippet and therefore no
  fixture.
- **`disabled_rules_*.toml` / `enabled_rules_*.toml`** — map to TOML
  snippets in `README.md` → `### Disabling and re-enabling rules`
  (Disable/Enable mechanisms tables). Unnumbered because the README's
  presentation isn't path-ordered.

End-to-end migration-path behavior is verified separately at
`tests/schema/lint/cli/test_cli_r6_migration_recipe.py` (D6f U1, against
the `d6f_r6_migration/` fixture set). This directory's fixtures are
parse-and-doc-presence ratchets only.
