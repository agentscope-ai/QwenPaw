# NocoBase Auth Plugin

Make NocoBase the sole authority for who can use QwenPaw and over which channel. NocoBase owns the user accounts, passwords, and login tokens end-to-end; QwenPaw stores no user copy. Identity and roles are resolved **live** from NocoBase on each request (with a short in-memory cache) — there is no local user mirror to keep in sync.

## What it does

- **Login**: username/password is verified against NocoBase (`auth:signIn`); the NocoBase-issued token is passed through to the client, so NocoBase owns token issuing and verification.
- **Per-request identity**: a NocoBase token (from the `X-NocoBase-Token` header, an `Authorization: Bearer` header, or a `?token=` query param) is verified live via `auth:check`, yielding the caller's `sender_id` (the configurable `user_id_field`, default `email`) and their NocoBase roles. Cached briefly (~60s).
- **Console access control**: the `console` channel is **fail-closed** — a request with no resolved NocoBase identity is denied. A resolved user is allowed unless the role→channel map (`role_channel_map`) explicitly denies one of their roles; an empty map allows any authenticated NocoBase user.
- **Admin views**: `GET /nocobase-auth/users` and `/roles` query NocoBase live (using the admin `api_token`).

## Configuration

Stored in `~/.qwenpaw/nocobase_auth_config.json` (the `api_token` is encrypted at rest). On first run, if that file does not exist, the plugin seeds it from environment variables:

- `QWENPAW_NOCOBASE_ENABLED` — `true` / `1` / `yes`
- `QWENPAW_NOCOBASE_BASE_URL` — e.g. `http://nocobase:13000`
- `QWENPAW_NOCOBASE_API_TOKEN` — admin token; **only** needed for the `/users` and `/roles` admin views. Login and the console gate do NOT require it (they use the caller's own token).
- `QWENPAW_NOCOBASE_USER_ID_FIELD` — default `email`
- `QWENPAW_NOCOBASE_AUTHENTICATOR` — default `basic`

You can also edit these via the plugin's admin page or `PUT /nocobase-auth/config`. An existing config file is never overwritten by the env seed.

## Endpoints

- `GET /nocobase-auth/status` — enabled/configured status.
- `GET /nocobase-auth/users`, `GET /nocobase-auth/roles` — live NocoBase data. If NocoBase is unreachable or unconfigured these return an error, never a silently empty list.
- `GET /nocobase-auth/config`, `PUT /nocobase-auth/config` — read/update integration config + `role_channel_map`.
- `POST /nocobase-auth/test-connection` — connectivity check.

## Availability

Console auth resolves live against NocoBase (with a short cache). If NocoBase is unreachable beyond the cache TTL, console logins/requests fail closed. External chat channels keep QwenPaw's native whitelist/blacklist as before.

## Upgrading from the sync-based version

Earlier versions mirrored NocoBase users/roles into `~/.qwenpaw/nocobase_permissions.json` and exposed `/sync` + `/webhook`. Those are removed. After upgrading you may delete `~/.qwenpaw/nocobase_permissions.json` (it is no longer read). Do **not** delete `nocobase_auth_config.json`. Local QwenPaw accounts are also gone — if you relied on `~/.qwenpaw.secret/auth.json`, note that authentication now requires NocoBase.
