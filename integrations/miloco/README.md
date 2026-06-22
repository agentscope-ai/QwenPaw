# Xiaomi Miloco 全屋智能集成

将 [Xiaomi Miloco](https://github.com/XiaoMi/xiaomi-miloco) 全屋智能系统接入 QwenPaw，让你的 AI 助理能感知家庭环境、控制米家设备、做出智能决策。

## 架构

```
小米设备 (93+ 台灯/窗帘/空调/音箱/传感器)
    │  Mi Home Cloud / LAN
    ▼
Miloco 后端 (:1810)
    │  POST /miloco/webhook { action: "agent"|"get_trace" }
    ▼
Webhook 桥接器 (:18789)
    │  qwenpaw agents chat --to-agent miloco
    ▼
QwenPaw Miloco Agent
    │  16 个技能：设备控制、场景、感知、规则、通知...
    └── AI 决策 → 返回 → 设备执行
```

## 快速开始

### 前提

- QwenPaw 已部署运行
- 小米账号和米家设备
- Linux 宿主机（推荐 `--net=host` 网络模式以支持摄像头）

### 1. 安装 Miloco

```bash
git clone https://github.com/XiaoMi/xiaomi-miloco.git
cd xiaomi-miloco
bash scripts/install.sh --dev --skip-openclaw --agent-prepare
```

### 2. 创建 QwenPaw Agent

```bash
# 创建 Miloco 主 Agent
qwenpaw agents create --name "Miloco" --agent-id miloco

# 创建桥接 Agent
qwenpaw agents create --name "Miloco Bridge" --agent-id miloco-bridge
```

### 3. 部署 Agent 技能和配置

将本目录下的 workspace 文件复制到 QwenPaw 的 miloco agent workspace：

```bash
cp integrations/miloco/workspace/* /app/working/workspaces/miloco/
```

包含：
- `SOUL.md` — Agent 身份定义
- `AGENTS.md` — 行为准则和工具指南
- `skills/` — 16 个技能（设备控制、场景管理、感知查询、规则引擎等）

### 4. 配置 API Key

```bash
miloco-cli config set model.omni.api_key <your-deepseek-or-openai-key>
miloco-cli config set model.omni.model deepseek/deepseek-chat
miloco-cli config set model.omni.base_url https://api.deepseek.com/v1
```

### 5. 绑定小米账号

```bash
miloco-cli account bind
# 浏览器打开提示的 URL，扫码授权
```

### 6. 启动服务

```bash
# 启动 Webhook 桥接器
python3 xiaomi-miloco/scripts/qwenpaw_webhook_bridge.py &

# 启动 Miloco 后端
miloco-cli service start
```

### 7. 验证

```bash
# 检查设备列表
miloco-cli device list

# 测试 Agent 互通
qwenpaw agents chat --from-agent miloco-bridge --to-agent miloco --text "列出所有在线设备"

# 验证桥接器
curl -X POST http://127.0.0.1:18789/miloco/webhook \
  -H "Content-Type: application/json" \
  -d '{"action":"get_trace","payload":{"runId":"test"}}'
```

## 可用功能

| 功能 | 说明 | 示例 |
|------|------|------|
| 设备控制 | 开关灯、调亮度、空调温度等 | "打开客厅筒灯" |
| 状态查询 | 查看设备属性和在线状态 | "书房大灯开着吗" |
| 场景管理 | 执行/创建米家场景 | "开启电影模式" |
| 窗帘控制 | 开关窗帘 | "拉上客厅窗帘" |
| TTS 播报 | 让小爱音箱说话 | "通知家人吃饭" |
| 规则引擎 | 条件触发 + AI 决策 | 水浸报警 → Agent 判断 |
| 设备目录 | 注入 system prompt 的设备清单 | 自动感知环境 |

### 需要 host 网络

| 功能 | 说明 |
|------|------|
| 摄像头截图 | P2P 视频流需直连 |
| 感知查询 | 依赖摄像头帧 |
| 人脸识别 | 依赖本地模型 |

Docker 部署时建议 `--net=host`。如无法使用 host 网络，可运行 `udp_lan_relay.py` 中继解决设备发现问题（摄像头画面仍不可用）。

## Docker 部署

```bash
# 推荐：host 网络模式
docker run -d --name qwenpaw --net=host \
  --restart unless-stopped \
  -v /data/qwenpaw/working:/app/working \
  -v /data/qwenpaw/secret:/app/working.secret \
  -v /data/qwenpaw/backups:/app/working.backups \
  -e QWENPAW_PORT=8088 \
  qwenpaw/qwenpaw:latest
```

## 技术细节

- Webhook 协议兼容 OpenClaw `waitForRun` 格式
- Agent 响应包含 `runId` + `status`，后端自动轮询 `get_trace`
- 技能从 Miloco `plugins/skills/` 迁移，保持功能一致
- 所有文件在 `xiaomi-miloco/` 仓库的 `scripts/` 和 `docs/` 目录
