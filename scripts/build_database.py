"""Prepare the checked database and compressed download before serving traffic."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import app  # noqa: E402

action = "Reused" if app.config["DATABASE_REUSED"] else "Built"
print(f"{action} checked database and compressed snapshot")
