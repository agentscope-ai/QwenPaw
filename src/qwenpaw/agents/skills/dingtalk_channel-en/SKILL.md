---
name: dingtalk_channel_connect
description: "Use a headed browser to automatically complete DingTalk channel integration for QwenPaw. Applicable when the user mentions DingTalk, developer console, Client ID, Client Secret, bot, Stream mode, binding or configuring a channel. Supports pausing when a login page is detected and resuming after the user logs in."
metadata:
  builtin_skill_version: "1.3"
  qwenpaw:
    emoji: "🤖"
    requires: {}
---

# DingTalk Channel Auto-Connect (Headed Browser)

This skill automates the creation of a DingTalk application and the binding of a QwenPaw channel using a headed browser.

## Mandatory Rules

1. Must launch in headed browser mode:

```json
{"action": "start", "headed": true}
```

2. Must pause when a login gate is encountered:
   - If the page displays a login screen (e.g., login prompt, QR code login, phone/password login), stop automated operations immediately.
   - Clearly prompt the user to log in manually first, then wait for the user to reply with "logged in / continue".
   - Do not proceed with subsequent steps until the user confirms.

3. Any application configuration change only takes effect after creating a new version and publishing:
   - After configuring bot-related information, **you must publish the bot**.
   - Whether creating a new application or modifying application information (name, description, icon, bot configuration, etc.), you **must perform "create new version + publish"** at the end.
   - Do not claim the configuration is active if publishing has not been completed.

## Pre-Execution Confirmation (Must Do First)

Before starting automated clicks, initiate a "configuration confirmation" with the user, clearly informing them of customizable fields, image specifications, and default values. Use the following structured confirmation:

1. Allow the user to customize the following fields:
   - Application name
   - Application description
   - Bot icon image URL or local path
   - Bot message preview image URL or local path

2. Clearly state the image specifications (prominently):
   - Bot icon: JPG/PNG only, `240*240px` or larger, `1:1` ratio, under `2MB`, no rounded corners.
   - Bot message preview image: format `png/jpeg/jpg`, no more than `2MB`.

3. Clearly state the default values (used automatically if the user does not specify):
   - Application name: `QwenPaw`
   - Application description: `Your personal assistant`
   - Bot icon: `https://img.alicdn.com/imgextra/i4/O1CN01M0iyHF1FVNzM9qjC0_!!6000000000492-2-tps-254-254.png`
   - Bot message preview image: `https://img.alicdn.com/imgextra/i4/O1CN01M0iyHF1FVNzM9qjC0_!!6000000000492-2-tps-254-254.png`

4. If the user provides no custom values, you must first explicitly reply:
   - "All default settings will be used (QwenPaw / Your personal assistant / default images). Proceeding now."

## Image Upload Strategy (Both link and path are supported)

1. If the user provides a local path, use it directly for upload.
2. If the user provides an image link, download it to a local temporary file first, then upload.
3. The upload action sequence must be:
   - First click the page upload entry (to trigger the chooser)
   - Then call `file_upload` with the local path array (`paths_json`)
4. If the upload fails due to image specification mismatch (dimensions, ratio, size, format):
   - Immediately pause automation
   - Clearly ask the user to manually upload a compliant image
   - After the user confirms "uploaded / continue", resume from the current step

### Practical Upload Tips

1. The `paths_json` of `file_upload` must be a "JSON string array" -- note the escaping:

```json
{
  "action": "file_upload",
  "paths_json": "[\"xxx.png\"]",
  "frame_selector": "iframe[src*=\"/fe/app?isHideOuterFrame=true\"]"
}
```

2. If the page is within an iframe, prefer including `frame_selector`; otherwise the upload control may not be found or the chooser may not trigger.

3. You must click the upload entry before calling `file_upload`; calling it directly will result in:
   - `No chooser. Click upload then file_upload.`

4. Common structural features of the bot icon area that can be used for locating elements (examples; these may appear as Chinese UI labels in the DingTalk console):
   - `text: "* 机器人图标"` (Bot Icon)
   - `button: "使用应用图标"` (Use App Icon)
   - `button: "avatar"` (usually contains `img "avatar"` inside)

5. When the snapshot shows both "使用应用图标" ("Use App Icon") and "avatar", prefer clicking the `avatar` button to trigger the upload, then call `file_upload`.

## Automation Flow

### Step 1: Open the DingTalk Developer Console

1. Launch the browser in headed mode (`headed: true`)
2. Navigate to `https://open-dev.dingtalk.com/`
3. Call `snapshot` to check if login is required

