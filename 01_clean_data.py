"""
01_clean_data.py
Amazon India Sales: cleaning + star-schema build.

Reads the raw Kaggle CSVs, applies documented cleaning rules and writes
analysis-ready tables to data/cleaned/:

    fact_orders.csv     one row per order LINE (grain = Amazon "index"); product attributes live in dim_products
    dim_products.csv    one row per SKU
    dim_state.csv       one row per cleaned ship-state + official zone
    dim_date.csv        calendar table (for SQL and Power BI time intelligence)
    stock_by_style.csv  current stock aggregated to style level
    data_quality_log.csv  every rule applied and how many rows it touched

Usage (from the project root):
    python python/01_clean_data.py
    python python/01_clean_data.py --raw path/to/raw --out path/to/cleaned
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------
# Business rules (edit here, not buried in the code below)
# --------------------------------------------------------------------------
STATE_FIXES = {
    "NEW DELHI": "DELHI",
    "RAJSHTHAN": "RAJASTHAN", "RAJSTHAN": "RAJASTHAN", "RJ": "RAJASTHAN",
    "PB": "PUNJAB", "PUNJAB/MOHALI/ZIRAKPUR": "PUNJAB",
    "NL": "NAGALAND", "AR": "ARUNACHAL PRADESH",
    "ORISSA": "ODISHA", "PONDICHERRY": "PUDUCHERRY",
    "DADRA AND NAGAR": "DADRA AND NAGAR HAVELI",
    "APO": "UNKNOWN",  # military postal code, not a real state
}

# Based on India's Zonal Councils (+ North Eastern Council); island territories assigned to South by convention
ZONES = {
    "North": ["DELHI", "HARYANA", "PUNJAB", "HIMACHAL PRADESH", "JAMMU & KASHMIR",
              "LADAKH", "CHANDIGARH", "RAJASTHAN"],
    "Central": ["UTTAR PRADESH", "UTTARAKHAND", "MADHYA PRADESH", "CHHATTISGARH"],
    "East": ["WEST BENGAL", "ODISHA", "BIHAR", "JHARKHAND"],
    "West": ["MAHARASHTRA", "GUJARAT", "GOA", "DADRA AND NAGAR HAVELI"],
    "South": ["KARNATAKA", "TAMIL NADU", "TELANGANA", "ANDHRA PRADESH", "KERALA",
              "PUDUCHERRY", "ANDAMAN & NICOBAR", "LAKSHADWEEP"],
    "North-East": ["ASSAM", "MANIPUR", "MEGHALAYA", "SIKKIM", "NAGALAND", "TRIPURA",
                   "ARUNACHAL PRADESH", "MIZORAM"],
}
STATE_TO_ZONE = {s: z for z, states in ZONES.items() for s in states}

# Status -> business group. "Completed" = revenue we expect to keep.
def status_group(s: str) -> str:
    if s == "Cancelled":
        return "Cancelled"
    if s.startswith("Pending"):
        return "Pending"
    if s in ("Shipped - Returned to Seller", "Shipped - Returning to Seller",
             "Shipped - Rejected by Buyer"):
        return "Returned"
    if s in ("Shipped - Lost in Transit", "Shipped - Damaged"):
        return "Lost/Damaged"
    return "Completed"  # Shipped, Delivered, Picked Up, Out for Delivery, Shipping


LOG = []
def log(step, rule, rows):
    LOG.append({"step": step, "rule": rule, "rows_affected": int(rows)})
    print(f"[{step:>4}] {rule}: {int(rows):,}")


def title_case_state(s: str) -> str:
    if s == "UNKNOWN":
        return "Unknown"
    # keep '&' and handle small words
    return " ".join(w.capitalize() if w != "&" else w for w in s.split())


def main(raw: Path, out: Path):
    out.mkdir(parents=True, exist_ok=True)

    # ---------------- Load ----------------
    df = pd.read_csv(raw / "Amazon Sale Report.csv", low_memory=False)
    n_raw = len(df)
    print(f"Loaded {n_raw:,} rows")

    # 1. Column hygiene
    df.columns = df.columns.str.strip()
    df = df.drop(columns=["Unnamed: 22"])
    log(1, "Stripped column names (e.g. 'Sales Channel ') and dropped empty 'Unnamed: 22'", 0)
    df = df.rename(columns={
        "index": "order_line_id", "Order ID": "order_id", "Date": "order_date",
        "Status": "status", "Fulfilment": "fulfilment", "Sales Channel": "sales_channel",
        "ship-service-level": "ship_service_level", "Style": "style", "SKU": "sku",
        "Category": "category", "Size": "size", "ASIN": "asin",
        "Courier Status": "courier_status", "Qty": "qty", "currency": "currency",
        "Amount": "amount", "ship-city": "city", "ship-state": "state",
        "ship-postal-code": "postal_code", "ship-country": "country",
        "promotion-ids": "promotion_ids", "B2B": "is_b2b", "fulfilled-by": "fulfilled_by",
    })

    # 2. Exact duplicate lines (ignoring the row index)
    dup_mask = df.drop(columns="order_line_id").duplicated(keep="first")
    dup_amount = df.loc[dup_mask, "amount"].sum()
    log(2, "Exact duplicate order lines dropped (kept first)", dup_mask.sum())
    df = df[~dup_mask].copy()

    # 3. Dates (source format is mm-dd-yy)
    df["order_date"] = pd.to_datetime(df["order_date"], format="%m-%d-%y")
    df["order_month"] = df["order_date"].dt.to_period("M").dt.to_timestamp()
    log(3, "Parsed order_date from mm-dd-yy; added order_month (first day of month)", len(df))

    # 4. Text standardisation
    for c in ["status", "fulfilment", "sales_channel", "ship_service_level", "style", "sku",
              "category", "size", "courier_status", "city"]:
        df[c] = df[c].astype("string").str.strip()
    n_cat = (df["category"] != df["category"].str.title()).sum()
    df["category"] = df["category"].str.title()
    df["style"] = df["style"].str.upper()
    log(4, "Category standardised to Title Case (e.g. 'kurta' -> 'Kurta')", n_cat)
    df["courier_status"] = df["courier_status"].fillna("Unknown")
    df["city"] = df["city"].str.title()

    # 5. State standardisation + zone
    raw_state = df["state"].astype("string").str.strip().str.upper().fillna("UNKNOWN")
    fixed = raw_state.replace(STATE_FIXES)
    # count rows whose raw text differs from the canonical UPPER-case name (case/typo/abbreviation)
    changed = (df["state"].astype("string").str.strip().notna()
               & (df["state"].astype("string").str.strip() != fixed)).sum()
    df["state"] = fixed.map(title_case_state)
    log(5, "ship-state standardised (case, typos, abbreviations, Orissa->Odisha etc.)", changed)
    zone_lookup = {title_case_state(k): v for k, v in STATE_TO_ZONE.items()}
    df["zone"] = df["state"].map(zone_lookup).fillna("Unknown")
    log(6, "State mapped to official zone; rows left 'Unknown' (no/invalid state)", (df["zone"] == "Unknown").sum())

    # 7. Postal code as text
    df["postal_code"] = df["postal_code"].astype("Int64").astype("string")

    # 8. Redundant / constant columns
    assert ((df["fulfilment"] == "Merchant") == (df["fulfilled_by"] == "Easy Ship")).all()
    df["has_promotion"] = df["promotion_ids"].notna().astype(int)
    log(7, "Replaced messy promotion_ids text with has_promotion flag (0/1)", df["has_promotion"].sum())
    df = df.drop(columns=["promotion_ids", "fulfilled_by", "currency", "country"])
    log(8, "Dropped fulfilled_by (identical to fulfilment), currency (all INR) and country (all IN)", 0)

    # 9. Status groups
    df["status_group"] = df["status"].map(status_group)
    df["is_b2b"] = df["is_b2b"].astype(int)

    # 10. Amount handling
    df["amount_was_missing"] = df["amount"].isna().astype(int)
    log(9, "amount was NULL (set to 0, flagged in amount_was_missing)", df["amount_was_missing"].sum())
    df["amount"] = df["amount"].fillna(0.0).round(2)
    completed = df["status_group"].eq("Completed")
    df["net_revenue"] = np.where(completed, df["amount"], 0.0)
    df["net_units"] = np.where(completed, df["qty"], 0)
    df["zero_value_completed"] = (completed & (df["amount"] == 0)).astype(int)
    log(10, "Completed lines with zero/missing amount (flagged zero_value_completed; kept)", df["zero_value_completed"].sum())
    # priced_units: units on completed lines that carry a price. Use it for average-selling-price
    # so free/zero-value lines do not drag prices down.
    df["priced_units"] = np.where(completed & (df["amount"] > 0), df["qty"], 0)
    log(10.1, "Non-Amazon channel lines (multi-channel fulfilment): all zero-amount, kept but excluded from fulfilment analysis",
        (df["sales_channel"] == "Non-Amazon").sum())
    log(10.2, "Completed lines with qty = 0 (kept; contribute no units)", (completed & (df["qty"] == 0)).sum())
    log(10.3, "Return statuses exist only for Merchant fulfilment: Amazon-fulfilled returns are NOT in this report (do not compare return rates across fulfilment)",
        df["status_group"].eq("Returned").sum())
    log(10.4, "has_promotion is not a causal variable: 98% of cancelled lines have no promotion ID (recorded after confirmation)",
        ((df["status_group"] == "Cancelled") & (df["has_promotion"] == 0)).sum())

    # ---------------- Fact table ----------------
    fact_cols = [
        "order_line_id", "order_id", "order_date", "order_month", "status", "status_group",
        "fulfilment", "ship_service_level", "sales_channel", "courier_status", "is_b2b",
        "sku", "state", "city", "postal_code",
        "qty", "amount", "net_units", "priced_units", "net_revenue", "has_promotion",
        "amount_was_missing", "zero_value_completed",
    ]
    fact = df[fact_cols].sort_values("order_line_id")
    fact.to_csv(out / "fact_orders.csv", index=False, lineterminator="\n", date_format="%Y-%m-%d")

    # ---------------- Dimensions ----------------
    prod = (df.groupby("sku", as_index=False)
              .agg(style=("style", "first"), category=("category", "first"),
                   size=("size", "first"),
                   asin=("asin", lambda s: s.mode().iat[0])))
    log(11, "dim_products: SKUs with >1 ASIN resolved to most frequent ASIN",
        (df.groupby("sku")["asin"].nunique() > 1).sum())
    prod.to_csv(out / "dim_products.csv", index=False, lineterminator="\n")

    dim_state = (df[["state", "zone"]].drop_duplicates().sort_values("state"))
    dim_state.to_csv(out / "dim_state.csv", index=False, lineterminator="\n")

    days = pd.date_range(df["order_date"].min(), df["order_date"].max(), freq="D")
    dim_date = pd.DataFrame({"date_key": days})
    dim_date["year"] = dim_date["date_key"].dt.year
    dim_date["month_num"] = dim_date["date_key"].dt.month
    dim_date["month_name"] = dim_date["date_key"].dt.strftime("%b")
    dim_date["month_start"] = dim_date["date_key"].dt.to_period("M").dt.to_timestamp()
    dim_date["week_start"] = dim_date["date_key"] - pd.to_timedelta(dim_date["date_key"].dt.weekday, unit="D")
    dim_date["day_name"] = dim_date["date_key"].dt.strftime("%a")
    dim_date["is_weekend"] = (dim_date["date_key"].dt.weekday >= 5).astype(int)
    dim_date.to_csv(out / "dim_date.csv", index=False, lineterminator="\n", date_format="%Y-%m-%d")

    # ---------------- Stock ----------------
    st = pd.read_csv(raw / "Sale Report.csv")
    n_st = len(st)
    st = st.dropna(subset=["Design No.", "Stock"]).copy()
    st["Design No."] = st["Design No."].str.strip().str.upper()
    log(12, "Stock file: rows without Design No./Stock removed", n_st - len(st))
    d = st.drop(columns="index").duplicated().sum()
    st = st.drop_duplicates(subset=[c for c in st.columns if c != "index"])
    log(13, "Stock file: exact duplicate rows removed (SKU Code contains Excel '#REF!' errors, so Design No. is used as key)", d)
    stock = (st.groupby("Design No.", as_index=False)
               .agg(stock_units=("Stock", "sum"), stock_skus=("Stock", "size"))
               .rename(columns={"Design No.": "style"}))
    stock["stock_units"] = stock["stock_units"].astype(int)
    stock.to_csv(out / "stock_by_style.csv", index=False, lineterminator="\n")

    # ---------------- Reconciliation ----------------
    pd.DataFrame(LOG).to_csv(out / "data_quality_log.csv", index=False, lineterminator="\n")
    print("\n--- RECONCILIATION (match these in your Excel pivot) ---")
    print(f"Raw rows: {n_raw:,} | clean rows: {len(fact):,} | dropped duplicates: {n_raw-len(fact)}")
    print(f"Gross booked amount (all statuses): {fact['amount'].sum():,.2f}")
    print(fact.groupby("status_group")["amount"].agg(["count", "sum"]).round(2))
    print(f"Net revenue (Completed): {fact['net_revenue'].sum():,.2f}")
    print(f"Distinct orders: {fact['order_id'].nunique():,}")
    print(f"Date range: {fact['order_date'].min().date()} -> {fact['order_date'].max().date()}")


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", type=Path, default=root / "data" / "raw")
    ap.add_argument("--out", type=Path, default=root / "data" / "cleaned")
    a = ap.parse_args()
    main(a.raw, a.out)
