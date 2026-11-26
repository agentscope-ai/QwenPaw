# Mobile Web App

> Your QwenPaw installation and Platform deployment must both support Web App access.

Use QwenPaw from your phone's browser, or add it to your home screen for easy access. One workspace menu lets you switch between cloud deployments and connected local instances. There is no native app to install from an app store; home-screen installation varies by browser and operating system.

Open [platform.agentscope.io/m](https://platform.agentscope.io/m). To connect a local instance, follow the steps below. Updating Console alone will not enable the feature if your Platform deployment does not yet support Web App access.

## Connect your local QwenPaw

1. Start QwenPaw and open Console.
2. Click the phone icon at the top right. If you have not connected a cloud account, choose **Sign in to cloud** and finish sign-in in the window that opens.
3. Once connected, the same dialog shows a QR code. You can also sign in to or manage your cloud account from the workspace menu at the bottom left.

For a standalone installation, sign in to Platform directly; you do not need to create a local account. In Hub, sign in to your local account first, then connect your cloud account. The account panel shows both. Each Hub connection is limited to that user's personal Runtime, including when the user is an administrator.

One cloud account can connect multiple local accounts or devices, up to its node quota. Each connection has its own credentials. If a new connection fails, existing connections stay in place. Resolve the quota or network error shown in the panel, then choose **Retry connection**.

## Sign in on your phone

1. Click the **Add to phone** icon at the top right of Console.
2. Scan the QR code with your phone. If the page opens inside another app, follow the browser instructions or copy the full link into Safari on iOS or your system browser on Android or HarmonyOS. Do this before continuing sign-in.
3. Tap **Continue sign-in** and check that the digits match on your phone and computer.
4. On your computer, choose **Confirm this phone**.
5. Once your workspace opens on the phone, follow the home-screen instructions.

**This signs your phone in to your full Platform account**, with access to all of its cloud and connected workspaces. Only confirm a phone you trust. The QR code uses a single-use authorization that expires after two minutes; it never contains a long-lived login token. Closing the QR dialog on your computer cancels any unfinished authorization.

If your phone is already signed in to an account with access to that workspace, the workspace opens directly. Switching to a different account still requires confirmation on your computer.

## Add to your home screen

| System       | Steps                                                                                                                                                     |
| ------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| iOS / iPadOS | In Safari, open the **⋯** menu if needed, then **Share → Add to Home Screen → Add**. If the action is missing, check **Edit Actions** in the share sheet. |
| Android      | Choose **Add to home screen** and confirm the browser's installation prompt when available, or use **Install app / Add to Home Screen** in its menu.      |
| HarmonyOS    | Look for **Add to desktop** in the system browser. Availability depends on your OS and browser version; use a bookmark if this option is unavailable.     |

No Android Quick App or HarmonyOS native package is needed. Use an HTTPS address with a trusted certificate. Browsers inside apps such as WeChat and DingTalk show instructions for opening the page in your system browser. The scan page also lets you copy the full link. Opening that link in another browser does not use up the authorization; if it has expired or you have already started sign-in, refresh the QR code on your computer and scan again.

Your home-screen icon uses the QwenPaw logo. Whether the installed app keeps your browser session depends on your operating system and browser. If it asks you to sign in, scan a new QR code from Console after launching the app.

## Workspaces and conversations

- Open the workspace menu at the top or in **Settings**. Choose a **Cloud** or **Connected** workspace, then select an agent and conversation.
- Use **Refresh workspace** if a page gets stuck. Your account and selected workspace stay in place.
- Choose a model, thinking intensity, and mode from the composer. Thinking settings depend on the selected model's capabilities.
- Your phone uses the Console that comes with the selected node. Other pages, attachments, files, and terminal access follow that node's configuration and permissions.
- Conversations and approvals stay with their workspace when you switch.
- Keep your computer on, with QwenPaw running and connected to Platform. Your phone can use a different network.
- When you reconnect or return to the app, it restores saved conversation state without resending your last message.
- You can add an offline node to your phone, but the node must come online before you can use it. Offline execution is not supported.
- After a node upgrade, wait for the current response to finish, then choose **Update** to reload its Console. Unsent drafts are retained; sent requests are never automatically replayed.

Each supported node supplies its own Console. Terminal access requires the node's usual authentication and dependencies. Uploads are limited to 8 MiB. Push notifications are unavailable.

## Sign out or disconnect a node

Choose **Sign out of Web App** on your phone to end its web session. Signing out of your cloud account in Console ends the desktop login but keeps the node connected. The main Platform website has a separate sign-out action.

Choose **Disconnect node** in the Console account panel to stop remote access to that node. This does not disconnect other devices on the same cloud account. Disabling a Hub user or changing Runtime ownership also stops remote access through that user's previous connection.

## Troubleshooting

**Expired or used QR code:** Refresh it on your computer, then scan and confirm again.

**Signed in but not connected:** Resolve the quota or network error shown in the account panel, then retry the connection.

**Asked to sign in after installation:** Your browser session may not carry over to the installed app. Open the app and scan a new QR code from Console. Never put long-lived tokens in a URL.

**No Install button:** Use the browser-menu steps above. A website cannot guarantee that your browser will show an installation prompt.

**Console fails to load:** Choose **Refresh** on the recovery page, or select another workspace. If a loaded Console page fails, use **Refresh workspace** at the top. Refreshing does not resend your last message.

See also [Console](./console), [Hub](./hub), and [Security](./security).
