"""Post normalization, file names, fetch ranges, and the info file."""

import json
import re
from html.parser import HTMLParser
from pathlib import Path

INLINE_RE = re.compile(
    r"""(?:src|href)\s*=\s*["'](?:https?://[^"']+)?(/[0-9a-f]{2}/[0-9a-f]{2}/[0-9a-f]{64}\.[A-Za-z0-9]+)""",
    re.IGNORECASE,
)

PAGE_SIZE = 50
RESERVED = {"CON", "PRN", "AUX", "NUL"}
RESERVED.update(f"COM{i}" for i in range(1, 10))
RESERVED.update(f"LPT{i}" for i in range(1, 10))


class FetchMode:
    """Which posts to take from a profile.

    kind is "all", "page", "range", or "ids".
    start and end are ints, or the words "start" and "end" for page offsets.
    """

    def __init__(self, kind, start=None, end=None):
        self.kind = kind
        self.start = start
        self.end = end


def last_offset(post_count):
    count = int(post_count or 0)
    if count <= 0:
        return 0
    return ((count - 1) // PAGE_SIZE) * PAGE_SIZE


def snap_offset(value):
    if value in (None, "start"):
        return 0
    if isinstance(value, str) and value.strip().lower() == "end":
        return "end"
    number = int(str(value).strip())
    if number < 0:
        raise ValueError(f"Offset cannot be negative: {value}")
    return (number // PAGE_SIZE) * PAGE_SIZE


def mode_from_offset_text(text):
    """Turn '50' into one page and '0-750' or 'start-end' into a range."""
    raw = (text or "").strip()
    if not raw:
        raise ValueError("empty offset")
    if "-" in raw:
        left, right = raw.split("-", 1)
        return FetchMode("range", left.strip() or "start", right.strip() or "end")
    return FetchMode("page", raw)


def page_offsets(mode, post_count):
    """Offsets to request. None means walk every page until a short page."""
    if mode.kind in ("all", "ids"):
        return None
    if mode.kind == "page":
        offset = snap_offset(mode.start)
        if offset == "end":
            offset = last_offset(post_count)
        return [offset]
    if mode.kind == "range":
        start = snap_offset(mode.start)
        end = snap_offset(mode.end)
        if start == "end":
            start = last_offset(post_count)
        if end == "end":
            end = last_offset(post_count)
        if end < start:
            start, end = end, start
        return list(range(start, end + 1, PAGE_SIZE))
    raise ValueError(f"Unknown fetch mode: {mode.kind}")


def numeric_id(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def in_id_range(post_id, start, end):
    """Inclusive numeric range. Text order would put '9' after '100'."""
    number = numeric_id(post_id)
    left = numeric_id(start)
    right = numeric_id(end)
    if number is None or left is None or right is None:
        return False
    low, high = (left, right) if left <= right else (right, left)
    return low <= number <= high


def sort_posts(posts, oldest_first):
    def key(post):
        published = post.get("published") or ""
        number = numeric_id(post.get("id"))
        return (published, number if number is not None else 0)

    posts.sort(key=key, reverse=not oldest_first)
    return posts


def inline_paths(content):
    if not content:
        return []
    found = []
    seen = set()
    for match in INLINE_RE.finditer(content):
        path = match.group(1)
        if path not in seen:
            seen.add(path)
            found.append(path)
    return found


def collect_files(post, videos=None, servers=None):
    """Unique files in display order: main file, attachments, videos, inline images."""
    servers = servers or {}
    items = []

    def add(name, path, role):
        if not isinstance(path, str) or not path.strip():
            return
        cleaned = path.replace("\\", "/").strip()
        items.append({
            "name": name or "",
            "path": cleaned,
            "server": servers.get(cleaned),
            "role": role,
        })

    main = post.get("file") or {}
    if isinstance(main, dict):
        add(main.get("name"), main.get("path"), "file")
    for attachment in post.get("attachments") or []:
        if isinstance(attachment, dict):
            add(attachment.get("name"), attachment.get("path"), "attachment")
    for video in videos or []:
        if isinstance(video, dict):
            add(video.get("name"), video.get("path"), "video")
    for path in inline_paths(post.get("content") or ""):
        add(Path(path).name, path, "inline")

    unique = []
    seen = set()
    for item in items:
        if item["path"] in seen:
            continue
        seen.add(item["path"])
        unique.append(item)
    return unique


def _servers_from_previews(previews):
    servers = {}
    for preview in previews or []:
        if not isinstance(preview, dict):
            continue
        path = preview.get("path")
        server = preview.get("server")
        if path and server and path not in servers:
            servers[path] = server
    return servers


def _base_post(post, site, files):
    return {
        "id": str(post.get("id") or ""),
        "user": str(post.get("user") or ""),
        "service": post.get("service") or "",
        "title": post.get("title") or "",
        "content": post.get("content") or post.get("substring") or "",
        "published": post.get("published") or post.get("added") or "",
        "embed": post.get("embed") or {},
        "poll": post.get("poll"),
        "files": files,
        "site": site.name,
        "link": (
            f"{site.root}/{post.get('service')}/user/{post.get('user')}/post/{post.get('id')}"
        ),
    }


def normalize_list_post(raw, site):
    files = collect_files(raw)
    return _base_post(raw, site, files)


def normalize_detail(data, site):
    post = data.get("post") or data
    files = collect_files(
        post,
        videos=data.get("videos") or [],
        servers=_servers_from_previews(data.get("previews") or []),
    )
    return _base_post(post, site, files)


def sanitize_filename(value):
    text = str(value or "").strip()
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", text)
    text = text.strip(" .")
    text = re.sub(r"\s+", " ", text)
    if not text:
        return "file"
    stem = Path(text).stem.upper()
    if stem in RESERVED:
        text = "_" + text
    return text


def _extension(value):
    suffix = Path(str(value or "")).suffix
    if not suffix or len(suffix) > 10 or " " in suffix:
        return ""
    return suffix


def _clip(name, limit=120):
    if len(name) <= limit:
        return name
    suffix = Path(name).suffix
    keep = max(1, limit - len(suffix))
    return name[:keep].rstrip(" .") + suffix


def assign_names(files):
    used = set()
    named = []
    for index, item in enumerate(files, start=1):
        base = sanitize_filename(item.get("name") or "")
        if base == "file":
            base = f"file{index}"
        extension = _extension(item.get("name")) or _extension(item.get("path"))
        if extension and not base.lower().endswith(extension.lower()):
            base = f"{base}{extension}"
        filename = _clip(f"{index}-{base}")
        lowered = filename.lower()
        extra = 2
        while lowered in used:
            filename = _clip(f"{index}-{extra}-{base}")
            lowered = filename.lower()
            extra += 1
        used.add(lowered)
        named.append((item, filename))
    return named


class _HTMLToText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self._href = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "a":
            self._href = attributes.get("href") or ""
            self.parts.append("[")
        elif tag in ("p", "br", "div", "li"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            self.parts.append(f"]({self._href})")
            self._href = None
        elif tag in ("p", "div", "li"):
            self.parts.append("\n")

    def handle_data(self, data):
        self.parts.append(data)

    def text(self):
        collapsed = re.sub(r"\n{3,}", "\n\n", "".join(self.parts))
        return collapsed.strip()


def html_to_text(html):
    if not html:
        return ""
    parser = _HTMLToText()
    try:
        parser.feed(str(html))
        parser.close()
    except Exception:
        return re.sub(r"<[^>]+>", "", str(html)).strip()
    return parser.text()


def render_info(post, outcomes, file_format):
    title = post.get("title") or post.get("id") or "Post"
    body = html_to_text(post.get("content") or "")
    markdown = file_format == "md"
    lines = []
    if markdown:
        lines.append(f"# {title}")
    else:
        lines.append(f"Title: {title}")
    lines.append("")
    if post.get("published"):
        lines.append(f"Published: {post['published']}")
    if post.get("link"):
        lines.append(f"Link: {post['link']}")
    lines.append("")
    if body:
        lines.append(body)
        lines.append("")

    poll = post.get("poll") or None
    if isinstance(poll, dict) and poll:
        lines.append("Poll" if not markdown else "## Poll")
        lines.append("")
        if poll.get("title"):
            lines.append(poll["title"])
        for choice in poll.get("choices") or []:
            if isinstance(choice, dict):
                lines.append(f"- {choice.get('text', '')}: {choice.get('votes', 0)}")
        lines.append("")

    embed = post.get("embed") or {}
    if isinstance(embed, dict) and embed.get("url"):
        lines.append("Embed" if not markdown else "## Embed")
        lines.append("")
        lines.append(embed.get("url") or "")
        if embed.get("subject"):
            lines.append(str(embed["subject"]))
        if embed.get("description"):
            lines.append(str(embed["description"]))
        lines.append("")

    lines.append("Files" if not markdown else "## Files")
    lines.append("")
    if not outcomes:
        lines.append("(no files)")
    for outcome in outcomes:
        kind = " [preview]" if getattr(outcome, "kind", "") == "preview" else ""
        lines.append(f"- {outcome.name}{kind} — {outcome.status}")
        if outcome.source:
            lines.append(f"  {outcome.source}")
    lines.append("")
    return "\n".join(lines)


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(str(path) + ".tmp")
    temporary.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def creator_folder(download_dir, site, profile, service, user_id):
    name = sanitize_filename(profile.get("name") or "unknown")[:80]
    service_name = sanitize_filename(service)[:40]
    user = sanitize_filename(user_id)[:80]
    folder = Path(download_dir) / site.name / f"{name}-{service_name}-{user}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def manifest_file(download_dir, site_name, creator_name, post_id, flat):
    """Resume record. Kept outside the folder that holds the downloaded files."""
    base = Path(download_dir) / "kcdl-state" / site_name / creator_name
    if flat:
        return base / "download.json"
    return base / "posts" / sanitize_filename(post_id)[:80] / "download.json"


def info_file(download_dir, site_name, creator_name, post_id, extension):
    """Post info file. Kept beside the resume record, not with the pictures."""
    suffix = "txt" if extension == "txt" else "md"
    post = sanitize_filename(post_id)[:80]
    return Path(download_dir) / "kcdl-state" / site_name / creator_name / "posts" / post / f"files.{suffix}"


def remember_profile(download_dir, site, profile):
    path = Path(download_dir) / "kcdl-state" / site.name / "profiles.json"
    legacy = Path(download_dir) / site.name / "profiles.json"
    data = _read_profile_index(path)
    if legacy.exists() and legacy.resolve() != path.resolve():
        data.update(_read_profile_index(legacy))
    data[str(profile.get("id") or "")] = profile
    write_json(path, data)
    if legacy.exists() and legacy.resolve() != path.resolve():
        try:
            legacy.unlink()
        except OSError:
            pass


def _read_profile_index(path):
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}
