#!/usr/bin/env python3
"""Startet Project Blindsight direkt aus dem Quellordner, ohne Installation und ohne Abhaengigkeiten.

  python run.py                 Web UI auf http://127.0.0.1:8765
  python run.py --port 9000     anderer Port
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from blindsight.web.server import main  # noqa: E402

if __name__ == "__main__":
    main()
