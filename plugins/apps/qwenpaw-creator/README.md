# QwenPaw Creator

English | [中文](README_zh.md)

![QwenPaw Creator — agentic video creation platform](https://img.alicdn.com/imgextra/i1/O1CN0141WNzmX0SxB3FPZ2_!!6000000007600-2-tps-1600-600.png)

<p class="creator-lead">QwenPaw Creator is an <strong>agentic video creation platform</strong>: you set the goal, provide sources, and steer the direction; an Agent team handles planning, generation, editing, and composition, returning every important decision to you.</p>

- **The Agent stays throughout the process**: screenwriting, directing, visual development, motion, and editing Specialists collaborate against live project state;
- **You remain in control**: redirect the work with a sentence or fine-tune an object directly on the timeline;
- **Start either way**: generate a short drama from an idea, or turn existing footage into a finished film.

Creator natively supports [Qwen-MM-Plugins](https://github.com/QwenLM/Qwen-MM-Plugins) and reuses its three official capabilities throughout the creation workflow: `core` provides dynamic-resolution reading for images, videos, documents, and 3D models, together with foundational vision capabilities such as OCR, grounding, segmentation, and ASR; `video-memory` provides hierarchical graph memory for question answering over very long videos; and `video-edit` provides video editing workflows plus image, video, and audio generation.

<figure class="creator-figure">
  <img class="creator-shot" src="https://img.alicdn.com/imgextra/i3/O1CN01Lg9abZ1bycqw8mR6L_!!6000000003534-2-tps-2400-1240.png" alt="The two Creator workflows: generating from an idea and editing existing footage" />
  <figcaption>Creator has one project entry. After entering, choose either “generate from an idea” or “edit existing footage,” then continue through one Agentic creation loop.</figcaption>
</figure>

---

## Start your first project in three minutes

### 1. Open Creator

Creator is installed and opened from **Apps** in QwenPaw. Start QwenPaw and open the console (default `http://127.0.0.1:8088/`), select **Apps** in the left navigation, find **QwenPaw Creator**, and choose Install. After installation, open it from the same Apps page.

<figure class="creator-figure">
  <img class="creator-shot" src="https://img.alicdn.com/imgextra/i1/O1CN01gEoPuRRY0KE4fX2q_!!6000000002947-2-tps-2300-1520.png" alt="The Apps navigation and QwenPaw Creator card on the QwenPaw Apps page" />
  <figcaption>Find QwenPaw Creator in Apps, install it, and open it from the same page.</figcaption>
</figure>

### 2. Configure models

Before your first project, open **Model Configuration** at the lower right of the home composer (or follow the first-run guide). Connect only the capabilities your scenario needs:

| Scenario                            | Required capabilities                     | Role in the workflow                                             |
| ----------------------------------- | ----------------------------------------- | ---------------------------------------------------------------- |
| Every scenario                      | LLM (required)                            | The brain for creative planning, storyboards, and Agent dialogue |
| Short drama / general generation    | Image generation + video generation + VLM | Generate frames and video; use VLM for visual quality review     |
| Editing / uploaded sources          | VLM                                       | Understand uploaded image and video content                      |
| Sources with speech / transcription | ASR                                       | Turn speech into text for editing and subtitles                  |
| Voice-over / digital-human delivery | TTS + digital human                       | Synthesize narration and dialogue; drive talking-video segments  |

The current model matrix is grouped by capability:

- **LLM / VLM**: OpenAI-compatible APIs, DashScope / Bailian, Anthropic Claude, DeepSeek, Google Gemini, Baidu Qianfan, Volcano Engine, and custom providers;
- **Grounding**: Serper (Google) or Tavily; the validation model can reuse an LLM / VLM connection or be configured separately;
- **Image generation**: OpenAI-compatible APIs or DashScope;
- **Video generation**: DashScope `wan2.7` and `happyhorse-1.1` automatically select t2v / i2v / r2v from the element type; Volcano Engine `doubao-seedance-2.0` provides r2v;
- **ASR**: DashScope Fun-ASR, DashScope Qwen3-ASR, or OpenAI Whisper;
- **TTS / digital human**: DashScope Qwen-TTS, CosyVoice, and `wan2.2-s2v` (with free `wan2.2-s2v-detect` face validation);
- **Embedding**: DashScope `qwen3-vl-embedding` for asset retrieval and long-source memory.

### 3. Hand the goal and sources to the Agent

1. **Describe the goal**: for example, “Create a fast-paced short drama with strong conflict and a warm ending,” or “Turn these cat videos into a one-minute highlight reel”;
2. **Provide sources (optional)**: add files, folders, or links. Inside the project they become manageable, referenceable, and traceable assets;
3. **Choose the format**: Short Drama / Editing / General, plus resolution and aspect ratio;
4. Select **Launch Agent**. The Agent starts planning and opens the workbench.

<figure class="creator-figure">
  <img class="creator-shot" src="https://img.alicdn.com/imgextra/i1/O1CN01z4vG56cEgTB3thAe_!!6000000006487-2-tps-1920-1080.png" alt="The Creator home composer with goal, source import, creation type, aspect ratio, and model controls" />
  <figcaption>One composer holds the goal, sources, and constraints. It starts the project; the uploaded material then becomes structured project data.</figcaption>
</figure>

---

## The workbench: selection becomes context, with manual control

Creator’s agentic capability is not a separate layer floating beside the editor: **project content itself is actionable Agent context**. The currently selected clip / subtitle / motion / transition / asset appears as a linked object above the AgentDock composer. Timeline points, time ranges, and highlighted text can be inserted through the selection action. You can also use `@` to reference additional objects. Describe the intended change and the Agent works against those exact objects.

<figure class="creator-figure">
  <img class="creator-shot" src="https://img.alicdn.com/imgextra/i1/O1CN01mOyx2tu7UMD3thAe_!!6000000004154-2-tps-1920-1080.png" alt="Creator workbench with element details open and the timeline plus multiple project elements linked in the AgentDock composer" />
  <figcaption>The current project element is linked in AgentDock, while an exact time range enters the composer as a structured selection. Refine either through natural language or continue editing manually.</figcaption>
</figure>

| What you select                                          | How it becomes Agent context                                                   | What remains manually editable                                               |
| -------------------------------------------------------- | ------------------------------------------------------------------------------ | ---------------------------------------------------------------------------- |
| A timeline point or dragged time range                   | Insert it through the selection action with exact timing and object references | Continue adjusting clip bounds, order, track relationships, and rhythm       |
| A clip, subtitle, motion, transition, asset, or artifact | The current selection is linked automatically; use `@` to reference another    | Open details to edit timing, stacking, position, opacity, or copy            |
| A section of page text                                   | Highlight it and use the selection action to insert it in the composer         | Edit the source field directly, or ask the Agent to change only that passage |

Timeline content, project elements, assets, and text are therefore not static results that an Agent can only “see”; they are referenceable, locatable, editable, and reviewable project objects. Use **Asset Library** at the top to browse source material and generated outputs. **Video Preview / Compose Final Cut** checks and outputs the current plan.

### Three practical Agent collaboration habits

- **Reference with `@`**: attach a shot, source, or other object as context; the selected object is also carried into the conversation automatically;
- **Intervene at any time**: ask for a targeted change such as “only rewrite the second caption” or a broader one such as “add a sunray motion treatment to the opening”;
- **Stop when needed**: interrupt an in-progress task immediately with the stop control.

---

## Two typical creation paths

### Short-drama generation: zero to film

1. **Script and shots**: screenwriting / directing Specialists turn the goal into scenes, characters, action, and dialogue;
2. **Consistency assets**: anchor images establish each character and scene;
3. **Storyboard and video**: frames use those assets as references, then reference-to-video (r2v) models generate clips;
4. **Composition**: ready clips enter the shared timeline and are composed into a complete film.

### Footage editing: sources to film

1. **Understand sources**: VLM analysis (plus ASR for speech) finds content and highlight moments;
2. **Build an edit plan**: the Agent selects clips, arranges the timeline, and adds subtitles, motion, and transitions;
3. **Human + Agent refinement**: adjust a segment directly or ask the Agent to do it;
4. **Preview and compose**: confirm the plan and render the film.

---

## Review: every Agent change has a clear decision

Generated media and Agent-authored text changes enter the decision tray. Content you edit manually applies directly and does not create another review item.

<div class="creator-media-grid">
  <figure class="creator-figure">
    <img class="creator-shot" src="https://img.alicdn.com/imgextra/i1/O1CN01j3Wnw8SpaHE1qYPq_!!6000000007962-2-tps-910-780.png" alt="Generated-video review card in the decision tray" />
    <figcaption><strong>Media review</strong>: preview generated video directly in the decision tray, then Keep or Undo it individually or in a batch.</figcaption>
  </figure>
  <figure class="creator-figure">
    <img class="creator-shot" src="https://img.alicdn.com/imgextra/i2/O1CN01Yb3MTwmx9zF1roSO_!!6000000001528-2-tps-920-760.png" alt="Text review card showing the content before and after a change" />
    <figcaption><strong>Text review</strong>: see the before / after change immediately, or open its original context.</figcaption>
  </figure>
</div>

Review items jump as close as possible to their generation context: character image → asset detail, storyboard frame → shot detail, and text change → original location.

### Production confirmation: see estimated cost before a paid call

Before a paid image or video generation call, the Agent presents a **production confirmation card** with the target, model, parameters, and a locally estimated cost. The billable task is submitted only after you click **Continue**; **Cancel** ends that production request.

<figure class="creator-figure">
  <img class="creator-shot creator-shot--compact" src="https://img.alicdn.com/imgextra/i1/O1CN010iruaGE2zLH1qInk_!!6000000006076-2-tps-908-760.png" alt="Production confirmation focused on target, model, parameters, estimated cost, Continue, and Cancel" />
  <figcaption>The confirmation card summarizes the target, model, parameters, and estimated cost; the paid task starts only after approval.</figcaption>
</figure>

> 💰 The estimate is computed locally from published model pricing and is for reference only. Your provider’s bill is authoritative. This confirmation can be disabled in Model Configuration.

---

## Preview, manage, and export

- **Preview the film**: use “Video Preview” in the workbench, or “Preview” on a card in My Projects;
- **Compose and export**: use “Compose Final Cut” at the upper right, then “Download / Export” to save the finished video;
- **Manage projects**: My Projects shows creation type, aspect ratio, resolution, and update time, with sorting controls.

<figure class="creator-figure">
  <img class="creator-shot" src="https://img.alicdn.com/imgextra/i1/O1CN01vnCiZG2Z3DH3thAe_!!6000000005181-2-tps-1920-1080.png" alt="Full Creator project-management page with the complete film preview dialog open" />
  <figcaption>My Projects brings project status and creation settings together; open Preview to inspect the finished film in a complete dialog.</figcaption>
</figure>

---

## Appendix: installation and runtime

Open **Apps** in the QwenPaw console, find **QwenPaw Creator**, and select Install. After installation, open Creator directly from Apps.

Creator uses a few local tools without changing your system installation: `ffmpeg` handles media processing and composition (set `CREATOR_FFMPEG_PATH`, otherwise it falls back to system `ffmpeg` or `imageio-ffmpeg`); `jq` supports structured Agent edits to project files (`CREATOR_JQ_PATH` or `PATH`). If a dependency is missing, Creator starts in degraded mode; inspect `GET /api/qwenpaw-creator/health` for details.
