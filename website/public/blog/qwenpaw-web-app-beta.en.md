---
title: "QwenPaw Web App Beta: cloud and local workspaces on your phone"
date: 2026-11-16
author: QwenPaw Team
tags: [Web App, PWA, Mobile, Beta]
excerpt: "Connect Platform from Console, scan to sign in on your phone, and add QwenPaw to your home screen."
related:
  heading: "Get started on your phone"
  description: "Beta feature. May be unstable. Both your local instance and Platform must support this feature."
  items:
    - label: "Docs"
      name: "Mobile Web App guide"
      href: "/docs/mobile"
---

# QwenPaw Web App Beta: cloud and local workspaces on your phone

The mobile experience is a Web App. Open it in your browser, sign in, and add it to your home screen to switch between cloud deployments and connected local QwenPaw instances. This feature is **Beta** and may be unstable.

## Start from Console

The mobile entry is [platform.agentscope.io/m](https://platform.agentscope.io/m). Both your local instance and Platform need this Beta deployment.

![The Platform account panel in Console](/images/mobile/console-account.jpg)

Click the phone icon at the top right of your local Console. If needed, sign in to your cloud account from that dialog; the QR code appears there once the connection completes. Scan it, compare the digits on both devices, and confirm the phone on your computer. Follow the phone's instructions to add the app to your home screen.

Use any QR scanner. Recognized in-app browsers, including WeChat and DingTalk, first guide you to Safari or your system browser and let you copy the complete link. Switch browsers before continuing authorization. The phone page and home-screen icon use the QwenPaw logo. On iOS, adding the app still uses Safari's Share menu.

The phone signs in to your full Platform account, including all its cloud and connected targets. The QR code contains only a short-lived, single-use authorization. Long-lived credentials never appear in the QR code or URL.

Hub users see both their local and cloud identities. Each remote binding points to that user's personal Runtime. Standalone users sign in to Platform directly, without creating a new local account. One cloud account can connect multiple local accounts or devices within its node quota.

## What this phase supports

![Shared Console model and thinking controls (demo environment)](/images/mobile/model-thinking.jpg)

Your phone uses the Console shipped with the selected node, including the existing model, thinking intensity, and mode controls in the composer. Other pages reuse the same interface. Switching targets keeps conversations and approvals separate. Returning from the background reloads saved state without automatically resending your last message. After a node upgrade, reload its matching Console; there is no separate mobile UI to maintain.

Your local instance continues running on your computer. The phone reaches it through Platform without a manually entered LAN address. Keep the computer on and connected.

## One browser entry across systems

On iPhone and iPad, use Safari's Share → Add to Home Screen. Android can show an Install button or offer installation through its browser menu. On HarmonyOS, use the system browser's home-screen option when available; behavior depends on the OS and browser version.

Browser distribution avoids native mobile packages. Attachments, the file workspace, and terminal retain the node's capabilities and permissions. Installation, microphone access, and background behavior still require device testing; push notifications and offline execution are unavailable.

See the [Mobile Web App guide](/docs/mobile) for steps, authorization scope, and troubleshooting.
