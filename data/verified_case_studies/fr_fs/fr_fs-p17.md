# E-commerce Billing and Order Management Tool (code-verified)

Project: fr_fs-p17  
Repository: https://github.com/shayanop/GigBid/tree/master/data/personas/fr_fs/repos/fr_fs-p17

## Summary
This internal tool integrates Stripe billing with a Next.js/React front-end, using TypeScript for type safety. The application stores and indexes order data in PostgreSQL, and uses Python to interact with Stripe's API. The front‑end components provide navigation and state management for order and billing views.

## Code-verified stack
- Python: `billing.py: import stripe`
- Stripe: `billing.py: import stripe`
- React: `App.tsx: import { useState } from 'react';`
- Next.js: `page.tsx: import Link from 'next/link';`
- TypeScript: `App.tsx: import { useState } from 'react';`
- PostgreSQL: `schema.sql: CREATE INDEX idx_orders_user ON orders(user_id);`
