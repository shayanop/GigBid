# Internal Data Pipeline for Legal Analytics (code-verified)

Project: fr_da-p15  
Repository: https://github.com/shayanop/GigBid/tree/master/data/personas/fr_da/repos/fr_da-p15

## Summary
This internal data pipeline processes legal case data. It uses Airflow DAGs to orchestrate tasks, Python scripts for statistical analysis via SciPy, and dbt models materialized as tables in Snowflake. The results are visualized in Looker.

## Code-verified stack
- Python: `analysis.py: from scipy import stats`
- Airflow: `pipeline.py: from airflow import DAG`
- Statistics: `analysis.py: from scipy import stats`
- dbt: `models.sql: {{ config(materialized='table') }}`
- Snowflake: `models.sql: USE WAREHOUSE analytics_wh;`
- Looker: `orders.lkml: explore: orders {}`
