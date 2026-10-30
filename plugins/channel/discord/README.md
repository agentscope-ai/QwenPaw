# Discord official channel plugin

Private integration preview. The v2 descriptor runs
`qwenpaw_channel_discord.driver.DiscordDriver` in the existing runner
process with shared dependencies. `discord-py` and Gateway callbacks are loaded in that worker only.
Install dependencies explicitly through the existing plugin installation flow.

The routing/configuration identity remains `discord`. Existing bot token,
proxy/auth, bot message and mention policies, DM/channel/thread sessions,
media directory and `DISCORD_*` environment inputs are retained. ACL, approval,
Agent execution and message queues remain in the host. Source installation,
global/workspace enablement, worker readiness and Gateway connection are
separate states.

Text uses Discord's 2000 character limit with legacy fenced-code chunking.
Images, audio, video, files and data URLs are sent as attachments. Local media
must be inside the configured media directory or projected workspace; remote
HTTP(S) and data URLs are explicit external inputs. Temporary outbound files
and SDK file handles are cleaned on failure and cancellation.

Typing is owned by a response handle; reasoning and message streams have
separate native message IDs. Stream edits never substitute a new message after
an uncertain SDK result. Long final output replaces a placeholder only after
its deletion is confirmed. Native network/5xx outcomes and partially completed
multipart sends retain an unknown receipt rather than replaying effects.
Thread starter routing supports the existing on_thread_create-before-message
race; the inverse race has no new guarantee.

Stop fences callbacks and awaits Gateway, download, typing and thread eviction
tasks. A failed SDK close retains the client for retry. Two workspaces use
separate plugin instances and media/state roots. Uninstall clears plugin
installation settings while preserving channels.discord configuration and
business files through the existing Loader transaction.

No live Discord account was used for migration validation. Release measurements
across all 16 channels and public marketplace publication remain separate work.
