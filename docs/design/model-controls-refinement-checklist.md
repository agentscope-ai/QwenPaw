# 模型交互收敛清单

用户已确认本轮方案；复用 apple-design 的空间一致性、直接反馈与克制原则。

- [x] Selector 固定浏览高度、保留 Provider 焦点，浮层适应屏幕；移动端底部面板
- [x] 删除冗余来源说明与免费提示横幅，缩短不可调节思考提示
- [x] 侧栏模型入口常驻，次要入口显式收纳，历史独立滚动
- [x] 全局默认模型并入 Provider 工具栏，卡片优先显示启用数；总数已有缓存时才显示分母，不增加目录加载
- [x] 模型管理加入整个 Provider 模型池的全启用 / 全关闭快捷操作，保留配置
- [x] 使用现有测试、构建与实际页面检查；不新增测试文件


验证：前端现有 258 项通过；后端现有 312 项通过、1 项跳过；生产构建通过。
浏览器夹具验证了桌面折叠位置和焦点、390px 移动面板、650px 高度侧栏入口；未操作用户运行服务。
pre-commit 的 AST、mypy、flake8 等检查通过；pylint 仍报告现有风格告警（包括与项目要求冲突的无插值 f-string），未扩大范围修复。

- [x] 模型数量入口使用整行浅灰圆角按钮，统一普通与分组卡片的悬停、按下和键盘聚焦反馈。

新建任务模型继承修复：

- [x] 核对当前 Agent 默认接口：返回 qwen3.8-max-0902，来源 agent。
- [x] 新建任务清除当前 Agent 的空白草稿模型与思考设置，并通知选择器重新加载默认值。
- [x] 保留既有会话和其他 Agent 的选择；验证首条请求不携带旧草稿覆盖。
- [x] 扩展现有用例，相关 32 项测试通过。
- [x] 生产构建及资源检查通过。

模型能力与实时统计修复：

- [x] 核对官方 DashScope Qwen3.8、DeepSeek V4/V4.1、GLM 与 Kimi K3 控制参数。
- [x] 补齐明确型号，修正预算范围及 DashScope 强度参数格式。
- [x] 每次 LLM 调用后发送累计 usage，前端即时接收，使用最近调用输入计算上下文。
- [x] 保留临时会话转正式会话的统计归属，历史加载不覆盖流中数据。
- [x] 前端 106 项、后端 181 项测试通过；追加的 3 项实际请求拦截测试通过；生产构建通过。

能力核对依据：[阿里云 Chat Completions 参数](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions)，2026-09-20。

- Qwen3.8 Max / Max-0902 / Flash / 2.4t-a95b / 27b：数字预算上限 262144，默认 131072，与 reasoning_effort 互斥。
- DeepSeek V4 Pro / Flash：high、max；Pro-0813 / Flash-0731 / V4.1-Flash：low、high、max，允许关闭。
- GLM 5 / 5.1 / 5.2：high、max；GLM 5.3：low、high、max，不能关闭；Kimi K3：low、high、max，允许关闭。
- 仅更新已核实的服务与确切型号，不将三方转发型号的能力按名称猜测继承。

PR 全量检查与发布：

- [x] 完整前端测试：414 个文件、4480 项通过。
- [x] 前端 TypeScript / Prettier 与生产构建通过。
- [x] 模型相关后端回归：1033 项通过、1 项跳过。
- [x] ESLint 对照：基线 382 个错误，当前 380 个，新增 0 个；全量命令仍未通过。
- [x] 全量 pre-commit 在最终文件状态下通过（退出码 0）。
- [ ] 确认历史 ESLint 错误处理范围后提交、推送并转正式 PR。

Lint 规则说明：AGENTS.md 要求使用 f-string，故明确豁免 W1309。pytest fixture / 白盒测试和集中协议映射使用局部、附带原因的 pylint 例外；未关闭其他错误检查。

### Slider alignment and live numeric feedback

- [x] Center tick dots and thumb on the enlarged rail, including endpoints.
- [x] Snap effort sliders only to declared model levels; retain continuous budget and separate off position.
- [x] Use NumberFlow for live budget digits with reduced-motion support; persist on release.
- [x] Let arrow keys cross the off/budget gap in one step.
- [x] Verify mouse reversal, touch snapping, keyboard endpoints/gap and reduced motion in an isolated browser fixture.
- [x] Re-run full frontend suite: 414 files / 4,480 tests passed; TypeScript, Prettier, production build and changed-file pre-commit passed. Slider ESLint: zero errors, one existing hook-dependency warning.

### Commit and model-card-tilt integration

- [x] User authorized committing and pushing current changes with the recorded historical ESLint baseline.
- [ ] Commit and push current slider and validation fixes.
- [ ] Merge feat/model-card-tilt into the current branch.
- [ ] Verify merged frontend and push the integration.