If login is required, pause with the following message:

> Login to the DingTalk Developer Console is required. I have paused automated operations. Please complete the login in the opened browser. Reply "continue" when done, and I will resume from the current page.

### Step 2: Create an Internal Enterprise Application

After the user confirms login, continue:

1. Navigate to the creation path:
   - Application Development -> Internal Enterprise Applications -> DingTalk Applications -> Create Application
2. Fill in the application information (prefer user-customized values, otherwise use defaults):
   - Application name: default `QwenPaw`
   - Application description: default `Your personal assistant`
3. Save and create the application

If the page text or structure does not match expectations, re-run `snapshot` and relocate elements based on visible text semantics.

### Step 3: Add Bot Capability and Publish

1. Click **Add Application Capability** under **Application Capabilities**, find **Bot** and add it
2. Toggle the switch button on the right side of **Bot Configuration** to enabled
3. Fill in **Bot Name**, **Bot Brief**, and **Bot Description**
4. Upload the **Bot Icon** (user-customized or default image):
   - Click the image below the bot icon label
   - Default image URL: `https://img.alicdn.com/imgextra/i4/O1CN01M0iyHF1FVNzM9qjC0_!!6000000000492-2-tps-254-254.png`
   - If it is a link, download to local first, then upload
   - If the image does not meet specifications, pause and ask the user to manually upload a compliant image before continuing
5. Upload the **Bot Message Preview Image** (user-customized or default image):
   - Click the image below the bot message preview image label
   - Default image URL: `https://img.alicdn.com/imgextra/i4/O1CN01M0iyHF1FVNzM9qjC0_!!6000000000492-2-tps-254-254.png`
   - If it is a link, download to local first, then upload
   - If the image does not meet specifications, pause and ask the user to manually upload a compliant image before continuing
6. Confirm that the message receiving mode is set to `Stream Mode` (the Chinese UI may display `Stream 模式`)
7. Select **Publish**; a further confirmation dialog will appear -- select publish. Note: **you must publish the bot** before proceeding to the next step

### Step 4: Create Version and Publish

1. Navigate to `Application Release -> Version Management & Release`
2. Create a new version (required after every configuration change)
3. Fill in the version description; set the application visibility scope to all employees
4. Follow the page prompts to complete publishing; a new dialog will appear -- select confirm publish
5. Only after seeing the successful publication status may you proceed with subsequent steps or tell the user "the configuration is now active"

### Step 5: Obtain Credentials

1. Navigate to `Basic Information -> Credentials & Basic Info`
2. Inform the user that the `Client ID` (AppKey) and `Client Secret` (AppSecret) are on this page. Do not make changes proactively; guide the user to bind them on their own

## QwenPaw Binding Methods

After obtaining the credentials, guide the user to choose one of the following methods:

1. Console frontend configuration:
   - In the QwenPaw console, go to `Control -> Channels -> DingTalk`
   - Enter the `Client ID` and `Client Secret`

2. Configuration file method:

```json
"dingtalk": {
  "enabled": true,
  "bot_prefix": "[BOT]",
  "client_id": "Your Client ID",
  "client_secret": "Your Client Secret"
}
```

Path: `~/.qwenpaw/config.json`, under `channels.dingtalk`.

### Credential Delivery Requirements (Mandatory)

1. The agent is only responsible for guiding the user to the credentials page, obtaining and displaying the `Client ID` and the actual `Client Secret`.
2. The agent must not proactively modify the `console` configuration or `~/.qwenpaw/config.json`.
3. You must instruct the user to fill in the credentials manually using one of the following two methods:
   - Console frontend: `Control -> Channels -> DingTalk`
   - Configuration file: edit the `channels.dingtalk` field in `~/.qwenpaw/config.json`

## Browser Tool Usage Pattern

Execute in the following order by default:

1. `start` with `headed: true`
2. `open`
3. `snapshot`
4. `click` / `type` / `select_option` / `press_key` as needed
5. frequent `snapshot` after page transitions
6. `stop` when done

## Stability and Recovery Strategy

- Prefer using the `ref` from the latest `snapshot`; only use `selector` when necessary.
- After each critical click or navigation, use a short wait (`wait_for`) and immediately re-run `snapshot`.
- If the session expires or re-login is required mid-flow, pause again and wait for the user to log in before continuing from the current step.
- If automation is blocked by tenant permissions or admin approval, clearly describe the blocker and ask the user to manually complete that step before resuming.
