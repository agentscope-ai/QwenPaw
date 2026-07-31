# QwenPaw Creator

[English](README.md) | 中文

![QwenPaw Creator：Agentic 视频创作平台](https://img.alicdn.com/imgextra/i1/O1CN01fqzbpn1uZs98aHllk_!!6000000006052-2-tps-1600-600.png)

<p class="creator-lead">QwenPaw Creator 是一个 <strong>Agentic 视频创作平台</strong>：你负责提出目标、提供素材和把握方向，Agent 团队负责策划、生成、剪辑与合成，并在关键节点把决定权交还给你。</p>

- **Agent 贯穿全程**：编剧、导演、视觉开发、动效、剪辑等 Specialist 按项目状态协作，不是一次性生成后就结束；
- **你始终掌舵**：随时用一句话改变方向，也可以直接在时间线上手动精修；
- **两类素材都能开始**：从一句想法生成短剧，或从一批现有视频剪出成片。

<figure class="creator-figure">
  <img class="creator-shot" src="https://img.alicdn.com/imgextra/i4/O1CN01I6Fa3321Z8pCMUYyO_!!6000000006998-2-tps-2400-1240.png" alt="Creator 从创意生成和从素材剪辑的两条工作流" />
  <figcaption>Creator 只有一个项目入口；进入后根据任务选择「从创意生成」或「编辑已有素材」，再进入统一的 Agentic 创作闭环。</figcaption>
</figure>

---

## 3 分钟开始第一个项目

### 1. 打开 Creator

Creator 通过 QwenPaw 的 **Apps（应用中心）** 安装和打开。启动 QwenPaw 并进入控制台（默认 `http://127.0.0.1:8088/`），在左侧选择 **Apps**；找到 **QwenPaw Creator** 并点击安装，安装完成后从同一位置打开。

<figure class="creator-figure">
  <img class="creator-shot" src="https://img.alicdn.com/imgextra/i1/O1CN01MXPKfU25B6V6preKc_!!6000000007487-2-tps-850-620.png" alt="QwenPaw Apps 页面中的 Apps 导航和 QwenPaw Creator 应用卡片" />
  <figcaption>在 QwenPaw 的 Apps 页面找到 QwenPaw Creator，完成安装后即可从同一位置打开。</figcaption>
</figure>

### 2. 配置模型

首次使用前，点击首页输入区右下角的 **模型配置**（或跟随首次引导）完成接入。按场景准备能力即可：

| 你的创作方式       | 需要的模型能力                               |
| ------------------ | -------------------------------------------- |
| 所有场景           | 大语言模型（LLM）                            |
| 短剧等生成类创作   | 图片生成、视频生成、视觉语言模型（VLM）      |
| 上传现有素材做剪辑 | VLM；素材含人声时建议同时配置语音识别（ASR） |

支持 OpenAI 协议、百炼、Claude、DeepSeek、Gemini、千帆、火山引擎、自定义等 LLM / VLM 接入；图片、视频与 ASR 的可用提供商会在模型配置界面按能力展示。

### 3. 把目标和素材交给 Agent

1. **描述目标**：例如「做一个快节奏、强冲突、结局温暖的短剧」，或「把这些猫咪视频剪成 1 分钟精彩合集」；
2. **提供素材（可选）**：添加文件、文件夹或链接。进入项目后，它们会成为可管理、可引用、可追踪的项目资产；
3. **选择规格**：短剧 / 剪辑 / 通用，以及分辨率、画幅；
4. 点击发送，Agent 开始策划并进入工作台。

<figure class="creator-figure">
  <img class="creator-shot" src="https://img.alicdn.com/imgextra/i3/O1CN01SQFiPY25CTgmT9bXb_!!6000000007490-2-tps-2100-1320.png" alt="Creator 首页中目标描述、素材导入、创作类型、画幅和模型配置区域" />
  <figcaption>一个输入区同时承载目标、素材和限制；这只是项目的启动动作，后续素材会进入可追踪的资产与方案结构。</figcaption>
</figure>

---

## 工作台：选中即上下文，也能手动精修

Creator 的 Agentic 能力不是额外悬浮在编辑器旁边：**项目里的内容本身就是 Agent 可以操作的上下文**。你可以选中时间线上的时间点、拖拽框选时间段、点击片段 / 字幕 / 动效 / 转场 / 资产，也可以划选页面文本，然后点击「添加到对话」。选中对象会进入 AgentDock 的上下文；在输入框中描述修改意图，Agent 就会针对这个对象工作。

<figure class="creator-figure">
  <img class="creator-shot" src="https://img.alicdn.com/imgextra/i1/O1CN01XdZVAE26qc0mbr8J5_!!6000000007713-2-tps-2400-1800.png" alt="选择时间线、片段或文本并加入 AgentDock 上下文，同时保留手动编辑能力的 Creator 工作台示意" />
  <figcaption>同一个项目对象有两种并行操作方式：加入 AgentDock 上下文，用自然语言精确修改；或打开详情，直接编辑字段并应用修改。</figcaption>
</figure>

| 你选择的内容                           | 如何成为 Agent 上下文                               | 仍然可以手动做什么                               |
| -------------------------------------- | --------------------------------------------------- | ------------------------------------------------ |
| 时间线上的时间点或拖拽框选的时间段     | 点击浮出的「添加到对话」，把准确时段交给 AgentDock  | 继续调整片段起止、顺序、轨道关系与整体节奏       |
| 片段、字幕、动效、转场、资产或生成产物 | 选中对象会自动关联；也可以在输入框中用 `@` 再次引用 | 打开详情编辑时间、层级、位置、透明度和具体文案等 |
| 页面中的一段文本                       | 划选文本后点击「添加到对话」                        | 直接修改原字段，或要求 Agent 只改选中的这一处    |

这意味着时间线、内容元素、资产和文本都不是只能被 Agent “看见”的静态结果，而是可以被引用、定位、修改和审阅的项目对象。顶部的 **资产库** 用于浏览原始素材与生成产物；**视频预览 / 下载成片** 则负责检查和导出当前方案。

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
    <img class="creator-shot" src="https://img.alicdn.com/imgextra/i1/O1CN01UhZVZn1sEECIv5SXW_!!6000000005734-2-tps-920-1050.png" alt="角色视觉资产的媒体审阅卡" />
    <figcaption><strong>媒体审阅</strong>：查看生成结果与详情，选择「保留」或「撤销」，也可批量处理。</figcaption>
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
  <img class="creator-shot creator-shot--compact" src="https://img.alicdn.com/imgextra/i2/O1CN01EJ5RXHZn1gH1gENM_!!6000000002366-2-tps-828-548.png" alt="显示对象、模型、参数、预估费用、继续和取消按钮的生产确认卡" />
  <figcaption>生产确认卡集中展示对象、模型、参数和预估费用；确认后才会提交计费任务。</figcaption>
</figure>

> 💰 费用为按模型公开单价在本地计算的参考值，实际费用以服务商账单为准；此确认可在模型配置中关闭。

---

## 预览、管理与导出

- **成片预览**：在工作台点击「视频预览」，或在「我的项目」卡片上点击「预览」；
- **下载成片**：使用工作台右上角的「下载成片」导出最终视频；
- **管理项目**：「我的项目」集中展示创作类型、画幅、分辨率与更新时间，并支持排序。

<figure class="creator-figure">
  <img class="creator-shot" src="https://img.alicdn.com/imgextra/i2/O1CN01KhoHYq1vvgcvVfCfo_!!6000000006235-2-tps-3456-1882.png" alt="包含项目管理页面和完整成片预览窗口的 Creator 全局界面" />
  <figcaption>「我的项目」集中展示项目状态和创作规格；打开「预览」即可在完整弹窗中检查成片。</figcaption>
</figure>

---

## 附录：安装与运行环境

请打开 QwenPaw 控制台的 **Apps（应用中心）**，找到 **QwenPaw Creator** 并点击安装；安装完成后，直接从 Apps 打开 Creator。

Creator 会使用若干本地工具，但不会改动系统安装：`ffmpeg` 负责媒体处理与合成（可用 `CREATOR_FFMPEG_PATH` 指定，否则回退系统 `ffmpeg` 或 `imageio-ffmpeg`）；`jq` 支撑 Agent 对项目文件的结构化编辑（`CREATOR_JQ_PATH` 或 `PATH`）。依赖缺失时 Creator 以降级模式启动，可通过 `GET /api/qwenpaw-creator/health` 查看缺失项。
