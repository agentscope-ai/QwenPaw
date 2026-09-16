# Task 7.3 语音转写验收记录

最终状态（2026-09-06）：Task7.3实施、分项和整体审查修复、构建、真实浏览器验收、原18089部署及保真核验均已完成。服务PID60212，schema仍为0015。等待用户验收，不自动进入8.1。

## 范围与实现边界

- 管理员及Legacy沿用语音设置页，联合保存模式、供应商和模型，测试服务器已保存配置。
- 普通用户仅在有使用权的Agent中录音或上传音频转文字，追加当前草稿，不自动发送；切换账户、Agent、会话或sender后不接受旧结果。
- 旧管理接口统一权限；安全状态不暴露供应商配置。音频临时文件按请求隔离，失败、取消及成功后清理。聊天音频附件沿用归属、会话与删除状态校验。
- 复用现有配置、请求和附件系统；无新数据库迁移、核心依赖更新或第二套语音服务。

## 验证与环境

基线后端124项、前端Agent API17项通过。后端初轮相关回归312通过、4失败，修复后限定8通过；后端fix1相关154通过，后台音频3个新增拒绝用例通过。另2个共享会话旧fixture在本次改动前即缺PG配置，已用AST及失败位置核实，不计为通过。前端最终相关集合511项通过，app/node TypeScript通过；build02通过，Monaco CSS检查通过。各任务详细日志与独立before/diff/哈希证据位于 `.superpowers/sdd/2026-09-06-task-7-3-voice-transcription/`。

2026-09-06第八轮Chrome验收退出0、16项检查全部通过，最终报告 `tmp/task73-browser-20260906-201635/acceptance.json`。验证了四账户登录、联合保存/刷新、管理员实际HTTP转写、权限和Agent隔离、上传草稿追加且不发送、MediaRecorder真实录音、上游错误/空结果、Agent切换丢弃迟到结果、关闭与本地依赖缺失，以及音频附件跨用户404和真实PG消息绑定、日志不含合成Secret/上游错误、所有请求音频清理。上传与录音分别监听浏览器POST确认零聊天提交；附件检查关联attachment/message/conversation/run全部归属，匹配当前用户、Agent和session，检查SSE response/completed及run completed。

前四轮保留失败证据：启动探测误用需认证接口、供应商选择器过宽、真实SDK sender-prefix产品缺陷、PG核验线程的asyncio冲突。第五轮通过原16项断言，Task3审查后进一步加强“零发送”和PG完整归属核验；第六轮修正SSE终态类型误判，第七轮通过加强后的断言，第八轮通过最终集中修复后的代码。产品缺陷已由Task2 fix1修复并独立复审；其他为脚本修正。未把失败运行列为通过。

真实Chrome录音与上传验收使用独立PostgreSQL测试schema、工作目录、合成账户和本机Whisper协议测试服务。该验收验证真实multipart上传、SDK调用、界面与权限闭环，不证明真实语音识别准确率。本机缺少Whisper与FFmpeg，未下载模型或安装依赖；本地推理由受控测试替身覆盖，真实环境只验缺失依赖状态。

## 原数据保真

原18089环境的593份技能文件、7份manifest、7份配置/Secret文件和3张模型表已在本任务实施前建立哈希基线。部署后最终核验全部匹配，不公开凭据值。原schema维持0015_skill_governance。证据：`tmp/task73-preservation-before-deploy.json`、`tmp/task73-preservation-after-deploy.json`。

启动时原config.json被补写新增默认字段transcription_local_model=base，首次部署后保真因此失败。已确认只移除该字段、保持原CRLF就精确匹配实施前SHA256；在比较当前文件未被并发修改后原子恢复原字节。最终7份配置/Secret哈希全部一致，恢复后的真实浏览器smoke再次通过。没有更改真实语音选择、模型或凭据。

## 已知限制

真实ASR与本地模型推理未测；同步本地推理取消会等待读取线程结束，未实现硬中止。进程崩溃/强杀后的临时目录自动回收未实现；正常成功、失败、取消终态会清理。本地缓存会淘汰同模型旧权重版本，不删除磁盘模型。

旧ChatPage套件在原Vite配置中排除，显式运行及加载事前快照均16失败（缺少同一mock导出），未纳入511通过项。保留既有Starlette弃用、jsdom伪元素及构建大chunk警告，无本次新增失败冒充基线。

## 交付状态

整体审查的native历史内联P2和本地状态刷新P3均已完成一次集中修复，最终限定复审通过（`final-fix-review.md`）。native附件身份随Msg序列化保存，历史恢复受保护URL并服从分享/删除权限；原文件、推理Base64、派生清理及Legacy保留。最终后端74项针对性测试通过；前端37项针对性测试和tsc通过，保留保存期间的新草稿。最终build03退出0，Monaco CSS检查通过。

Task1三个P2和缓存P3、Task2 sender定位P1均已修复并通过限定复审，后台附件附属入口已补同一resolver。Task3两个验收P2也已修复并通过限定复审。最终代码第八轮Chrome16checks通过：`tmp/task73-browser-20260906-201635/acceptance.json`。

2026-09-06 20:18（Asia/Shanghai）原18089进程49040重启为60212，未迁移schema，旧日志保留，部署记录 `tmp/task73-deployment.json`。实际管理员页面/配置读取、普通用户管理拒绝与安全使用状态共3项smoke通过，恢复原config字节后再次通过（`tmp/task73-deployed-after-restore.log`）。

未执行git提交、推送、分支、worktree或原用户数据清理。八轮独立测试schema/目录保留，测试服务均已终止；原18089正常运行。累计差异和文件哈希见 `task73-final.diff`、`task73-final-delivery.json`，均以本任务最早事前快照为准，不以脏HEAD为基线。
