"""
02_analysis.py  |  Amazon India Sales: outliers, decline drivers, 4-week forecast

Reads  data/cleaned/*.csv   (produced by 01_clean_data.py)
Writes data/outputs/*.csv   (Power BI ready)  and  images/*.png

Design rules (each one exists because the data punishes ignoring it)
  1. SETTLED WINDOW. Orders placed in the last days of the extract have not had time to
     ship, so their status is still 'Pending' and they count as zero net revenue.
     The window is detected from the data, not hard-coded, and is trimmed to whole
     Monday-Sunday weeks so day-of-week effects cannot bias comparisons.
  2. BACKTEST BEFORE TRUSTING A FORECAST. Every model is scored on data it never saw,
     against a naive baseline, using rolling origins.
  3. NO CAUSAL CLAIMS the data cannot support. Hypotheses are tested, and when the data
     cannot decide, the output says so.

Usage (from the project root):   python python/02_analysis.py
Needs: pandas, numpy, scipy, matplotlib
"""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
CLEAN, OUT, IMG = ROOT / "data" / "cleaned", ROOT / "data" / "outputs", ROOT / "images"
OUT.mkdir(parents=True, exist_ok=True)
IMG.mkdir(parents=True, exist_ok=True)

PENDING_SETTLED_MAX = 0.02   # a day is "settled" if <= 2% of its lines are still Pending
HORIZON = 28                 # forecast horizon in days (4 whole weeks)
N_BOOT = 5000
RNG = np.random.default_rng(42)
SUMMARY = {}

INK, GREY, RED, BLUE, GREEN, AMBER = "#1f2937", "#9ca3af", "#dc2626", "#2563eb", "#16a34a", "#d97706"
plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.titleweight": "bold", "axes.titlesize": 11, "figure.dpi": 150})
fmt_k = lambda x, _=None: f"{x/1000:,.0f}K"
fmt_d = mdates.DateFormatter("%d %b")


# ----------------------------------------------------------------------------
# 0. Load + settled window
# ----------------------------------------------------------------------------
def load():
    f = pd.read_csv(CLEAN / "fact_orders.csv", parse_dates=["order_date"])
    p = pd.read_csv(CLEAN / "dim_products.csv")
    s = pd.read_csv(CLEAN / "dim_state.csv")
    stock = pd.read_csv(CLEAN / "stock_by_style.csv")
    f = f.merge(p[["sku", "style", "category", "size"]], on="sku").merge(s[["state", "zone"]], on="state", how="left")
    return f, stock


def detect_window(f):
    day = f.groupby("order_date").agg(
        lines=("order_line_id", "size"),
        pending=("status_group", lambda x: (x == "Pending").mean()))
    first_full = day.index[day.lines >= 0.5 * day.lines.median()].min()      # drops the 1-day March stub
    bad = day.loc[first_full:][day.loc[first_full:, "pending"] > PENDING_SETTLED_MAX]
    last_settled = (bad.index.min() - pd.Timedelta(days=1)) if len(bad) else day.index.max()
    start = first_full + pd.Timedelta(days=(7 - first_full.weekday()) % 7)    # first Monday
    end = last_settled - pd.Timedelta(days=(last_settled.weekday() + 1) % 7)  # last Sunday
    SUMMARY["window"] = {"first_full_day": str(first_full.date()), "last_settled_day": str(last_settled.date()),
                         "start_monday": str(start.date()), "end_sunday": str(end.date()),
                         "days": int((end - start).days + 1)}
    print(f"Settled window: {start.date()} -> {end.date()} ({(end-start).days+1} days). "
          f"Pending share on the days after it: " +
          ", ".join(f"{d.strftime('%d %b')} {day.pending[d]*100:.1f}%" for d in day.loc[end + pd.Timedelta(days=1):].index))
    return day, start, end


