CREATE DATABASE IF NOT EXISTS amazon_sales CHARACTER SET utf8mb4;
USE amazon_sales;

DROP TABLE IF EXISTS fact_orders;
DROP TABLE IF EXISTS stock_by_style;
DROP TABLE IF EXISTS dim_products;
DROP TABLE IF EXISTS dim_state;
DROP TABLE IF EXISTS dim_date;

CREATE TABLE dim_date (
    date_key     DATE        NOT NULL,
    year         SMALLINT    NOT NULL,
    month_num    SMALLINT    NOT NULL,
    month_name   VARCHAR(3)  NOT NULL,
    month_start  DATE        NOT NULL,
    week_start   DATE        NOT NULL,
    day_name     VARCHAR(3)  NOT NULL,
    is_weekend   SMALLINT    NOT NULL,
    PRIMARY KEY (date_key)
);

CREATE TABLE dim_state (
    state  VARCHAR(40) NOT NULL,
    zone   VARCHAR(12) NOT NULL,
    PRIMARY KEY (state)
);

CREATE TABLE dim_products (
    sku       VARCHAR(40) NOT NULL,
    style     VARCHAR(20) NOT NULL,
    category  VARCHAR(20) NOT NULL,
    size      VARCHAR(6)  NOT NULL,
    asin      VARCHAR(15),
    PRIMARY KEY (sku),
    INDEX ix_products_style (style)
);

CREATE TABLE stock_by_style (
    style        VARCHAR(20) NOT NULL,
    stock_units  INT         NOT NULL,
    stock_skus   INT         NOT NULL,
    PRIMARY KEY (style)
);

CREATE TABLE fact_orders (
    order_line_id         INT           NOT NULL,
    order_id              VARCHAR(25)   NOT NULL,
    order_date            DATE          NOT NULL,
    order_month           DATE          NOT NULL,
    status                VARCHAR(40)   NOT NULL,
    status_group          VARCHAR(15)   NOT NULL,  
    fulfilment            VARCHAR(10)   NOT NULL,  
    ship_service_level    VARCHAR(10)   NOT NULL,
    sales_channel         VARCHAR(12)   NOT NULL,
    courier_status        VARCHAR(12)   NOT NULL,
    is_b2b                SMALLINT      NOT NULL,
    sku                   VARCHAR(40)   NOT NULL,
    state                 VARCHAR(40)   NOT NULL,
    city                  VARCHAR(60),
    postal_code           VARCHAR(10),
    qty                   SMALLINT      NOT NULL,
    amount                DECIMAL(12,2) NOT NULL,  
    net_units             SMALLINT      NOT NULL,   
    priced_units          SMALLINT      NOT NULL,  
    net_revenue           DECIMAL(12,2) NOT NULL,  
    has_promotion         SMALLINT      NOT NULL,
    amount_was_missing    SMALLINT      NOT NULL,
    zero_value_completed  SMALLINT      NOT NULL,
    PRIMARY KEY (order_line_id),
    INDEX ix_fact_date  (order_date),
    INDEX ix_fact_sku   (sku),
    INDEX ix_fact_state (state),
    INDEX ix_fact_order (order_id),
    CONSTRAINT fk_fact_date  FOREIGN KEY (order_date) REFERENCES dim_date(date_key),
    CONSTRAINT fk_fact_sku   FOREIGN KEY (sku)        REFERENCES dim_products(sku),
    CONSTRAINT fk_fact_state FOREIGN KEY (state)      REFERENCES dim_state(state)
);
