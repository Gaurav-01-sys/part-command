from __future__ import annotations

import os

import pandas as pd
import plotly.express as px

from data_engine import (
    ALL_REGIONS,
    ALL_TIERS,
    build_deals,
    build_health,
    build_partners,
    render_chart,
)
from mini_anvil import App


app = App(
    title="Partner Studio",
    description="An Anvil-style Python UI scaffold built on a small Gradio runtime.",
)


with app:
    with app.tabs():
        with app.tab("Partner Explorer"):
            with app.row():
                region = app.dropdown(ALL_REGIONS, value="All", label="Region")
                tier = app.dropdown(ALL_TIERS, value="All", label="Tier")
                status = app.dropdown(["All", "Active", "Inactive"], value="All", label="Status")
            search = app.button("Search partners")
            partners_table = app.dataframe(label="Partners")
            partners_summary = app.markdown("Use the filters and run a search.")

            @app.on_click(search, inputs=[region, tier, status], outputs=[partners_table, partners_summary])
            def search_partners(region_value: str, tier_value: str, status_value: str):
                df = build_partners(region_value, tier_value, status_value)
                summary = (
                    f"Showing {len(df)} partner records for "
                    f"region={region_value}, tier={tier_value}, status={status_value}."
                )
                return df, summary

        with app.tab("Deal Explorer"):
            with app.row():
                deal_region = app.dropdown(ALL_REGIONS, value="All", label="Region")
                deal_tier = app.dropdown(ALL_TIERS, value="All", label="Tier")
                stage = app.dropdown(["All", "Prospect", "Qualification", "Proposal", "Negotiation", "Closed-Won", "Closed-Lost"], value="All", label="Stage")
            deal_search = app.button("Search deals")
            deals_table = app.dataframe(label="Deals")
            deals_plot = app.plot(label="Stage chart")

            @app.on_click(deal_search, inputs=[deal_region, deal_tier, stage], outputs=[deals_table, deals_plot])
            def search_deals(region_value: str, tier_value: str, stage_value: str):
                df, fig = build_deals(region_value, tier_value, stage_value)
                return df, fig

        with app.tab("Health View"):
            with app.row():
                churn = app.dropdown(["All", "High", "Medium", "Low"], value="All", label="Churn risk")
                health_tier = app.dropdown(ALL_TIERS, value="All", label="Tier")
            health_search = app.button("Refresh health")
            health_table = app.dataframe(label="Health scores")
            health_scatter = app.plot(label="Scatter")
            health_box = app.plot(label="Tier box")

            @app.on_click(health_search, inputs=[churn, health_tier], outputs=[health_table, health_scatter, health_box])
            def refresh_health(churn_value: str, tier_value: str):
                df, scatter, box = build_health(churn_value, tier_value)
                return df, scatter, box

        with app.tab("Assistant"):
            prompt = app.textbox(label="Ask the app", placeholder="e.g. Show Gold partners in EMEA with high churn risk", lines=3)
            ask_btn = app.button("Run")
            answer = app.markdown("Type a question and run it.")
            placeholder = app.dataframe(label="Result preview")

            @app.on_click(ask_btn, inputs=[prompt], outputs=[answer, placeholder])
            def explain(query: str):
                query = (query or "").strip()
                if not query:
                    return "Enter a question first.", pd.DataFrame()
                return (
                    "This scaffold is ready for LLM wiring. "
                    "The current demo keeps it local and deterministic.",
                    pd.DataFrame([{"query": query, "status": "received"}]),
                )


if __name__ == "__main__":
    share = os.getenv("MINI_ANVIL_SHARE", "").strip().lower() in {"1", "true", "yes", "on"}
    app.run(server_name="127.0.0.1", server_port=7861, share=share)
