# Mobile Web App (Beta)

> Beta feature. May be unstable. Both your local QwenPaw and Platform must run versions that support this feature.

The mobile experience runs in your browser. Add it to your home screen to switch between cloud workspaces and connected local QwenPaw instances in Platform. Browser distribution does not require an App Store or Android store listing; installation behavior varies by system.

Entry point: [platform.agentscope.io/m](https://platform.agentscope.io/m). This Beta requires a coordinated deployment; upgrading Console alone does not enable it.

## Connect from your computer

1. Start QwenPaw and open its Console.
2. Open the bottom-left workspace menu, choose **Sign in to cloud**, and complete sign-in and authorization in the new window.
3. Return to Console and check your cloud identity and node status.

Standalone users sign in to Platform directly, without creating a new local account. Hub users first sign in to their local account, then connect a cloud account. The account panel displays both identities. Each Hub binding targets that user's personal Runtime; administrator privileges do not expand its remote scope.

One cloud account can connect multiple local accounts or devices, with separate credentials for each binding and subject to Platform's existing node quota. If enrollment fails, existing bindings remain intact. Resolve the quota or network issue, then choose **Retry connection**.

## Sign in on your phone

![Platform account panel in Console](/images/mobile/console-account.jpg)

1. Click the phone icon, **Add to phone (Beta)**, at the top right of Console.
2. Scan the QR code and open it in your system browser.
3. Tap **Continue sign-in** and compare the digits on both devices.
4. On your computer, choose **Confirm this phone**.
5. Once your workspace opens on the phone, follow the home-screen instructions.

**This signs in to your full Platform account**, including all its cloud and connected targets. Confirm only on a phone you trust. The QR code contains a single-use authorization valid for two minutes, never a long-lived login token. Closing the desktop QR panel cancels unfinished authorization.

A phone already signed in to an account that owns the scanned target opens that target directly. Switching to another account still requires desktop confirmation.

## Add to your home screen

| System       | Steps                                                                                                                                 |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------------- |
| iOS / iPadOS | Open in Safari, then **Share → Add to Home Screen → Add**. The website can guide you through this system action.                      |
| Android      | Tap **Install** when supported, or find **Install app / Add to Home Screen** in the browser menu.                                     |
| HarmonyOS    | Look for **Add to desktop** in the system browser. Availability depends on the OS and browser version; use a bookmark if unavailable. |

No Android Quick App or HarmonyOS native package is required. Use trusted HTTPS. If an in-app browser lacks installation controls, open the page in your system browser. Systems that transfer cookies during installation can restore your session; otherwise scan again from Console after launching the installed app.

## Use and recovery

![Console model and thinking controls on mobile (demo environment)](/images/mobile/model-thinking.jpg)

- Open the workspace menu with the experiment icon at the top, choose **Cloud** or **Connected**, then select an agent and conversation.
- Your phone reuses the Console shipped with the selected node. Choose the model, thinking intensity, and mode with the existing composer controls. Pages, attachments, the file workspace, and terminal use the same Console; availability depends on node configuration.
- Switching workspaces clears the current target's UI context, keeping messages and approvals separate.
- Your computer must stay on and QwenPaw must keep running with outbound access to Platform. Your phone can use another network.
- On reconnect or return from the background, the page reloads saved conversation status. It never automatically resends your last message.
- You can add an offline node to your phone, but operations require it to come online. There is no offline execution.
- After a node upgrade, wait for the current response to finish before choosing **Update** to reload its Console. Unsent drafts are retained; sent requests are never automatically replayed.

Older nodes without Web App support must upgrade first. Updating the web entry does not require every node to upgrade together, but its connection protocol must be supported. Terminal retains the node's authentication and dependency requirements. HTTP uploads are limited to 8 MiB. Push notifications and offline execution are unavailable; installation, microphone permissions, and background behavior require validation on individual devices.

## Sign out and disconnect

**Sign out of Web App** on your phone ends its web session. Signing out of the cloud account in Console ends the desktop login and leaves the node binding in place. The main Platform site keeps its existing account session and has its own sign-out action.

Choose **Disconnect node** in the Console account panel to stop remote access to that node. Other devices connected to the same cloud account remain connected. Disabling a Hub user or changing Runtime ownership also stops forwarding through the old local mapping.

## Troubleshooting

**Expired or used QR code:** Refresh it on your computer, then scan and confirm again.

**Signed in but not connected:** Resolve the quota or network error shown in the account panel, then retry connection.

**Asked to sign in after installation:** Session transfer depends on your system version. Scan again; do not copy long-lived tokens into URLs.

**No Install button:** Follow the browser-menu instructions above. Websites cannot guarantee a system installation prompt.

See also [Console](./console), [Hub](./hub), and [Security](./security).
