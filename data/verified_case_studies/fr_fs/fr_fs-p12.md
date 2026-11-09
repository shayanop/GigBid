# Logistics Billing & Task Automation Tool (code-verified)

Project: fr_fs-p12  
Repository: https://github.com/shayanop/GigBid/tree/master/data/personas/fr_fs/repos/fr_fs-p12

## Summary
This internal logistics tool integrates billing via Stripe, leveraging Python for backend logic. Background jobs are orchestrated with Celery and Redis, ensuring reliable task execution. A TypeScript/Node.js Express server exposes the API for client interaction.

## Code-verified stack
- Python: `billing.py: import stripe`
- Celery: `tasks.py: from celery import Celery`
- Redis: `tasks.py: import redis`
- Stripe: `billing.py: import stripe`
- TypeScript: `server.ts: import express from 'express';`
- Node.js: `server.ts: import express from 'express';`
