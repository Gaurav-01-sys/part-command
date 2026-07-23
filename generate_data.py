import pandas as pd
import numpy as np
import random
from datetime import datetime, timedelta
import os

random.seed(42)
np.random.seed(42)

# ── helpers ──────────────────────────────────────────────────────────────────
def rand_date(start, end):
    return start + timedelta(days=random.randint(0, (end - start).days))

def fmt(d): return d.strftime("%Y-%m-%d")

START = datetime(2022, 1, 1)
NOW   = datetime(2024, 12, 31)

REGIONS   = ["North America", "EMEA", "APAC", "LATAM", "ANZ"]
TIERS     = ["Gold", "Silver", "Bronze"]
TIER_W    = [0.2, 0.35, 0.45]
SOLUTIONS = ["Data & AI", "Modern Work", "Security", "Azure Infrastructure", "Business Applications"]
SKUS      = ["Enterprise", "Premium", "Standard", "Developer"]

# ── 1. MICROSOFT ─────────────────────────────────────────────────────────────

# partners.csv
partner_names = [
    "Nexus Analytics","CloudBridge Consulting","DataPeak Solutions","Vertex Systems",
    "Pinnacle Tech","Axiom Cloud","Quantum Leap IT","SkyNet Integrations","BluePath Partners",
    "Elevate Digital","TrueNorth Technologies","Meridian Data","CoreEdge Solutions",
    "Synapse Consulting","Horizon AI","Catalyst Cloud","Apex Innovations","Luminary Tech",
    "Stellar Systems","Vanguard IT","Orbit Partners","Zenith Solutions","Prism Analytics",
    "Insight Bridge","Fusion Data","Matrix Cloud","Clarity Systems","Nexgen Consulting",
    "Pulse Technologies","Dynamic Edge"
]

partners = []
for i, name in enumerate(partner_names):
    pid = f"PRT-{1000+i}"
    tier = random.choices(TIERS, weights=TIER_W)[0]
    enroll = rand_date(START, datetime(2023, 6, 1))
    partners.append({
        "partner_id": pid, "partner_name": name, "mpn_id": f"MPN{random.randint(1000000,9999999)}",
        "tier": tier, "region": random.choice(REGIONS),
        "solution_area": random.choice(SOLUTIONS),
        "contact_email": f"contact@{name.lower().replace(' ','')}.com",
        "contact_phone": f"+1-{random.randint(200,999)}-{random.randint(100,999)}-{random.randint(1000,9999)}",
        "enrolled_date": fmt(enroll), "status": random.choices(["Active","Inactive"],[0.85,0.15])[0],
        "country": random.choice(["USA","UK","Germany","India","Australia","Canada","Singapore","Brazil"]),
        "employee_count": random.choice([10,25,50,100,250,500,1000]),
        "annual_revenue_usd": random.randint(500_000, 50_000_000)
    })

df_partners = pd.DataFrame(partners)
df_partners.to_csv("/home/claude/partner-command-center/data/microsoft/partners.csv", index=False)

# certifications.csv
CERTS = [
    "Azure Solutions Architect Expert","Azure Data Engineer Associate",
    "Azure AI Engineer Associate","Microsoft 365 Certified: Enterprise Administrator",
    "Power Platform Solution Architect","Security Operations Analyst Associate",
    "Azure DevOps Engineer Expert","Data Analyst Associate",
    "Azure Database Administrator Associate","Cybersecurity Architect Expert"
]
certs = []
for p in partners:
    n = random.randint(1, 4)
    chosen = random.sample(CERTS, n)
    for c in chosen:
        issued = rand_date(datetime(2022,1,1), datetime(2024,6,1))
        expiry = issued + timedelta(days=365*2)
        status = "Expired" if expiry < NOW else ("Expiring Soon" if (expiry - NOW).days < 90 else "Valid")
        certs.append({
            "cert_id": f"CERT-{random.randint(10000,99999)}",
            "partner_id": p["partner_id"], "partner_name": p["partner_name"],
            "certification_name": c,
            "issued_date": fmt(issued), "expiry_date": fmt(expiry),
            "status": status, "issuing_body": "Microsoft",
            "exam_id": f"AZ-{random.choice([104,204,305,400,500,700,900,204])}"
        })

pd.DataFrame(certs).to_csv("/home/claude/partner-command-center/data/microsoft/certifications.csv", index=False)

