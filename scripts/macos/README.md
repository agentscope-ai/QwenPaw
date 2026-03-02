# macOS DMG packaging

Build from repo root:

```bash
bash scripts/macos/build_dmg.sh [VERSION]
```

Output: `dist/CoPaw.app`, `dist/CoPaw-<version>.dmg`.

**UX:** Double-click CoPaw opens a **native window** showing the Console (web UI).
First launch runs `copaw init --defaults --accept-security` in
`~/Library/Application Support/CoPaw`. Closing the window quits the app and server.
