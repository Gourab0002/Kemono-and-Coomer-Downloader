"""English menu. The program itself lives in the repository root."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    import requests  # noqa: F401
except ImportError:
    raise SystemExit(
        "Install dependencies first: py -3 -m pip install -r requirements.txt"
    )

if "--lang" not in sys.argv:
    sys.argv[1:1] = ["--lang", "en"]

from kcdl.cli import main

if __name__ == "__main__":
    main()
