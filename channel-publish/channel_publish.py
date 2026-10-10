#!/usr/bin/env python3
"""Post build files to a Telegram channel through a local Bot API server.

The server runs with --local on the same machine, which raises the 50 MB
limit of the public Bot API to 2000 MB and takes a file by its path, so
nothing is uploaded over HTTP.

There are two styles. 'rich' sends one rich message that holds the title,
the notes or the commits, the files and the buttons; rich_post.py describes
its layout. 'album' sends the files as documents, in albums of up to ten,
with a short HTML caption under the last one, for the clients and the
cases a rich message does not suit.

A post can be repeated in other channels with --copy-to without sending
the files again: a rich message is sent anew with the files it already
has on the server, an album is copied by the server.

The bot token is read from CHANNEL_BOT_TOKEN. The posted messages are
written to --out as JSON, [{"file": <name>, "message_id": <id>}], for the
steps that record them elsewhere; the copies are not in it.
"""

import argparse
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import rich_post

ALBUM = 10
COPY = 100
CAPTION_LIMIT = 1024
SIZE_LIMIT = 2000 * 1024 * 1024
HASHTAG = re.compile(r"\w+")
READY_WAIT = 60
SEND_TIMEOUT = 3600
FLOOD_ATTEMPTS = 3


class PublishError(Exception):
    pass


def units(text):
    """The length the way Telegram counts it, in UTF-16 code units."""
    return len(text.encode("utf-16-le")) // 2


def caption(title, version, hashtags=(), body="", links=()):
    """Build the HTML caption; links are (text, address) pairs."""
    for tag in hashtags:
        if not HASHTAG.fullmatch(tag):
            raise PublishError(f"'{tag}' is not a hashtag: letters, digits and '_' only")
    head = f"<b>{html.escape(title)}</b> <code>{html.escape(version)}</code>"
    if hashtags:
        head += "\n" + " ".join(f"#{tag}" for tag in hashtags)
    foot = " · ".join(
        f'<a href="{html.escape(address)}">{html.escape(text)}</a>' for text, address in links
    )
    lines = body.strip().splitlines()
    cut = False
    while True:
        parts = [head]
        if lines:
            parts.append(html.escape("\n".join(lines)) + ("\n…" if cut else ""))
        if foot:
            parts.append(foot)
        text = "\n\n".join(parts)
        if units(text) <= CAPTION_LIMIT:
            return text
        elif not lines:
            raise PublishError(f"the caption is longer than {CAPTION_LIMIT} even without a body")
        lines.pop()
        while lines and not lines[-1].strip():
            lines.pop()
        cut = True


def check_files(paths):
    names = set()
    for path in paths:
        if not path.is_file():
            raise PublishError(f"{path} is not a file")
        size = path.stat().st_size
        if size == 0:
            raise PublishError(f"{path} is empty")
        elif size > SIZE_LIMIT:
            raise PublishError(f"{path} is larger than the 2000 MB a bot can send")
        elif path.name in names:
            raise PublishError(f"two files are named {path.name}")
        names.add(path.name)


def reference(path):
    """The address of the file for the server, which decodes it as a URL."""
    return path.resolve().as_uri()


