"""Run from a checkout with Python 3.12+; no installation is required."""
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1] / "src"))
from cadtoolbox.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
