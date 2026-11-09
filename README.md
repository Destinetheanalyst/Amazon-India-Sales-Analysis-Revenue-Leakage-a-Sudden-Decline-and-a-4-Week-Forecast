# Amazon-India-Sales-Analysis-Revenue-Leakage-a-Sudden-Decline-and-a-4-Week-Forecast

*An end-to-end business analytics project using Excel, Python, MySQL, and Power BI*

## Overview
<img width="1454" height="809" alt="Screenshot 2026-11-09 154121" src="https://github.com/user-attachments/assets/3bf98c8d-f4ec-4ca6-b7dc-99c5bf21f347" />


This project analyses 128,975 Amazon India order lines (31 Mar to 29 Jun 2022) to answer four business questions: where revenue leaks, why it fell, what to expect next, and which best sellers are about to run out of stock. It follows the full analyst workflow: inspecting raw data, cleaning and modelling it, analysing it in SQL and Python, forecasting, and presenting the results in an interactive dashboard.

| Result | Value |
| --- | --- |
| Revenue kept after cancellations and returns | ₹65.9M of ₹73.8M booked (89%) |
| Step change in daily revenue, around 9 May | -17.9% (₹876K to ₹719K per day; 95% interval -23% to -11%) |
| Forecast, next 28 days | ₹19.4M (80% range ₹15.6M to ₹22.7M) |
| Best sellers at risk (under 30 days of stock) | 76 styles, 26% of revenue |

## Business Problem

A fashion seller on Amazon India wants answers to five questions:

1. Where does revenue leak (cancellations, returns)?
2. Did revenue fall gradually or suddenly, and in which segments?
3. Can cancellations, catalog changes or stock-outs explain the fall?
4. What should we expect over the next four weeks, and how sure can we be?
5. Which products are about to run out, and which are tying up stock?

## Dataset

<img width="1220" height="724" alt="Screenshot 2026-11-05 173701" src="https://github.com/user-attachments/assets/47e7cf59-cd28-45bd-8ae1-1de795c0ab6b" />

- **Source:** the Kaggle “Amazon Sales Report” files: order-level sales (128,975 lines, 24 columns), a stock snapshot by style, and SKU price catalogues. Amounts are in INR.
- **Period:** 31 Mar to 29 Jun 2022. The first day is a one-day stub, and the last three days are not settled (see Key Findings).
- **Limitation:** There is no cost or profit column, and the SKU formats in the price catalogues do not match the sales data. This is therefore a revenue and operations analysis, not a margin analysis.

## Approach

```
raw CSVs → Excel (inspect) → Python (clean, star schema) → Excel (reconcile)
                                  ├→ MySQL (21 analytical queries)
                                  └→ Python (drivers, hypothesis tests, forecasting) → Power BI dashboard
```

| Tool | Role in the project |
| --- | --- |
| Excel | Inspecting the raw data, reconciling totals with pivot tables, a what-if scenario model |
| Python (pandas, NumPy, SciPy, Matplotlib) | Cleaning, outlier checks, change-point detection, hypothesis tests, backtested forecast |
| MySQL 8 | Star schema with keys, 21 analytical queries using CTEs, window functions and joins |
| Power BI | Data model, DAX measures, a 3-page dashboard |
| Jupyter | Both Python scripts as documented notebooks with saved outputs |

## Key Findings

1. **The last days of the extract are not settled.** Orders from 27 to 29 Jun were still pending (4.5%, 31.7% and 69.0% of those days’ lines), so their net revenue was understated while booked value looked normal. All trend analysis uses the settled window 4 Apr to 26 Jun: 84 days, or 12 whole weeks.
2. **Revenue stepped down; it did not slide.** Around 9 May, net revenue per day fell from ₹876K to ₹719K (-17.9%, 95% interval -23.4% to -11.3%). A single step explains the data better than a straight-line trend (R² 0.44 vs 0.28).
3. **The drop is broad and driven by volume.** All six zones fell (South -8%, the others -21% to -30%). Sets fell 29% and Kurtas 20%, while Western Dress grew 34%. Order lines per day fell 22.5%; unit prices did not.
4. **Three explanations were tested and ruled out.** Cancellations were flat (14.4% to 14.1%). Catalog changes do not explain it: 63% of continuing styles sold less, and new and discontinued styles net to about +₹3K per day against a -₹157K per day drop. Stock-outs do not explain it: only 1 of the top 150 styles is nearly out of stock, and stock level has no relationship with the size of the fall (Spearman rho -0.02). **The cause is not in the data.**
5. **Leakage.** Cancellations cost ₹6.5M (8.8% of bookings) and returns ₹1.35M (1.8%). Merchant-fulfilled (Easy Ship) orders cancel more: 17.5% vs 12.8% for Amazon-fulfilled.
6. **Concentration and inventory.** Sets and Kurtas make up 77% of net revenue, and the South zone 40%. 323 of 1,357 styles (24%) earn 80% of revenue. 76 styles have under 30 days of stock (12 under a week); the top style has 3.4 days left. 276 styles hold 14,353 units (6% of stock) with no sales in the window.