def request(api, token, method, payload, timeout):
    """One Bot API call; returns the decoded answer whatever its status."""
    data = json.dumps(payload).encode("utf-8")
    query = urllib.request.Request(
        f"{api.rstrip('/')}/bot{token}/{method}",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(query, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as error:
        raw = error.read()
    try:
        answer = json.loads(raw)
    except ValueError as error:
        raise PublishError(f"{method}: the server did not answer with JSON") from error
    if not isinstance(answer, dict):
        raise PublishError(f"{method}: the server did not answer with an object")
    return answer


def call(api, token, method, payload, timeout=SEND_TIMEOUT, sleep=time.sleep):
    """Call a method and return its result.

    Only a flood wait is tried again: it says the request was not carried
    out. After any other failure the message may have been posted.
    """
    for attempt in range(FLOOD_ATTEMPTS):
        try:
            answer = request(api, token, method, payload, timeout)
        except (urllib.error.URLError, OSError) as error:
            # The address holds the token, so only the reason is reported.
            reason = getattr(error, "reason", error)
            raise PublishError(f"{method}: no answer from the server: {reason}") from None
        if answer.get("ok"):
            return answer.get("result")
        wait = (answer.get("parameters") or {}).get("retry_after")
        if isinstance(wait, int) and attempt + 1 < FLOOD_ATTEMPTS:
            print(f"{method}: flood wait, trying again in {wait} s", flush=True)
            sleep(wait)
            continue
        raise PublishError(
            f"{method}: {answer.get('error_code')} {answer.get('description')}"
        )


def wait_ready(api, token, wait=READY_WAIT, sleep=time.sleep, clock=time.monotonic):
    """Wait for the server to start and check the token; returns the bot."""
    deadline = clock() + wait
    while True:
        try:
            answer = request(api, token, "getMe", {}, timeout=30)
        except (urllib.error.URLError, OSError) as error:
            if clock() >= deadline:
                reason = getattr(error, "reason", error)
                raise PublishError(f"the Bot API server did not start: {reason}") from None
            sleep(2)
            continue
        if not answer.get("ok"):
            raise PublishError(
                f"the bot token is not accepted: {answer.get('error_code')} {answer.get('description')}"
            )
        return answer.get("result") or {}


def publish(api, token, chat, paths, text, sleep=time.sleep):
    """Post the files; returns [{"file": <name>, "message_id": <id>}]."""
    posted = []
    albums = [paths[start:start + ALBUM] for start in range(0, len(paths), ALBUM)]
    for index, album in enumerate(albums):
        last = index + 1 == len(albums)
        if len(album) == 1:
            payload = {"chat_id": chat, "document": reference(album[0])}
            if last:
                payload.update(caption=text, parse_mode="HTML")
            messages = [call(api, token, "sendDocument", payload, sleep=sleep)]
        else:
            media = [{"type": "document", "media": reference(path)} for path in album]
            if last:
                media[-1].update(caption=text, parse_mode="HTML")
            messages = call(
                api, token, "sendMediaGroup", {"chat_id": chat, "media": media}, sleep=sleep
            )
        if not isinstance(messages, list) or len(messages) != len(album) or not all(
            isinstance(message, dict) and isinstance(message.get("message_id"), int)
            for message in messages
        ):
            raise PublishError(f"the server answered without the {len(album)} posted messages")
        for path, message in zip(album, messages):
            posted.append({"file": path.name, "message_id": message["message_id"]})
            print(f"{path.name}: message {message['message_id']}", flush=True)
    return posted


def copy(api, token, source, target, posted, sleep=time.sleep):
    """Copy the posted messages to another channel; returns the new ids."""
    ids = sorted(entry["message_id"] for entry in posted)
    copied = []
    for start in range(0, len(ids), COPY):
        part = ids[start:start + COPY]
        payload = {"chat_id": target, "from_chat_id": source, "message_ids": part}
        result = call(api, token, "copyMessages", payload, sleep=sleep)
        if not isinstance(result, list) or len(result) != len(part) or not all(
            isinstance(message, dict) and isinstance(message.get("message_id"), int)
            for message in result
        ):
            raise PublishError(f"the server answered without the {len(part)} copied messages")
        copied.extend(message["message_id"] for message in result)
    print(f"copied to {target}: messages {', '.join(map(str, copied))}", flush=True)
    return copied


def served_files(result):
    """The files of a posted message, {name: file id}, wherever they are in it."""
    found = {}

    def walk(value):
        if isinstance(value, dict):
            name, identifier = value.get("file_name"), value.get("file_id")
            if isinstance(name, str) and isinstance(identifier, str):
                found[name] = identifier
            for inner in value.values():
                walk(inner)
        elif isinstance(value, list):
            for inner in value:
                walk(inner)

    walk(result)
    return found


def send_rich(api, token, chat, markdown, media, silent=False, sleep=time.sleep):
    """Send a rich message; media is [(key, file address or id)]. Returns the message."""
    payload = {
        "chat_id": chat,
        "rich_message": {
            "markdown": markdown,
            "media": [
                {"id": key, "media": {"type": "document", "media": source}} for key, source in media
            ],
        },
    }
    if silent:
        payload["disable_notification"] = True
    message = call(api, token, "sendRichMessage", payload, sleep=sleep)
    if not isinstance(message, dict) or not isinstance(message.get("message_id"), int):
        raise PublishError("the server answered without the posted message")
    print(f"rich message {message['message_id']} in {chat}", flush=True)
    return message


def rich_text(args, arranged, post=""):
    """The Markdown of the post; arranged is [(name, caption, folded)]."""
    blocks = [
        rich_post.heading(args.title, args.version, args.build, small=args.kind == "test"),
        rich_post.hashtags_line(args.hashtag),
    ]
    if args.notes_file:
        notes = Path(args.notes_file).read_text(encoding="utf-8")
        blocks.extend(rich_post.notes_blocks(notes, args.fold_section, args.drop_section))
    if args.notes_en_file:
        english = Path(args.notes_en_file).read_text(encoding="utf-8")
        blocks.append(rich_post.details("English", rich_post.plain_versions(english)))
    if args.commits_file:
        blocks.append(rich_post.commits_block(read_commits(args.commits_file), args.repository))
    if args.body_file:
        blocks.append(rich_post.escape(Path(args.body_file).read_text(encoding="utf-8").strip()))
    files = [(f"f{index}", caption, folded) for index, (_, caption, folded) in enumerate(arranged)]
    blocks.append(rich_post.files_block(files, args.files_title, args.folded_files_title))
    rows = [rich_post.parse_button_row(line) for line in args.button_row]
    blocks.append(rich_post.buttons_block(rows, post))
    return rich_post.compose(blocks)


def read_commits(path):
    try:
        commits = json.loads(Path(path).read_text(encoding="utf-8") or "[]")
    except ValueError as error:
        raise PublishError(f"{path} is not JSON: {error}") from error
    if commits is None:
        return []
    elif not isinstance(commits, list):
        raise PublishError(f"{path} must hold a list of commits")
    return commits


def album_text(args):
    """The short caption of an album, from the same parts as the rich post."""
    if args.caption_file:
        return Path(args.caption_file).read_text(encoding="utf-8").strip()
    version = f"{args.version} ({args.build})" if args.build else args.version
    if args.body_file:
        body = Path(args.body_file).read_text(encoding="utf-8")
    elif args.commits_file:
        commits = [rich_post.parse_commit(entry) for entry in read_commits(args.commits_file)]
        body = "\n".join(f"• {commit['subject']}" for commit in commits)
    else:
        body = ""
    links = [
        (text, address)
        for line in args.button_row
        for text, address, _ in rich_post.parse_button_row(line)
        if address != rich_post.POST
    ]
    return caption(args.title, version, args.hashtag, body, links)


def publish_rich(args, token, paths, sleep=time.sleep):
    """Send the rich post and repeat it in the other channels; returns the posted."""
    rules = [rich_post.parse_file_rule(line) for line in args.file_rule]
    by_name = {path.name: path for path in paths}
    arranged = rich_post.arrange(by_name, rules)
    media = [(f"f{index}", reference(by_name[name])) for index, (name, _, _) in enumerate(arranged)]
    silent = args.kind == "test"
    message = send_rich(args.api, token, args.chat_id, rich_text(args, arranged), media, silent, sleep)
    posted = [{"file": name, "message_id": message["message_id"]} for name, _, _ in arranged]
    if args.out:
        Path(args.out).write_text(json.dumps(posted) + "\n", encoding="utf-8")
    if args.copy_to:
        served = served_files(message)
        missing = [name for name, _, _ in arranged if name not in served]
        if missing:
            raise PublishError(f"the posted message does not name the file {missing[0]}, it cannot be repeated")
        try:
            link = rich_post.post_link(args.chat_id, message["message_id"])
        except rich_post.PostError:
            link = ""
        again = [(f"f{index}", served[name]) for index, (name, _, _) in enumerate(arranged)]
        for target in args.copy_to:
            send_rich(args.api, token, target, rich_text(args, arranged, link), again, silent, sleep)
    return posted


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api", default="http://127.0.0.1:8081", help="the Bot API server")
    parser.add_argument("--chat-id", required=True, help="the channel: its id or @username")
    parser.add_argument("--copy-to", action="append", default=[], metavar="CHAT",
                        help="another channel that gets the post as well")
    parser.add_argument("--style", choices=("rich", "album"), default="rich")
    parser.add_argument("--kind", choices=("release", "test"), default="release",
                        help="a test build has a smaller title and is sent silently")
    parser.add_argument("--title", help="the name of the application")
    parser.add_argument("--version")
    parser.add_argument("--build", default="", help="shown in brackets after the version")
    parser.add_argument("--hashtag", action="append", default=[], help="without the '#'")
    parser.add_argument("--notes-file", help="Markdown notes of the release")
    parser.add_argument("--notes-en-file", help="English notes, folded under the others")
    parser.add_argument("--fold-section", action="append", default=[], metavar="HEADING",
                        help="a '## ' section of the notes to fold")
    parser.add_argument("--drop-section", action="append", default=[], metavar="HEADING",
                        help="a '## ' section of the notes to leave out")
    parser.add_argument("--commits-file", help='JSON list of commits, [{"id", "message"}]')
    parser.add_argument("--repository", default="", help="address of the repository of the commits")
    parser.add_argument("--body-file", help="plain text under the title")
    parser.add_argument("--files-title", default="", help="heading above the files")
    parser.add_argument("--folded-files-title", default="", help="summary of the folded files")
    parser.add_argument("--file-rule", action="append", default=[], metavar="'PATTERN | CAPTION | folded'")
    parser.add_argument("--button-row", action="append", default=[], metavar="'TEXT=ADDRESS | ...'")
    parser.add_argument("--caption-file", help="a ready HTML caption of an album")
    parser.add_argument("--out", help="write the posted messages here as JSON")
    parser.add_argument("--dry-run", action="store_true", help="print the text and the files")
    parser.add_argument("files", nargs="+")
    args = parser.parse_args(argv)
    try:
        paths = [Path(name) for name in args.files]
        check_files(paths)
        if not (args.title and args.version) and not (args.style == "album" and args.caption_file):
            raise PublishError("give --title and --version")
        # The text is put together before anything is asked of the server,
        # so that a wrong argument is reported at once.
        if args.style == "rich":
            rules = [rich_post.parse_file_rule(line) for line in args.file_rule]
            arranged = rich_post.arrange({path.name for path in paths}, rules)
            text = rich_text(args, arranged)
            names = [name for name, _, _ in arranged]
        else:
            text = album_text(args)
            names = [path.name for path in paths]
        if args.dry_run:
            print(text, end="" if text.endswith("\n") else "\n")
            print("\n".join(names))
            for target in args.copy_to:
                print(f"also to {target}")
            return 0
        token = os.environ.get("CHANNEL_BOT_TOKEN", "")
        if not token:
            raise PublishError("CHANNEL_BOT_TOKEN is not set")
        bot = wait_ready(args.api, token)
        print(f"Posting as @{bot.get('username')} to {args.chat_id}.", flush=True)
        if args.style == "rich":
            publish_rich(args, token, paths)
        else:
            posted = publish(args.api, token, args.chat_id, paths, text)
            # Written before the copies: a failing copy must not hide the post.
            if args.out:
                Path(args.out).write_text(json.dumps(posted) + "\n", encoding="utf-8")
            for target in args.copy_to:
                copy(args.api, token, args.chat_id, target, posted)
    except (PublishError, rich_post.PostError, OSError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
