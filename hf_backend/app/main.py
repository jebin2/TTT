import sys
from contextlib import asynccontextmanager

# Nothing logs at import time, so this is the earliest point that matters.
# Every app log line goes through sys.stdout, and when that is a pipe — always,
# under Docker — CPython block-buffers it. A whole run then produced no output
# for minutes and then landed in one burst: the "stuck at 42%" that was really
# a log pipeline hiding a live task behind a stale timestamp.
#
# The Dockerfile sets ENV PYTHONUNBUFFERED=1, but an empty or "0" value in a
# compose `environment:` block or .env file silently reverts it to buffered, so
# force write-through in-process rather than trusting the env. Measured
# equivalent to PYTHONUNBUFFERED=1: first byte at t=0.03s instead of t=2.02s,
# which is when the process exited.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(line_buffering=True, write_through=True)
    except (AttributeError, ValueError):
        pass  # not a real TextIOWrapper (test capture, or already detached)

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
