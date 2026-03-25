# CoPaw 发布指南

本文档描述 CoPaw 的官方发布流程。

## 范围

当 GitHub Release 进入 `published` 状态后，会自动触发以下工作流：

- PyPI 包发布：`.github/workflows/publish-pypi.yml`
- Docker 多架构镜像发布：`.github/workflows/docker-release.yml`
- Desktop 安装包构建并上传：`.github/workflows/desktop-release.yml`

## 1. 发布前置条件

1. 从 `main` 分支发布。
2. 本地质量门禁必须通过：

```bash
pip install -e ".[dev,full]"
pre-commit run --all-files
pytest
```

3. GitHub Secrets 需已配置：
- `PYPI_API_TOKEN`
- `DOCKER_USERNAME`
- `DOCKER_PASSWORD`
- `ALIYUN_ACR_USERNAME`
- `ALIYUN_ACR_PASSWORD`

## 2. 版本号更新

版本号单一来源：

- `src/copaw/__version__.py`

示例：

```python
__version__ = "0.0.8"
```

校验版本号格式：

```bash
python -c "from packaging.version import Version; from copaw.__version__ import __version__; Version(__version__); print(__version__)"
```

## 3. 本地构建冒烟（推荐）

构建包含控制台前端的 wheel + sdist：

```bash
bash scripts/wheel_build.sh
ls -lh dist/
```

可选：Docker 冒烟构建：

```bash
bash scripts/docker_build.sh copaw:release-smoke
```

## 4. 提交并合入

```bash
git checkout main
git pull origin main
git add src/copaw/__version__.py
git commit -m "chore(release): bump version to X.Y.Z"
git push origin main
```

## 5. 创建 GitHub Release

创建 tag 并发布（推荐使用 `gh`）：

```bash
gh release create vX.Y.Z \
  --title "Release vX.Y.Z" \
  --notes "Release notes for vX.Y.Z"
```

预发布版本示例：

```bash
gh release create vX.Y.Z-rc.1 \
  --title "Release vX.Y.Z-rc.1" \
  --notes "Pre-release notes" \
  --prerelease
```

## 6. 监控自动化流程

发布后检查工作流：

```bash
gh run list --workflow publish-pypi.yml -L 1
gh run list --workflow docker-release.yml -L 1
gh run list --workflow desktop-release.yml -L 1
```

如失败，查看日志：

```bash
gh run view <RUN_ID> --log
```

## 7. 发布后验收

1. PyPI 版本可安装。
2. Docker 标签可拉取：
   - `agentscope/copaw:vX.Y.Z`
   - `agentscope/copaw:pre`
   - `agentscope/copaw:latest`（仅正式版）
3. GitHub Release 资产包含：
   - `CoPaw-Setup-*.exe`
   - `CoPaw-*-macOS.zip`

## 8. 版本语义说明

Docker 标签逻辑定义在 `.github/workflows/docker-release.yml`：

- `beta`、`alpha`、`rc`、`dev`：视为预发布，仅更新 `pre`。
- `.post`：视为正式补丁版本，会更新 `latest`。
- 其他情况：回退到 GitHub release `prerelease` 标记。

## 9. 问题版本处理策略（Roll-forward）

若已发布版本存在问题：

1. 在 `main` 修复问题。
2. 递增 patch 或发布 `.post` 版本。
3. 重新创建 GitHub Release。

除非必要，不建议删除公共仓库中已发布版本。

## 10. 维护者检查清单模板

每次发布可使用以下 issue 模板进行过程留痕：

- `.github/ISSUE_TEMPLATE/6-release_checklist.md`