# 四源文件引用与会话恢复实施计划

> 按已确认方案在当前工作目录执行；使用 executing-plans 与测试驱动开发，不创建分支或提交。

**Goal:** 对话支持四源引用、自动识别个人资料库文件名，切页恢复当前会话。

**Architecture:** 后端生成按身份过滤的候选目录；按来源和 ID 重新解析内容。个人资料库自动匹配与显式引用共享授权读取。前端以有效 URL 会话维护用户及 Agent 隔离的最近会话。

**Tech Stack:** Python / FastAPI，React / TypeScript，pytest / Vitest。

## 约束

- Agent 资料仅托管档案。临时附件限定当前会话或未绑定会话。
- 私人资料、产物按当前用户隔离；引用不增加写权限。
- 拒绝伪造内容、越权 ID、路径穿越、失效及撤销授权引用。
- 保留旧 personal-library 引用格式兼容；新引用带来源，避免同名错配。
- 数据目录保持英文；不迁移或删除现有用户数据。

## 1. 后端目录与解析

- [x] 在 tests/unit/app/routers/test_console_personal_library_references.py 验证自然文件名、歧义和授权边界，先观察失败。
- [x] 在 personal_library/service.py 增加授权目录和归一化名称匹配；console.py 复用授权读取。
- [x] 新建 app/chat_file_references.py：四源目录与解析；请求仅接受 source/id，服务端生成内容。
- [x] 测试四源解析、伪造来源、其他用户/Agent/会话、删除和路径逃逸。

## 2. 前端引用

- [x] 新建 Chat/fileMentions.ts 与测试：来源标识、稳定 token、最后一条用户消息提取。
- [x] Chat/index.tsx 使用统一目录，显示来源，切 Agent/会话清空选择，重新打开菜单刷新目录。
- [x] 发送 file_references，由后端再次鉴权；保留旧格式兼容。

## 3. 当前会话

- [x] 添加会话选择后离开再返回的回归测试。
- [x] ChatSessionInitializer 对有效 URL 匹配会话持久化，Sidebar 使用该 Agent 最近会话。
- [x] 验证 Agent 切换和临时会话 ID 不互相覆盖；复用现有用户隔离存储。

## 4. 验证与交付

- [x] 运行关联 pytest / Vitest 和前端构建。
- [x] 部署当前服务实际使用的前端资源，必要时使用现有启动脚本重启 18089。
- [x] 浏览器验证菜单与切菜单恢复会话；自然匹配已确认进入运行上下文，记录结果和限制。
- [ ] 模型上游恢复后，补验不使用 @ 的完整模型回答（当前 503 usage_limit_reached）。

## 审计与未完成项

详见同目录 `2026-09-05-unified-chat-files-verification.md`。通用工具层的强用户隔离仍有独立风险，不因本次引用接口修复而视为完成。
