"""Docker HEALTHCHECK: the monitor writes data/heartbeat after every check."""

import os
import sys
import time
from pathlib import Path

base = Path(__file__).resolve().parent
db_path = Path(os.getenv("DATABASE_PATH", "data/aurix.db"))
if not db_path.is_absolute():
    db_path = base / db_path
heartbeat = db_path.parent / "heartbeat"
interval = int(os.getenv("CHECK_INTERVAL_SECONDS", "300") or 300)

try:
    age = time.time() - heartbeat.stat().st_mtime
except FileNotFoundError:
    sys.exit(1)
sys.exit(0 if age < interval * 3 + 120 else 1)