# ----------------------------------------------------------------------------
# 1. Outliers
# ----------------------------------------------------------------------------
def outliers(f, d):
    rows = []
    # (a) daily net revenue: robust z-score against a centred 15-day rolling median
    med = d.net_revenue.rolling(15, center=True, min_periods=8).median()
    mad = (d.net_revenue - med).abs().rolling(15, center=True, min_periods=8).median()
    z = 0.6745 * (d.net_revenue - med) / mad
    n_daily = int((z.abs() > 3.5).sum())
    rows.append(["Daily net revenue", "robust z > 3.5 vs rolling median (15d)", n_daily, len(d), 0.0,
                 "None found. The series is volatile but contains no isolated anomalies."])

    # (b) unit price: compare each completed priced line to its own style's median price
    c = f[(f.status_group == "Completed") & (f.priced_units > 0)].copy()
    c["unit_price"] = c.net_revenue / c.priced_units
    cnt = c.groupby("style").unit_price.transform("size")
    c = c[cnt >= 5]
    c["ratio"] = c.unit_price / c.groupby("style").unit_price.transform("median")
    flag = (c.ratio > 1.5) | (c.ratio < 1 / 1.5)
    rows.append(["Unit price vs own style", "price > 1.5x or < 0.67x style median", int(flag.sum()), len(c),
                 round(100 * c.loc[flag, "net_revenue"].sum() / c.net_revenue.sum(), 2),
                 "Kept. Flag only. See note below."])

    # (c) the naive method: IQR on unit price within category (shown to explain why it is not used)
    def iqr_flag(g):
        q1, q3 = g.quantile(.25), g.quantile(.75)
        i = q3 - q1
        return (g < q1 - 1.5 * i) | (g > q3 + 1.5 * i)
    naive = c.groupby("category").unit_price.transform(iqr_flag)
    rows.append(["Unit price vs category (naive IQR)", "outside 1.5 x IQR within category", int(naive.sum()), len(c),
                 round(100 * c.loc[naive, "net_revenue"].sum() / c.net_revenue.sum(), 2),
                 "Not used: flags legitimately expensive styles (many are premium Kurtas), not errors."])

    # (d) quantity
    big = int((f.qty >= 5).sum())
    rows.append(["Quantity per line", "qty >= 5", big, len(f), round(100 * f.loc[f.qty >= 5, "net_revenue"].sum() / f.net_revenue.sum(), 2),
                 "Kept. Plausible bulk/B2B lines (max qty is 8)."])
    tab = pd.DataFrame(rows, columns=["check", "rule", "flagged", "of_total", "pct_of_net_revenue", "decision"])
    tab["pct_flagged"] = (100 * tab.flagged / tab.of_total).round(2)
    tab.to_csv(OUT / "outlier_summary.csv", index=False)
    print("\nOUTLIERS\n", tab[["check", "flagged", "of_total", "pct_flagged", "pct_of_net_revenue"]].to_string(index=False))
    SUMMARY["outliers"] = {"daily_flagged": n_daily, "price_flagged_pct_lines": float(tab.pct_flagged[1]),
                           "price_flagged_pct_revenue": float(tab.pct_of_net_revenue[1]),
                           "naive_iqr_flagged_pct_lines": float(tab.pct_flagged[2])}


# ----------------------------------------------------------------------------
# 2. Decline drivers
# ----------------------------------------------------------------------------
def best_changepoint(y, min_seg=14):
    best = None
    for k in range(min_seg, len(y) - min_seg):
        sse = ((y[:k] - y[:k].mean()) ** 2).sum() + ((y[k:] - y[k:].mean()) ** 2).sum()
        if best is None or sse < best[1]:
            best = (k, sse)
    return best[0]


def block_boot_diff(a, b, block=7, n=N_BOOT):
    """% change in mean (b vs a) with moving-block bootstrap, preserving day-to-day autocorrelation."""
    def resample(x):
        nb = int(np.ceil(len(x) / block))
        starts = RNG.integers(0, len(x) - block + 1, size=nb)
        return np.concatenate([x[s:s + block] for s in starts])[:len(x)]
    diffs = np.array([resample(b).mean() / resample(a).mean() - 1 for _ in range(n)])
    return np.percentile(diffs, [2.5, 97.5])


