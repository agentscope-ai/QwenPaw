# Task 7.1 模型治理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. 用户禁止 Git 提交、分支和新工作树；这些要求优先于技能默认流程。

**Goal:** 管理员安全管理模型，普通用户通过安全目录为本人私人会话选择模型，真实运行遵循授权和继承规则。

**Architecture:** 复用 ProviderManager 与 MODELS_MANAGE，区分安全目录和管理员配置投影；复用 ChatManager 和统一模型解析，不从聊天修改 Agent 默认。PG 已有模型治理表，先核实接入，不以另建文件授权表代替，也不自动迁移真实配置。

**Tech Stack:** 现有 Python/FastAPI、PostgreSQL、React/TypeScript、pytest/Vitest、Playwright。

## Global Constraints

- 设计：docs/superpowers/specs/2026-09-06-task-7-1-model-governance-design.md，用户已确认。
- 原目录 E:/git_project/QwenPaw；服务 18089；真实配置、凭据和现有对话不修改，测试只用隔离数据或 TASK71 新会话。
- 不提交、不建分支/工作树、不清理用户数据、不改系统环境或依赖。数据库结构变更及真实批量数据更新须另行明确确认。
- 管理员也不可回读已存明文 Secret；用户目录使用字段白名单。公用 Agent 不等于锁模共享应用。
- 测试先 RED 后 GREEN，独立评审后才能标记完成。保留 Legacy，不扩展技能池和应用发布功能。

## Task 1：管理入口与不可回读凭据

本任务独立简报：docs/superpowers/plans/2026-09-06-task-7-1-task-1-brief.md。

- [x] 建立直接 HTTP 授权与合成密钥泄露的失败测试。
- [x] 补齐供应商、本地运行时和 OAuth 管理入口鉴权；不要阻断合法 OAuth 回调协议。
- [x] 返回只含配置状态的管理员投影，保护配置保存、连接测试和异常响应；未提交/替换/清除语义明确。
- [x] 调整管理员模型编辑 UI 不回填旧密钥并覆盖原功能回归。
- [x] 独立任务评审；记录准确变更、测试和剩余接口依赖。

## Task 2：授权目录与私人会话模型闭环

- [ ] 核实既有 models/model_grants 表与发布模型来源，形成确切接口和测试简报；如果启用需要真实配置迁移，停止部署并请求授权，不默认全量放行。
- [ ] 用户模型目录仅投影获授权可用模型；管理员授权/停用及引用检查复用既有持久化表和配置。
- [ ] 通过 ChatManager 为可信会话更新覆盖，不修改 Agent 默认；对应 GET 回显与新会话草稿隔离。
- [ ] Console 到 runtime 构造前执行服务端授权与统一解析；无效/未授权/停用不降级，共享应用锁定模型优先。
- [ ] 前端选择器改用目录与当前会话覆盖，保留管理员 Agent 默认模型编辑；账户/Agent/会话切换不能复用过期请求。
- [ ] 两用户同一 Agent、刷新、新会话、错误模型、共享应用锁定、公用 Agent 不锁定等测试通过，独立评审。

## Task 3：集成和交付

- [ ] 全任务独立审查；检查 Task 1/2 边界、凭据返回与真实运行一致性。
- [ ] 运行相关后端/前端测试及完整前端构建，记录现存警告，不伪称全平台无漏洞。
- [ ] 保持真实配置只读；双角色浏览器新建 TASK71 会话进行模型选择与刷新验证，需要额外配置授权则明确请求。
- [ ] 更新报告，列清实际验证/未验证；服务保持可验收，不自动推进 7.2。

## 进度账本

