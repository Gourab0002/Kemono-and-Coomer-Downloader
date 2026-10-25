"""Menu em português. O programa fica na raiz do repositório."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    import requests  # noqa: F401
except ImportError:
    raise SystemExit(
        "Instale as dependências primeiro: py -3 -m pip install -r requirements.txt"
    )

if "--lang" not in sys.argv:
    sys.argv[1:1] = ["--lang", "pt"]

from kcdl.cli import main

if __name__ == "__main__":
    main()
