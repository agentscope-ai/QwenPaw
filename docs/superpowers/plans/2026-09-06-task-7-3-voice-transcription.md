# Task7.3 语音转写配置与使用实施计划

> 使用subagent-driven-development。用户禁止提交/分支/worktree/清理；在原目录按任务事前快照生成独立diff。具体契约见同日期design spec，总计划纵向7.3已获用户启动确认。

## Task1 后端治理、调用和音频生命周期

文件：workspace.py及必要的独立voice服务模块、audio_transcription.py、config/config.py、agent_context.py；console.py与附件引用/消息绑定最小适配、message_processing.py的派生音频清理、models/runtime.py及必要治理状态检查。仅对语音安全直接相关的旧日志出口补权限，不重构调试平台。新增文件是为避免继续扩大workspace路由和复用运行逻辑。

- [x] 先写真实HTTP权限失败用例，覆盖admin/member及Agent owner/collaborator/user、旧路由/别名、无权/只读会话。
- [x] 实现安全配置/状态/测试DTO，联合保存、旧端点门禁、模型选择、不可变调用快照、Secret与异常投影。
- [x] 临时音频受控目录/大小/取消/清理；聊天audio.data归属校验和消息绑定、派生文件清理，保留原附件与native语义。
- [x] 本地模型缓存与就绪边界，远程客户端关闭及失败码；已登记模型/供应商状态和引用保护。
- [x] 跑原相关回归及新增隔离测试，输出before/diff/真实命令报告并独立审查。

## Task2 原页面与Chat转写闭环

文件：VoiceTranscription页面/hooks/cards，api/modules/agent.ts及必要独立voice API/hook，WhisperSpeechButton、Chat/index.tsx的最小接入、OS SettingsApp权限、zh/en文案和对应测试。与Task1无共享写文件，可按冻结DTO并行实施；不修改公共request.ts的既有认证保证。

- [x] 先写管理员设置/模型/测试、仅使用者录音、上传转文字和身份/Agent/会话切换失败用例。
- [x] 原设置联合保存与安全状态，录音/上传共用scope、取消和错误逻辑；保留普通附件及草稿不自动发送。
- [x] 页面和OS设置权限一致；当前sender定位，卸载与等待麦克风授权的迟到清理。
- [x] 跑前端相关测试、实际app/node tsc，独立diff与审查；完整build留交付阶段。

## Task3 集成与真实浏览器交付

主流程拥有 e2e/tests/test_voice.py 的必要改造、隔离联调脚本、最终文档及真实部署，不与实现者共写。

- [x] 全任务独立整体审查与必要集中修复，验证角色、附属入口、配置与临时数据边界。
- [x] 构建；隔离loopback Whisper真实multipart接收与Chrome录音/上传/回填、管理测试、拒绝和迟到结果验证；保留既有e2e功能意图，修正旧路径和宽泛断言，不触发默认e2e清理钩子。
- [x] 原18089原目录部署，确认配置/Secret/模型表/已有技能保真；不迁移真实schema。
- [x] 更新验收报告和总计划；明确未测真实ASR/本地依赖、既有警告、未提交；不自动进入8.1。

## 基线

- `tmp/task73-run-backend.py`运行audio_transcription、workspace_router、channels voice与voice contract四文件：124 passed、1既有Starlette warning，2.16s，exit0。
- `npm run test:run -- src/api/modules/agent.test.ts`：17 passed，exit0。
- 本机whisper模块与ffmpeg均不可用，仅作依赖现状，不调用模型下载或真实供应商。
