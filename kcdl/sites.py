"""Site roots and link parsing.

Old domains (kemono.su, coomer.party, and the rest) map to the current site.
The API host is always the current one.
"""

import re
from dataclasses import dataclass
from urllib.parse import urlparse

POST_RE = re.compile(
    r"^/(?P<service>[^/]+)/user/(?P<user>[^/]+)/post/(?P<post>[^/?#]+)/?$"
)
USER_RE = re.compile(
    r"^/(?P<service>[^/]+)/user/(?P<user>[^/]+)/?$"
)


@dataclass(frozen=True)
class Site:
    name: str
    root: str

    @property
    def api_root(self):
        return self.root + "/api/v1"

    @property
    def image_root(self):
        return self.root.replace("://", "://img.", 1)


KEMONO = Site("kemono", "https://kemono.cr")
COOMER = Site("coomer", "https://coomer.st")
PAWCHIVE = Site("pawchive", "https://pawchive.pw")

_BY_LABEL = {
    "kemono": KEMONO,
    "coomer": COOMER,
    "pawchive": PAWCHIVE,
}


@dataclass(frozen=True)
class Target:
    site: Site
    service: str
    user_id: str
    post_id: str | None
    url: str


class LinkError(ValueError):
    pass


def site_for_host(host):
    label = host.lower().removeprefix("www.").split(".")[0]
    site = _BY_LABEL.get(label)
    if site is None:
        raise LinkError(f"Unsupported site: {host}")
    return site


def parse_target(url):
    raw = (url or "").strip().strip('"').strip("'")
    if not raw:
        raise LinkError("Empty link")
    if "://" not in raw:
        raw = "https://" + raw
    parsed = urlparse(raw)
    if not parsed.hostname or not parsed.path:
        raise LinkError(f"Unsupported link: {url}")
    site = site_for_host(parsed.hostname)
    path = parsed.path
    match = POST_RE.match(path)
    if match:
        return Target(
            site=site,
            service=match.group("service"),
            user_id=match.group("user"),
            post_id=match.group("post"),
            url=raw,
        )
    match = USER_RE.match(path)
    if match:
        return Target(
            site=site,
            service=match.group("service"),
            user_id=match.group("user"),
            post_id=None,
            url=raw,
        )
    raise LinkError(f"Unsupported link: {url}")


def post_id_from_text(value):
    """Accept a bare id or a post link. Return the id text."""
    text = (value or "").strip()
    if not text:
        raise LinkError("Empty post id")
    if "://" in text or "/" in text:
        target = parse_target(text)
        if not target.post_id:
            raise LinkError(f"Not a post link: {value}")
        return target.post_id
    return text


def split_links(text):
    cleaned = (text or "").replace(",", " ")
    links = []
    for part in cleaned.split():
        token = part.strip().strip('"').strip("'")
        if token:
            links.append(token)
    return links
