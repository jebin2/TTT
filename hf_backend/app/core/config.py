import os

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
