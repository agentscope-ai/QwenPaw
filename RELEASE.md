# CoPaw Release Guide

This document describes the official release procedure for CoPaw.

## Scope

A GitHub Release with status `published` triggers these workflows automatically:

- PyPI package publishing: `.github/workflows/publish-pypi.yml`
- Docker multi-arch image publishing: `.github/workflows/docker-release.yml`
- Desktop artifact build and upload: `.github/workflows/desktop-release.yml`

## 1. Preconditions

1. Release from `main`.
2. Local checks must pass:

```bash
pip install -e ".[dev,full]"
pre-commit run --all-files
pytest
```

3. Required GitHub secrets are configured:
- `PYPI_API_TOKEN`
- `DOCKER_USERNAME`
- `DOCKER_PASSWORD`
- `ALIYUN_ACR_USERNAME`
- `ALIYUN_ACR_PASSWORD`

## 2. Bump Version

Update version in a single source of truth:

- `src/copaw/__version__.py`

Example:

```python
__version__ = "0.0.8"
```

Validate version format:

```bash
python -c "from packaging.version import Version; from copaw.__version__ import __version__; Version(__version__); print(__version__)"
```

## 3. Local Build Smoke Test (Recommended)

Build wheel and sdist with bundled console frontend:

```bash
bash scripts/wheel_build.sh
ls -lh dist/
```

Optional Docker smoke build:

```bash
bash scripts/docker_build.sh copaw:release-smoke
```

## 4. Commit and Merge

```bash
git checkout main
git pull origin main
git add src/copaw/__version__.py
git commit -m "chore(release): bump version to X.Y.Z"
git push origin main
```

## 5. Create GitHub Release

Create a tag and publish release (recommended via `gh`):

```bash
gh release create vX.Y.Z \
  --title "Release vX.Y.Z" \
  --notes "Release notes for vX.Y.Z"
```

For pre-releases:

```bash
gh release create vX.Y.Z-rc.1 \
  --title "Release vX.Y.Z-rc.1" \
  --notes "Pre-release notes" \
  --prerelease
```

## 6. Monitor Automation

After release is published, verify workflows:

```bash
gh run list --workflow publish-pypi.yml -L 1
gh run list --workflow docker-release.yml -L 1
gh run list --workflow desktop-release.yml -L 1
```

If a workflow fails:

```bash
gh run view <RUN_ID> --log
```

## 7. Post-release Verification

1. PyPI package is available and installable.
2. Docker tags are available:
   - `agentscope/copaw:vX.Y.Z`
   - `agentscope/copaw:pre`
   - `agentscope/copaw:latest` (non-pre-release only)
3. GitHub Release assets include:
   - `CoPaw-Setup-*.exe`
   - `CoPaw-*-macOS.zip`

## 8. Version Semantics Notes

Docker tag behavior is controlled in `.github/workflows/docker-release.yml`:

- `beta`, `alpha`, `rc`, `dev`: treated as pre-release (`pre` tag only).
- `.post`: treated as stable patch release (updates `latest`).
- Otherwise, fallback to GitHub release `prerelease` flag.

## 9. Roll-forward Strategy

If a bad release is published:

1. Fix on `main`.
2. Bump to next patch or `.post` version.
3. Create a new GitHub Release.

Avoid deleting published package versions from public registries unless strictly necessary.

## 10. Maintainer Checklist Template

Use the release issue template to track each release execution:

- `.github/ISSUE_TEMPLATE/6-release_checklist.md`
