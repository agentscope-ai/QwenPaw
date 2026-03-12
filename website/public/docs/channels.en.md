# Channels

A **channel** is where you talk to CoPaw: connect DingTalk and it replies
in DingTalk; same for QQ, etc. If that term is new, see [Introduction](./intro).

Two ways to configure channels:

- **Console** (recommended) — In the [Console](./console) under **Control → Channels**, click a channel card, enable it and fill in credentials in the drawer. Changes take effect when you save.
- **Edit `config.json` directly** — Default `~/.copaw/config.json` (created by `copaw init`), set `enabled: true` and fill in that platform's credentials. Saving triggers a reload without restarting the app.

All channels have common fields below:

- **enabled** — Turn the channel on or off.
- **bot_prefix** — Prefix for bot replies (e.g. `[BOT]`) so they're easy to spot.
- **filter_tool_messages** — (optional, default `false`) Filter tool call and output messages from being sent to users. Set to `true` to hide tool execution details.
- **filter_thinking** — (optional, default `false`) Filter model thinking/reasoning content from being sent to users. Set to `true` to hide thinking blocks.

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

7. (Optional) **Add your server's IP to the whitelist** — this is required for features that call the DingTalk Open API (e.g. downloading images and files sent by users). Go to **"Security & Compliance → IP Whitelist"** in your app settings and add the public IP of the machine running CoPaw. You can find your public IP by running `curl ifconfig.me` in a terminal. If the IP is not whitelisted, image and file downloads will fail with a `Forbidden.AccessDenied.IpNotInWhiteList` error.

### Link the app

You can configure it either in the Console frontend or by editing `~/.copaw/config.json`.

**Method 1**: Configure in the Console frontend

Go to "Control→Channels", find **DingTalk**, click it, and enter the **Client ID** and **Client Secret** you just obtained.

