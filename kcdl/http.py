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
    """Remember hosts that refused the connection during this run."""

    def __init__(self):
        self._dead = set()
        self._lock = threading.Lock()

    def is_dead(self, host):
        if not host:
            return False
        with self._lock:
            return host.lower() in self._dead

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


class Pace:
    """Wait so file requests stay at or under the given interval."""

    def __init__(self, interval):
        self.interval = max(0.0, float(interval))
        self._next = 0.0
        self._lock = threading.Lock()

    def wait(self):
        if self.interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            delay = self._next - now
            if delay < 0:
                delay = 0
            self._next = max(self._next, now) + self.interval
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
