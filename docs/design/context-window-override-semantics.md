# 上下文窗口的覆盖语义与生效值展示

## 1. 状态与范围

- 状态：**实现完成，自动化验证通过**（checklist 见第 9 节，验证结果见第 10 节）
- 分支：`fix/context-window-inherit-semantics`
- 关联 Issue：`agentscope-ai/QwenPaw#7810`
- 范围：`ModelInfo.max_input_length` 的语义、`context_windows` 的解析与来源、
  provider 快照迁移（v2 → v3）、provider 响应的只读投影、Console 模型配置弹窗
- 不包含：
  1. catalog 中「等于默认值 = 未提供」这一约定的语义化（见第 12 节，含 22 条
     影响清单）；
  2. 本地模型（llama.cpp `--ctx-size`）与静态目录的关系；
  3. `thinking_*` / `generate_kwargs` 的继承值展示；
  4. `EmbeddingModelConfig.max_input_length`（ReMe 嵌入配置，同名不同物）。

## 2. 问题与根因

Issue #7810 的现象：用户在模型页把「最大上下文长度」设为 131072（压缩比例
0.5，期望阈值 65536），实际请求却一路涨到 271k，压缩看起来不触发。用户按
建议「改一个值再改回来保存」后问题消失。

根因是三条叠加：

1. **显示读原始字段，运行读解析结果。** 模型页显示
   `model.max_input_length ?? 131072`
   （`console/.../ModelConfigEditor.tsx:53`），而运行时用
   `Provider.get_context_size` → `resolve_context_window`
   （`src/qwenpaw/providers/provider.py:1099`、
   `src/qwenpaw/providers/context_windows.py:143`）。后者在「存的正好是默认值
   131072」时把该值视为「没配过」而跳过，转而使用静态目录（`gpt-5` →
   272000），于是界面与运行分叉。
2. **一个字段承担三种含义。** `max_input_length` 同时表示「用户覆盖值」
   「历史默认值」「未设置哨兵」，只能靠伴随布尔
   `max_input_length_configured` 区分，导致「用户显式选择 131072」在数据层
   不可表达——这正是 issue 里那句「改一下再存才生效」的来源。
3. **保存路径的脏值门控。** 前端只在字段被编辑过（`maxInputLengthDirty`）时
   才把 `max_input_length` 发给后端，后端收到该字段才把伴随布尔置 True
   （`provider.py:978`），所以「打开弹窗直接保存」不产生任何效果。

维护者在 issue 中的判断（「131072 未被识别为显式保存的设置，回退到内置值
272000」）与此一致，用户回复问题解决。但代码级缺陷仍在，且用户可见的
「模型页显示一个从不生效的数字」至今没有修复。

## 3. 关键证据

### 3.1 解析分叉实测（本机运行 `provider.get_context_size`）

| 模型 | 模型页显示 | 实际生效 | 0.5 比例的真实触发点 |
| --- | --- | --- | --- |
| `gpt-5` | 131072 | 272000 | 136000 |
| `qwen3-max` | 131072 | 262144 | 131072 |
| `claude-sonnet-4-5` | 131072 | 200000 | 100000 |

`gpt-5` 的 272000 与 issue 中「271k」吻合。

### 3.2 catalog 里的「131072」是生成器写出的占位符

`src/qwenpaw/providers/data/model_catalog.json` 共 133 条模型带
`max_input_length`，其中 111 条与静态目录一致，22 条不一致——而这 22 条**全部**
是 catalog 值为 131072（默认值）的情况：

| provider | model | catalog | 静态目录 | 旧生效 | 若删掉「= 默认值即未设置」 |
| --- | --- | --- | --- | --- | --- |
| OPENAI_MODELS | gpt-5 | 131072 | 272000 | 272000 | 131072 |
| OPENAI_MODELS | gpt-4.1 | 131072 | 1047576 | 1047576 | 131072 |
| OPENAI_MODELS | o3 | 131072 | 200000 | 200000 | 131072 |
| AZURE_OPENAI_MODELS | gpt-4.1-mini | 131072 | 1047576 | 1047576 | 131072 |
| DASHSCOPE_MODELS | qwen3.8-max | 131072 | 1000000 | 1000000 | 131072 |
| ALIYUN_TOKENPLAN_MODELS | qwen3.7-plus | 131072 | 1000000 | 1000000 | 131072 |
| ALIYUN_CODINGPLAN_MODELS | qwen3-coder-next | 131072 | 262144 | 262144 | 131072 |
| …（共 22 条，全部同型） | | | | | |

结论：**「catalog 值等于默认值 ⇒ 视为未提供」是承载语义的规则，不是历史
包袱**——它是 catalog 生成器「未采集到窗口时写入字段默认值」这一事实的唯一
补偿。因此本改动的目标不是删掉这条规则，而是**把它从解析器里挪到数据边界**
（第 4.5 节），让解析器不再需要认识「131072」这个魔法数字。

## 4. 设计决策

### 4.1 槽位拆分：每个来源一个槽

| 来源 | 旧存放 | 新存放 |
| --- | --- | --- |
| 用户显式覆盖 | `max_input_length` + 布尔 | `max_input_length`（`None` = 未覆盖） |
| 供应商 API 探测 | `max_input_length_auto_detected` | 不变 |
| provider/catalog 文档值 | 复用 `max_input_length`（无标记） | 新增 `max_input_length_catalog` |
| 静态目录（代码内表） | 不落库 | 不变 |
| 兜底 128k | 常量 | 不变 |

旧结构里「用户覆盖」与「catalog 值」共用一个槽，**伴随布尔是唯一的区分手段**；
拆成两个槽后布尔被删除，「未覆盖」由 `None` 直接表达。

### 4.2 `None` 表示继承，符合本类既有约定

`ModelInfo` 中 `max_output_length`、`max_input_length_auto_detected`、
`thinking_enabled`、`thinking_budget`、`reasoning_effort` 全部是
`Type | None = None`（`provider.py:150-270`），只有 `max_input_length` 是
「整数默认值 + 伴随布尔」。本次改动把它并入既有约定，而不是发明新约定。

### 4.3 读取时解析 + 只读投影，而不是回写

拒绝「照抄输出侧」的方案（`max_output_length` 由 discovery 回写到同名字段）。
理由：输出侧没有「默认值」，`None` 天然表示未知；而输入侧的目录值是**代码内
静态表 + 随包数据**，不在存储里。回写会要求「目录升级后重新水合」，并需要
保留标记来区分用户值与数据值，等于把同一信息复制进存储、制造第二个真相与
漂移风险。读取时解析的输入是「存储 + 代码版本」，天然不会与代码版本脱节。

因此展示侧采用**只读投影**：`Provider.to_provider_info()` 是全部 provider
响应的唯一出口，那里已有逐模型派生字段的先例
（`payload["supports_agent_thinking"] = ...`，`provider.py:1199`）。投影只写进
响应用字典，**不写回 `ModelInfo` 实例**，因此不会被快照持久化。

### 4.4 优先级顺序与结果都不变

解析顺序保持原有 5 级，只是「显式」的判定从布尔改为 `is not None`：

| 级别 | 条件 | 来源标签 |
| --- | --- | --- |
| 1 | `max_input_length is not None` 且 `> 0` | `user` |
| 2 | `max_input_length_auto_detected > 0` | `api` |
| 3 | `max_input_length_catalog is not None` 且 `> 0` | `catalog` |
| 4 | 静态目录命中 | `catalog` 表内值（同标 `catalog`） |
| 5 | 兜底 | `default` |

两处与旧行为的差异，均为**有意为之且已评估**：

