"""
Partner Management Command Center — Dash by Plotly
Replaces the Gradio frontend with a fast, responsive Dash SPA.

Shareable public link: powered by pyngrok (same mechanism as Gradio share=True).
Run:  python dash_app.py
Then open the printed URL from any browser / share it with teammates.
"""

import sys, os, json as _json, urllib.parse
import traceback
import pandas as pd
sys.path.insert(0, os.path.dirname(__file__))

from utils.runtime_logging import setup_runtime_logging

LOG_FILES = setup_runtime_logging("dash_app")

import dash
from dash import dcc, html, Input, Output, State, callback, no_update, ctx, ALL
import dash_bootstrap_components as dbc
import dash_ag_grid as dag
import plotly.graph_objects as go
from ui.ai_query_corporate import build_ai_query_tab, status_chip
from ui.result_cards import build_result_panel
from partner_solutions.registry import build_full_registry, build_primary_registry
from ui.partner_hub import build_live_workspace, build_partner_home, build_standby_workspace

from utils.euler_oauth import build_auth_url, exchange_code, is_connected, get_token_set, clear_token_set
from utils.euler_mcp_client import EulerMCPClient

from data_engine import (
    # Synthetic data imports (commented out — Claude Partner Network mode)
    # ALL_PARTNERS, ALL_REGIONS, ALL_TIERS, STAGE_ORDER,
    # db_usage,
    # get_kpi_data, build_overview_figs,
    # build_partners, build_deals, build_certs,
    # build_snowflake, build_pipelines,
    # build_usage, build_health,
    render_chart, tablerag_ask,
    EXAMPLE_QUESTIONS,
    # ALL_REGIONS, ALL_TIERS,  # no longer needed — synthetic filters removed
)

# EULER is the only partner solution loaded by the live Dash runtime.
# Standby partner modules are lazy-loaded only by build_full_registry(), never
# by this application path.
PRIMARY_SOLUTIONS = build_primary_registry()
EULER_SOLUTION = PRIMARY_SOLUTIONS.get("euler")
# The full registry is metadata-only for standby solutions.  It powers the
# homepage and routed workspace shells without loading partner credentials or
# making network calls.
PARTNER_SOLUTIONS = build_full_registry()
PARTNER_MANIFESTS = {manifest.id: manifest for manifest in PARTNER_SOLUTIONS.manifests()}

dbc.Tab(
    build_ai_query_tab(),
    label="AI Query",
    tab_id="tab-ai-query",
)

# ── App init ──────────────────────────────────────────────────────────────────
app = dash.Dash(
    __name__,
    external_stylesheets=[
        dbc.themes.SLATE,
        "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800"
        "&family=JetBrains+Mono:wght@400;500&display=swap",
    ],
    suppress_callback_exceptions=True,
    title="Partner Fabric",
    meta_tags=[
        {"name": "viewport", "content": "width=device-width, initial-scale=1"},
        {"name": "description", "content": "A unified portal for live and integration-ready partner workspaces."},
    ],
)
server = app.server  # Expose Flask server for WSGI deployment


def _log_tablerag_error(question, result, region, tier, source):
    provider = result.get("provider") or "unknown"
    providers_used = result.get("providers_used") or []
    provider_label = " -> ".join(providers_used) if providers_used else provider
    print(
        (
            "[LinearRAG][ERROR] "
            f"provider={provider_label} region={region} tier={tier} source={source} "
            f"question={question!r} error={result.get('error', '')}"
        ),
        file=sys.stderr,
        flush=True,
    )


def _log_unexpected_error(question, region, tier, source):
    print(
        (
            "[LinearRAG][UNEXPECTED] "
            f"region={region} tier={tier} source={source} question={question!r}"
        ),
        file=sys.stderr,
        flush=True,
    )
    traceback.print_exc()


# ── Utility helpers ───────────────────────────────────────────────────────────
def make_col_defs(df):
    """Generate AG Grid columnDefs from a DataFrame."""
    return [
        {
            "field": col,
            "headerName": col.replace("_", " ").title(),
            "filter": True,
            "sortable": True,
            "resizable": True,
            "minWidth": 100,
        }
        for col in df.columns
    ]


def empty_grid(grid_id, height="400px"):
    return dag.AgGrid(
        id=grid_id,
        columnDefs=[],
        rowData=[],
        defaultColDef={"resizable": True, "sortable": True, "filter": True, "minWidth": 100},
        dashGridOptions={"pagination": True, "paginationPageSize": 15, "animateRows": True},
        style={"height": height, "width": "100%"},
        className="ag-theme-alpine-dark",
    )


