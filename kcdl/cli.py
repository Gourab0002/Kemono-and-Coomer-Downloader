"""Command line and the text menu."""

import argparse
import os
import sys
from pathlib import Path

from kcdl.config import load, save, settings_from
from kcdl.engine import run_links, run_profile
from kcdl.i18n import tr
from kcdl.media import FetchMode, mode_from_offset_text, numeric_id
from kcdl.sites import LinkError, post_id_from_text, split_links

LOGO = r"""
 _  __
| |/ /___ _ __ ___   ___  _ __   ___
| ' // _ \ '_ ` _ \ / _ \| '_ \ / _ \
| . \  __/ | | | | | (_) | | | | (_) |
|_|\_\___|_| |_| |_|\___/|_| |_|\___/
 / ___|___   ___  _ __ ___   ___ _ __
| |   / _ \ / _ \| '_ ` _ \ / _ \ '__|
| |__| (_) | (_) | | | | | |  __/ |
 \____\___/ \___/|_| |_| |_|\___|_|          _
|  _ \  _____      ___ __ | | ___   __ _  __| | ___ _ __
| | | |/ _ \ \ /\ / / '_ \| |/ _ \ / _` |/ _` |/ _ \ '__|
| |_| | (_) \ V  V /| | | | | (_) | (_| | (_| |  __/ |
|____/ \___/ \_/\_/ |_| |_|_|\___/ \__,_|\__,_|\___|_|
"""


def configure_stdio():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass


def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


def banner(language):
    print(LOGO)
    print(tr(language, "tagline"))
    print("GitHub: https://github.com/e43b/Kemono-and-Coomer-Downloader")
    print("Discord: https://discord.gg/GNJbxzD8bK")
    print("Donate: https://ko-fi.com/e43bs")
    print()


def build_parser():
    parser = argparse.ArgumentParser(
        prog="kcdl",
        description="Download posts from Kemono and Coomer.",
    )
    parser.add_argument("--lang", choices=("en", "pt"), help="Menu language for this run")
    parser.add_argument("--dir", type=Path, help="Folder where kemono/ and coomer/ are created")
    parser.add_argument(
        "--layout",
        choices=("folders", "flat"),
        help="folders: one folder per post. flat: all files in one folder",
    )
    sub = parser.add_subparsers(dest="command")

    post = sub.add_parser("post", help="Download one or more post links")
    post.add_argument("urls", nargs="*", help="Post links")
    post.add_argument("--file", "-f", type=Path, help="Text file of links, separated by commas or whitespace")
    post.add_argument("--limit", type=int, help="Maximum number of posts")

    profile = sub.add_parser("profile", help="Download posts from a profile")
    profile.add_argument("url", help="Profile link, or one post link")
    profile.add_argument("--offset", help="One page (50) or a range (0-750, start-end)")
    profile.add_argument("--between", nargs=2, metavar=("START", "END"), help="Two post links or ids")
    profile.add_argument("--limit", type=int, help="Maximum number of posts")
    return parser


def gather_links(urls, file_path):
    collected = []
    for url in urls or []:
        collected.extend(split_links(url))
    if file_path:
        text = Path(file_path).read_text(encoding="utf-8-sig")
        collected.extend(split_links(text))
    return collected


def make_settings(config, download_dir, language, limit):
    return settings_from(config, download_dir or Path.cwd(), language=language, limit=limit)


