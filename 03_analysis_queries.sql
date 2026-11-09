USE amazon_sales;

-- Q0. Load validation

SELECT COUNT(*)                  AS order_lines,
       COUNT(DISTINCT order_id)  AS distinct_orders,
       SUM(amount)               AS gross_booked,
       SUM(net_revenue)          AS net_revenue
FROM fact_orders;


-- Q1. Monthly KPIs
SELECT order_month,
       COUNT(DISTINCT order_id)                                        AS orders_placed,
       SUM(amount)                                                     AS gross_booked,
       SUM(CASE WHEN status_group = 'Cancelled' THEN amount ELSE 0 END) AS cancelled_value,
       SUM(net_revenue)                                                AS net_revenue,
       SUM(net_units)                                                  AS units_sold,
       ROUND(SUM(net_revenue) /
             NULLIF(COUNT(DISTINCT CASE WHEN status_group = 'Completed' THEN order_id END), 0), 2) AS avg_order_value,
       ROUND(100.0 * SUM(CASE WHEN status_group = 'Cancelled' THEN 1 ELSE 0 END) / COUNT(*), 2) AS cancel_rate_pct
FROM fact_orders
GROUP BY order_month
ORDER BY order_month;


-- Q2. Month-over-month growth (LAG), normalised per day 

WITH monthly AS (
    SELECT order_month,
           SUM(net_revenue)            AS net_revenue,
           COUNT(DISTINCT order_date)  AS days_in_data
    FROM fact_orders
    WHERE order_date BETWEEN '2022-04-04' AND '2022-06-26'   -- settled window (see header)
    GROUP BY order_month
),
daily_rate AS (
    SELECT order_month, net_revenue, days_in_data,
           net_revenue / days_in_data AS revenue_per_day
    FROM monthly
)
SELECT order_month,
       net_revenue,
       days_in_data,
       ROUND(revenue_per_day, 0) AS revenue_per_day,
       ROUND(100.0 * (net_revenue - LAG(net_revenue) OVER (ORDER BY order_month))
             / NULLIF(LAG(net_revenue) OVER (ORDER BY order_month), 0), 2)       AS mom_growth_total_pct,
       ROUND(100.0 * (revenue_per_day - LAG(revenue_per_day) OVER (ORDER BY order_month))
             / NULLIF(LAG(revenue_per_day) OVER (ORDER BY order_month), 0), 2)   AS mom_growth_per_day_pct
FROM daily_rate
ORDER BY order_month;


-- Q3. Category performance
SELECT p.category,
       SUM(f.net_revenue)                                              AS net_revenue,
       SUM(f.net_units)                                                AS units_sold,
       ROUND(100.0 * SUM(f.net_revenue) / SUM(SUM(f.net_revenue)) OVER (), 2) AS pct_of_net_revenue,
       ROUND(SUM(f.net_revenue) / NULLIF(SUM(f.priced_units), 0), 2)   AS avg_price_per_unit
FROM fact_orders f
JOIN dim_products p ON p.sku = f.sku
GROUP BY p.category
ORDER BY net_revenue DESC;


-- Q4. Top 3 selling sizes inside each category
WITH size_units AS (
    SELECT p.category, p.size, SUM(f.net_units) AS units_sold
    FROM fact_orders f
    JOIN dim_products p ON p.sku = f.sku
    GROUP BY p.category, p.size
),
ranked AS (
    SELECT category, size, units_sold,
           RANK() OVER (PARTITION BY category ORDER BY units_sold DESC) AS size_rank
    FROM size_units
)
SELECT category, size_rank, size, units_sold
FROM ranked
WHERE size_rank <= 3 AND units_sold > 0
ORDER BY category, size_rank;


-- Q5. Top 10 styles + Pareto
WITH style_rev AS (
    SELECT p.style, p.category, SUM(f.net_revenue) AS net_revenue, SUM(f.net_units) AS units_sold
    FROM fact_orders f
    JOIN dim_products p ON p.sku = f.sku
    GROUP BY p.style, p.category
)
SELECT style, category, net_revenue, units_sold,
       ROUND(100.0 * net_revenue / SUM(net_revenue) OVER (), 2) AS pct_of_total,
       ROUND(100.0 * SUM(net_revenue) OVER (ORDER BY net_revenue DESC, style)
             / SUM(net_revenue) OVER (), 2)                     AS cumulative_pct
FROM style_rev
ORDER BY net_revenue DESC, style
LIMIT 10;


-- Q5b. How concentrated is revenue? Styles needed to reach 80%
WITH style_rev AS (
    SELECT p.style, SUM(f.net_revenue) AS net_revenue
    FROM fact_orders f
    JOIN dim_products p ON p.sku = f.sku
    GROUP BY p.style
),
cum AS (
    SELECT style,
           100.0 * SUM(net_revenue) OVER (ORDER BY net_revenue DESC, style)
                 / SUM(net_revenue) OVER () AS cumulative_pct
    FROM style_rev
)
SELECT COUNT(*)                                           AS styles_to_reach_80pct,
       (SELECT COUNT(*) FROM style_rev WHERE net_revenue > 0) AS styles_with_revenue,
       ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM style_rev WHERE net_revenue > 0), 1) AS pct_of_styles
