---
title: "QwenPaw on your phone: Web App"
date: 2026-11-16
author: QwenPaw Team
tags: [Web App, PWA, Mobile]
excerpt: "Pick up a conversation from your phone, switch between cloud and local workspaces, and keep using the Console you already know."
related:
  heading: "Get started on your phone"
  description: "Connect your local workspace, sign in with a QR code, and add QwenPaw to your home screen."
  items:
    - label: "Docs"
      name: "Mobile Web App guide"
      href: "/docs/mobile"
---

# QwenPaw on your phone: Web App

You no longer need to be at your computer to use your local QwenPaw. Web App access lets you pick up a conversation from your phone and switch between cloud deployments and connected local workspaces. Open it in your browser or add it to your home screen. No native app is needed.

Your QwenPaw installation and Platform deployment must both support Web App access.

## Start from Console

Open [platform.agentscope.io/m](https://platform.agentscope.io/m), or connect your local workspace from Console.

Click the phone icon at the top right of your local Console. If you have not connected a cloud account, sign in from that dialog. Once connected, the same dialog shows a QR code. Scan it with your phone, check that the digits match on both screens, and confirm sign-in on your computer.

You can use any QR scanner. If the link opens inside WeChat, DingTalk, or another app, follow the page's instructions to open it in Safari or your system browser before continuing. You can also copy the full link. After sign-in, the page explains how to add QwenPaw to your home screen.

This signs your phone in to your **full Platform account**, with access to its cloud and connected workspaces. Only confirm a phone you trust. The QR code uses a short-lived, single-use authorization; it never contains a long-lived account token.

Hub users keep their local and cloud accounts separate, and each connection is limited to that user's personal Runtime. Standalone users can sign in to Platform without creating a local account. A cloud account can connect multiple local accounts or devices, up to its node quota.

## The Console you already know

Your phone loads the Console that comes with the workspace you select. The familiar model, thinking intensity, and mode controls are right in the composer; thinking settings are available when the selected model supports them. Conversations and approvals stay with their workspace when you switch.

The workspace menu is available at the top of every page and in Settings. It lists your cloud deployments and connected computers, including their online status. If a page gets stuck, choose **Refresh workspace** to reconnect without signing in again.

When you return to the app, it restores saved conversation state without resending your last message. If a node has been upgraded, reload to use its updated Console. The mobile and desktop experiences share the same UI.

Your local QwenPaw still runs on your computer, so keep it on and connected. Your phone connects through Platform and can use a different network. There is no LAN address to enter.

## One browser entry across systems

On iPhone and iPad, open Safari's **⋯** menu if needed, then choose **Share → Add to Home Screen**. On supported Android browsers, **Add to home screen** opens the installation prompt directly; otherwise, use the browser menu. On HarmonyOS, look for an option to add the page to your home screen in the system browser. Availability varies by OS and browser version.

Attachments, files, and terminal access follow the selected node's configuration and permissions. Push notifications and offline execution are unavailable.

See the [Mobile Web App guide](/docs/mobile) for setup steps, account access, and troubleshooting.
