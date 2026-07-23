"""
ui/result_cards.py
------------------
Friendly card layout for EULER tool results (single partner / few rows).
Use when the dataframe is small and a bar chart of IDs is not useful.

Example in a Dash callback:

    from ui.result_cards import build_result_panel

    children = build_result_panel(result["dataframe"], result.get("tool_results") or [])
"""

from __future__ import annotations

from typing import Any

import pandas as pd
from dash import html


_FIELD_LABELS = {
    "name": "Partner",
    "Name": "Partner",
    "type": "Type",
    "Type": "Type",
    "affiliate_company_name": "Affiliate",
    "Affiliate Company Name": "Affiliate",
    "partner_id": "Partner ID",
    "Partner Id": "Partner ID",
    "company_id": "Company ID",
    "Company Id": "Company ID",
    "id": "Account ID",
    "Id": "Account ID",
    "dashboard_url": "Dashboard",
    "Dashboard Url": "Dashboard",
    "status": "Status",
    "Status": "Status",
    "tier": "Tier",
    "Tier": "Tier",
    "region": "Region",
    "Region": "Region",
}


def _label(col: str) -> str:
    return _FIELD_LABELS.get(col, str(col).replace("_", " ").title())


def _is_url(val: Any) -> bool:
    return isinstance(val, str) and val.startswith("http")


def partner_card(row: dict[str, Any]) -> html.Div:
    """One partner/account as a clean key-value card."""
    title = row.get("Name") or row.get("name") or row.get("Partner") or "Partner"
    affiliate = row.get("Affiliate Company Name") or row.get("affiliate_company_name") or ""

    header = html.Div(
        [
            html.Div(str(title), className="pc-card-title"),
            html.Div(str(affiliate), className="pc-muted") if affiliate else None,
        ],
        className="pc-card-header",
        style={"marginBottom": "12px"},
    )

    rows = []
    skip = {"Name", "name", "Affiliate Company Name", "affiliate_company_name"}
    for k, v in row.items():
        if k in skip or v is None or str(v).strip() == "":
            continue
        val_node: Any
        if _is_url(v):
            val_node = html.A(str(v), href=str(v), target="_blank", rel="noopener noreferrer")
        else:
            val_node = html.Span(str(v), className="pc-mono" if "id" in k.lower() else None)
        rows.append(
            html.Div(
                [
                    html.Div(_label(k), className="pc-label"),
                    html.Div(val_node, style={"fontSize": "0.9rem", "marginTop": "2px"}),
                ],
                style={"marginBottom": "10px"},
            )
        )

    return html.Div([header, html.Div(rows)], className="pc-card", style={"marginBottom": "12px"})


def build_result_panel(
    df: pd.DataFrame | None,
    tool_results: list[dict] | None = None,
) -> html.Div:
    """
    Prefer cards for 1–5 rows of partner-like data.
    Fall back to a short empty state when there is nothing to show.
    """
    if df is None or df.empty:
        # Still surface tool errors if any
        errors = [
            tr.get("error") or tr.get("raw")
            for tr in (tool_results or [])
            if tr.get("error")
        ]
        if errors:
            return html.Div(
                [
                    html.Div("Tool issue", className="pc-card-title"),
                    html.Pre("\n".join(str(e)[:500] for e in errors), className="pc-mono"),
                ],
                className="pc-card",
            )
        return html.Div(
            "No structured rows yet. Ask about partners, deals, or artifacts.",
            className="pc-empty",
        )

    if len(df) <= 5:
        cards = [partner_card(row._asdict() if hasattr(row, "_asdict") else row.to_dict()) for _, row in df.iterrows()]
        return html.Div(cards)

    # Many rows → leave grid rendering to the caller; return a compact summary
    return html.Div(
        [
            html.Div(f"{len(df)} records", className="pc-card-title"),
            html.Div(
                f"Fields: {', '.join(str(c) for c in df.columns[:8])}",
                className="pc-muted",
            ),
        ],
        className="pc-card",
    )
