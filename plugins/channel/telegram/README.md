# Telegram channel

Telegram Bot API polling integration, loaded in the shared channel worker.
Configure the existing `channels.telegram` settings; bot tokens, optional
`base_url`, HTTP proxy/auth, typing, display and access policy retain their
existing meanings. Explicit plugin installation/repair installs dependencies;
ordinary startup never installs packages.

Sessions remain `telegram:{chat_id}`. Forum topics select reply routing within
that existing session. Text, Rich Messages, media, streaming and approval cards
use response ownership and durable delivery receipts. Button receipt is neutral;
the host validates the actual clicker before a confirmed approval result edits
the owned card. Expired or unowned cards cannot authorize an action.

Stopping and uninstalling preserve channel configuration, sessions and media.
New presentation fields require the declared opt-in send capabilities.