1. 级别 1 增加 `> 0` 守卫。旧代码的显式分支没有下界检查，而级别 3 有；
   槽位拆分后，一个被写入的 `0` 会直接成为级别 1 并导致用量百分比除零，
   因此必须补上（契约仍是「大于等于 1000」，见 `ModelInfo` 的 `ge=1000`）。
2. 级别 3 不再重复判断「是否等于默认值」——该判断已前移到 catalog 装载边界
   （第 4.5 节），结果与旧行为逐条相同（3.2 节的 111/22 分析可复算）。

### 4.5 「等于默认值 = 未提供」前移到数据边界

在 `model_catalog.py` 读取 packaged / OTA / local 三个 catalog 文档后，把
`max_input_length == DEFAULT_CONTEXT_WINDOW` 归一化为「不提供该字段」，非默认值
写入 `max_input_length_catalog`。这样：

- 解析器只需判断 `None`，不必认识 131072；
- catalog 装载是唯一的数据入口，规则集中一处、可被 3.2 节的清单验证；
- 用户在**覆盖槽**里写 131072 依然被尊重（级别 1 无默认值判断），语义自洽。

## 5. 数据模型

```python
# 覆盖槽：None = 继承（不覆盖）
max_input_length: int | None = Field(default=None, ge=1000)
# provider/catalog 文档值（随包 catalog、OTA、local catalog）
max_input_length_catalog: int | None = Field(default=None, ge=1000)
# 供应商 API 探测值（不变）
max_input_length_auto_detected: int | None = Field(default=None, ge=1000)
# 已删除：max_input_length_configured
# 只读投影（仅出现在 provider 响应里，不写实例、不落库）
effective_max_input_length: int | None = Field(default=None)
effective_max_input_length_source: Literal[
    "user", "api", "catalog", "default"
] | None = Field(default=None)
```

持久化白名单：加入 `max_input_length_catalog`，移除
`max_input_length_configured`；两个 `effective_*` 字段不入白名单。

> 说明：快照继续保存 catalog 槽的值，是为了**保持今天的行为**——今天
> `restore_model_state` 也会用快照里的 `max_input_length` 覆盖刚装载的 catalog
> 值（「快照钉死旧目录值」）。该行为是否合理见第 12 节后续项。

## 6. 投影与 API 契约

- 响应：`ProviderInfo.models[]` / `extra_models[]` / `discovered_models[]`
  每个模型新增 `effective_max_input_length` 与
  `effective_max_input_length_source`，由 `to_provider_info()` 统一填充。
- 请求：`ModelConfigRequest.max_input_length`
  - 字段缺席 = 不修改；
  - 整数 = 设置覆盖；
  - `null` = **清除覆盖**（回到继承）。
  路由已用 `body.model_fields_set` 构造配置字典
  （`app/routers/providers.py:766`），缺席与 `null` 天然可区分，无需新增字段。
- 命名冲突说明：`ActiveModelsInfo.effective_max_input_length`
  （`config/config.py:210`，当前激活模型的生效值）与本投影同义不同层，刻意保持
  同名以便阅读；两者都取自 `Provider.get_context_size`。

## 7. 快照迁移 v2 → v3

`PROVIDER_SNAPSHOT_SCHEMA_VERSION` 2 → 3，在 `migrate_provider_snapshot` 中按
模型逐条转换（`models` / `extra_models` / `discovered_models` 三个集合）：

| 旧状态 | 新状态 |
| --- | --- |
| `configured == True` | `max_input_length` = 旧值 |
| `configured` 假/缺 且 值 != 131072 | `max_input_length` = `null`，`max_input_length_catalog` = 旧值 |
| `configured` 假/缺 且 值 == 131072 | `max_input_length` = `null`（等价于未提供） |
| 一律 | 删除 `max_input_length_configured` 键 |

迁移是纯数据变换，不依赖网络；对未被显式配置过的模型，迁移后解析结果不变
（3.2 节清单可复算）。

## 8. Console 改动

`ModelConfigEditor.tsx`：

- 输入框绑定覆盖槽；`max_input_length == null` 时输入框为空，`placeholder`
  显示生效值（例如 `272000`）；
- 输入框下方灰字：`当前生效 {effective} · 来源 {source}`，来源用既有
  `max_output_length` 的呈现习惯（`Model capability · api`）；
- 已覆盖时显示「恢复默认」按钮（`RotateCcw`，与 Max Tokens 的既有按钮同款），
  点击后发送 `max_input_length: null`；
- 脏值门控保持：未编辑则不发该字段，避免「看一眼即覆盖」；
- 新增 i18n key（zh/en）：继承提示、来源标签、恢复默认。

## 9. 改动点清单与进度

### 后端

- [x] `providers/context_windows.py`：新增 `ContextWindowSource` 与
  `ContextWindowResolution`，`resolve_context_window_details`（唯一优先级实现）
  与 `resolve_context_window`（返回 int 的薄封装）并存；移除
  `configured_is_explicit`，改为「槽位为 `None` 即继承」
- [x] `providers/provider.py`：`ModelInfo` 字段改动；删除
  `max_input_length_configured`；`update_model_config` 支持 `None` 清除覆盖并
  同步 `config_overrides`；`get_context_size` 走 details 版本（新增
  `get_context_window_details`）；`get_info().serialize_model` 填充只读投影
- [x] `providers/provider_model_state.py`：白名单与 `serialize/restore` 适配，
  迁移升级到 v3
- [x] `providers/model_catalog.py`：装载边界归一化（= 默认值 → 不提供），写入
  `max_input_length_catalog`
- [x] `providers/provider_discovery.py`：fetch 报告的值一律进入 catalog 槽，
  不再可能成为/覆盖用户覆盖值
- [x] `providers/provider_manager.py`：删除自定义 provider 创建时的
  「字段存在即显式」推断（值本身就是覆盖）
- [x] `providers/provider_manager_persistence.py`：`configured_update` 不再补
  `max_input_length_configured`
- [x] `providers/openrouter_provider.py`：删除「为兼容而写入覆盖槽」的 legacy
  写入（该值已写入 `auto_detected`，生效结果不变）
- [x] `agents/acp/runtime_provider.py`：不再写伴随布尔
- [x] `app/routers/providers.py`：`ModelConfigRequest.max_input_length` 加
  `ge=1000` 并说明 `null` 语义

### 前端

- [x] `console/src/api/types/provider.ts`：`max_input_length: number | null`，
  删除 `max_input_length_configured`，新增两个投影字段
- [x] `console/.../ModelConfigEditor.tsx`：继承态展示（占位符 + 生效值/来源）、
  「清除覆盖」按钮、脏值门控保持
- [x] `console/src/locales/{zh,en}.json`：新增 6 个文案键
- [x] `console/src/pages/Agent/Config/index.tsx`：回退路径优先取投影值

### 测试

- [x] 后端：`test_context_windows.py` 重写为新 API，新增来源/清除覆盖/非正值/
  投影一致性用例
- [x] 后端：`test_provider_model_state.py` 新增 5 条 v2→v3 迁移用例
- [x] 后端：`test_model_catalog.py`、`test_provider_manager.py`、
  `test_mimo_provider.py`、`test_volcengine_provider.py`、
  `test_llamacpp_backend.py`、`test_acp_runtime_provider.py`、
  `test_create_model_and_formatter_override.py` 适配新槽位
- [x] 后端：`test_provider_context_window.py` 新增 null=清除、0/负数被拒
- [x] 前端：`ModelConfigEditor.test.tsx` 新增 4 条（继承展示、覆盖可见、清除
  发送 null、未触碰不发字段）
- [x] 验证：后端单测、`tsc`、vitest、eslint、black/flake8、基线差分对比、
  浏览器端到端（10.6）

## 10. 验证结果

### 10.1 语义验证（本机实测）

