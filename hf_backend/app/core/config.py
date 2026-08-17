import os
from pathlib import Path

from jebin_lib import load_env

# Same convention as ttt/__init__.py: ~/.env, ~/.envs/.env,
# ~/.envs/.<project>_env, then <project>/.env. The path is resolved from
# __file__ so it lands on hf_backend/ whatever the CWD is.
load_env(str(Path(__file__).resolve().parents[2]))


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
