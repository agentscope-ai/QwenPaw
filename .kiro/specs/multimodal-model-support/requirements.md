# 需求文档：多模态模型支持

## 简介

CoPaw 当前仅在模型返回 400 错误时被动地剥离媒体内容块（图片、音频、视频）。本功能旨在为模型和供应商引入主动的多模态能力标识，使系统在发送请求前即可判断当前模型是否支持多模态输入，从而实现前端 UI 自适应、内容主动过滤和优雅降级。

## 术语表

- **ModelInfo**: 模型信息数据模型，包含模型 ID 和名称，定义于 `src/copaw/providers/models.py` 和 `src/copaw/providers/provider.py`
- **ProviderInfo**: 供应商信息数据模型，包含供应商配置和模型列表，定义于 `src/copaw/providers/provider.py`
- **Provider**: 供应商抽象基类，提供连接检查、模型获取等接口
- **ProviderManager**: 供应商管理器，管理所有内置和自定义供应商的单例类
- **ReactAgent**: 响应式智能体，定义于 `src/copaw/agents/react_agent.py`，包含当前的被动媒体回退逻辑
- **MediaBlock**: 消息中的媒体内容块，类型包括 image、audio、video
- **Console**: 前端控制台界面，用户通过该界面与智能体交互并上传文件
- **CapabilityFlag**: 能力标志，用于标识模型是否支持特定功能（如多模态输入）

## 需求

### 需求 1：模型多模态能力标识

**用户故事：** 作为开发者，我希望每个模型都有明确的多模态支持标识，以便系统能在调用前判断模型是否支持图片、音频、视频等媒体输入。

#### 验收标准

1. THE ModelInfo SHALL 包含一个 `supports_multimodal` 布尔字段，默认值为 `false`
2. THE ModelInfo SHALL 包含 `supports_image` 和 `supports_video` 布尔字段，默认值为 `false`，用于细粒度标识各媒体类型的支持情况
3. THE ProviderInfo SHALL 在其 `models` 和 `extra_models` 列表中的每个 ModelInfo 实例上暴露上述能力字段
4. WHEN 用户通过 API 添加自定义模型时，THE ProviderManager SHALL 允许用户指定该模型的多模态能力值
5. THE ProviderManager SHALL 将多模态能力字段持久化到供应商配置文件中

### 需求 2：主动媒体内容过滤

**用户故事：** 作为用户，我希望系统在发送消息前自动过滤不支持的媒体内容，而不是等到模型报错后再处理。

#### 验收标准

1. WHEN 当前激活的模型的 `supports_multimodal` 值为 `false` 时，THE ReactAgent SHALL 在构建请求前移除消息中的所有 MediaBlock
2. WHEN ReactAgent 主动移除了 MediaBlock 时，THE ReactAgent SHALL 记录一条警告日志，说明已移除的媒体块数量和类型
3. WHILE 当前激活的模型的 `supports_multimodal` 值为 `true` 时，THE ReactAgent SHALL 保留消息中的所有 MediaBlock 不做修改
4. THE ReactAgent SHALL 保留现有的被动媒体回退逻辑作为兜底机制，以处理能力标识不准确的情况

### 需求 3：前端能力感知

**用户故事：** 作为用户，我希望前端界面能根据当前模型的多模态能力自动调整，避免我上传模型无法处理的文件。

#### 验收标准

1. THE Provider API SHALL 在 ModelInfo 响应中包含 `supports_multimodal`、`supports_image`、`supports_video` 字段
2. WHEN 当前激活的模型不支持多模态时，THE Console SHALL 向用户展示文件上传功能不可用的视觉提示
3. WHEN 当前激活的模型支持图片但不支持视频时，THE Console SHALL 仅允许上传图片类型的文件
4. WHEN 用户在非多模态模型下尝试上传文件时，THE Console SHALL 显示一条提示信息，说明当前模型不支持媒体输入
5. WHEN 用户切换到支持多模态的模型时，THE Console SHALL 立即恢复文件上传功能的可用状态

### 需求 4：模型能力主动探测

**用户故事：** 作为开发者，我希望系统能自动探测模型的多模态能力，而不需要手动维护能力映射表。

#### 验收标准

1. WHEN 用户激活一个尚未探测过的模型时，THE ProviderManager SHALL 自动发送带最小图片和视频的轻量请求来分别探测该模型的图片和视频支持能力
2. IF 图片探测请求成功，THEN THE ProviderManager SHALL 将该模型的 `supports_image` 设置为 `true`
3. IF 视频探测请求成功，THEN THE ProviderManager SHALL 将该模型的 `supports_video` 设置为 `true`
4. THE ProviderManager SHALL 根据 `supports_image` 和 `supports_video` 的值自动计算 `supports_multimodal` 复合标志
5. THE ProviderManager SHALL 将探测结果持久化到供应商配置文件中，避免重复探测
6. THE Provider API SHALL 提供一个手动触发探测的端点，允许用户在配置页面主动测试模型的多模态能力
7. WHEN 用户在配置页面的模型管理弹窗中点击"测试多模态"按钮时，THE Console SHALL 调用探测 API 并显示各媒体类型的支持结果
8. WHEN 探测完成后，THE Console SHALL 在模型列表中显示能力标签（如图片、视频标签）
9. IF 探测请求因网络超时或其他非媒体相关错误失败，THEN THE ProviderManager SHALL 保持能力字段为 `false`（安全默认），且不阻塞模型激活流程

### 需求 5：优雅降级与错误处理

**用户故事：** 作为用户，我希望即使能力标识有误，系统也能正常工作，不会因为媒体内容导致对话中断。

#### 验收标准

1. IF 一个标记为支持多模态的模型在处理媒体内容时返回错误，THEN THE ReactAgent SHALL 回退到现有的被动媒体剥离逻辑并重试请求
2. WHEN 被动回退成功处理了一个标记为多模态的模型的媒体错误时，THE ReactAgent SHALL 记录一条警告日志，提示该模型的多模态能力标识可能不准确
3. IF 主动过滤和被动回退均失败，THEN THE ReactAgent SHALL 向用户返回清晰的错误信息，说明当前模型无法处理该类型的媒体内容
