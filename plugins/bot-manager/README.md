# Bot 管理器 v1.0.0

统一管理多个智能体的各渠道 Bot 配置。当前支持微信、钉钉，架构可扩展。

## 支持渠道

| 渠道 | 绑定方式 | 特有配置 |
|------|---------|---------|
| 微信 | 扫码二维码 | 私聊策略、群聊策略 |
| 钉钉 | 手动输入凭据 | 消息类型、流式回复、群聊共享、@发送者、卡片模板 |

## 架构设计

### 渠道适配器模式

```
backend/
├── channels.py   ← 渠道适配器注册中心，新增渠道在此注册
└── main.py        ← 统一 API，通过 channel 参数路由到对应适配器

ui/
└── index.js       ← CHANNEL_DEFS 定义各渠道 UI 行为，新增渠道加一条即可
```

### 新增渠道步骤

1. **后端**：在 `channels.py` 中继承 `ChannelAdapter`，实现 `has_credentials()` 和 `get_status_fields()`，调用 `register_channel()`
2. **前端**：在 `index.js` 的 `CHANNEL_DEFS` 中添加渠道定义（名称、图标、绑定方式、表格列、编辑字段）

无需修改其他代码。

### ChannelAdapter 接口

```python
class ChannelAdapter:
    channel_key: str          # 渠道标识，如 "feishu"
    display_name: str         # 显示名称，如 "飞书"
    binding_method: str       # "qrcode" | "manual"
    credential_fields: list   # 凭据字段，清除时置空

    def get_config(agent_config) -> dict      # 从 agent.json 提取渠道配置
    def update_config(agent_config, update)   # 更新渠道配置
    def has_credentials(config) -> bool        # 是否已配置凭据
    def clear_credentials(agent_config)        # 清除凭据
    def get_status_fields(config) -> dict      # 表格展示字段
```

### API 端点

所有 API 以 `{channel}` 为路径参数自动路由：

| 端点 | 方法 | 说明 |
|------|------|------|
| `/channels` | GET | 列出所有支持的渠道 |
| `/{channel}/agents` | GET | 列出智能体配置 |
| `/{channel}/agents/{id}` | GET | 获取单个配置 |
| `/{channel}/agents/{id}/config` | POST | 更新配置 |
| `/{channel}/agents/{id}/toggle` | POST | 切换启用 |
| `/{channel}/agents/{id}/clear-credentials` | POST | 清除凭据 |
| `/{channel}/agents/batch-update` | POST | 批量更新 |
| `/{channel}/status` | GET | 渠道统计 |

## 安装

```
~/.qwenpaw/plugins/bot-manager/
```

重启 QwenPaw 后生效。

## 与旧插件的关系

本插件取代 `wechat-bot-manager` 和 `dingtalk-bot-manager`。
安装本插件后应禁用或删除旧插件以避免冲突。