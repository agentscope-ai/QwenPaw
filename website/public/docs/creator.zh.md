# QwenPaw Creator

<p class="creator-lead">QwenPaw Creator 是一个 <strong>Agentic 视频创作平台</strong>：你负责提出目标、提供素材和把握方向，Agent 团队负责策划、生成、剪辑与合成，并在关键节点把决定权交还给你。</p>

- **Agent 贯穿全程**：编剧、导演、视觉开发、动效、剪辑等 Specialist 按项目状态协作，不是一次性生成后就结束；
- **你始终掌舵**：随时用一句话改变方向，也可以直接在时间线上手动精修；
- **两类素材都能开始**：从一句想法生成短剧，或从一批现有视频剪出成片。

Creator 原生支持 [Qwen-MM-Plugins](https://github.com/QwenLM/Qwen-MM-Plugins)，并在创作链路中复用其三项官方能力：`core` 提供图像、视频、文档和 3D 模型的动态分辨率读取，并覆盖 OCR、grounding、分割、ASR 等基础视觉能力；`video-memory` 提供面向长视频问答的分层图记忆；`video-edit` 提供视频编辑工作流以及图像、视频和音频生成。

<figure class="creator-figure">
  <img class="creator-shot" src="https://img.alicdn.com/imgextra/i4/O1CN01I6Fa3321Z8pCMUYyO_!!6000000006998-2-tps-2400-1240.png" alt="Creator 从创意生成和从素材剪辑的两条工作流" />
  <figcaption>Creator 只有一个项目入口；进入后根据任务选择「从创意生成」或「编辑已有素材」，再进入统一的 Agentic 创作闭环。</figcaption>
</figure>

---

## 3 分钟开始第一个项目

### 1. 打开 Creator

Creator 通过 QwenPaw 的 **Apps（应用中心）** 安装和打开。启动 QwenPaw 并进入控制台（默认 `http://127.0.0.1:8088/`），在左侧选择 **Apps**；找到 **QwenPaw Creator** 并点击安装，安装完成后从同一位置打开。

<figure class="creator-figure">
  <img class="creator-shot" src="https://img.alicdn.com/imgextra/i1/O1CN01C3nur6L5b7C4fX2q_!!6000000006822-2-tps-2300-1520.png" alt="QwenPaw Apps 页面中的应用导航和 QwenPaw Creator 应用卡片" />
  <figcaption>在 QwenPaw 的 Apps 页面找到 QwenPaw Creator，完成安装后即可从同一位置打开。</figcaption>
</figure>

### 2. 配置模型

首次使用前，点击首页输入区右下角的 **模型配置**（或跟随首次引导）完成接入。按场景准备能力即可：

| 场景                  | 需要的模型能力            | 在流程中的作用                               |
| --------------------- | ------------------------- | -------------------------------------------- |
| 所有场景              | LLM（必选）               | 创作总纲规划、分镜脚本与 Agent 对话的大脑    |
| 短剧 / 通用生成       | 图片生成 + 视频生成 + VLM | 生成分镜图与视频画面，VLM 负责画面质量回看   |
| 剪辑 / 上传素材       | VLM                       | 理解上传的图片、视频素材画面内容             |
| 素材含人声 / 需要转写 | ASR                       | 将语音识别成文字，用于剪辑与字幕             |
| 旁白配音 / 数字人口播 | TTS + 数字人              | 合成旁白与台词；由音频驱动数字人口播视频片段 |

当前模型矩阵按能力展示：

- **LLM / VLM**：OpenAI 兼容协议、DashScope / 百炼、Anthropic Claude、DeepSeek、Google Gemini、百度千帆、火山引擎和自定义提供商；
- **Grounding**：Serper（Google）或 Tavily；验证模型可复用 LLM / VLM，也可单独配置；
- **图片生成**：OpenAI 兼容协议或 DashScope；
- **视频生成**：DashScope 的 `wan2.7`、`happyhorse-1.1` 会按元素类型自动选择 t2v / i2v / r2v；火山引擎 `doubao-seedance-2.0` 提供 r2v；
- **ASR**：DashScope Fun-ASR、DashScope Qwen3-ASR 或 OpenAI Whisper；
- **TTS / 数字人**：DashScope Qwen-TTS、CosyVoice，以及 `wan2.2-s2v`（并提供 `wan2.2-s2v-detect` 免费人脸检测）；
- **Embedding**：DashScope `qwen3-vl-embedding`，用于资产检索与长素材记忆。

### 3. 把目标和素材交给 Agent

1. **描述目标**：例如「做一个快节奏、强冲突、结局温暖的短剧」，或「把这些猫咪视频剪成 1 分钟精彩合集」；
2. **提供素材（可选）**：添加文件、文件夹或链接。进入项目后，它们会成为可管理、可引用、可追踪的项目资产；
3. **选择规格**：短剧 / 剪辑 / 通用，以及分辨率、画幅；
4. 点击「启动 Agent」，Agent 开始策划并进入工作台。

<figure class="creator-figure">
  <img class="creator-shot" src="https://img.alicdn.com/imgextra/i1/O1CN01tdK9SHSDDJC3thAe_!!6000000005409-2-tps-1920-1080.png" alt="Creator 首页中目标描述、素材导入、创作类型、画幅和模型配置区域" />
  <figcaption>一个输入区同时承载目标、素材和限制；这只是项目的启动动作，后续素材会进入可追踪的资产与方案结构。</figcaption>
</figure>

---

## 工作台：选中即上下文，也能手动精修

Creator 的 Agentic 能力不是额外悬浮在编辑器旁边：**项目里的内容本身就是 Agent 可以操作的上下文**。当前选中的片段 / 字幕 / 动效 / 转场 / 资产会作为关联对象出现在 AgentDock 输入区上方；时间点、时间区间和划选文本可通过选择浮层加入输入框。你也可以用 `@` 引用其他对象。描述修改意图后，Agent 会针对这些精确对象工作。

<figure class="creator-figure">
  <img class="creator-shot" src="https://img.alicdn.com/imgextra/i1/O1CN0109MaKHOvgHC3thAe_!!6000000000337-2-tps-1920-1080.png" alt="打开元素详情后，将时间线与多个项目元素关联到 AgentDock 输入区的 Creator 工作台" />
  <figcaption>当前项目元素会关联到 AgentDock；精确时间区间以引用片段进入输入框。既能用自然语言针对上下文修改，也能继续在工作台中手动精修。</figcaption>
</figure>

| 你选择的内容                           | 如何成为 Agent 上下文                             | 仍然可以手动做什么                               |
| -------------------------------------- | ------------------------------------------------- | ------------------------------------------------ |
| 时间线上的时间点或拖拽框选的时间段     | 通过选择浮层加入输入框，携带精确时间与对象引用    | 继续调整片段起止、顺序、轨道关系与整体节奏       |
| 片段、字幕、动效、转场、资产或生成产物 | 当前选中对象自动关联；也可以在输入框中用 `@` 引用 | 打开详情编辑时间、层级、位置、透明度和具体文案等 |
| 页面中的一段文本                       | 划选后通过选择浮层加入输入框                      | 直接修改原字段，或要求 Agent 只改选中的这一处    |

这意味着时间线、内容元素、资产和文本都不是只能被 Agent “看见”的静态结果，而是可以被引用、定位、修改和审阅的项目对象。顶部的 **资产库** 用于浏览原始素材与生成产物；**视频预览 / 合成成片** 则负责检查和输出当前方案。

### 与 Agent 协作的三个技巧

- **用 `@` 引用对象**：引用分镜、素材等对象作为上下文；当前选中对象也会自动带入对话；
- **随时干预**：例如「只把第二段字幕改成……」或「开场增加阳光射线动效」，Agent 会读取当前项目状态后做关联修改；
- **必要时立即停止**：执行中的任务可以通过停止按钮中断。

---

## 两条典型创作路径

### 短剧生成：从零到成片

1. **剧本与分镜**：编剧 / 导演 Specialist 根据目标生成剧本，并拆成场景、角色、动作与台词；
2. **一致性资产**：为角色生成锚点形象图、为场景生成基准图；
3. **分镜图与视频**：以资产图为参考逐镜生成画面，再调用参考生视频（r2v）模型生成片段；
4. **合成**：片段就绪后进入统一时间线并生成完整成片。

### 素材剪辑：从现有素材到成片

1. **理解素材**：VLM（含人声时结合 ASR）识别内容与精彩时刻；
2. **形成剪辑方案**：Agent 选择片段、编排时间线，并补充字幕、动效与转场；
3. **人机精修**：你可以直接点选片段手动调整，也可以让 Agent 代劳；
4. **预览并合成**：确认方案后生成成片。

---

## 审阅：每一处 Agent 改动都有去留

Agent 生成的媒体和修改的文本会进入决策托盘；你手动编辑的内容默认直接生效，不额外进入审阅。

<div class="creator-media-grid">
  <figure class="creator-figure">
    <img class="creator-shot" src="https://img.alicdn.com/imgextra/i1/O1CN01JCRfcQXIgwB1qYPq_!!6000000001152-2-tps-910-780.png" alt="决策托盘中的生成视频审阅卡" />
    <figcaption><strong>媒体审阅</strong>：在决策托盘中直接预览生成的视频，选择「保留」或「撤销」，也可批量处理。</figcaption>
  </figure>
  <figure class="creator-figure">
    <img class="creator-shot" src="https://img.alicdn.com/imgextra/i2/O1CN01Yb3MTwmx9zF1roSO_!!6000000001528-2-tps-920-760.png" alt="展示修改前后内容的文本审阅卡" />
    <figcaption><strong>文本审阅</strong>：直接看到修改前后，也可以「查看」并跳转到原文上下文。</figcaption>
  </figure>
</div>

审阅项会尽量跳到准确的生成上下文，例如角色图对应资产详情、分镜图对应分镜详情、文本修改对应原文位置。

### 生产确认：付费操作先看预计费用

调用付费图片 / 视频生成模型前，Agent 会展示**生产确认卡**，列出对象、模型、参数与本地估算费用。只有点击「继续」才会提交计费任务；点击「取消」则终止本次制作。

<figure class="creator-figure">
  <img class="creator-shot creator-shot--compact" src="https://img.alicdn.com/imgextra/i1/O1CN01yhmd1CI7mCD1qInk_!!6000000007002-2-tps-908-760.png" alt="显示对象、模型、参数、预估费用、继续和取消按钮的生产确认卡" />
  <figcaption>生产确认卡集中展示对象、模型、参数和预估费用；确认后才会提交计费任务。</figcaption>
</figure>

> 💰 费用为按模型公开单价在本地计算的参考值，实际费用以服务商账单为准；此确认可在模型配置中关闭。

---

## 预览、管理与导出

- **成片预览**：在工作台点击「视频预览」，或在「我的项目」卡片上点击「预览」；
- **合成与导出**：使用工作台右上角的「合成成片」，完成后通过「下载 / 导出」保存最终视频；
- **管理项目**：「我的项目」集中展示创作类型、画幅、分辨率与更新时间，并支持排序。

<figure class="creator-figure">
  <img class="creator-shot" src="https://img.alicdn.com/imgextra/i1/O1CN01VO33ftbLHSF3thAe_!!6000000003520-2-tps-1920-1080.png" alt="包含项目管理页面和完整成片预览窗口的 Creator 全局界面" />
  <figcaption>「我的项目」集中展示项目状态和创作规格；打开「预览」即可在完整弹窗中检查成片。</figcaption>
</figure>

---

## 附录：安装与运行环境

请打开 QwenPaw 控制台的 **Apps（应用中心）**，找到 **QwenPaw Creator** 并点击安装；安装完成后，直接从 Apps 打开 Creator。

Creator 会使用若干本地工具，但不会改动系统安装：`ffmpeg` 负责媒体处理与合成（可用 `CREATOR_FFMPEG_PATH` 指定，否则回退系统 `ffmpeg` 或 `imageio-ffmpeg`）；`jq` 支撑 Agent 对项目文件的结构化编辑（`CREATOR_JQ_PATH` 或 `PATH`）。依赖缺失时 Creator 以降级模式启动，可通过 `GET /api/qwenpaw-creator/health` 查看缺失项。
