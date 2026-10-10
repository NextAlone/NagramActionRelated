"""The text of a post as a rich message, in the Markdown of sendRichMessage.

Every application gets the same skeleton:

    # <title> `<version>` (<build>)
    #hashtags

    <notes, with chosen sections folded or dropped>
    <English notes, folded>
    <commits, grouped by their kind>

    ## <files title>
    <files with their captions; the less wanted ones folded>

    <rows of buttons>

A file is a link tg://document?id=<id>, the id names it in the media of
the message. A button whose address is {post} points to the first post of
the files and is left out of that post itself.
"""

import html
import re
from fnmatch import fnmatchcase

TEXT_LIMIT = 32768
COMMITS_SHOWN = 40
POST = "{post}"

# Conventional Commits kinds in the order they are shown.
GROUPS = (
    ("feat", "✨ Features", ("feat",)),
    ("fix", "🔧 Fixes", ("fix",)),
    ("perf", "⚡ Performance", ("perf",)),
    ("refactor", "♻️ Refactor", ("refactor", "refa")),
    ("docs", "📝 Docs", ("docs", "doc")),
    ("test", "✅ Tests", ("test",)),
    ("build", "📦 Build", ("build",)),
    ("ci", "⚙️ CI", ("ci",)),
    ("style", "💄 Style", ("style",)),
    ("chore", "🧹 Chore", ("chore",)),
    ("revert", "⏪ Revert", ("revert",)),
    ("merge", "🔀 Merge", ("merge",)),
    ("other", "📌 Other", ()),
)
KINDS = {name: key for key, _, names in GROUPS for name in names}
SUBJECT = re.compile(r"(?P<kind>[A-Za-z]+)(?:\([^)]*\))?!?:\s*.+")
# A trailer naming where the setting of a feature is: "<path>" or "<path> | <address>".
SETTING = re.compile(r"\s*Setting-Path\s*:\s*(.+?)\s*", re.IGNORECASE)
# The marks a backslash makes literal; before any other one it would stay in the text.
MARKS = re.compile(r"([\\`*_\[\]()#~=$|>])")
# A four-part version is taken for an IP address and made a link.
VERSION = re.compile(r"(?<![\w.\[/`])(\d+\.\d+\.\d+\.\d+)(?![\w`]|\.\w)")
HASHTAG = re.compile(r"\w+")
ADDRESS = re.compile(r"(https?|tg)://\S+")


class PostError(Exception):
    pass


def escape(text):
    """Plain text for Markdown: nothing in it is taken for formatting or a tag."""
    return MARKS.sub(r"\\\1", text.replace("&", "&amp;").replace("<", "&lt;"))


def plain_versions(text):
    return VERSION.sub(r"`\1`", text)


def sections(notes):
    """Split notes into the introduction and the (heading, body) of each '## '."""
    parts = re.split(r"^##[ \t]+(.+?)[ \t]*$", notes, flags=re.MULTILINE)
    pairs = [(parts[n].strip(), parts[n + 1].strip()) for n in range(1, len(parts), 2)]
    return parts[0].strip(), pairs


def details(summary, body):
    return f"<details><summary>{html.escape(summary)}</summary>\n{body.strip()}\n</details>"


def notes_blocks(notes, fold=(), drop=()):
    """The notes as blocks, folding or dropping the sections with the given headings.

    A heading the notes do not have is passed over: the same headings are
    given for every release, and not every release has every section.
    """
    introduction, pairs = sections(plain_versions(notes))
    blocks = [introduction] if introduction else []
    for heading, body in pairs:
        if heading in drop:
            continue
        elif heading in fold:
            blocks.append(details(heading, body))
        else:
            blocks.append(f"## {heading}\n\n{body}")
    return blocks


def parse_commit(entry):
    """A commit of a push event, {"id", "message"}, as what is shown of it."""
    if not isinstance(entry, dict) or not isinstance(entry.get("message"), str):
        raise PostError("a commit is an object with a message")
    lines = entry["message"].replace("\r", "").strip().split("\n")
    subject = lines[0].strip()
    settings = []
    for line in lines[1:]:
        match = SETTING.fullmatch(line)
        if match:
            path, separator, address = match.group(1).partition("|")
            settings.append((path.strip(), address.strip() if separator else ""))
    match = SUBJECT.fullmatch(subject)
    if match:
        kind = KINDS.get(match.group("kind").lower(), "other")
    elif subject.lower().startswith("merge "):
        kind = "merge"
    else:
        kind = "other"
    sha = entry.get("id") or entry.get("sha") or ""
    return {"sha": sha if isinstance(sha, str) else "", "subject": subject, "kind": kind, "settings": settings}


