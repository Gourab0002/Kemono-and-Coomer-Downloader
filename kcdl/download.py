"""Download one post's files, with fallbacks when a file server is down."""

import json
from pathlib import Path
from urllib.parse import urljoin

import requests

from kcdl.http import (
    FILE_HEADERS,
    REDIRECTS,
    TRANSIENT,
    DeadHost,
    DownloadError,
    hostname,
)
from kcdl.media import assign_names, write_json

PAWCHIVE_FILES = "https://file.pawchive.pw"
TEXT_TYPES = {"text/html", "text/plain", "application/json"}


def build_candidates(site, remote_path, server, health):
    """URLs to try, best first. Preview images are last."""
    path = remote_path.replace("\\", "/")
    if path.startswith("http://") or path.startswith("https://"):
        return [(path, "original")]

    candidates = []
    if server:
        candidates.append((server.rstrip("/") + "/data" + path, "original"))
    candidates.append((site.root + "/data" + path, "original"))
    if site.name != "pawchive":
        candidates.append((PAWCHIVE_FILES + "/data" + path, "original"))
    candidates.append((site.image_root + "/thumbnail/data" + path, "preview"))

    open_candidates = []
    seen = set()
    for url, kind in candidates:
        if url in seen or health.is_dead(hostname(url)):
            continue
        seen.add(url)
        open_candidates.append((url, kind))
    return open_candidates


def _content_type(response):
    raw = response.headers.get("content-type") or ""
    return raw.split(";", 1)[0].strip().lower()


def _save_body(response, dest):
    partial = Path(str(dest) + ".partial")
    written = 0
    try:
        with partial.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 64):
                if chunk:
                    handle.write(chunk)
                    written += len(chunk)
    except Exception:
        partial.unlink(missing_ok=True)
        raise
    finally:
        response.close()
    if written <= 0:
        partial.unlink(missing_ok=True)
        raise DownloadError("Empty file")
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial.replace(dest)
    return written


def _follow(session, url, referer, health, pace, timeouts, on_note):
    """GET one candidate, following redirects until a body or a dead host."""
    current = url
    for _ in range(5):
        host = hostname(current)
        if health.is_dead(host):
            raise DeadHost(host)
        pace.wait()
        headers = dict(FILE_HEADERS)
        headers["Referer"] = referer
        try:
            response = session.get(
                current,
                headers=headers,
                timeout=timeouts,
                stream=True,
                allow_redirects=False,
            )
        except (requests.ConnectTimeout, requests.ConnectionError) as exc:
            if health.mark_dead(host) and on_note:
                on_note("dead-host", host=host)
            raise DeadHost(host) from exc
        if response.status_code in REDIRECTS:
            location = urljoin(current, response.headers.get("location") or "")
            response.close()
            if not location:
                raise DownloadError("Redirect with no location")
            next_host = hostname(location)
            if health.is_dead(next_host):
                raise DeadHost(next_host)
            current = location
            continue
        return response, current
    raise DownloadError("Too many redirects")


def download_candidates(session, candidates, dest, health, pace, referer, timeouts, on_note=None):
    """Try each URL. Return a result dict or raise DownloadError."""
    errors = []
    for url, kind in candidates:
        if health.is_dead(hostname(url)):
            continue
        for attempt in range(3):
            try:
                response, final_url = _follow(
                    session, url, referer, health, pace, timeouts, on_note
                )
            except DeadHost as exc:
                errors.append(f"{url} ({exc.host} unreachable)")
                break
            except requests.ReadTimeout:
                if attempt == 2:
                    errors.append(f"{url} (timed out)")
                continue
            except requests.RequestException as exc:
                errors.append(f"{url} ({exc.__class__.__name__})")
                break

            status = response.status_code
            if status in TRANSIENT:
                response.close()
                if attempt == 2:
                    errors.append(f"{url} (HTTP {status})")
                continue
            if status != 200:
                response.close()
                errors.append(f"{url} (HTTP {status})")
                break
            if _content_type(response) in TEXT_TYPES:
                response.close()
                errors.append(f"{url} (not a file)")
                break
            try:
                nbytes = _save_body(response, dest)
            except (OSError, requests.RequestException, DownloadError) as exc:
                errors.append(f"{url} ({exc})")
                break
            return {
                "status": "downloaded",
                "kind": kind,
                "nbytes": nbytes,
                "source": final_url,
            }
    detail = "; ".join(errors) if errors else "no file server available"
    raise DownloadError(detail)


