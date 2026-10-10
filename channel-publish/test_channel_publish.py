#!/usr/bin/env python3
"""Tests of channel_publish.py: python3 channel-publish/test_channel_publish.py"""
import contextlib
import io
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import channel_publish as channel

TOKEN = "123:secret"
BOT = {"ok": True, "result": {"username": "nagram_bot"}}


def messages(first, count):
    return {"ok": True, "result": [{"message_id": first + n} for n in range(count)]}


class Server:
    """A Bot API server that answers from a list and keeps what it was asked."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                owner.calls.append((self.path, json.loads(body)))
                status, answer = owner.answers.pop(0)
                raw = json.dumps(answer).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.address = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class CaptionTest(unittest.TestCase):
    def test_parts(self):
        text = channel.caption(
            "Nagram Desktop",
            "7.3.0.1-beta",
            ["desktop", "beta"],
            "Fixed <this> & that.",
            [("GitHub Release", "https://example.org/r?a=1&b=2")],
        )
        self.assertEqual(
            text,
            "<b>Nagram Desktop</b> <code>7.3.0.1-beta</code>\n"
            "#desktop #beta\n\n"
            "Fixed &lt;this&gt; &amp; that.\n\n"
            '<a href="https://example.org/r?a=1&amp;b=2">GitHub Release</a>',
        )

    def test_title_and_version_alone(self):
        self.assertEqual(channel.caption("Nagram", "1.0"), "<b>Nagram</b> <code>1.0</code>")

    def test_long_body_loses_its_last_lines(self):
        body = "\n".join(f"line {n} " + "x" * 90 for n in range(30))
        text = channel.caption("Nagram", "1.0", body=body, links=[("Release", "https://e.org")])
        self.assertLessEqual(channel.units(text), channel.CAPTION_LIMIT)
        self.assertIn("line 0 ", text)
        self.assertNotIn("line 29 ", text)
        self.assertIn("\n…\n\n<a href", text)

    def test_length_is_counted_in_utf16(self):
        self.assertEqual(channel.units("a😀"), 3)
        body = "\n".join("😀" * 100 for _ in range(8))
        text = channel.caption("Nagram", "1.0", body=body)
        self.assertLessEqual(channel.units(text), channel.CAPTION_LIMIT)
        self.assertEqual(text.count("😀"), 400)

    def test_caption_too_long_without_a_body(self):
        with self.assertRaises(channel.PublishError):
            channel.caption("N" * 2000, "1.0")

    def test_bad_hashtag(self):
        with self.assertRaises(channel.PublishError):
            channel.caption("Nagram", "1.0", ["two words"])

    def test_links(self):
        self.assertEqual(channel.parse_link("Release = https://e.org/a=b"), ("Release", "https://e.org/a=b"))
        for value in ("https://e.org", "=https://e.org", "Release=javascript:1"):
            with self.assertRaises(channel.PublishError):
                channel.parse_link(value)


class PublishTest(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        self.server = None

    def tearDown(self):
        if self.server:
            self.server.close()
        self._temp.cleanup()

    def files(self, count):
        paths = []
        for n in range(count):
            path = self.root / f"Nagram-{n:02}.zip"
            path.write_bytes(b"package")
            paths.append(path)
        return paths

    def serve(self, *answers):
        self.server = Server(answers)
        return self.server

    def test_single_file_is_a_document(self):
        server = self.serve((200, {"ok": True, "result": {"message_id": 7}}))
        posted = channel.publish(server.address, TOKEN, "@channel", self.files(1), "text", "/upload")
        self.assertEqual(posted, [{"file": "Nagram-00.zip", "message_id": 7}])
        path, payload = server.calls[0]
        self.assertEqual(path, f"/bot{TOKEN}/sendDocument")
        self.assertEqual(
            payload,
            {
                "chat_id": "@channel",
                "document": "file:///upload/Nagram-00.zip",
                "caption": "text",
                "parse_mode": "HTML",
            },
        )

    def test_album_has_the_caption_under_the_last_file(self):
        server = self.serve((200, messages(10, 3)))
        posted = channel.publish(server.address, TOKEN, "-1001", self.files(3), "text", "/upload/")
        self.assertEqual([entry["message_id"] for entry in posted], [10, 11, 12])
        path, payload = server.calls[0]
        self.assertEqual(path, f"/bot{TOKEN}/sendMediaGroup")
        self.assertEqual(payload["chat_id"], "-1001")
        self.assertEqual(
            payload["media"],
            [
                {"type": "document", "media": "file:///upload/Nagram-00.zip"},
                {"type": "document", "media": "file:///upload/Nagram-01.zip"},
                {
                    "type": "document",
                    "media": "file:///upload/Nagram-02.zip",
                    "caption": "text",
                    "parse_mode": "HTML",
                },
            ],
        )

    def test_more_than_ten_files_make_several_albums(self):
        server = self.serve((200, messages(1, 10)), (200, {"ok": True, "result": {"message_id": 11}}))
        posted = channel.publish(server.address, TOKEN, "1", self.files(11), "text", "/upload")
        self.assertEqual(len(posted), 11)
        self.assertEqual([path.rsplit("/", 1)[1] for path, _ in server.calls], ["sendMediaGroup", "sendDocument"])
        self.assertFalse(any("caption" in item for item in server.calls[0][1]["media"]))
        self.assertEqual(server.calls[1][1]["caption"], "text")

    def test_without_a_server_directory_the_own_path_is_used(self):
        path = self.files(1)[0]
        self.assertEqual(channel.reference(path, None), path.resolve().as_uri())

    def test_flood_wait_is_tried_again(self):
        flood = {"ok": False, "error_code": 429, "description": "Too Many Requests", "parameters": {"retry_after": 5}}
        server = self.serve((429, flood), (200, {"ok": True, "result": {"message_id": 3}}))
        waits = []
        posted = channel.publish(server.address, TOKEN, "1", self.files(1), "text", sleep=waits.append)
        self.assertEqual(posted[0]["message_id"], 3)
        self.assertEqual(waits, [5])
        self.assertEqual(len(server.calls), 2)

    def test_another_failure_is_not_tried_again(self):
        server = self.serve((400, {"ok": False, "error_code": 400, "description": "Bad Request: chat not found"}))
        with self.assertRaises(channel.PublishError) as raised:
            channel.publish(server.address, TOKEN, "1", self.files(2), "text")
        self.assertIn("chat not found", str(raised.exception))
        self.assertEqual(len(server.calls), 1)

    def test_answer_without_the_messages(self):
        server = self.serve((200, messages(1, 1)))
        with self.assertRaises(channel.PublishError):
            channel.publish(server.address, TOKEN, "1", self.files(2), "text")

    def test_unreachable_server_does_not_show_the_token(self):
        with self.assertRaises(channel.PublishError) as raised:
            channel.call("http://127.0.0.1:1", TOKEN, "sendDocument", {})
        self.assertNotIn("secret", str(raised.exception))

    def test_wait_for_a_server_that_never_starts(self):
        now = [0]

        def sleep(seconds):
            now[0] += seconds

        with self.assertRaises(channel.PublishError) as raised:
            channel.wait_ready("http://127.0.0.1:1", TOKEN, wait=6, sleep=sleep, clock=lambda: now[0])
        self.assertIn("did not start", str(raised.exception))
        self.assertNotIn("secret", str(raised.exception))
        self.assertEqual(now[0], 6)

    def test_rejected_token(self):
        server = self.serve((401, {"ok": False, "error_code": 401, "description": "Unauthorized"}))
        with self.assertRaises(channel.PublishError) as raised:
            channel.wait_ready(server.address, TOKEN)
        self.assertIn("Unauthorized", str(raised.exception))

    def test_copy_keeps_the_order_of_the_messages(self):
        server = self.serve((200, messages(40, 3)))
        posted = [{"file": name, "message_id": n} for name, n in (("b", 12), ("a", 10), ("c", 11))]
        copied = channel.copy(server.address, TOKEN, "-1001", "@official", posted)
        self.assertEqual(copied, [40, 41, 42])
        path, payload = server.calls[0]
        self.assertEqual(path, f"/bot{TOKEN}/copyMessages")
        self.assertEqual(
            payload, {"chat_id": "@official", "from_chat_id": "-1001", "message_ids": [10, 11, 12]}
        )

    def test_copy_of_more_than_a_hundred_messages(self):
        server = self.serve((200, messages(500, 100)), (200, messages(600, 1)))
        posted = [{"file": str(n), "message_id": n} for n in range(1, 102)]
        copied = channel.copy(server.address, TOKEN, "1", "2", posted)
        self.assertEqual(len(copied), 101)
        self.assertEqual(server.calls[1][1]["message_ids"], [101])

    def test_copy_answer_without_the_messages(self):
        server = self.serve((200, messages(1, 1)))
        with self.assertRaises(channel.PublishError):
            channel.copy(server.address, TOKEN, "1", "2", [{"file": "a", "message_id": 1}, {"file": "b", "message_id": 2}])

    def test_file_checks(self):
        (self.root / "empty.zip").write_bytes(b"")
        other = self.root / "other"
        other.mkdir()
        (other / "Nagram-00.zip").write_bytes(b"package")
        for paths in (
            [self.root / "missing.zip"],
            [self.root / "empty.zip"],
            self.files(1) + [other / "Nagram-00.zip"],
        ):
            with self.assertRaises(channel.PublishError):
                channel.check_files(paths)

    def run_main(self, *arguments, token=TOKEN):
        out, err = io.StringIO(), io.StringIO()
        before = os.environ.get("CHANNEL_BOT_TOKEN")
        os.environ["CHANNEL_BOT_TOKEN"] = token
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                status = channel.main(list(arguments))
        finally:
            if before is None:
                del os.environ["CHANNEL_BOT_TOKEN"]
            else:
                os.environ["CHANNEL_BOT_TOKEN"] = before
        return status, out.getvalue(), err.getvalue()

    def test_main_posts_and_writes_the_messages(self):
        server = self.serve((200, BOT), (200, messages(20, 2)))
        result = self.root / "result.json"
        status, out, _ = self.run_main(
            "--api", server.address, "--chat-id", "-1001", "--server-dir", "/upload",
            "--title", "Nagram Desktop", "--version", "7.3.0.1", "--hashtag", "desktop",
            "--link", "GitHub Release=https://example.org/r", "--out", str(result),
            *map(str, self.files(2)),
        )
        self.assertEqual(status, 0)
        self.assertIn("@nagram_bot", out)
        self.assertEqual(
            json.loads(result.read_text(encoding="utf-8")),
            [{"file": "Nagram-00.zip", "message_id": 20}, {"file": "Nagram-01.zip", "message_id": 21}],
        )
        self.assertEqual(server.calls[0][0], f"/bot{TOKEN}/getMe")
        self.assertEqual(
            server.calls[1][1]["media"][-1]["caption"],
            "<b>Nagram Desktop</b> <code>7.3.0.1</code>\n#desktop\n\n"
            '<a href="https://example.org/r">GitHub Release</a>',
        )

    def test_main_copies_to_the_other_channels(self):
        server = self.serve(
            (200, BOT), (200, messages(20, 2)), (200, messages(7, 2)),
            (400, {"ok": False, "error_code": 400, "description": "Bad Request: chat not found"}),
        )
        result = self.root / "result.json"
        status, out, err = self.run_main(
            "--api", server.address, "--chat-id", "-1001", "--copy-to", "@official", "--copy-to", "@missing",
            "--title", "Nagram", "--version", "1.0", "--out", str(result), *map(str, self.files(2)),
        )
        self.assertEqual(status, 1)
        self.assertIn("copied to @official: messages 7, 8", out)
        self.assertIn("chat not found", err)
        self.assertEqual([entry["message_id"] for entry in json.loads(result.read_text())], [20, 21])
        self.assertEqual([payload.get("chat_id") for _, payload in server.calls[2:]], ["@official", "@missing"])

    def test_main_takes_a_ready_caption(self):
        server = self.serve((200, BOT), (200, {"ok": True, "result": {"message_id": 1}}))
        ready = self.root / "caption.html"
        ready.write_text("<b>Nnngram</b>\n", encoding="utf-8")
        status, _, _ = self.run_main(
            "--api", server.address, "--chat-id", "1", "--caption-file", str(ready), str(self.files(1)[0])
        )
        self.assertEqual(status, 0)
        self.assertEqual(server.calls[1][1]["caption"], "<b>Nnngram</b>")

    def test_main_dry_run_asks_nothing(self):
        status, out, _ = self.run_main(
            "--chat-id", "1", "--server-dir", "/upload", "--title", "Nagram", "--version", "1.0",
            "--dry-run", str(self.files(1)[0]), token="",
        )
        self.assertEqual(status, 0)
        self.assertEqual(out, "<b>Nagram</b> <code>1.0</code>\nfile:///upload/Nagram-00.zip\n")
        status, out, _ = self.run_main(
            "--chat-id", "1", "--copy-to", "@official", "--title", "Nagram", "--version", "1.0",
            "--dry-run", str(self.files(1)[0]), token="",
        )
        self.assertEqual(status, 0)
        self.assertTrue(out.endswith("copy to @official\n"))

    def test_main_failures(self):
        path = str(self.files(1)[0])
        for arguments, token, message in (
            (("--chat-id", "1", path), TOKEN, "--caption-file"),
            (("--chat-id", "1", "--title", "Nagram", "--version", "1.0", path), "", "CHANNEL_BOT_TOKEN"),
            (("--chat-id", "1", "--title", "Nagram", "--version", "1.0", "missing.zip"), TOKEN, "not a file"),
        ):
            status, _, err = self.run_main(*arguments, token=token)
            self.assertEqual(status, 1)
            self.assertIn(message, err)


if __name__ == "__main__":
    unittest.main()