| 场景 | 输入 | 结果 |
| --- | --- | --- |
| `gpt-5` 未配置 | 三槽皆空 | 272000 / `catalog` |
| 用户覆盖 131072 | `override=131072` | 131072 / `user` |
| 目录槽 1000000 | `catalog=1000000` | 1000000 / `catalog` |
| API 探测 200000 + 目录槽 1000000 | 二者同时 | 200000 / `api` |
| 覆盖 65536 + API 200000 | 二者同时 | 65536 / `user` |
| 覆盖为 0（非法） | `override=0` | 272000 / `catalog`（不进入触发点） |
| 目录装载：`gpt-5` | JSON 中 131072 占位符 | `catalog_slot=None` |
| 目录装载：`qwen3.7-plus` | JSON 中 1000000 | `catalog_slot=1000000` |
| 迁移：`configured=True, 131072` | v2 快照 | `max_input_length=131072` |
| 迁移：`configured=False, 1000000` | v2 快照 | `None` + `catalog=1000000` |
| 迁移：`configured=False, 131072` | v2 快照 | `None`（占位符丢弃） |
| 投影 | 300 模型 provider | 实例上不残留派生值（`effective_*` 只出现在响应里）|

> 投影的耗时不能只看单点：初版只记了「300 模型 8.3 ms」，而它随模型数**平方**
> 增长（见 §13.1 的 P1）。修复后的完整曲线与归属见 §13.5。

### 10.2 测试与静态检查

| 项目 | 结果 |
| --- | --- |
| `tests/unit/providers` + `config` + `token_usage` + `local_models` + `app/routers` | 1670 passed；23 failed 与基线**逐条相同**（见 10.3） |
| `tests/unit/app` + `tests/unit/agents` | 失败/错误集合与基线完全相同（各 20） |
| 新增/修改测试文件 | 全部通过（含 5 条迁移、4 条前端、2 条 API 契约） |
| `tsc -b --noEmit` | 147 个错误全部位于 `src/pages/Chat/**`，与基线一致；改动文件 0 错误 |
| vitest（`ModelConfigEditor.test.tsx`） | 7 passed |
| eslint（4 个改动文件） | 无输出（无告警） |
| black（**23.3.0** `--line-length=79`）/ flake8 | 通过；唯一 flake8 告警是既有的 E203（全仓 130 处，非本次引入） |

### 10.3 基线差分方法

用 `git stash` 切回基线，跑同一命令，对 `FAILED` 集合做 `comm` 差集：

- `tests/unit/providers|config|token_usage`：基线 22 个失败 → 分支 22 个，**差集为空**；
- `tests/unit/app|agents`：基线 20 个 → 分支 20 个，**差集为空**；
- 已知环境阻塞：`test_retry_chat_model.py`（agentscope 缺 `InjectionConfig`）与
  `test_gemini_provider.py::test_summary_thinking_override_is_concurrency_safe`
  （基线即死锁）在命令中用 `--ignore` / `--deselect` 排除。

### 10.4 实现偏差与备注（与第 4 节的差异）

1. 只读投影字段按**既有先例**声明在 `ModelInfo` 上
   （`supports_agent_thinking` 同样如此），由 `Provider.get_info()` 填充进响应
   字典，**不写回实例、不在持久化白名单内**；没有引入新的响应子模型。
2. `merge_discovered_model` 收到 fetch 携带的 `max_input_length` 时，一律改写为
   `max_input_length_catalog`（防御性：任何 provider 插件都不该通过上报把值
   变成用户覆盖）。
3. 前端「保存」按钮本来就是 `disabled={!dirty}`，因此「未触碰窗口但保存其他
   设置」需要先改别的字段——测试据此构造，且窗口字段确实不进入请求体。
4. 前端测试文件新增 `import "@/i18n"`：共享测试环境未初始化 i18next，插值不会
   发生（数字根本不会渲染），断言必须基于真实译文。
5. 格式化须使用仓库锁定的 **black 23.3.0 `--line-length=79`**；本机
   `agentscope` 环境的 black 26.5.1 会把代码重排到 88 列，产生大量无关改动。

### 10.5 手工验收步骤（供 Review 复核）

1. 启动 Console → 设置 → 模型，打开 `gpt-5`（或任一目录内窗口 ≠ 131072 的
   模型）：输入框应为空，占位符显示 `272000`，下方灰字为
   `继承中 · 当前生效 272,000 · 来源：内置模型目录`，且**没有**「清除覆盖」按钮。
2. 在输入框填入 `131072` 并保存：输入框保留该值，出现「清除覆盖」按钮。
3. 打开 Agent 配置（上下文管理）：压缩比例 0.5 时「压缩阈值」应显示
   `65536`；改前该值为 `136000`（0.5 × 272000），即 issue 中「压缩不触发」的
   直接原因。
4. 回到模型页点击「清除覆盖」并保存：阈值回到 `136000`，输入框恢复占位符
   显示 `272000`。
5. 升级路径：用旧版本生成的 providers 快照启动，确认模型页对未配置过的模型
   显示的是生效值而非 131072（快照迁移 v3 生效）。

### 10.6 浏览器端到端实测（Console @ 127.0.0.1:8088，2026-09-17）

前置条件（本次踩到的坑，后续复现请照做）：

1. 本地 `node_modules` 里 `@agentscope-ai/chat` 是 `1.1.73-beta`，而
   `package.json`/`package-lock.json` 要求 `1.2.0-beta.*`；版本不符会让
   `npm run build` 的第一步 `tsc -b` 报 147 个 `src/pages/Chat/**` 类型错误而
   **中断构建**（dist 保持旧产物，界面看不到任何修复）。先 `npm install`
   （不会改 lock，已核验）再 `npm run build`（本次 5m 5s，含 monaco/precompress/
   initial-bundle 校验）。构建后 `dist/assets/*.js` 应能命中
   `maxInputLengthInherited`。
2. 页面搜索框是「聚焦后才可编辑」（防自动填充），必须先 click 再输入。
3. provider 卡片会随列表刷新短暂卸载，定位需轮询等待或按卡片重新定位。

在浏览器中逐条验证（`poke/gpt-5.6-luna`、`poke/gpt-6-astra`、
`dashscope/qwen3.7-max`）：

| 场景 | 覆盖槽 | 输入框 | 占位符 | 提示行 | 清除按钮 |
| --- | --- | --- | --- | --- | --- |
| 继承 + 目录值 | 空 | 空 | `272000` | `Inherited · effective 272,000 · from built-in catalog` | 无 |
| 继承 + 兜底值 | 空 | 空 | `131072` | `Inherited · effective 131,072 · from 128K default` | 无 |
| 用户覆盖 | 65536 | `65536` | `65536` | 基础提示（无「继承」行） | 有 |

「清除覆盖」闭环另在 `dashscope/qwen3.7-max` 上实测：点击清除 → 输入框清空、
保存按钮激活 → 保存后 `GET /api/models` 返回
`max_input_length=None, effective=1000000, source=catalog`，即真正回到继承。

> 事故记录（可复现的注意点）：验证末尾的「恢复原值」保存**没有落盘**，原因是
> 后端进程在 16:56:07 正常退出（`qwenpaw.log` 末尾是完整 shutdown 流程，无异常
> 栈），前端点击并未送达。已按快照文件精确恢复该模型（`max_input_length=65536`
> 且 `config_overrides` 去掉已删除的旧字段名），并用离线解析复核为
> `65536 / user`。**教训：在真实用户配置上验证「清除/改写」类交互前，先确认
> 后端存活并在每次写入后立即用 API 复核落盘结果。**

### 10.7 实现期间新增的小改动