def _load_manifest(path):
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    files = data.get("files") if isinstance(data, dict) else None
    return files if isinstance(files, dict) else {}


def _existing_file(folder, name, record):
    current = folder / name
    if record and record.get("name"):
        previous = folder / record["name"]
        if previous.exists() and previous.stat().st_size > 0:
            return previous
    if current.exists() and current.stat().st_size > 0:
        return current
    return current


def _already_complete(dest, record):
    if not record or record.get("kind") != "original":
        return False
    if not dest.exists() or not dest.is_file():
        return False
    size = dest.stat().st_size
    return size > 0 and size == record.get("bytes")


def download_post_files(session, site, post, folder, health, pace, timeouts, on_note=None, on_file=None):
    """Download every file for one post. Existing full files are skipped."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    manifest_path = folder / "download.json"
    manifest = _load_manifest(manifest_path)
    referer = post.get("link") or site.root + "/"
    outcomes = []

    for item, name in assign_names(post.get("files") or []):
        record = manifest.get(item["path"]) if isinstance(manifest.get(item["path"]), dict) else None
        dest = _existing_file(folder, name, record)
        if _already_complete(dest, record):
            outcome = {
                "name": dest.name,
                "status": "skipped",
                "kind": "original",
                "nbytes": dest.stat().st_size,
                "source": record.get("source") or "",
                "error": "",
                "path": item["path"],
            }
            outcomes.append(outcome)
            if on_file:
                on_file(outcome)
            continue

        candidates = build_candidates(site, item["path"], item.get("server"), health)
        kept_preview = (
            record
            and record.get("kind") == "preview"
            and dest.exists()
            and dest.stat().st_size > 0
        )
        if kept_preview:
            candidates = [item for item in candidates if item[1] == "original"]
        try:
            result = download_candidates(
                session,
                candidates,
                dest,
                health,
                pace,
                referer,
                timeouts,
                on_note,
            )
        except DownloadError as exc:
            if kept_preview:
                outcome = {
                    "name": dest.name,
                    "status": "skipped",
                    "kind": "preview",
                    "nbytes": dest.stat().st_size,
                    "source": record.get("source") or "",
                    "error": "",
                    "path": item["path"],
                }
            elif dest.exists() and dest.stat().st_size > 0 and record:
                outcome = {
                    "name": dest.name,
                    "status": "skipped",
                    "kind": record.get("kind") or "preview",
                    "nbytes": dest.stat().st_size,
                    "source": record.get("source") or "",
                    "error": "",
                    "path": item["path"],
                }
            else:
                outcome = {
                    "name": name,
                    "status": "failed",
                    "kind": "",
                    "nbytes": 0,
                    "source": "",
                    "error": str(exc),
                    "path": item["path"],
                }
            outcomes.append(outcome)
            if on_file:
                on_file(outcome)
            continue

        manifest[item["path"]] = {
            "name": dest.name,
            "bytes": result["nbytes"],
            "kind": result["kind"],
            "source": result["source"],
        }
        write_json(manifest_path, {"files": manifest})
        outcome = {
            "name": dest.name,
            "status": "downloaded",
            "kind": result["kind"],
            "nbytes": result["nbytes"],
            "source": result["source"],
            "error": "",
            "path": item["path"],
        }
        outcomes.append(outcome)
        if on_file:
            on_file(outcome)

    if manifest:
        write_json(manifest_path, {"files": manifest})
    return outcomes
