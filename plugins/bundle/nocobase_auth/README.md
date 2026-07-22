# NocoBase Auth Plugin for QwenPaw

Sync NocoBase users and roles into QwenPaw's channel access control. NocoBase becomes the source of truth for who can talk to the agent over which channel; QwenPaw's native whitelist/blacklist remains as a fallback when NocoBase is unreachable or has no opinion.

## Features

- Sync NocoBase users and roles via REST API.
- Map NocoBase roles to allowed/denied QwenPaw channels.
- Webhook endpoint for near-real-time sync from NocoBase.
- Manual sync fallback.
- Console UI for connection config, user inspection, and role mapping.

## Installation

1. Open the QwenPaw Console.
2. Go to **Plugins**.
3. Install from local path: `plugins/bundle/nocobase_auth` (or upload a zip of this directory).
4. Refresh the page to load the frontend plugin.

## Configuration

After installation, open **NocoBase Auth** in the left sidebar.

| Field | Description |
|-------|-------------|
| Enable NocoBase ACL | Turn the integration on/off. |
| NocoBase Address | Base URL of your self-hosted NocoBase, e.g. `https://nocobase.example.com`. |
| API Token | NocoBase API token with permission to read `/api/users:list` and `/api/roles:list`. |
| User ID Field | Which NocoBase user field maps to the QwenPaw channel sender ID. Default: `email`. |

Click **Test Connection** to verify, then **Save**.

## Role → Channel Mapping

On the **Role Mapping** page, configure for each NocoBase role:

- **Allowed channels**: channel keys the role may use (e.g. `console`, `dingtalk`, `telegram`).
- **Denied channels**: channel keys the role is explicitly blocked from.

Deny takes precedence over allow. Unknown channels fall back to QwenPaw's native ACL.

## Webhook Setup (optional)

To sync immediately when users or roles change in NocoBase:

1. In NocoBase, configure a webhook plugin to call:
   ```
   POST https://<qwenpaw-host>/api/nocobase-auth/webhook
   ```
2. Trigger on user/role create/update/delete events.

The plugin accepts the webhook asynchronously and runs a full sync.

## How It Works

1. On startup, the plugin performs a full sync from NocoBase to a local JSON cache (`~/.qwenpaw/nocobase_permissions.json`).
2. When a channel message arrives, the plugin's ACL checker runs before QwenPaw's native whitelist/blacklist.
3. If NocoBase says allow → message passes.
4. If NocoBase says deny → message is blocked.
5. If NocoBase has no opinion (user unknown or channel not mapped) → QwenPaw native ACL decides.
6. If NocoBase is unreachable → QwenPaw native ACL decides.

## Files

- `plugin.py` — plugin entry point, registers hooks and channel gate checker.
- `nocobase_client.py` — NocoBase REST client.
- `permission_store.py` — local JSON cache and permission evaluation.
- `sync_engine.py` — sync orchestration.
- `routers.py` — HTTP API endpoints.
- `config.py` — configuration model and persistence.
- `channel_gate.py` — channel access control checker.
- `frontend/` — Console UI plugin.

## Requirements

- `httpx` (auto-installed by the plugin loader).
- NocoBase self-hosted (Community/Enterprise) with API token authentication.

## Troubleshooting

- **Status shows `configured: false`**: save the connection config first.
- **Sync returns auth error**: verify the API token and that the NocoBase user has read access to the `users` and `roles` collections.
- **Users are not matched**: ensure the selected **User ID Field** matches the value sent by the channel as `sender_id` (e.g. the user's email).