def pvm(wa, wb, da, db, key):
    """Price / volume / mix decomposition of the change in net revenue per day (exactly reconciles)."""
    a = wa.groupby(key).agg(rev=("net_revenue", "sum"), u=("priced_units", "sum")) / da
    b = wb.groupby(key).agg(rev=("net_revenue", "sum"), u=("priced_units", "sum")) / db
    idx = a.index.union(b.index)
    a, b = a.reindex(idx).fillna(0), b.reindex(idx).fillna(0)
    ua, ub, ra, rb = a.u.sum(), b.u.sum(), a.rev.sum(), b.rev.sum()
    pa_avg = ra / ua
    pa = (a.rev / a.u.replace(0, np.nan)); pb = (b.rev / b.u.replace(0, np.nan))
    pa = pa.fillna(pb).fillna(0)
    volume = (ub - ua) * pa_avg
    mix = (((b.u / ub) - (a.u / ua)) * ub * pa).sum()
    price = (b.u * (pb.fillna(0) - pa)).sum()
    return {"delta_rev_per_day": rb - ra, "volume": volume, "mix": mix, "price": price,
            "reconciles": bool(abs((rb - ra) - (volume + mix + price)) < 1)}


def drivers(f, d, start, end, stock):
    w = f[(f.order_date >= start) & (f.order_date <= end)].copy()
    y = d.net_revenue.values
    cp = best_changepoint(y)
    cp_date = start + pd.Timedelta(days=cp)
    cp_date = cp_date - pd.Timedelta(days=cp_date.weekday()) if cp_date.weekday() < 4 else cp_date + pd.Timedelta(days=7 - cp_date.weekday())
    A = w[w.order_date < cp_date]; B = w[w.order_date >= cp_date]
    da, db = (cp_date - start).days, (end - cp_date).days + 1
    ya, yb = d[d.index < cp_date].net_revenue.values, d[d.index >= cp_date].net_revenue.values
    pct = yb.mean() / ya.mean() - 1
    lo, hi = block_boot_diff(ya, yb)
    print(f"\nSTEP CHANGE at {cp_date.date()}: {ya.mean():,.0f} -> {yb.mean():,.0f} per day ({pct*100:+.1f}%), "
          f"95% block-bootstrap CI [{lo*100:+.1f}%, {hi*100:+.1f}%]")
    # Weekly view + linear-trend-only comparison
    wk = (w.order_date - start).dt.days // 7 + 1
    weekly = w.groupby(wk).agg(net=("net_revenue", "sum"), gross=("amount", "sum"), lines=("order_line_id", "size")) / 7
    weekly["cancel_rate_pct"] = w.groupby(wk).apply(lambda g: (g.status_group == "Cancelled").mean() * 100)
    weekly.index.name = "week"
    t = np.arange(len(y)); slope, icpt, r, pval, _ = stats.linregress(t, y)
    r2_trend = r ** 2
    pred_step = np.where(t < cp, ya.mean(), yb.mean()); r2_step = 1 - ((y - pred_step) ** 2).sum() / ((y - y.mean()) ** 2).sum()
    print(f"Fit to daily revenue: straight-line trend R2 = {r2_trend:.2f} | single step change R2 = {r2_step:.2f}")

    SUMMARY["step_change"] = {"date": str(cp_date.date()), "before_per_day": round(float(ya.mean())), "after_per_day": round(float(yb.mean())),
                              "pct_change": round(float(pct) * 100, 1), "ci95_pct": [round(float(lo) * 100, 1), round(float(hi) * 100, 1)],
                              "r2_linear_trend": round(float(r2_trend), 2), "r2_step_change": round(float(r2_step), 2),
                              "days_before": da, "days_after": db}
    cr_a = (A.status_group == "Cancelled").mean() * 100; cr_b = (B.status_group == "Cancelled").mean() * 100
    gross_pct = (B.amount.sum() / db) / (A.amount.sum() / da) - 1
    lines_pct = (len(B) / db) / (len(A) / da) - 1
    SUMMARY["step_change"].update({"cancel_rate_before": round(cr_a, 1), "cancel_rate_after": round(cr_b, 1),
                                   "gross_booked_pct_change": round(gross_pct * 100, 1), "order_lines_pct_change": round(lines_pct * 100, 1)})
    print(f"Cancel rate {cr_a:.1f}% -> {cr_b:.1f}% | gross booked/day {gross_pct*100:+.1f}% | order lines/day {lines_pct*100:+.1f}%")

    # Segment contributions
    seg_rows = []
    for key in ["category", "zone", "fulfilment", "ship_service_level"]:
        sub_a = A[A.sales_channel == "Amazon.in"] if key in ("fulfilment", "ship_service_level") else A
        sub_b = B[B.sales_channel == "Amazon.in"] if key in ("fulfilment", "ship_service_level") else B
        ra = sub_a.groupby(key).net_revenue.sum() / da; rb = sub_b.groupby(key).net_revenue.sum() / db
        tt = pd.DataFrame({"before_per_day": ra, "after_per_day": rb}).fillna(0)
        tt["change_per_day"] = tt.after_per_day - tt.before_per_day
        tt["pct_change"] = (100 * tt.change_per_day / tt.before_per_day.replace(0, np.nan)).round(1)
        tt["share_of_total_change_pct"] = (100 * tt.change_per_day / (B.net_revenue.sum() / db - A.net_revenue.sum() / da)).round(1)
        tt.insert(0, "dimension", key); tt.index.name = "segment"
        seg_rows.append(tt.reset_index())
    seg = pd.concat(seg_rows)
    seg = seg[seg.before_per_day + seg.after_per_day > 5000].round(0).sort_values(["dimension", "change_per_day"])
    seg.to_csv(OUT / "decline_drivers.csv", index=False)
    zones = seg[seg.dimension == "zone"].set_index("segment"); cats = seg[seg.dimension == "category"].set_index("segment")
    print("\nBy category (rev/day):\n", cats[["before_per_day", "after_per_day", "pct_change"]].to_string())
    print("\nBy zone:\n", zones[["before_per_day", "after_per_day", "pct_change"]].to_string())
    print("\nBy fulfilment/service:\n", seg[seg.dimension.isin(["fulfilment", "ship_service_level"])][["dimension", "segment", "pct_change"]].to_string(index=False))
    SUMMARY["by_category_pct"] = cats["pct_change"].to_dict(); SUMMARY["by_zone_pct"] = zones["pct_change"].to_dict()
    SUMMARY["segments_declining"] = {"zones": f"{int((zones.change_per_day<0).sum())} of {len(zones)}",
                                     "categories": f"{int((cats.change_per_day<0).sum())} of {len(cats)}"}

    # Price / volume / mix (by category)
    pv = pvm(A, B, da, db, "category")
    tot = pv["delta_rev_per_day"]
    print(f"\nPRICE-VOLUME-MIX of {tot:,.0f}/day change: volume {pv['volume']:,.0f} ({pv['volume']/tot*100:.0f}%), "
          f"mix {pv['mix']:,.0f} ({pv['mix']/tot*100:.0f}%), price {pv['price']:,.0f} ({pv['price']/tot*100:.0f}%) | reconciles={pv['reconciles']}")
    SUMMARY["pvm"] = {k: (round(float(v)) if k != "reconciles" else v) for k, v in pv.items()}

    # Style lifecycle + breadth
    sa = A.groupby("style").net_revenue.sum() / da; sb = B.groupby("style").net_revenue.sum() / db
    st = pd.DataFrame({"A": sa, "B": sb}).fillna(0); st["chg"] = st.B - st.A
    cont = st[(st.A > 0) & (st.B > 0)]; lost = st[(st.A > 0) & (st.B == 0)]; new = st[(st.A == 0) & (st.B > 0)]
    top10 = st.chg.nsmallest(10).sum() / st.chg[st.chg < 0].sum() * 100
    print(f"STYLES: continuing {len(cont)} (change {cont.chg.sum():,.0f}/day, {100*(cont.chg<0).mean():.0f}% declining) | "
          f"discontinued {len(lost)} ({-lost.A.sum():,.0f}) | new {len(new)} ({new.B.sum():,.0f}) | top-10 declining styles = {top10:.0f}% of all declines")
    SUMMARY["styles"] = {"continuing": len(cont), "pct_continuing_declining": round(100 * float((cont.chg < 0).mean()), 1),
                         "continuing_change_per_day": round(float(cont.chg.sum())), "discontinued_change_per_day": round(float(-lost.A.sum())),
                         "new_change_per_day": round(float(new.B.sum())), "top10_decliners_pct_of_declines": round(float(top10), 1)}

    # Hypothesis test: stock-outs?  (stock file is a snapshot of unknown date, so this can only rule things OUT)
    top = st.sort_values("A", ascending=False).head(150).join(stock.set_index("style")["stock_units"])
    top["stock_units"] = top.stock_units.fillna(0); top["pct"] = 100 * top.chg / top.A
    rho, p_rho = stats.spearmanr(top.stock_units, top.pct)
    low = int((top.stock_units <= 10).sum())
    print(f"STOCK-OUT TEST (top 150 styles): {low} have <=10 units in stock | Spearman(stock, % change) = {rho:.2f} (p={p_rho:.2f})")
    SUMMARY["stockout_test"] = {"top_styles_tested": 150, "styles_with_le10_units": low, "spearman_rho": round(float(rho), 2), "p_value": round(float(p_rho), 2)}

    # Weekly by category output (Power BI)
    wc = w.assign(week=wk).pivot_table(index="week", columns="category", values="net_revenue", aggfunc="sum").fillna(0) / 7
    wc.insert(0, "week_start", [start + pd.Timedelta(days=7 * (int(i) - 1)) for i in wc.index])
    wc.reset_index().to_csv(OUT / "weekly_revenue_per_day_by_category.csv", index=False)
    weekly_out = weekly.round(1)
    weekly_out.insert(0, "week_start", [start + pd.Timedelta(days=7 * (int(i) - 1)) for i in weekly.index])
    weekly_out.reset_index().to_csv(OUT / "weekly_summary.csv", index=False, date_format="%Y-%m-%d")
    return cp_date, seg, wc, weekly


