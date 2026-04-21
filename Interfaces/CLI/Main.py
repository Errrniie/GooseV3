"""
CLI Main.py - entry point that launches the core orchestrator.
"""

from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from Core.Orchestrator import run


if __name__ == "__main__":
    run()

 