# 发布 QwenPaw

_English: [RELEASING.md](RELEASING.md)_

QwenPaw 一个版本会发布四种产物——**PyPI** wheel、**Docker** 镜像、**桌面**应用
（Tauri，Windows + macOS）和**插件**包。它们由一个统一编排的 workflow 一起发布：
任一产物失败都会拦下整个发布，绝不会出现"Web 版发了、却没有对应桌面版"这种情况。

> 编排器：[`.github/workflows/release.yml`](.github/workflows/release.yml)。
> 旧的按产物拆分的 workflow 作为回退保留——见
> [回退到旧流程](#回退到旧流程)。

## 速览

1. 建一个**草稿** GitHub Release（tag + 说明），**不要**点 *Publish*。
2. Actions → **Release (unified)** → *Run workflow*（`dry_run` 不勾）。
3. 它会构建 + 验证所有产物；只有全部通过，才发布全部产物并把 release 翻成
   *published*。
4. 任一步失败则什么都不发、草稿原样保留——修好后重跑即可。

## 发布流程原理

`release.yml` 分三个阶段：

1. **Resolve（解析草稿）**——按 `tag` 输入找到目标草稿（留空则自动识别唯一草稿），
   把草稿的 `target_commitish` 解析成具体 SHA，并把后续所有 job 钉在该 SHA 上
   （保证*构建的代码 == 发布的代码*）。正式发布时若缺 DashScope secret 会直接 fail。
2. **Prepare（构建 + 验证，不发布任何东西）**——并行：
   - `build-wheel`——构建 Python wheel（含打包好的 console）。
   - `verify-web`——pip 安装、Docker 健康检查、安装脚本三类验证。
   - `build-desktop`——构建 Tauri Windows + macOS 应用，并跑
     安装 → 启动 → 真实问答 的 UI 验证。
   - `build-plugins`——打包插件。
3. **Gate + Publish（门禁 + 发布）**——每个 publish job 都 `needs` **全部** prepare
   job，因此上面任一失败都会跳过整个发布阶段。全绿后：发布 PyPI、推多架构 Docker
   镜像、把桌面安装包挂到 release 并上传 OSS、发布插件——然后**最后一步**才把草稿翻成
   *published*（tag 钉到构建用的 SHA），并创建 Release Duty 验收 issue。

整体约 60–75 分钟，主要耗时在桌面 Tauri 构建。

## 发一个版本

1. **建草稿 Release**
   - UI：Releases → *Draft a new release* → 填 tag + 说明 → **Save draft**
     （**不要** publish）。预发布请勾 *Set as a pre-release*。
   - CLI：
     ```bash
     gh release create v2.0.0-beta.8 --draft --prerelease \
       --target main --title "v2.0.0-beta.8" --notes "..."
     ```
   - tag 应与 `src/qwenpaw/__version__.py` 对应（`resolve` 会用 `packaging` 归一化校验，
     不一致直接 fail；如 tag `v2.0.1-beta.1` 须匹配版本 `2.0.1b1`）。
   - 建议建草稿时用 `--target <sha>` 钉住 commit。若用 `--target main`，则建草稿到运行
     workflow 之间**不要**再往 main 合入，否则构建的是更新后的 main HEAD。
2. **运行 workflow**：Actions → **Release (unified)** → *Run workflow*，选 `main`。
   `tag` 留空可自动识别唯一草稿（也可显式填）；`dry_run` **不勾**。
3. **观察**：成功后 release 翻成 *published*、资产齐全，并开出一个 Release Duty
   issue。失败见 [故障处理](#故障处理)。

## 版本类型：beta / 正式 / post

流程完全一样——类型由 **tag** 推断：

| 类型 | tag 示例 | 草稿勾 pre-release？ | Docker 标签 | PyPI |
|------|----------|---------------------|-------------|------|
| beta / rc / alpha / dev | `v2.0.0-beta.8` | 是 | `<version>` + `pre`（无 `latest`） | 上传；pip 视为预发布（`--pre`） |
| 正式 | `v2.0.0` | 否 | `<version>` + `pre` + `latest` | 正常 |
| post | `v2.0.0.post4` | 否 | `<version>` + `pre` + `latest` | post 版本 |

说明：

- 预发布判定是**基于 tag** 的：tag 含 `beta`/`alpha`/`rc`/`dev` 即为预发布
  （所以用 `-beta.N` 写法）；`stable` 与 `.postN` 会更新 Docker 的 `latest` 标签。
- ⚠️ 桌面 OSS 的 `latest` 文件与 Tauri 自动更新清单目前对**每个**版本（含 beta）
  都会更新（与之前 `desktop-release.yml` 行为一致，本次未改）。让桌面
  `latest`/自动更新只在正式版更新，可作为后续改进。

## 故障处理

**保证**：只有**全部** publish job 成功后，草稿才会被翻成 *published*；任一步失败，
release 就仍是草稿。

| 场景 | 发生了什么 | 怎么办 |
|------|-----------|--------|
| 准备阶段某 job 失败（桌面 / web 验证 / wheel / 插件） | 所有 publish + `finalize` + `duty-issue` 全被 **skip**；什么都没发；草稿不动 | 看失败 job 日志修复（flake 就直接重跑）→ **Re-run failed jobs** 或重跑 workflow。无需清理。 |
| 发布阶段某 publish 失败（如 PyPI 已传、Docker 推失败） | `finalize` 需要全部 publish 成功，故草稿**未翻**；但部分产物可能已上线 | **Re-run failed jobs**（已成功的不会重跑；Docker 重推幂等、OSS 用 `--force`）→ 补齐后自动翻。若某个 PyPI 版本已被占用无法重用，改用 `.postN` 重发。 |
| `finalize` 失败 | 产物都发了但 release 没翻 | 重跑 `finalize`，或手动 `gh release edit <tag> --draft=false --target <sha>`（或 UI 点 *Publish*）。 |
| `duty-issue` 失败 | release 已发布，只是缺验收 issue | 重跑该 job，或用 `tag` 手动 dispatch `release-duty.yml`。不阻塞发布。 |
| `promote-desktop` 失败 | release 已发布，但桌面 `latest` 文件 / 更新清单 / index 未刷新（存量用户的自动更新暂时看不到新版；版本化下载仍可用） | 重跑该 job，幂等（`ossutil cp --force`）。对首装用户不阻塞。 |
| "Multiple draft releases found" | 存在多个草稿 | 重跑 *Run workflow* 时显式填 `tag`。 |
| "No draft release found" / "not a draft" | 没有草稿，或 tag 填错 | 先建草稿 / 改正 tag，再重跑。 |
| resolve 拒绝该 tag（版本不匹配） | 草稿 tag 与 `src/qwenpaw/__version__.py` 不一致 | 让 tag 与版本对齐（`packaging` 归一化，如 `v2.0.1-beta.1` ↔ `2.0.1b1`），再重跑。 |

## 回退到旧流程

旧的按产物拆分的 workflow 是特意保留的。如果编排器坏了，就用旧方式发布——把 GitHub
Release **点 Publish**（或 `gh release create ...`），会在 `release: published` 上触发
`publish-pypi` / `docker-release` / `desktop-release` / `plugins-release`。

> **警告**：旧流程**不会**用桌面构建来 gate Web 发布（这正是本编排器要修的问题），
> 因此仅作应急回退使用。

## Fork / dry-run 测试

运行 **Release (unified)** 时勾 `dry_run: true`，可在**不触及生产**的前提下验证门禁与
草稿→published 翻牌：PyPI 上传、Docker 推送、OSS 上传都变成 no-op，而桌面构建/验证、
草稿翻牌、duty issue 仍会真实执行。（在 fork 上这些只影响 fork 自己的 release 页面。）

注意：桌面构建的 装 → 启 → 问答 UI 验证在 `dry_run` 下**仍会真跑**，需要
`QWENPAW_DASHSCOPE_API_KEY` secret——`dry_run` 只跳过 resolve 阶段的 fail-fast 检查，
不跳过验证本身。