- `prune_model_overrides` 清洗 `config_overrides` 中已不存在的字段名（例如被删除
  的 `max_input_length_configured`）。**初版只加在 `serialize_model_state`
  （恢复路径）上，落盘仍走 `provider.model_dump()`，所以磁盘快照并不自愈**——
  这一点由 review 指出并已修正：现在写盘路径
  （`provider_persistence.write_provider_snapshot`）在落盘前对三个集合统一裁剪，
  所有写入路径都会收敛。覆盖用例：`test_serialized_state_drops_dead_override_names`
  （内存）与 `test_snapshot_write_drops_dead_override_names`（落盘-读回）。

## 11. 风险与兼容性

| 风险 | 处置 |
| --- | --- |
| 外部插件构造 `ModelInfo(max_input_length_configured=...)` | 仓内 `plugins/`、`packages/` 无此用法；字段删除属破坏性变更，需在 PR 描述中公告 |
| 插件在 `get_default_models()` 里声明 `max_input_length` | 注册边界把声明值搬进 `max_input_length_catalog`（§15 Fix A1），优先级与 main 相同（rank 3），UI 不再显示假的「清除覆盖」 |
| 插件只覆写实例方法 `_context_catalog_enabled` | 只影响注册响应的投影值精度（运行时解析不受影响）；建议改覆写类方法。见 §15.6 |
| 旧客户端（Console 缓存）发送布尔字段 | `ModelInfo` 未开启 `extra=forbid`，未知字段被忽略；`ModelConfigRequest` 同理 |
| 客户端回传 `effective_*` | 字段已声明故会被接受，但响应一律重算，且落盘前 `strip_derived_model_state` 清除（§15 Fix C） |
| 快照未迁移即被读取 | 迁移在加载入口统一执行（与 v2 迁移同路径），并有单测覆盖 |
| 覆盖槽出现 `0`/负数 | 级别 1 增加 `> 0` 守卫 + 请求模型 `ge=1000` |

## 12. 后续项（本 PR 不做）

1. **catalog 的 131072 语义化**：若要在 catalog 中显式表达 131072，需要改
   catalog 生成器让「未采集」与「131072」可区分（例如省略字段），届时可在
   `model_catalog.json` 重生成后去掉装载边界的归一化。3.2 节的 22 条即影响面。
   **补记（review P3a）**：归一化还必须在「占位符」分支里显式回写
   `max_input_length_catalog: None`，否则合并后的 catalog 会因为该字段
   「缺席」而保留旧值，overlay 永远无法把一个已记录的较大窗口下调回 128k。
   已修复，覆盖用例 `test_catalog_overlay_can_lower_a_documented_window`。
   注意修复后的语义边界：下调到 128k 只在静态模式目录**没有**该模型时才真正
   改变生效值；`gpt-5` 这类命中静态目录的仍解析为 272000（rank 4 > rank 5）。
   **第三轮补记**：`data/model_catalog.json` 里仍写着已删除的
   `max_input_length_configured`（装载时被 pydantic 忽略），重生成 catalog 时
   应一并清掉。
2. ~~**快照钉死 catalog 值**~~：**已在第二轮 review 中处理**（见 §14.3）。
   `restore_model_state` 现在让当前目录值优先，快照值仅在该模型当前目录没有
   记录时兜底；无需改持久化白名单。
3. **本地模型**：`qwenpaw-local` 未像 Ollama 一样退出静态目录
   （`ollama_provider.py` 的类级 `context_catalog_enabled` 是唯一例外），且
   `--ctx-size` 未回写为窗口来源，本地模型（如 `Qwen3-Coder-30B`）的压缩窗口
   可能按云端 262144 计算。
4. **`thinking_*` / `generate_kwargs` 的继承展示**：字段语义正确但继承值不可见，
   属于同一族体验缺口。
5. **422 校验错误的展示**：`ModelConfigRequest.max_input_length` 的 `ge=1000`
   由路由层拒绝越界值时返回数组形式的 `detail`，Console 会显示整段 JSON
   （§15.2 的 N2）。属通用错误渲染问题，见 §15.6。

## 13. PR Review 反馈：核实结论与修复方案

对 review 提出的 5 项逐条在本机复现。结论：**全部真实存在**；其中 P1 的
O(N²) 形态是先于本 PR 存在的（`supports_agent_thinking` 早就在做同样的线性
反查），但本 PR 让它翻了一倍，且 review 对"本 PR 引入 O(N²)"的表述需要修正为
"本 PR 放大了 O(N²)"。P2b/P3a 的用户可见后果需要区分"本 PR 引入的症状"与
"继承自旧语义的形态"。

### 13.1 复现结果与归属

| 项 | 是否真实 | 本 PR 的角色 | 复现实据 |
| --- | --- | --- | --- |
| P1 投影使 `get_info()` 成 O(N²) 且占用事件循环 | 是 | **放大**：O(N²) 形态先存在（`supports_agent_thinking` → `get_model_info` 线性扫描），本 PR 新增的窗口解析又做 2 次线性扫描，比较次数与耗时都翻了约一倍 | 比较次数严格 ×4/翻倍：50→5,000；800→**1,280,000**（= 2N²）。其中本投影占 640,000（恰好一半）。回调延迟法（预热 + 中位数）：800 模型 **42.7 ms**（去掉本投影 22.9 ms），延迟 ≈ `get_info` 自身耗时；`get_info` 内部**无 await**（整段同步占住循环），`list_provider_info` 用 `asyncio.gather` 直接在循环上 await，`configure_model` 同样 |
| P2a 磁盘快照不自愈 | 是 | **引入**：过滤只加在 `serialize_model_state`（恢复路径），写盘走 `provider_persistence.write_provider_snapshot` → `provider.model_dump()`，绕过了过滤；§10.7 的"快照自愈"表述因此**不成立** | 实测：内存过滤后 `['generate_kwargs']`，落盘读回仍是 `['max_input_length_configured', 'generate_kwargs']` |
| P2b hub 目录窗口落在"用户覆盖"槽 | 是 | **症状由本 PR 引入**（旧 UI 没有"清除覆盖"按钮）；值占覆盖槽是旧 `configured=True` 语义的延续，本 PR 只是删掉布尔后让它在新的判定下暴露 | `hub_managed.py:96` 现在 `max_input_length=<目录值>`；`ManagedProvider.get_info()` 覆写后直接返回 `self.models`，响应**没有投影**（不是错标来源）；console 用 `max_input_length != null` 判定 → 显示"清除覆盖"，保存被 `app/routers/providers.py:94` 以 403 "Organization model configuration is locked" 拒绝 |
| P3a overlay 无法把窗口下调回 131072 | 是 | **分支由本 PR 引入**，但用户可见结果与改前一致（旧代码里 131072 会被"等于默认值"规则忽略，最终仍由静态目录给出 272000） | 实测：packaged=272000 + overlay=131072 → catalog 槽仍是 **272000**；overlay=64000 → 64000（正常） |
| P3b 冗余双写 / 死条件 / 白名单与赋值重叠 | 是 | 本 PR 引入 | `provider_discovery.py:88` 同时写 catalog 与 auto_detected（内建发现路径只写 auto_detected，两条路径不一致）；`provider_model_state.py:94` 的条件在早返回之后恒为真；`serialize_model_state` 先由白名单取值再整段覆盖 |

### 13.2 修复方案（含 checklist）

**P1（阻塞项）：让 `get_info()` 回到 O(N)，并锁一条回归断言**

- [x] `Provider.get_info()` 内构建一次 id→ModelInfo 索引
      （`extra_models` 优先于 `models`，与 `get_model_info` 的查找顺序一致；
      `discovered_models` 单独一张表）
