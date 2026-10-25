"""Tests for link parsing, ranges, and the file fallback downloader."""

import tempfile
import unittest
from pathlib import Path

import requests

from kcdl.config import normalize
from kcdl.download import build_candidates, download_candidates, download_post_files
from kcdl.engine import _walk_offsets
from kcdl.http import HostHealth, Pace
from kcdl.media import (
    FetchMode,
    assign_names,
    collect_files,
    html_to_text,
    in_id_range,
    mode_from_offset_text,
    page_offsets,
    render_info,
    sort_posts,
)
from kcdl.sites import KEMONO, parse_target, split_links
from kcdl.config import settings_from


PATH = "/6b/fb/" + ("a" * 64) + ".png"


class Headers(dict):
    def get(self, key, default=None):
        for name, value in self.items():
            if name.lower() == key.lower():
                return value
        return default


class FakeResponse:
    def __init__(self, status, headers=None, body=b""):
        self.status_code = status
        self.headers = Headers(headers or {})
        self._body = body

    def close(self):
        return None

    def iter_content(self, chunk_size=8192):
        if self._body:
            yield self._body


class FakeSession:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(url)
        spec = self.routes[url]
        if isinstance(spec, Exception):
            raise spec
        return spec


class LinkTests(unittest.TestCase):
    def test_post_and_profile_links(self):
        post = parse_target("https://kemono.su/patreon/user/9919437/post/103396563?o=1")
        self.assertEqual(post.site.name, "kemono")
        self.assertEqual(post.site.root, "https://kemono.cr")
        self.assertEqual(post.service, "patreon")
        self.assertEqual(post.user_id, "9919437")
        self.assertEqual(post.post_id, "103396563")

        profile = parse_target("coomer.party/onlyfans/user/rosiee616/")
        self.assertEqual(profile.site.name, "coomer")
        self.assertEqual(profile.site.root, "https://coomer.st")
        self.assertIsNone(profile.post_id)

    def test_split_links(self):
        text = "https://kemono.cr/patreon/user/1/post/2, https://coomer.st/onlyfans/user/a/post/3\nhttps://kemono.cr/fanbox/user/4/post/5"
        links = split_links(text)
        self.assertEqual(len(links), 3)

    def test_bad_link(self):
        with self.assertRaises(ValueError):
            parse_target("https://example.com/patreon/user/1")


class RangeTests(unittest.TestCase):
    def test_id_range_is_numeric(self):
        self.assertTrue(in_id_range("9", 9, 100))
        self.assertTrue(in_id_range("50", "100", "9"))
        self.assertTrue(in_id_range("100", 9, 100))
        self.assertFalse(in_id_range("8", 9, 100))
        self.assertFalse(in_id_range("101", 9, 100))

    def test_offsets(self):
        self.assertEqual(page_offsets(FetchMode("page", 60), 883), [50])
        self.assertEqual(page_offsets(FetchMode("range", "start", "end"), 120), [0, 50, 100])
        self.assertEqual(page_offsets(mode_from_offset_text("0-750"), 1000)[:3], [0, 50, 100])
        self.assertEqual(page_offsets(mode_from_offset_text("0-750"), 1000)[-1], 750)
        self.assertIsNone(page_offsets(FetchMode("all"), 10))
        self.assertIsNone(page_offsets(FetchMode("ids", 9, 100), 10))

    def test_profile_walk_filters_ids_and_empty_posts(self):
        class FakeApi:
            def profile(self, site, service, user_id):
                return {"id": user_id, "name": "Artist", "service": service, "post_count": 51}

            def posts_page(self, site, service, user_id, offset):
                if offset == 0:
                    page = [
                        self._post("1", True, "2020-01-03"),
                        self._post("2", False, "2020-01-02"),
                        self._post("9", True, "2020-01-01"),
                    ]
                    page.extend(
                        self._post(str(1000 + index), True, "2020-01-01")
                        for index in range(47)
                    )
                    return page
                if offset == 50:
                    return [self._post("100", True, "2019-01-01")]
                return []

            def _post(self, post_id, with_file, published):
                return {
                    "id": post_id,
                    "user": "42",
                    "service": "patreon",
                    "title": "t" + post_id,
                    "published": published,
                    "file": {"name": "a.png", "path": "/aa/bb/" + post_id + ".png"} if with_file else {},
                    "attachments": [],
                }

        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_from({"get_empty_posts": False, "save_info": False}, tmp)
            empty = [0]
            _profile, posts = _walk_offsets(
                FakeApi(), KEMONO, "patreon", "42", FetchMode("ids", 9, 100), settings, None, empty
            )
        ids = [post["id"] for post in posts]
        self.assertEqual(ids, ["9", "100"])
        self.assertEqual(empty[0], 0)

        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_from({"get_empty_posts": False}, tmp)
            empty = [0]
            _profile, posts = _walk_offsets(
                FakeApi(), KEMONO, "patreon", "42", FetchMode("all"), settings, None, empty
            )
        ids = [post["id"] for post in posts]
        self.assertIn("1", ids)
        self.assertIn("9", ids)
        self.assertIn("100", ids)
        self.assertNotIn("2", ids)
        self.assertEqual(empty[0], 1)
        sort_posts(posts, oldest_first=True)
        self.assertEqual(posts[0]["id"], "100")


