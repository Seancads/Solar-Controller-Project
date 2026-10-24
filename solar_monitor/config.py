"""Where things live on disk. Everything else asks this file, nothing hard-codes paths.

Environment variables (all optional):
    SOLAR_PORT            port the web app listens on (default 5000)
    SOLAR_ADMIN_PASSWORD  ask for this password before showing the web pages
    SOLAR_DB              database file (default data/solar.db)
    SOLAR_REPORTS         folder for saved reports (default data/reports)
    SOLAR_DEBUG=1         Flask debug mode (never use on a shared network)
"""

import os

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_DIR, "data")
FIRMWARE_DIR = os.path.join(PROJECT_DIR, "firmware")


def db_path():
    # Read at call time so tests (or you) can point SOLAR_DB elsewhere.
    return os.environ.get("SOLAR_DB", os.path.join(DATA_DIR, "solar.db"))


def reports_dir():
    return os.environ.get("SOLAR_REPORTS", os.path.join(DATA_DIR, "reports"))


def port():
    return int(os.environ.get("SOLAR_PORT", "5000"))
