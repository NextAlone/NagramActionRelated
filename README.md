# NagramActionRelated

GitHub Actions shared by the Nagram projects (Nagram for Android, Nagram for iOS, Nagram Desktop, Nnngram). Each action is a directory of its own; reference it by a full commit:

```yaml
uses: NextAlone/NagramActionRelated/<action>@<commit>
```

## channel-publish

Posts the files of a directory to a Telegram channel. Every application hands over its data and gets the same layout, by default one rich message:

```
# <title> <version> (<build>)
#hashtags

<notes of the release, with chosen sections folded or left out>
<English notes, folded>
<commits, grouped by their kind>

## <files title>
<files with their captions; the less wanted ones folded>

<rows of buttons>
```

Build packages are larger than the 50 MB the public Bot API accepts, so the action runs a Bot API server in `--local` mode for the duration of the call (2000 MB per file, files are read by their path instead of being uploaded over HTTP). It needs an `ubuntu-24.04` runner, the system the server is built on: a macOS or Windows build hands its files over as an artifact to a Linux job.

A release, with its notes and the packages:

```yaml
- uses: NextAlone/NagramActionRelated/channel-publish@<commit>
  with:
    bot-token: ${{ secrets.NAGRAM_CHANNEL_BOT_TOKEN }}
    api-id: ${{ secrets.NAGRAM_API_ID }}
    api-hash: ${{ secrets.NAGRAM_API_HASH }}
    chat-id: ${{ vars.NAGRAM_CHANNEL_ASSETS_CHAT_ID }}
    copy-to: ${{ vars.NAGRAM_CHANNEL_CHAT_ID }}
    directory: upload
    title: Nagram Desktop
    version: 7.3.0.1
    hashtags: desktop release
    notes-file: docs/releases/v7.3.0.1.md
    notes-en-file: docs/releases/v7.3.0.1.en.md
    fold-sections: Upstream
    files-title: Download
    folded-files-title: Other packages
    files: |
      *-macos.dmg | macOS
      *-windows-x64-setup.exe | Windows x64 · installer
      *-windows-x64.zip | Windows x64 · portable | folded
    buttons: |
      *GitHub Release=https://github.com/NextAlone/Nagram-Qt/releases/tag/v7.3.0.1
      Feedback=https://t.me/OrIssuesBot | Assets={post}
```

A build of a push, with the commits it brings:

```yaml
- uses: NextAlone/NagramActionRelated/channel-publish@<commit>
  with:
    bot-token: ${{ secrets.NAGRAM_CHANNEL_BOT_TOKEN }}
    api-id: ${{ secrets.NAGRAM_API_ID }}
    api-hash: ${{ secrets.NAGRAM_API_HASH }}
    chat-id: ${{ vars.NAGRAM_CHANNEL_ASSETS_CHAT_ID }}
    directory: upload
    kind: test
    title: Nagram Desktop
    version: 7.3.0.1
    build: abc1234
    hashtags: desktop test macos
    commits-file: commits.json
    buttons: Commit=https://github.com/NextAlone/Nagram-Qt/commit/abc1234
```

| Input | |
| --- | --- |
| `bot-token` | Token of a bot that may post in the channels. |
| `api-id`, `api-hash` | Telegram API credentials the Bot API server runs with. |
| `chat-id` | The channel, its id or `@username`. |
| `copy-to` | Other channels that get the post as well, separated by spaces or lines. The files are not sent again. |
| `directory` | Directory whose files are posted. |
| `style` | `rich` (default) for one rich message; `album` for documents in albums of up to ten with a short caption under the last, for the clients and the cases a rich message does not suit. |
| `kind` | `release` (default), or `test` for a build of a push: a smaller title, sent without a notification. |
| `title`, `version`, `build` | The heading: the name, the version, and what is shown in brackets after it. |
| `hashtags` | Hashtags without `#`, separated by spaces. |
| `notes-file` | Markdown notes of the release, sent as they are. A version of four parts is set in code style, because a client takes it for an IP address. |
| `notes-en-file` | English notes, folded under the others. |
| `fold-sections`, `drop-sections` | Headings of the `## ` sections of the notes to fold or to leave out, one per line. A heading the notes do not have is passed over. |
| `commits-file` | JSON list of commits, `[{"id", "message"}]` as in a push event. They are shown grouped by their Conventional Commits kind and linked to `repository`; past forty only a count is left. A `Setting-Path: <path> \| <address>` trailer is shown under its commit. |
| `repository` | Address of the repository the commits link to; the calling repository by default. |
| `body-file` | Plain text under the title. |
| `files-title`, `folded-files-title` | Heading above the files and summary of the folded ones. |
| `files` | Order and captions of the files, one `PATTERN \| CAPTION \| folded` per line; the caption and `folded` are optional. A line that matches nothing is skipped, files no line matches come last. |
| `buttons` | Rows of buttons, one row per line: `TEXT=ADDRESS \| TEXT=ADDRESS`. `*` before a text marks the main button. The address `{post}` is the first post of the files; such a button is left out of that post and shown in the copies. |
| `caption-file` | A ready HTML caption of an album, used instead of the parts above. |

The output `messages` is JSON, `[{"file": <name>, "message_id": <id>}]`, for steps that record the posted messages elsewhere, such as the metadata an in-app updater reads. It lists the messages in `chat-id`, not the copies; the files of a rich message share one message.

In `copy-to` channels a rich message is sent anew with the files the first post already put on the server, so its buttons can point back to that post; an album is copied by the server.

Only a flood wait is retried. After any other failure the post may have gone through, so the step fails instead of sending it again.

### The Bot API server

The server receives the bot token and every posted file, so it is built here and never taken from a third party. The `Bot API binary.` workflow builds it from a full `tdlib/telegram-bot-api` commit and attaches it to a release of this repository; the action downloads it from there and checks it against the SHA-256 recorded in `channel-publish/action.yml`.

To upgrade, run the workflow with the new commit and write the release name and the checksum it prints into `BOT_API_RELEASE` and `BOT_API_SHA256` of the action. The repositories that use the action need no setting for the server, they take it with the commit of the action.

### Tests

```bash
python3 channel-publish/test_rich_post.py
python3 channel-publish/test_channel_publish.py
```
