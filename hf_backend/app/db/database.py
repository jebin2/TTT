import aiosqlite
from app.core.config import settings
from custom_logger import logger_config as logger

async def init_db():
    logger.info(f"Initializing database at {settings.DATABASE_FILE}")
    async with aiosqlite.connect(settings.DATABASE_FILE) as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS text_tasks
                     (id TEXT PRIMARY KEY,
                      input_text TEXT NOT NULL,
                      system_prompt TEXT,
                      status TEXT NOT NULL,
                      result TEXT,
                      created_at TEXT NOT NULL,
                      processed_at TEXT,
                      progress INTEGER DEFAULT 0,
                      progress_text TEXT,
                      hide_from_ui INTEGER DEFAULT 0)''')
        await db.commit()
    logger.info("Database initialized successfully.")