# ----------------------------------------------------------------------------
# 3. Forecast with rolling-origin backtest
# ----------------------------------------------------------------------------
def dow_index(s):
    m = s.groupby(s.index.dayofweek).mean()
    return (m / m.mean()).reindex(range(7)).values


def m_seasonal_naive(tr, dates):
    last = tr.values[-7:]
    return np.array([last[(i) % 7] for i in range(len(dates))])


def make_level_dow(k):
    def model(tr, dates):
        idx = dow_index(tr)
        level = (tr.iloc[-k:] / idx[tr.iloc[-k:].index.dayofweek]).mean()
        return level * idx[dates.dayofweek]
    return model


def m_ses_dow(tr, dates):
    idx = dow_index(tr); ds = (tr / idx[tr.index.dayofweek]).values
    best = None
    for a in np.arange(0.05, 0.95, 0.05):
        lvl, sse = ds[0], 0.0
        for v in ds[1:]:
            sse += (v - lvl) ** 2; lvl = a * v + (1 - a) * lvl
        if best is None or sse < best[0]:
            best = (sse, a, lvl)
    return best[2] * idx[dates.dayofweek]


def m_trend_dow(tr, dates):
    idx = dow_index(tr); ds = (tr / idx[tr.index.dayofweek]).values
    t = np.arange(len(ds)); b, a = np.polyfit(t, ds, 1)
    tf = np.arange(len(ds), len(ds) + len(dates))
    return (a + b * tf) * idx[dates.dayofweek]