class Progress:
    """Print each step as it starts, and keep a running tally."""

    width = 100

    def __init__(self, language):
        self.language = language
        self.saved = 0
        self.previews = 0
        self.skipped = 0
        self.failed = 0
        self.post_index = 0
        self.post_total = 0
        self.file_index = 0
        self.file_total = 0

    def note(self, kind, **kwargs):
        if kind == "detail":
            self.live(tr(self.language, "detail", index=kwargs.get("index", 0), total=kwargs.get("total", 0), post_id=kwargs.get("post_id", "")))
        elif kind == "details":
            self.live(tr(self.language, "details", total=kwargs.get("total", 0)))
        elif kind == "file":
            self.file_index = kwargs.get("index", 0)
            self.file_total = kwargs.get("total", 0)
            self.live(tr(
                self.language,
                "file_start",
                post_index=self.post_index,
                post_total=self.post_total,
                index=self.file_index,
                total=self.file_total,
                name=kwargs.get("name", ""),
            ))
        elif kind == "trying":
            self.live(tr(
                self.language,
                "trying",
                post_index=self.post_index,
                post_total=self.post_total,
                index=self.file_index,
                total=self.file_total,
                host=kwargs.get("host", ""),
                name=kwargs.get("name", ""),
            ))
        elif kind == "post":
            self.post_index = kwargs.get("index", 0)
            self.post_total = kwargs.get("total", 0)
            self.commit(tr(
                self.language,
                "post_line",
                index=self.post_index,
                total=self.post_total,
                post_id=kwargs.get("post_id", ""),
                title=kwargs.get("title") or kwargs.get("post_id", ""),
            ))
        elif kind == "post-done":
            self.commit(tr(
                self.language,
                "status",
                done=kwargs.get("index", self.post_index),
                total=kwargs.get("total", self.post_total),
                saved=self.saved,
                previews=self.previews,
                skipped=self.skipped,
                failed=self.failed,
            ))
        elif kind == "download-start":
            self.post_total = kwargs.get("total", 0)
            self.commit(tr(self.language, "download_start", total=self.post_total))
        elif kind == "listed":
            self.commit(tr(self.language, "listed", kept=kwargs.get("kept", 0), empty=kwargs.get("empty", 0)))
        elif kind == "dead-host":
            self.commit(tr(self.language, "dead_host", host=kwargs.get("host", "")))
        elif kind == "skip-host":
            self.commit(tr(self.language, "skip_host", host=kwargs.get("host", "")))
        elif kind == "creator":
            self.commit(tr(
                self.language,
                "creator",
                name=kwargs.get("name", ""),
                service=kwargs.get("service", ""),
                user=kwargs.get("user", ""),
                count=kwargs.get("count", 0),
            ))
        elif kind == "page":
            self.commit(tr(self.language, "page", offset=kwargs.get("offset", 0), count=kwargs.get("count", 0)))

    def file_done(self, item):
        if item.status == "failed":
            self.failed += 1
            line = tr(self.language, "failed", name=item.name, error=item.error)
        elif item.kind == "preview":
            self.previews += 1
            if item.status == "skipped":
                line = tr(self.language, "skipped", name=item.name)
            else:
                line = tr(self.language, "saved_preview", name=item.name, nbytes=item.nbytes)
        elif item.status == "skipped":
            self.skipped += 1
            line = tr(self.language, "skipped", name=item.name)
        else:
            self.saved += 1
            line = tr(self.language, "saved", name=item.name, nbytes=item.nbytes)
        self.commit(line)

    def live(self, text):
        shown = text if len(text) <= self.width else text[:self.width - 3] + "..."
        print("\r" + shown.ljust(self.width), end="", flush=True)

    def commit(self, text):
        gap = max(0, self.width - len(text))
        print("\r" + text + (" " * gap), flush=True)


def print_summary(language, result):
    saved = previews = skipped = failed = 0
    for post in result.posts:
        if post.error:
            print(tr(language, "post_error", post_id=post.post_id, error=post.error))
            failed += 1
        for item in post.files:
            if item.status == "failed":
                failed += 1
            elif item.kind == "preview":
                previews += 1
            elif item.status == "skipped":
                skipped += 1
            elif item.status == "downloaded":
                saved += 1
    if result.errors:
        print(tr(language, "errors_header"))
        for error in result.errors:
            print(f"  {error}")
    print(tr(
        language,
        "summary",
        posts=len(result.posts),
        saved=saved,
        previews=previews,
        skipped=skipped,
        failed=failed,
    ))
    if result.empty_skipped:
        print(tr(language, "empty_note", count=result.empty_skipped))
    return 1 if failed or result.errors else 0


