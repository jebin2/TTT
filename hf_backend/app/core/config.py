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

    # opencode budget. big-pickle reports no progress at all, so the worker
    # estimates a runtime from the prompt size and both the progress curve and
    # the kill deadline are derived from that one estimate — see
    # app/services/worker.py. These are env-tunable so a slow host can be fixed
    # without a code change.
    #
    # CHARS_PER_SECOND is deliberately pessimistic. Guessing low only makes a
    # run wait longer; guessing high kills a task that was about to finish,
    # which is what happened at 600s. Raise it only with evidence from a real
    # run, and raise MIN_SECONDS first — that is the floor every prompt pays.
    OPENCODE_CHARS_PER_SECOND = int(os.environ.get('TTT_OPENCODE_CHARS_PER_SECOND', 120))
    OPENCODE_MIN_SECONDS = int(os.environ.get('TTT_OPENCODE_MIN_SECONDS', 1200))
    OPENCODE_MAX_SECONDS = int(os.environ.get('TTT_OPENCODE_MAX_SECONDS', 7200))
    # Kill at estimate * this, so a run that overruns its estimate still gets a
    # margin instead of dying the instant it crosses the line.
    OPENCODE_TIMEOUT_SLACK = float(os.environ.get('TTT_OPENCODE_TIMEOUT_SLACK', 1.5))
    OPENCODE_PROGRESS_INTERVAL = int(os.environ.get('TTT_OPENCODE_PROGRESS_INTERVAL', 10))

settings = Config()

os.makedirs(settings.UPLOAD_FOLDER, exist_ok=True)
os.makedirs(settings.TEMP_DIR, exist_ok=True)
