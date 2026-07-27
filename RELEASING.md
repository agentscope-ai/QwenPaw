# Releasing QwenPaw

_中文版：[RELEASING_zh.md](RELEASING_zh.md)_

QwenPaw ships four artifacts from a single version — the **PyPI** wheel, the
**Docker** image, the **desktop** apps (Tauri, Windows + macOS) and the
**plugins** bundle. They are published together by one orchestrated workflow so
that a failure in any one of them blocks the whole release: you can never end up
with, e.g., a web release that has no matching desktop build.

> Orchestrator: [`.github/workflows/release.yml`](.github/workflows/release.yml).
> The older per-artifact workflows are kept as a fallback — see
> [Rollback to the legacy flow](#rollback-to-the-legacy-flow).

## TL;DR

1. Create a **draft** GitHub Release (tag + notes). Do **not** click *Publish*.
2. Actions → **Release (unified)** → *Run workflow* (leave `dry_run` off).
3. It builds + verifies everything; only if all of it passes does it publish all
   artifacts and flip the release to *published*.
4. If anything fails, nothing is published and the draft is left untouched — fix
   and re-run.

## How a release works

`release.yml` runs in three phases:

1. **Resolve** — finds the target draft (the `tag` input, or auto-detects the
   single existing draft), resolves the draft's `target_commitish` to a concrete
   SHA, and pins every downstream job to that SHA (so *what is built* == *what is
   published*). On a real release it also fails fast if the DashScope secret is
   missing.
2. **Prepare** (build + verify, publishes nothing) — in parallel:
   - `build-wheel` — build the Python wheel (with the bundled console).
   - `verify-web` — pip-install, Docker health-check and install-script checks.
   - `build-desktop` — build the Tauri Windows + macOS apps and run the
     install → launch → real-chat UI verification.
   - `build-plugins` — pack the plugin bundle.
3. **Gate + Publish** — every publish job `needs` **all** prepare jobs, so a
   single failure above skips the entire publish phase. When all prepare jobs are
   green: publish to PyPI, push the multi-arch Docker image, attach the desktop
   installers to the release + upload them to OSS, publish plugins — then, as the
   **last** step, flip the draft to *published* (pinned to the built SHA) and open
   the Release Duty verification issue.

A full run is ~60–75 min, dominated by the desktop Tauri builds.

## Cutting a release

1. **Create the draft release**
   - UI: Releases → *Draft a new release* → set the tag + notes → **Save draft**
     (do **not** publish). For a pre-release, tick *Set as a pre-release*.
   - CLI:
     ```bash
     gh release create v2.0.0-beta.8 --draft --prerelease \
       --target main --title "v2.0.0-beta.8" --notes "..."
     ```
   - The tag should correspond to `src/qwenpaw/__version__.py` (`resolve`
     validates this with `packaging` normalization and fails on a mismatch, e.g.
     tag `v2.0.1-beta.1` must match version `2.0.1b1`).
   - Prefer pinning the draft to a commit (`--target <sha>`). If you use
     `--target main`, avoid merging to `main` between creating the draft and
     running the workflow, otherwise the build uses the newer `main` HEAD.
2. **Run the workflow**: Actions → **Release (unified)** → *Run workflow* on
   `main`. Leave `tag` empty to auto-detect the single draft (or set it
   explicitly); leave `dry_run` **unchecked**.
3. **Watch it**: on success the release flips to *published* with all artifacts
   attached and a Release Duty issue is opened. On failure, see
   [Troubleshooting](#troubleshooting).

## Version types: beta / stable / post

The procedure is identical for all types — the type is inferred from the **tag**:

| Type | Example tag | Draft "pre-release"? | Docker tags | PyPI |
|------|-------------|----------------------|-------------|------|
| beta / rc / alpha / dev | `v2.0.0-beta.8` | yes | `<version>` + `pre` (no `latest`) | uploaded; treated as a pre-release by pip (`--pre`) |
| stable | `v2.0.0` | no | `<version>` + `pre` + `latest` | normal |
| post | `v2.0.0.post4` | no | `<version>` + `pre` + `latest` | post release |

Notes:

- Pre-release detection is **tag-based**: a tag containing `beta`/`alpha`/`rc`/`dev`
  is a pre-release (so use the `-beta.N` form); `stable` and `.postN` tags also
  update the Docker `latest` tag.
- The desktop OSS `latest` files and the Tauri auto-update manifest are currently
  updated for **every** release, including betas (this matches the previous
  `desktop-release.yml` behavior and is unchanged here). Making the desktop
  `latest`/updater stable-only is a possible future improvement.

## Troubleshooting

**Guarantee:** the draft is flipped to *published* only after **all** publish
jobs succeed. If anything fails, the release stays a draft.

| Situation | What happened | What to do |
|-----------|---------------|------------|
| A prepare job fails (desktop / web verify / wheel / plugins) | All publish + `finalize` + `duty-issue` are **skipped**; nothing published; draft untouched | Read the failed job's logs and fix (or re-run if flaky) → **Re-run failed jobs**, or re-run the workflow. No cleanup needed. |
| A publish job fails after the gate (e.g. Docker push fails after PyPI already uploaded) | `finalize` needs all publishes, so the draft is **not** flipped; but some artifacts may already be live | **Re-run failed jobs** (already-succeeded jobs are not re-run; Docker re-push is idempotent, OSS uses `--force`) → the draft flips once they pass. If a published PyPI version is now taken and cannot be reused, cut a `.postN` instead. |
| `finalize` fails | All artifacts published but the release was not flipped | Re-run `finalize`, or manually `gh release edit <tag> --draft=false --target <sha>` (or click *Publish*). |
| `duty-issue` fails | Release is published; only the tracking issue is missing | Re-run the job, or dispatch `release-duty.yml` with the `tag`. Non-blocking. |
| `promote-desktop` fails | Release is published, but the desktop `latest` files / updater manifest / index were not refreshed (existing users' auto-updater does not see the new version yet; versioned downloads still work) | Re-run the job — it is idempotent (`ossutil cp --force`). Non-blocking for first-install users. |
| "Multiple draft releases found" | More than one draft exists | Re-run *Run workflow* with an explicit `tag`. |
| "No draft release found" / "not a draft" | No draft, or wrong tag | Create the draft / fix the tag, then re-run. |
| resolve rejects the tag (version mismatch) | The draft tag doesn't match `src/qwenpaw/__version__.py` | Align the tag with the version (packaging-normalized, e.g. `v2.0.1-beta.1` ↔ `2.0.1b1`), then re-run. |

## Rollback to the legacy flow

The pre-existing per-artifact workflows are intentionally retained. If the
orchestrator is broken, publish the release the old way — **Publish** the GitHub
Release (or `gh release create ...`), which triggers `publish-pypi` /
`docker-release` / `desktop-release` / `plugins-release` on `release: published`.

> **Warning:** the legacy flow does **not** gate the web release on the desktop
> build (the very problem this orchestrator fixes), so use it only as an
> emergency fallback.

## Fork / dry-run testing

Run **Release (unified)** with `dry_run: true` to exercise the gate and the
draft→published flip **without** touching production: PyPI upload, Docker push
and OSS upload become no-ops, while the desktop build/verify, the draft flip and
the duty issue still run for real. On a fork this only affects the fork's own
release page.

Note: the desktop build's install → launch → chat UI verification still runs
under `dry_run` and needs the `QWENPAW_DASHSCOPE_API_KEY` secret — `dry_run` only
skips the resolve-stage fail-fast check, not the verification itself.
