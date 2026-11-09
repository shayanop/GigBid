# E-commerce Data Pipeline Tool (code-verified)

Project: fr_da-p13  
Repository: https://github.com/shayanop/GigBid/tree/master/data/personas/fr_da/repos/fr_da-p13

## Summary
An internal tool was built to orchestrate data pipelines for an e‑commerce client. It uses Python to define the main execution logic, Airflow to schedule and manage the DAGs, and Snowflake to store and query analytics data. The tool runs locally with `make dev` and is documented in the docs folder.

## Code-verified stack
- Python: `app.py: def main() -> None:`
- Airflow: `pipeline.py: from airflow import DAG`
- Snowflake: `models.sql: USE WAREHOUSE analytics_wh;`