- [x] 窗口解析走索引：新增私有 `_resolve_window_from(model_id, configured_info,
      discovered_info)`，公开的 `get_context_window_details(model_id)` 变成
      "先查表再调用同一个实现"的薄封装（保持对其它调用方的行为与签名不变，
      并沿用 `model_info` 优先、`auto_detected` 先取 model_info 再回退
      discovered 的细节）
- [x] 思考标记同样走索引：给 `supports_agent_thinking` 增加可选
      `info` 关键字参数（不传时保持原有查表行为），`serialize_model` 传入索引
      结果；同步更新 `hub_managed.ManagedProvider` 的重载签名，避免子类覆写被绕过
- [x] 新增**确定性**回归断言（不依赖计时）：用子类包装两个 finder 统计 id
      比较次数，断言 N 与 2N 的次数比 ≤ 2.5（线性），失败时给出实测比值
- [x] 更新实验数据：文档 §10.1 的单点（300 模型 8.3 ms）替换为增长曲线 +
      归属拆分，避免再次掩盖增长趋势

**P2a：把过滤放到写盘路径**

- [x] 在 `provider_model_state` 增加可复用的裁剪函数（按
      `ModelInfo.model_fields` 清洗 `config_overrides`）
- [x] 在 `provider_persistence.write_provider_snapshot` 落盘前，对
      `models` / `extra_models` / `discovered_models` 三个集合统一裁剪
      （一处生效，所有写入路径自愈；无需再加快照版本号）
- [x] 修正文档 §10.7 的错误表述，并新增"落盘-读回"测试断言死名字消失

**P2b：hub 目录值改放 catalog 槽，并让 hub 响应带上投影**

- [x] `hub_managed.managed_provider` 改为
      `max_input_length_catalog=m["input_token_limit"]`，覆盖槽保持 `None`
      （运行时结果不变：hub 无发现流程，`auto_detected` 为空，rank 3 与旧
      rank 1 等价）
- [x] `ManagedProvider.get_info()` 为每个模型补上
      `effective_max_input_length[_source]`（用新索引/解析实现，返回
      `model_copy` 而不是就地写实例），使 console 显示
      "继承中 · 当前生效 N · 来源：内置目录"且不出现"清除覆盖"按钮
- [x] 新增测试：hub provider 的模型覆盖槽为 None、投影存在、
      且 `_active...`/console 判定不会给出可写操作

**P3a：占位符分支同时回写 catalog 槽**

- [x] `model_catalog._catalog_input_window` 在"等于默认值"分支返回
      `{"max_input_length": None, "max_input_length_catalog": None}`
- [x] 新增测试：packaged=272000 + overlay=131072 → 合并后 catalog 槽为
      `None`（并说明：此时静态目录仍会给出 272000，只有静态目录无语义的模型
      才真正落到 128k —— 这是设计使然，需要在文档写清楚预期）
- [x] 文档 §12.1 补上该后果与修法，避免只留"后续项"而无具体影响

**P3b：清理**

- [x] `provider_discovery`：保留 catalog 写入但补注释说明它是插件渠道的
      语义归属；或按其建议删除并统一到 `auto_detected`（二选一，倾向保留 +
      注释，因为 fetch 上报的窗口语义上属于目录而非 API 自检）
- [x] 删除 `provider_model_state` 中恒真的版本判断
- [x] `serialize_model_state` 把 `config_overrides` 从白名单循环中排除，
      只保留一次裁剪赋值
- [x] 补充 `apply_discovery_metadata` 与 `merge_discovered_model` 路径差异的
      注释说明

### 13.3 已评估但**不**纳入本次的做法

- **把 `get_info()` 挪到线程池**（`run_sync_io`，hub 路径已经这么用）：能缓解
  阻塞但掩盖 O(N²)，且要改 `ProviderManager` 的并发模型；先修复杂度，若之后
  仍有可感阻塞再单独评估。
- **给 `get_model_info` 加缓存索引**：调用点遍布、列表会被发现/覆盖/删除改写，
  需要失效钩子，风险远大于收益；改成"每次 `get_info()` 建一次局部索引"即可。

### 13.4 验收口径

1. 800 模型下 `get_info()` 的派生字段**查找次数归零**（原 1,280,000）。
   注意：剩余阻塞是响应体自身 `model_dump()` + 校验的线性成本（800 模型约 16 ms），
   与派生字段无关，无法在不改响应结构的前提下消除；
2. 落盘-读回后 `config_overrides` 不含已删除字段名；
3. hub 模型：覆盖槽为 None、响应带投影、UI 不出现"清除覆盖"；
4. overlay 能把文档窗口下调（catalog 槽变 None），并在静态目录无语义时真正生效；
5. P3b 三处冗余消除，`pytest`（providers/config/token_usage/local_models/app）
   失败集合与基线保持一致。

### 13.5 修复实现与复测（2026-09-18）

`get_info()`（800 模型）修复前后：

| 指标 | 修复前 | 修复后 |
| --- | --- | --- |
| id 比较次数 | 1,280,000（= 2N²） | **0** |
| 事件循环阻塞（回调延迟中位数） | 42.7 ms | **16.4 ms** |
| `get_info()` 自身耗时（best-of-3） | 46.7 ms | 25.2 ms |
| 其中派生字段逻辑 | 含在上面扫描里 | ~1.3 ms（把 `supports_agent_thinking` 置空仍是 23.9 ms） |

残余 16 ms 是 800 个模型自身 `model_dump()` + `ProviderInfo` 校验的线性成本，与
派生字段无关；§13.4 原先写的"≤5 ms"是把目标定错了对象——可消除的是查找成本
（已归零），不可消除的是响应体构造成本。

新增/修改的用例：

- `tests/unit/providers/test_context_windows.py`：
  `test_provider_info_serialization_does_not_rescan_per_model`（比较次数 ≤ 2N；
  逐模型扫描会给出 80,000 并失败）
- `tests/unit/providers/test_hub_managed_provider.py`（新）：目录值落在 catalog
  槽、覆盖槽为 None、hub 响应带投影（2 条）
- `tests/unit/providers/test_provider_model_state.py`：
  `test_snapshot_write_drops_dead_override_names`（落盘-读回）
- `tests/unit/providers/test_model_catalog.py`：
  `test_catalog_overlay_can_lower_a_documented_window`、
  `test_catalog_overlay_replaces_a_larger_documented_window`

复测结果：`tests/unit/providers|config|token_usage|local_models`
**22 failed / 971 passed**，失败集合与基线 `comm` 差集为空；`tests/unit/app|agents`
的 20 项失败/错误与基线一致。静态检查：`black 23.3.0 --line-length=79` 全部
unchanged、`flake8` 除仓库既有 E203 外无输出、`mypy`（hook 参数）10 文件
no issues、`pylint`（hook 参数）10.00/10。

## 14. 第二轮 PR Review 反馈（Hub 路径 / 插件签名 / 目录钉死）

三条均由 review 提出并复现成立，前两条是本 PR 引入的回归/破坏。

### 14.1 复现与归属

| 项 | 是否真实 | 本 PR 的角色 | 复现实据 |
| --- | --- | --- | --- |
| P1 Hub 路径 `get_info()` 仍是 O(N²) | 是 | **引入**（补投影时逐模型调用公开解析方法，Hub 的模型都在 `models` 里 → N²） | 800 模型 **640,000** 次比较、阻塞 **124 ms**；4000 模型 **16,000,000** 次、**576 ms**；不投影（= main 行为）0 次 / 0.2 ms |
| P2 `supports_agent_thinking(resolved=…)` 击穿插件 provider | 是 | **引入**（把索引塞进公开签名） | 旧签名子类直接 `TypeError: got an unexpected keyword argument 'resolved'`；`list_provider_info` 是裸 `asyncio.gather`，实测整批调用失败（`/api/providers` 全挂）。插件可注册任意 Provider 类：`plugins/registry.py:333 register_provider(..., provider_class, ...)` |
| P3 `max_input_length_catalog` 被快照永久钉住 | 是 | **有意保留的旧行为**（我把它列为 §12.2 后续项），但字段名与只读投影都暗示"实时目录数据"，静默钉死站不住 | 快照 200000 + 当前目录 1048576 → 解析 **200000**；不持久化该槽才是 1048576 |