FROM cum
WHERE cumulative_pct <= 80;


-- Q6. State ranking inside each zone (top 3 per zone)
WITH state_rev AS (
    SELECT s.zone, f.state, SUM(f.net_revenue) AS net_revenue, SUM(f.net_units) AS units_sold
    FROM fact_orders f
    JOIN dim_state s ON s.state = f.state
    GROUP BY s.zone, f.state
)
SELECT zone, zone_rank, state, net_revenue, units_sold, pct_of_zone
FROM (
    SELECT zone, state, net_revenue, units_sold,
           RANK() OVER (PARTITION BY zone ORDER BY net_revenue DESC) AS zone_rank,
           ROUND(100.0 * net_revenue / SUM(net_revenue) OVER (PARTITION BY zone), 1) AS pct_of_zone
    FROM state_rev
) t
WHERE zone_rank <= 3
ORDER BY zone, zone_rank;


-- Q6b. Zone summary
SELECT s.zone,
       SUM(f.net_revenue)                                                       AS net_revenue,
       ROUND(100.0 * SUM(f.net_revenue) / SUM(SUM(f.net_revenue)) OVER (), 2)   AS pct_of_total,
       ROUND(100.0 * SUM(CASE WHEN f.status_group = 'Cancelled' THEN 1 ELSE 0 END) / COUNT(*), 2) AS cancel_rate_pct
FROM fact_orders f
JOIN dim_state s ON s.state = f.state
GROUP BY s.zone
ORDER BY net_revenue DESC;


-- Q7. Top 10 cities
SELECT city, state,
       SUM(net_revenue) AS net_revenue,
       SUM(net_units)   AS units_sold
FROM fact_orders
WHERE city IS NOT NULL
GROUP BY city, state
ORDER BY net_revenue DESC
LIMIT 10;


-- Q8. Fulfilment model x service level

SELECT fulfilment,
       ship_service_level,
       COUNT(*)                                                        AS order_lines,
       SUM(net_revenue)                                                AS net_revenue,
       ROUND(SUM(net_revenue) / NULLIF(SUM(priced_units), 0), 2)       AS avg_price_per_unit,
       ROUND(100.0 * SUM(CASE WHEN status_group = 'Cancelled' THEN 1 ELSE 0 END) / COUNT(*), 2) AS cancel_rate_pct,
       CASE WHEN fulfilment = 'Merchant'
            THEN ROUND(100.0 * SUM(CASE WHEN status_group = 'Returned' THEN 1 ELSE 0 END) /
                 NULLIF(SUM(CASE WHEN status_group IN ('Completed', 'Returned') THEN 1 ELSE 0 END), 0), 2)
       END                                                             AS return_rate_pct
FROM fact_orders
WHERE sales_channel = 'Amazon.in'
GROUP BY fulfilment, ship_service_level
ORDER BY fulfilment, ship_service_level;


-- Q9. Revenue leakage by category 
SELECT p.category,
       SUM(f.amount)                                                             AS gross_booked,
       SUM(CASE WHEN f.status_group = 'Cancelled'    THEN f.amount ELSE 0 END)   AS cancelled_value,
       SUM(CASE WHEN f.status_group = 'Returned'     THEN f.amount ELSE 0 END)   AS returned_value,
       SUM(CASE WHEN f.status_group = 'Pending'      THEN f.amount ELSE 0 END)   AS pending_value,
       SUM(f.net_revenue)                                                        AS net_revenue,
       ROUND(100.0 * SUM(CASE WHEN f.status_group IN ('Cancelled', 'Returned', 'Lost/Damaged')
                              THEN f.amount ELSE 0 END) / NULLIF(SUM(f.amount), 0), 2) AS leakage_pct
FROM fact_orders f
JOIN dim_products p ON p.sku = f.sku
GROUP BY p.category
ORDER BY gross_booked DESC;


-- Q9b. Cancellation rate by fulfilment model
SELECT fulfilment,
       COUNT(*) AS order_lines,
       SUM(CASE WHEN status_group = 'Cancelled' THEN 1 ELSE 0 END) AS cancelled_lines,
       ROUND(100.0 * SUM(CASE WHEN status_group = 'Cancelled' THEN 1 ELSE 0 END) / COUNT(*), 2) AS cancel_rate_pct
FROM fact_orders
WHERE sales_channel = 'Amazon.in'
GROUP BY fulfilment
ORDER BY cancel_rate_pct DESC;


