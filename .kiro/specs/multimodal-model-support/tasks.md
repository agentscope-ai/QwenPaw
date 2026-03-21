# 实施计划：多模态模型支持

## 概述

为 CoPaw 引入主动的多模态能力标识系统。实施顺序：后端数据模型 → 探测器 → Provider 集成 → API 端点 → ReactAgent 主动过滤 → 前端类型与 UI。每一步都在前一步基础上递增构建，确保无孤立代码。

## 任务

- [x] 1. 扩展 ModelInfo 数据模型
  - [x] 1.1 在 `src/copaw/providers/provider.py` 的 ModelInfo 中添加 `supports_multimodal`、`supports_image`、`supports_video` 布尔字段，默认值为 `false`
    - 同步更新 ProviderInfo 中的 models 和 extra_models 类型注解（已为 `List[ModelInfo]`，无需改动）
    - _需求: 1.1, 1.2, 1.3_
  - [x] 1.2 在 `src/copaw/providers/models.py` 的 ModelInfo 中添加相同的三个布尔字段
    - 确保 ProviderSettings 和 CustomProviderData 中的 `models` / `extra_models` 字段自动继承新字段
    - _需求: 1.1, 1.2, 1.5_
  - [x] 1.3 编写属性测试：ModelInfo 默认值不变量
    - **Property 1: ModelInfo 默认值不变量**
    - 生成随机 id/name，不指定 supports_multimodal，验证默认 false
    - **验证: 需求 1.1**
  - [x] 1.4 编写属性测试：ModelInfo 序列化往返
    - **Property 2: ModelInfo 序列化往返**
    - 生成随机 ModelInfo（含随机 bool），序列化后反序列化，验证等价
    - **验证: 需求 1.4, 1.5**

- [x] 2. 检查点 - 确保数据模型测试通过
  - 确保所有测试通过，如有疑问请询问用户。

- [x] 3. 创建多模态能力探测器
  - [x] 3.1 新建 `src/copaw/providers/multimodal_prober.py`
    - 实现 `ProbeResult` 数据类（`supports_image`, `supports_video`, `supports_multimodal` 计算属性）
    - 实现 `probe_image_support(base_url, api_key, model_id, timeout)` 函数，发送带 1x1 PNG 的轻量请求
    - 实现 `probe_video_support(base_url, api_key, model_id, timeout)` 函数，发送带最小视频的轻量请求
    - 实现 `probe_multimodal_support(base_url, api_key, model_id, timeout)` 组合函数
    - 实现 `_is_media_keyword_error(exc)` 辅助函数
    - _需求: 4.1, 4.2, 4.3, 4.4_
  - [x] 3.2 编写单元测试：探测器函数
    - 使用 mock 测试 probe_image_support 成功/失败场景
    - 使用 mock 测试 probe_video_support 成功/失败场景
    - 测试网络超时时返回 false（安全默认）
    - _需求: 4.1, 4.2, 4.3, 4.9_

- [x] 4. Provider 集成探测逻辑
  - [x] 4.1 在 `src/copaw/providers/provider.py` 的 Provider 基类中添加 `probe_model_multimodal` 方法
    - 默认实现返回 `ProbeResult()`（全 false）
    - _需求: 4.1_
  - [x] 4.2 在 `src/copaw/providers/openai_provider.py` 的 OpenAIProvider 中实现 `probe_model_multimodal`
    - 调用 `multimodal_prober.probe_multimodal_support`，传入 `self.base_url` 和 `self.api_key`
    - _需求: 4.1, 4.2, 4.3_
  - [x] 4.3 在 `src/copaw/providers/anthropic_provider.py` 的 AnthropicProvider 中实现 `probe_model_multimodal`
    - 使用 Anthropic messages API 格式发送带 image source 的探测请求
    - _需求: 4.1, 4.2, 4.3_
  - [x] 4.4 在 `src/copaw/providers/gemini_provider.py` 的 GeminiProvider 中实现 `probe_model_multimodal`
    - 使用 Gemini generateContent API 格式发送带 inline_data 的探测请求
    - _需求: 4.1, 4.2, 4.3_

- [x] 5. ProviderManager 探测集成
  - [x] 5.1 在 `src/copaw/providers/provider_manager.py` 中添加 `probe_model_multimodal` 方法
    - 调用 provider 的探测方法，更新对应 ModelInfo 的能力字段
    - 根据 `supports_image` 和 `supports_video` 自动计算 `supports_multimodal`
    - 调用 `_save_provider` 持久化探测结果
    - _需求: 4.2, 4.3, 4.4, 4.5_
  - [x] 5.2 修改 `activate_model` 方法，集成自动探测
    - 模型激活时，若尚未探测过（`supports_multimodal` 为 false 且非本地模型），使用 `asyncio.create_task` 异步触发探测
    - 添加 `_auto_probe_multimodal` 后台方法，探测失败不阻塞激活流程
    - _需求: 4.1, 4.5, 4.9_
  - [x] 5.3 编写属性测试：探测结果持久化
    - **Property 6: 探测结果持久化**
    - 探测后序列化再反序列化，验证 supports_multimodal 值不变
    - **验证: 需求 4.1, 4.2**

- [x] 6. 检查点 - 确保后端探测逻辑测试通过
  - 确保所有测试通过，如有疑问请询问用户。