![console](https://img.alicdn.com/imgextra/i3/O1CN01i07tt61rzZUSMo5SI_!!6000000005702-2-tps-3643-1897.png)

**Method 2**: Edit `~/.copaw/config.json`

In `config.json`, find `channels.dingtalk` and fill in the corresponding information, for example:

```json
"dingtalk": {
  "enabled": true,
  "bot_prefix": "[BOT]",
  "client_id": "your Client ID",
  "client_secret": "your Client Secret"
  "filter_tool_messages": false
}
```

- Set `filter_tool_messages: true` if you want to hide tool execution details in the chat.

Save the file; if the app is already running, the channel will reload. Otherwise run
`copaw app`.

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

3. Fill **App ID** and **App Secret** in `config.json` (see "Fill config.json" below) and save

4. Run **`copaw app`** to start CoPAW

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

> **Note:** Follow this order: Configure App ID/Secret → start `copaw app` → then configure the long connection in the Feishu console. If errors persist, try stopping the copaw service and restarting `copaw app`.

![WebSocket](https://img.alicdn.com/imgextra/i3/O1CN01XdU7hK1fVY8gIDhZK_!!6000000004012-2-tps-4082-2126.png)

8. Select **Add Events**, search for **Message reveived**, and subscribe to **Message received v2.0**

![Receive](https://img.alicdn.com/imgextra/i1/O1CN01EE4iZf1CnIdDDeli6_!!6000000000125-2-tps-4082-2126.png)

![Click](https://img.alicdn.com/imgextra/i2/O1CN01PlzsFU1JhWx9EcuPc_!!6000000001060-2-tps-4082-2126.png)

![Result](https://img.alicdn.com/imgextra/i2/O1CN01fiMjkp24mN51TyWcI_!!6000000007433-2-tps-4082-2126.png)

9. Under **App Versions** → **Version Management & Release**, **Create a version**, fill in basic info, **Save** and **Publish**

![Create](https://img.alicdn.com/imgextra/i3/O1CN01mzOHs11cdO4MnZMcX_!!6000000003623-2-tps-4082-2126.png)

![Info](https://img.alicdn.com/imgextra/i1/O1CN01y1SkZP24hKiufZpb5_!!6000000007422-2-tps-4082-2126.png)

![Save](https://img.alicdn.com/imgextra/i2/O1CN01o1Wq3n2AD0BkIVidL_!!6000000008168-2-tps-4082-2126.png)

![pub](https://img.alicdn.com/imgextra/i1/O1CN01dcWI7F1PmSuniDLJx_!!6000000001883-2-tps-4082-2126.png)

### Fill config.json

Find `channels.feishu`（default as `~/.copaw/config.json`） in `config.json`. Only **App ID** and **App Secret** are required (copy from the Feishu console under Credentials & basic info):

```json
"feishu": {
  "enabled": true,
  "bot_prefix": "[BOT]",
  "app_id": "cli_xxxxx",
  "app_secret": "your App Secret"
}
```

Other fields (encrypt_key, verification_token, media_dir) are optional; with WebSocket mode you can omit them (defaults apply). Then `pip install lark-oapi` and run `copaw app`. If your environment uses a SOCKS proxy, also install `python-socks` (for example, `pip install python-socks`), otherwise you may see: `python-socks is required to use a SOCKS proxy`.

> **Note:** You can also fill in **App ID** and **App Secret** in the Console UI, but you must restart the copaw service before continuing with the long-connection configuration.
> ![console](https://img.alicdn.com/imgextra/i1/O1CN01JInbHT1ei5MdfkMGv_!!6000000003904-2-tps-4082-2126.png)

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

> **User display name (recommended):** To show **user nicknames** in sessions and logs (e.g. "张三#1d1a" instead of "unknown#1d1a"), enable the contact read permission **Read contact as app** (`contact:user.base:readonly`). Without it, Feishu only returns identity fields (e.g. open_id) and not the user's name, so CoPAW cannot resolve nicknames. After enabling, publish or update the app version so the permission takes effect.

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

3. For CoPaw to read iMessage data, **Terminal** (or the app you use to run `copaw app`) and **Messages** need **Full Disk Access** (System Settings → Privacy & Security → Full Disk Access).

4. Set the iMessage database path. The default is `~/Library/Messages/chat.db`; use this unless you've moved the database. You can configure it in either of these ways:

   - In **Console → Channels**, click the **iMessage** card, turn **Enable** on, enter the path in **DB Path**, and click **Save**.

     ![save](https://img.alicdn.com/imgextra/i1/O1CN01Bc1Dxe1rhi2vhjGsC_!!6000000005663-2-tps-3814-1954.png)

   - Or edit `config.json` (usually at `~/.copaw/config.json`):

     ```json
     "imessage": {
       "enabled": true,
       "bot_prefix": "[BOT]",
       "db_path": "~/Library/Messages/chat.db",
       "poll_sec": 1.0
     }
     ```

     **db_path** — Path to the iMessage database

     **poll_sec** — Poll interval in seconds (1 is fine)

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

You can configure via the Console UI or by editing `~/.copaw/config.json`.

**Method 1:** Configure in the Console

Go to **Control → Channels**, click **Discord**, and enter the **Bot Token** you obtained.

![Console](https://img.alicdn.com/imgextra/i4/O1CN019GKk901VE0od1PU9t_!!6000000002620-2-tps-4084-2126.png)

**Method 2:** Edit `~/.copaw/config.json`

Find `channels.discord` in `config.json` and fill in the fields, for example:

```json
"discord": {
  "enabled": true,
  "bot_prefix": "[BOT]",
  "bot_token": "your Bot Token",
  "http_proxy": "",
  "http_proxy_auth": ""
}
```

If you need a proxy (e.g. for network restrictions):

- **http_proxy** — e.g. `http://127.0.0.1:7890`
- **http_proxy_auth** — `username:password` if the proxy requires auth, otherwise leave empty

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

   > **Tip:** If you are using ModelScope Creative Space to deploy CoPaw, the IP whitelist for QQ channel should be: `47.92.200.108`

![1](https://img.alicdn.com/imgextra/i4/O1CN012UQWI21cnvBAUcz54_!!6000000003646-2-tps-4082-2126.png)

6. In sandbox config, scan the QR code with QQ to add the bot to your message list

![1](https://img.alicdn.com/imgextra/i3/O1CN01r1OvPy1kcwc30w32K_!!6000000004705-2-tps-4082-2126.png)

### Fill config.json

In `config.json`, find `channels.qq` and set `app_id` and `client_secret` to the
values above:

```json
"qq": {
  "enabled": true,
  "bot_prefix": "[BOT]",
  "app_id": "your AppID",
  "client_secret": "your AppSecret"
}
```

You provide **AppID** and **AppSecret** as two separate fields; do not concatenate
them into a single token.

You can also fill them in the Console UI.

![1](https://img.alicdn.com/imgextra/i1/O1CN013zS1dF1hLal9IM4rc_!!6000000004261-2-tps-4082-2126.png)

---

## Telegram

### Get Telegram bot credentials

1. Open Telegram and search for `@BotFather` to add a Bot (make sure it is the official @BotFather with a blue verified badge).
2. Open the chat with @BotFather and follow the instructions to create a new bot

   ![Create bot](https://img.alicdn.com/imgextra/i1/O1CN01wVVmbY1qkcxBn8Oc0_!!6000000005534-0-tps-817-1279.jpg)

3. Create the bot name in the dialog and copy the bot_token

   ![Copy token](https://img.alicdn.com/imgextra/i3/O1CN01KUMvBW1UnuF599tNX_!!6000000002563-0-tps-1209-1237.jpg)

### Configure the Bot

You can configure via the Console UI or by editing `~/.copaw/config.json`.

**Method 1:** Configure in the Console

Go to **Control → Channels**, click **Telegram**, and enter the **Bot Token** you obtained.

![Console](https://img.alicdn.com/imgextra/i4/O1CN01utJvvg1dmNSiFOOJi_!!6000000003778-0-tps-1920-993.jpg)

**Method 2:** Edit `~/.copaw/config.json`

Find `channels.telegram` in `config.json` and fill in the fields, for example:

```json
"telegram": {
    "enabled": true,
    "bot_prefix": "[BOT]",
    "bot_token": "your Bot Token",
    "http_proxy": "",
    "http_proxy_auth": ""
}
```

If you need a proxy to access the Telegram API (e.g. for network restrictions):

- **http_proxy** — e.g. `http://127.0.0.1:7890`
- **http_proxy_auth** — `username:password` if the proxy requires auth, otherwise leave empty

### Notes

The Telegram whitelist mechanism is still under construction. It is recommended to deploy for personal use only and avoid exposing your bot username publicly.

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

| Field                             | Description                                                               | Default  |
| --------------------------------- | ------------------------------------------------------------------------- | -------- |
| **url**                           | Full URL of your Mattermost instance                                      | -        |
| **bot_token**                     | Bot Access Token                                                          | -        |
| **show_typing**                   | Whether to show the "typing..." indicator                                 | `true`   |
| **thread_follow_without_mention** | Whether to respond without @mention in threads the bot has already joined | `false`  |
| **dm_policy**                     | DM policy: `open` (allow all) or `allowlist` (whitelist only)             | `"open"` |
| **group_policy**                  | Group policy: `open` (allow all) or `allowlist` (whitelist only)          | `"open"` |
| **allow_from**                    | List of allowed User IDs (effective if policy is `allowlist`)             | `[]`     |
| **deny_message**                  | Automatic reply when access is denied by the whitelist                    | `""`     |

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

   Subscribe to the wildcard topic `/server/+/up`. Messages will be automatically pushed to the corresponding topic based on the client's `client_id`. For example, after a client pushes a message to `/server/client_a/up`, OpenClaw will push the message to `/client/client_b/down` after processing.

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

   Messages will be pushed to `client/client_b/down` based on the `redirect_client_id` attribute, enabling cross-topic push. In IoT scenarios, with OpenClaw as the core, autonomous message pushing between multiple devices can be achieved according to individual requirements.

---

## Matrix

The Matrix channel connects CoPaw to any Matrix homeserver using the [matrix-nio](https://github.com/poljar/matrix-nio) library. It supports text messaging in both direct messages and group rooms.

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

**Method 2:** Edit `~/.copaw/config.json`

Find `channels.matrix` in `config.json`:

```json
"matrix": {
  "enabled": true,
  "bot_prefix": "[BOT]",
  "homeserver": "https://matrix.org",
  "user_id": "@mybot:matrix.org",
  "access_token": "syt_..."
}
```

Save the file; the channel will reload automatically if CoPaw is already running.

### Chat with the bot

Invite the bot to a room or send it a direct message from any Matrix client (e.g. Element). The bot listens for messages in all rooms it has joined.

### Notes

- The Matrix channel is **text-only** (no image/file attachments in the current version).
- Only rooms the bot has already joined are monitored. Invite the bot to a room before sending messages.
- For self-hosted homeservers, set `homeserver` to your server's base URL (e.g. `https://matrix.example.com`).

---

## Appendix

### Config overview

| Channel    | Config key | Main fields                                                             |
| ---------- | ---------- | ----------------------------------------------------------------------- |
| DingTalk   | dingtalk   | client_id, client_secret                                                |
| Feishu     | feishu     | app_id, app_secret; optional encrypt_key, verification_token, media_dir |
| iMessage   | imessage   | db_path, poll_sec (macOS only)                                          |
| Discord    | discord    | bot_token; optional http_proxy, http_proxy_auth                         |
| QQ         | qq         | app_id, client_secret                                                   |
| Telegram   | telegram   | bot_token; optional http_proxy, http_proxy_auth                         |
| Mattermost | mattermost | url, bot_token; optional show_typing, dm_policy, allow_from             |
| Matrix     | matrix     | homeserver, user_id, access_token                                       |

Field details and structure are in the tables above and [Config & working dir](./config).

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
| QQ         | ✓         | 🚧         | 🚧         | 🚧         | 🚧        | ✓         | 🚧         | 🚧         | 🚧         | 🚧        |
| Telegram   | ✓         | ✓          | ✓          | ✓          | ✓         | ✓         | ✓          | ✓          | ✓          | ✓         |
| Mattermost | ✓         | ✓          | 🚧         | 🚧         | ✓         | ✓         | ✓          | 🚧         | 🚧         | ✓         |
| Matrix     | ✓         | ✓          | ✓          | ✓          | ✓         | ✓         | ✓          | ✓          | ✓          | ✓         |

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
- **Matrix**: Receives image, video, audio, and file attachments via `mxc://` media URLs. Sends media by uploading to the homeserver and sending native Matrix media messages (`m.image`, `m.video`, `m.audio`, `m.file`).

### Changing config via HTTP

With the app running you can read and update channel config; changes are written to
`config.json` and applied automatically:

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
from copaw.app.channels.base import BaseChannel
from copaw.app.channels.schema import ChannelType

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

- **Directory**: Channels under the working dir at `custom_channels/` (default `~/.copaw/custom_channels/`) are loaded at runtime. The manager scans `.py` files and packages (subdirs with `__init__.py`), loads `BaseChannel` subclasses, and registers them by the class’s `channel` attribute.
- **Install**: `copaw channels install <key>` creates a template `<key>.py` in `custom_channels/` for you to edit, or use `--path <local path>` / `--url <URL>` to copy a channel module from disk or the web. `copaw channels add <key>` does the same and also adds a default entry to config (with optional `--path`/`--url`).
- **Remove**: `copaw channels remove <key>` deletes that channel’s module from `custom_channels/` (custom channels only; built-ins cannot be removed). By default it also removes the key from `channels` in `config.json`; use `--keep-config` to leave config unchanged.
- **Config**: `ChannelConfig` uses `extra="allow"`, so any channel key can appear under `channels` in `config.json`. Use `copaw channels config` for interactive setup or edit config by hand.

---

## Related pages

- [Introduction](./intro) — What the project can do
- [Quick start](./quickstart) — Install and first run
- [Heartbeat](./heartbeat) — Scheduled check-in / digest
- [CLI](./cli) — init, app, cron, clean
- [Config & working dir](./config) — config.json and working directory
