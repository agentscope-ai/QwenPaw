# Task 7.1 / 1 管理入口与不可回读凭据

## 要求与范围

仅实现供应商/模型/本地运行时/OAuth 配置管理入口鉴权与任何角色不可回读已存 Secret。不要实施 model_grants、用户目录授权、会话模型覆盖或真实数据迁移，这些是下一任务。保留当前 GET /models 被聊天和 Agent 编辑使用的兼容路径；本任务先确保响应不含明文凭据，Task 2 再拆用户目录。未完成整个7.1时不宣称用户模型授权已完备。

复用 src/qwenpaw/app/routers/providers.py 的 _require_global_model_manage 与现有 Capability.MODELS_MANAGE；检查 local_models.py、provider_oauth.py 的实际管理入口及统一路由注册，管理读和写都需后端授权，但临时兼容目录 GET /models 不能全局加admin导致现有使用页面不可用。共享应用/publication 不在本任务。

## 文件边界

- src/qwenpaw/app/routers/providers.py、local_models.py、provider_oauth.py：请求身份与响应边界。
- 新增 src/qwenpaw/providers/api_projection.py（如需）：纯响应投影与错误脱敏，不修改 ProviderManager 运行时凭据实例。
- src/qwenpaw/providers/provider.py 与 provider_manager.py：仅必须的显式凭据更新语义；不要全模块重构。
- console/src/pages/Settings/Models/useProviders.ts 与 components/modals 中实际凭据表单、console/src/api/types/provider.ts（先核实实际文件路径）：管理员修改入口保真。
- 新增 tests/isolation/test_model_governance.py；相关模型配置前端测试及现有providers单元测试。

## TDD 步骤

1. 检查完整路由及现有测试fixture；先以合成ProviderInfo和真实HTTP入口构造以下失败用例，不用mock权限返回值：

```python
def assert_secret_absent(response, secret):
    assert secret not in response.text

# 每个管理入口：普通主体403且Manager配置没有变化；管理员可达。
# 管理员/普通用户 GET /models 与配置保存响应不包含合成api_key/auth_token。
# custom_headers Authorization、带凭据URL、连接错误嵌入secret也不能回读。
# 未提交secret保留；提交新值替换；明确清除删除；掩码不能被写成真实密钥。
```

2. 运行 `.venv/Scripts/python.exe -m pytest tests/isolation/test_model_governance.py -q --tb=short`，保存预期失败证据。无需访问实际供应商。
3. 最小修改复用授权能力，投影复制数据而非改动共享Provider实例；区分保存输入与返回DTO。日志/错误不要包含原请求体或凭据。Legacy保留管理能力，Secret不可回读仍生效。
4. 前端针对旧密钥不回填、空输入不误清空、新密钥替换和显式清除编写失败测试，再修改对应表单/序列化。仅使用现有文案风格；不要重做页面。
5. 定向回归并记录命令/结果。列出未改的使用目录、会话覆盖依赖，不能把下一任务缺口算作已完成。

## 交付

完整报告写 docs/superpowers/plans/2026-09-06-task-7-1-task-1-report.md，含RED/GREEN、变更文件、接口变化、关注点。返回简短 DONE / DONE_WITH_CONCERNS / NEEDS_CONTEXT / BLOCKED。

## 强制约束

在现有 E:/git_project/QwenPaw 脏工作区先读后写。禁止git提交/暂存/分支/工作树/清理，禁止服务重启、真实配置变更、读取输出真实密钥、真实网络探测、安装依赖或数据库结构/数据迁移。apply_patch UTF-8。业务逻辑调试不需Context7；如果涉及框架具体API变更，依用户要求查Context7原始文档。发现设计决策或跨任务依赖必须先询问主流程。
