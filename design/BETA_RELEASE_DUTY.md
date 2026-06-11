# Beta Release Installation Duty

## Background & Goal

QwenPaw is released on GitHub, including stable and beta versions.
Beta releases are the first versions users encounter; a broken install
experience immediately hurts perception.

**Goal:** For every beta / pre-release, one designated person per
installation method verifies that users can complete the critical path:
**install → launch → configure a model → basic chat.**

---

## Pass Criteria

A platform **passes** only when all four checkpoints succeed:

| Checkpoint | What to verify |
|------------|---------------|
| Install | Follow docs, exits without error |
| Launch | Service / app opens, UI is reachable |
| Configure model | Enter API key, select model, save succeeds |
| Basic chat | Send a message, receive a non-error reply |

**Any checkpoint fails → comment with repro steps → label `installation-bug`
→ ping maintainer → maintainer decides whether to block the release.**

---

## Platform Matrix

| Platform | Install method | Environment requirement |
|----------|---------------|------------------------|
| **PyPI** | `pip install qwenpaw==<version>` | Python 3.10+, clean venv |
| **Docker** | `docker run agentscope/qwenpaw:<version>` | Docker Desktop / Linux daemon |
| **macOS Desktop** | Download `.zip` from GitHub Release | macOS 13+, Apple Silicon or Intel |
| **Windows Desktop** | Download `.exe` from GitHub Release | Windows 10/11 64-bit |

---

## Collaboration Mechanism: GitHub Issue Duty

### Overall Flow

```
Beta pre-release published on GitHub
            │
            ▼
GitHub Actions  (beta-release-duty.yml)
  Counts previous pre-releases → computes sequential rotation index
  Picks one assignee per platform from the per-platform roster
  Creates a Duty Issue via GitHub API:
    - Title:   [Release Duty] QwenPaw <tag> — Installation Verification
    - Label:   release-duty
    - Assigns: all platform assignees
    - Body:    per-platform checklist + install commands + deadline
            │
            ▼
Each assignee receives a GitHub notification
  Verifies their platform, ticks checklist items
            │
      ┌─────┴─────┐
    PASS         FAIL
      │             │
      ▼             ▼
  Close issue   Comment repro + logs
  Label: verified   Label: installation-bug
                    @maintainer decides
```

### Issue Lifecycle

- **Created:** within 5 minutes of the Release being published
- **Deadline:** 4 hours after the release is published (shown in the issue)
- **Close condition:** all four platforms PASS → maintainer or assignee
  closes the issue and adds the `verified` label
- **Failure handling:** add `installation-bug`, comment repro steps,
  @maintainer to decide on blocking the release announcement

---

## Rotation Design

### Roster file: `.github/release-duty-roster.yml`

Each platform has its own independent rotation list.

```yaml
pypi:
  rotation:
    - github: alice
      name: Alice
    - github: bob
      name: Bob

docker:
  rotation:
    - github: charlie
      name: Charlie
    - github: dave
      name: Dave

macos:
  rotation:
    - github: eve
      name: Eve
    - github: frank
      name: Frank

windows:
  rotation:
    - github: grace
      name: Grace
    - github: henry
      name: Henry
```

### Sequential rotation (stateless)

The GitHub Action computes the rotation index at runtime without storing
any state file:

```
index = (number of pre-releases published BEFORE this one) % len(rotation)
```

This means each new pre-release automatically advances every platform's
rotation by one slot, in the order the releases were published.

**Example:** If there have been 3 previous pre-releases and Alice / Bob / Charlie
are in the PyPI rotation, the 4th pre-release assigns Charlie (index 3 % 3 = 0 → wait, 3 pre-releases means index = 3, 3 % 3 = 0 = Alice again, then Bob for the 4th, etc.).

If a temporary swap is needed, just manually re-assign in the GitHub Issue —
the next release will still follow the roster.

---

## Required GitHub Setup

### Labels to create

Go to **Issues → Labels** and create:

| Label name | Suggested color | Purpose |
|------------|----------------|---------|
| `release-duty` | `#0075ca` | Applied to every duty issue |
| `pre-release` | `#e4e669` | Applied to beta / alpha / rc / dev duty issues |
| `stable` | `#0e8a16` | Applied to stable and post duty issues |
| `installation-bug` | `#d93f0b` | Marks failures found during duty |
| `verified` | `#0e8a16` | Marks issues where all platforms passed |

### Actions permissions

Go to **Settings → Actions → General → Workflow permissions**
and select **"Read and write permissions"** so the Action can create issues.

---

## File Inventory

```
.github/
├── release-duty-roster.yml           # Per-platform rotation roster
├── ISSUE_TEMPLATE/
│   └── 6-release_duty.md            # Manual fallback template
└── workflows/
    └── release-duty.yml             # Action: auto-create Duty Issue on every release
design/
└── BETA_RELEASE_DUTY.md             # This design document
```

---

## On-Call Handbook

### 1. Receive notification

GitHub will notify you by email / notification center when you are assigned
to a Duty Issue. Issue URL format:
`https://github.com/agentscope-ai/CoPaw/issues/XXXX`

### 2. Verify PyPI

```bash
python -m venv /tmp/qwenpaw-test
source /tmp/qwenpaw-test/bin/activate   # Windows: .\Scripts\activate
pip install qwenpaw==VERSION
qwenpaw
# Open http://localhost:<PORT> in browser, configure model, send a message
```

### 3. Verify Docker

```bash
docker run --rm -p 7860:7860 agentscope/qwenpaw:VERSION
# Open http://localhost:7860, configure model, send a message
```

### 4. Verify macOS Desktop

1. Go to the GitHub Release page, download `QwenPaw-VERSION-macOS.zip`
2. Unzip, drag `QwenPaw.app` to Applications
3. Open the app, configure a model, send a message

### 5. Verify Windows Desktop

1. Go to the GitHub Release page, download `QwenPaw-Setup-VERSION.exe`
2. Run the installer, follow the wizard
3. Launch QwenPaw, configure a model, send a message

### 6. Record result

Tick checkboxes in the Issue. If a platform fails, reply with:
- Exact steps to reproduce
- Relevant logs or screenshots
- Your OS / env info

Then add label `installation-bug` and @mention the maintainer.

### 7. Close on success

All platforms PASS → leave a comment with environment details → close the
issue → add label `verified`.

---

## FAQ

**Q: I don't have a Windows machine — what do I do?**
A: Note it in the roster file (`platforms: [pypi, docker, macos]`).
The current implementation assigns one person per platform independently,
so you only need to cover your listed platforms.

**Q: The Docker image isn't pushed yet when I check.**
A: The Docker release Action runs in parallel with PyPI and takes up to
~30 min. Comment in the issue that you are waiting, and check back. Do not
close or FAIL before the image is available.

**Q: Should I wait for a bug fix before closing the issue?**
A: No. The Duty Issue records the verification *result*, not the fix status.
If you find a FAIL, create a separate bug issue linked to the Duty Issue,
and let the maintainer decide whether to block the release announcement.

**Q: Do stable and post releases also need duty?**
A: Yes. The Action triggers on **every** published release — pre-release
(beta / alpha / rc / dev), stable, and `.post` patch releases. Each release
advances the rotation by one slot regardless of type. The Issue title and
labels include the release type badge (Beta / RC / Stable / Post) so it
is clear at a glance what kind of release is being verified.