# deals.csv
STAGES   = ["Prospect","Qualification","Proposal","Negotiation","Closed-Won","Closed-Lost"]
STAGE_W  = [0.15, 0.20, 0.20, 0.15, 0.20, 0.10]
deals = []
for i in range(120):
    p = random.choice(partners)
    stage = random.choices(STAGES, weights=STAGE_W)[0]
    created = rand_date(datetime(2023,1,1), datetime(2024,10,1))
    close_est = created + timedelta(days=random.randint(30,180))
    deals.append({
        "deal_id": f"DEAL-{5000+i}",
        "partner_id": p["partner_id"], "partner_name": p["partner_name"],
        "deal_name": f"{random.choice(['Digital Transformation','Cloud Migration','AI Modernization','Security Overhaul','Data Platform'])} - {p['partner_name'][:10]}",
        "stage": stage, "solution_area": random.choice(SOLUTIONS),
        "deal_value_usd": random.randint(10_000, 2_000_000),
        "co_sell": random.choice(["Yes","No"]),
        "created_date": fmt(created), "estimated_close_date": fmt(close_est),
        "deal_owner": random.choice(["Alice Kim","Bob Patel","Carlos Rivera","Diana Müller","Ethan Ng"]),
        "region": p["region"]
    })

pd.DataFrame(deals).to_csv("/home/claude/partner-command-center/data/microsoft/deals.csv", index=False)

print("✅ Microsoft data generated")

# ── 2. SNOWFLAKE ─────────────────────────────────────────────────────────────

# fact_deals.csv (snowflake mart view)
fact_deals = pd.read_csv("/home/claude/partner-command-center/data/microsoft/deals.csv")
fact_deals["revenue_recognized"] = (fact_deals["stage"] == "Closed-Won").astype(int) * fact_deals["deal_value_usd"]
fact_deals["days_to_close"] = random.randint(30, 150)
fact_deals["pipeline_weight"] = fact_deals["stage"].map({
    "Prospect":0.05,"Qualification":0.15,"Proposal":0.35,
    "Negotiation":0.65,"Closed-Won":1.0,"Closed-Lost":0.0})
fact_deals["weighted_value"] = (fact_deals["deal_value_usd"] * fact_deals["pipeline_weight"]).round(0)
fact_deals.to_csv("/home/claude/partner-command-center/data/snowflake/fact_deals.csv", index=False)

# dim_partners.csv
dim_partners = df_partners.copy()
dim_partners["tier_rank"] = dim_partners["tier"].map({"Gold":1,"Silver":2,"Bronze":3})
dim_partners["active_flag"] = (dim_partners["status"] == "Active").astype(int)
dim_partners["years_enrolled"] = ((NOW - pd.to_datetime(dim_partners["enrolled_date"])).dt.days / 365).round(1)
dim_partners.to_csv("/home/claude/partner-command-center/data/snowflake/dim_partners.csv", index=False)

print("✅ Snowflake data generated")

# ── 3. DATABRICKS ────────────────────────────────────────────────────────────

# product_usage.csv
products = ["Databricks Runtime","Delta Lake","MLflow","Unity Catalog","Databricks SQL","Workflows"]
usage_rows = []
months = pd.date_range("2023-01-01","2024-12-01", freq="MS")
for p in partners[:20]:   # top 20 partners have usage
    for prod in random.sample(products, random.randint(1,4)):
        for m in months:
            dbu = round(random.uniform(50, 5000), 2)
            rate = {"Databricks Runtime":0.55,"Delta Lake":0.22,"MLflow":0.10,
                    "Unity Catalog":0.30,"Databricks SQL":0.45,"Workflows":0.15}.get(prod, 0.30)
            cost = round(dbu * rate, 2)
            usage_rows.append({
                "partner_id": p["partner_id"], "partner_name": p["partner_name"],
                "product": prod, "sku": random.choice(SKUS),
                "month": m.strftime("%Y-%m"),
                "dbu_consumed": dbu, "cost_usd": cost,
                "overage_flag": "Yes" if dbu > 3000 else "No",
                "cluster_hours": round(dbu / 4, 1)
            })

pd.DataFrame(usage_rows).to_csv("/home/claude/partner-command-center/data/databricks/product_usage.csv", index=False)

