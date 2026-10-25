"""Fetch posts and save their files."""

from dataclasses import dataclass, field

from kcdl.api import Api
from kcdl.download import download_post_files
from kcdl.http import ApiError, make_session
from kcdl.media import (
    PAGE_SIZE,
    creator_folder,
    in_id_range,
    info_file,
    manifest_file,
    normalize_detail,
    normalize_list_post,
    page_offsets,
    remember_profile,
    render_info,
    sort_posts,
)
from kcdl.sites import LinkError, parse_target


@dataclass
class FileOutcome:
    name: str
    status: str
    nbytes: int = 0
    kind: str = ""
    source: str = ""
    error: str = ""


@dataclass
class PostOutcome:
    post_id: str
    title: str
    folder: str
    files: list = field(default_factory=list)
    error: str = ""


@dataclass
class RunResult:
    posts: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    empty_skipped: int = 0


def _keep_list_post(post, mode, settings, empty_counter):
    if mode is not None and mode.kind == "ids":
        if not in_id_range(post["id"], mode.start, mode.end):
            return False
    if not post["files"] and not settings.get_empty_posts:
        empty_counter[0] += 1
        return False
    return True


def _stop_early(collected, mode, settings):
    if settings.process_from_oldest or not settings.limit:
        return False
    if mode is not None and mode.kind == "ids":
        return False
    return len(collected) >= settings.limit


def _consume_batch(batch, site, mode, settings, collected, empty_counter):
    for raw in batch:
        post = normalize_list_post(raw, site)
        if not post["id"]:
            continue
        if not _keep_list_post(post, mode, settings, empty_counter):
            continue
        collected.append(post)
        if _stop_early(collected, mode, settings):
            return True
    return False


def _walk_offsets(api, site, service, user_id, mode, settings, on_note, empty_counter):
    profile = api.profile(site, service, user_id)
    remember_profile(settings.download_dir, site, profile)
    if on_note:
        on_note(
            "creator",
            name=profile.get("name") or user_id,
            service=service,
            user=user_id,
            count=profile.get("post_count") or 0,
        )
    offsets = page_offsets(mode, profile.get("post_count") or 0)
    collected = []
    if offsets is None:
        offset = 0
        while offset <= 1_000_000:
            batch = api.posts_page(site, service, user_id, offset)
            if on_note:
                on_note("page", offset=offset, count=len(batch))
            if not batch:
                break
            if _consume_batch(batch, site, mode, settings, collected, empty_counter):
                break
            if len(batch) < PAGE_SIZE:
                break
            offset += PAGE_SIZE
    else:
        for offset in offsets:
            batch = api.posts_page(site, service, user_id, offset)
            if on_note:
                on_note("page", offset=offset, count=len(batch))
            if not batch:
                break
            if _consume_batch(batch, site, mode, settings, collected, empty_counter):
                break
            if len(batch) < PAGE_SIZE:
                break
    return profile, collected


def _with_details(api, site, service, user_id, posts, settings, on_note=None):
    if not settings.save_info:
        return posts
    detailed = []
    total = len(posts)
    for index, post in enumerate(posts, start=1):
        if on_note:
            on_note("detail", index=index, total=total, post_id=post["id"])
        try:
            payload = api.post(site, service, user_id, post["id"])
            detailed.append(normalize_detail(payload, site))
        except ApiError:
            detailed.append(post)
    return detailed


def _download_ready(session, site, profile, posts, settings, on_note, on_post, on_file):
    if not posts:
        return []
    folder = creator_folder(
        settings.download_dir,
        site,
        profile,
        posts[0]["service"] or profile.get("service") or "",
        posts[0]["user"] or str(profile.get("id") or ""),
    )
    outcomes = []
    total = len(posts)
    if on_note:
        on_note("download-start", total=total)
    for index, post in enumerate(posts, start=1):
        post_id = sanitize_id(post["id"])
        flat = not settings.separate_folders
        post_folder = folder if flat else folder / "posts" / post_id
        title = (post.get("title") or post["id"]).replace("\n", " ").strip()
        if len(title) > 80:
            title = title[:77] + "..."
        if on_note:
            on_note("post", index=index, total=total, post_id=post["id"], title=title)
        if on_post:
            on_post(post)
        try:
            files = []

            def emit(payload, _files=files, _post_id=post["id"]):
                item = FileOutcome(
                    name=payload["name"],
                    status=payload["status"],
                    nbytes=payload["nbytes"],
                    kind=payload["kind"],
                    source=payload["source"],
                    error=payload["error"],
                )
                _files.append(item)
                if on_file:
                    on_file(_post_id, item)

            download_post_files(
                session,
                site,
                post,
                post_folder,
                health=settings_health(settings),
                pace=settings_pace(settings),
                timeouts=settings.timeouts,
                on_note=on_note,
                on_file=emit,
                flat=flat,
                manifest_path=manifest_file(
                    settings.download_dir,
                    site.name,
                    folder.name,
                    post_id,
                    flat,
                ),
            )
        except Exception as exc:
            outcomes.append(PostOutcome(
                post_id=post["id"],
                title=post.get("title") or "",
                folder=str(post_folder),
                error=str(exc),
            ))
            if on_note:
                on_note("post-done", index=index, total=total)
            continue
        if settings.save_info:
            extension = "md" if settings.post_info == "md" else "txt"
            text = render_info(post, files, settings.post_info)
            info_path = info_file(settings.download_dir, site.name, folder.name, post_id, extension)
            info_path.parent.mkdir(parents=True, exist_ok=True)
            info_path.write_text(text, encoding="utf-8")
            _remove_legacy_info(post_folder, info_path, post_id)
        outcomes.append(PostOutcome(
            post_id=post["id"],
            title=post.get("title") or "",
            folder=str(post_folder),
            files=files,
        ))
        if on_note:
            on_note("post-done", index=index, total=total)
    return outcomes


