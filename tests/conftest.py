"""Session fixtures: make sure generated data exists before the suite runs."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MAN = ROOT / "data" / "equipment" / "manuals" / "AX300_manual.pdf"
TICKS = ROOT / "data" / "equipment" / "tickets" / "tickets.csv"


@pytest.fixture(scope="session", autouse=True)
def generated_data() -> None:
    if not MAN.is_file():
        subprocess.run([sys.executable, str(ROOT / "scripts" / "gen_manuals.py")], check=True, cwd=ROOT)
    if not TICKS.is_file():
        subprocess.run([sys.executable, str(ROOT / "scripts" / "gen_data.py")], check=True, cwd=ROOT)
