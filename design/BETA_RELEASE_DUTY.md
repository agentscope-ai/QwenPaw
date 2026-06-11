# Beta Release 安装验证值班制度

## 背景与目标

QwenPaw 在 GitHub 上以 Release 形式对外发布，包括正式版和 beta 版。
Beta 版是用户最先接触到的版本，安装体验直接影响用户印象。

**目标：** 每次发布 beta 版本时，由值班同学覆盖所有主流安装方式，确保用户
能完成"安装 → 启动 → 配置模型 → 基础对话"这条最短路径。

---

## 验收标准（Pass/Fail）

对于每个平台，必须同时满足以下 4 个检查点，才算通过：

| 检查点 | 具体动作 |
|--------|----------|
| 安装   | 按文档步骤安装，无报错退出 |
| 启动   | 服务/应用正常启动，界面可访问 |
| 配置模型 | 在 UI 中填入 API Key 并选择模型，配置保存成功 |
| 基础对话 | 发送一条消息，收到正常回复（非报错） |

**任意一项失败 → 该平台标记为 FAIL → 立刻在 Issue 中 @maintainer 阻断。**

---

## 覆盖平台

| 平台 | 安装方式 | 验证环境要求 |
|------|----------|-------------|
| **PyPI** | `pip install qwenpaw==<version>` | Python 3.10+，干净 venv |
| **Docker** | `docker run agentscope/qwenpaw:<version>` | Docker Desktop / Linux daemon |
| **macOS Desktop** | GitHub Release 下载 `.zip`，解压运行 | macOS 13+（Apple Silicon / Intel 均可） |
| **Windows Desktop** | GitHub Release 下载 `.exe`，安装运行 | Windows 10/11 64-bit |

---

## 协作机制：GitHub Issue 值班制

### 整体流程

```
Beta Release 发布
       │
       ▼
GitHub Actions (beta-release-duty.yml)
  自动创建 Duty Issue
  - 标题：[Release Duty] QwenPaw <version> Beta 安装验证
  - 内容：各平台 checklist
  - 标签：release-duty / beta
  - 按 roster 自动分配当日值班人
       │
       ▼
值班人收到 GitHub 通知
  逐一验证各平台，勾选 checklist
       │
    ┌──┴──┐
   PASS  FAIL
    │       │
    ▼       ▼
关闭 Issue  评论详情 + @maintainer
            阻断发布公告
```

### Issue 生命周期

- **创建**：Release Action 触发后 5 分钟内自动创建
- **截止时间**：Release 发布后 **4 小时** 内完成（写在 Issue 标题/body 里）
- **关闭条件**：4 个平台全部 PASS，值班人手动关闭并打 `verified` 标签
- **失败处理**：评论说明复现步骤，打 `installation-bug` 标签，@maintainer 决策

---

## 值班名单

配置文件：`.github/beta-duty-roster.yml`

```yaml
# 按顺序轮转，每次 beta release 用下一个
rotation:
  - github: alice
    name: Alice
  - github: bob
    name: Bob
  - github: charlie
    name: Charlie
```

GitHub Actions 根据 release 编号对名单取模，自动 assign 到当前值班人。
如需临时换班，直接在 Issue 里手动 re-assign 即可。

---

## 文件清单

```
.github/
├── beta-duty-roster.yml              # 值班名单（轮转配置）
├── ISSUE_TEMPLATE/
│   └── 6-beta_release_duty.md       # 手动创建时用的模板（备用）
└── workflows/
    └── beta-release-duty.yml        # 自动创建 Duty Issue 的 Action
```

---

## GitHub Actions 设计

**触发条件：**
- `release.published` + (`prerelease == true` 或 tag 含 `beta`/`alpha`/`rc`)

**权限需求：**
- `issues: write`（创建并 assign issue）
- `contents: read`（读 roster 文件）

**步骤：**
1. 读取 `.github/beta-duty-roster.yml`，计算当前值班人
2. 用 `actions/github-script` 调用 GitHub API 创建 Issue
3. Issue body 包含版本号、安装命令、4 个平台 checklist、截止时间

---

## 值班人操作手册

### 1. 收到通知

GitHub 会通过邮件/通知中心提醒你被 assign 了一个 Issue。
Issue 链接格式：`https://github.com/agentscope-ai/CoPaw/issues/xxxx`

### 2. 验证 PyPI

```bash
# 用干净的虚拟环境
python -m venv /tmp/qwenpaw-test && source /tmp/qwenpaw-test/bin/activate
pip install qwenpaw==<VERSION>
qwenpaw
# 浏览器打开 http://localhost:xxxx，配置模型，发条消息
```

### 3. 验证 Docker

```bash
docker run --rm -p 7860:7860 agentscope/qwenpaw:<VERSION>
# 浏览器打开 http://localhost:7860，配置模型，发条消息
```

### 4. 验证 macOS Desktop

1. 前往 GitHub Release 页面，下载 `QwenPaw-<VERSION>-macOS.zip`
2. 解压，双击 `QwenPaw.app`
3. 配置模型，发条消息

### 5. 验证 Windows Desktop

1. 前往 GitHub Release 页面，下载 `QwenPaw-Setup-<VERSION>.exe`
2. 双击安装，完成后启动
3. 配置模型，发条消息

### 6. 填写结果

在 Issue 的 checklist 中勾选已通过项。
如有失败，回复评论（附截图/日志），打标签 `installation-bug`，@maintainer。

### 7. 通过后关闭

所有平台 PASS → 在评论中填写实际环境信息 → 关闭 Issue 并打 `verified` 标签。

---

## FAQ

**Q: 我没有 Windows 机器怎么办？**
A: 在值班表里标注你缺少的平台，roster 配置时可以指定每个人负责的平台子集。
当前简单实现是全平台轮转，后续可按平台分组。

**Q: Docker 镜像还没推上去怎么办？**
A: Docker Release Action 和 PyPI Action 并行，一般 30 分钟内完成。
如果超时，在 Issue 评论说明等待状态，不要强行关闭。

**Q: 发现问题要等修复好才能关闭 Issue 吗？**
A: 不，Issue 记录的是"验证结果"，不是修复跟踪。
发现 FAIL → 记录详情 → 创建新 bug issue 关联 → 由 maintainer 决策是否推迟发布。

**Q: 正式版（non-prerelease）需要值班吗？**
A: Action 只在 prerelease 触发，正式版通常从 beta 升级，风险较低。
但如果团队认为有必要，可以修改 Action 的触发条件覆盖正式版。
