# Internal Data Cleaning Tool for E-commerce (code-verified)

Project: fr_da-p17  
Repository: https://github.com/shayanop/GigBid/tree/master/data/personas/fr_da/repos/fr_da-p17

## Summary
This internal tool automates data cleaning for an e-commerce client by extracting raw transaction data from BigQuery, transforming it with SQL logic in dbt models, and loading the results into a Snowflake warehouse. The Python script orchestrates the process, while Looker explores the cleaned orders data for reporting.

## Code-verified stack
- Python: `clean.py: from google.cloud import bigquery`
- BigQuery: `clean.py: from google.cloud import bigquery`
- SQL: `models.sql: SELECT user_id, SUM(amount) OVER (PARTITION BY user_id) FROM orders;`
- dbt: `models.sql: {{ config(materialized='table') }}`
- Snowflake: `models.sql: USE WAREHOUSE analytics_wh;`
- Looker: `orders.lkml: explore: orders {}`
