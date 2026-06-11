---
name: Beta Release Installation Duty
about: Verify installation across platforms for a beta release (usually auto-created by CI)
title: "[Release Duty] QwenPaw vX.X.X — Installation Verification"
labels: ["release-duty"]
assignees: []
---

## Release Info

- **Version:** vX.X.X
- **Release page:** https://github.com/agentscope-ai/CoPaw/releases/tag/vX.X.X
- **Deadline:** 4 hours after release publish

## Pass Criteria

A platform **passes** only when all four checkpoints are green:

| Checkpoint | What to verify |
|------------|---------------|
| Install | Follow docs, exits without error |
| Launch | Service / app opens, UI is reachable |
| Configure model | Enter API key, select model, save succeeds |
| Basic chat | Send a message, receive a non-error reply |

**Any checkpoint fails → comment with repro steps → label `installation-bug` → ping maintainer.**

---

## PyPI

**Assignee:** @<!-- fill in -->

```bash
python -m venv /tmp/qwenpaw-test && source /tmp/qwenpaw-test/bin/activate
pip install qwenpaw==X.X.X
qwenpaw
```

- [ ] Install succeeds (`pip install` exits cleanly)
- [ ] Launch succeeds (`qwenpaw` starts, browser UI reachable)
- [ ] Model configured (API key + model saved without error)
- [ ] Basic chat works (message sent, normal reply received)

**Environment:** OS: &nbsp; / Python: &nbsp; / Notes:

---

## Docker

**Assignee:** @<!-- fill in -->

```bash
docker run --rm -p 7860:7860 agentscope/qwenpaw:X.X.X
```

- [ ] Image pulled successfully
- [ ] Container starts, `http://localhost:7860` reachable
- [ ] Model configured (API key + model saved without error)
- [ ] Basic chat works (message sent, normal reply received)

**Environment:** OS: &nbsp; / Docker: &nbsp; / Arch (amd64/arm64): &nbsp; / Notes:

---

## macOS Desktop

**Assignee:** @<!-- fill in -->

1. Go to the [Release page](https://github.com/agentscope-ai/CoPaw/releases/tag/vX.X.X)
2. Download `QwenPaw-X.X.X-macOS.zip`
3. Unzip, drag `QwenPaw.app` to Applications, launch

- [ ] Download and unzip succeed
- [ ] App launches without crash
- [ ] Model configured (API key + model saved without error)
- [ ] Basic chat works (message sent, normal reply received)

**Environment:** macOS version: &nbsp; / Chip (Apple Silicon / Intel): &nbsp; / Notes:

---

## Windows Desktop

**Assignee:** @<!-- fill in -->

1. Go to the [Release page](https://github.com/agentscope-ai/CoPaw/releases/tag/vX.X.X)
2. Download `QwenPaw-Setup-X.X.X.exe`
3. Run the installer, follow the wizard, launch QwenPaw

- [ ] Installer runs without error
- [ ] App launches without crash
- [ ] Model configured (API key + model saved without error)
- [ ] Basic chat works (message sent, normal reply received)

**Environment:** Windows version: &nbsp; / Notes:

---

## Summary

| Platform | Result | Assignee |
|----------|--------|----------|
| PyPI | ⬜ PENDING | |
| Docker | ⬜ PENDING | |
| macOS Desktop | ⬜ PENDING | |
| Windows Desktop | ⬜ PENDING | |

**All PASS** → close this issue with label `verified`. Release proceeds normally.

**Any FAIL** → comment with repro steps + logs, add label `installation-bug`, ping maintainer to decide whether to block the release announcement.
