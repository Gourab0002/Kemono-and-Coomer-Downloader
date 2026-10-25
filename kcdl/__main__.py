try:
    import requests  # noqa: F401
except ImportError:
    raise SystemExit(
        "Install dependencies first: py -3 -m pip install -r requirements.txt"
    )

from kcdl.cli import main

if __name__ == "__main__":
    main()
