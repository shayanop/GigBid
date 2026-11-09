# Real Estate Data Processing Tool (code-verified)

Project: fr_da-p16  
Repository: https://github.com/shayanop/GigBid/tree/master/data/personas/fr_da/repos/fr_da-p16

## Summary
This internal tool processes real estate transaction data using Python. It cleans and transforms data with pandas, loads results into BigQuery, and defines analytic models in SQL. The dbt framework materializes tables, and Snowflake is used as the target warehouse.

## Code-verified stack
- Python: `app.py: def main() -> None:`
- pandas: `clean.py: import pandas as pd`
- BigQuery: `clean.py: from google.cloud import bigquery`
- SQL: `models.sql: SELECT user_id, SUM(amount) OVER (PARTITION BY user_id) FROM orders;`
- dbt: `models.sql: {{ config(materialized='table') }}`
- Snowflake: `models.sql: USE WAREHOUSE analytics_wh;`
