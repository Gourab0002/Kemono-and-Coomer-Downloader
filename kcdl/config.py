"""Settings stored in config/conf.json."""

import json
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "conf.json"

DEFAULTS = {
    "get_empty_posts": False,
    "process_from_oldest": False,
    "post_info": "md",
    "save_info": True,
    "separate_folders": True,
    "download_dir": "",
    "language": "en",
    "file_interval": 1.0,
    "api_interval": 0.4,
    "connect_timeout": 5.0,
    "read_timeout": 120.0,
}


def normalize(data):
    """Fill defaults and keep values inside the ranges the sites allow."""
    merged = dict(DEFAULTS)
    if isinstance(data, dict):
        merged.update(data)

    merged["get_empty_posts"] = bool(merged["get_empty_posts"])
    merged["process_from_oldest"] = bool(merged["process_from_oldest"])
    merged["save_info"] = bool(merged["save_info"])
    merged["separate_folders"] = _bool(merged["separate_folders"], True)
    picked = accepted_download_dir(merged.get("download_dir"))
    merged["download_dir"] = "" if picked is None else picked
    if str(merged["post_info"]).lower() not in ("md", "txt"):
        merged["post_info"] = "md"
    else:
        merged["post_info"] = str(merged["post_info"]).lower()
    if merged["language"] not in ("en", "pt"):
        merged["language"] = "en"

    merged["file_interval"] = max(1.0, _float(merged["file_interval"], 1.0))
    merged["api_interval"] = max(0.0, _float(merged["api_interval"], 0.4))
    merged["connect_timeout"] = min(30.0, max(2.0, _float(merged["connect_timeout"], 5.0)))
    merged["read_timeout"] = min(600.0, max(10.0, _float(merged["read_timeout"], 120.0)))
    return merged


def accepted_download_dir(value):
    """Return a folder path, '' when unset, or None when the path is a file."""
    text = str(value or "").strip().strip('"')
    if not text:
        return ""
    path = Path(text).expanduser()
    try:
        if path.exists() and not path.is_dir():
            return None
        return str(path.resolve())
    except OSError:
        return str(path)


def resolve_download_dir(config, override=None):
    """Use the command folder when one was given, otherwise the saved folder."""
    if override:
        return Path(override).expanduser()
    saved = accepted_download_dir((config or {}).get("download_dir"))
    if saved:
        return Path(saved)
    return Path.cwd()


def _bool(value, fallback):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("1", "true", "yes"):
            return True
        if text in ("0", "false", "no"):
            return False
    return fallback


def _float(value, fallback):
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def load():
    if not CONFIG_PATH.exists():
        return normalize({})
    with CONFIG_PATH.open("r", encoding="utf-8") as handle:
        return normalize(json.load(handle))


def save(config):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = normalize(config)
    text = json.dumps(payload, indent=4, ensure_ascii=False) + "\n"
    temporary = CONFIG_PATH.with_suffix(".json.tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(CONFIG_PATH)
    return payload


@dataclass
class Settings:
    download_dir: Path
    language: str
    get_empty_posts: bool
    process_from_oldest: bool
    save_info: bool
    separate_folders: bool
    post_info: str
    file_interval: float
    api_interval: float
    connect_timeout: float
    read_timeout: float
    limit: int | None = None

    @property
    def timeouts(self):
        return (self.connect_timeout, self.read_timeout)


def settings_from(config, download_dir, language=None, limit=None):
    data = normalize(config)
    return Settings(
        download_dir=Path(download_dir),
        language=language or data["language"],
        get_empty_posts=data["get_empty_posts"],
        process_from_oldest=data["process_from_oldest"],
        save_info=data["save_info"],
        separate_folders=data["separate_folders"],
        post_info=data["post_info"],
        file_interval=data["file_interval"],
        api_interval=data["api_interval"],
        connect_timeout=data["connect_timeout"],
        read_timeout=data["read_timeout"],
        limit=limit,
    )