### 14.2 修复

- **P1**：`ManagedProvider.get_info()` 内建一次 `{id: model}` 索引，`_projected()`
  改为接收已解析的 `ContextWindowResolution`，窗口走模块级
  `resolve_window_from_info`；新增比较次数断言
  （`test_hub_info_serialization_does_not_rescan_per_model`）。
- **P2**：撤销公开签名变更，`supports_agent_thinking(model_id)` 恢复单参；索引
  改由 `_SERIALIZED_MODEL_INDEX` ContextVar 在序列化期间"环境式"发布
  （带 provider id 作用域，防止嵌套响应取到别的 provider 的索引），由新的
  `Provider._configured_model_info()` 消费；Hub 覆写改调该私有方法。新增
  `test_provider_info_works_with_legacy_thinking_overrides` 锁住"旧签名仍可用"。
- **P3**：`restore_model_state` 让当前目录值优先——仅当新装载的模型
  `max_input_length_catalog is None` 时才用快照值兜底；字段 description 写明
  该优先级。新增两条断言（陈旧值不覆盖；当前目录无值时兜底生效）。

### 14.3 复测

| 指标 | 修复前 | 修复后 |
| --- | --- | --- |
| Hub 800 模型：比较次数 / 阻塞 | 640,000 / 124.0 ms | **0 / 10.7 ms** |
| Hub 4000 模型：比较次数 / 阻塞 | 16,000,000 / 576.1 ms | **0 / 27.2 ms**（线性：4000 次 model_copy + 校验） |
| 旧签名插件 provider 经 gather | TypeError，整批失败 | 正常返回（新增用例覆盖） |
| 快照 200000 + 当前目录 1048576 | 200000 | **1048576** |
| 当前目录无值 + 快照 200000 | 200000 | 200000（兜底保留） |

套件：`tests/unit/providers|config|token_usage|local_models` **22 failed / 975
passed**（失败集合与基线 `comm` 差集为空）；`tests/unit/app|agents` 20 项与基线
一致；`tests/unit/hub` 174 passed（2 个既有环境失败）。静态检查：black 23.3.0@79
unchanged、flake8 除既有 E203 无输出、mypy 6 文件 no issues、pylint 10.00/10。

## 15. 第三轮 Review：核实结论与修复方案

复核基准：PR #7832 的 head `c5340e5e`（= 本地 `fix/context-window-inherit-semantics`）。
状态：**方案待确认，尚未改代码**。

### 15.1 复核方式（可复现）

| 手段 | 命令 / 做法 | 结果 |
| --- | --- | --- |
| 基线差分 | §10.3 的同一命令，分别在分支与 `origin/main`（`ee0c08e7`）各跑一次，`FAILED` 集合 `sort -u` 后 `diff` | 分支 23 failed / 1462 passed；main 23 failed / 1432 passed；**对称差为空**（+30 passed = 新增用例） |
| 语义探针 | `python -c` 直接调 `merge_discovered_model` / `resolve_window_from_info` / `get_context_window_details` | 见 15.2 的"复现实据"列 |
| 落盘探针 | 临时用例：`manager.update_model_config` 设置 65536 → 重建 manager → 再传 `None` | 覆盖槽 / `config_overrides` / 解析值 / 磁盘四处一致，**通过**（非缺陷，见 15.3 D1） |
| 快照探针 | `write_provider_snapshot` 后读回 JSON | `models[0]` 含 `effective_max_input_length`、`effective_max_input_length_source`（均为 null） |
| 前端 | `vitest run` 两个改动测试文件 | 10 passed |
| 静态检查 | `flake8` 全部改动 Python 文件 | 仅 `test_llamacpp_backend.py:135` 的既有 E203（不在 diff 内） |
| PR 页面 | GitHub PR #7832 | 非 draft、目标 `main`、描述含模板全部标题并公告了破坏性变更；页面上**看不到** check 结果（无法为 CI 背书） |

### 15.2 核实结论与归属

| 项 | 是否真实 | 本 PR 的角色 | 复现实据 |
| --- | --- | --- | --- |
| P1 插件 provider：默认模型的窗口占**覆盖槽**，且注册响应**没有投影** | 是 | **症状由本 PR 引入**：旧 UI 依据 `max_input_length_configured`，不会给出"清除覆盖"；本 PR 改为按"值非空 ⇒ 用户覆盖"判定后暴露，同时优先级从 rank 3 升到 rank 1 | 定义里写 `max_input_length=200000` 实测 `ContextWindowResolution(value=200000, source='user')`；`ProviderInfo(**provider.model_dump())`（注册信息路径）实测 `effective=None, source=None`；`_prepare_plugin_registration` 的 `models` 只来自 `get_default_models()`（`provider_manager_persistence.py:520`），快照只回填 `extra_models` / `discovered_models` |
| P2 `merge_discovered_model` 的 catalog 兜底对**已配置模型**不生效 | 是 | **本 PR 引入**（新增的兜底写入 + 注释） | 同一 id：仅发现态解析 `500000 / catalog`，同时存在于 `models` 时解析 `131072 / default`（值被丢弃）；原因是 `resolve_window_from_info` 的 `auto_detected` 有 discovered 兜底而 `catalog` 没有，`DISCOVERY_MODEL_FIELDS` 也不含 `max_input_length_catalog` |
| P3 只读投影会**落盘**，也接受客户端回传 | 是 | **本 PR 引入** | `write_provider_snapshot` 用全量 `provider.model_dump()`（`provider_persistence.py:48`），落盘 JSON 里每个模型都有这两个键；`CreateCustomProviderRequest.models: List[ModelInfo]` 允许回传（字段已声明）。今天不出错只因 `get_info()` 会覆盖响应值 |
| P4 测试与类型缺口 | 是 | 本 PR 引入 | ① 没有 manager 级 set→重启→clear→重启 用例（写盘合并链正是本 PR 动过的地方）；② `test_context_windows.py:379` 守卫用空的 `extra_models` / `discovered_models`，`get_discovered_model_info` 计数恒 0；③ `effective_max_input_length_source` 是 `str \| None`，文档/console 是 4 值 `Literal` |
| N1 `serialize_model_state` 的死条件 | 是 | 本 PR 引入 | `provider_model_state.py:119-124` 的 `if field != "config_overrides"` 恒被下一行覆盖 |
| N2 `ge=1000` 的 422 渲染 | 是 | 本 PR 引入（约束本身是改进） | 低于 1000 现在由 FastAPI 422 拒绝（比 main 静默存 500 好），但 `detail` 是数组，`console/src/api/request.ts:24` 只解字符串 → 弹窗显示整段 JSON |

### 15.3 修复设计

#### Fix A（P2）插件窗口落位 + 注册响应投影

三条同时做才有意义：A1 之后插件模型的覆盖槽变空、注册响应又没有投影，界面会从"显示错误的覆盖值"变成"什么都不显示"。

