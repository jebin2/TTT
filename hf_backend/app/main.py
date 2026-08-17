from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.api.routes import router
from app.core.config import settings
from app.db.database import init_db
from custom_logger import logger_config as logger

@asynccontextmanager
async def lifespan(app: FastAPI):
    if not settings.API_KEY:
        logger.error("="*60)
        logger.error("TTT_API_KEY is not set - refusing to start")
        logger.error("Every /api request needs this value in the X-API-Key header.")
        logger.error("Generate one with:")
        logger.error("  export TTT_API_KEY=$(python3 -c 'import secrets;print(\"ttt_\"+secrets.token_urlsafe(32))')")
        logger.error("="*60)
        raise RuntimeError("TTT_API_KEY environment variable is required")

    logger.info("="*60)
    logger.info("TTT Runner API Server Starting Up")
    logger.info("="*60)
    logger.info("Worker will start automatically on first task")
    logger.info("="*60)
    
    await init_db()
    yield
    logger.info("TTT Runner API Server Shutting Down")

app = FastAPI(title="TTT Runner API", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(router)