<img width="1486" height="813" alt="Screenshot 2026-11-09 154213" src="https://github.com/user-attachments/assets/f8ca75f5-9c54-4c34-b49c-626e18d39e82" />

## What Makes the Analysis Trustworthy

- **Settled window.** Detected from the data, not hard-coded, and trimmed to whole Monday-to-Sunday weeks.
- **Documented data quality.** 15 issues found and logged with a decision for each, including 6 duplicate lines, 69 spellings for about 36 states, and 7,795 blank amounts (97% on cancelled orders, so kept and flagged rather than dropped).
- **Traps recorded, not hidden.** Returns exist only for Merchant orders, so return rates are never compared across fulfilment models. Promotion IDs are not used to explain cancellations: 98% of cancelled lines have none, which would falsely suggest promotions prevent cancellations.
- **Reconciled across tools.** The same totals (128,969 lines, ₹78,590,043.30 booked, ₹69,660,658.00 net) appear in Excel, MySQL and Python, and every dashboard measure is checked against an independently computed value.
- **Forecast validated before use.** Six simple models were backtested on unseen data with rolling origins. The best have about 10% to 12% average daily error, against 13% for a naive baseline and 15% for a linear trend. The final forecast is an ensemble of the three best, because their scores cannot be told apart with so few test windows. That selection rule was set after seeing the results, and the models disagree by up to 16% on the 28-day total, so the output is a range, not a single number.
- **Nothing deleted as an outlier.** No daily anomalies were found. Comparing each price with its own style flags 0.44% of lines, which are plausible and kept.

## Dashboard

<img width="1495" height="804" alt="Screenshot 2026-11-09 154242" src="https://github.com/user-attachments/assets/97f65a10-a60c-434f-93b5-d554857b4c04" />

A three-page Power BI report built on the cleaned star schema and the Python outputs:

| Page | Purpose |
| --- | --- |
| Executive Overview | Net revenue, leakage, average order value, revenue by week, category, zone and state |
| Why It Fell, and What Is Next | The step change, segment drivers, the 4-week forecast with range, and scenarios |
| Leakage and Inventory | Revenue waterfall from booked to net, cancel rate by fulfilment, best sellers at risk of stock-out, dead stock |


## Recommendations

| # | Recommendation | Evidence |
| --- | --- | --- |
| 1 | Find what changed on or around 9 May (advertising, sale events, pricing, competitors) | A 17.9% step down worth about ₹157K per day, roughly ₹5M a month, across every zone, with the obvious causes ruled out |
| 2 | Reduce Merchant (Easy Ship) cancellations | 17.5% vs 12.8%. Matching Amazon’s rate would have kept roughly ₹0.8M of bookings (a rough estimate) |
| 3 | Reorder best sellers now | 76 styles under 30 days of stock, 12 under a week, covering 26% of revenue |
| 4 | Clear dead stock | 276 styles, 14,353 units, no sales in the window |

## Repository Structure

```
amazon-sales-project/
├── data/
│   ├── raw/          (not committed; download from Kaggle)
│   ├── cleaned/      (star schema CSVs and data quality log)
│   └── outputs/      (forecast, drivers, backtest, summary JSON)
├── python/           (01_clean_data.py, 02_analysis.py)
├── notebooks/        (cleaning and analysis, with saved outputs)
├── sql/              (schema, load script, 21 analysis queries)
├── powerbi/          (build guide, DAX measures, theme, wireframes)
├── docs/             (data quality log, end-to-end guide)
├── images/           (charts)
└── README.md
```

## How to Reproduce

1. Download the Kaggle files into `data/raw/`.
2. Install and run the pipeline:

```
pip install -r requirements.txt
python python/01_clean_data.py
python python/02_analysis.py
```

3. Prefer notebooks? Run `pip install -r requirements-notebooks.txt`, start `jupyter lab`, and run the two notebooks in `notebooks/` in order.
4. MySQL 8.0 or later: run `sql/01_schema.sql`, then `sql/02_load_data.sql` (edit the folder path first), confirm the verify query returns 128,969 lines and ₹69,660,658.00 net revenue, then run `sql/03_analysis_queries.sql`.
5. Power BI: follow `powerbi/BUILD_GUIDE.md`.

Full walkthrough with a checkpoint number at every stage: `docs/END_TO_END_GUIDE.md`.

## Limitations

- Three months of data: no year-over-year or seasonality conclusions, and the forecast covers only four weeks.
- No cost data, so no profit or margin analysis.
- The date of the step change is estimated from the same data it is tested on, so its confidence interval is somewhat optimistic.
- The stock file is a snapshot of an unknown date. It can rule hypotheses out but cannot prove one.
- Return data exists only for Merchant orders.

## Next Steps

- Add cost data to move from revenue to margin analysis.
- Add advertising spend and promotion calendars to test what happened around 9 May.
- Extend the history to measure seasonality and improve the forecast.