- 2026-09-06：书面设计已确认。Task 1 实施中；Task 2 持久化前置只读核实中。无业务代码变更被本计划验收。
- 前置核实结果：既有 model_providers/models/model_grants 仅有 DDL，无业务 Repository/Service；不需新增 Schema，但启用治理需对现有文件模型做受控元数据登记。首次授权范围尚未指定，不能自动全平台放行。主流程暂停请求用户确认“只登记非敏感模型元数据、不改原供应商配置，初始仅管理员可用，管理员明确授权后普通用户可用”；普通用户访问切换应在管理员配置好授权后生效，避免未通知中断。
- Task 1 实现代理 model_governance_implementation 前置核实阶段曾安全暂停；用户已确认受控初始化，现继续同代理实施，不重复派发。授权范围：仅登记非敏感元数据，不复制密钥、不修改原供应商配置、初始不创建普通用户授权；强制校验由管理员明确授权后开启，之前保持兼容状态。尚未执行真实数据库初始化或服务重启。
- Task 2 简报已完成：复用既有表、确定性模型 ID、独立会话覆盖与可信运行校验。公用 Agent 不按共享应用锁模；共享应用发布源尚不存在时不伪称已实现发布闭环。
- 基线验证：effective_model、model_factory_effective_model、providers_model_inheritance 共 11 项通过（pytest，退出码 0）。本计划业务变更仍待分任务评审与集成验收。
- Task 1：实现者第一轮报告 11 项隔离、48 项后端回归、31 项前端测试通过，tsc/compileall 通过；独立评审 model_governance_task1_review 未通过。fix round 1/5 已交回原实现者：URL/非敏感键中已知 Secret 泄露、列表嵌套 Secret 保存丢失、脱敏 URL 回填及 IPv6 保真、空 API Key 错误清除。覆盖用例需补充 RED/GREEN 后限定复审，当前不部署、不进入 Task 2 实施。
- Task 1 minor (deferred)：既有 Starlette/httpx 弃用警告，记录技术债，不安装/升级依赖。最终评审核实未引入新警告。跨任务待核实：路由挂载别名不存在鉴权绕过；安全用户目录及公用 Agent 锁模纠正由 Task 2 承接。
- Task 1：fix round 1/5 复审 2 项通过、3 项未通过（URL path/非绝对 URL 已知 Secret 脱敏，列表删除重排引起凭据错配，对应用例）。fix round 2/5 已派回：无稳定元素标识的含 Secret 列表保持不变可保留原始值，涉及改动则明确拒绝并保留旧配置；不凭位置迁移凭据。URL dirty/IPv6 和空 API Key 协议已通过。
- 主流程限定路由核查：app/_app.py 挂载 api_router，routers/__init__.py 对 providers/local_models/provider_oauth 单点挂载；agent_scoped.py 无重复模型管理挂载。未发现这些模块另有未保护别名；该核查不等同全平台安全审计。
- Task 1: complete（无提交；独立规格/质量 Approved）。fix round 2/5：3 项全部解决、无新增 Critical/Important；隔离测试 20 passed。含隐藏信息列表无可靠元素标识时修改被明确拒绝且不写旧配置；普通列表可编辑。Task 2 实施开始，Task 1 尚未单独部署。
- Task 2 实施代理 model_governance_task2；初步服务 TDD 3 RED→3 GREEN，会话 Repository 保字段/Agent 限定/清除用例已实现。真实 PG 测试库只读确认 qwenpaw-pg / qwenpaw_test_migrations，使用一次性 postgres_test_schema，不触及原库 qwenpaw_test_single_node。首次 PG 断言通过但 Windows loop 退出异常，需干净退出复验，不能据此完成。
- 主流程 Task 1 最终修复后相关 Provider/OAuth/继承回归重新执行：48 passed、退出码 0，1 个既有弃用警告。线上双角色基线已记录于 task-7-1-acceptance.md；当前仍未部署。
- Task 2 阶段状态：授权目录/幂等导入/治理影响预览、PG+Legacy 私人会话覆盖、Console+builder 再校验、前端模型消费者/治理面板已实施，正在综合测试和整理；尚无独立评审，不标记完成。实现者初步 7 项前端/11 项后端定向测试通过；主流程要求补真实组件交互和真实 PG owner/Agent 隔离。PG 若仍有 Windows access-violation 诊断，须保留日志查明，不单凭 exit 0 判清洁。
- Task 2 PG 退出异常已由实现者定位到测试迁移/容器 inspect 在异步 loop 中的生命周期；改为同步 fixture 先执行后，真实 schema 测试 1 passed / exit 0 且无异常诊断。覆盖 owner/Agent 条件更新、管理员不能改别人私人会话、清除、Agent grant 使用权和不存在用户拒绝；最终报告及独立评审待收。
- Task 2 实现报告与44文件专属diff已提交，model_governance_task2_review 独立评审中。实现者报告：相关后端111passed、后增本地删除HTTP文件6passed、PG1passed、前端9passed、tsc/build exit0。4个fork测试已在编辑前基线复现request=None旧错误；原excluded ChatPage整页测试缺旧mock契约尚未通过。它们不计通过，浏览器验收仍待做。
- Task 2 评审未通过，fix round 1/5 已回原代理：ReMe缺可信会话槽/授权复核；AgentModal默认403连带丢授权目录；草稿离开/同路径新建未清理；FORCE RLS可能隐藏其他owner引用并错放删除；另修旧异步失败清新状态Minor。需补ReMe并发/显式、真实运行链路和受RLS角色测试。
- RLS修复约束：不新增Schema/权限架构；事务局部row_security=off用于要求完整可见性，受限查询应显式失败并阻止删除，不伪称绕过RLS。已只读确认既有qwenpaw_runtime为非super/non-BYPASSRLS；测试仅fixture schema和局部role，不新建角色/改变全局role权限。
- ReMe 范围澄清：核实 ReMeLightMemoryConfig / reme_config 没有独立聊天 LLM 槽，本阶段不新增该配置；自动跟随当前会话最终有效槽（含会话显式选择或Agent显式默认），保留现有Embedding/reranker独立配置。缺可信身份的多用户LLM记忆任务不得隐式退Agent默认绕治理。此澄清交回Task2实施者。
- Task 2: complete（无提交，fix round 1/5独立复审全部ADDRESSED，无新增Critical/Important）。ReMe队列authority/独占注入执行、Agent目录默认403独立处理、草稿新建离开清理、RLS失败关闭、过期失败guard均通过限定审查。真实浏览器链路仍属于Task3。
- Task 3 整体审查由model_governance_final_review执行，审查包包含按时序的本任务专属增量。主流程统一前端build新运行exit0，Monaco CSS检查通过；保留既有循环/大chunk和混合导入警告。主流程集成后端复跑中，尚未部署。
- 主流程最终后端集成复跑：184 passed / exit 0，1 个既有Starlette警告，无Windows异常。
- 整体审查发现2项阻塞，已统一派model_governance_final_fix（唯一最终修复波）：P1 /models/active PUT agent默认写仍仅使用权限，需owner/editor配置门控；P2 Legacy meta.model_override缺模型/provider/local删除引用保护。修复后限定复审及双角色浏览器待执行，尚不Ready。
- 最终修复波限定复审 Ready，两项阻断均解决。主流程新运行集成测试 210 passed / exit 0；原服务已重启至 PID 21524 / 18089，原目录不变。管理员页面幂等登记 12 个非敏感模型元数据，原供应商哈希不变，0 用户授权、enforced=false。双角色页面和普通用户私人会话选择/刷新/菜单返回/恢复默认已验证。Task 7.1 本轮交付完成，详细证据及未验证范围见 task-7-1-acceptance.md；不自动推进 7.2，不替管理员开启强制治理。
