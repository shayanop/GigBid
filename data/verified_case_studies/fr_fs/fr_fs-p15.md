# Internal Manufacturing Tool (code-verified)

Project: fr_fs-p15  
Repository: https://github.com/shayanop/GigBid/tree/master/data/personas/fr_fs/repos/fr_fs-p15

## Summary
The repository contains an internal tool for a manufacturing client. It uses Python and FastAPI to expose a web API, with a TypeScript front‑end built in App.tsx. The back‑end stores data in PostgreSQL, as shown by the schema and index creation.

## Code-verified stack
- Python: `app.py: from fastapi import FastAPI`
- FastAPI: `app.py: from fastapi import FastAPI`
- TypeScript: `App.tsx: type Props = { id: string };`
- PostgreSQL: `schema.sql: CREATE INDEX idx_orders_user ON orders(user_id);`
