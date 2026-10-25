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
from kcdl.media import assign_names, sanitize_filename, write_json

PAWCHIVE_FILES = "https://file.pawchive.pw"
PAWCHIVE_HOST = "file.pawchive.pw"
PREVIEW_INTERVAL = 0.2
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
        if url in seen or health.is_blocked(hostname(url)):
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


def _follow(session, url, referer, health, pace, timeouts, on_note, name=""):
    """GET one candidate, following redirects until a body or a dead host."""
    current = url
    for _ in range(5):
        host = hostname(current)
        if health.is_blocked(host):
            raise DeadHost(host)
        if on_note:
            on_note("trying", host=host, name=name)
        pace.wait(host, pace.interval if host == PAWCHIVE_HOST else min(pace.interval, PREVIEW_INTERVAL))
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
            if health.note_down(host) and on_note:
                on_note("dead-host", host=host)
            raise DeadHost(host) from exc
        if response.status_code in REDIRECTS:
            location = urljoin(current, response.headers.get("location") or "")
            response.close()
            if not location:
                raise DownloadError("Redirect with no location")
            next_host = hostname(location)
            if health.is_dead(next_host):
                if health.skip_redirect(host) and on_note:
                    on_note("skip-host", host=host)
                raise DeadHost(next_host)
            current = location
            continue
        return response, current
    raise DownloadError("Too many redirects")


def download_candidates(session, candidates, dest, health, pace, referer, timeouts, on_note=None):
    """Try each URL. Return a result dict or raise DownloadError."""
    errors = []
    for url, kind in candidates:
        if health.is_blocked(hostname(url)):
            continue
        for attempt in range(3):
            try:
                response, final_url = _follow(
                    session, url, referer, health, pace, timeouts, on_note, dest.name
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
                if status == 404 and hostname(url) == PAWCHIVE_HOST and health.note_miss(PAWCHIVE_HOST) and on_note:
                    on_note("skip-host", host=PAWCHIVE_HOST)
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
            health.note_hit(hostname(final_url))
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


def _flat_name(folder, name, path, manifest, post_id):
    """Pick a file name that does not replace another post's file."""
    owners = {}
    for remote, record in manifest.items():
        if isinstance(record, dict) and record.get("name"):
            owners[str(record["name"]).lower()] = remote
    prefix = sanitize_filename(post_id)[:40] or "post"
    candidate = name
    number = 2
    while number < 100:
        owner = owners.get(candidate.lower())
        on_disk = (folder / candidate).exists()
        if (owner is None or owner == path) and (owner == path or not on_disk):
            return candidate
        candidate = f"{prefix}-{name}" if number == 2 else f"{prefix}-{number}-{name}"
        number += 1
    return candidate


def _take_legacy_manifest(folder, manifest_path):
    """Move a download.json out of the media folder when a state path is set."""
    legacy = Path(folder) / "download.json"
    target = Path(manifest_path) if manifest_path else legacy
    try:
        same = target.resolve() == legacy.resolve()
    except OSError:
        same = str(target) == str(legacy)
    if same or not legacy.exists():
        return target
    merged = _load_manifest(legacy)
    merged.update(_load_manifest(target))
    if merged:
        write_json(target, {"files": merged})
    try:
        legacy.unlink()
    except OSError:
        pass
    return target


def download_post_files(
    session, site, post, folder, health, pace, timeouts,
    on_note=None, on_file=None, flat=False, manifest_path=None,
):
    """Download every file for one post. Existing full files are skipped."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    manifest_path = _take_legacy_manifest(folder, manifest_path)
    manifest = _load_manifest(manifest_path)
    referer = post.get("link") or site.root + "/"
    outcomes = []

    named = list(assign_names(post.get("files") or []))
    total = len(named)
    for index, (item, name) in enumerate(named, start=1):
        record = manifest.get(item["path"]) if isinstance(manifest.get(item["path"]), dict) else None
        if flat and not record:
            name = _flat_name(folder, name, item["path"], manifest, post.get("id") or "post")
        dest = _existing_file(folder, name, record)
        if on_note:
            on_note("file", index=index, total=total, name=dest.name)
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
