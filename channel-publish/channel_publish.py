#!/usr/bin/env python3
"""Post build files to a Telegram channel through a local Bot API server.

The server runs with --local, which raises the 50 MB limit of the public
Bot API to 2000 MB and takes a file by its path on the server's side, so
nothing is uploaded over HTTP: the files are in a directory the server
sees as --server-dir.

The files go out as documents, in albums of up to ten, with the caption
under the last one. The caption is either a ready HTML file or is put
together here from a title, a version, hashtags, a plain text body and
links; a body that does not fit loses its last lines.

The bot token is read from CHANNEL_BOT_TOKEN. The posted messages are
written to --out as JSON, [{"file": <name>, "message_id": <id>}], for the
steps that record them elsewhere.
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

ALBUM = 10
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


def parse_link(value):
    text, separator, address = value.partition("=")
    if not separator or not text.strip() or not re.match(r"(https?|tg)://", address.strip()):
        raise PublishError(f"'{value}' is not a link: write TEXT=ADDRESS")
    return text.strip(), address.strip()


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


def reference(path, server_dir):
    """The address of the file as the server finds it."""
    if server_dir:
        return f"file://{server_dir.rstrip('/')}/{path.name}"
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


def publish(api, token, chat, paths, text, server_dir=None, sleep=time.sleep):
    """Post the files; returns [{"file": <name>, "message_id": <id>}]."""
    posted = []
    albums = [paths[start:start + ALBUM] for start in range(0, len(paths), ALBUM)]
    for index, album in enumerate(albums):
        last = index + 1 == len(albums)
        if len(album) == 1:
            payload = {"chat_id": chat, "document": reference(album[0], server_dir)}
            if last:
                payload.update(caption=text, parse_mode="HTML")
            messages = [call(api, token, "sendDocument", payload, sleep=sleep)]
        else:
            media = [
                {"type": "document", "media": reference(path, server_dir)} for path in album
            ]
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


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api", default="http://127.0.0.1:8081", help="the Bot API server")
    parser.add_argument("--chat-id", required=True, help="the channel: its id or @username")
    parser.add_argument("--server-dir", help="where the server sees the directory of the files")
    parser.add_argument("--title", help="the name of the application")
    parser.add_argument("--version")
    parser.add_argument("--hashtag", action="append", default=[], help="without the '#'")
    parser.add_argument("--body-file", help="plain text under the title, cut to fit")
    parser.add_argument("--link", action="append", default=[], metavar="TEXT=ADDRESS")
    parser.add_argument("--caption-file", help="a ready HTML caption, instead of the parts above")
    parser.add_argument("--out", help="write the posted messages here as JSON")
    parser.add_argument("--dry-run", action="store_true", help="print the caption and the files")
    parser.add_argument("files", nargs="+")
    args = parser.parse_args(argv)
    try:
        paths = [Path(name) for name in args.files]
        check_files(paths)
        if args.caption_file:
            text = Path(args.caption_file).read_text(encoding="utf-8").strip()
        elif args.title and args.version:
            body = Path(args.body_file).read_text(encoding="utf-8") if args.body_file else ""
            links = [parse_link(value) for value in args.link]
            text = caption(args.title, args.version, args.hashtag, body, links)
        else:
            raise PublishError("give --caption-file, or --title and --version")
        if args.dry_run:
            print(text)
            for path in paths:
                print(reference(path, args.server_dir))
            return 0
        token = os.environ.get("CHANNEL_BOT_TOKEN", "")
        if not token:
            raise PublishError("CHANNEL_BOT_TOKEN is not set")
        bot = wait_ready(args.api, token)
        print(f"Posting as @{bot.get('username')} to {args.chat_id}.", flush=True)
        posted = publish(args.api, token, args.chat_id, paths, text, args.server_dir)
    except (PublishError, OSError) as error:
        print(error, file=sys.stderr)
        return 1
    if args.out:
        Path(args.out).write_text(json.dumps(posted) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
