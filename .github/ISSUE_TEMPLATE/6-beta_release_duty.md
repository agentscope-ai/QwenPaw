---
name: Beta Release 安装验证值班
about: Beta 版本发布后，由值班同学验证各平台安装情况（通常由 Action 自动创建）
title: "[Release Duty] QwenPaw vX.X.X Beta 安装验证"
labels: ["release-duty", "beta"]
assignees: []
---

## 版本信息

- **Release 版本：** vX.X.X
- **Release 链接：** https://github.com/agentscope-ai/CoPaw/releases/tag/vX.X.X
- **值班截止时间：** Release 发布后 4 小时内完成

## 验收标准

每个平台需通过以下所有检查点：
- **安装**：按文档步骤安装，无报错退出
- **启动**：服务/应用正常启动，界面可访问
- **配置模型**：在 UI 中填入 API Key 并选择模型，配置保存成功
- **基础对话**：发送一条消息，收到正常回复（非报错）

---

## PyPI

**安装命令：**
```bash
python -m venv /tmp/qwenpaw-test && source /tmp/qwenpaw-test/bin/activate
pip install qwenpaw==X.X.X
qwenpaw
```

- [ ] 安装成功（`pip install` 无错误）
- [ ] 启动成功（`qwenpaw` 命令正常启动，浏览器可访问）
- [ ] 配置模型成功（填入 API Key，选择模型，保存无报错）
- [ ] 基础对话成功（发送消息，收到正常回复）

**验证环境：**
- OS：
- Python 版本：
- 备注：

---

## Docker

**安装命令：**
```bash
docker run --rm -p 7860:7860 agentscope/qwenpaw:X.X.X
```

- [ ] 拉取镜像成功（`docker pull` 无错误）
- [ ] 启动成功（容器正常运行，`http://localhost:7860` 可访问）
- [ ] 配置模型成功（填入 API Key，选择模型，保存无报错）
- [ ] 基础对话成功（发送消息，收到正常回复）

**验证环境：**
- OS：
- Docker 版本：
- 架构（amd64/arm64）：
- 备注：

---

## macOS Desktop

**安装步骤：**
1. 前往 [Release 页面](https://github.com/agentscope-ai/CoPaw/releases/tag/vX.X.X)
2. 下载 `QwenPaw-X.X.X-macOS.zip`
3. 解压，将 `QwenPaw.app` 拖入应用程序文件夹
4. 打开应用

- [ ] 下载并解压成功
- [ ] 启动成功（应用正常打开，无崩溃）
- [ ] 配置模型成功（填入 API Key，选择模型，保存无报错）
- [ ] 基础对话成功（发送消息，收到正常回复）

**验证环境：**
- macOS 版本：
- 芯片（Apple Silicon / Intel）：
- 备注：

---

## Windows Desktop

**安装步骤：**
1. 前往 [Release 页面](https://github.com/agentscope-ai/CoPaw/releases/tag/vX.X.X)
2. 下载 `QwenPaw-Setup-X.X.X.exe`
3. 双击安装，按向导完成
4. 启动 QwenPaw

- [ ] 下载并安装成功（安装向导无报错）
- [ ] 启动成功（应用正常打开，无崩溃）
- [ ] 配置模型成功（填入 API Key，选择模型，保存无报错）
- [ ] 基础对话成功（发送消息，收到正常回复）

**验证环境：**
- Windows 版本：
- 备注：

---

## 最终结论

| 平台 | 结果 | 值班人 |
|------|------|--------|
| PyPI | ⬜ PENDING | |
| Docker | ⬜ PENDING | |
| macOS Desktop | ⬜ PENDING | |
| Windows Desktop | ⬜ PENDING | |

**全部 PASS：** 关闭本 Issue，打 `verified` 标签，Release 正常推进。

**有 FAIL：** 在评论中附上复现步骤和日志，打 `installation-bug` 标签，@maintainer 决策是否阻断。
