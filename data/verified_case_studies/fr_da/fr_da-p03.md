# Healthcare Internal Data Tool (code-verified)

Project: fr_da-p03  
Repository: https://github.com/shayanop/GigBid/tree/master/data/personas/fr_da/repos/fr_da-p03

## Summary
This internal tool for a healthcare client orchestrates data processing and reporting. It is built in Python, using pandas for data cleaning, Airflow for scheduling pipelines, and Looker for data exploration. The code includes a main entry point, a cleaning module, an Airflow DAG definition, and a Looker model for orders.

## Code-verified stack
- Python: `app.py: def main() -> None:`
- pandas: `clean.py: import pandas as pd`
- Airflow: `pipeline.py: from airflow import DAG`
- Looker: `orders.lkml: explore: orders {}`
