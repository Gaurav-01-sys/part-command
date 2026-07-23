# Corporate UI — integration

Based on [bergside/awesome-design-skills · corporate](https://github.com/bergside/awesome-design-skills/tree/main/skills/corporate).

## 1. Copy files

```
assets/corporate.css          →  your_project/assets/corporate.css
ui/ai_query_corporate.py      →  your_project/ui/ai_query_corporate.py
```

Dash auto-serves everything under `assets/`.

## 2. Load CSS in `dash_app.py`

```python
app = dash.Dash(
    __name__,
    external_stylesheets=[
        dbc.themes.FLATLY,  # or keep SLATE if you prefer dark elsewhere
        "https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=Open+Sans:wght@400;500;600;700&family=Poppins:wght@500;600;700&display=swap",
    ],
    suppress_callback_exceptions=True,
)
# corporate.css is picked up automatically from assets/
```

## 3. Use the tab

```python
from ui.ai_query_corporate import build_ai_query_tab, status_chip

dbc.Tab(
    build_ai_query_tab(),
    label="AI Query",
    tab_id="tab-ai-query",
)
```

Existing callback IDs are preserved:

| ID | Role |
|----|------|
| `dbgpt-input` | question textarea |
| `dbgpt-run-btn` / `dbgpt-clear-btn` | actions |
| `dbgpt-sql` | answer (Markdown) |
| `dbgpt-grid` | results table host |
| `dbgpt-chart` | Plotly figure |
| `dbgpt-status` | status chip area |
| `dbgpt-history` | conversation store |
| `rag-region` / `rag-tier` / `rag-source` | filters |
| `{"type": "example-btn", "index": i}` | example prompts |

## 4. Status chip in your run callback

```python
from ui.ai_query_corporate import status_chip

# inside the run-query callback return:
status_chip(
    provider=result.get("provider", ""),
    euler_on="euler_mcp" in (result.get("providers_used") or []),
    error=result.get("error") or "",
)
```

## Design tokens (corporate skill)

| Token | Value |
|-------|-------|
| primary | `#3B82F6` |
| secondary | `#8B5CF6` |
| success | `#16A34A` |
| warning | `#D97706` |
| danger | `#DC2626` |
| surface | `#FFFFFF` |
| text | `#111827` |
| spacing | 8pt grid |
| fonts | Poppins / Open Sans / IBM Plex Mono |
