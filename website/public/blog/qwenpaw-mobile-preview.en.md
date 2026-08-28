---
title: "QwenPaw Mobile Preview: Take Your QwenPaw With You"
date: 2026-08-28
author: QwenPaw Team
tags: [QwenPaw Mobile, Android, iOS, Multiple Connections]
excerpt: "QwenPaw Mobile is entering developer preview with a native experience for Platform deployments, local computers, and other paired QwenPaw instances."
related:
  heading: "Explore QwenPaw Mobile"
  description: "Review current capabilities, connection methods, distribution status, and testing notes."
  items:
    - label: "Docs"
      name: "QwenPaw Mobile documentation"
      href: "/docs/mobile"
---

# QwenPaw Mobile Preview: Take Your QwenPaw With You

QwenPaw has always been available through its browser Console. But when a task
is running in the background, an Agent is waiting for approval, or you simply
want to check progress while away from your desk, opening an interface designed
for desktop is not the most natural experience.

QwenPaw Mobile is now entering developer preview. It is a native Android and
iOS client built on the same QwenPaw services, chats, and APIs, rather than a
separate mobile product with a reduced feature set.

## One app, multiple QwenPaw connections

Mobile can save and switch between multiple connections:

- A cloud QwenPaw on AgentScope Platform.
- A local QwenPaw on a home or office computer.
- Other instances securely paired with a QR code from Console.

These connections remain independent. Switch the active QwenPaw from the top
of the Chats screen, or remove a connection with a native swipe action. If the
active connection is removed, the app moves to another saved connection rather
than clearing every pairing.

## Full capability goes beyond chat

Mobile is more than a messaging window. The current experience is organized
around Chats, Agents, Community, and Workbench:

- Chats support creation, grouping, streaming replies, and running-session
  recovery.
- Each session can select its own model, approval level, and Loop settings.
- Approval Inbox stays with Chats to reduce navigation during active work.
- Agents and Workbench expose Agent, model, Skills, MCP, automation, security,
  and connection settings.
- Light and dark appearance can follow the system or the user's preference.

A small number of specialist interactions may remain PC-only when they are not
usable on a small screen. The goal is still to keep routine QwenPaw operation
inside Mobile instead of sending users back to the browser Console.

## Interaction designed for a phone

Shrinking Console is not the same as designing for mobile. The app uses bottom
navigation, native back behavior, bottom sheets, anchored action menus,
in-bubble text selection, and swipe actions. Common operations remain close to
the thumb without stacking desktop-style dialogs on a small screen.

Connections, chats, and Agent state continue to use the same API contract as
Console. The next contract work will extract shared TypeScript request/response
types, parsing, validation, and status mapping so Mobile and Console do not
maintain separate interpretations of the protocol.

## A preview, not a production release

Android can already produce private test APKs. Compatibility work has covered
Android 16, different browser-discovery behaviors, and Platform OAuth return
handling. iOS and Android share the same product capabilities and design, with
TestFlight planned for iOS distribution.

Current Android APKs still use a test signature. The production keystore,
automated CI, stable OSS download URL, and upgrade path are not complete. iOS
distribution signing and TestFlight upload also remain to be configured. The
website will therefore not show a production download button yet.

The next release milestones are:

1. Android production signing and versioned OSS publishing.
2. Mobile pull-request CI and reproducible builds.
3. iOS TestFlight signing and upload.
4. A formal Android/iOS device acceptance matrix.
5. Notification deep-link validation in foreground, background, and cold start.

Internal testers should read the [QwenPaw Mobile documentation](/docs/mobile)
and include the phone model, operating-system version, default browser,
connection type, and reproduction steps when reporting an issue. Never include
passwords, OAuth codes, access tokens, or API keys in screenshots or logs.
