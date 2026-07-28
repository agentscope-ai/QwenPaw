# 动态动效生成（Dynamic Motion Overlays）技术实现方案

> 状态：已实现并通过真实模型验证 · 分支未提交（按要求不 commit / 不 push）

## 1. 背景与目标

Creator 此前的动效包装（`pet_os` / `interview_summary` 等 Overlay）是**固定模板**：
样式单一、与素材内容无关、无法适配不同画面。参考
[heygen-com/hyperframes](https://github.com/heygen-com/hyperframes) 的核心思路——
**动效本质是代码，可以由多模态模型按画面动态生成**——本方案把"看画面 → 写动效代码 →
确定性渲染合成"引入 Creator，并满足以下约束：

1. 通用：不针对特定 case，任何视频片段都走同一条链路；
2. 按需：模型对每个片段自主判断"要不要动效"，不需要就跳过；
3. 贴合：动效的配色、形状、位置、大小来自对**真实画面帧**的观察，不遮挡画面主体；
4. 高效：有合理的插入时机与并发/超时控制；
5. 无侵入：不破坏现有 data-driven 结构与 agent 协作；
6. prompt 只描述 agent 可见的概念，不引用内部实现。

第二轮迭代（用户检查成片后反馈）进一步明确了产品定位：

- **文字 Overlay（`pet_os` / `interview_summary`）是主角**：固定模板样式单一显眼，
  改为由模型按画面动态生成 fancy 字幕卡；
- **装饰动效是锦上添花**：只在恰当的少数位置出现，不要每个片段都有（稀疏化）。

## 2. 方案选型（综合评估）

| 候选方案 | 评估 | 结论 |
| --- | --- | --- |
| A. 扩充固定模板库（参数化模板） | 实现简单，但表达力受模板集合限制，无法真正"贴合任意画面"，违背通用性要求 | 否 |
| B. 生成 Lottie/SVG 动画 JSON | 依赖模型对 Lottie schema 的掌握，出错率高、可校验性差、生态工具重 | 否 |
| C. **生成自包含 HTML+CSS 动画文档 + seek-and-capture 确定性渲染**（hyperframes 同思路） | HTML/CSS 是 LLM/VLM 最熟练的"绘图语言"；文档自包含可静态校验（禁 script/外链）；CSS 动画可被逐帧 seek，渲染完全确定；透明背景 PNG 序列可无损叠加到任何视频 | **采用** |

选 C 的关键理由：**生成侧最大自由度 + 渲染侧最大确定性**。模型只负责产出一个受约束的
纯 CSS 动画文档；渲染器暂停时钟、逐帧 seek、逐帧截图，输出与模型能力完全解耦。

## 3. 数据结构：动效是 data-driven 整体的一部分

只扩展了 Overlay 这一个 element 的 creation 定义，其余数据结构零改动。

### 3.1 `MotionGraphic`（新增，`services/project_files/models.py`）

```python
class MotionGraphic(StrictModel):
    format: Literal["html_css"] = "html_css"   # 预留未来格式扩展
    html: str            # 自包含 HTML 文档，透明背景，仅 CSS @keyframes 动画
    fps: int = 24        # 8~60
    loop: bool = True
    design_notes: str    # 模型的设计意图说明（审阅/前端展示用）
```

### 3.2 挂接点：`OverlayCreation.motion`

```python
class OverlayCreation(StrictModel):
    overlay_kind: "pet_os" | "interview_summary" | "motion" | "media"
    ...
    motion: MotionGraphic | None = None   # media 之外的 overlay_kind 均可携带
```

`motion` 字段有两种语义（校验器保证不出现在 `media` 上）：

- `overlay_kind="motion"`：`motion` 就是这个装饰 Overlay 的全部内容；
- `overlay_kind="pet_os" / "interview_summary"`：`motion` 是该文字 Overlay 的
  **动态生成样式**——`text` 始终是权威内容，`motion` 只是它的呈现方式；
  渲染时优先使用 `motion` 字幕卡，渲染失败自动**回退固定模板**，成片永远有字幕。
- 动效 Overlay 与其他 Overlay 完全同构：同样是 `TimelineElement`，用绝对 `span`
  表达出现时段、`location`（归一化坐标）表达位置大小、`z_index` 表达叠放次序、
  `enabled` 可整体停用。**读、改、删全部复用既有的 `jq_project` / `read_project`
  工具与校验管线**，前端契约同步扩展（`ui/src/contracts/creator/projectSnapshot.ts`
  的 `MotionGraphicDocument`）。

这样"动效"就像 `pet_os` 一样是 project.json 的普通组成部分：可审阅、可回放、可
增量修改，不引入任何第二存储或旁路状态。

## 4. 生成链路：`design_motion_overlays` 专家工具（两 Pass）

新增 specialist 工具（`services/specialist_tools.py`），仅授权给 AI 剪辑导演角色，
实现在 `services/media_files/motion_design.py`：

```
design_motion_overlays(targetRef=timeline:<id>, brief?, elementIds?, maxDecorations?)
├─ Pass A 文字样式化（主角，逆向需求的核心）
│  对 Timeline 上每个 pet_os / interview_summary Overlay（信号量并发 3）：
│  1. 帧观察  抽取该 Overlay 时段内的 2~3 张真实画面帧
│  2. VLM 设计 帧 + 台词原文 + 情绪基调 + 盒子像素尺寸 + brief → 字幕卡 html
│  3. 三重硬校验（见 §4.1）+ 静态校验（禁 script/外链/emoji）
│  4. 失败带具体原因反馈重试（最多 3 次）；通过后写入该 Overlay 的 motion 字段
│  已有样式返回 already_styled；全部失败返回 failed（渲染时回退固定模板）
└─ Pass B 稀疏装饰（配角）
   1. 单次纯文本挑选调用：把全部片段的剪辑意图列给模型，
      让它只挑最值得点缀的 ≤maxDecorations 个（默认 3，上限 8，可传 0 关闭）
   2. 仅对选中片段走"帧观察 → VLM 设计 → 校验 → 探针 → 重试"链路，
      以 `<editElementId>-motion` 写入 overlay_kind=motion 的装饰 Overlay
   同一片段已有装饰返回 already_exists；模型判断不需要则跳过
└─ 返回逐项摘要（styled / designed / skipped / already_* / failed + 原因）
```

### 4.1 字幕卡三重质量硬校验（真实重跑中逐步发现并沉淀）

文字卡是成片主角，对它的要求比装饰严格得多；每条校验失败都会把具体数值/原因
作为 feedback 注入重试：

| 校验 | 阈值 | 防的问题（均为真实跑出来的 bad case） |
| --- | --- | --- |
| 可见覆盖率 | `_TEXT_CARD_MIN_COVERAGE = 0.3` | 模型在大盒子里画一张小卡片，成片里字幕小到看不清 |
| 边缘接触率 | `_TEXT_CARD_MAX_EDGE_CONTACT = 0.02` | 大字号单行不换行，台词横向溢出视口被裁（"[这水]里有鱼吗"） |
| 可见文本白名单 | 台词必须一字不差出现，多余可见文字 ≤6 字符 | 导演把任务元数据写进 brief，设计模型把 "os-04-pond →" 之类的说明画进卡片 |

实现要点：

- 覆盖率与边缘接触率由渲染探针的几何分析给出（`motion_overlay.py` 的
  `_alpha_plane_stats`）：ffmpeg `alphaextract` 抽出探针帧的 alpha 平面，
  可见占比 = 非透明像素比例；边缘接触率 = 四条最外沿像素行/列中可见像素占比
  的最大值（高值意味着内容贴到/超出视口正在被裁）；几何不匹配时返回
  `(-1.0, -1.0)` 疑罪从无，探针自身失败不会误拒文档；
- 可见文本校验在静态校验层（`motion_design.py` 的 `_validated_design`）：
  剥离 `<style>`/`<head>` 与标签后取可见文本做 verbatim 包含检查
  （CSS `content` 里的文字不算数），再检查去除台词后的剩余可见文字长度；
- prompt 同步明令：整句台词必须完整落在视口内，一行放不下就换行并调小字号；
  卡片上的文字只能是台词本身，绝不把任务说明、Element ID 等元数据写进卡片。

其余要点：

- **按需与稀疏**（要求 2 + 二轮反馈）：装饰由 Pass B 的预算机制从源头限额，
  而不是靠 prompt 口头约束；选择权交给模型（看全部片段意图后挑“最值得”的），
  选不满预算也是正常结果。验证 case 中 10 个片段只选了 3 处（开场/高潮/结尾）。
- **贴合画面**（要求 3）：模型看到的是该片段的真实帧，prompt 要求配色从画面取、
  形状与主题呼应、位置避开主体（通常角落/留白）、面积一般不超过画面 1/4。
  `location` 用归一化坐标（x/y/width/height/anchor/opacity），与现有 Overlay
  的 `ElementLocation` 完全一致。
- **幂等**：文字 Overlay 已有样式返回 `already_styled`、同一片段已有装饰返回
  `already_exists`，不重复消耗模型调用；重跑安全。`elementIds` 可定向只重做
  个别 Element（配合删掉旧 motion 字段，支持对单张卡的反馈迭代）。
- **效率**（要求 4）：并发 3 路设计；文字卡 3 次/装饰 2 次尝试上限；探针只渲
  少量帧；生成阶段与 `ai_edit` 渲染解耦，失败只影响单个 Element
  （文字卡降级为固定模板、装饰降级为无动效，都不阻塞成片）。

## 5. 渲染链路：seek-and-capture 确定性合成

实现在 `services/media_files/motion_overlay.py`，被 `ai_edit`
（`local_execution.py`）在准备每个视频分段时调用：

```
render_motion_overlay(html, fps, loop, video_size, appear_at, duration, location)
  1. 子进程 worker（Playwright + headless Chromium，stdin/stdout JSON 协议）
     - 加载文档后注入样式暂停所有 CSS 动画
     - 逐帧设置 animation currentTime（seek），逐帧 omit_background 截透明 PNG
     - 帧数上限 240，有效 fps 下限 6（长片段自动降帧 + loop 循环补齐）
  2. ffmpeg 把 PNG 序列按 location 归一化坐标缩放、定位，
     以 `appear_at`/`duration` 窗口 overlay 到分段视频上（alpha 混合）
```

与时间轴的对接（`local_execution.py`）：

- **文字 Overlay**：构造 pet_os / interview_summary 叠加时，`motion` 字段存在
  则走动态字幕卡渲染；渲染失败自动回退固定模板（只记 warning），
  保证成片任何情况下都有字幕。
- **装饰 Overlay**：`_edit_motion_overlays()` 在构造每个 Edit 输入时，收集**与该
  片段 span 相交**的全部启用状态 motion Overlay，按 `z_index` 排序依次合成
  （支持多个动效叠加）；`appear_at`/`duration` 由两个 span 的交集换算，
  语义与其他 Overlay 一致。
- 渲染失败仅记 warning 并保留原片段，绝不让动效问题毁掉成片渲染。

## 6. 插入方式与 agent 协作（要求 4、5）

AI 剪辑导演的工作流只插入了一个**可选步骤**（prompt 第 6 步）：

```
写入 Edit/Overlay Elements → （可选）design_motion_overlays → ai_edit 渲染
```

- 导演在 Edit Element 写入并验证后决定是否调用该工具；用户明确不要包装、或内容
  严肃不宜点缀时直接跳过——整条原有链路（素材理解 → 剪辑选择 → 渲染 → 审阅）
  完全不变。
- 工具把结果直接写入 project.json，导演用 `read_project` 复核，可用 `jq_project`
  微调 span/location/z_index 或禁用某个动效——与它处理其他 element 的方式一致。
- 其他 specialist、其他 Overlay 类型、渲染缓存、审阅机制均不感知此特性；
  backend 全量测试全部通过。

## 7. 可靠性工程（真实迭代中发现并修复）

| 问题 | 根因 | 修复 |
| --- | --- | --- |
| 渲染 worker 偶发挂死（macOS headless Chromium） | 动效 html 含 **emoji** 时颜色字体光栅化高概率挂死（挂点漂移于 goto/evaluate，与 GPU/route 无关；launch flags 缓解不可靠） | ① 校验层直接拒绝含 emoji 的设计（`_EMOJI_PATTERN`，不误伤 CJK）② prompt 明确要求"不要使用 emoji，需要具象图形用纯 CSS 画"③ 拒绝原因通过 feedback 重试，模型会自动改产纯 CSS 方案（实测重试后 100% 通过） |
| 超时后 Chromium 孤儿进程残留 | 子进程超时只杀 python，浏览器进程组存活 | worker 以 `start_new_session=True` 启动，超时/异常时 `os.killpg(SIGKILL)` 清理整个进程组 |
| 逐帧渲染开销不可控 | 长片段 × 高 fps 帧数爆炸 | 帧数硬上限 240 + 动态降帧（≥6fps）+ loop 循环补齐 + 逐帧超时预算（120s 基础 + 3s/帧） |
| 部分动效合成后全透明（渲染"成功"但成片里看不见） | 模型常写 `body{height:100%}` 但未给 `html` 设高度 → body 高度塌陷为 0 → `overflow:hidden` 裁掉全部内容；且探针只查动画数量从不查可见像素 | ① 渲染 worker 注入样式补 `html,body{width:100%;height:100%}`（存量文档无需重新设计即恢复可见）② 探针增加可见像素检测（截动画周期 25%/60% 两帧，ffmpeg alphaextract 验 alpha），全透明则返回可行动的修改建议进入重试 ③ 设计 prompt 补充布局要求（显式设置 html/body 宽高，用 vw/vh 百分比布局） |
| 动效设计对比度不足（白色半透明元素叠亮色画面几乎不可见）/ 入场动画前几秒在画布外 | VLM 设计时未充分考虑背景亮度与入场路径 | 通过对话反馈让导演重新设计单个动效（真实评估 → 反馈 → 重设计 → 重渲染的迭代闭环，不需要改代码） |
| 字幕卡在大盒子里画得很小，成片里看不清 | 模型不知道自己的输出会被缩放到多大，倾向于保守留白 | 探针几何分析 + 可见覆盖率 ≥0.3 硬校验，失败时把实测百分比反馈给模型重试 |
| 台词单行溢出视口被裁（v5 成片抽帧发现 2/10 张卡） | 大字号 + 不换行，稳定状态就超宽；探针此前只查可见占比查不出溢出 | 探针新增边缘接触率检测（`_alpha_plane_stats`）+ ≤0.02 硬校验 + prompt 强制换行规则；重跑时实测拦截到一次超标设计并重试成功 |
| 任务元数据被画进卡片（v6 抽帧发现 "os-04-pond →" 上卡） | 导演把 Element→台词映射说明写进 brief，设计模型照画；旧 verbatim 校验只检查"包含台词"不检查"只有台词" | 可见文本白名单校验（剥标签后多余可见文字 ≤6 字符拒绝）+ prompt 明令禁止元数据上卡 |
| 严格校验使部分卡单次调用内 3 次尝试后仍 failed | 质量门槛与模型一次成功率的天然张力 | 设计为可恢复：failed 逐项带原因返回，导演会自主用 `elementIds` 定向补跑直到全部 styled（真实重跑中观察到的收敛行为）；即使最终 failed 也只是回退固定模板 |

## 8. prompt 设计原则（要求 7）

- 导演 prompt（`ai_editing_director.system.txt`）只描述 agent 可见的事实：工具名、
  project.json 内的字段（`creation.motion`、`overlay_kind=motion`、span/location/
  z_index）、工具返回语义（already_exists）；不出现 runtime、渲染器、Playwright
  等内部概念。
- 设计 prompt（VLM 侧）中的每条"不要"都对应模型可控的输出内容（不要 script 标签、
  不要外链资源、不要 emoji），并给出替代做法；没有出现"禁止使用某个不存在工具"
  之类的指令。
- prompt 变更同步更新了 hash 白名单（`prompts/__init__.py`）。

## 9. 真实模型验证

开发环境首次安装请执行 `scripts/dev.sh install`；该脚本除安装
Python `playwright` 依赖外，也会执行 `python -m playwright install chromium`
安装实际渲染所需的浏览器。非开发脚本部署也必须额外执行该
Playwright 命令；只安装 `requirements.txt` 不会下载 Chromium。浏览器
不可用时，动效渲染会显式返回警告，文字 Overlay 回退到固定气泡模板。

### 9.1 第一轮（基础链路）

- **单链路验证**：用已配置的 VLM key（qwen3.6-plus）对三个真实猫咪片段跑完整
  "观察→设计→校验→探针→渲染→合成"链路，三段全部成功；
  逐帧视觉评估符合"点缀不遮主体、配色贴画面"原则。
- **端到端 case**："1 分钟猫咪精彩合集"通过标准 API 全流程驱动（建项目 → URL
  素材注册 → 用户消息），素材理解产出 17 场景/13 事件时间线；成片用 ffmpeg
  difference 差分客观确认动效真实合成进成片。

### 9.2 第二轮（用户反馈后：文字卡 fancy 化 + 装饰稀疏化）

复用同一项目已持久化的素材理解（不重跑），只通过对话驱动导演
"清除旧样式 → design_motion_overlays → 重渲染"，共三轮迭代：

| 轮次 | 驱动方式 | 结果与发现 |
| --- | --- | --- |
| v5 全量重做 | 一条对话消息（maxDecorations=3） | 10/10 文字卡 styled + 3 装饰（开场屋顶/挖掘机/结尾树冠）；抽帧评估 8/10 完美，2 张卡台词溢出视口被裁 |
| v6 修溢出 | 新增边缘接触率校验后，`elementIds` 定向重做 2 张卡 | 溢出修复（校验实测拦截一次超标设计）；但发现其中 1 张卡把任务元数据画进了卡片 |
| v7 修元数据 | 新增可见文本白名单校验后，定向重做 1 张卡 | 全部抽帧验证通过：每张卡只含台词、完整落在视口内、样式各异且贴合画面；装饰徽标醒目不喧宾 |

验证中同时观察到 agent 协作的真实鲁棒性：委派偶发模型错误时主 agent 自动
精简任务重试；工具返回部分 failed 时导演自主定向补跑直到全部 styled。

- **回归**：backend 全量 pytest 通过（含新增的几何分析与文本校验单测，
  media_files 模块 42 passed），现有功能不受影响。

## 10. 涉及文件

| 文件 | 变更 |
| --- | --- |
| `backend/services/project_files/models.py` | 新增 `MotionGraphic`；`OverlayCreation.motion` 字段与校验（文字 Overlay 可携带样式） |
| `backend/services/media_files/motion_design.py` | 新增：两 Pass 设计链路（文字样式化/稀疏装饰挑选/三重硬校验/反馈重试/写入） |
| `backend/services/media_files/motion_overlay.py` | 新增：seek-and-capture 渲染器（子进程 worker + ffmpeg 合成）；探针几何分析（覆盖率/边缘接触率） |
| `backend/services/media_files/local_execution.py` | 确定性后端渲染的分段准备阶段合成 motion Overlay；文字 Overlay 优先用 motion 样式、失败回退固定模板 |
| `backend/services/specialist_tools.py` | 注册 `design_motion_overlays` 工具（仅剪辑导演可用） |
| `backend/services/file_agent_runtime/prompts/ai_editing_director.system.txt` | 工作流插入可选动效步骤与使用原则 |
| `backend/services/file_agent_runtime/prompts/__init__.py` | prompt hash 白名单同步 |
| `backend/tests/media_files/test_motion_design.py` 等 | 设计校验/几何分析/可见文本校验等单测 |
| `ui/src/contracts/creator/projectSnapshot.ts` | 前端契约新增 `MotionGraphicDocument` / `motion` 字段 |
| `requirements.txt` | 渲染依赖（playwright） |