def run_post_command(urls, settings, language):
    if not urls:
        print(tr(language, "no_links"))
        return 1
    progress = Progress(language)
    result = run_links(
        urls,
        settings,
        on_note=progress.note,
        on_file=lambda post_id, item: progress.file_done(item),
    )
    return print_summary(language, result)


def run_profile_command(url, mode, settings, language):
    progress = Progress(language)
    result = run_profile(
        url,
        mode,
        settings,
        on_note=progress.note,
        on_file=lambda post_id, item: progress.file_done(item),
    )
    return print_summary(language, result)


def choose(language, title, options):
    while True:
        clear_screen()
        banner(language)
        print(title)
        print("-" * 40)
        for index, (_key, label) in enumerate(options, start=1):
            print(f"{index} - {label}")
        raw = input("\n" + tr(language, "choice")).strip()
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1][0]
        print(tr(language, "invalid"))
        input(tr(language, "press_enter"))


def pause(language):
    input("\n" + tr(language, "press_enter"))


def ask_links(language):
    action = choose(language, tr(language, "post_title"), [
        ("paste", tr(language, "post_paste")),
        ("file", tr(language, "post_file")),
        ("back", tr(language, "back")),
    ])
    if action == "back":
        return None
    if action == "paste":
        return split_links(input(tr(language, "links_prompt")))
    path = input(tr(language, "file_prompt")).strip().strip('"')
    if not path or not Path(path).is_file():
        print(tr(language, "file_missing", path=path))
        pause(language)
        return None
    return split_links(Path(path).read_text(encoding="utf-8-sig"))


def ask_token(language, prompt_key, allow_end):
    while True:
        raw = input(tr(language, prompt_key)).strip().lower()
        if allow_end and raw in ("start", "end"):
            return raw
        try:
            number = int(raw)
        except ValueError:
            print(tr(language, "bad_number"))
            continue
        if number < 0:
            print(tr(language, "bad_number"))
            continue
        return number


def ask_post_id(language, prompt_key):
    while True:
        raw = input(tr(language, prompt_key)).strip()
        try:
            number = numeric_id(post_id_from_text(raw))
        except LinkError:
            print(tr(language, "bad_id"))
            continue
        if number is None:
            print(tr(language, "bad_id"))
            continue
        return number


def ask_profile_mode(language):
    action = choose(language, tr(language, "profile_title"), [
        ("all", tr(language, "profile_all")),
        ("page", tr(language, "profile_page")),
        ("range", tr(language, "profile_range")),
        ("ids", tr(language, "profile_ids")),
        ("back", tr(language, "back")),
    ])
    if action == "back":
        return None
    url = input(tr(language, "profile_url")).strip()
    if not url:
        return None
    if action == "all":
        return url, FetchMode("all")
    if action == "page":
        return url, FetchMode("page", ask_token(language, "offset_prompt", allow_end=True))
    if action == "range":
        return url, FetchMode(
            "range",
            ask_token(language, "start_offset", allow_end=True),
            ask_token(language, "end_offset", allow_end=True),
        )
    return url, FetchMode(
        "ids",
        ask_post_id(language, "first_post"),
        ask_post_id(language, "second_post"),
    )


def ask_layout(config, language, layout):
    """Choose per-post folders or one shared folder. Return False to go back."""
    if layout in ("folders", "flat"):
        config["separate_folders"] = layout == "folders"
        return True
    action = choose(language, tr(language, "layout_title"), [
        ("folders", tr(language, "layout_folders")),
        ("flat", tr(language, "layout_flat")),
        ("back", tr(language, "back")),
    ])
    if action == "back":
        return False
    config["separate_folders"] = action == "folders"
    save(config)
    return True


