#!/usr/bin/env python3
"""Run vanaf elke werkmap met de projectvenv; extra vlaggen gaan naar de CLI."""
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
raise SystemExit(subprocess.call(
    [sys.executable, "-m", "lusmaker.cli", "heat", "sync-vlaanderen",
     "--output", str(root / ".route-data" / "vlaanderen"), *sys.argv[1:]], cwd=root,
))