- **A1 落位**：`_prepare_plugin_registration` 取得 `default_models` 后做一次目录槽归一化（`max_input_length is not None` ⇒ 搬到 `max_input_length_catalog`，不覆盖已有 catalog 槽），沿用 `model_catalog._catalog_input_window` 的边界归一化思路。安全性来自该函数的构造方式：`provider_info.models` **只**来自 `provider_class.get_default_models()`，快照只回填 `extra_models` / `discovered_models`，所以这里不可能碰到用户状态；搬过去后插件默认窗口回到 main 的 rank 3（目录值）语义，"清除覆盖"按钮不再出现。
- **A2 投影**：把"建一次索引 + 逐模型投影"抽成可复用的实现
  （`provider.model_window_sources` / `project_model_window` /
  `project_model_windows`），基础 `get_info`、Hub 的手写响应、以及插件注册的
  **读取路径**共用同一份实现（与 `serialize_model` 的解析完全一致）。返回值一律
  是 `ModelInfo` / `ProviderInfo` 的副本，派生值不写实例、不进存储。
  - **投影放在读取路径而不是写入路径**（实现时的修正）：最初把 5 处
    `ProviderInfo(**snapshot.model_dump())` 的**存储**结果改成带投影，结果派生值
    会随 `provider_class(**info.model_dump())` 回灌到插件 provider 实例上
    （违反"不回写实例"）。改为在唯一的插件读取入口
    `PluginProviderRegistry.list_provider_infos()` 上做投影，存储保持干净；单个
    provider 的接口本来就materialize 实例并走 `get_info()`，无需额外处理。
  - 明确**不**改用 `get_info()` 替换 `ProviderInfo(**snapshot.model_dump())`：注册
    信息会被 `provider_class(**info.model_dump())` 回灌，`get_info()` 的构造是响应
    语义，换掉会丢字段。
- **A3 `use_catalog` 的读取**：新增类级钩子 `@classmethod context_catalog_enabled()`
  （默认 `True`），`_context_catalog_enabled()` 委托给它，Ollama 改为覆写类方法；
  注册路径（无实例）通过 `plugin_provider_registry._catalog_enabled()` 读取类方法，
  鸭子类型（非 Provider 子类）缺这个钩子时按默认 `True`。
  - 兼容性代价（记录在 15.6）：只覆写实例方法、不覆写类方法的第三方本地 provider，
    其**注册响应里的投影值**可能按"静态目录已启用"计算；运行时解析仍走实例方法，
    不受影响。另外，把 `_context_catalog_enabled` 整个方法拷进非 Provider 的
    鸭子类型替身时，必须同时提供类级钩子（本仓 `test_context_windows.py` 的
    `_CatalogProvider` 已按此调整）。

#### Fix B（P3）解析对称：catalog 槽也从 discovered 兜底

`resolve_window_from_info` 里让 catalog 与 auto_detected 采用同一种兜底（configured 有值就用 configured，为空才看 discovered）。理由：fetch 上报的窗口语义上属于目录数据，`merge_discovered_model` 已经把它写进 discovered 的 catalog 槽；不兜底就等于那个分支永不生效。

**不采用**"把 `max_input_length_catalog` 加进 `DISCOVERY_MODEL_FIELDS`"：那会把 fetch 值回写并持久化到已配置模型上，覆盖随包目录值（且 fetch 的 131072 不做占位符归一化，会盖掉静态目录值），风险更大。

#### Fix C（P3）投影不落盘

`provider_model_state` 增加 `strip_derived_model_state(model)`，在 `write_provider_snapshot` 已有循环里与 `prune_model_overrides` 一起调用（三个集合统一处理）。

**不采用**"给 `ModelInfo` 加 validator 清空派生字段"：响应里的投影也是经 `ProviderInfo` 校验同一个 `ModelInfo` 类落地的，validator 会把响应中的投影一起擦掉。

#### Fix D（P3）测试与类型

- **D1** `tests/unit/providers/test_provider_manager.py` 增加 manager 级 set→reload→clear→reload 用例（断言覆盖槽、`config_overrides`、解析值，以及磁盘 JSON 两态）。
- **D2** `test_context_windows.py:379` 守卫把 `extra_models` / `discovered_models` 也填满，使 `get_discovered_model_info` 的计数不再是恒 0（实现时确认能否直接断言"查找次数 == 0"）。
- **D3** `effective_max_input_length_source` 收紧为 `ContextWindowSource | None`（复用 `context_windows.ContextWindowSource`，无新类型）。
- **D4** 删掉 `serialize_model_state` 的死条件；恢复 `test_create_model_and_formatter_override.py` 里与改动无关的空行。

### 15.4 checklist（2026-09-18 完成）

后端

- [x] A1 `_prepare_plugin_registration`：默认模型窗口落 catalog 槽 + 注释说明
      （`provider.declared_window_to_catalog`）
- [x] A2 抽出 `model_window_sources` / `project_model_window` /
      `project_model_windows`；基础 `get_info`、Hub 响应、插件读取入口
      （`list_provider_infos`）共用
- [x] A3 类级 `context_catalog_enabled` + Ollama 覆写 + `_context_catalog_enabled`
      委托
- [x] B `resolve_window_from_info` 的 catalog 兜底 + docstring 改写
- [x] C `strip_derived_model_state` + 落盘路径调用
- [x] D3 `ContextWindowSource` 收紧、D4 死条件与无关空行

测试（后端）

- [x] 插件默认窗口：`max_input_length is None`、`max_input_length_catalog == N`、
      解析 `N / catalog`
      （`test_plugin_declared_window_is_catalog_data`）
- [x] 插件读取路径带投影，并覆盖类级钩子（本地插件不继承云端窗口）
      （`test_plugin_provider_response_carries_the_window_projection`）
- [x] 解析对称：仅发现态与"已配置 + 已发现"两条路径同值、已配置目录槽优先
      （`test_context_size_catalog_slot_falls_back_to_discovered_metadata`、
      `test_context_size_configured_catalog_slot_wins_over_discovered`）
- [x] 落盘-读回：模型键里不含 `effective_*`
      （`test_snapshot_write_drops_the_window_projection`）
- [x] manager 级 set→reload→clear→reload
      （`test_context_override_set_and_clear_survive_a_reload`）
- [x] O(N) 守卫覆盖三个集合
      （`test_provider_info_serialization_does_not_rescan_per_model`）
- [x] 既有迁移 / overlay / 目录用例全绿（234 passed in the focused run）

前端

- [x] 复跑 `vitest`（`ModelConfigEditor.test.tsx`、`ModelTokenFields.test.tsx`）
- [x] "插件场景用例"由既有 `ModelTokenFields.test.tsx` 的第一条覆盖
      （`max_input_length: null` + `effective_*` 有值 ⇒ 无"清除覆盖"且有继承提示），
      本次未改前端

文档

- [x] §15 据实更新（A2 改为读取路径投影、A3 鸭子类型代价）
- [x] §11 兼容性表补齐插件行与 `effective_*` 回传行；§12 后续项补第三轮补记
- [ ] PR 描述的 breaking-change 段落改为"插件默认模型的窗口仍是目录值（与 main
      同级），只有 `update_model_config` 写入的是用户覆盖"（GitHub 侧编辑，不在
      本次代码改动内）

验证

- [x] `pytest tests/unit/providers tests/unit/app/routers tests/unit/local_models
      tests/unit/agents/test_acp_runtime_provider.py`：23 failed / 1711 passed，
      `FAILED` 集合与基线（含 main）`comm` 双向差集为空
- [x] `flake8` 改动文件无新增；`black 23.3.0 --line-length=79` 全部 unchanged
- [x] `pylint -E` 改动文件 10.00/10；`mypy`（本机新版）改动模块无输出
- [x] 复跑本轮探针：插件解析来源 `catalog`、注册响应带投影、已配置模型解析到
      discovered 的 `500000 / catalog`、快照无 `effective_*`

### 15.5 验收口径