def _remove_legacy_info(post_folder, info_path, post_id):
    """Delete info files left in the picture folder by older versions."""
    names = ("files.md", "files.txt", f"{post_id}.md", f"{post_id}.txt")
    for name in names:
        legacy = post_folder / name
        try:
            if legacy.exists() and legacy.resolve() != info_path.resolve():
                legacy.unlink()
        except OSError:
            pass


def sanitize_id(post_id):
    from kcdl.media import sanitize_filename
    return sanitize_filename(post_id)[:80]


def settings_health(settings):
    health = getattr(settings, "_health", None)
    if health is None:
        from kcdl.http import HostHealth
        health = HostHealth()
        settings._health = health
    return health


def settings_pace(settings):
    pace = getattr(settings, "_pace", None)
    if pace is None:
        from kcdl.http import Pace
        pace = Pace(settings.file_interval)
        settings._pace = pace
    return pace


def _prepare_settings(settings):
    settings_health(settings)
    settings_pace(settings)
    return make_session()


def run_links(urls, settings, on_note=None, on_post=None, on_file=None):
    """Download specific post links."""
    result = RunResult()
    session = _prepare_settings(settings)
    api = Api(session, settings.api_interval)
    grouped = {}
    order = []
    seen = set()
    for url in urls:
        try:
            target = parse_target(url)
        except LinkError as exc:
            result.errors.append(str(exc))
            continue
        if not target.post_id:
            result.errors.append(f"Not a post link: {url}")
            continue
        key = (target.site.name, target.service, target.user_id, target.post_id)
        if key in seen:
            continue
        seen.add(key)
        creator = (target.site.name, target.service, target.user_id)
        if creator not in grouped:
            grouped[creator] = {"target": target, "ids": []}
            order.append(creator)
        grouped[creator]["ids"].append(target.post_id)

    for creator in order:
        bundle = grouped[creator]
        target = bundle["target"]
        try:
            profile = api.profile(target.site, target.service, target.user_id)
            remember_profile(settings.download_dir, target.site, profile)
            if on_note:
                on_note(
                    "creator",
                    name=profile.get("name") or target.user_id,
                    service=target.service,
                    user=target.user_id,
                    count=profile.get("post_count") or 0,
                )
        except ApiError as exc:
            result.errors.append(str(exc))
            continue
        posts = []
        id_total = len(bundle["ids"])
        for index, post_id in enumerate(bundle["ids"], start=1):
            if on_note:
                on_note("detail", index=index, total=id_total, post_id=post_id)
            try:
                payload = api.post(target.site, target.service, target.user_id, post_id)
                posts.append(normalize_detail(payload, target.site))
            except ApiError as exc:
                result.errors.append(str(exc))
        sort_posts(posts, settings.process_from_oldest)
        if settings.limit:
            posts = posts[: settings.limit]
        result.posts.extend(
            _download_ready(
                session, target.site, profile, posts, settings, on_note, on_post, on_file
            )
        )
    return result


def run_profile(url, mode, settings, on_note=None, on_post=None, on_file=None):
    """Download posts from a profile link."""
    result = RunResult()
    try:
        target = parse_target(url)
    except LinkError as exc:
        result.errors.append(str(exc))
        return result
    if target.post_id:
        return run_links([url], settings, on_note, on_post, on_file)

    session = _prepare_settings(settings)
    api = Api(session, settings.api_interval)
    empty_counter = [0]
    try:
        profile, posts = _walk_offsets(
            api,
            target.site,
            target.service,
            target.user_id,
            mode,
            settings,
            on_note,
            empty_counter,
        )
    except ApiError as exc:
        result.errors.append(str(exc))
        return result
    result.empty_skipped = empty_counter[0]
    sort_posts(posts, settings.process_from_oldest)
    if settings.limit:
        posts = posts[: settings.limit]
    if on_note:
        on_note("listed", kept=len(posts), empty=result.empty_skipped)
    try:
        if settings.save_info and posts and on_note:
            on_note("details", total=len(posts))
        posts = _with_details(
            api, target.site, target.service, target.user_id, posts, settings, on_note
        )
    except ApiError as exc:
        result.errors.append(str(exc))
        return result
    if not posts:
        return result
    result.posts.extend(
        _download_ready(
            session, target.site, profile, posts, settings, on_note, on_post, on_file
        )
    )
    return result
