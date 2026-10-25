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


def on_note(language, kind, **kwargs):
    if kind == "dead-host":
        print(tr(language, "dead_host", host=kwargs.get("host", "")), flush=True)
    elif kind == "creator":
        print(tr(
            language,
            "creator",
            name=kwargs.get("name", ""),
            service=kwargs.get("service", ""),
            user=kwargs.get("user", ""),
            count=kwargs.get("count", 0),
        ), flush=True)
    elif kind == "page":
        print(tr(language, "page", offset=kwargs.get("offset", 0), count=kwargs.get("count", 0)), flush=True)


def on_post(language, post):
    print(tr(language, "post_line", post_id=post["id"], title=post.get("title") or post["id"]), flush=True)


def on_file(language, post_id, item):
    del post_id
    if item.status == "failed":
        print(tr(language, "failed", name=item.name, error=item.error), flush=True)
    elif item.status == "skipped":
        print(tr(language, "skipped", name=item.name), flush=True)
    elif item.kind == "preview":
        print(tr(language, "saved_preview", name=item.name, nbytes=item.nbytes), flush=True)
    else:
        print(tr(language, "saved", name=item.name, nbytes=item.nbytes), flush=True)


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
    result = run_links(
        urls,
        settings,
        on_note=lambda kind, **kwargs: on_note(language, kind, **kwargs),
        on_post=lambda post: on_post(language, post),
        on_file=lambda post_id, item: on_file(language, post_id, item),
    )
    return print_summary(language, result)


def run_profile_command(url, mode, settings, language):
    result = run_profile(
        url,
        mode,
        settings,
        on_note=lambda kind, **kwargs: on_note(language, kind, **kwargs),
        on_post=lambda post: on_post(language, post),
        on_file=lambda post_id, item: on_file(language, post_id, item),
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


def settings_menu(config, language):
    while True:
        lang_label = tr(language, "lang_en" if config["language"] == "en" else "lang_pt")
        action = choose(language, tr(language, "settings_title"), [
            ("empty", tr(language, "set_empty", value=config["get_empty_posts"])),
            ("oldest", tr(language, "set_oldest", value=config["process_from_oldest"])),
            ("info", tr(language, "set_info", value=config["save_info"])),
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
        elif action == "format":
            config["post_info"] = "txt" if config["post_info"] == "md" else "md"
        elif action == "lang":
            config["language"] = "pt" if config["language"] == "en" else "en"
            language = config["language"]
        save(config)


def interactive(config, download_dir, forced_language):
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

    return interactive(config, download_dir, args.lang)


def main(argv=None):
    try:
        code = run(argv)
    except KeyboardInterrupt:
        print()
        code = 130
    raise SystemExit(code)
