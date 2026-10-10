# NagramActionRelated

GitHub Actions shared by the Nagram projects (Nagram for Android, Nagram for iOS, Nagram Desktop, Nnngram). Each action is a directory of its own; reference it by a full commit:

```yaml
uses: NextAlone/NagramActionRelated/<action>@<commit>
```

## channel-publish

Posts the files of a directory to a Telegram channel as documents, in albums of up to ten, with one caption under the last file.

Build packages are larger than the 50 MB the public Bot API accepts, so the action runs a Bot API server in `--local` mode for the duration of the call (2000 MB per file, files are read by their path instead of being uploaded over HTTP). It needs an `ubuntu-24.04` runner, the system the server is built on: a macOS or Windows build hands its files over as an artifact to a Linux job.

```yaml
- uses: NextAlone/NagramActionRelated/channel-publish@<commit>
  with:
    bot-token: ${{ secrets.NAGRAM_CHANNEL_BOT_TOKEN }}
    api-id: ${{ secrets.NAGRAM_API_ID }}
    api-hash: ${{ secrets.NAGRAM_API_HASH }}
    chat-id: ${{ vars.NAGRAM_CHANNEL_CHAT_ID }}
    directory: upload
    title: Nagram Desktop
    version: 7.3.0.1
    hashtags: desktop
    links: |
      GitHub Release=https://github.com/NextAlone/Nagram-Qt/releases/tag/v7.3.0.1
```

| Input | |
| --- | --- |
| `bot-token` | Token of a bot that may post in the channel. |
| `api-id`, `api-hash` | Telegram API credentials the Bot API server runs with. |
| `chat-id` | The channel, its id or `@username`. |
| `copy-to` | Other channels that get a copy of the post, separated by spaces or lines. The server copies the messages, the files are not sent again. |
| `directory` | Directory whose files are posted, in the order of their names. |
| `title`, `version` | The first line of the caption. |
| `hashtags` | Hashtags without `#`, separated by spaces. |
| `body-file` | Plain text under the title; its last lines are dropped when the caption would exceed 1024 characters. |
| `links` | Links that close the caption, one `TEXT=ADDRESS` per line. |
| `caption-file` | A ready HTML caption, used instead of the five inputs above. |

The output `messages` is JSON, `[{"file": <name>, "message_id": <id>}]`, for steps that record the posted messages elsewhere, such as the metadata an in-app updater reads. It lists the messages in `chat-id`, not the copies.

Only a flood wait is retried. After any other failure the post may have gone through, so the step fails instead of sending it again.

### The Bot API server

The server receives the bot token and every posted file, so it is built here and never taken from a third party. The `Bot API binary.` workflow builds it from a full `tdlib/telegram-bot-api` commit and attaches it to a release of this repository; the action downloads it from there and checks it against the SHA-256 recorded in `channel-publish/action.yml`.

To upgrade, run the workflow with the new commit and write the release name and the checksum it prints into `BOT_API_RELEASE` and `BOT_API_SHA256` of the action. The repositories that use the action need no setting for the server, they take it with the commit of the action.

### Tests

```bash
python3 channel-publish/test_channel_publish.py
```