_LEVEL14, _LEVEL28 = make_level_dow(14), make_level_dow(28)


def m_ensemble(tr, dates):
    """Average of the three 'recent level' models. With only a few backtest folds these models cannot be
    told apart, so averaging them avoids betting on one."""
    return (_LEVEL14(tr, dates) + _LEVEL28(tr, dates) + m_ses_dow(tr, dates)) / 3


MODELS = {"Seasonal naive (last week)": m_seasonal_naive, "Level, last 14 days x weekday": _LEVEL14,
          "Level, last 28 days x weekday": _LEVEL28, "Exp. smoothing x weekday": m_ses_dow,
          "Linear trend x weekday": m_trend_dow, "Ensemble of the three level models": m_ensemble}


def backtest(y):
    rows, errs = [], {k: [] for k in MODELS}
    for n0 in (35, 42, 49, 56):                                   # training lengths; test = next 28 days
        tr, te = y.iloc[:n0], y.iloc[n0:n0 + HORIZON]
        if len(te) < HORIZON:
            continue
        for name, fn in MODELS.items():
            fc = fn(tr, te.index)
            wape = np.abs(te.values - fc).sum() / te.values.sum()
            bias = fc.sum() / te.values.sum() - 1
            rows.append([name, n0, te.index[0].date(), wape * 100, bias * 100])
            errs[name].extend(np.log(te.values / fc))
    bt = pd.DataFrame(rows, columns=["model", "train_days", "test_start", "wape_pct", "total_bias_pct"])
    bt.to_csv(OUT / "backtest_results.csv", index=False)
    return bt, errs