class FileTests(unittest.TestCase):
    def test_duplicate_main_file_is_kept_once(self):
        files = collect_files({
            "file": {"name": "pic.png", "path": PATH},
            "attachments": [
                {"name": "pic.png", "path": PATH},
                {"name": "other.png", "path": "/aa/bb/" + ("b" * 64) + ".png"},
            ],
            "content": f'<img src="{PATH}">',
        })
        self.assertEqual(len(files), 2)
        self.assertEqual(files[0]["path"], PATH)

    def test_names_keep_extension(self):
        named = assign_names([
            {"name": "my file", "path": PATH},
            {"name": "CON", "path": "/aa/bb/" + ("c" * 64) + ".jpg"},
        ])
        self.assertTrue(named[0][1].endswith(".png"))
        self.assertTrue(named[1][1].startswith("2-_CON"))

    def test_save_info_does_not_remove_files(self):
        files = collect_files({"file": {"name": "a.png", "path": PATH}, "attachments": []})
        self.assertEqual(len(files), 1)
        text = render_info(
            {"id": "1", "title": "Hello", "content": "<p>Hi <a href=\"https://example.com\">there</a></p>", "files": files, "link": "https://kemono.cr/x"},
            [],
            "md",
        )
        self.assertIn("# Hello", text)
        self.assertIn("[there](https://example.com)", html_to_text("<p>Hi <a href=\"https://example.com\">there</a></p>"))

    def test_candidates_skip_dead_hosts(self):
        health = HostHealth()
        health.mark_dead("n4.kemono.cr")
        urls = build_candidates(KEMONO, PATH, "https://n4.kemono.cr", health)
        self.assertEqual(urls[0][0], "https://kemono.cr/data" + PATH)
        self.assertEqual(urls[1][0], "https://file.pawchive.pw/data" + PATH)
        self.assertEqual(urls[-1][1], "preview")
        self.assertTrue(all("n4.kemono.cr" not in url for url, _kind in urls))

    def test_download_uses_next_server_when_cdn_times_out(self):
        root = "https://kemono.cr/data" + PATH
        cdn = "https://n4.kemono.cr/data" + PATH
        mirror = "https://file.pawchive.pw/data" + PATH
        body = b"\x89PNG\r\n\x1a\n" + b"pixels"
        session = FakeSession({
            root: FakeResponse(302, {"Location": cdn}),
            cdn: requests.ConnectTimeout("timed out"),
            mirror: FakeResponse(200, {"Content-Type": "image/png"}, body),
        })
        health = HostHealth()
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "1-pic.png"
            result = download_candidates(
                session,
                [(root, "original"), (mirror, "original")],
                dest,
                health,
                Pace(0),
                "https://kemono.cr/",
                (1, 1),
            )
            self.assertEqual(dest.read_bytes(), body)
        self.assertEqual(result["kind"], "original")
        self.assertEqual(result["source"], mirror)
        self.assertTrue(health.is_dead("n4.kemono.cr"))
        self.assertNotIn(cdn, session.calls[2:])

    def test_existing_original_is_skipped_and_preview_is_not_redownloaded(self):
        health = HostHealth()
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            dest = folder / "1-pic.png"
            dest.write_bytes(b"full-file")
            manifest = {
                "files": {
                    PATH: {
                        "name": "1-pic.png",
                        "bytes": len(b"full-file"),
                        "kind": "original",
                        "source": "https://file.pawchive.pw/data" + PATH,
                    }
                }
            }
            (folder / "download.json").write_text(__import__("json").dumps(manifest), encoding="utf-8")
            session = FakeSession({})
            outcomes = download_post_files(
                session,
                KEMONO,
                {"id": "1", "files": [{"name": "pic.png", "path": PATH}], "link": "https://kemono.cr/"},
                folder,
                health,
                Pace(0),
                (1, 1),
            )
            self.assertEqual(outcomes[0]["status"], "skipped")
            self.assertEqual(session.calls, [])

            preview = folder / "1-pic.png"
            preview.write_bytes(b"thumb")
            manifest["files"][PATH]["kind"] = "preview"
            manifest["files"][PATH]["bytes"] = len(b"thumb")
            (folder / "download.json").write_text(__import__("json").dumps(manifest), encoding="utf-8")
            root = "https://kemono.cr/data" + PATH
            mirror = "https://file.pawchive.pw/data" + PATH
            session = FakeSession({
                root: FakeResponse(404, {"Content-Type": "text/plain"}, b"missing"),
                mirror: FakeResponse(404, {"Content-Type": "text/plain"}, b"missing"),
            })
            outcomes = download_post_files(
                session,
                KEMONO,
                {"id": "1", "files": [{"name": "pic.png", "path": PATH, "server": None}], "link": "https://kemono.cr/"},
                folder,
                HostHealth(),
                Pace(0),
                (1, 1),
            )
            self.assertEqual(outcomes[0]["status"], "skipped")
            self.assertEqual(outcomes[0]["kind"], "preview")
            self.assertEqual(preview.read_bytes(), b"thumb")


class ConfigTests(unittest.TestCase):
    def test_file_interval_cannot_drop_below_one_second(self):
        data = normalize({"file_interval": 0, "post_info": "nope", "language": "fr"})
        self.assertEqual(data["file_interval"], 1.0)
        self.assertEqual(data["post_info"], "md")
        self.assertEqual(data["language"], "en")
        self.assertTrue(data["save_info"])


if __name__ == "__main__":
    unittest.main()
