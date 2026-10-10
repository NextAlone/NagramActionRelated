#!/usr/bin/env python3
"""Tests of rich_post.py: python3 channel-publish/test_rich_post.py"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import rich_post as post

NOTES = """Nagram Desktop 7.3.0.1, see [7.2.10.3](https://example.org/v7.2.10.3).

## Upstream

- wallet

## New

- one
- `7.3.0.1` stays

## Packages

| a | b |
"""


class TextTest(unittest.TestCase):
    def test_escape_keeps_text_literal(self):
        # Checked against the server: a backslash before another mark, such
        # as ':' or ',', would be shown, and '<' would start a tag.
        self.assertEqual(
            post.escape("fix(a): `c`, *s* _u_ <t> & [b](x) #h a|b ~~s~~ ==m== $x$ >q"),
            "fix\\(a\\): \\`c\\`, \\*s\\* \\_u\\_ &lt;t\\> &amp; \\[b\\]\\(x\\) \\#h a\\|b \\~\\~s\\~\\~ \\=\\=m\\=\\= \\$x\\$ \\>q",
        )

    def test_four_part_versions_are_not_left_to_become_links(self):
        self.assertEqual(
            post.plain_versions("Nagram 7.3.0.1, [7.2.10.3](https://e.org/v7.2.10.3), `1.2.3.4`, 12.10.6, 1.2.3.4.5, 7.3.0.2."),
            "Nagram `7.3.0.1`, [7.2.10.3](https://e.org/v7.2.10.3), `1.2.3.4`, 12.10.6, 1.2.3.4.5, `7.3.0.2`.",
        )

    def test_heading(self):
        self.assertEqual(post.heading("Nagram Desktop", "7.3.0.1"), "# Nagram Desktop `7.3.0.1`")
        self.assertEqual(
            post.heading("Nagram", "12.10.6", "7112", small=True), "### Nagram `12.10.6` \\(7112\\)"
        )

    def test_hashtags(self):
        self.assertEqual(post.hashtags_line(["desktop", "beta"]), "\\#desktop \\#beta")
        self.assertEqual(post.hashtags_line([]), "")
        with self.assertRaises(post.PostError):
            post.hashtags_line(["two words"])

    def test_compose_skips_the_empty_blocks(self):
        self.assertEqual(post.compose(["a", "", "b"]), "a\n\nb\n")
        with self.assertRaises(post.PostError):
            post.compose(["x" * (post.TEXT_LIMIT + 1)])

    def test_post_link(self):
        self.assertEqual(post.post_link("@nagram_assets", 7), "https://t.me/nagram_assets/7")
        self.assertEqual(post.post_link("-1001234567890", 7), "https://t.me/c/1234567890/7")
        with self.assertRaises(post.PostError):
            post.post_link("12345", 7)


class NotesTest(unittest.TestCase):
    def test_sections_are_folded_and_dropped_in_place(self):
        self.assertEqual(
            post.notes_blocks(NOTES, fold=["Upstream"], drop=["Packages"]),
            [
                "Nagram Desktop `7.3.0.1`, see [7.2.10.3](https://example.org/v7.2.10.3).",
                "<details><summary>Upstream</summary>\n- wallet\n</details>",
                "## New\n\n- one\n- `7.3.0.1` stays",
            ],
        )

    def test_notes_without_sections(self):
        self.assertEqual(post.notes_blocks("Just a line.\n"), ["Just a line."])

    def test_heading_the_notes_do_not_have_is_passed_over(self):
        self.assertEqual(
            post.notes_blocks("Intro.\n\n## New\n\n- one\n", fold=["Upstream"], drop=["Packages"]),
            ["Intro.", "## New\n\n- one"],
        )

    def test_summary_is_not_taken_for_a_tag(self):
        self.assertEqual(post.details("a <b>", "x"), "<details><summary>a &lt;b&gt;</summary>\nx\n</details>")


class CommitsTest(unittest.TestCase):
    def test_commits_are_grouped_in_a_fixed_order(self):
        commits = [
            {"id": "1111111aaaa", "message": "chore: three"},
            {"id": "2222222bbbb", "message": "fix(ui): one\n\nbody"},
            {"id": "3333333cccc", "message": "FEAT!: two"},
            {"id": "4444444dddd", "message": "Merge branch 'x'"},
            {"id": "5555555eeee", "message": "no kind here"},
            {"id": "6666666ffff", "message": "refa: four"},
        ]
        self.assertEqual(
            post.commits_block(commits, "https://e.org/r/"),
            "**✨ Features**\n- [`3333333`](https://e.org/r/commit/3333333cccc) FEAT!: two\n\n"
            "**🔧 Fixes**\n- [`2222222`](https://e.org/r/commit/2222222bbbb) fix\\(ui\\): one\n\n"
            "**♻️ Refactor**\n- [`6666666`](https://e.org/r/commit/6666666ffff) refa: four\n\n"
            "**🧹 Chore**\n- [`1111111`](https://e.org/r/commit/1111111aaaa) chore: three\n\n"
            "**🔀 Merge**\n- [`4444444`](https://e.org/r/commit/4444444dddd) Merge branch 'x'\n\n"
            "**📌 Other**\n- [`5555555`](https://e.org/r/commit/5555555eeee) no kind here",
        )

    def test_commit_without_a_repository_or_an_id(self):
        self.assertEqual(post.commits_block([{"id": "abcdef0123", "message": "fix: a"}]), "**🔧 Fixes**\n- `abcdef0` fix: a")
        self.assertEqual(post.commits_block([{"message": "fix: a"}]), "**🔧 Fixes**\n- fix: a")

    def test_setting_paths_follow_their_commit(self):
        message = "feat: quick reply\n\nSetting-Path: Chats > Quick reply | tg://nnn/chat?r=quick\nsetting-path: Plain"
        self.assertEqual(
            post.commits_block([{"id": "abcdef0123", "message": message}]),
            "**✨ Features**\n- `abcdef0` feat: quick reply\n"
            "  - ↳ [Chats \\> Quick reply](tg://nnn/chat?r=quick)\n"
            "  - ↳ Plain",
        )

    def test_many_commits_end_with_a_count(self):
        commits = [{"id": f"{n:07}", "message": f"fix: {n}"} for n in range(post.COMMITS_SHOWN + 3)]
        block = post.commits_block(commits)
        self.assertEqual(block.count("\n- "), post.COMMITS_SHOWN)
        self.assertTrue(block.endswith("\n\n*… 3 more*"))

    def test_no_commits(self):
        self.assertEqual(post.commits_block([]), "")

    def test_bad_commit(self):
        with self.assertRaises(post.PostError):
            post.commits_block(["fix: a"])


class FilesTest(unittest.TestCase):
    def test_rules(self):
        self.assertEqual(post.parse_file_rule("*.dmg | macOS | folded"), ("*.dmg", "macOS", True))
        self.assertEqual(post.parse_file_rule("*.dmg|macOS"), ("*.dmg", "macOS", False))
        self.assertEqual(post.parse_file_rule(" *.dmg "), ("*.dmg", "", False))
        for line in ("", " | macOS", "*.dmg | macOS | shown", "a | b | folded | c"):
            with self.assertRaises(post.PostError):
                post.parse_file_rule(line)

    def test_files_follow_the_rules_and_the_rest_comes_last(self):
        names = {"N-macos.zip", "N-macos.dmg", "N-linux.tar.xz", "N-extra.bin"}
        rules = [("*.dmg", "disk image", False), ("*-windows-*", "none of these", False), ("*-macos*", "archive", True)]
        self.assertEqual(
            post.arrange(names, rules),
            [
                ("N-macos.dmg", "disk image", False),
                ("N-macos.zip", "archive", True),
                ("N-extra.bin", "", False),
                ("N-linux.tar.xz", "", False),
            ],
        )

    def test_files_block(self):
        files = [("f0", "macOS", False), ("f1", "", False), ("f2", 'the "portable" one', True)]
        self.assertEqual(
            post.files_block(files, "Download", "Other"),
            "## Download\n\n"
            '![](tg://document?id=f0 "macOS")\n![](tg://document?id=f1)\n\n'
            "<details><summary>Other</summary>\n![](tg://document?id=f2 \"the 'portable' one\")\n</details>",
        )
        self.assertEqual(post.files_block([("f0", "", False)]), "![](tg://document?id=f0)")


class ButtonsTest(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(
            post.parse_button_row("*GitHub Release=https://e.org/a=b | Assets = {post}"),
            [("GitHub Release", "https://e.org/a=b", True), ("Assets", "{post}", False)],
        )
        for value in ("https://e.org", "=https://e.org", "Release=javascript:1", "A=https://e.org | B"):
            with self.assertRaises(post.PostError):
                post.parse_button_row(value)

    def test_buttons_of_the_post_need_its_address(self):
        rows = [[("Release", "https://e.org/?a=1&b=2", True)], [("A <b>", "{post}", False)]]
        first = (
            '<tg-button-row align="center">\n'
            '  <tg-button type="url" style="primary" url="https://e.org/?a=1&amp;b=2">Release</tg-button>\n'
            "</tg-button-row>"
        )
        self.assertEqual(post.buttons_block(rows), first)
        self.assertEqual(
            post.buttons_block(rows, "https://t.me/c/1/2"),
            first + '\n<tg-button-row align="center">\n'
            '  <tg-button type="url" url="https://t.me/c/1/2">A &lt;b&gt;</tg-button>\n'
            "</tg-button-row>",
        )
        self.assertEqual(post.buttons_block([]), "")


if __name__ == "__main__":
    unittest.main()
