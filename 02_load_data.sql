USE amazon_sales;

LOAD DATA LOCAL INFILE 'C:/path/to/amazon-sales-project/data/cleaned/dim_date.csv'
INTO TABLE dim_date
FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
LINES TERMINATED BY '\n'
IGNORE 1 LINES;

LOAD DATA LOCAL INFILE 'C:/path/to/amazon-sales-project/data/cleaned/dim_state.csv'
INTO TABLE dim_state
FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
LINES TERMINATED BY '\n'
IGNORE 1 LINES;

LOAD DATA LOCAL INFILE 'C:/path/to/amazon-sales-project/data/cleaned/dim_products.csv'
INTO TABLE dim_products
FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
LINES TERMINATED BY '\n'
IGNORE 1 LINES;

LOAD DATA LOCAL INFILE 'C:/path/to/amazon-sales-project/data/cleaned/stock_by_style.csv'
INTO TABLE stock_by_style
FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
LINES TERMINATED BY '\n'
IGNORE 1 LINES;

LOAD DATA LOCAL INFILE 'C:/path/to/amazon-sales-project/data/cleaned/fact_orders.csv'
INTO TABLE fact_orders
FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
LINES TERMINATED BY '\n'
IGNORE 1 LINES
(order_line_id, order_id, order_date, order_month, status, status_group, fulfilment,
 ship_service_level, sales_channel, courier_status, is_b2b, sku, state, @city, @postal_code,
 qty, amount, net_units, priced_units, net_revenue, has_promotion, amount_was_missing,
 zero_value_completed)
SET city        = NULLIF(@city, ''),
    postal_code = NULLIF(@postal_code, '');

SELECT COUNT(*)         AS order_lines,   
       SUM(amount)      AS gross_booked,  
       SUM(net_revenue) AS net_revenue,  
       SUM(city IS NULL) AS null_city    
FROM fact_orders;
SHOW WARNINGS;  
