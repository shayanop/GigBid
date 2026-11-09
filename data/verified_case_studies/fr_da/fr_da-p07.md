# Internal Legal Data Tool (code-verified)

Project: fr_da-p07  
Repository: https://github.com/shayanop/GigBid/tree/master/data/personas/fr_da/repos/fr_da-p07

## Summary
The repository contains an internal tool designed for a legal client. It is implemented in Python, leveraging pandas for data manipulation and Snowflake for data warehousing. The tool can be run locally with `make dev` and includes documentation in the docs folder.

## Code-verified stack
- Python: `app.py: def main() -> None:`
- pandas: `clean.py: import pandas as pd`
- Snowflake: `models.sql: USE WAREHOUSE analytics_wh;`
