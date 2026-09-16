# Personal Library Mentions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为聊天增加安全、确定性的个人资料库 `@` 文件引用能力。

**Architecture:** 前端候选组件保存文档 ID，Console 请求通过结构化字段提交引用；后端使用认证用户和当前 Agent 重新校验并读取内容，在调用模型前追加只读上下文。个人资料库文件不转换成工作区路径。

**Tech Stack:** React、TypeScript、Lexical、FastAPI、Pydantic、pytest、Vitest。

## Global Constraints

- 当前用户与当前 Agent 授权必须在后端逐次校验。
- 单次最多 5 个文本文件，每个最多 65,536 字节。
- 不修改数据库结构，不迁移或删除现有文件。
- 所有生产代码先有失败测试，再最小实现。

---

### Task 1: 后端可信引用解析

**Files:**
- Modify: `src/qwenpaw/app/routers/console.py`
- Modify: `src/qwenpaw/personal_library/service.py`
- Test: `tests/unit/app/routers/test_console_personal_library_references.py`

**Interfaces:**
- Consumes: `PersonalLibraryService.read_text_for_agent(owner_user_id, agent_key, document_id)`
- Produces: `_resolve_personal_library_references(request, workspace, native_payload)`

- [ ] 写失败测试：当前用户有效引用被解析为只读上下文。
- [ ] 写失败测试：另一用户文档 ID、撤销授权和超过 5 个引用均被拒绝。
- [ ] 运行测试，确认因解析函数不存在而失败。
- [ ] 最小实现解析与结构化上下文注入。
- [ ] 运行后端相关测试并确认通过。

### Task 2: 前端引用协议与候选组件

**Files:**
- Create: `console/src/pages/Chat/PersonalLibraryMentionMenu.tsx`
- Create: `console/src/pages/Chat/personalLibraryMentions.ts`
- Modify: `console/src/pages/Chat/RichFileReferenceInput.tsx`
- Modify: `console/src/pages/Chat/index.tsx`
- Modify: `console/src/pages/Chat/fileReferenceFormatting.ts`
- Modify: `console/src/api/modules/personalLibrary.ts`
- Test: `console/src/pages/Chat/PersonalLibraryMentionMenu.test.tsx`
- Test: `console/src/pages/Chat/personalLibraryMentions.test.ts`

**Interfaces:**
- Produces: `PersonalLibraryMention { documentId: string; name: string }`
- Produces: `extractPersonalLibraryDocumentIds(value: string): string[]`
- Consumes: `personalLibraryApi.list()`

- [ ] 写失败测试：输入 `@` 显示当前资料库文本文件并支持文件名筛选。
- [ ] 写失败测试：选中候选生成带文档 ID 的原子引用，删除后 ID 消失。
- [ ] 运行测试并确认缺少组件/协议而失败。
- [ ] 实现候选菜单、键盘交互和引用序列化。
- [ ] 将 ID 写入聊天请求的 `request_context.personal_library_document_ids`。
- [ ] 运行前端单测与 TypeScript 检查。

### Task 3: 构建部署与浏览器隔离验收

**Files:**
- Build output: `console/dist/`

**Interfaces:**
- Consumes: 前两项完整行为。

- [ ] 运行后端资料库、Console 路由和隔离测试。
- [ ] 运行前端 @ 引用、输入框和聊天请求测试。
- [ ] 构建前端并重启 18089 服务。
- [ ] 浏览器用管理员账号验证 `@AI写作需求文档.md` 被精准读取且不扫描工作区。
- [ ] 浏览器/API 用第二用户验证候选和伪造引用均无法访问管理员文档。

