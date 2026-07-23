# Partner solutions

The portal is intentionally EULER-first.

- `build_primary_registry()` is the runtime registry used by `dash_app.py`.
  It contains only EULER.
- Databricks, Snowflake, and Microsoft have manifest-only standby solutions.
  They describe the future MCP contract but do not read credentials or make
  network calls.
- `build_full_registry()` is an explicit catalog for future Settings and
  diagnostics screens. It is not imported by the main Dash runtime.

When a standby partner is activated, replace its manifest-only implementation
with a real MCP adapter and add it to the primary registry deliberately.
