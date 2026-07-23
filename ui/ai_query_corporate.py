"""
ui/ai_query_corporate.py
------------------------
Corporate-styled AI Query tab layout for Partner Command Center (Dash).

Design system: bergside/awesome-design-skills · skills/corporate
  primary=#3B82F6  surface=#FFFFFF  text=#111827
  Poppins / Open Sans / IBM Plex Mono · 8pt grid · WCAG 2.2 AA

Wire into dash_app.py:
    from ui.ai_query_corporate import build_ai_query_tab

    dbc.Tab(build_ai_query_tab(), label="AI Query", tab_id="tab-ai-query")

Requires assets/corporate.css loaded by the Dash app.
Keeps existing callback IDs (dbgpt-*) so your current callbacks still work.
"""

from __future__ import annotations

from dash import dcc, html
import dash_bootstrap_components as dbc

# Example prompts — pattern-matching IDs match existing dash skill.
# Public name: dash_app.py's fill_example callback imports THIS list so the
# text it fills in always matches the button the user actually clicked.
EXAMPLE_QUESTIONS = [
    "List my EULER accounts",
    "How am I performing this quarter?",
    "Show my pending referrals",
    "What content has my customer shared with me?",
    "List my team and their roles",
]
_EXAMPLES = EXAMPLE_QUESTIONS  # backward-compat alias for any existing imports


def _chip(text: str, kind: str = "info") -> html.Span:
    return html.Span(
        [html.Span(className="pc-chip-dot"), text],
        className=f"pc-chip pc-chip-{kind}",
        id="dbgpt-status-chip" if kind == "info" else None,
    )


