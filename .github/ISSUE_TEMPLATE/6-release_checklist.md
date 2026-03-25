---
name: Release Checklist
about: Maintainer checklist for official CoPaw release
title: "[Release]: vX.Y.Z"
labels: ["release", "triage"]
assignees: []
---

## Release Target

- **Version:** [e.g. 0.0.8]
- **Tag:** [e.g. v0.0.8]
- **Type:** [stable / prerelease / post]
- **Release date:** [YYYY-MM-DD]

## Branch and Scope

- [ ] Release source branch is `main`
- [ ] Scope and changelog reviewed
- [ ] Breaking changes are explicitly documented

## Local Quality Gate

- [ ] `pre-commit run --all-files` passed
- [ ] `pytest` passed
- [ ] Frontend formatting done if needed (`console` / `website`)

## Build Smoke Test

- [ ] `bash scripts/wheel_build.sh` succeeded
- [ ] Wheel/sdist artifacts exist in `dist/`
- [ ] Optional Docker smoke build succeeded (`bash scripts/docker_build.sh copaw:release-smoke`)

## Release Publish

- [ ] `src/copaw/__version__.py` updated
- [ ] Version format validated (PEP 440)
- [ ] Tag created and GitHub Release published
- [ ] Pre-release flag set correctly if applicable

## Workflow Status

- [ ] `.github/workflows/publish-pypi.yml` succeeded
- [ ] `.github/workflows/docker-release.yml` succeeded
- [ ] `.github/workflows/desktop-release.yml` succeeded

## Post-release Verification

- [ ] PyPI package is available and installable
- [ ] Docker tags verified (`vX.Y.Z`, `pre`, and `latest` when stable)
- [ ] Release assets verified (`CoPaw-Setup-*.exe`, `CoPaw-*-macOS.zip`)

## Roll-forward Notes

- [ ] Roll-forward plan prepared if issues are found
- [ ] Follow-up issue(s) created when needed

## Evidence

```bash
# Paste key command outputs and workflow links here
```