def settings_menu(config, language):
    while True:
        lang_label = tr(language, "lang_en" if config["language"] == "en" else "lang_pt")
        action = choose(language, tr(language, "settings_title"), [
            ("empty", tr(language, "set_empty", value=config["get_empty_posts"])),
            ("oldest", tr(language, "set_oldest", value=config["process_from_oldest"])),
            ("info", tr(language, "set_info", value=config["save_info"])),
            ("layout", tr(language, "set_layout", value=config["separate_folders"])),
            ("format", tr(language, "set_format", value=config["post_info"])),
            ("lang", tr(language, "set_lang", value=lang_label)),
            ("back", tr(language, "back")),
        ])
        if action == "back":
            return save(config), language
        if action == "empty":
            config["get_empty_posts"] = not config["get_empty_posts"]
        elif action == "oldest":
            config["process_from_oldest"] = not config["process_from_oldest"]
        elif action == "info":
            config["save_info"] = not config["save_info"]
        elif action == "layout":
            config["separate_folders"] = not config["separate_folders"]
        elif action == "format":
            config["post_info"] = "txt" if config["post_info"] == "md" else "md"
        elif action == "lang":
            config["language"] = "pt" if config["language"] == "en" else "en"
            language = config["language"]
        save(config)


def interactive(config, download_dir, forced_language, layout=None):
    language = forced_language or config["language"]
    while True:
        action = choose(language, tr(language, "menu_title"), [
            ("post", tr(language, "menu_post")),
            ("profile", tr(language, "menu_profile")),
            ("settings", tr(language, "menu_settings")),
            ("exit", tr(language, "menu_exit")),
        ])
        if action == "exit":
            print(tr(language, "bye"))
            return 0
        if action == "settings":
            before = config["language"]
            config, language = settings_menu(config, language)
            if forced_language and config["language"] == before:
                language = forced_language
            continue
        if action == "post":
            if not ask_layout(config, language, layout):
                continue
            urls = ask_links(language)
            if not urls:
                continue
            settings = make_settings(config, download_dir, language, None)
            run_post_command(urls, settings, language)
            pause(language)
            continue
        picked = ask_profile_mode(language)
        if not picked:
            continue
        if not ask_layout(config, language, layout):
            continue
        url, mode = picked
        settings = make_settings(config, download_dir, language, None)
        run_profile_command(url, mode, settings, language)
        pause(language)


def run(argv=None):
    configure_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    config = load()
    language = args.lang or config["language"]
    download_dir = args.dir

    if args.layout in ("folders", "flat"):
        config["separate_folders"] = args.layout == "folders"

    if args.command == "post":
        try:
            urls = gather_links(args.urls, args.file)
        except OSError as exc:
            print(tr(language, "file_missing", path=exc))
            return 1
        settings = make_settings(config, download_dir, language, args.limit)
        return run_post_command(urls, settings, language)

    if args.command == "profile":
        try:
            if args.between and args.offset:
                print(tr(language, "invalid"))
                return 1
            if args.between:
                start = numeric_id(post_id_from_text(args.between[0]))
                end = numeric_id(post_id_from_text(args.between[1]))
                if start is None or end is None:
                    print(tr(language, "bad_id"))
                    return 1
                mode = FetchMode("ids", start, end)
            elif args.offset:
                mode = mode_from_offset_text(args.offset)
            else:
                mode = FetchMode("all")
        except (LinkError, ValueError):
            print(tr(language, "bad_number"))
            return 1
        settings = make_settings(config, download_dir, language, args.limit)
        return run_profile_command(args.url, mode, settings, language)

    return interactive(config, download_dir, args.lang, args.layout)


def main(argv=None):
    try:
        code = run(argv)
    except KeyboardInterrupt:
        print()
        code = 130
    raise SystemExit(code)
