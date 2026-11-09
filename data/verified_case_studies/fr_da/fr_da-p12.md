# Healthcare Data Pipeline (code-verified)

Project: fr_da-p12  
Repository: https://github.com/shayanop/GigBid/tree/master/data/personas/fr_da/repos/fr_da-p12

## Summary
This internal tool processes healthcare data using a data pipeline orchestrated with Airflow, cleans the data with pandas, and performs statistical analysis with SciPy. The pipeline extracts, transforms, and loads data, while the analysis module calculates descriptive statistics. The tool is designed for a healthcare client and runs locally with a make dev command.

## Code-verified stack
- Python: `analysis.py: from scipy import stats`
- pandas: `clean.py: import pandas as pd`
- Airflow: `pipeline.py: from airflow import DAG`
- Statistics: `analysis.py: from scipy import stats`
