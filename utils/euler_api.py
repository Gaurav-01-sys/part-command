"""
utils/euler_api.py
-------------------
Adapter layer that pulls live partner data from EULER (eulerapp.com) and
reshapes it into the exact same pandas DataFrame columns that data_engine.py
already expects from the local CSVs. This means nothing downstream (Dash/
Gradio tabs, the Claude query engine, charts) needs to change - only where
the data comes from.

SETUP REQUIRED BEFORE THIS WILL WORK:
1. Log into your EULER account -> Settings -> Integrations/API -> generate
   an API key (ask an admin if you don't see this option).
2. Set these environment variables (e.g. in a .env file):
       EULER_API_BASE=https://api.eulerapp.com/v1     <- confirm real base URL
       EULER_API_KEY=your-key-here
3. Confirm the real endpoint paths and field names against EULER's API docs
   and fix the ENDPOINTS dict + the *_normalize() functions below - the
   paths and field names here are placeholders until you have the docs
   in front of you.

USAGE:
    from utils.euler_api import fetch_partners, fetch_deals, EULER_CONFIGURED
    if EULER_CONFIGURED:
        ms_partners = fetch_partners()
    else:
        ms_partners = pd.read_csv(...)   # fallback to sample data
"""

import os
import requests
import pandas as pd

EULER_API_BASE = os.environ.get("EULER_API_BASE", "https://api.eulerapp.com/v1")
EULER_API_KEY = os.environ.get("EULER_API_KEY", "")

EULER_CONFIGURED = bool(EULER_API_KEY)

# TODO: confirm these paths against EULER's actual API reference
ENDPOINTS = {
    "partners": "/partners",
    "deals": "/deals",
    "certifications": "/certifications",
}

_SESSION = requests.Session()
_SESSION.headers.update({
    "Authorization": f"Bearer {EULER_API_KEY}",
    "Accept": "application/json",
})


def _get(path, params=None, timeout=15):
    """Thin GET wrapper with clear error messages instead of silent failure."""
    if not EULER_CONFIGURED:
        raise RuntimeError(
            "EULER_API_KEY is not set. Add it to your environment/.env before "
            "calling live EULER endpoints."
        )
    url = f"{EULER_API_BASE}{path}"
    resp = _SESSION.get(url, params=params, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _paginate(path, params=None, items_key="data", cursor_key="next_cursor"):
    """
    Generic pagination helper - many PRM APIs return {data: [...], next_cursor: ...}.
    Adjust items_key/cursor_key once you see a real response payload.
    """
    params = dict(params or {})
    results = []
    while True:
        payload = _get(path, params=params)
        batch = payload.get(items_key, payload if isinstance(payload, list) else [])
        results.extend(batch)
        cursor = payload.get(cursor_key) if isinstance(payload, dict) else None
        if not cursor:
            break
        params["cursor"] = cursor
    return results


# ── Partners ──────────────────────────────────────────────────────────────────
def fetch_partners() -> pd.DataFrame:
    """
    Returns a DataFrame matching data/microsoft/partners.csv columns:
    partner_id, partner_name, mpn_id, tier, region, solution_area,
    contact_email, contact_phone, enrolled_date, status, country,
    employee_count, annual_revenue_usd
    """
    raw = _paginate(ENDPOINTS["partners"])
    df = pd.DataFrame(raw)

    # TODO: map EULER's real field names (left) to our schema (right) once
    # you can see an actual API response. These are best-guess placeholders.
    rename_map = {
        "id": "partner_id",
        "name": "partner_name",
        "microsoft_partner_id": "mpn_id",
        "partner_tier": "tier",
        "region": "region",
        "practice_area": "solution_area",
        "email": "contact_email",
        "phone": "contact_phone",
        "created_at": "enrolled_date",
        "status": "status",
        "country": "country",
        "employees": "employee_count",
        "revenue": "annual_revenue_usd",
    }
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})

    expected_cols = ["partner_id", "partner_name", "mpn_id", "tier", "region",
                      "solution_area", "contact_email", "contact_phone",
                      "enrolled_date", "status", "country", "employee_count",
                      "annual_revenue_usd"]
    for col in expected_cols:
        if col not in df.columns:
            df[col] = None
    return df[expected_cols]


# ── Deals ─────────────────────────────────────────────────────────────────────
def fetch_deals() -> pd.DataFrame:
    """
    Returns a DataFrame matching data/microsoft/deals.csv columns:
    deal_id, partner_id, partner_name, deal_name, stage, solution_area,
    deal_value_usd, co_sell, created_date, estimated_close_date,
    deal_owner, region
    """
    raw = _paginate(ENDPOINTS["deals"])
    df = pd.DataFrame(raw)

    rename_map = {
        "id": "deal_id",
        "partner_id": "partner_id",
        "partner_name": "partner_name",
        "name": "deal_name",
        "stage": "stage",
        "practice_area": "solution_area",
        "value": "deal_value_usd",
        "co_sell": "co_sell",
        "created_at": "created_date",
        "close_date": "estimated_close_date",
        "owner": "deal_owner",
        "region": "region",
    }
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})

    expected_cols = ["deal_id", "partner_id", "partner_name", "deal_name", "stage",
                      "solution_area", "deal_value_usd", "co_sell", "created_date",
                      "estimated_close_date", "deal_owner", "region"]
    for col in expected_cols:
        if col not in df.columns:
            df[col] = None
    return df[expected_cols]


# ── Certifications ────────────────────────────────────────────────────────────
def fetch_certifications() -> pd.DataFrame:
    """
    Returns a DataFrame matching data/microsoft/certifications.csv columns:
    cert_id, partner_id, partner_name, certification_name, issued_date,
    expiry_date, status, issuing_body, exam_id
    """
    raw = _paginate(ENDPOINTS["certifications"])
    df = pd.DataFrame(raw)

    rename_map = {
        "id": "cert_id",
        "partner_id": "partner_id",
        "partner_name": "partner_name",
        "name": "certification_name",
        "issued_at": "issued_date",
        "expires_at": "expiry_date",
        "status": "status",
        "issuer": "issuing_body",
        "exam_code": "exam_id",
    }
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})

    expected_cols = ["cert_id", "partner_id", "partner_name", "certification_name",
                      "issued_date", "expiry_date", "status", "issuing_body", "exam_id"]
    for col in expected_cols:
        if col not in df.columns:
            df[col] = None
    return df[expected_cols]
