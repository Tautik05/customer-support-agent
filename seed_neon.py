import asyncio
import logging
import os
import sys
from dotenv import load_dotenv

# Force reload of .env
load_dotenv(override=True)

from app.config import settings
from app.db.database import init_db, engine
from app.db.seed_data import seed_database

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("seed_neon")

async def main():
    db_url = settings.get_async_db_url()
    logger.info(f"Target Database URL: {db_url.split('@')[-1] if '@' in db_url else db_url}")

    if "sqlite" in db_url:
        logger.warning("DATABASE_URL is currently pointing to SQLite fallback.")
        logger.warning("Please ensure DATABASE_URL in .env is set to your Neon PostgreSQL connection string.")
        logger.warning("Example: DATABASE_URL=postgresql+asyncpg://neondb_owner:password@ep-xyz.region.aws.neon.tech/neondb?sslmode=require")

    logger.info("Initializing schema tables in PostgreSQL...")
    await init_db()

    logger.info("Seeding realistic ground-truth support data...")
    result = await seed_database()

    logger.info(f"✅ Seeding Complete! Summary: {result}")

if __name__ == "__main__":
    asyncio.run(main())
