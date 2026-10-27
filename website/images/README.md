# Docs images

Static media for the Mintlify site. Files here are served from the site root,
so a file at `website/images/foo.png` is referenced in `.mdx` as `/images/foo.png`.

## Conventions

- **Images:** commit PNG/SVG here. Compress screenshots (e.g. `pngquant`, `oxipng`)
  before committing — keep them small since they live in git.
- **Videos:** do **not** commit video files. Host walkthroughs on YouTube (unlisted)
  or Loom and embed the URL with an `<iframe>` in the `.mdx` page.

## Referencing in .mdx

```mdx
<Frame caption="Creating a bot with @BotFather">
  <img src="/images/botfather-newbot.png" alt="BotFather /newbot flow" />
</Frame>
```

## Placeholders expected by quickstart.mdx

Drop these files here, then uncomment the matching `<Frame>` block in `quickstart.mdx`:

| File | Step | Type | Shows |
|---|---|---|---|
| `docker-running.svg` | 0 | SVG mockup | `docker compose version` + `ps` with all containers up |
| `botfather-newbot.png` | 1 | screenshot | The @BotFather `/newbot` flow and token |
| `ios-shortcut-sms.jpeg` | 2 | screenshot (name redacted) | iOS SMS automation (Sender → Telegram) |
| `ios-shortcut-push.jpeg` | 2 | screenshot (name redacted) | iOS push automation (bank app → Telegram) |
| `env-annotated.svg` | 4 | SVG mockup | Filled `.env` (fake values) with arrows to each value's source |
| `bot-status-reply.svg` | 5 | SVG mockup | Telegram chat: `/start` wizard + `/status` reply |

All placeholders are now filled. The `.svg` mockups are hand-built (editable text); the `.png`/`.jpeg` files are real screenshots. The two iOS screenshots had the Telegram recipient name pixelated for privacy.
