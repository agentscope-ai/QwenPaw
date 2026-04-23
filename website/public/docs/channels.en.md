# Channels

A **channel** is where you talk to QwenPaw: connect DingTalk and it replies
in DingTalk; same for QQ, etc. If that term is new, see [Introduction](./intro).

Two ways to configure channels:

- **Console** (recommended) — In the [Console](./console) under **Control → Channels**, click a channel card, enable it and fill in credentials in the drawer. Changes take effect when you save.
- **Edit `agent.json` directly** — Agent workspace config at `~/.qwenpaw/workspaces/{agent_id}/agent.json`, set `enabled: true` and fill in that platform's credentials. Saving triggers a reload without restarting the app.

Below is how to get credentials and fill config for each channel.

---

## DingTalk (recommended)

### Create a DingTalk app

Video tutorial:

![Video tutorial](https://cloud.video.taobao.com/vod/Fs7JecGIcHdL-np4AS7cXaLoywTDNj7BpiO7_Hb2_cA.mp4)

Step-by-step:

1. Open the [DingTalk Developer Portal](https://open-dev.dingtalk.com/)

2. Create an **internal enterprise app**

   ![internal enterprise app](https://img.alicdn.com/imgextra/i1/O1CN01KLtwvu1rt9weVn8in_!!6000000005688-2-tps-2809-1585.png)

3. Add the **「Robot」** capability

   ![add robot](https://img.alicdn.com/imgextra/i2/O1CN01AboPsn1XGQ84utCG8_!!6000000002896-2-tps-2814-1581.png)

4. Set message receiving mode to **Stream** then publish

   ![robot](https://img.alicdn.com/imgextra/i3/O1CN01KwmNZ61GwhDhKxgSv_!!6000000000687-2-tps-2814-1581.png)

   ![Stream](https://img.alicdn.com/imgextra/i2/O1CN01tk8QW11NqvXYqcoPH_!!6000000001622-2-tps-2809-1590.png)

5. Create a new version to publish, fill in basic info and save

   ![new version](https://img.alicdn.com/imgextra/i3/O1CN01lRCPuf1PQwIeFL4AL_!!6000000001836-2-tps-2818-1590.png)

   ![save](https://img.alicdn.com/imgextra/i1/O1CN01vrzbIA1Qey2x8Jbua_!!6000000002002-2-tps-2809-1585.png)

6. In the app details, copy:

   - **Client ID** (AppKey)
   - **Client Secret** (AppSecret)

   ![client](https://img.alicdn.com/imgextra/i3/O1CN01JsRrwx1hJImLfM7O1_!!6000000004256-2-tps-2809-1585.png)

7. (Optional) **Add your server's IP to the whitelist** — this is required for features that call the DingTalk Open API (e.g. downloading images and files sent by users). Go to **"Security & Compliance → IP Whitelist"** in your app settings and add the public IP of the machine running QwenPaw. You can find your public IP by running `curl ifconfig.me` in a terminal. If the IP is not whitelisted, image and file downloads will fail with a `Forbidden.AccessDenied.IpNotInWhiteList` error.

### Link the app

You can configure it either in the Console frontend or by editing the agent workspace `agent.json`.

**Method 1**: Configure in the Console frontend

Go to "Control→Channels", find **DingTalk**, click it, and enter the **Client ID** and **Client Secret** you just obtained.

![console](https://img.alicdn.com/imgextra/i3/O1CN01h4fEUa244rSp3WR0T_!!6000000007338-2-tps-3822-2070.png)

**Method 2**: Edit agent workspace `agent.json`

In your agent's `agent.json` (e.g., `~/.qwenpaw/workspaces/default/agent.json`), find `channels.dingtalk` and fill in the corresponding information, for example:

```json
"dingtalk": {
  "enabled": true,
  "bot_prefix": "[BOT]",
  "client_id": "your Client ID",
  "client_secret": "your Client Secret",
  "message_type": "markdown",
  "card_template_id": "",
  "card_template_key": "content",
  "robot_code": "",
  "filter_tool_messages": false
}
```

**DingTalk-specific fields:**

| Field               | Type   | Default         | Description                                                                                                      |
| ------------------- | ------ | --------------- | ---------------------------------------------------------------------------------------------------------------- |
| `client_id`         | string | `""` (required) | DingTalk app Client ID (AppKey)                                                                                  |
| `client_secret`     | string | `""` (required) | DingTalk app Client Secret (AppSecret)                                                                           |
| `message_type`      | string | `"markdown"`    | Message mode: `"markdown"` (default) or `"card"` (AI interactive card)                                           |
| `card_template_id`  | string | `""`            | DingTalk AI Card template ID (required when `message_type` is `card`)                                            |
| `card_template_key` | string | `"content"`     | AI Card variable key; must exactly match your template variable name                                             |
| `robot_code`        | string | `""`            | Robot code (recommended explicit config for group card delivery scenarios; falls back to `client_id` when empty) |
| `media_dir`         | string | `null`          | Media file download directory (leave empty to not save)                                                          |

> **Tips:**
>
> - Set `filter_tool_messages: true` if you want to hide tool execution details in the chat.
> - AI Card mode: set `message_type` to `card`, then configure `card_template_id`; keep `card_template_key` consistent with your DingTalk template variable (default `content`).
> - `robot_code` is recommended in group scenarios; if empty, QwenPaw falls back to `client_id`.

Save the file; if the app is already running, the channel will reload. Otherwise run `qwenpaw app`.

### Find the created app

Video tutorial:

![Video tutorial](https://cloud.video.taobao.com/vod/Ppt7rLy5tvuMFXDLks8Y2hDYV9hAfoZ78Y8mC0wUn1g.mp4)

Step-by-step:

1. In DingTalk, tap the **search box** in the **[Messages]** tab

![Search box](https://img.alicdn.com/imgextra/i4/O1CN01qVVqyx1Mh1MLdOq2X_!!6000000001465-2-tps-2809-2236.png)

2. Search for the **bot name** you just created; find the bot under **[Functions]**

![Bot](https://img.alicdn.com/imgextra/i3/O1CN01AzxSlR2AJPjY6xfOU_!!6000000008182-2-tps-2809-2236.png)

3. Tap to open the chat

![Chat](https://img.alicdn.com/imgextra/i4/O1CN01ut70CJ1pXyOO5sg7P_!!6000000005371-2-tps-2032-1614.png)

> You can add the bot to a group chat via **Group Settings → Bots → Add a robot in DingTalk**. If you create a group chat from your one-on-one chat with the bot, the bot’s replies will not be triggered.

---

## Feishu (Lark)

The Feishu channel receives messages via **WebSocket long connection** (no public IP or webhook). Sending uses the Feishu Open API. It supports text, image, and file in both directions. For group chats, `chat_id` and `message_id` are included in the request message metadata for downstream deduplication and context.

### Create a Feishu app and get credentials

1. Open the [Feishu Open Platform](https://open.feishu.cn/app) and create an enterprise app

![Feishu](https://img.alicdn.com/imgextra/i4/O1CN01pb7WtO1Zvl6rlQllk_!!6000000003257-2-tps-4082-2126.png)

![Build](https://img.alicdn.com/imgextra/i4/O1CN018o4NsY1Q0fC22LtRv_!!6000000001914-2-tps-4082-2126.png)

2. In **Credentials & Basic Info**, copy **App ID** and **App Secret**

![ID & Secret](https://img.alicdn.com/imgextra/i2/O1CN01XISo4K2A9nPrMUT4f_!!6000000008161-2-tps-4082-2126.png)

3. Fill **App ID** and **App Secret** in `agent.json` (see "Fill agent.json" below) and save

4. Run **`qwenpaw app`** to start QwenPaw

5. Back in the Feishu console, enable **Bot** under **Add Features**

![Bot](https://img.alicdn.com/imgextra/i3/O1CN01kqWyqE1mM7IAlSf8k_!!6000000004939-2-tps-4082-2126.png)

6. Under **Permissions & Scopes**, select **Batch import/export scopes** and paste the following JSON:

```json
{
  "scopes": {
    "tenant": [
      "aily:file:read",
      "aily:file:write",
      "aily:message:read",
      "aily:message:write",
      "corehr:file:download",
      "im:chat",
      "im:message",
      "im:message.group_msg",
      "im:message.p2p_msg:readonly",
      "im:message.reactions:read",
      "im:resource",
      "contact:user.base:readonly"
    ],
    "user": []
  }
}
```

![Import/Export](https://img.alicdn.com/imgextra/i1/O1CN01mrXvWI1tiHm1tm9BE_!!6000000005935-2-tps-4082-2126.png)

![JSON](https://img.alicdn.com/imgextra/i4/O1CN01YJPgEg20OmDC1SfEa_!!6000000006840-2-tps-4082-2126.png)

![Confirm](https://img.alicdn.com/imgextra/i3/O1CN01J37Aq41GH1B7NgLYi_!!6000000000596-2-tps-4082-2126.png)

![Confirm](https://img.alicdn.com/imgextra/i1/O1CN01N0ZPMt1LM7fi35WAn_!!6000000001284-2-tps-4082-2126.png)

7. Under **Events & Callbacks**, click **Event configuration**, and choose **Receive events through persistent connection** as the subscription mode (no public IP needed)

> **Note:** Follow this order: Configure App ID/Secret → start `qwenpaw app` → then configure the long connection in the Feishu console. If errors persist, try stopping the qwenpaw service and restarting `qwenpaw app`.

![WebSocket](https://img.alicdn.com/imgextra/i3/O1CN01XdU7hK1fVY8gIDhZK_!!6000000004012-2-tps-4082-2126.png)

8. Select **Add Events**, search for **Message received**, and subscribe to **Message received v2.0**

![Receive](https://img.alicdn.com/imgextra/i1/O1CN01EE4iZf1CnIdDDeli6_!!6000000000125-2-tps-4082-2126.png)

![Click](https://img.alicdn.com/imgextra/i2/O1CN01PlzsFU1JhWx9EcuPc_!!6000000001060-2-tps-4082-2126.png)

![Result](https://img.alicdn.com/imgextra/i2/O1CN01fiMjkp24mN51TyWcI_!!6000000007433-2-tps-4082-2126.png)

9. Under **App Versions** → **Version Management & Release**, **Create a version**, fill in basic info, **Save** and **Publish**

![Create](https://img.alicdn.com/imgextra/i3/O1CN01mzOHs11cdO4MnZMcX_!!6000000003623-2-tps-4082-2126.png)

![Info](https://img.alicdn.com/imgextra/i1/O1CN01y1SkZP24hKiufZpb5_!!6000000007422-2-tps-4082-2126.png)

![Save](https://img.alicdn.com/imgextra/i2/O1CN01o1Wq3n2AD0BkIVidL_!!6000000008168-2-tps-4082-2126.png)

![pub](https://img.alicdn.com/imgextra/i1/O1CN01dcWI7F1PmSuniDLJx_!!6000000001883-2-tps-4082-2126.png)

### Fill agent.json

Find `channels.feishu` in your agent's `agent.json` (e.g., `~/.qwenpaw/workspaces/default/agent.json`). Only **App ID** and **App Secret** are required (copy from the Feishu console under Credentials & basic info):

```json
"feishu": {
  "enabled": true,
  "bot_prefix": "[BOT]",
  "app_id": "cli_xxxxx",
  "app_secret": "your App Secret",
  "domain": "feishu"
}
```

**Feishu-specific fields:**

| Field                | Type   | Default         | Description                                    |
| -------------------- | ------ | --------------- | ---------------------------------------------- |
| `app_id`             | string | `""` (required) | Feishu App ID                                  |
| `app_secret`         | string | `""` (required) | Feishu App Secret                              |
| `domain`             | string | `"feishu"`      | `"feishu"` (China) or `"lark"` (International) |
| `encrypt_key`        | string | `""`            | Event encryption key (optional)                |
| `verification_token` | string | `""`            | Event verification token (optional)            |
| `media_dir`          | string | `null`          | Directory for received media files             |

> **Tip:** Other fields (encrypt_key, verification_token, media_dir) are optional; with WebSocket mode you can omit them (defaults apply).

**Dependencies:** `pip install lark-oapi`

If your environment uses a SOCKS proxy, also install `python-socks` (for example, `pip install python-socks`), otherwise you may see: `python-socks is required to use a SOCKS proxy`.

> **Note:** You can also fill in **App ID** and **App Secret** in the Console UI, but you must restart the qwenpaw service before continuing with the long-connection configuration.
> ![console](https://img.alicdn.com/imgextra/i4/O1CN01OXdwjN1KVS8Nsc1he_!!6000000001169-2-tps-3822-2070.png)

### Recommended bot permissions

The JSON in step 6 grants the following permissions (app identity) for messaging and files:

| Permission name                     | Permission ID                  | Type    | Notes         |
| ----------------------------------- | ------------------------------ | ------- | ------------- |
| Get file                            | aily:file:read                 | App     | -             |
| Upload file                         | aily:file:write                | App     | -             |
| Get message                         | aily:message:read              | App     | -             |
| Send message                        | aily:message:write             | App     | -             |
| Download file                       | corehr:file:download           | App     | -             |
| Get/update group info               | im:chat                        | App     | -             |
| Get/send chat and group messages    | im:message                     | App     | -             |
| Get all group messages (sensitive)  | im:message.group_msg           | App     | -             |
| Read user-to-bot DMs                | im:message.p2p_msg:readonly    | App     | -             |
| View message reactions              | im:message.reactions:read      | App     | -             |
| Get/upload image and file resources | im:resource                    | App     | -             |
| **Read contact as app**             | **contact:user.base:readonly** | **App** | **See below** |

> **User display name (recommended):** To show **user nicknames** in sessions and logs (e.g. "张三#1d1a" instead of "unknown#1d1a"), enable the contact read permission **Read contact as app** (`contact:user.base:readonly`). Without it, Feishu only returns identity fields (e.g. open_id) and not the user's name, so QwenPaw cannot resolve nicknames. After enabling, publish or update the app version so the permission takes effect.

### Add the bot to favorites

1. In the **Workplace**, tap add **Favorites**

![Add favorite](https://img.alicdn.com/imgextra/i2/O1CN01G32zCo1gKqUyJH8H7_!!6000000004124-2-tps-2614-1488.png)

2. Search for the bot name you created and tap **Add**

![Add](https://img.alicdn.com/imgextra/i3/O1CN01paAwW31XhRUuRq7vi_!!6000000002955-2-tps-3781-2154.png)

3. The bot will appear in your favorites; tap it to open the chat

![Added](https://img.alicdn.com/imgextra/i4/O1CN012n7SOT1D07imvq7LY_!!6000000000153-2-tps-2614-1488.png)

![Chat](https://img.alicdn.com/imgextra/i2/O1CN01upVEJw1zKMmYtP9PP_!!6000000006695-2-tps-2614-1488.png)

---

## iMessage (macOS only)

> ⚠️ The iMessage channel is **macOS only**. It relies on the local Messages app and the iMessage database, so it cannot run on Linux or Windows.

The app polls the local iMessage database for new messages and sends replies on your behalf.

1. Ensure **Messages** is signed in on this Mac (open the Messages app and sign in with your Apple ID in System Settings).

2. Install **imsg** (used to access the iMessage database):

   ```bash
   brew install steipete/tap/imsg
   ```

   > If installation fails on Intel Mac, clone the repo and build from source:
   >
   > ```bash
   > git clone https://github.com/steipete/imsg.git
   > cd imsg
   > make build
   > sudo cp build/Release/imsg /usr/local/bin/
   > cp ./bin/imsg /usr/local/bin/
   > ```

3. For QwenPaw to read iMessage data, **Terminal** (or the app you use to run `qwenpaw app`) and **Messages** need **Full Disk Access** (System Settings → Privacy & Security → Full Disk Access).

4. Set the iMessage database path. The default is `~/Library/Messages/chat.db`; use this unless you've moved the database. You can configure it in either of these ways:

   - In **Console → Channels**, click the **iMessage** card, turn **Enable** on, enter the path in **DB Path**, and click **Save**.

     ![console](https://img.alicdn.com/imgextra/i3/O1CN01LXTm20287qVYjicfn_!!6000000007886-2-tps-3822-2070.png)

   - Or edit the agent workspace `agent.json` (usually at `~/.qwenpaw/workspaces/default/agent.json`):

     ```json
     "imessage": {
       "enabled": true,
       "bot_prefix": "[BOT]",
       "db_path": "~/Library/Messages/chat.db",
       "poll_sec": 1.0
     }
     ```

**iMessage-specific fields:**

| Field      | Type   | Default                      | Description                |
| ---------- | ------ | ---------------------------- | -------------------------- |
| `db_path`  | string | `~/Library/Messages/chat.db` | iMessage database path     |
| `poll_sec` | float  | `1.0`                        | Polling interval (seconds) |

5. After saving, send any message from your phone to the iMessage account signed in on this Mac (same Apple ID). You should see a reply.

   ![reply](https://img.alicdn.com/imgextra/i2/O1CN01btWaV21CtFmbnxFYw_!!6000000000138-2-tps-1206-2622.png)

---

## Discord

### Get a Bot Token

1. Open the [Discord Developer Portal](https://discord.com/developers/applications)

![Discord Developer Portal](https://img.alicdn.com/imgextra/i2/O1CN01oV68yZ1sb7y3nGoQN_!!6000000005784-2-tps-4066-2118.png)

2. Create a new application (or select an existing one)

![Create application](https://img.alicdn.com/imgextra/i2/O1CN01eA9lA71kMukVCWR4y_!!6000000004670-2-tps-3726-1943.png)

3. Go to **Bot** in the left sidebar, create a bot, and copy the **Token**

![Token](https://img.alicdn.com/imgextra/i1/O1CN01iuPiUe1lJzqEiIu23_!!6000000004799-2-tps-2814-1462.png)

4. Scroll down, enable **Message Content Intent** and **Send Messages** for the bot, then save

![Permissions](https://img.alicdn.com/imgextra/i4/O1CN01EXH4w51FSdbxYKLG9_!!6000000000486-2-tps-4066-2118.png)

5. In **OAuth2 → URL Generator**, enable `bot`, grant **Send Messages**, and generate the invite link

![Bot](https://img.alicdn.com/imgextra/i2/O1CN01B2oXx71KVS7kjKSEm_!!6000000001169-2-tps-4066-2118.png)

![Send Messages](https://img.alicdn.com/imgextra/i3/O1CN01DlU9oi1QYYVBPoUIA_!!6000000001988-2-tps-4066-2118.png)

![Link](https://img.alicdn.com/imgextra/i2/O1CN01ljhh1j1OZLxb2mAkO_!!6000000001719-2-tps-4066-2118.png)

6. Open the link in your browser; it will redirect to Discord. Add the bot to your server

![Server](https://img.alicdn.com/imgextra/i2/O1CN01QlcQPI1KzgGTWtZnb_!!6000000001235-2-tps-2798-1822.png)

![Server](https://img.alicdn.com/imgextra/i4/O1CN01ihF0dW1xC0Jw8uwm6_!!6000000006406-2-tps-2798-1822.png)

7. You can see the bot is now in your server

![Bot in server](https://img.alicdn.com/imgextra/i4/O1CN01IDPCke1S1EvIIqtX9_!!6000000002186-2-tps-2798-1822.png)

### Configure the Bot

You can configure via the Console UI or by editing the agent workspace `agent.json`.

**Method 1:** Configure in the Console

Go to **Control → Channels**, click **Discord**, and enter the **Bot Token** you obtained.

![console](https://img.alicdn.com/imgextra/i1/O1CN01VjFNXn1oUTlVH6Bmt_!!6000000005228-2-tps-3822-2070.png)

**Method 2:** Edit agent workspace `agent.json`

Find `channels.discord` in your agent's `agent.json` (e.g., `~/.qwenpaw/workspaces/default/agent.json`) and fill in the fields, for example:

```json
"discord": {
  "enabled": true,
  "bot_prefix": "[BOT]",
  "bot_token": "your Bot Token",
  "http_proxy": "",
  "http_proxy_auth": ""
}
```

**Discord-specific fields:**

| Field             | Type   | Default         | Description                                                                            |
| ----------------- | ------ | --------------- | -------------------------------------------------------------------------------------- |
| `bot_token`       | string | `""` (required) | Discord bot token                                                                      |
| `http_proxy`      | string | `""`            | HTTP proxy URL (useful in China)                                                       |
| `http_proxy_auth` | string | `""`            | Proxy authentication string (format: `username:password`, leave empty if not required) |

> **Tip:** Accessing the Discord API from China may require a proxy.

---

## QQ

### Get QQ bot credentials

1. Open the [QQ Developer Platform](https://q.qq.com/)

![Platform](https://img.alicdn.com/imgextra/i4/O1CN01OjCvUf1oT6ZDWpEk5_!!6000000005225-2-tps-4082-2126.png)

2. Create a **bot application** and click to open the edit page

![bot](https://img.alicdn.com/imgextra/i3/O1CN01xBbXWa1pSTdioYFdg_!!6000000005359-2-tps-4082-2126.png)

![confirm](https://img.alicdn.com/imgextra/i3/O1CN01zt7w0V1Ij4fjcm5MS_!!6000000000928-2-tps-4082-2126.png)

3. Go to **Callback config** → enable **C2C message events** under **Direct message events**, and **At-event for group messages** under **Group events**, then confirm

![c2c](https://img.alicdn.com/imgextra/i4/O1CN01HDSoX91iOAbTVULZf_!!6000000004402-2-tps-4082-2126.png)

![at](https://img.alicdn.com/imgextra/i4/O1CN01UJn1AK1UKatKkjMv4_!!6000000002499-2-tps-4082-2126.png)

4. In **Sandbox config** → **Message list**, click **Add member** and add **yourself**

![1](https://img.alicdn.com/imgextra/i4/O1CN01BSdkXl1ckG0dC7vH9_!!6000000003638-2-tps-4082-2126.png)

![1](https://img.alicdn.com/imgextra/i4/O1CN01LGYUMe1la1hmtcuyY_!!6000000004834-2-tps-4082-2126.png)

5. In **Developer settings**, get **AppID** and **AppSecret** (ClientSecret) and fill them into config (see below). Add your server’s **IP to the whitelist** — only whitelisted IPs can call the Open API outside sandbox.

   > **Tip:** If you are using ModelScope Creative Space to deploy QwenPaw, the IP whitelist for QQ channel should be: `47.92.200.108`

![1](https://img.alicdn.com/imgextra/i4/O1CN012UQWI21cnvBAUcz54_!!6000000003646-2-tps-4082-2126.png)

6. In sandbox config, scan the QR code with QQ to add the bot to your message list

![1](https://img.alicdn.com/imgextra/i3/O1CN01r1OvPy1kcwc30w32K_!!6000000004705-2-tps-4082-2126.png)

### Fill agent.json

In your agent's `agent.json` (e.g., `~/.qwenpaw/workspaces/default/agent.json`), find `channels.qq` and set `app_id` and `client_secret` to the values above:

```json
"qq": {
  "enabled": true,
  "bot_prefix": "[BOT]",
  "app_id": "your AppID",
  "client_secret": "your AppSecret"
}
```

**QQ-specific fields:**

| Field                    | Type   | Default         | Description                                                              |
| ------------------------ | ------ | --------------- | ------------------------------------------------------------------------ |
| `app_id`                 | string | `""` (required) | QQ bot App ID                                                            |
| `client_secret`          | string | `""` (required) | QQ bot Client Secret (AppSecret)                                         |
| `markdown_enabled`       | bool   | `false`         | Whether to enable Markdown messages (requires QQ platform authorization) |
| `max_reconnect_attempts` | int    | `-1`            | WebSocket max reconnect attempts (`-1` = unlimited)                      |

> **Note:** Fill in **AppID** and **AppSecret** as two separate fields; do not concatenate them into a single token.

You can also fill them in the Console UI.

![console](https://img.alicdn.com/imgextra/i1/O1CN01QPxQ9S1sxZNvpV4ZW_!!6000000005833-2-tps-3822-2070.png)

---

## OneBot v11 (NapCat / QQ full protocol)

The **OneBot** channel connects QwenPaw to [NapCat](https://github.com/NapNeko/NapCatQQ), [go-cqhttp](https://github.com/Mrs4s/go-cqhttp), [Lagrange](https://github.com/LagrangeDev/Lagrange.Core), or any other [OneBot v11](https://github.com/botuniverse/onebot-11) compatible implementation via **reverse WebSocket**.

Unlike the built-in QQ channel (which uses the official QQ Bot API with limited features), OneBot v11 provides **full QQ protocol** support: personal accounts, group messages without @mention, rich media, and more.

### How it works

QwenPaw starts a WebSocket server; the OneBot implementation (e.g. NapCat) connects to it as a client:

```
NapCat  ──reverse WS──▶  QwenPaw (:6199/ws)
```

### Setup NapCat

1. Run NapCat via Docker:

   ```bash
   docker run -d \
     --name napcat \
     -e ACCOUNT=<your_qq_number> \
     -p 6099:6099 \
     mlikiowa/napcat-docker:latest
   ```

2. Open NapCat WebUI at `http://localhost:6099`, scan the QR code with QQ to log in.

3. Go to **Network Config** → **New** → **WebSocket Client** (reverse WS):
   - URL: `ws://<qwenpaw_host>:6199/ws`
   - Access Token: same as `access_token` in QwenPaw config (optional)

### Fill agent.json

```json
"onebot": {
  "enabled": true,
  "ws_host": "0.0.0.0",
  "ws_port": 6199,
  "access_token": "",
  "share_session_in_group": false
}
```

**OneBot-specific fields:**

| Field                    | Type   | Default   | Description                                                                                              |
| ------------------------ | ------ | --------- | -------------------------------------------------------------------------------------------------------- |
| `ws_host`                | string | `0.0.0.0` | WebSocket server listen address                                                                          |
| `ws_port`                | int    | `6199`    | WebSocket server listen port                                                                             |
| `access_token`           | string | `""`      | Optional token for authentication (must match NapCat config)                                             |
| `share_session_in_group` | bool   | `false`   | If `true`, all members in a group share one session; if `false`, each member gets an independent session |

> **Docker Compose tip:** When running QwenPaw and NapCat in Docker Compose, set the NapCat reverse WS URL to `ws://qwenpaw:6199/ws` (using the service name).

**Multimodal support:**

| Type  | Receive | Send |
| ----- | ------- | ---- |
| Text  | ✓       | ✓    |
| Image | ✓       | ✓    |
| Audio | 🚧      | ✓    |
| Video | 🚧      | ✓    |
| File  | ✓       | ✓    |

> **Note:** Audio and video are received at the channel level, but require QwenPaw's transcription provider (`transcription_provider_type`) to be configured for the LLM to process them. Without transcription, voice messages are shown as placeholders.

---

## WeCom (WeChat Work)

### Create a new enterprise

Individual users can visit the [WeCom official website](https://work.weixin.qq.com) to register an account, create a new enterprise, and become an enterprise administrator.

![Create enterprise](https://img.alicdn.com/imgextra/i2/O1CN01Xg8B3i1EQWAKt5xj0_!!6000000000346-2-tps-2938-1588.png)

Fill in the enterprise information and administrator information, and bind your WeChat account.

![New account](https://img.alicdn.com/imgextra/i4/O1CN01uRF1Mv1TX87bOQ045_!!6000000002391-2-tps-1538-905.png)

Once registered, you can log in to WeCom and start using it.

If you already have a WeCom account or are a regular employee of an enterprise, you can directly create an API-mode robot in your current enterprise.

### Create a bot

In the Workplace, click Smart Robot → Create Robot, select API Mode → Configure via Long Connection.

![Create robot 1](https://img.alicdn.com/imgextra/i3/O1CN01lcA2rX1fm2P19SLcB_!!6000000004048-2-tps-1440-814.png)

![Create robot 2](https://img.alicdn.com/imgextra/i1/O1CN014R3a0f1mnb3qbycMV_!!6000000004999-2-tps-1440-814.png)

![Create robot 3](https://img.alicdn.com/imgextra/i4/O1CN01kZDNVk1ugHf73ybs2_!!6000000006066-2-tps-2938-1594.png)

Obtain the `Bot ID` and `Secret`.

![Create robot 4](https://img.alicdn.com/imgextra/i1/O1CN01Znm7aQ1Tfpe5Ha9WL_!!6000000002410-2-tps-1482-992.png)

### Bind the bot

You can bind the bot by filling in the Bot ID and Secret in the Console or `agent.json`.

**Method 1:** Fill in the Console

![console](https://img.alicdn.com/imgextra/i1/O1CN01A4916J1RB1mXpeVqK_!!6000000002072-2-tps-3822-2070.png)

**Method 2:** Fill in `agent.json` (e.g., `~/.qwenpaw/workspaces/default/agent.json`)

Find `wecom` and fill in the corresponding information, for example:

```json
"wecom": {
  "enabled": true,
  "bot_prefix": "[BOT]",
  "dm_policy": "open",
  "group_policy": "open",
  "bot_id": "your bot_id",
  "secret": "your secret",
  "media_dir": "~/.qwenpaw/media",
  "max_reconnect_attempts": -1
}
```

**WeCom-specific fields:**

| Field                    | Type   | Default            | Description                                          |
| ------------------------ | ------ | ------------------ | ---------------------------------------------------- |
| `bot_id`                 | string | `""` (required)    | WeCom bot ID                                         |
| `secret`                 | string | `""` (required)    | WeCom bot secret                                     |
| `media_dir`              | string | `~/.qwenpaw/media` | Media files (images, files, etc.) download directory |
| `max_reconnect_attempts` | int    | `-1`               | WebSocket max reconnect attempts (`-1` = unlimited)  |

### Start chatting with the bot in WeCom

![Start using](https://img.alicdn.com/imgextra/i3/O1CN01ZsmpYr1tq4ViIbO80_!!6000000005952-2-tps-1308-1130.png)

---

## WeChat Personal (iLink)

The WeChat iLink Bot channel lets you run an AI bot via a **personal WeChat account** — no enterprise account required — using the official [iLink Bot HTTP API](https://weixin.qq.com/cgi-bin/readtemplate?t=ilink/chatbot) protocol.

> **Note**: WeChat personal bots (iLink protocol) are currently in limited beta. You need to apply for access before using this feature.

### How it works

- **Authentication**: On first use, scan a QR code to authorize. The token is automatically persisted to a local file (default `~/.qwenpaw/weixin_bot_token`), so you won't need to scan again on subsequent starts.
- **Receiving messages**: Uses HTTP long-polling (`getupdates`) to continuously fetch new messages. Supports text, images, voice (ASR transcription), files, and videos.
- **Sending messages**: Replies via `sendmessage`. Currently only text is supported (iLink API limitation).

### QR code login (recommended via Console)

1. Open the QwenPaw Web Console and go to **Settings → Channels → WeChat Personal (iLink)**.
2. Click **Get Login QR Code** and wait for the QR code to appear.
3. Scan the QR code with your WeChat mobile app and confirm authorization.
4. Once confirmed, the Bot Token is automatically filled in the form — click **Save**.

### Configure via config file

You can also configure directly in the agent workspace `agent.json` (e.g., `~/.qwenpaw/workspaces/default/agent.json`):

```json
"weixin": {
  "enabled": true,
  "bot_token": "your_bot_token",
  "bot_token_file": "~/.qwenpaw/weixin_bot_token",
  "base_url": "",
  "media_dir": "~/.qwenpaw/media",
  "dm_policy": "open",
  "group_policy": "open"
}
```

**WeChat Personal-specific fields:**

| Field            | Type   | Default                       | Description                                                                           |
| ---------------- | ------ | ----------------------------- | ------------------------------------------------------------------------------------- |
| `bot_token`      | string | `""`                          | Bearer token obtained after QR code login; leave empty to trigger QR login on startup |
| `bot_token_file` | string | `~/.qwenpaw/weixin_bot_token` | Path to persist the token for future runs                                             |
| `base_url`       | string | official default              | iLink API base URL; leave empty to use the official default                           |
| `media_dir`      | string | `~/.qwenpaw/media`            | Directory to save received images and files                                           |

### Configure via environment variables

```bash
WEIXIN_CHANNEL_ENABLED=1
WEIXIN_BOT_TOKEN=your_bot_token
WEIXIN_BOT_TOKEN_FILE=~/.qwenpaw/weixin_bot_token
WEIXIN_MEDIA_DIR=~/.qwenpaw/media
WEIXIN_DM_POLICY=open
WEIXIN_GROUP_POLICY=open
```

---

## Telegram

### Get Telegram bot credentials

1. Open Telegram and search for `@BotFather` to add a Bot (make sure it is the official @BotFather with a blue verified badge).
2. Open the chat with @BotFather and follow the instructions to create a new bot

   ![Create bot](https://img.alicdn.com/imgextra/i1/O1CN01wVVmbY1qkcxBn8Oc0_!!6000000005534-0-tps-817-1279.jpg)

3. Create the bot name in the dialog and copy the bot_token

   ![Copy token](https://img.alicdn.com/imgextra/i3/O1CN01KUMvBW1UnuF599tNX_!!6000000002563-0-tps-1209-1237.jpg)

### Configure the Bot

You can configure via the Console UI or by editing the agent workspace `agent.json`.

**Method 1:** Configure in the Console

Go to **Control → Channels**, click **Telegram**, and enter the **Bot Token** you obtained.

![console](https://img.alicdn.com/imgextra/i2/O1CN01Ue1bBr1DxCp8WkyzP_!!6000000000282-2-tps-3822-2070.png)

**Method 2:** Edit agent workspace `agent.json`

Find `channels.telegram` in your agent's `agent.json` (e.g., `~/.qwenpaw/workspaces/default/agent.json`) and fill in the fields, for example:

```json
"telegram": {
    "enabled": true,
    "bot_prefix": "[BOT]",
    "bot_token": "your Bot Token",
    "http_proxy": "",
    "http_proxy_auth": ""
}
```

**Telegram-specific fields:**

| Field             | Type   | Default         | Description                                                                     |
| ----------------- | ------ | --------------- | ------------------------------------------------------------------------------- |
| `bot_token`       | string | `""` (required) | Telegram Bot Token                                                              |
| `http_proxy`      | string | `""`            | Proxy address (e.g., `http://127.0.0.1:7890`)                                   |
| `http_proxy_auth` | string | `""`            | Proxy authentication (format: `username:password`, leave empty if not required) |

> **Tip:** Accessing the Telegram API from China may require a proxy.

### Notes

To control who can interact with the bot, use the common access control fields (`dm_policy`, `group_policy`, `allow_from`, `deny_message`, `require_mention`) described at the top of this page. It is still recommended to avoid exposing your bot username publicly.

It is recommended to configure the following in `@BotFather`:

```
/setprivacy -> ENABLED    # Restrict bot reply permissions
/setjoingroups -> DISABLED # Block group invitations
```

---

## Mattermost

The Mattermost channel uses WebSockets for real-time monitoring and REST APIs for replies. It supports both direct messages and group chats, using **Threads** to isolate conversation contexts in channels.

### Get credentials

1. Create a **Bot Account** in Mattermost (System Console → Integrations → Bot Accounts).
2. Grant necessary permissions (e.g., `Post all`) and obtain the **Access Token**.
3. Configure the **URL** and **Token** in the Console or `config.json`.

### Core Config

**Mattermost-specific fields:**

| Field                           | Type   | Default         | Description                                                               |
| ------------------------------- | ------ | --------------- | ------------------------------------------------------------------------- |
| `url`                           | string | `""` (required) | Full URL of your Mattermost instance                                      |
| `bot_token`                     | string | `""` (required) | Bot Access Token                                                          |
| `show_typing`                   | bool   | `true`          | Whether to show the "typing..." indicator                                 |
| `thread_follow_without_mention` | bool   | `false`         | Whether to respond without @mention in threads the bot has already joined |

> **Note**: The `session_id` for Mattermost is fixed as `mattermost_dm:{mm_channel_id}` for DMs and isolated by Thread ID for group chats. Recent history is automatically fetched as context supplement only upon the first trigger of a session.

---

## MQTT

### About

Currently, only text and JSON format messages are supported.

JSON message format

```
{
  "text": "...",
  "redirect_client_id": "..."
}
```

### Basic Configuration

| Description     | Field           | Required field | Example                 |
| --------------- | --------------- | -------------- | ----------------------- |
| MQTT Host       | host            | Y              | 127.0.0.1               |
| MQTT Port       | port            | Y              | 1883                    |
| Transport       | transport       | Y              | tcp                     |
| Clean Session   | clean_session   | Y              | true                    |
| QoS             | qos             | Y              | 2                       |
| MQTT Username   | username        | N              |                         |
| MQTT Password   | password        | N              |                         |
| Subscribe Topic | subscribe_topic | Y              | server/+/up             |
| Publish Topic   | publish_topic   | Y              | client/{client_id}/down |
| TLS Enabled     | tls_enabled     | N              | false                   |
| TLS CA Certs    | tls_ca_certs    | N              | /tsl/ca.pem             |
| TLS Certfile    | tls_certfile    | N              | /tsl/client.pem         |
| TLS Keyfile     | tls_keyfile     | N              | /tsl/client.key         |

### Topic

1. Simple subscription and push

   | subscribe_topic | publish_topic |
   | --------------- | ------------- |
   | server          | client        |

2. Fuzzy match subscription and automatic push

   Subscribe to the wildcard topic `/server/+/up`. Messages will be automatically pushed to the corresponding topic based on the client's `client_id`. For example, after a client pushes a message to `/server/client_a/up`, QwenPaw will push the message to `/client/client_b/down` after processing.

   | subscribe_topic | publish_topic           |
   | --------------- | ----------------------- |
   | server/+/up     | client/{client_id}/down |

3. Redirected topic push

   The message sent is in JSON format. The subscription topic is `server/client_a/up`, and the push topic is `client/client_a/down`.

   ```json
   {
     "text": "Tell me a joke, return the result in plain text",
     "redirect_client_id": "client_b"
   }
   ```

   Messages will be pushed to `client/client_b/down` based on the `redirect_client_id` attribute, enabling cross-topic push. In IoT scenarios, with QwenPaw as the core, autonomous message pushing between multiple devices can be achieved according to individual requirements.

---

## Matrix

The Matrix channel connects QwenPaw to any Matrix homeserver using the [matrix-nio](https://github.com/poljar/matrix-nio) library. It supports text messaging in both direct messages and group rooms.

### Create a Matrix bot account and get an access token

1. Create a bot account on any Matrix homeserver (e.g. [matrix.org](https://matrix.org) — register at [app.element.io](https://app.element.io/#/register)).

2. Get the bot's **access token**. The easiest way is via Element:

   - Log in as the bot account at [app.element.io](https://app.element.io)
   - Go to **Settings → Help & About → Advanced → Access Token**
   - Copy the token (it starts with `syt_...`)

   Alternatively, use the Matrix Client-Server API directly:

   ```bash
   curl -X POST "https://matrix.org/_matrix/client/v3/login" \
     -H "Content-Type: application/json" \
     -d '{"type":"m.login.password","user":"@yourbot:matrix.org","password":"yourpassword"}'
   ```

   The response includes `access_token`.

3. Note your bot's **User ID** (format: `@username:homeserver`, e.g. `@mybot:matrix.org`) and the **Homeserver URL** (e.g. `https://matrix.org`).

### Configure the channel

**Method 1:** Configure in the Console

Go to **Control → Channels**, click **Matrix**, enable it, and fill in:

- **Homeserver URL** — e.g. `https://matrix.org`
- **User ID** — e.g. `@mybot:matrix.org`
- **Access Token** — the token you copied above (shown as a password field)

**Method 2:** Edit agent workspace `agent.json`

Find `channels.matrix` in your agent's `agent.json` (e.g., `~/.qwenpaw/workspaces/default/agent.json`):

```json
"matrix": {
  "enabled": true,
  "bot_prefix": "[BOT]",
  "homeserver": "https://matrix.org",
  "user_id": "@mybot:matrix.org",
  "access_token": "syt_..."
}
```

**Matrix-specific fields:**

| Field          | Type   | Default         | Description                                        |
| -------------- | ------ | --------------- | -------------------------------------------------- |
| `homeserver`   | string | `""` (required) | Matrix server address (e.g., `https://matrix.org`) |
| `user_id`      | string | `""` (required) | Bot User ID (e.g., `@mybot:matrix.org`)            |
| `access_token` | string | `""` (required) | Bot access token (starts with `syt_`)              |

Save the file; the channel will reload automatically if QwenPaw is already running.

### Chat with the bot

Invite the bot to a room or send it a direct message from any Matrix client (e.g. Element). The bot listens for messages in all rooms it has joined.

### Notes

- Matrix supports multimodal messages (text, images, videos, audio, and files). Attachments are received via `mxc://` media URLs and uploaded to the homeserver, then sent as native Matrix media messages (`m.image`, `m.video`, `m.audio`, `m.file`).
- Only rooms the bot has already joined are monitored. Invite the bot to a room before sending messages.
- For self-hosted homeservers, set `homeserver` to your server's base URL (e.g. `https://matrix.example.com`).

---

## XiaoYi

The XiaoYi channel connects QwenPaw via **A2A (Agent-to-Agent) protocol** over WebSocket to Huawei's AI assistant platform.

### Get credentials

1. Create an agent in the XiaoYi Open Platform.
2. Obtain **AK** (Access Key), **SK** (Secret Key), and **Agent ID**.

### Core Config

**XiaoYi-specific fields:**

| Field      | Type   | Default                                          | Description             |
| ---------- | ------ | ------------------------------------------------ | ----------------------- |
| `ak`       | string | `""` (required)                                  | Access Key              |
| `sk`       | string | `""` (required)                                  | Secret Key              |
| `agent_id` | string | `""` (required)                                  | Agent unique identifier |
| `ws_url`   | string | `wss://hag.cloud.huawei.com/openclaw/v1/ws/link` | WebSocket URL           |

### Supported File Types

**Images**: JPEG, JPG, PNG, BMP, WEBP

**Files**: PDF, DOC, DOCX, PPT, PPTX, XLS, XLSX, TXT

> Note: Video and audio files are not supported by the XiaoYi platform.

---

## Voice

The Voice channel enables phone call interactions with QwenPaw via Twilio ConversationRelay, supporting Speech-to-Text (STT) and Text-to-Speech (TTS) for voice-based conversations.

### Prerequisites

1. **Twilio Account**: Register at [Twilio](https://www.twilio.com/) and obtain credentials
2. **Cloudflare Tunnel** (or similar): Expose your local QwenPaw service to the public internet for Twilio webhook callbacks

### Create Twilio account and get credentials

1. Visit the [Twilio Console](https://console.twilio.com/) and register an account
2. From the Dashboard, obtain:
   - **Account SID** (account identifier)
   - **Auth Token** (authentication token)
3. Purchase a phone number:
   - Go to **Phone Numbers → Buy a Number**
   - Select a number that supports voice calls
   - Note the **Phone Number** (e.g., `+1234567890`) and **Phone Number SID**

### Configure Cloudflare Tunnel

Twilio needs to reach QwenPaw's webhook endpoint via the public internet, so you need to expose your local service.

1. Install Cloudflare Tunnel client:

```bash
# macOS
brew install cloudflare/cloudflare/cloudflared

# Linux
wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
sudo mv cloudflared-linux-amd64 /usr/local/bin/cloudflared
sudo chmod +x /usr/local/bin/cloudflared
```

2. Start the tunnel to expose local port 8088:

```bash
cloudflared tunnel --url http://localhost:8088
```

3. The terminal will output a public URL, e.g., `https://abc-def-ghi.trycloudflare.com`

### Configure Voice channel

**Method 1:** Configure in the Console

Go to **Control → Channels**, click **Voice**, enable it, and fill in:

- **Twilio Account SID**: From Twilio Dashboard
- **Twilio Auth Token**: From Twilio Dashboard
- **Phone Number**: Your purchased phone number (e.g., `+1234567890`)
- **Phone Number SID**: The phone number's SID

Advanced options:

- **TTS Provider**: Text-to-speech provider (default `google`)
- **TTS Voice**: Voice model (default `en-US-Journey-D`)
- **STT Provider**: Speech-to-text provider (default `deepgram`)
- **Language**: Language code (default `en-US`)
- **Welcome Greeting**: Initial greeting when the call connects

**Method 2:** Edit `agent.json` manually

```json
{
  "channels": {
    "voice": {
      "enabled": true,
      "twilio_account_sid": "ACxxxxxxxxxxxxxxxxxxxxxxxxxx",
      "twilio_auth_token": "your_auth_token",
      "phone_number": "+1234567890",
      "phone_number_sid": "PNxxxxxxxxxxxxxxxxxxxxxxxxxx",
      "tts_provider": "google",
      "tts_voice": "en-US-Journey-D",
      "stt_provider": "deepgram",
      "language": "en-US",
      "welcome_greeting": "Hi! This is QwenPaw. How can I help you?"
    }
  }
}
```

### Configure Twilio Webhook

Configure your phone number's webhook in the Twilio Console:

1. Go to **Phone Numbers → Manage → Active Numbers**
2. Click your phone number
3. In the **Voice Configuration** section:
   - **A Call Comes In**: Select **Webhook**
   - **URL**: Enter `https://your-cloudflare-url.trycloudflare.com/api/voice/callback`
   - **HTTP Method**: Select **POST**
4. Save the configuration

### Usage

After configuration, simply call your Twilio phone number to have a voice conversation with QwenPaw:

1. Dial the phone number
2. After hearing the welcome greeting, start speaking
3. QwenPaw converts speech to text and processes it through the Agent
4. The Agent's response is converted to speech and played back to you

**Voice channel-specific fields:**

| Field                | Type   | Default                                      | Description                                  |
| -------------------- | ------ | -------------------------------------------- | -------------------------------------------- |
| `twilio_account_sid` | string | `""` (required)                              | Twilio Account SID                           |
| `twilio_auth_token`  | string | `""` (required)                              | Twilio Auth Token                            |
| `phone_number`       | string | `""` (required)                              | Purchased phone number (e.g., `+1234567890`) |
| `phone_number_sid`   | string | `""` (required)                              | Phone number SID                             |
| `tts_provider`       | string | `"google"`                                   | Text-to-speech provider                      |
| `tts_voice`          | string | `"en-US-Journey-D"`                          | TTS voice model                              |
| `stt_provider`       | string | `"deepgram"`                                 | Speech-to-text provider                      |
| `language`           | string | `"en-US"`                                    | Language code                                |
| `welcome_greeting`   | string | `"Hi! This is QwenPaw. How can I help you?"` | Welcome message when call connects           |

> **Note**: The Voice channel requires a continuous network connection and a running tunnel solution. For production use, consider stable tunneling options (like Cloudflare Tunnel, ngrok paid plans, etc.).

---

## SIP

The SIP channel enables voice conversations with QwenPaw via standard SIP phones and softphones (e.g., Linphone, MicroSIP, IP desk phones). It works entirely on your local network or private infrastructure — no cloud account or public URL required.

Two backend modes are available:

| Mode        | Best for                          | External infra needed?            |
| ----------- | --------------------------------- | --------------------------------- |
| **Dev**     | Local development, PoC, debugging | None — built-in SIP registrar     |
| **LiveKit** | Production, high quality          | LiveKit Server (or LiveKit Cloud) |

### Quick try: Dev mode (3 minutes, zero external infra)

The fastest way to try SIP. QwenPaw starts a built-in SIP registrar automatically — no Asterisk, FreeSWITCH, or any external server needed.

1. Install:

```bash
pip install "qwenpaw[sip]"
```

2. Start QwenPaw and configure in Console:

```bash
qwenpaw init --defaults
qwenpaw app
```

Open **http://127.0.0.1:8088/** → **Settings → Models**: configure a model provider and API key. Then go to **Control → Channels → SIP**: enable it, fill in your DashScope API Key, and click **Save**. All other fields can be left at their defaults — when `sip_server` is empty, QwenPaw automatically starts a built-in registrar, uses `aliyun` for STT/TTS, and picks a default voice.

QwenPaw will restart the SIP channel automatically. You'll see in the terminal:

```
[SIP] Built-in SIP registrar started on 0.0.0.0:5060
[SIP] Quickstart: register your softphone to <Your-IP>:5060
[SIP] Dial 'sip:agent@<Your-IP>:5060' to talk with QwenPaw!
```

3. Open [Linphone](https://www.linphone.org/linphone) (or any SIP softphone) and configure:

   - Go to **Preferences → SIP Accounts → Add**
   - Username: any name (e.g., `caller`)
   - SIP Domain: `127.0.0.1` (use IP address, **not** `localhost`, to avoid IPv6 issues)
   - Transport: **UDP**
   - No password needed — the built-in registrar accepts all registrations
   - Dial: `sip:agent@127.0.0.1:5060`

   You should hear the welcome greeting, then speak — QwenPaw will reply!

   **Alternative: pjsua (CLI, uses system microphone/speaker)**

   ```bash
   pjsua --local-port=5062 \
     --bound-addr=127.0.0.1 \
     --no-tcp \
     --id='sip:caller@127.0.0.1:5062' \
     --registrar='sip:127.0.0.1:5060' \
     --realm='*' --username=caller --password=pass
   ```

   Once registered, press `m` to make a call, enter `sip:agent@127.0.0.1:5060`, and talk through your microphone. Press `h` to hang up.

> **Note**: The built-in registrar is for quick testing only. For production use, see [Production deployment](#production-deployment) below.

### Quick try: LiveKit mode via browser (3 minutes, no SIP phone needed)

You can test the full LiveKit audio pipeline directly from your browser using WebRTC — no SIP Trunk, Docker, or Redis required.

1. Sign up for [LiveKit Cloud](https://cloud.livekit.io/) (free tier available) and create a project. Note your project URL (from **Settings → Project**), and API Key / API Secret (from **Settings → API keys**).

2. Install, start QwenPaw, and configure in Console:

```bash
pip install "qwenpaw[sip,sip-livekit]"
qwenpaw init --defaults
qwenpaw app
```

Open **http://127.0.0.1:8088/** → **Settings → Models**: configure a model provider and API key. Then go to **Control → Channels → SIP**: enable it, set SIP Mode to **Production (LiveKit)**, and fill in these 4 fields:

- **LiveKit URL** (e.g., `wss://<your-project>.livekit.cloud`)
- **LiveKit API Key**
- **LiveKit API Secret**
- **DashScope API Key**

All other fields can be left empty. Click **Save**.

You'll see in the terminal: `Connected to room: sip-inbound, waiting...`

3. Generate a token and join via [LiveKit Meet](https://meet.livekit.io/):

   ```bash
   # Install LiveKit CLI (one-time)
   brew install livekit-cli

   # Generate a token
   lk token create \
     --api-key <your-api-key> \
     --api-secret <your-api-secret> \
     --join --room sip-inbound \
     --identity test-user
   ```

   - Open [meet.livekit.io](https://meet.livekit.io/) → click **"Custom"** at the bottom
   - Enter your LiveKit Cloud URL (e.g., `wss://<your-project>.livekit.cloud`)
   - Paste the generated token and click **Connect**
   - Allow microphone access, then speak — QwenPaw responds!

> **Note**: This browser-based test exercises the exact same audio pipeline (streaming STT, 24kHz TTS, barge-in) as a real SIP phone call. It's a fully valid test of LiveKit mode.

### Production deployment

For production use with real phone numbers and carrier-grade reliability, use one of these setups:

**Dev mode with external SIP server:**

Use Asterisk, FreeSWITCH, or any SIP PBX as the registrar. Set `sip_server` to your PBX address. QwenPaw registers as a SIP extension and receives calls routed by the PBX.

**LiveKit mode with SIP Trunk:**

For PSTN connectivity (real phone numbers), deploy LiveKit Server + LiveKit SIP with a SIP Trunk provider (e.g., Twilio, Telnyx, Vonage). See [LiveKit SIP docs](https://docs.livekit.io/sip/) for trunk and dispatch rule setup.

| Production setup                  | Supports PSTN?   | Scalability | Complexity |
| --------------------------------- | ---------------- | ----------- | ---------- |
| Dev + Asterisk/FreeSWITCH         | Yes (with trunk) | Single call | Low        |
| LiveKit + Twilio/Telnyx SIP Trunk | Yes              | High        | Medium     |
| LiveKit + self-hosted SIP         | Depends          | High        | High       |

### Dev mode configuration

Dev mode uses `pyVoIP` — a pure-Python SIP library.

**Method 1:** Configure in the Console

Go to **Control → Channels**, click **SIP**, select **Dev (pyVoIP)** mode. Leave `sip_server` empty to use the built-in registrar, or fill in your external SIP server address. Click **Save**.

**Method 2:** Edit agent workspace `agent.json`

```json
{
  "channels": {
    "sip": {
      "enabled": true,
      "sip_mode": "dev",
      "sip_server": "",
      "stt_provider": "aliyun",
      "tts_provider": "aliyun",
      "tts_voice": "longxiaochun",
      "language": "zh-CN",
      "welcome_greeting": "你好，我是QwenPaw"
    }
  }
}
```

When `sip_server` is empty, QwenPaw starts a built-in SIP registrar on port 5060 and the agent registers to it automatically. When `sip_server` is set (e.g., `"192.168.1.100:5060"`), QwenPaw registers to that external server instead.

### LiveKit mode configuration

Production mode delegates SIP/RTP to LiveKit SIP Server — a Go binary that handles NAT traversal, jitter buffering, and codec negotiation. QwenPaw joins LiveKit rooms as an AI participant.

1. Install extras:

```bash
pip install "qwenpaw[sip,sip-livekit]"
```

2. Configure the SIP channel in Console or `agent.json`:

```json
{
  "channels": {
    "sip": {
      "enabled": true,
      "sip_mode": "livekit",
      "livekit_url": "wss://<your-project>.livekit.cloud",
      "livekit_api_key": "your-api-key",
      "livekit_api_secret": "your-api-secret",
      "stt_provider": "aliyun",
      "tts_provider": "aliyun",
      "tts_voice": "longxiaochun",
      "language": "zh-CN",
      "welcome_greeting": "你好，我是QwenPaw"
    }
  }
}
```

> **`livekit_url`**: Use `wss://<project>.livekit.cloud` for LiveKit Cloud, or `ws://<host>:<port>` for a self-hosted LiveKit Server.

3. Start QwenPaw. For SIP phone calls, also set up LiveKit infrastructure with a SIP Trunk and Dispatch Rule (see [LiveKit SIP docs](https://docs.livekit.io/sip/)). For browser-based testing, see the [Quick try](#quick-try-livekit-mode-via-browser-3-minutes-no-sip-phone-needed) section above.

### Usage

After configuration, start a call from your SIP phone or browser:

1. The call connects and you hear the welcome greeting
2. Start speaking — QwenPaw converts speech to text via streaming STT
3. The Agent processes your message and generates a reply
4. The reply is converted to speech via TTS and played back to you
5. Continue the conversation naturally — multi-turn is fully supported
6. Barge-in supported: start speaking while the agent is talking to interrupt

### SIP channel fields

| Field                | Type   | Default                                      | Description                                                             |
| -------------------- | ------ | -------------------------------------------- | ----------------------------------------------------------------------- |
| `sip_mode`           | string | `"dev"`                                      | Backend mode: `"dev"` (pyVoIP) or `"livekit"`                           |
| `sip_server`         | string | `""`                                         | SIP registrar address. Leave empty to use built-in registrar (dev mode) |
| `sip_username`       | string | `""`                                         | SIP account username (default: `agent` with built-in registrar)         |
| `sip_password`       | string | `""`                                         | SIP account password                                                    |
| `sip_host`           | string | `"0.0.0.0"`                                  | Local bind address                                                      |
| `sip_port`           | int    | `5061`                                       | Local SIP port (agent side)                                             |
| `sip_transport`      | string | `"UDP"`                                      | SIP transport: `UDP`, `TCP`, or `TLS`                                   |
| `rtp_port_low`       | int    | `10000`                                      | RTP port range start (dev mode only)                                    |
| `rtp_port_high`      | int    | `20000`                                      | RTP port range end (dev mode only)                                      |
| `livekit_url`        | string | `""`                                         | LiveKit Server WebSocket URL (production mode)                          |
| `livekit_api_key`    | string | `""`                                         | LiveKit API key (production mode)                                       |
| `livekit_api_secret` | string | `""`                                         | LiveKit API secret (production mode)                                    |
| `tts_provider`       | string | `"aliyun"`                                   | TTS provider (currently supports `aliyun`)                              |
| `tts_voice`          | string | `"longxiaochun"`                             | TTS voice model                                                         |
| `stt_provider`       | string | `"aliyun"`                                   | STT provider (currently supports `aliyun`)                              |
| `language`           | string | `"zh-CN"`                                    | Language code                                                           |
| `welcome_greeting`   | string | `"Hi! This is QwenPaw. How can I help you?"` | Welcome message when call connects                                      |
| `call_timeout`       | float  | `30.0`                                       | Outbound call timeout in seconds                                        |

---

## Appendix

### Config overview

| Channel    | Config key | Main fields                                                                                                |
| ---------- | ---------- | ---------------------------------------------------------------------------------------------------------- |
| DingTalk   | dingtalk   | client_id, client_secret, message_type, card_template_id, card_template_key, robot_code                    |
| Feishu     | feishu     | app_id, app_secret, domain; optional encrypt_key, verification_token, media_dir                            |
| iMessage   | imessage   | db_path, poll_sec (macOS only)                                                                             |
| Discord    | discord    | bot_token; optional http_proxy, http_proxy_auth                                                            |
| QQ         | qq         | app_id, client_secret, markdown_enabled, max_reconnect_attempts                                            |
| Telegram   | telegram   | bot_token; optional http_proxy, http_proxy_auth                                                            |
| Mattermost | mattermost | url, bot_token; optional show_typing, thread_follow_without_mention                                        |
| Matrix     | matrix     | homeserver, user_id, access_token                                                                          |
| WeCom      | wecom      | bot_id, secret; optional media_dir, max_reconnect_attempts                                                 |
| WeChat     | weixin     | bot_token (or QR login); optional bot_token_file, base_url, media_dir                                      |
| XiaoYi     | xiaoyi     | ak, sk, agent_id; optional ws_url                                                                          |
| Voice      | voice      | twilio_account_sid, twilio_auth_token, phone_number, phone_number_sid; optional tts_provider, stt_provider |

All channels also support the common access control fields (`dm_policy`, `group_policy`, `allow_from`, `deny_message`, `require_mention`) documented in the common fields section below.

Field details and structure are in the tables above and [Config & working dir](./config).

### Common fields

All channels support the following common fields:

| Field                  | Type     | Default  | Description                                                               |
| ---------------------- | -------- | -------- | ------------------------------------------------------------------------- |
| `enabled`              | bool     | `false`  | Whether to enable this channel                                            |
| `bot_prefix`           | string   | `""`     | Bot reply prefix (e.g., `[BOT]`)                                          |
| `filter_tool_messages` | bool     | `false`  | Whether to filter tool call/output messages                               |
| `filter_thinking`      | bool     | `false`  | Whether to filter thinking/reasoning content                              |
| `dm_policy`            | string   | `"open"` | Direct message access policy: `"open"` (open) / `"allowlist"` (whitelist) |
| `group_policy`         | string   | `"open"` | Group chat access policy: `"open"` (open) / `"allowlist"` (whitelist)     |
| `allow_from`           | string[] | `[]`     | Whitelist (effective when policy is `"allowlist"`)                        |
| `deny_message`         | string   | `""`     | Denial message when access is denied                                      |
| `require_mention`      | bool     | `false`  | Whether @mention is required to respond                                   |

### Multi-modal message support

Support for **receiving** (user → bot) and **sending** (bot → user) text, image,
video, audio, and file varies by channel.
**✓** = supported. **🚧** = under construction (implementable but not yet
done). **✗** = not supported (not possible on this channel).

| Channel    | Recv text | Recv image | Recv video | Recv audio | Recv file | Send text | Send image | Send video | Send audio | Send file |
| ---------- | --------- | ---------- | ---------- | ---------- | --------- | --------- | ---------- | ---------- | ---------- | --------- |
| DingTalk   | ✓         | ✓          | ✓          | ✓          | ✓         | ✓         | ✓          | ✓          | ✓          | ✓         |
| Feishu     | ✓         | ✓          | ✓          | ✓          | ✓         | ✓         | ✓          | ✓          | ✓          | ✓         |
| Discord    | ✓         | ✓          | ✓          | ✓          | ✓         | ✓         | 🚧         | 🚧         | 🚧         | 🚧        |
| iMessage   | ✓         | ✗          | ✗          | ✗          | ✗         | ✓         | ✗          | ✗          | ✗          | ✗         |
| QQ         | ✓         | ✓          | ✓          | ✓          | ✓         | ✓         | ✓          | ✓          | ✓          | ✓         |
| WeCom      | ✓         | ✓          | ✓          | ✓          | ✓         | ✓         | ✓          | ✓          | ✓          | ✓         |
| WeChat     | ✓         | ✓          | ✓          | ✓          | ✓         | ✓         | ✓          | ✓          | ✓          | ✓         |
| Telegram   | ✓         | ✓          | ✓          | ✓          | ✓         | ✓         | ✓          | ✓          | ✓          | ✓         |
| Mattermost | ✓         | ✓          | 🚧         | 🚧         | ✓         | ✓         | ✓          | 🚧         | 🚧         | ✓         |
| Matrix     | ✓         | ✓          | ✓          | ✓          | ✓         | ✓         | ✓          | ✓          | ✓          | ✓         |
| XiaoYi     | ✓         | ✓          | ✗          | ✗          | ✓         | ✓         | 🚧         | 🚧         | 🚧         | 🚧        |
| Voice      | ✗         | ✗          | ✗          | ✓          | ✗         | ✗         | ✗          | ✗          | ✓          | ✗         |

Notes:

- **DingTalk**: Receives rich text and single-file (downloadCode); sends
  image / voice / video / file via session webhook.
- **Feishu**: WebSocket long connection for receiving; Open API for sending.
  Text / image / file supported both ways; message metadata includes
  `feishu_chat_id` and `feishu_message_id` for group context and dedup.
- **Discord**: Attachments are parsed as image / video / audio / file for the
  agent; sending real media is 🚧 (currently link-only in reply).
- **iMessage**: imsg + database polling; text only; attachments are ✗ (not
  possible on this channel).
- **QQ**: Receiving attachments as multimodal and sending real media are 🚧;
  currently text + link-only.
- **Telegram**: Attachments are parsed as files on receive and can be opened in the corresponding format (image / voice / video / file) within the Telegram chat interface.
- **WeCom**: WebSocket long connection for receiving; markdown/template_card for sending. Supports receiving and sending text, image, voice, video, and file.
- **WeChat Personal (iLink)**: HTTP long-polling for receiving. Supports text, images (AES-128-ECB decrypted), voice (ASR transcription), files, and videos. Sending supports text, images, files, and videos; audio files (e.g., MP3) are not supported due to iLink API limitations.
- **Matrix**: Receives image, video, audio, and file attachments via `mxc://` media URLs. Sends media by uploading to the homeserver and sending native Matrix media messages (`m.image`, `m.video`, `m.audio`, `m.file`).
- **XiaoYi**: Supports receiving text, images (JPEG/PNG/BMP/WEBP), and files (PDF/DOC/DOCX/PPT/PPTX/XLS/XLSX/TXT); video and audio are not supported by the platform.
- **Voice**: Phone call interaction via Twilio ConversationRelay. Receives audio (speech) and sends audio (TTS). All communication is voice-based; text/image/video/file are not supported over phone calls.

### Changing config via HTTP

With the app running you can read and update channel config; changes are written to
`agent.json` and applied automatically:

- `GET /config/channels` — List all channels
- `PUT /config/channels` — Replace all
- `GET /config/channels/{channel_name}` — Get one (e.g. `dingtalk`, `imessage`)
- `PUT /config/channels/{channel_name}` — Update one

---

## Extending channels

To add a new platform (e.g. WeCom, Slack), implement a subclass of **BaseChannel**; core code stays unchanged.

### Data flow and queue

- **ChannelManager** keeps one queue per channel that uses it. When a message arrives, the channel calls **`self._enqueue(payload)`** (injected by the manager at startup); the manager’s consumer loop then calls **`channel.consume_one(payload)`**.
- The base class implements a **default `consume_one`**: turn payload into `AgentRequest`, run `_process`, call `send_message_content` for each completed message, and `_on_consume_error` on failure. Most channels only need to implement “incoming → request” and “response → outgoing”; they do not override `consume_one`.

### Subclass must implement

| Method                                                  | Purpose                                                                                                                                                            |
| ------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `build_agent_request_from_native(self, native_payload)` | Convert the channel’s native message to `AgentRequest` (using runtime `Message` / `TextContent` / `ImageContent` etc.) and set `request.channel_meta` for sending. |
| `from_env` / `from_config`                              | Build instance from environment or config.                                                                                                                         |
| `async start()` / `async stop()`                        | Lifecycle (connect, subscribe, cleanup).                                                                                                                           |
| `async send(self, to_handle, text, meta=None)`          | Send one text (and optional attachments).                                                                                                                          |

### What the base class provides

- **Consume flow**: `_payload_to_request`, `get_to_handle_from_request` (default `user_id`), `get_on_reply_sent_args`, `_before_consume_process` (e.g. save receive_id), `_on_consume_error` (default: `send_content_parts`), and optional **`refresh_webhook_or_token`** (no-op; override when the channel needs to refresh tokens).
- **Helpers**: `resolve_session_id`, `build_agent_request_from_user_content`, `_message_to_content_parts`, `send_message_content`, `send_content_parts`, `to_handle_from_target`.

Override **`consume_one`** only when the flow differs (e.g. console printing, debounce). Override **`get_to_handle_from_request`** / **`get_on_reply_sent_args`** when the send target or callback args differ.

### Example: minimal channel (text only)

For text-only channels using the manager queue, you do not need to implement `consume_one`; the base default is enough:

```python
# my_channel.py
from agentscope_runtime.engine.schemas.agent_schemas import TextContent, ContentType
from qwenpaw.app.channels.base import BaseChannel
from qwenpaw.app.channels.schema import ChannelType

class MyChannel(BaseChannel):
    channel: ChannelType = "my_channel"

    def __init__(self, process, enabled=True, bot_prefix="", **kwargs):
        super().__init__(process, on_reply_sent=kwargs.get("on_reply_sent"))
        self.enabled = enabled
        self.bot_prefix = bot_prefix

    @classmethod
    def from_config(cls, process, config, on_reply_sent=None, show_tool_details=True):
        return cls(process=process, enabled=getattr(config, "enabled", True),
                   bot_prefix=getattr(config, "bot_prefix", ""), on_reply_sent=on_reply_sent)

    @classmethod
    def from_env(cls, process, on_reply_sent=None):
        return cls(process=process, on_reply_sent=on_reply_sent)

    def build_agent_request_from_native(self, native_payload):
        payload = native_payload if isinstance(native_payload, dict) else {}
        channel_id = payload.get("channel_id") or self.channel
        sender_id = payload.get("sender_id") or ""
        meta = payload.get("meta") or {}
        session_id = self.resolve_session_id(sender_id, meta)
        text = payload.get("text", "")
        content_parts = [TextContent(type=ContentType.TEXT, text=text)]
        request = self.build_agent_request_from_user_content(
            channel_id=channel_id, sender_id=sender_id, session_id=session_id,
            content_parts=content_parts, channel_meta=meta,
        )
        request.channel_meta = meta
        return request

    async def start(self):
        pass

    async def stop(self):
        pass

    async def send(self, to_handle, text, meta=None):
        # Call your HTTP API etc. to send
        pass
```

When you receive a message, build a native dict and enqueue (`_enqueue` is injected by the manager):

```python
native = {
    "channel_id": "my_channel",
    "sender_id": "user_123",
    "text": "Hello",
    "meta": {},
}
self._enqueue(native)
```

### Example: multimodal (text + image / video / audio / file)

In `build_agent_request_from_native`, parse attachments into runtime content and call `build_agent_request_from_user_content`:

```python
from agentscope_runtime.engine.schemas.agent_schemas import (
    TextContent, ImageContent, VideoContent, AudioContent, FileContent, ContentType,
)

def build_agent_request_from_native(self, native_payload):
    payload = native_payload if isinstance(native_payload, dict) else {}
    channel_id = payload.get("channel_id") or self.channel
    sender_id = payload.get("sender_id") or ""
    meta = payload.get("meta") or {}
    session_id = self.resolve_session_id(sender_id, meta)
    content_parts = []
    if payload.get("text"):
        content_parts.append(TextContent(type=ContentType.TEXT, text=payload["text"]))
    for att in payload.get("attachments") or []:
        t = (att.get("type") or "file").lower()
        url = att.get("url") or ""
        if not url:
            continue
        if t == "image":
            content_parts.append(ImageContent(type=ContentType.IMAGE, image_url=url))
        elif t == "video":
            content_parts.append(VideoContent(type=ContentType.VIDEO, video_url=url))
        elif t == "audio":
            content_parts.append(AudioContent(type=ContentType.AUDIO, data=url))
        else:
            content_parts.append(FileContent(type=ContentType.FILE, file_url=url))
    if not content_parts:
        content_parts = [TextContent(type=ContentType.TEXT, text="")]
    request = self.build_agent_request_from_user_content(
        channel_id=channel_id, sender_id=sender_id, session_id=session_id,
        content_parts=content_parts, channel_meta=meta,
    )
    request.channel_meta = meta
    return request
```

### Custom channel directory and CLI

- **Directory**: Channels under the working dir at `custom_channels/` (default `~/.qwenpaw/custom_channels/`) are loaded at runtime. The manager scans `.py` files and packages (subdirs with `__init__.py`), loads `BaseChannel` subclasses, and registers them by the class’s `channel` attribute.
- **Install**: `qwenpaw channels install <key>` creates a template `<key>.py` in `custom_channels/` for you to edit, or use `--path <local path>` / `--url <URL>` to copy a channel module from disk or the web. `qwenpaw channels add <key>` does the same and also adds a default entry to config (with optional `--path`/`--url`).
- **Remove**: `qwenpaw channels remove <key>` deletes that channel’s module from `custom_channels/` (custom channels only; built-ins cannot be removed). By default it also removes the key from `channels` in `config.json`; use `--keep-config` to leave config unchanged.
- **Config**: `ChannelConfig` uses `extra="allow"`, so any channel key can appear under `channels` in `config.json`. Use `qwenpaw channels config` for interactive setup or edit config by hand.

### HTTP route registration

For channels that require webhook callbacks (e.g., WeChat, Slack, LINE), you can register custom HTTP routes by exporting a `register_app_routes` callable in your module — no changes to QwenPaw's core source required.

At startup, QwenPaw scans modules in `custom_channels/` for a `register_app_routes` export. If found, it is called with the FastAPI `app` instance, allowing the channel to register any routes it needs.

**Route prefix behavior**:

| Prefix      | Behavior                                   |
| ----------- | ------------------------------------------ |
| `/api/`     | Silent registration                        |
| Other paths | Prints a warning at startup (non-blocking) |

**Interface — `register_app_routes(app)`**

- **Parameter**: `app` — FastAPI application instance
- **Returns**: None
- **Scope**: Register routes, middleware, or startup/shutdown events
- **Error isolation**: A single channel's registration failure does not affect other channels

**Minimal example — Echo channel**:

```
<workspace>/
└── custom_channels/
    └── my_echo/
        └── __init__.py
```

```python
# custom_channels/my_echo/__init__.py
from qwenpaw.app.channels.base import BaseChannel

class MyEchoChannel(BaseChannel):
    """A minimal channel that echoes messages back."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    async def _listen(self):
        pass  # Receive messages via HTTP callback

    async def _send(self, target, content, **kwargs):
        self.logger.info(f"Would send to {target}: {content}")


def register_app_routes(app):
    """Register HTTP routes for this channel."""

    @app.post("/api/my-echo/callback")
    async def echo_callback(request):
        """Webhook entry point."""
        body = await request.json()

        from qwenpaw.app.channels.base import TextContent
        channel = MyEchoChannel()
        channel.enqueue_user_message(
            user_id=body.get("user_id", "anonymous"),
            session_id=body.get("session_id", "default"),
            content=[TextContent(type="text", text=body.get("text", ""))],
        )

        return {"status": "ok"}
```

```json
{
  "channels": {
    "my_echo": {
      "enabled": true
    }
  }
}
```

Test after startup:

```bash
curl -X POST http://localhost:8088/api/my-echo/callback \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test", "session_id": "test", "text": "Hello!"}'
```

**Real-world example**: WeChat ClawBot integration ([PR #2140](https://github.com/agentscope-ai/QwenPaw/pull/2140), [Issue #2043](https://github.com/agentscope-ai/QwenPaw/issues/2043)) uses this mechanism to register the `/api/wechat/callback` route with Tencent's official SDK for message delivery.

---

## Related pages

- [Introduction](./intro) — What the project can do
- [Quick start](./quickstart) — Install and first run
- [Heartbeat](./heartbeat) — Scheduled check-in / digest
- [CLI](./cli) — init, app, cron, clean
- [Config & working dir](./config) — Configuration files and working directory
