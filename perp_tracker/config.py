import os
from pathlib import Path

APP_DIR = Path(os.environ.get("PERP_TRACKER_DIR", Path.home() / ".perp_tracker"))
DB_PATH = Path(os.environ.get("PERP_TRACKER_DB", APP_DIR / "tracker.db"))

DEFAULT_POLL_INTERVAL = int(os.environ.get("PERP_TRACKER_POLL_INTERVAL", "60"))
DEFAULT_HTTP_TIMEOUT = float(os.environ.get("PERP_TRACKER_TIMEOUT", "15.0"))
USER_AGENT = "perp-tracker/0.1.0"

def ensure_app_dir() -> Path:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    return APP_DIR
