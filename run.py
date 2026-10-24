#!/usr/bin/env python3
"""Starts Project Blindsight directly from the source folder, without installation and without dependencies.

  python run.py                 web UI at http://127.0.0.1:8765
  python run.py --port 9000     other port
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from blindsight.web.server import main  # noqa: E402

if __name__ == "__main__":
    main()