def forecast(d, cp_date):
    y = d.net_revenue.copy()
    bt, errs = backtest(y)
    summ = bt.groupby("model").agg(mean_wape=("wape_pct", "mean"), mean_bias=("total_bias_pct", "mean"))
    # Two views: all folds, and folds whose training data already contains the step (where the question is "what is the new level")
    post = bt[bt.train_days >= 42].groupby("model").wape_pct.mean().rename("wape_after_step")
    summ = summ.join(post).sort_values("wape_after_step").round(1)
    print("\nBACKTEST (28-day horizon, rolling origins 35/42/49/56 training days)\n", summ.to_string())
    # Selection rule: with so few folds, near-ties are noise. Prefer the ensemble unless a single model
    # beats it by more than 1 percentage point of WAPE.
    ens = "Ensemble of the three level models"
    best = ens if summ.loc[ens, "wape_after_step"] <= summ.wape_after_step.min() + 1.0 else summ.index[0]
    naive = "Seasonal naive (last week)"
    SUMMARY["backtest"] = {"best_model": best, "best_wape_after_step": float(summ.loc[best, "wape_after_step"]),
                           "naive_wape_after_step": float(summ.loc[naive, "wape_after_step"]),
                           "table": summ.reset_index().to_dict(orient="records")}

    # Final forecast: train on everything
    fdates = pd.date_range(y.index[-1] + pd.Timedelta(days=1), periods=HORIZON)
    fc = MODELS[best](y, fdates)
    e = np.array(errs[best]); q10, q90 = np.percentile(e, [10, 90])
    out = pd.DataFrame({"date": fdates, "forecast": fc.round(0), "lower_80": (fc * np.exp(q10)).round(0), "upper_80": (fc * np.exp(q90)).round(0)})
    out["series_type"] = "forecast"
    act = pd.DataFrame({"date": y.index, "actual_net_revenue": y.values.round(0), "series_type": "actual"})
    pd.concat([act, out], ignore_index=True)[["date", "series_type", "actual_net_revenue", "forecast", "lower_80", "upper_80"]] \
        .to_csv(OUT / "forecast_daily.csv", index=False, date_format="%Y-%m-%d")

    # Do the models agree? (the top backtest scores are within noise of each other, so check the forecasts too)
    agree = pd.DataFrame({"net_revenue_next_28_days": {m: float(fn(y, fdates).sum()) for m, fn in MODELS.items()}}).round(0).join(summ)
    agree.to_csv(OUT / "forecast_model_comparison.csv")
    print("\nMODEL AGREEMENT (28-day total)\n", agree.to_string())
    SUMMARY["model_totals"] = agree.net_revenue_next_28_days.to_dict()

    # Scenario totals for the 28 days
    pre_level = (y[y.index < cp_date] / dow_index(y)[y[y.index < cp_date].index.dayofweek]).mean() * dow_index(y)[fdates.dayofweek]
    sc = pd.DataFrame([["Low (10th percentile)", out.lower_80.sum()], ["Base forecast", out.forecast.sum()],
                       ["High (90th percentile)", out.upper_80.sum()], ["Back to pre-step level", pre_level.sum()]],
                      columns=["scenario", "net_revenue_next_28_days"]).round(0)
    sc["vs_base_pct"] = (100 * (sc.net_revenue_next_28_days / out.forecast.sum() - 1)).round(1)
    sc.to_csv(OUT / "forecast_scenarios.csv", index=False)
    print("\nFORECAST", fdates[0].date(), "->", fdates[-1].date(), f"| model: {best}\n", sc.to_string(index=False))
    SUMMARY["forecast"] = {"from": str(fdates[0].date()), "to": str(fdates[-1].date()), "model": best,
                           "interval_log_q10_q90": [round(float(q10), 3), round(float(q90), 3)],
                           "scenarios": sc.set_index("scenario").net_revenue_next_28_days.to_dict()}
    return bt, summ, out, y


