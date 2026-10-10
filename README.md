# NagramActionRelated

GitHub Actions shared by the Nagram projects (Nagram for Android, Nagram for iOS, Nagram Desktop, Nnngram). Each action is a directory of its own; reference it by a full commit:

```yaml
uses: NextAlone/NagramActionRelated/<action>@<commit>
```

## channel-publish

Posts the files of a directory to a Telegram channel as documents, in albums of up to ten, with one caption under the last file.

Build packages are larger than the 50 MB the public Bot API accepts, so the action starts a Bot API server in `--local` mode for the duration of the call (2000 MB per file, files are read from a mounted directory instead of being uploaded over HTTP). It needs a Linux runner with Docker: a macOS or Windows build hands its files over as an artifact to a Linux job.

```yaml
- uses: NextAlone/NagramActionRelated/channel-publish@<commit>
  with:
    bot-token: ${{ secrets.NAGRAM_CHANNEL_BOT_TOKEN }}
    api-id: ${{ secrets.NAGRAM_API_ID }}
    api-hash: ${{ secrets.NAGRAM_API_HASH }}
    image: ${{ vars.NAGRAM_BOT_API_IMAGE }}
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
| `image` | The Bot API server image, `ghcr.io/<owner>/telegram-bot-api@sha256:<digest>`. |
| `registry-token` | Token to pull the image with, when the package is not public. |
| `chat-id` | The channel, its id or `@username`. |
| `directory` | Directory whose files are posted, in the order of their names. |
| `title`, `version` | The first line of the caption. |
| `hashtags` | Hashtags without `#`, separated by spaces. |
| `body-file` | Plain text under the title; its last lines are dropped when the caption would exceed 1024 characters. |
| `links` | Links that close the caption, one `TEXT=ADDRESS` per line. |
| `caption-file` | A ready HTML caption, used instead of the five inputs above. |

The output `messages` is JSON, `[{"file": <name>, "message_id": <id>}]`, for steps that record the posted messages elsewhere, such as the metadata an in-app updater reads.

Only a flood wait is retried. After any other failure the post may have gone through, so the step fails instead of sending it again.

### The Bot API image

The container receives the bot token and every posted file, so it is built here and never taken from a third party. Run the `Bot API image.` workflow with a full `tdlib/telegram-bot-api` commit, then set the variable `NAGRAM_BOT_API_IMAGE` to the digest-pinned reference it prints in every repository that uses the action. Make the GHCR package public, or pass `registry-token`.

### Tests

```bash
python3 channel-publish/test_channel_publish.py
```