def commits_block(entries, repository=""):
    """The commits as lists under their kinds; past COMMITS_SHOWN only a count is left."""
    commits = [parse_commit(entry) for entry in entries]
    commits = [commit for commit in commits if commit["subject"]]
    shown, hidden = commits[:COMMITS_SHOWN], len(commits) - COMMITS_SHOWN
    blocks = []
    for key, label, _ in GROUPS:
        lines = []
        for commit in shown:
            if commit["kind"] != key:
                continue
            short = commit["sha"][:7]
            if short and repository:
                chip = f"[`{short}`]({repository.rstrip('/')}/commit/{commit['sha']}) "
            else:
                chip = f"`{short}` " if short else ""
            lines.append(f"- {chip}{escape(commit['subject'])}")
            for path, address in commit["settings"]:
                where = f"[{escape(path)}]({address})" if ADDRESS.fullmatch(address) else escape(path)
                lines.append(f"  - ↳ {where}")
        if lines:
            blocks.append(f"**{label}**\n" + "\n".join(lines))
    if hidden > 0:
        blocks.append(f"*… {hidden} more*")
    return "\n\n".join(blocks)


def parse_file_rule(line):
    """'PATTERN | CAPTION | folded' as (pattern, caption, folded)."""
    fields = [field.strip() for field in line.split("|")]
    if not fields[0] or len(fields) > 3 or (len(fields) == 3 and fields[2] != "folded"):
        raise PostError(f"'{line}' is not a file rule: write PATTERN | CAPTION | folded")
    return fields[0], fields[1] if len(fields) > 1 else "", len(fields) == 3


def arrange(names, rules):
    """Order the files by the rules; returns [(name, caption, folded)].

    A rule that matches no file is skipped, since a release may lack a
    platform; a file no rule matches comes last, without a caption.
    """
    left = sorted(names)
    arranged = []
    for pattern, caption, folded in rules:
        matched = [name for name in left if fnmatchcase(name, pattern)]
        arranged.extend((name, caption, folded) for name in matched)
        left = [name for name in left if name not in matched]
    return arranged + [(name, "", False) for name in left]


def parse_button(value):
    """'TEXT=ADDRESS', with '*' before the text of the main button."""
    text, separator, address = value.partition("=")
    text, address = text.strip(), address.strip()
    primary = text.startswith("*")
    text = text.lstrip("*").strip()
    if not separator or not text or not (address == POST or ADDRESS.fullmatch(address)):
        raise PostError(f"'{value}' is not a button: write TEXT=ADDRESS")
    return text, address, primary


def parse_button_row(line):
    return [parse_button(value) for value in line.split("|")]


def buttons_block(rows, post=""):
    """The rows of buttons; without the address of the post, its buttons are left out."""
    blocks = []
    for row in rows:
        buttons = []
        for text, address, primary in row:
            if address == POST:
                if not post:
                    continue
                address = post
            style = ' style="primary"' if primary else ""
            buttons.append(
                f'  <tg-button type="url"{style} url="{html.escape(address)}">{html.escape(text)}</tg-button>'
            )
        if buttons:
            blocks.append('<tg-button-row align="center">\n' + "\n".join(buttons) + "\n</tg-button-row>")
    return "\n".join(blocks)


def file_line(key, caption):
    if caption:
        return f'![](tg://document?id={key} "{caption.replace(chr(92), "").replace(chr(34), chr(39))}")'
    return f"![](tg://document?id={key})"


def files_block(files, title="", folded_title=""):
    """The files as blocks; files is [(key, caption, folded)]."""
    shown = [file_line(key, caption) for key, caption, folded in files if not folded]
    folded = [file_line(key, caption) for key, caption, folded in files if folded]
    blocks = []
    if title:
        blocks.append(f"## {escape(title)}")
    if shown:
        blocks.append("\n".join(shown))
    if folded:
        blocks.append(details(folded_title or "…", "\n".join(folded)))
    return "\n\n".join(blocks)


def heading(title, version, build="", small=False):
    text = f"{'###' if small else '#'} {escape(title)} `{version.replace('`', '')}`"
    return text + (f" \\({escape(build)}\\)" if build else "")


def hashtags_line(tags):
    for tag in tags:
        if not HASHTAG.fullmatch(tag):
            raise PostError(f"'{tag}' is not a hashtag: letters, digits and '_' only")
    return " ".join(f"\\#{tag}" for tag in tags)


def compose(blocks):
    """Join the blocks that are not empty and check the length of the post."""
    text = "\n\n".join(block for block in blocks if block) + "\n"
    if len(text) > TEXT_LIMIT:
        raise PostError(f"the post is {len(text)} characters long, a rich message holds {TEXT_LIMIT}")
    return text


def post_link(chat, message):
    """The address of a post of a channel given by @username or by its id."""
    chat = str(chat)
    if chat.startswith("@"):
        return f"https://t.me/{chat[1:]}/{message}"
    elif chat.startswith("-100") and chat[4:].isdigit():
        return f"https://t.me/c/{chat[4:]}/{message}"
    raise PostError(f"no address of a post can be made from the chat '{chat}'")
