# Kemono and Coomer Downloader

[![](img/en-flag.svg) English](README.md) | [![](img/br.png) Português](README-ptbr.md)

Download posts from [Kemono](https://kemono.cr/) and [Coomer](https://coomer.st/). One post, a list of posts, or a profile.

The English and Portuguese programs used to be two copies of the same code. They are now one program. `codeen` and `codept` only choose the menu language.

## Install

Python 3.10 or newer.

```sh
py -3 -m pip install -r requirements.txt
py -3 main.py
```

`python main.py` works too when `python` is on your PATH. From `codeen`, the menu is English. From `codept`, the menu is Portuguese.

## Menu

1. Download one post, or several posts. Paste links separated by commas or spaces, or give a text file with the same kind of list.
2. Download posts from a profile: every post, one page, a page range, or the posts between two ids.
3. Settings.
4. Exit.

Page offsets count by 50. The first page is `0`, the second is `50`, the third is `100`. A range can use those numbers, or the words `start` and `end`.

```text
https://kemono.cr/patreon/user/USER_ID/post/POST_ID
https://coomer.st/onlyfans/user/USER_ID
```

Older domains such as `kemono.su` and `coomer.party` are accepted and sent to the current site.

## Commands

```sh
py -3 main.py post "https://kemono.cr/patreon/user/USER_ID/post/POST_ID"
py -3 main.py post --file links.txt
py -3 main.py profile "https://kemono.cr/patreon/user/USER_ID"
py -3 main.py profile "https://kemono.cr/patreon/user/USER_ID" --offset 50
py -3 main.py profile "https://kemono.cr/patreon/user/USER_ID" --offset 0-750
py -3 main.py profile "https://kemono.cr/patreon/user/USER_ID" --between 1000 2000
py -3 main.py --lang pt --dir D:\Archive post "https://coomer.st/onlyfans/user/USER_ID/post/POST_ID"
py -3 main.py --layout flat profile "https://coomer.st/onlyfans/user/USER_ID"
```

`--limit 10` stops after 10 posts. `--dir` chooses where the site folders are created. The default is the folder you started the program from. `--layout folders` keeps one folder per post. `--layout flat` puts every file in the creator folder. The menu asks this before each download.

## Settings

`config/conf.json`:

| Setting | Default | Meaning |
|---|---|---|
| `get_empty_posts` | `false` | Profile downloads skip posts that have no files |
| `process_from_oldest` | `false` | Oldest post first when this is `true` |
| `save_info` | `true` | Write `files.md` or `files.txt` under `kcdl-state` for each post |
| `separate_folders` | `true` | `true` puts each post in its own folder. `false` puts every file in one folder |
| `post_info` | `md` | `md` or `txt` |
| `language` | `en` | `en` or `pt` |
| `file_interval` | `1.0` | Seconds between file requests. The minimum is 1 |
| `api_interval` | `0.4` | Seconds between API requests |
| `connect_timeout` | `5` | Seconds to wait for a file server to accept a connection |
| `read_timeout` | `120` | Seconds to wait while a file is transferring |

Turning off `save_info` skips the info file only. The files are still downloaded.

## Where files go

```text
kemono/ or coomer/
└── Name-service-userId/
    └── posts/
        └── POST_ID/
            └── 1-filename.ext

kcdl-state/
└── kemono/ or coomer/
    ├── profiles.json
    └── Name-service-userId/
        └── posts/
            └── POST_ID/
                ├── download.json
                └── files.md
```

With one shared folder, the pictures sit directly inside `Name-service-userId\`. If two posts would use the same file name, the later one is prefixed with its post id. `download.json` and `files.md` stay in `kcdl-state`, not next to the pictures.

`download.json` remembers what was saved. A finished original file is skipped on the next run. A preview is tried again in case the full file is reachable, and the preview stays in place when it is not.

## File servers

Kemono and Coomer keep post text on the main site. The full files are on `n1`–`n4` servers, and those servers often do not accept connections. When that happens for a Kemono file, the program downloads the same file from `https://file.pawchive.pw`, which asks downloaders to send an identifiable user agent and to stay at or under one request per second. This program does both.

Coomer files are not on that mirror. If the Coomer file server does not respond, the program saves the preview from `img.coomer.st` and says so in the log. The info file marks that file as a preview. After a few misses, hosts that are down or have no copy are skipped, and preview downloads are not held to the one-second Pawchive limit.

The user agent is `KemonoCoomerDownloader/2.0 (+https://github.com/e43b/Kemono-and-Coomer-Downloader)`.

## Checks

```sh
py -3 -m unittest discover -s tests
```

## Author

[E43b](https://github.com/e43b). Questions and bugs: [Discord](https://discord.gg/GNJbxzD8bK). Support: [Ko-fi](https://ko-fi.com/e43bs).