1. 插件默认模型：覆盖槽 `None`、目录槽为声明值、解析来源 `catalog`；console 不出现"清除覆盖"。
2. 注册信息路径的响应：每个模型都带 `effective_max_input_length` 与来源。
3. 仅通过 fetch 的 `max_input_length` 上报窗口时，已配置模型也能解析到该值（当前是 `131072 / default`）；已配置模型自身目录槽有值时仍以它为准（不被 fetch 覆盖）。
4. 落盘-读回后模型键里没有 `effective_*`。
5. manager 级 set→reload→clear→reload 的覆盖槽 / `config_overrides` / 解析值 / 磁盘四处一致。
6. 后端失败集合与基线差集为空。

### 15.6 不纳入本次

| 项 | 理由 |
| --- | --- |
| N2 的 422 数组 detail 渲染（`console/src/api/request.ts:24`） | 约束本身是改进（main 会静默存 500）；属通用错误渲染问题，另开更合适 |
| 只覆写**实例方法** `_context_catalog_enabled` 的第三方本地 provider 的注册响应投影精度 | ~~没有实例时无法调用实例方法；运行时解析不受影响~~ **已在第四轮处理（§16）**：这类注册直接不投影，宁可没有数字也不给错数字 |
| `model_catalog.json` 重生成（让"未采集"与"131072"可区分） | §12.1 已列为后续项，需改生成器 |
| 本地模型（llama.cpp `--ctx-size`）与静态目录的关系 | §12.3 已列为后续项 |

### 15.7 固定下来的不变量（供后续改动参照）

1. **三个槽位各只有一个写入者**：覆盖槽只由 `update_model_config` 写；`auto_detected`
   只由 provider 的探测代码写；`max_input_length_catalog` 只由目录装载边界、发现
   合并、插件注册边界写。
2. **派生值只在响应里存在**：`effective_*` 由 `project_model_windows` 在响应副本上
   生成，`write_provider_snapshot` 落盘前会 `strip_derived_model_state` 兜底。
3. **一个解析实现**：`resolve_context_window_details` 是唯一优先级实现，响应投影、
   compaction、usage%%、Agent 配置页全部经由它。
4. **一次响应一次建索引**：任何逐模型派生字段都必须用
   `model_window_sources` 建好的索引，且两个守卫用例（provider / Hub）断言
   "不做逐模型查找"。

## 16. 第四轮 Review：核实结论与修复（2026-09-20）

对 review 提出的 5 项逐条实测。**5 项全部真实**；其中 P2-1 是本 PR（第三轮修复）
引入的回归，P2-2 是本 PR 引入的插件侧行为变更，其余 3 项是描述/契约层面的问题。

### 16.1 核实结果

| 项 | 是否真实 | 本 PR 的角色 | 复现实据 |
| --- | --- | --- | --- |
| P2-1 插件："列表响应"与"运行时"给出不同窗口 | 是 | **第三轮引入**：第三轮把投影放到读取路径 `list_provider_infos`，它用类级钩子，而运行时用实例级钩子 | 造一个只覆写实例钩子的插件：列表投影 `200000 / catalog`，`get_context_size` = `131072`（`_context_catalog_enabled()` 返回 `False`）；console 的弹窗拿的正是列表对象 |
| P2-2 插件自定义 `max_input_length` 读回为 `None` | 是 | **第三轮引入**（A1 落位） | 插件在 `get_chat_model_instance` 里读 `get_model_info(id).max_input_length` 实测得到 `None`；`get_context_size` 给 `200000` |
| P3-1 PR 描述的数字 | 是 | 描述层面 | 实测打包目录：带 `max_input_length` 的 133 条里 **67 条**恰好是 131072 占位符；其中 **22 条**的静态目录窗口与占位符不同（`gpt-5` 的 catalog 值就是 131072，272000 是静态目录值） |
| P3-2 文档勾选与事实不符 | 是 | 描述层面 | 勾了 "Documentation updated"、又勾了 "Documentation (website)"，但 PR 无任何文档改动；`website/public/docs/config.en.md:469` 那条 `max_input_length` 与 `compact_threshold_ratio`（`config.py:1111`）同表，指 `AgentsRunningConfig.max_input_length`（`config.py:1930`），仅被 `daemon.py:121` 当显示兜底读 |
| P3-3 i18n 覆盖 | 是（一处描述需修正） | 第三轮引入（新增 6 个键） | 5 个 locale 的新键覆盖为 0（`maxInputLengthHint` 等既有键为 1）；`i18n.ts:51` 是 `fallbackLng: "en"`，所以非 en/zh 用户看到的是 **en 文案**（`from built-in catalog`），不是原始 id——原始 id 只在 en 也缺该 source 键时出现；`providerPlatformLocales.test.ts` 的 `requiredPaths` 未登记新键（该测试只检查登记项，因此不会失败，属维护约定） |

另外量化了 i18n 现状，用于判断"要不要补 5 个语种"：en/zh 各 3201 键（完整），
ja 2848、ru 2863、id 2427、vi 1863、pt-BR 2881，且 `models.*` 命名空间同样滞后
（en/zh 337，ja 301，vi 75）。结论：本仓的强制契约是 en+zh，其余语种异步补齐，
本轮不动它们的翻译。

### 16.2 修复

- **P2-1（代码）**：`plugin_provider_registry._catalog_decision()` 现在返回
  `bool | None`。当类的 MRO（`Provider` 之前）里只声明了实例钩子、没有声明类级钩子
  时返回 `None`，`list_provider_infos()` 对这种注册**不投影**（`effective_*` 留空），
  避免"列表显示 200000、运行时 131072"，以及"保存后提示行跳变"。
  同一类同时声明两个钩子时信任其类级答案。所有模型统一不投影（包括本可安全投影的
  目录槽模型），保持一条规则、不做部分猜测。
- **P2-2（契约 + 描述）**：`declared_window_to_catalog` 的 docstring 写明插件侧读法变更
  （改读 `max_input_length_catalog`，或调用 `get_context_size`），PR 描述的
  breaking-change 段落补充该条；新增断言 `live.get_context_size(...) == 400_000`
  固定"声明值仍可从运行时读到"。
- **P3-1（描述）**：改成"133 条中 67 条存的是 131072 占位符；其中 22 条静态目录给出
  更大的窗口，例如 `gpt-5` → 272000、`gpt-4.1` → 1047576"。
- **P3-2（描述 + 文档）**：取消 "Documentation (website)" 勾选（website 无相关内容），
  把设计文档与 PR 描述一起提交进 PR，使 "Documentation updated" 成立；
  `running.max_input_length` 这个"第三来源"记入后续项。
- **P3-3（前端契约）**：`providerPlatformLocales.test.ts` 的 `requiredPaths` 登记 6 个
  新键（含插值键与 4 个来源标签），锁定 zh/en 覆盖与插值一致性；5 个语种仍走 en
  fallback，并在 PR 描述中写明。

### 16.3 复测

| 手段 | 结果 |
| --- | --- |
| 后端切片（providers + app/routers + acp + local_models） | 24 failed / 1468 passed：其中 23 条与基线逐条相同，另 1 条是本机已知的负载抖动（`test_update_tool_config_keyless_provider_skips_credential_io`，单独跑 3/3 通过，且不 import 本次触碰的模块）；新增用例通过 |
| 聚焦 9 文件 | 346 passed, 1 skipped |
| 插件相关用例 | 17 passed（含"只覆写实例钩子 ⇒ 不投影"的新用例） |
| `vitest`（locale 契约 + 两个模型弹窗文件） | locale 20 passed；弹窗 10 passed |
| 静态检查 | `black 23.3.0 --line-length=79` unchanged；`flake8` clean；`eslint` clean |
| 探针 | 只覆写实例钩子的插件：列表投影 `(None, None)`、运行时 `131072`，注册信息未被写脏 |