# partner_health_scores.csv
health = []
for p in partners:
    cert_count  = len([c for c in certs if c["partner_id"] == p["partner_id"]])
    deal_count  = len([d for d in deals if d["partner_id"] == p["partner_id"]])
    usage_count = len([u for u in usage_rows if u["partner_id"] == p["partner_id"]])
    score = min(100, round(cert_count*8 + deal_count*6 + usage_count*0.5 + random.uniform(-5,15), 1))
    churn_risk = "High" if score < 30 else ("Medium" if score < 60 else "Low")
    deal_score = round(random.uniform(0.4, 0.95), 2)
    health.append({
        "partner_id": p["partner_id"], "partner_name": p["partner_name"],
        "tier": p["tier"], "region": p["region"],
        "health_score": score, "churn_risk": churn_risk,
        "deal_propensity_score": deal_score,
        "cert_count": cert_count, "active_deals": deal_count,
        "dbu_months_active": usage_count,
        "last_scored": fmt(rand_date(datetime(2024,10,1), NOW)),
        "recommendation": random.choice([
            "Upsell to Gold tier","Schedule QBR","Offer training vouchers",
            "Assign dedicated PDM","Review co-sell pipeline","Enroll in FastTrack"])
    })

pd.DataFrame(health).to_csv("/home/claude/partner-command-center/data/databricks/partner_health_scores.csv", index=False)

print("✅ Databricks data generated")

# ── 4. dbt ───────────────────────────────────────────────────────────────────

dbt_models = [
    "stg_microsoft__partners","stg_microsoft__deals","stg_microsoft__certifications",
    "stg_databricks__usage","int_partner_activity","int_deal_pipeline",
    "fct_partner_revenue","fct_deal_summary","dim_partners","dim_certifications",
    "mart_partner_health","mart_pipeline_overview"
]
dbt_rows = []
for m in dbt_models:
    last_run = rand_date(datetime(2024,11,1), NOW)
    duration = random.randint(4, 180)
    rows_out = random.randint(100, 50000)
    dbt_rows.append({
        "model_name": m,
        "schema": "stg" if m.startswith("stg") else ("int" if m.startswith("int") else ("fct" if m.startswith("fct") else ("dim" if m.startswith("dim") else "mart"))),
        "status": random.choices(["success","error","skipped"],[0.88,0.07,0.05])[0],
        "last_run_at": fmt(last_run),
        "duration_seconds": duration,
        "rows_affected": rows_out,
        "tests_passed": random.randint(3,12),
        "tests_failed": random.randint(0,2),
        "materialization": random.choice(["table","incremental","view","ephemeral"]),
        "source_freshness": random.choice(["Pass","Warn","Error"])
    })

pd.DataFrame(dbt_rows).to_csv("/home/claude/partner-command-center/data/dbt/model_run_results.csv", index=False)
print("✅ dbt data generated")

# ── 5. COALESCE ──────────────────────────────────────────────────────────────

coalesce_nodes = [
    ("src_partners","Source"), ("src_deals","Source"), ("src_certifications","Source"),
    ("src_usage","Source"), ("stg_partners","Staging"), ("stg_deals","Staging"),
    ("stg_certifications","Staging"), ("stg_usage","Staging"),
    ("int_partner_metrics","Transform"), ("int_deal_pipeline","Transform"),
    ("fct_revenue","Publish"), ("mart_partner_360","Publish")
]
pipe_rows = []
for node, node_type in coalesce_nodes:
    run_ts = rand_date(datetime(2024,11,1), NOW)
    pipe_rows.append({
        "node_name": node, "node_type": node_type,
        "database": "PARTNER_DW", "schema": node_type.upper(),
        "run_status": random.choices(["Success","Failed","Running"],[0.87,0.08,0.05])[0],
        "last_run_at": fmt(run_ts),
        "row_count": random.randint(200,100000),
        "execution_time_sec": random.randint(2,300),
        "column_count": random.randint(5,25),
        "lineage_parents": random.randint(0,3),
        "lineage_children": random.randint(0,4),
        "owner": random.choice(["data_team","analytics_eng","bi_team"]),
        "description": f"Coalesce node for {node.replace('_',' ')} pipeline"
    })

pd.DataFrame(pipe_rows).to_csv("/home/claude/partner-command-center/data/coalesce/pipeline_runs.csv", index=False)
print("✅ Coalesce data generated")

print("\n🎉 All synthetic data files generated successfully!")
for root, dirs, files in os.walk("/home/claude/partner-command-center/data"):
    for f in files:
        path = os.path.join(root, f)
        size = os.path.getsize(path)
        print(f"  {path.replace('/home/claude/partner-command-center/',''):<55} {size:>7,} bytes")