def make_graph(graph_id):
    return dcc.Graph(
        id=graph_id,
        figure=go.Figure(layout=dict(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")),
        config={"displayModeBar": False, "responsive": True},
        style={"minHeight": "320px"},
    )


def kpi_row(data: dict):
    """Build an 8-card KPI row from a data dict returned by get_kpi_data()."""
    cards_spec = [
        ("🤝 Total Partners",   str(data["total_partners"]),                         "#38BDF8"),
        ("✅ Active",            str(data["active_partners"]),                         "#10B981"),
        ("💰 Pipeline Value",   f"${data['total_pipeline']:,.0f}",                    "#A78BFA"),
        ("🏆 Closed-Won Rev",  f"${data['closed_won_rev']:,.0f}",                    "#F59E0B"),
        ("❤️ Avg Health",       f"{data['avg_health']:.1f}/100",                      "#34D399"),
        ("📜 Certs Expiring",   str(data["certs_expiring"]),                          "#FBBF24"),
        ("⚠️ High Churn Risk",  str(data["high_churn"]),                              "#EF4444"),
        ("📦 dbt Models",       str(data["dbt_models_count"]),                        "#818CF8"),
    ]
    cols = []
    for label, value, color in cards_spec:
        cols.append(
            dbc.Col(
                html.Div(
                    [
                        html.P(label, className="kpi-label"),
                        html.H3(
                            value,
                            style={
                                "color": color,
                                "margin": "0",
                                "fontSize": "22px",
                                "fontWeight": "800",
                                "letterSpacing": "-0.02em",
                            },
                        ),
                    ],
                    className="kpi-card",
                    style={"borderLeft": f"4px solid {color}"},
                ),
                xs=6, sm=4, md=3,
            )
        )
    return dbc.Row(cols, className="g-3 mb-3")


# ── Synthetic data pre-load (commented out — Claude Partner Network mode) ────
# _dbt_df, _coal_df, _dbt_fig, _coal_fig = build_pipelines()

# ── Layout components ─────────────────────────────────────────────────────────

HEADER = html.Div(
    html.Div(
        [
            html.Span("🧭", style={"fontSize": "40px", "lineHeight": "1"}),
            html.Div(
                [
                    html.H1(
                        "Partner Network — Claude AI",
                        style={
                            "margin": "0",
                            "fontSize": "26px",
                            "fontWeight": "800",
                            "color": "#F8FAFC",
                            "letterSpacing": "-0.02em",
                        },
                    ),
                    html.P(
                        [
                            "Live partner intelligence powered by ",
                            html.Span("Claude",               style={"color": "#A78BFA", "fontWeight": 700}), " · ",
                            html.Span("EULER Partner Network", style={"color": "#2563EB", "fontWeight": 700}), " · ",
                            html.Span("MCP Live Tools",        style={"color": "#38BDF8", "fontWeight": 700}),
                        ],
                        style={"margin": "4px 0 0", "color": "#94A3B8", "fontSize": "13px"},
                    ),
                ]
            ),
            html.Div(
                [
                    dbc.Button("🔌 Connect to EULER", id="euler-connect-btn", color="primary", size="sm", style={"fontWeight": "600"}),
                    dbc.Button("❌ Disconnect", id="euler-disconnect-btn", color="danger", size="sm", style={"display": "none", "fontWeight": "600"}),
                ],
                className="ms-auto", style={"display": "flex", "gap": "8px"}
            ),
        ],
        style={"display": "flex", "alignItems": "center", "gap": "16px"},
    ),
    className="header-banner",
)

# GLOBAL_FILTERS — commented out (synthetic data removed)
# GLOBAL_FILTERS = dbc.Row(
#     [
#         dbc.Col(
#             [
#                 html.Label("🌍 Region", className="filter-label"),
#                 dcc.Dropdown(id="g-region", options=[], value="All", clearable=False),
#             ],
#             md=2, sm=6, xs=12,
#         ),
#         dbc.Col(
#             [
#                 html.Label("🏅 Tier", className="filter-label"),
#                 dcc.Dropdown(id="g-tier", options=[], value="All", clearable=False),
#             ],
#             md=2, sm=6, xs=12,
#         ),
#     ],
#     className="mb-4 mt-3 g-3",
# )

# ── Tabs 1–6 (Synthetic data) — commented out ─────────────────────────────
# tab_overview = dbc.Tab([...], label="🏠 Overview",        tab_id="tab-overview")
# tab_ms       = dbc.Tab([...], label="🪟 Partners & Deals", tab_id="tab-ms")
# tab_sf       = dbc.Tab([...], label="❄️ Snowflake",        tab_id="tab-sf")
# tab_pipes    = dbc.Tab([...], label="⚙️ dbt / Coalesce",   tab_id="tab-pipes")
# tab_usage    = dbc.Tab([...], label="🔷 Usage & Cost",     tab_id="tab-usage")
# tab_health   = dbc.Tab([...], label="🧠 Partner Health",   tab_id="tab-health")

# ─────────────────────────────────────────────────────────────────────────────
# TAB 7 — AI QUERY HYBRID QUERY
# ─────────────────────────────────────────────────────────────────────────────
SCHEMA_PANEL = html.Details(
    [
        html.Summary("📋 Available EULER MCP Tools"),
        html.Div(
            [
                html.P([html.B("partners", style={"color": "#E2E8F0"}),
                        " — List and search partners in your EULER account"]),
                html.P([html.B("company_deals", style={"color": "#E2E8F0"}),
                        " — View and filter company deals"]),
                html.P([html.B("partner_directory_search", style={"color": "#E2E8F0"}),
                        " — Search the partner directory"]),
                html.P([html.B("partner_artifacts", style={"color": "#E2E8F0"}),
                        " — Browse partner artifacts and documents"]),
                html.P([html.B("referrals", style={"color": "#E2E8F0"}),
                        " — View and manage referrals"]),
            ],
            style={"marginTop": "10px", "fontFamily": "JetBrains Mono, monospace",
                   "fontSize": "12px", "color": "#94A3B8", "lineHeight": "1.9"},
        ),
    ],
    className="schema-details",
)

tab_dbgpt = dbc.Tab(
    [
        # ── Header ────────────────────────────────────────────────
        html.Div(
            [
                html.H2("🤖 AI Query — EULER MCP Chat",
                        style={"color": "#E9D5FF", "fontSize": "19px", "fontWeight": 700, "margin": "0 0 6px"}),
                html.P("Ask natural language questions. Claude uses live EULER MCP tools to answer with current data.",
                       style={"color": "#A78BFA", "fontSize": "13px", "margin": 0}),
            ],
            className="dbgpt-header mb-3",
        ),

        # ── Hidden filter stores (preserve callback compatibility) ──
        dcc.Store(id="rag-region", data="All"),
        dcc.Store(id="rag-tier", data="All"),
        dcc.Store(id="rag-source", data="All"),

        dbc.Row([
            # ── LEFT COLUMN: Chat Interface ─────────────────────────────
            dbc.Col([
                html.Div(
                    id="chat-history-container",
                    style={
                        "height": "500px", "overflowY": "auto", "padding": "12px",
                        "background": "#1E293B", "borderRadius": "8px", "border": "1px solid #334155",
                        "marginBottom": "12px", "display": "flex", "flexDirection": "column", "gap": "12px"
                    }
                ),
                html.P("💡 Example questions", style={"color": "#94A3B8", "fontSize": "12px", "fontWeight": 600, "margin": "0 0 8px"}),
                html.Div([
                    dbc.Button(q, id={"type": "example-btn", "index": i}, size="sm", outline=True, color="secondary",
                               style={"margin": "2px", "fontSize": "11px", "textAlign": "left", "whiteSpace": "normal"})
                    for i, q in enumerate(EXAMPLE_QUESTIONS[:4])
                ], className="mb-3"),

                html.Label("🤖 Model Provider", className="filter-label"),
                dcc.Dropdown(
                    id="rag-provider",
                    options=[
                        {"label": "Claude", "value": "Claude"},
                        {"label": "Groq (Llama 3.3)", "value": "Groq (Llama 3.3)"},
                        {"label": "Groq (GPT-OSS 120B)", "value": "Groq (GPT-OSS 120B)"},
                        {"label": "Groq (Qwen 3.6-27B)", "value": "Groq (Qwen 3.6-27B)"},
                    ],
                    value="Groq (Llama 3.3)",
                    clearable=False,
                    className="mb-3",
                ),
                html.Small(
                    "Live EULER tool access is used automatically on either provider once EULER is connected.",
                    style={"color": "#64748B", "display": "block", "marginTop": "-8px", "marginBottom": "12px"},
                ),

                dbc.Row([
                    dbc.Col(
                        dcc.Textarea(
                            id="dbgpt-input", placeholder="e.g. Which Gold partners in EMEA have high churn risk?",
                            style={"width": "100%", "height": "80px", "background": "#0F172A", "color": "#E2E8F0",
                                   "border": "1px solid #475569", "borderRadius": "8px", "padding": "10px", "resize": "none",
                                   "fontFamily": "Inter, sans-serif", "fontSize": "13px"}
                        ), md=9, style={"paddingRight": "4px"}
                    ),
                    dbc.Col([
                        dbc.Button("▶ Send", id="dbgpt-run-btn", color="primary", className="w-100 mb-1", n_clicks=0),
                        dbc.Button("🗑 Clear", id="dbgpt-clear-btn", color="secondary", outline=True, className="w-100", n_clicks=0),
                    ], md=3, style={"paddingLeft": "4px", "display": "flex", "flexDirection": "column", "justifyContent": "center"}),
                ], className="g-0"),
                html.Div(id="dbgpt-status", className="mt-2"),
                dcc.Store(id="dbgpt-history", data=[]),
            ], md=4),

            # ── RIGHT COLUMN: Dynamic Dashboard ─────────────────────────
            dbc.Col([
                SCHEMA_PANEL,
                html.Div(id="dynamic-charts-container", className="mt-3", style={"display": "flex", "flexWrap": "wrap", "gap": "16px"}),
                html.Div(id="dbgpt-sql", style={"display": "none"}), # hidden
                html.Div(make_graph("dbgpt-chart"), style={"display": "none"}), # hidden to avoid callback error, will dynamically generate
                html.Div(className="mt-3"),
                empty_grid("dbgpt-grid", "300px"),
                html.Label("📚 RAG Context / Trace", className="filter-label mt-3"),
                dcc.Textarea(
                    id="dbgpt-rag-context", readOnly=True, value="",
                    style={"width": "100%", "height": "110px", "background": "#1E293B", "color": "#64748B",
                           "border": "1px solid #334155", "borderRadius": "8px", "padding": "10px",
                           "fontFamily": "JetBrains Mono, monospace", "fontSize": "11px", "resize": "vertical"}
                ),
            ], md=8)
        ]),
    ],
    label="🤖 AI Query",
    tab_id="tab-dbgpt",
)

# ── Full app layout ───────────────────────────────────────────────────────────
tab_dbgpt = dbc.Tab(
    build_ai_query_tab(),
    label="AI Query",
    tab_id="tab-dbgpt",
)

def _euler_workspace_actions():
    """Connection controls kept inside the live EULER workspace only."""
    return html.Div(
        [
            dcc.Store(id="euler-page-mounted", data=True),
            dbc.Button(
                "Connect EULER",
                id="euler-connect-btn",
                color="primary",
                size="sm",
                style={"fontWeight": "600"},
            ),
            dbc.Button(
                "Disconnect",
                id="euler-disconnect-btn",
                color="danger",
                size="sm",
                style={"display": "none", "fontWeight": "600"},
            ),
        ],
        style={"display": "flex", "gap": "8px"},
    )


def _render_partner_page(pathname):
    """Route the hub and partner workspaces without turning standby into live."""
    route = (pathname or "/").strip("/").split("/")
    partner_id = route[1] if len(route) == 2 and route[0] == "partners" else None
    manifest = PARTNER_MANIFESTS.get(partner_id)

    if manifest is None:
        return build_partner_home(PARTNER_MANIFESTS.values())
    if manifest.status == "active":
        return build_live_workspace(
            manifest,
            build_ai_query_tab(),
            actions=_euler_workspace_actions(),
        )
    return build_standby_workspace(manifest)


app.layout = html.Div(
    [
        dcc.Location(id="url", refresh=False),
        dcc.Location(id="oauth-redirect", refresh=True),
        html.Div(id="app-page"),
    ]
)


@callback(Output("app-page", "children"), Input("url", "pathname"))
def render_partner_page(pathname):
    return _render_partner_page(pathname)


# ═════════════════════════════════════════════════════════════════════════════
# CALLBACKS
# ═════════════════════════════════════════════════════════════════════════════

# ── Callbacks for Tabs 1–6 (Synthetic data) — commented out ─────────────────
# @callback(Output("kpi-cards", ...), ...) def update_overview(...): ...
# @callback(Output("partners-grid", ...), ...) def update_partners(...): ...
# @callback(Output("deals-grid", ...), ...) def update_deals(...): ...
# @callback(Output("certs-grid", ...), ...) def update_certs(...): ...
# @callback(Output("sf-grid", ...), ...) def update_snowflake(...): ...
# @callback(Output("usage-grid", ...), ...) def update_usage(...): ...
# @callback(Output("health-grid", ...), ...) def update_health(...): ...


# ── Tab 7 — Fill input from example buttons ───────────────────────────────────
@callback(
    Output("dbgpt-input", "value"),
    Input({"type": "example-btn", "index": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def fill_example(_):
    if not ctx.triggered_id:
        return no_update
    idx = ctx.triggered_id["index"]
    return EXAMPLE_QUESTIONS[idx]


def _empty_chart():
    return go.Figure(
        layout=dict(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            margin=dict(t=12, r=12, b=12, l=12),
        )
    )


def _render_result_children(df, tool_results):
    """Render small live responses as cards and larger responses as a grid."""
    if df is None or df.empty or len(df) <= 5:
        return build_result_panel(df, tool_results)

    return dag.AgGrid(
        id="euler-result-grid",
        columnDefs=make_col_defs(df),
        rowData=df.to_dict("records"),
        defaultColDef={
            "resizable": True,
            "sortable": True,
            "filter": True,
            "minWidth": 110,
        },
        dashGridOptions={
            "pagination": True,
            "paginationPageSize": 15,
            "animateRows": True,
        },
        className="ag-theme-alpine-dark",
        style={"height": "320px", "width": "100%"},
    )


def _chart_for_result(df, spec):
    """Render a chart against the display frame, tolerating title-cased columns."""
    if df is None or df.empty or not spec or spec.get("chart_type") == "none":
        return _empty_chart()

    normalized = dict(spec)
    for key in ("x", "y", "color"):
        value = normalized.get(key)
        if value and value not in df.columns:
            title_value = str(value).replace("_", " ").strip().title()
            normalized[key] = title_value if title_value in df.columns else value
    return render_chart(df, normalized)


def _trace_for_result(result):
    trace = result.get("trace") or ""
    used = [str(item.get("name")) for item in result.get("tool_results") or [] if item.get("name")]
    available = [str(name) for name in result.get("tools_available") or [] if name]
    lines = [trace] if trace else []
    if used:
        lines.append("Live tools used: " + ", ".join(dict.fromkeys(used)))
    if available:
        lines.append("Live tools available: " + ", ".join(available))
    return "\n".join(lines)

# # ── Tab 7 — Run AI query ──────────────────────────────────────────────────────
# @callback(
#     Output("dbgpt-history",     "data"),
#     Output("dbgpt-sql",         "children"),
#     Output("dbgpt-grid",        "children"),
#     Output("dbgpt-chart",       "figure"),
#     Output("dbgpt-status",      "children"),
#     Output("dbgpt-rag-context", "children"),
#     Output("dbgpt-provider",    "children"),
#     Input("dbgpt-run-btn",  "n_clicks"),
#     State("dbgpt-input",    "value"),
#     State("dbgpt-history",  "data"),
#     State("rag-region",     "value"),
#     State("rag-tier",       "value"),
#     State("rag-source",     "value"),
#     State("dbgpt-model",    "value"),
#     prevent_initial_call=True,
# )
# def run_dbgpt(n_clicks, question, history, region, tier, source, model):
#     _empty_fig = go.Figure(layout=dict(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)"))

#     if not question or not question.strip():
#         return (
#             history or [],
#             "Ask a question to see a clear, business-friendly answer here.",
#             html.Div("No rows yet.", className="pc-empty"),
#             _empty_chart(),
#             status_chip(),
#             "",
#             "",
#         )

#     try:
#         result = tablerag_ask(
#             question,
#             history or [],
#             region=region or "All",
#             tier=tier or "All",
#             source=source or "All",
#             model_provider=model or "Groq",
#         )
#     except Exception:
#         _log_unexpected_error(question, region, tier, source)
#         raise

#     provider = result.get("provider") or "unknown"
#     providers_used = result.get("providers_used") or []
#     provider_label = " -> ".join(providers_used) if providers_used else provider
#     if result.get("error"):
#         _log_tablerag_error(question, result, region, tier, source)

#     answer = result.get("markdown") or result.get("answer") or result.get("error") or ""
#     new_history = (history or []) + [
#         {"role": "user", "content": question},
#         {"role": "assistant", "content": answer},
#     ]
#     df = result.get("dataframe")
#     chart_specs = result.get("chart_specs") or []
#     chart = _chart_for_result(df, chart_specs[0] if chart_specs else None)
#     status = status_chip(
#         provider_label,
#         euler_on=bool(result.get("euler_live_fetch_ok")),
#         error=result.get("error") or "",
#     )
#     return (
#         new_history,
#         answer,
#         _render_result_children(df, result.get("tool_results") or []),
#         chart,
#         status,
#         _trace_for_result(result),
#         provider_label,
#     )

#     if not question or not question.strip():
#         return history, "", [], [], _empty_fig, "", "", [], []

#     try:
#         result = tablerag_ask(question, history or [], region=region, tier=tier, source=source, model_provider=provider or "Groq (Llama 3.3)")
#     except Exception:
#         _log_unexpected_error(question, region, tier, source)
#         raise
#     provider = result.get("provider") or "unknown"
#     providers_used = result.get("providers_used") or []
#     provider_label = " -> ".join(providers_used) if providers_used else provider

#     if result["error"]:
#         _log_tablerag_error(question, result, region, tier, source)
#         status = html.Div(
#             [
#                 f"⚠️ {result['error']} ",
#                 html.Span(f"(provider: {provider_label})"),
#             ],
#             className="dbgpt-status-err",
#         )
#         return history, "", [], [], _empty_fig, status, "", render_chat_bubbles(history), []

#     new_history = (history or []) + [
#         {"role": "user",      "content": question},
#         {"role": "assistant", "content": result.get("answer", "")},
#     ]

#     df        = result["dataframe"]
    
#     chart_specs = result.get("chart_specs", [])
#     dynamic_charts = []
#     for i, spec in enumerate(chart_specs):
#         fig = render_chart(df, spec)
#         if fig:
#             dynamic_charts.append(html.Div(
#                 dcc.Graph(figure=fig, config={"displayModeBar": False}),
#                 style={"flex": "1 1 300px", "minWidth": "300px", "background": "#1E293B", "borderRadius": "8px", "padding": "8px", "border": "1px solid #334155"}
#             ))
            
#     chart = _empty_fig # keep the dummy one empty
    
#     col_defs  = make_col_defs(df) if not df.empty else []
#     row_data  = df.to_dict("records") if not df.empty else []
#     n_steps   = len(result.get("subqueries", []))
#     n_rows    = len(df)

#     answer_preview = result.get("answer", "")
#     if len(answer_preview) > 220:
#         answer_preview = answer_preview[:220] + "…"

#     status = html.Div(
#         [
#             f"✅ Retrieved {n_rows} passages across {n_steps} LinearRAG step{'s' if n_steps != 1 else ''}. ",
#             html.Span(f"Provider: {provider_label}. "),
#             html.Strong(answer_preview),
#         ],
#         className="dbgpt-status-ok",
#     )

#     return new_history, result["sql"], col_defs, row_data, chart, status, result.get("trace", ""), render_chat_bubbles(new_history), dynamic_charts

# ── Tab 7 — Run AI query ──────────────────────────────────────────────────────
@callback(
    Output("dbgpt-history",     "data"),
    Output("dbgpt-sql",         "children"),
    Output("dbgpt-grid",        "children"),
    Output("dbgpt-chart",       "figure"),
    Output("dbgpt-status",      "children"),
    Output("dbgpt-rag-context", "children"),
    Output("dbgpt-provider",    "children"),
    Input("dbgpt-run-btn",  "n_clicks"),
    State("dbgpt-input",    "value"),
    State("dbgpt-history",  "data"),
    State("rag-source",     "value"),
    State("dbgpt-model",    "value"),
    running=[
        (
            Output("dbgpt-status", "children"),
            html.Span(
                [
                    html.Span(className="pc-chip-dot"),
                    "Working… contacting EULER / LLM",
                ],
                className="pc-chip pc-chip-info",
            ),
            html.Span(
                [
                    html.Span(className="pc-chip-dot"),
                    "Ready",
                ],
                className="pc-chip pc-chip-info",
            ),
        ),
        (Output("dbgpt-run-btn", "disabled"), True, False),
    ],
    prevent_initial_call=True,
)
def run_dbgpt(n_clicks, question, history, source, model):
    if not question or not question.strip():
        return (
            history or [],
            "Ask a question to see a clear, business-friendly answer here.",
            html.Div("No rows yet.", className="pc-empty"),
            _empty_chart(),
            status_chip(),
            "",
            "",
        )

    region, tier = "All", "All"
    try:
        result = tablerag_ask(
            question,
            history or [],
            region=region,
            tier=tier,
            source=source or "All",
            model_provider=model or "Groq",
        )
    except Exception:
        _log_unexpected_error(question, region, tier, source)
        raise

    provider = result.get("provider") or "unknown"
    providers_used = result.get("providers_used") or []
    provider_label = " -> ".join(providers_used) if providers_used else provider
    if result.get("error"):
        _log_tablerag_error(question, result, region, tier, source)

    answer = result.get("markdown") or result.get("answer") or result.get("error") or ""
    new_history = (history or []) + [
        {"role": "user", "content": question},
        {"role": "assistant", "content": answer},
    ]
    df = result.get("dataframe")
    chart_specs = result.get("chart_specs") or []
    chart = _chart_for_result(df, chart_specs[0] if chart_specs else None)
    status = status_chip(
        provider_label,
        euler_on=bool(result.get("euler_live_fetch_ok")),
        error=result.get("error") or "",
    )
    return (
        new_history,
        answer,
        _render_result_children(df, result.get("tool_results") or []),
        chart,
        status,
        _trace_for_result(result),
        provider_label,
    )

# ── Tab 7 — Clear ─────────────────────────────────────────────────────────────
@callback(
    Output("dbgpt-history",     "data",    allow_duplicate=True),
    Output("dbgpt-sql",         "children",   allow_duplicate=True),
    Output("dbgpt-grid",        "children", allow_duplicate=True),
    Output("dbgpt-chart",       "figure",  allow_duplicate=True),
    Output("dbgpt-status",      "children",allow_duplicate=True),
    Output("dbgpt-rag-context", "children", allow_duplicate=True),
    Output("dbgpt-provider",    "children", allow_duplicate=True),
    Output("dbgpt-input",       "value",   allow_duplicate=True),
    Input("dbgpt-clear-btn", "n_clicks"),
    prevent_initial_call=True,
)
def clear_dbgpt(_):
    _empty_fig = go.Figure(layout=dict(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)"))
    return [], "Ask a question to see a clear, business-friendly answer here.", html.Div("No rows yet.", className="pc-empty"), _empty_chart(), status_chip(), "", "", ""


def _tool_catalog_item(name, description, operation, *, live):
    meta = f"{'LIVE' if live else 'DOCUMENTED REFERENCE — NOT LIVE'} · {operation.upper()}"
    return html.Div(
        [
            html.Div(str(name), className="pc-tool-name"),
            html.Div(meta, className="pc-tool-meta"),
            html.Div(str(description or "No description advertised."), className="pc-tool-description"),
        ],
        className="pc-tool-item",
    )

@callback(
    Output("euler-tool-status", "children"),
    Output("euler-tool-status", "className"),
    Output("euler-tool-catalog", "children"),
    Input("euler-tools-refresh-btn", "n_clicks"),
    Input("url", "hash"),
    Input("euler-connect-btn", "n_clicks"),
    Input("euler-disconnect-btn", "n_clicks"),
    prevent_initial_call=False,
)
def refresh_euler_tool_catalog(_n_clicks, _hash, _connect, _disconnect):
    """Same live path as the Groq agent: EulerMCPClient.list_tools()."""
    live_tools = []
    reason = ""

    try:
        client = EulerMCPClient()
        try:
            tools = client.list_tools()
            if getattr(client, "live_fetch_ok", False) and tools:
                live_tools = [
                    {
                        "name": t.get("name"),
                        "description": t.get("description") or "",
                    }
                    for t in tools
                    if isinstance(t, dict) and t.get("name")
                ]
        finally:
            client.close()
    except Exception as exc:
        reason = str(exc)

    if not live_tools:
        try:
            discovered = EULER_SOLUTION.discover(force=True)
            live_tools = []
            for t in discovered or []:
                name = getattr(t, "name", None) or (t.get("name") if isinstance(t, dict) else None)
                desc = getattr(t, "description", None) or (t.get("description") if isinstance(t, dict) else "") or ""
                if name:
                    live_tools.append({"name": name, "description": desc})
            if live_tools:
                reason = ""
        except Exception as exc:
            if not reason:
                reason = str(exc)

    if live_tools:
        items = [
            _tool_catalog_item(
                t["name"],
                t.get("description") or "",
                "write"
                if any(w in str(t["name"]).lower() for w in ("submit", "manage", "create", "update", "delete"))
                else "read",
                live=True,
            )
            for t in live_tools
        ]
        return (
            [html.Span(className="pc-chip-dot"), f"{len(live_tools)} live tools"],
            "pc-chip pc-chip-success",
            html.Div(
                [
                    html.Div(
                        "Confirmed by EULER tools/list. These names are safe for routing.",
                        className="pc-muted",
                        style={"marginBottom": "10px"},
                    ),
                    html.Div(items, className="pc-tool-list"),
                ]
            ),
        )

    reference_tools = EulerMCPClient.known_tools()
    items = [
        _tool_catalog_item(
            tool.get("name"),
            tool.get("description"),
            "write"
            if any(w in str(tool.get("name", "")).lower() for w in ("submit", "manage", "create", "update", "delete"))
            else "read",
            live=False,
        )
        for tool in reference_tools
    ]
    detail = (reason or "The live catalog returned no tools.")[:240]
    return (
        [html.Span(className="pc-chip-dot"), "Live catalog unavailable"],
        "pc-chip pc-chip-danger",
        html.Div(
            [
                html.Div(
                    "Could not load tools/list. Reference names below are not used for routing.",
                    className="pc-muted",
                    style={"marginBottom": "6px"},
                ),
                html.Div(detail, className="pc-mono", style={"marginBottom": "10px"}),
                html.Div(items, className="pc-tool-list"),
            ]
        ),
    )


# @callback(
#     Output("euler-tool-status", "children"),
#     Output("euler-tool-status", "className"),
#     Output("euler-tool-catalog", "children"),
#     Input("euler-tools-refresh-btn", "n_clicks"),
#     Input("euler-page-mounted", "data"),
#     prevent_initial_call=False,
# )
# def refresh_euler_tool_catalog(_n_clicks, _mounted):
#     """Show only the live catalog; documented names are visibly non-live hints."""
#     try:
#         live_tools = EULER_SOLUTION.discover(force=True)
#     except Exception as exc:
#         live_tools = []
#         reason = str(exc)
#     else:
#         reason = ""

#     if live_tools:
#         items = [
#             _tool_catalog_item(tool.name, tool.description, tool.operation, live=True)
#             for tool in live_tools
#         ]
#         return (
#             [html.Span(className="pc-chip-dot"), f"{len(live_tools)} live tools"],
#             "pc-chip pc-chip-success",
#             html.Div(
#                 [
#                     html.Div(
#                         "Confirmed by EULER tools/list. These names are safe for routing.",
#                         className="pc-muted",
#                         style={"marginBottom": "10px"},
#                     ),
#                     html.Div(items, className="pc-tool-list"),
#                 ]
#             ),
#         )

#     reference_tools = EulerMCPClient.known_tools()
#     items = [
#         _tool_catalog_item(
#             tool.get("name"),
#             tool.get("description"),
#             "write" if any(word in str(tool.get("name", "")).lower() for word in ("submit", "manage", "create", "update", "delete")) else "read",
#             live=False,
#         )
#         for tool in reference_tools
#     ]
#     detail = reason[:240] if reason else "The live catalog returned no tools."
#     return (
#         [html.Span(className="pc-chip-dot"), "Live catalog unavailable"],
#         "pc-chip pc-chip-danger",
#         html.Div(
#             [
#                 html.Div(
#                     "No tool calls are possible until EULER is connected. The names below are documented reference hints only.",
#                     className="pc-muted",
#                     style={"marginBottom": "6px"},
#                 ),
#                 html.Div(detail, className="pc-mono", style={"marginBottom": "10px"}),
#                 html.Div(items, className="pc-tool-list"),
#             ]
#         ),
#     )


── EULER OAuth Callbacks ─────────────────────────────────────────────────────
@callback(
    Output("oauth-redirect", "href"),
    Input("euler-connect-btn", "n_clicks"),
    prevent_initial_call=True
)


def euler_connect_click(n_clicks):
    if n_clicks:
        import flask
        host = flask.request.host_url.strip('/')
        redirect_uri = f"{host}/euler-callback"
        auth_url = build_auth_url(redirect_uri)
        return auth_url
    return no_update

@callback(
    Output("euler-connect-btn", "style"),
    Output("euler-disconnect-btn", "style"),
    Output("url", "hash"),
    Input("euler-page-mounted", "data"),
    Input("euler-disconnect-btn", "n_clicks"),
    State("url", "hash"),
    prevent_initial_call=False
)
def handle_oauth_state(_mounted, disconnect_clicks, hash_val):
    ctx_id = ctx.triggered_id if ctx.triggered_id else None
    
    if ctx_id == "euler-disconnect-btn":
        clear_token_set()
        EULER_SOLUTION.close()
        return {"display": "block", "fontWeight": "600"}, {"display": "none"}, no_update
        
    if hash_val and 'euler_code=' in hash_val:
        params = dict(urllib.parse.parse_qsl(hash_val.lstrip('#')))
        if 'euler_code' in params:
            try:
                exchange_code(params['euler_code'], params.get('euler_state'))
            except Exception as e:
                print(f"OAuth error: {e}")
                
    connected = is_connected()
    if connected:
        clear_hash = "" if 'euler_code=' in (hash_val or "") else no_update
        return {"display": "none"}, {"display": "block", "fontWeight": "600"}, clear_hash
    else:
        return {"display": "block", "fontWeight": "600"}, {"display": "none"}, no_update


# ── Flask OAuth Callback Route ─────────────────────────────────────────────────
from flask import request
@app.server.route("/euler-callback")
def euler_callback():
    code = request.args.get("code", "")
    state = request.args.get("state", "")
    error = request.args.get("error", "")

    if error:
        return f"<html><body><h2>OAuth Error</h2><p>{error}</p><p><a href='/'>Return</a></p></body></html>", 400
    if not code:
        return "<html><body><h2>No code received</h2><p><a href='/'>Return</a></p></body></html>", 400

    safe_code  = code.replace("'", "").replace('"', "")
    safe_state = state.replace("'", "").replace('"', "")
    return f"<html><head><meta http-equiv='refresh' content=\"0;url=/partners/euler#euler_code={safe_code}&euler_state={safe_state}\"></head><body>Redirecting to app...</body></html>"


# ═════════════════════════════════════════════════════════════════════════════
# ENTRY POINT  —  pyngrok tunnel for shareable public link
# ═════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    PORT = 8050

    sep = "=" * 62
    print(f"\n{sep}")
    print("  Partner Network — Claude AI")
    print(sep)

    try:
        import os
        from pyngrok import ngrok
        
        # Force-kill any orphaned ngrok.exe daemon on Windows to ensure fresh tunnel
        os.system("taskkill /f /im ngrok.exe >nul 2>&1")
        ngrok.kill()
        
        # pooling_enabled=True load-balances if the domain is already online elsewhere
        tunnel = ngrok.connect(PORT, pooling_enabled=True)
        public_url = tunnel.public_url
        print(f"  [SHARE] Shareable link:  {public_url}")
    except ImportError:
        public_url = None
        print("  [WARN]  pyngrok not installed - no public link.")
        print("          Run:  pip install pyngrok")
    except Exception as exc:
        public_url = None
        print(f"  [WARN]  ngrok error: {exc}")

    print(f"  [LOCAL] Local link:      http://localhost:{PORT}")
    print(f"{sep}\n")

    from utils.bm25_rag_engine import index_euler_data
    from utils.euler_api import fetch_partners, fetch_deals, EULER_CONFIGURED

    if EULER_CONFIGURED:
        print("  [BM25RAG] Live EULER API configured. Indexing live data...")
        index_euler_data()
    else:
        print("  [BM25RAG] EULER API not configured. Skipping index build. No synthetic data will be used.")

    app.run(host="0.0.0.0", port=PORT, debug=True)