- [x] 7. 添加探测 API 端点
  - [x] 7.1 在 `src/copaw/app/routers/providers.py` 中添加 `POST /{provider_id}/models/{model_id}/probe-multimodal` 端点
    - 调用 `manager.probe_model_multimodal(provider_id, model_id)`
    - 返回 `{ supports_image, supports_video, supports_multimodal, image_message, video_message }`
    - _需求: 4.6_
  - [x] 7.2 编写属性测试：ProviderInfo 模型字段完整性
    - **Property 3: ProviderInfo 模型字段完整性**
    - 生成随机 ProviderInfo，验证所有 ModelInfo 序列化后包含 supports_multimodal 字段
    - **验证: 需求 1.2, 3.1**

- [x] 8. ReactAgent 主动媒体过滤
  - [x] 8.1 在 `src/copaw/agents/react_agent.py` 中添加 `_get_current_model_supports_multimodal` 方法
    - 从 ProviderManager 获取当前激活模型的 `supports_multimodal` 值
    - 异常时安全返回 `False`
    - _需求: 2.1, 2.3_
  - [x] 8.2 添加 `_proactive_strip_media_blocks` 方法并修改 `_reasoning` 方法
    - 在调用 `super()._reasoning()` 之前，检查 `supports_multimodal`，若为 false 则主动移除媒体块
    - 主动移除时记录警告日志（包含移除数量）
    - 保留现有被动回退逻辑
    - 若模型标记为多模态但仍报错，记录能力标记可能不准确的警告
    - _需求: 2.1, 2.2, 2.3, 2.4, 5.1, 5.2_
  - [x] 8.3 同样修改 `_summarizing` 方法，添加主动过滤逻辑
    - 与 `_reasoning` 相同的主动过滤 + 被动回退 + 错误日志逻辑
    - _需求: 2.1, 2.2, 5.1, 5.2_
  - [x] 8.4 编写属性测试：主动媒体过滤正确性
    - **Property 4: 主动媒体过滤正确性**
    - 生成随机消息内容（含/不含媒体块）+ 随机 supports_multimodal 值，验证过滤行为
    - **验证: 需求 2.1, 2.3**
  - [x] 8.5 编写属性测试：主动过滤日志记录
    - **Property 5: 主动过滤日志记录**
    - 生成随机媒体块数量，对非多模态模型执行过滤，验证日志包含正确数量
    - **验证: 需求 2.2**
  - [x] 8.6 编写属性测试：多模态标记模型的错误回退
    - **Property 7: 多模态标记模型的错误回退**
    - 模拟多模态模型抛出媒体错误，验证回退行为和日志
    - **验证: 需求 5.1, 5.2**

- [x] 9. 检查点 - 确保后端全部测试通过
  - 确保所有测试通过，如有疑问请询问用户。

- [x] 10. 前端 TypeScript 类型与 API 更新
  - [x] 10.1 更新 `console/src/api/types/provider.ts` 中的 ModelInfo 接口
    - 添加 `supports_multimodal: boolean`、`supports_image: boolean`、`supports_video: boolean` 字段
    - 新增 `ProbeMultimodalResponse` 接口
    - _需求: 3.1_
  - [x] 10.2 在 `console/src/api/modules/provider.ts` 中添加 `probeMultimodal` API 调用方法
    - `POST /providers/${providerId}/models/${modelId}/probe-multimodal`
    - _需求: 4.6_

- [x] 11. 配置页面集成探测测试
  - [x] 11.1 在 `console/src/pages/Settings/Models/components/modals/RemoteModelManageModal.tsx` 中添加"测试多模态"按钮
    - 每个模型旁边新增 `EyeOutlined` 图标的"测试多模态"按钮
    - 点击后调用 `probeMultimodal` API，显示 loading 状态
    - 返回结果后显示 message 提示（如"支持: 图片"或"该模型不支持多模态输入"）
    - _需求: 4.7_
  - [x] 11.2 在模型列表项中显示能力标签
    - 已探测过的模型显示 `图片`（蓝色 Tag）、`视频`（紫色 Tag）标签
    - 未支持多模态的模型显示 `纯文本`（默认 Tag），不使用 emoji
    - 探测完成后调用 `onSaved()` 刷新列表
    - _需求: 4.8_

- [x] 12. Console 聊天 UI 文件上传控制
  - [x] 12.1 在 `console/src/pages/Chat/index.tsx` 中根据当前模型能力控制文件上传
    - 获取当前激活模型的 `supports_multimodal`、`supports_image`、`supports_video` 字段
    - `supports_multimodal=false` 时禁用所有媒体上传，显示视觉提示
    - `supports_image=true` 且 `supports_video=false` 时仅允许图片上传
    - 用户切换到支持多模态的模型时立即恢复上传功能
    - _需求: 3.2, 3.3, 3.4, 3.5_

- [x] 13. 更新国际化文案
  - [x] 13.1 在 `console/src/locales/zh.json` 和 `console/src/locales/en.json` 中添加多模态相关文案
    - 添加"测试多模态"、"图片"、"视频"、"纯文本"、探测结果提示等翻译键
    - _需求: 4.7, 4.8_

- [x] 14. 最终检查点 - 确保所有测试通过
  - 确保所有测试通过，如有疑问请询问用户。

## 备注

- 标记 `*` 的任务为可选任务，可跳过以加速 MVP 交付
- 每个任务引用了具体的需求编号以确保可追溯性
- 检查点确保增量验证
- 属性测试使用 Hypothesis 库验证通用正确性属性
- 单元测试验证具体示例和边界情况