def build_ai_query_tab() -> html.Div:
    """Return the AI Query tab body (corporate layout)."""
    return html.Div(
        className="corporate-shell pc-ai-layout",
        children=[
            # ── Left: compose ──────────────────────────────────────────
            html.Div(
                className="pc-card pc-ai-compose",
                children=[
                    html.Div(
                        className="pc-card-header",
                        children=[
                            html.Div(
                                [
                                    html.Div("AI Query", className="pc-card-title"),
                                    html.Div(
                                        "Ask EULER in plain language. Live MCP tools when connected.",
                                        className="pc-muted",
                                    ),
                                ]
                            ),
                            html.Div(
                                id="dbgpt-status",
                                className="pc-status-bar",
                                children=[
                                    html.Span(
                                        [html.Span(className="pc-chip-dot"), "Ready"],
                                        className="pc-chip pc-chip-info",
                                    )
                                ],
                            ),
                        ],
                    ),
                    # Filters
                    html.Div(
                        className="pc-ai-filters",
                        children=[
                            html.Div(
                                [
                                    html.Label("Source", className="pc-label"),
                                    dcc.Dropdown(
                                        id="rag-source",
                                        options=[
                                            {"label": "All", "value": "All"},
                                            {"label": "EULER MCP", "value": "euler"},
                                        ],
                                        value="All",
                                        clearable=False,
                                        className="pc-select",
                                    ),
                                ]
                            ),
                            html.Div(
                                [
                                    html.Label("Model", className="pc-label"),
                                    dcc.Dropdown(
                                        id="dbgpt-model",
                                        options=[
                                            {"label": "Groq — GPT-OSS 120B", "value": "Groq"},
                                            {"label": "Groq — Qwen 3.6 27B", "value": "Groq qwen"},
                                            {"label": "Claude — MCP connector", "value": "Claude"},
                                        ],
                                        value="Groq",
                                        clearable=False,
                                        className="pc-select",
                                    ),
                                ]
                            ),
                        ],
                    ),
                    # Region/Tier filters were removed here — they were leftover
                    # UI from the old synthetic Microsoft-Partner-Center demo
                    # dataset and never mapped to anything in EULER's real data
                    # model, nor to any live tool call.
                    # Question
                    html.Div(
                        [
                            html.Label("Question", className="pc-label"),
                            dcc.Textarea(
                                id="dbgpt-input",
                                placeholder='e.g. List my EULER accounts · How am I performing this quarter?',
                                className="pc-textarea",
                                style={"width": "100%"},
                            ),
                            html.Div(
                                "Partner of more than one customer? Just name the one you "
                                "mean — e.g. \"At Acme, show my pipeline.\"",
                                className="pc-muted",
                                style={"marginTop": "6px"},
                            ),
                        ]
                    ),
                    # Actions
                    html.Div(
                        className="pc-ai-actions",
                        children=[
                            html.Button(
                                "Run query",
                                id="dbgpt-run-btn",
                                className="pc-btn pc-btn-primary",
                                n_clicks=0,
                            ),
                            html.Button(
                                "Clear",
                                id="dbgpt-clear-btn",
                                className="pc-btn pc-btn-secondary",
                                n_clicks=0,
                            ),
                        ],
                    ),
                    # Examples
                    html.Div(
                        [
                            html.Div("Try an example", className="pc-label", style={"marginBottom": "8px"}),
                            html.Div(
                                className="pc-ai-examples",
                                children=[
                                    html.Button(
                                        q if len(q) < 48 else q[:45] + "…",
                                        id={"type": "example-btn", "index": i},
                                        className="pc-example-btn",
                                        n_clicks=0,
                                        title=q,
                                    )
                                    for i, q in enumerate(_EXAMPLES)
                                ],
                            ),
                        ]
                    ),
                    dcc.Store(id="dbgpt-history", data=[]),
                ],
            ),
            # ── Right: answer + grid ───────────────────────────────────
            html.Div(
                style={"display": "flex", "flexDirection": "column", "gap": "16px"},
                children=[
                    html.Div(
                        className="pc-card",
                        children=[
                            html.Div(
                                className="pc-card-header",
                                children=[
                                    html.Div("Answer", className="pc-card-title"),
                                    html.Span(id="dbgpt-provider", className="pc-chip pc-chip-info"),
                                ],
                            ),
                            dcc.Markdown(
                                id="dbgpt-sql",
                                className="pc-answer",
                                children="Ask a question to see a clear, business-friendly answer here.",
                            ),
                        ],
                    ),
                    html.Div(
                        className="pc-card pc-tools-panel",
                        children=[
                            html.Div(
                                className="pc-card-header",
                                children=[
                                    html.Div(
                                        [
                                            html.Div("EULER capability surface", className="pc-card-title"),
                                            html.Div(
                                                "Names below come from the live MCP catalog when connected.",
                                                className="pc-muted",
                                            ),
                                        ]
                                    ),
                                    html.Span(
                                        [html.Span(className="pc-chip-dot"), "Checking"],
                                        id="euler-tool-status",
                                        className="pc-chip pc-chip-info",
                                    ),
                                ],
                            ),
                            html.Div(
                                id="euler-tool-catalog",
                                children=html.Div(
                                    "Checking the live EULER tool catalog...",
                                    className="pc-empty",
                                ),
                            ),
                            html.Button(
                                "Refresh live catalog",
                                id="euler-tools-refresh-btn",
                                className="pc-btn pc-btn-ghost pc-tools-refresh",
                                n_clicks=0,
                            ),
                        ],
                    ),
                    html.Div(
                        className="pc-card",
                        children=[
                            html.Div(
                                className="pc-card-header",
                                children=[
                                    html.Div("Results", className="pc-card-title"),
                                    html.Span("Structured tool rows", className="pc-muted"),
                                ],
                            ),
                            html.Div(
                                id="dbgpt-grid",
                                className="pc-grid-shell",
                                children=html.Div(
                                    "No rows yet. Tool results will appear here as a table.",
                                    className="pc-empty",
                                ),
                            ),
                        ],
                    ),
                    html.Div(
                        className="pc-card",
                        children=[
                            html.Div("Chart", className="pc-card-title", style={"marginBottom": "12px"}),
                            dcc.Graph(
                                id="dbgpt-chart",
                                config={"displayModeBar": False, "responsive": True},
                                style={"height": "260px"},
                            ),
                        ],
                    ),
                    html.Div(
                        className="pc-card",
                        children=[
                            html.Div(
                                className="pc-card-header",
                                children=[
                                    html.Div("Context", className="pc-card-title"),
                                    html.Span("RAG / MCP trace", className="pc-muted"),
                                ],
                            ),
                            html.Pre(
                                id="dbgpt-rag-context",
                                className="pc-mono",
                                style={
                                    "margin": 0,
                                    "whiteSpace": "pre-wrap",
                                    "maxHeight": "160px",
                                    "overflow": "auto",
                                    "color": "#6B7280",
                                    "fontSize": "0.75rem",
                                },
                                children="",
                            ),
                        ],
                    ),
                ],
            ),
        ],
    )


def status_chip(provider: str = "", euler_on: bool = False, error: str = "") -> html.Span:
    """Helper for callbacks to render a corporate status chip."""
    if error:
        return html.Span(
            [html.Span(className="pc-chip-dot"), f"Error: {error[:80]}"],
            className="pc-chip pc-chip-danger",
        )
    if euler_on and provider:
        return html.Span(
            [html.Span(className="pc-chip-dot"), f"{provider} · EULER live"],
            className="pc-chip pc-chip-success",
        )
    if provider:
        return html.Span(
            [html.Span(className="pc-chip-dot"), provider],
            className="pc-chip pc-chip-info",
        )
    return html.Span(
        [html.Span(className="pc-chip-dot"), "Ready"],
        className="pc-chip pc-chip-info",
    )