# QwenPaw Mobile

QwenPaw Mobile is the native Android and iOS client for QwenPaw. It connects
to the same QwenPaw services and data as Console; it is not a separate,
reduced-capability product.

The app is currently a developer preview. Android builds are available for
private APK testing, but production signing, a stable OSS download URL, and
automatic updates are not yet available. TestFlight distribution is being
prepared for iOS; there is no public IPA download.

## What it can do

Mobile organizes the product around four primary areas:

- **Chats**: create and group chats, stream replies, recover running sessions,
  configure per-session model, approval and Loop settings, and use the
  Approval Inbox.
- **Agents**: browse, select, and manage Agents in the connected QwenPaw.
- **Community**: access QwenPaw community content and related destinations.
- **Workbench**: manage connections, models, Skills, MCP, automation,
  security, data, and system settings.

One installation can keep and switch between multiple connections, such as a
Platform deployment, a home computer, and a work computer. Removing one does
not remove the other paired QwenPaw connections.

## Connect to QwenPaw

### AgentScope Platform

Select AgentScope Platform on the connection screen. After secure sign-in,
the app discovers and connects to the QwenPaw deployment associated with the
account. Android uses a secure browser authentication session. The page may
appear in a Chrome Custom Tab, which is still part of the system-supported
OAuth flow. Authorization should return to QwenPaw automatically.

If authorization finishes without returning to the app:

1. Confirm Chrome or another compatible browser is enabled.
2. Return to QwenPaw from recent apps and check whether sign-in recovered.
3. Close the authorization page and start sign-in again.
4. Report the phone model, Android version, default browser, and incident time.

### Local or LAN QwenPaw

The phone must be able to reach the computer running QwenPaw. A physical phone
cannot use the computer's `127.0.0.1` or `localhost`; those addresses point to
the phone itself.

Listen on the computer's LAN interface:

```bash
qwenpaw app --host 0.0.0.0 --port 8088
```

Then enter the computer's LAN address in Mobile, for example:

```text
http://192.168.1.23:8088
```

The phone and computer must be on a network that allows them to communicate,
and the computer firewall must allow the port. Never expose an unauthenticated
QwenPaw directly to the public internet.

### QR pairing

Create a one-time pairing QR code in Console and scan it with Mobile. The QR
code contains a connection address and a short-lived, single-use ticket. It
does not contain a password or long-lived access token. Generate another QR
code after it expires.

## Multiple connections and unpairing

Tap the current QwenPaw at the top of the Chats screen to switch between saved
connections. The connection list supports native swipe actions. If the active
connection is removed while others remain, the app switches to a remaining
connection instead of clearing the entire app.

Signing out of AgentScope Platform also removes cloud QwenPaw connections
discovered and paired through that Platform account. Manually added local
connections remain intact.

## Credentials and privacy

- Connection credentials are kept in secure storage backed by iOS Keychain or
  Android Keystore.
- OAuth authorization codes and transient state are not written to ordinary
  preferences.
- Notification payloads must not contain credentials, service URLs, or full
  message bodies.
- Other devices on the network may observe traffic when plain LAN HTTP is
  used. Use a trusted network or HTTPS for sensitive environments.

## Current distribution status

| Platform | Current status                               | Planned channel                              |
| -------- | -------------------------------------------- | -------------------------------------------- |
| Android  | Private test APK, no production keystore yet | Production-signed APK on OSS; AAB can follow |
| iOS      | No public build                              | Internal or external TestFlight              |

Current Android test APKs use a test signature. Users may need to uninstall a
test build before installing the first production-signed build. Once the
production key is in use, later releases can provide stable in-place upgrades.

## Remaining release work

- Add Mobile pull-request CI for TypeScript, ESLint, unit tests, Android lint/
  build, and an unsigned iOS compile.
- Generate and back up the Android production keystore.
- Publish versioned production APKs, SHA-256 files, and `latest.json` to OSS.
- Configure Apple Developer, App Store Connect, iOS distribution signing, and
  TestFlight upload.
- Complete the Android/iOS device matrix for OAuth, LAN connections,
  multi-connection switching, notification deep links, and cold-start restore.

The website will not show a production Mobile download button until these
items are complete.

## Report an issue

Include the following when reporting a Mobile issue:

- App version and Android versionCode or iOS build number.
- Phone model, operating-system version, and default browser.
- Connection type: Platform, QR, local, or LAN.
- Reproduction steps and a screenshot of the page.
- Whether the target QwenPaw URL opens in the phone's browser.

Do not include passwords, OAuth codes, access tokens, or complete API keys in
screenshots or logs.