-- Q10. B2B vs B2C
SELECT CASE WHEN is_b2b = 1 THEN 'B2B' ELSE 'B2C' END AS customer_type,
       COUNT(DISTINCT order_id)                       AS orders,
       SUM(net_revenue)                               AS net_revenue,
       ROUND(SUM(net_revenue) /
             NULLIF(COUNT(DISTINCT CASE WHEN status_group = 'Completed' THEN order_id END), 0), 2) AS avg_order_value,
       ROUND(100.0 * SUM(net_revenue) / SUM(SUM(net_revenue)) OVER (), 2) AS pct_of_net_revenue
FROM fact_orders
GROUP BY is_b2b;


-- Q10b. Promotion flag on COMPLETED lines only (descriptive, not causal)
SELECT p.category,
       ROUND(100.0 * SUM(CASE WHEN f.has_promotion = 1 THEN 1 ELSE 0 END) / COUNT(*), 1) AS pct_lines_with_promo,
       ROUND(SUM(CASE WHEN f.has_promotion = 1 THEN f.net_revenue ELSE 0 END) /
             NULLIF(SUM(CASE WHEN f.has_promotion = 1 THEN f.priced_units ELSE 0 END), 0), 2) AS asp_with_promo,
       ROUND(SUM(CASE WHEN f.has_promotion = 0 THEN f.net_revenue ELSE 0 END) /
             NULLIF(SUM(CASE WHEN f.has_promotion = 0 THEN f.priced_units ELSE 0 END), 0), 2) AS asp_without_promo
FROM fact_orders f
JOIN dim_products p ON p.sku = f.sku
WHERE f.status_group = 'Completed'
GROUP BY p.category
HAVING COUNT(*) >= 500
ORDER BY pct_lines_with_promo DESC;


-- Q11. Daily revenue, running total and 7-day moving average
WITH daily AS (
    SELECT order_date, SUM(net_revenue) AS net_revenue
    FROM fact_orders
    GROUP BY order_date
)
SELECT order_date,
       net_revenue,
       SUM(net_revenue) OVER (ORDER BY order_date)                                     AS running_total,
       ROUND(AVG(net_revenue) OVER (ORDER BY order_date ROWS BETWEEN 6 PRECEDING AND CURRENT ROW), 0) AS moving_avg_7d
FROM daily
ORDER BY order_date;


-- Q12. Day-of-week pattern (JOIN to dim_date)
WITH daily AS (
    SELECT order_date, SUM(net_revenue) AS net_revenue
    FROM fact_orders
    WHERE order_date BETWEEN '2022-04-04' AND '2022-06-26'
    GROUP BY order_date
)
SELECT d.day_name,
       d.is_weekend,
       COUNT(*)                        AS days_counted,
       ROUND(AVG(daily.net_revenue), 0) AS avg_daily_net_revenue
FROM daily
JOIN dim_date d ON d.date_key = daily.order_date
GROUP BY d.day_name, d.is_weekend
ORDER BY avg_daily_net_revenue DESC;


-- Q13. Best sellers at risk of stock-out
WITH sales AS (
    SELECT p.style, SUM(f.net_units) AS units_sold, SUM(f.net_revenue) AS net_revenue
    FROM fact_orders f
    JOIN dim_products p ON p.sku = f.sku
    WHERE f.order_date BETWEEN '2022-04-04' AND '2022-06-26'
    GROUP BY p.style
)
SELECT s.style,
       s.units_sold,
       s.net_revenue,
       st.stock_units,
       ROUND(st.stock_units / (s.units_sold / 84.0), 1) AS days_of_cover
FROM sales s
JOIN stock_by_style st ON st.style = s.style
WHERE s.units_sold >= 100
  AND st.stock_units / (s.units_sold / 84.0) < 30
ORDER BY s.units_sold DESC
LIMIT 15;


-- Q13b. Dead stock: styles holding stock that sold nothing
SELECT st.style, st.stock_units, st.stock_skus
FROM stock_by_style st
LEFT JOIN (SELECT p.style, SUM(f.net_units) AS units_sold
           FROM fact_orders f JOIN dim_products p ON p.sku = f.sku
           GROUP BY p.style) s ON s.style = st.style
WHERE COALESCE(s.units_sold, 0) = 0
ORDER BY st.stock_units DESC
LIMIT 15;


-- Q13c. Join coverage check: sold styles with no stock record
SELECT COUNT(*) AS sold_styles_without_stock_row
FROM (SELECT DISTINCT p.style
      FROM fact_orders f JOIN dim_products p ON p.sku = f.sku) s
LEFT JOIN stock_by_style st ON st.style = s.style
WHERE st.style IS NULL;


-- Q14. Why the edge days are excluded: share of lines still 'Pending' by day 
SELECT order_date,
       COUNT(*)                                                                               AS order_lines,
       SUM(amount)                                                                            AS gross_booked,
       SUM(net_revenue)                                                                       AS net_revenue,
       ROUND(100.0 * SUM(CASE WHEN status_group = 'Pending' THEN 1 ELSE 0 END) / COUNT(*), 1) AS pending_pct
FROM fact_orders
WHERE order_date >= '2022-06-20'
GROUP BY order_date
ORDER BY order_date;
