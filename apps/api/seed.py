"""Creates (or resets) the demo account from DEMO_EMAIL / DEMO_PASSWORD with the AI/ML
persona and one saved search. Run: uv run python -m apps.api.seed"""

import asyncio
import os
import sys

from dotenv import load_dotenv

from apps.api import db
from apps.api.auth import hash_password


async def main() -> None:
    load_dotenv()
    pool = await db.open_pool()
    try:
        user = await db.fetchone(
            pool, "INSERT INTO users (email, password_hash, account, settings) "
                  "VALUES (lower(%s), %s, 'fr_ml', '{\"weekly_connects_budget\": 80}') "
                  "ON CONFLICT (email) DO UPDATE SET password_hash = excluded.password_hash "
                  "RETURNING id", os.environ["DEMO_EMAIL"], hash_password(os.environ["DEMO_PASSWORD"]))
        await db.fetchone(
            pool, "INSERT INTO saved_searches (user_id, skills, every_minutes) "
                  "SELECT %s, ARRAY['LangGraph', 'RAG'], 60 WHERE NOT EXISTS "
                  "(SELECT 1 FROM saved_searches WHERE user_id = %s) RETURNING id",
            user["id"], user["id"])
        print(f"demo account ready: {os.environ['DEMO_EMAIL']} (password in .env)")
    finally:
        await pool.close()


if __name__ == "__main__":
    loop = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    asyncio.run(main(), loop_factory=loop)
