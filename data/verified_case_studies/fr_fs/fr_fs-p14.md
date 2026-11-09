# Travel Client Billing & Order Tool (code-verified)

Project: fr_fs-p14  
Repository: https://github.com/shayanop/GigBid/tree/master/data/personas/fr_fs/repos/fr_fs-p14

## Summary
This internal tool for a travel client automates billing and order processing using Stripe integration and PostgreSQL for data storage. The backend is built in Python with Celery for asynchronous tasks, while the frontend uses Next.js and TypeScript to provide a user-friendly interface.

## Code-verified stack
- Python: `billing.py: import stripe`
- Celery: `tasks.py: from celery import Celery`
- Stripe: `billing.py: import stripe`
- Next.js: `page.tsx: import Link from 'next/link';`
- TypeScript: `page.tsx: import Link from 'next/link';`
- PostgreSQL: `schema.sql: CREATE INDEX idx_orders_user ON orders(user_id);`
