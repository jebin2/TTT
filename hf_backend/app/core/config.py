import os
from pathlib import Path

from dotenv import load_dotenv

# hf_backend/.env, resolved from this file so it is found whatever the CWD is.
# override=False keeps real env vars (HF Space secrets, `export`) ahead of the file.
load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)


class Config:
    PORT = int(os.environ.get('PORT', 7860))
    UPLOAD_FOLDER = 'uploads'
    TEMP_DIR = 'temp_dir'
    DATABASE_FILE = 'text_tasks.db'

    # Auth: every /api/* request must send this value in the X-API-Key header
    API_KEY = os.environ.get('TTT_API_KEY')
    API_KEY_HEADER = 'X-API-Key'

    # Core logic settings
    POLL_INTERVAL = 3
    CLEANUP_DAYS = 10

settings = Config()

os.makedirs(settings.UPLOAD_FOLDER, exist_ok=True)
os.makedirs(settings.TEMP_DIR, exist_ok=True)
