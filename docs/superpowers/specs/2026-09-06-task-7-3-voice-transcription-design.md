# 纵向 Task7.3 语音转写配置与使用

用户已要求进入并执行下一项。沿用总计划纵向7.3（旧内部7.5），在原目录实现；Task7.2已交付。保留Legacy、现有录音、音频附件、native/auto处理和草稿行为，不创建分支/提交/工作树，不清理用户数据。

## 权限与事实来源

- 语音转写是管理员启用的全局基础设施。普通用户通过当前Agent使用权消费，owner/collaborator/user均可；历史只读或只读共享会话不可写。用户不得覆盖provider/model/Secret或读取基础设施配置。
- 全局配置继续是现有JSON的agents音频字段；新增本地模型名默认base，不新建PG表或迁移。供应商Secret继续由现有后端Manager读取，响应只投影安全ID/名称/可配置状态，不返回Key、地址、headers或磁盘路径。
- 治理读写与测试复用MODELS_MANAGE；新端点、旧端点及Agent别名均执行相同门禁。Agent使用权不等于平台配置管理权。
- ASR不强套聊天模型逐用户grant；管理员明确选择即启用全局服务。但已登记的供应商/模型停用状态和引用保护不能被绕过；失败不自动换供应商或模型。

## API契约

- `GET /workspace/voice-transcription`（管理员/Legacy）：返回 `settings`（audio_mode、transcription_provider_type、transcription_provider_id、transcription_model、transcription_local_model）、`providers`（id/name/available）、`local_status`（available/ffmpeg_installed/whisper_installed以及安全就绪状态）、`local_models`安全模型名列表。只读不下载模型或联网探测。
- `PUT /workspace/voice-transcription`：body为上述五个settings字段；联合校验后一次保存，失败不部分生效。无加载成功配置不得从前端以默认值覆盖保存。旧单字段接口保留相同权限和校验边界。
- `GET /workspace/transcription-status`（Agent使用者/Legacy）：仅 `{enabled:boolean, available:boolean, reason:string|null}`，不回读类型、provider、model或依赖详情。
- `POST /workspace/transcribe`：继续multipart file，支持可选conversation_id并验证其归属/可写；成功仅 `{text:string}`。全局与Agent别名都解析可信Agent并验权；仅精确转写POST获得运行权限例外。
- `POST /workspace/transcription-test`：仅管理员，使用已保存配置和上传样本，复用转写代码；不能通过表单覆盖provider/model/URL/Key。普通用户不能调用测试入口。
- 错误结构保持 `detail:{code,message}`，保留TRANSCRIPTION_DISABLED/UNSUPPORTED_FILE_TYPE/FILE_TOO_LARGE，增加固定的未就绪、空音频、空文本、超时和上游失败码。完整错误码由后端报告锁定，前端不得展示原始上游响应。

## 运行与文件

- 每次转写使用一份不可变设置快照，客户端构造/调用/关闭全部纳入安全异常边界，不把Key、URL、headers、原始异常或识别文本写日志。
- 录音/显式转文字上传是短命处理文件，位于服务端受控的用户/Agent/请求目录；限流式大小、非空、并发和清理，成功/失败/取消均清理。取消本地线程时确保实际读取完成后清理，不误删源附件。
- 聊天音频附件沿用现有AttachmentRecord与生命周期；补齐audio.data与file/image相同的owner/Agent/conversation/deleted/path验证、发送绑定。不要新增任意本地路径或远程URL转写入口。
- 本地模型名受限，缓存按模型名与服务端缓存目录区分并限制推理并发；普通使用不隐式下载权重。模型权重仅共享文件缓存，不保存用户音频或结果。未安装依赖/未准备权重明确不可用；不为验收全局安装或下载大模型。

## 页面

- 原VoiceTranscription页面增加本地/远程模型选择和保存后音频测试，保留auto/native及原卡片。无Secret编辑副本；加载/保存/测试跨身份的迟到响应不污染当前页面。
- Chat使用安全status端点；录音及新增明确“上传音频转文字”动作复用一份上下文与错误处理逻辑。普通附件上传保持附件语义，不自动改写草稿。
- 捕获录音起始的认证代际、用户、Agent、会话和当前sender；切换或卸载停止tracks/timer并取消请求，等待麦克风授权的迟到stream也关闭。旧音频不得携新身份提交，旧结果不得回填新草稿；只追加当前输入框，不自动发送。
- OS设置入口复用现有能力门禁，不能绕过管理员页面权限。不扩展其他菜单重构。

## 验收边界

隔离HTTP/PG与页面测试覆盖权限、字段原子保存、凭据不回显、旧入口、附件音频归属、错误及清理、并发/身份切换。真实浏览器使用隔离服务与loopback假Whisper，实际MediaRecorder/文件上传→multipart→真实HTTP客户端→文本回填，不拦截成功API或替换后端转写函数。该证据验证链路，不证明ASR准确率或本地Whisper推理。本机缺少Whisper/FFmpeg，明确记录本地真实识别未测。

实现、测试、审查后在原18089部署代码并验证登录与页面；真实既有配置、Secret、模型及技能保持不变。无需真实schema迁移；仅测试fixture使用一次性schema。完成后交付证据，停在7.3，不自动进入8.1。
