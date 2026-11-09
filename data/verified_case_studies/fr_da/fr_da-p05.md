# Internal Data Cleaning Tool (code-verified)

Project: fr_da-p05  
Repository: https://github.com/shayanop/GigBid/tree/master/data/personas/fr_da/repos/fr_da-p05

## Summary
An internal data cleaning tool built for an education client that uses Python to connect to BigQuery, runs SQL queries to aggregate order data, employs dbt to materialize models, and integrates with Looker for data exploration.

## Code-verified stack
- Python: `clean.py: from google.cloud import bigquery`
- BigQuery: `clean.py: from google.cloud import bigquery`
- SQL: `models.sql: SELECT user_id, SUM(amount) OVER (PARTITION BY user_id) FROM orders;`
- dbt: `models.sql: {{ config(materialized='table') }}`
- Looker: `orders.lkml: explore: orders {}`
