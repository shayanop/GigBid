# Healthcare Data Analysis Tool (code-verified)

Project: fr_da-p06  
Repository: https://github.com/shayanop/GigBid/tree/master/data/personas/fr_da/repos/fr_da-p06

## Summary
An internal tool for a healthcare client that performs data analysis using Python and statistical methods from SciPy. The tool leverages dbt to materialize models into tables, facilitating reproducible data pipelines. It is designed for local development via a makefile and documented in the docs folder.

## Code-verified stack
- Python: `analysis.py: from scipy import stats`
- Statistics: `analysis.py: from scipy import stats`
- dbt: `models.sql: {{ config(materialized='table') }}`
