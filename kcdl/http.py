"""HTTP session, pacing, and memory of file servers that do not connect."""

import threading
import time
from urllib.parse import urlparse

import requests

from kcdl import __version__

USER_AGENT = (
    f"KemonoCoomerDownloader/{__version__} "
    "(+https://github.com/e43b/Kemono-and-Coomer-Downloader)"
)

API_HEADERS = {
    "Accept": "text/css",
    "User-Agent": USER_AGENT,
}

FILE_HEADERS = {
    "Accept": "*/*",
    "Accept-Encoding": "identity",
    "User-Agent": USER_AGENT,
}

REDIRECTS = {301, 302, 303, 307, 308}
TRANSIENT = {429, 500, 502, 503, 504}


class HostHealth:
    """Remember file hosts that should not be asked again during this run."""

    def __init__(self):
        self._dead = set()
        self._useless = set()
        self._hits = set()
        self._misses = {}
        self._down = {}
        self._lock = threading.Lock()

    def is_dead(self, host):
        if not host:
            return False
        with self._lock:
            return host.lower() in self._dead

    def is_blocked(self, host):
        if not host:
            return False
        key = host.lower()
        with self._lock:
            return key in self._dead or key in self._useless

    def mark_dead(self, host):
        """Return True the first time this host is marked."""
        if not host:
            return False
        key = host.lower()
        with self._lock:
            if key in self._dead:
                return False
            self._dead.add(key)
            return True

    def note_down(self, host, limit=3):
        """Count a connection failure. Return True the first time the host is skipped."""
        if not host:
            return False
        key = host.lower()
        with self._lock:
            if key in self._dead:
                return False
            count = self._down.get(key, 0) + 1
            self._down[key] = count
            if count < limit:
                return False
            self._dead.add(key)
            return True

    def forgive_outages(self):
        """Clear connection failures so failed files can be tried once more.

        Hosts skipped for redirects or repeated 404s stay blocked.
        """
        with self._lock:
            if not self._dead and not self._down:
                return False
            self._dead.clear()
            self._down.clear()
            return True

    def skip_redirect(self, host):
        """The host only redirects to a file server that is already down."""
        if not host:
            return False
        key = host.lower()
        with self._lock:
            if key in self._dead or key in self._useless:
                return False
            self._useless.add(key)
            return True

    def note_hit(self, host):
        if not host:
            return
        key = host.lower()
        with self._lock:
            self._hits.add(key)
            self._misses.pop(key, None)
            self._down.pop(key, None)
            self._useless.discard(key)
            self._dead.discard(key)

    def note_miss(self, host, limit=3):
        """Return True the first time repeated misses block this host."""
        if not host:
            return False
        key = host.lower()
        with self._lock:
            if key in self._hits or key in self._useless:
                return False
            count = self._misses.get(key, 0) + 1
            self._misses[key] = count
            if count < limit:
                return False
            self._useless.add(key)
            return True


class Pace:
    """Wait so requests to one host stay at or under the given interval."""

    def __init__(self, interval):
        self.interval = max(0.0, float(interval))
        self._next = {}
        self._lock = threading.Lock()

    def wait(self, host="", interval=None):
        gap = self.interval if interval is None else max(0.0, float(interval))
        if gap <= 0:
            return
        key = (host or "").lower()
        with self._lock:
            now = time.monotonic()
            nxt = self._next.get(key, 0.0)
            delay = nxt - now
            if delay < 0:
                delay = 0
            self._next[key] = max(nxt, now) + gap
        if delay:
            time.sleep(delay)


def hostname(url):
    host = urlparse(url).hostname
    return host.lower() if host else ""


def make_session():
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    return session


class ApiError(Exception):
    pass


class DeadHost(Exception):
    def __init__(self, host):
        super().__init__(host)
        self.host = host


class DownloadError(Exception):
    pass
