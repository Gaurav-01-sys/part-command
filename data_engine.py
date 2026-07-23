"""
data_engine.py - Pure-Python data and chart layer.
All build_* functions are extracted from app.py with no Gradio dependency.
Imported by dash_app.py to power the Dash frontend.
"""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import warnings
warnings.filterwarnings("ignore")

from utils.linear_query_engine import ask as tablerag_ask, get_connection  # noqa: F401
# from utils.euler_api import (
#     EULER_CONFIGURED, fetch_partners, fetch_deals, fetch_certifications,
# )

# ── Load all data (SYNTHETIC COMMENTED OUT) ──────────────────────────────────
# DATA = os.path.join(os.path.dirname(__file__), "data")

# if EULER_CONFIGURED:
#     # Live data from your company's EULER account
#     ms_partners = fetch_partners()
#     ms_certs    = fetch_certifications()
#     ms_deals    = fetch_deals()
# else:
#     ms_partners = pd.DataFrame()
#     ms_certs = pd.DataFrame()
#     ms_deals = pd.DataFrame()

# sf_fact_deals = pd.read_csv(f"{DATA}/snowflake/fact_deals.csv")
# sf_dim        = pd.read_csv(f"{DATA}/snowflake/dim_partners.csv")
# db_usage      = pd.read_csv(f"{DATA}/databricks/product_usage.csv")
# db_health     = pd.read_csv(f"{DATA}/databricks/partner_health_scores.csv")
# dbt_models    = pd.read_csv(f"{DATA}/dbt/model_run_results.csv")
# coal_pipe     = pd.read_csv(f"{DATA}/coalesce/pipeline_runs.csv")

# ALL_PARTNERS = ["All"]
# ALL_REGIONS = ["All"]
# ALL_TIERS = ["All"]
ALL_PARTNERS = ["All"]
ALL_REGIONS = ["All"]
ALL_TIERS = ["All"]

COLORS = {
    "Gold": "#F59E0B", "Silver": "#94A3B8", "Bronze": "#B45309",
    "Active": "#10B981", "Inactive": "#EF4444",
    "bg": "#0F172A", "card": "#1E293B", "accent": "#38BDF8",
    "success": "#10B981", "warn": "#F59E0B", "error": "#EF4444",
}

STAGE_ORDER = ["Prospect", "Qualification", "Proposal", "Negotiation", "Closed-Won", "Closed-Lost"]

EXAMPLE_QUESTIONS = [
    "List my EULER accounts",
    "How am I performing this quarter?",
    "Show my pending referrals",
    "What content has my customer shared with me?",
    "List my team and their roles",
    "Show my deals and pipeline",
]

_PLOT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font_color="#CBD5E1",
)

# Pre-warm SQLite DB — disabled (synthetic data removed)
# get_connection()


# ── Shared filter helper ───────────────────────────────────────────────────────
# def filter_partners(df, region="All", tier="All", id_col="partner_id"):
#     ids = ms_partners.copy()
#     if region != "All":
#         ids = ids[ids["region"] == region]
#     if tier != "All":
#         ids = ids[ids["tier"] == tier]
#     valid = ids["partner_id"].tolist()
#     return df[df[id_col].isin(valid)]


# ── TAB 1 — OVERVIEW ─────────────────────────────────────────────────────────
# def get_kpi_data(region="All", tier="All"):
#     ...
# def build_overview_figs(region="All", tier="All"):
#     ...

# ── TAB 2 — PARTNERS & DEALS (Microsoft) ─────────────────────────────────────
# def build_partners(region="All", tier="All", status_filter="All"):
#     ...

# def build_deals(region="All", tier="All", stage_filter="All"):
#     ...

# def build_certs(region="All", tier="All", cert_status="All"):
#     ...

# ── TAB 3 — SNOWFLAKE WAREHOUSE ───────────────────────────────────────────────
# def build_snowflake(table_choice="fact_deals  (120 rows)"):
#     ...

# ── TAB 4 — dbt / COALESCE PIPELINES ─────────────────────────────────────────
# def build_pipelines():
#     ...

# ── TAB 5 — DATABRICKS USAGE & COST ──────────────────────────────────────────
# def build_usage(partner_filter="All", product_filter="All"):
#     ...

# ── TAB 6 — PARTNER HEALTH (Databricks ML) ───────────────────────────────────
# def build_health(churn_filter="All", tier_filter="All"):
#     ...


# ── TAB 7 — AI query chart helper ─────────────────────────────────────────────
def render_chart(df: pd.DataFrame, spec: dict) -> go.Figure:
    """Build a Plotly figure from a chart spec dict returned by tablerag_ask."""
    if not spec or spec.get("chart_type") == "none" or df.empty:
        return go.Figure()
    ct = spec.get("chart_type", "none")
    x  = spec.get("x")     if spec.get("x")     in df.columns else None
    y  = spec.get("y")     if spec.get("y")     in df.columns else None
    c  = spec.get("color") if spec.get("color") in df.columns else None
    try:
        if   ct == "bar"       and x and y: fig = px.bar(df, x=x, y=y, color=c)
        elif ct == "line"      and x and y: fig = px.line(df, x=x, y=y, color=c)
        elif ct == "pie"       and x and y: fig = px.pie(df, names=x, values=y, hole=0.45)
        elif ct == "scatter"   and x and y: fig = px.scatter(df, x=x, y=y, color=c)
        elif ct == "histogram" and x:       fig = px.histogram(df, x=x, color=c)
        else:                               return go.Figure()
        fig.update_layout(**_PLOT, margin=dict(t=50, b=50, l=40, r=20))
        return fig
    except Exception:
        return go.Figure()
