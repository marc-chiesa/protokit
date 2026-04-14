# protokit examples

Runnable scripts demonstrating the schema-compatibility API.

Each file is self-contained — descriptor pools are built programmatically so you don't need `protoc` or prebuilt `.descriptor_set` files. Run any script from the repo root:

```bash
python examples/schema_check.py
python examples/schema_plugin.py
```

| File | Shows |
|------|-------|
| `schema_check.py` | Basic `check_compatibility` call, profile comparison, JSON output. |
| `schema_plugin.py` | Custom field plugin via `SchemaChecker.register_field_rule`, using the built-in `deprecated` option. |
| `rule_pack.py` | Module with a `RULES` list; imported by `schema_plugin.py` via `load_rule_pack`. |

See the main README's **Schema Compatibility** section for the full API reference.