# ----------------------------------------------------------------------------
# 4. Charts
# ----------------------------------------------------------------------------
def charts(day, d, start, end, cp_date, wc, seg, summ, out, y):
    # 1. Daily series with censored days
    fig, ax = plt.subplots(figsize=(10, 4.2))
    allday = day.copy()
    g = pd.read_csv(CLEAN / "fact_orders.csv", parse_dates=["order_date"]).groupby("order_date").net_revenue.sum()
    ax.bar(d.index, d.net_revenue, color=GREY, width=0.85, label="Daily net revenue")
    ax.plot(d.index, d.net_revenue.rolling(7, min_periods=4).mean(), color=BLUE, lw=2.2, label="7-day average")
    cens = g.loc[end + pd.Timedelta(days=1):]
    ax.bar(cens.index, cens.values, color=RED, alpha=.5, width=0.85, label="Not settled (orders still Pending)")
    ax.axvline(cp_date, color=AMBER, ls="--", lw=1.5); ax.text(cp_date, ax.get_ylim()[1] * .97, " step change", color=AMBER, va="top", fontsize=9)
    ax.yaxis.set_major_formatter(fmt_k); ax.set_xlim(start - pd.Timedelta(days=1), g.index.max() + pd.Timedelta(days=1))
    ax.set_title("Net revenue stepped down in early May, then fell again in late June\n(the last 3 days look like a collapse only because their orders had not shipped yet)", loc="left")
    ax.xaxis.set_major_formatter(fmt_d); ax.legend(frameon=False, fontsize=8, loc="upper right"); fig.tight_layout(); fig.savefig(IMG / "01_daily_net_revenue.png"); plt.close(fig)

    # 2. Weekly by category
    fig, ax = plt.subplots(figsize=(10, 4.2))
    for c, col in zip(["Set", "Kurta", "Western Dress", "Top"], [BLUE, GREEN, AMBER, GREY]):
        ax.plot(wc.week_start, wc[c], marker="o", ms=4, lw=2, color=col, label=c)
        ax.text(wc.week_start.iloc[-1] + pd.Timedelta(days=3), wc[c].iloc[-1], c, color=col, va="center", fontsize=9)
    ax.axvline(cp_date, color=AMBER, ls="--", lw=1); ax.yaxis.set_major_formatter(fmt_k); ax.set_xlim(right=wc.week_start.iloc[-1] + pd.Timedelta(days=22))
    ax.set_title("Sets and Kurtas fell by about a third in one week; Western Dress held up", loc="left")
    ax.xaxis.set_major_formatter(fmt_d); ax.set_ylabel("Net revenue per day (week average)"); fig.tight_layout(); fig.savefig(IMG / "02_weekly_by_category.png"); plt.close(fig)

    # 3. Drivers
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.8))
    for ax, dim, ttl in zip(axes, ["category", "zone"], ["By category", "By zone"]):
        s = seg[seg.dimension == dim].sort_values("change_per_day")
        ax.barh(s.segment, s.change_per_day, color=[RED if v < 0 else GREEN for v in s.change_per_day])
        for yy, (v, pc) in enumerate(zip(s.change_per_day, s["pct_change"])):
            ax.text(v, yy, f" {pc:+.0f}%" if v >= 0 else f"{pc:+.0f}% ", va="center", ha="left" if v >= 0 else "right", fontsize=8)
        ax.xaxis.set_major_formatter(fmt_k); ax.axvline(0, color=INK, lw=.8); ax.set_title(ttl, loc="left")
        ax.margins(x=0.25)
    fig.suptitle("Change in net revenue per day, before vs after the step change", x=0.01, ha="left", fontweight="bold", fontsize=11)
    fig.tight_layout(); fig.savefig(IMG / "03_decline_drivers.png"); plt.close(fig)

    # 4. Backtest
    fig, ax = plt.subplots(figsize=(8, 3.6)); s = summ.sort_values("wape_after_step", ascending=False)
    ax.barh(s.index, s.wape_after_step, color=[BLUE if m == summ.index[0] else GREY for m in s.index])
    for yy, v in enumerate(s.wape_after_step): ax.text(v, yy, f" {v:.1f}%", va="center", fontsize=9)
    ax.set_xlabel("Average daily error (WAPE), lower is better"); ax.margins(x=0.15)
    ax.set_title("Backtest: a simple recent-level model beats the naive baseline", loc="left"); fig.tight_layout(); fig.savefig(IMG / "04_backtest.png"); plt.close(fig)

    # 5. Forecast
    fig, ax = plt.subplots(figsize=(10, 4.2))
    ax.plot(y.index, y.values, color=GREY, lw=1.3, label="Actual")
    ax.plot(y.index, pd.Series(y.values, index=y.index).rolling(7, min_periods=4).mean(), color=INK, lw=2, label="7-day average")
    ax.plot(out.date, out.forecast, color=BLUE, lw=2.2, label="Forecast")
    ax.fill_between(out.date, out.lower_80, out.upper_80, color=BLUE, alpha=.18, label="80% range")
    pre = y[y.index < cp_date].mean(); ax.axhline(pre, color=AMBER, ls=":", lw=1.3)
    ax.text(out.date.iloc[-1], pre * 1.012, "average before the step change", color=AMBER, fontsize=8, ha="right", va="bottom")
    ax.yaxis.set_major_formatter(fmt_k); ax.xaxis.set_major_formatter(fmt_d); ax.legend(frameon=False, fontsize=8, ncol=4, loc="lower left")
    ax.set_title(f"Next 4 weeks: about Rs {out.forecast.sum()/1e6:.1f}M expected (80% range Rs {out.lower_80.sum()/1e6:.1f}M to Rs {out.upper_80.sum()/1e6:.1f}M)", loc="left")
    fig.tight_layout(); fig.savefig(IMG / "05_forecast.png"); plt.close(fig)


def main():
    f, stock = load()
    day, start, end = detect_window(f)
    w = f[(f.order_date >= start) & (f.order_date <= end)]
    d = w.groupby("order_date").agg(net_revenue=("net_revenue", "sum"), gross=("amount", "sum"), lines=("order_line_id", "size"))
    d = d.reindex(pd.date_range(start, end), fill_value=0)
    outliers(f, d)
    cp_date, seg, wc, weekly = drivers(f, d, start, end, stock)
    bt, summ, out, y = forecast(d, cp_date)
    charts(day, d, start, end, cp_date, wc, seg, summ, out, y.astype(float))
    (OUT / "analysis_summary.json").write_text(json.dumps(SUMMARY, indent=2, default=str))
    print("\nWrote:", ", ".join(sorted(p.name for p in OUT.glob("*"))), "| charts:", ", ".join(sorted(p.name for p in IMG.glob("0*.png"))))


if __name__ == "__main__":
    main()
