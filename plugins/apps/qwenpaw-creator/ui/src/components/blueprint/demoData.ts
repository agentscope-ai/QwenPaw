import type { ProjectDocument } from "@/contracts/creator";
import { projectDocument } from "@/test/creatorFixtures";

/**
 * Typed mock data for the Blueprint demo page. Mirrors the planned v9 domain
 * additions (NarrativeGraph / ScriptDocument / ResearchFinding) so the demo
 * components can later be rebound to real contracts without markup changes.
 */

export type Tone = "done" | "run" | "wait" | "idle";

export interface StageChip {
  label: string;
  tone: Tone;
}

export type ScriptBlock =
  | { kind: "scene"; text: string }
  | { kind: "action"; text: string; refs?: string[] }
  | { kind: "line"; character: string; parenthetical?: string; text: string }
  | { kind: "hook"; text: string };

export interface EpisodeScript {
  id: string;
  name: string;
  panelTitle?: string;
  version: string;
  status: { text: string; tone: Tone; progress?: number };
  stages: StageChip[];
  cast: { label: string; grad: string }[];
  planMeta: string[];
  synopsis: string;
  blocks: ScriptBlock[];
}

export interface GraphNode {
  ep: EpisodeScript;
  x: number;
  y: number;
  badge: string;
  ending?: boolean;
  icon: string;
  iconClass: string;
  spin?: boolean;
  reviewing?: boolean;
  meta: string;
}

export interface GraphData {
  width: number;
  height: number;
  nodes: GraphNode[];
  choice?: {
    x: number;
    y: number;
    question: string;
    state: string;
    tone: Tone;
    detail: InteractionDetailData;
  };
  edges: { d: string; active?: boolean }[];
  labels: { x: number; y: number; text: string }[];
}

export interface ListEpisode {
  n: number;
  title: string;
  dur: string;
  icon: string;
  iconClass: string;
  spin?: boolean;
  ep: EpisodeScript;
}

export interface StripItem {
  label: string;
  sub?: string;
  tone: Tone;
  ref?:
    | { kind: "script" }
    | { kind: "visual"; name: string }
    | { kind: "research"; title: string };
}

export interface StripStep {
  name: string;
  sub: string;
  tone: Tone;
  icon: string;
  items: StripItem[];
}

export interface RunningActivity {
  label: string;
  progress?: number;
}

export interface VisualDetailData {
  type: "visual";
  title: string;
  grad: string;
  versions: string[];
  selected: number;
  kv: [string, string][];
  prompt: string;
}

export interface ResearchDetailData {
  type: "research";
  title: string;
  conclusion: string;
  pages: [string, string][];
  inject: string;
}

export interface SourceDetailData {
  type: "source";
  title: string;
  kv: [string, string][];
  segs: [string, string][];
  note: string;
}

export interface InteractionDetailData {
  type: "interaction";
  title: string;
  lastFrame: { grad: string; label: string };
  options: { label: string; target: string }[];
  countdown: string;
  kv: [string, string][];
  prompt: string;
  versions: string[];
  selected: number;
}

export type DetailData =
  | VisualDetailData
  | ResearchDetailData
  | SourceDetailData
  | InteractionDetailData;

export interface VisualItem {
  name: string;
  grad: string;
  tag: string;
  state: string;
  tone: Tone;
  pending?: boolean;
  detail: VisualDetailData;
}

export interface ResearchItem {
  icon: string;
  iconBg: string;
  title: string;
  summary: string;
  tag: string;
  tone: Tone;
  detail: ResearchDetailData | SourceDetailData;
}

export type ScenarioKey = "drama" | "novel" | "story" | "promo" | "edit";

export interface ScenarioData {
  key: ScenarioKey;
  label: string;
  navName: string;
  navPreview: string;
  chips: { text: string; warn?: boolean }[];
  structure: "graph" | "list" | "single";
  structureActions?: boolean;
  graph?: GraphData;
  episodes?: ListEpisode[];
  single?: EpisodeScript;
  strip?: StripStep[];
  singleHint?: string;
  visual: VisualItem[] | null;
  research: ResearchItem[];
  defaultEpisodeId: string;
  running: RunningActivity[];
  runningEmpty?: string;
}

export const GRADS: Record<string, string> = {
  g1: "linear-gradient(160deg,#5b6d8f,#20283c)",
  g2: "linear-gradient(160deg,#8f6d5b,#3c2820)",
  g3: "linear-gradient(160deg,#5b8f76,#1f352a)",
  g4: "linear-gradient(160deg,#7a5b8f,#2c2038)",
  g5: "linear-gradient(160deg,#8f5b5b,#382020)",
  g6: "linear-gradient(160deg,#4e5d43,#1c2417)",
  g7: "linear-gradient(160deg,#3d6472,#152a31)",
  g8: "linear-gradient(160deg,#997a3d,#38290f)",
};

export const TONE_TEXT: Record<Tone, string> = {
  done: "text-[var(--color-success)]",
  run: "text-[var(--color-primary,#3b82f6)]",
  wait: "text-[var(--color-warning)]",
  idle: "text-[var(--color-text-tertiary)]",
};

export const TONE_CHIP: Record<Tone, string> = {
  done: "bg-[var(--color-success-soft)] text-[var(--color-success)]",
  run: "bg-[rgba(59,130,246,.1)] text-[var(--color-primary,#3b82f6)]",
  wait: "bg-[var(--color-warning-soft)] text-[var(--color-warning)]",
  idle: "bg-[var(--color-bg-secondary)] text-[var(--color-text-tertiary)]",
};

/* ------------------------------------------------------------------ */
/* 互动短剧 · 分支                                                      */
/* ------------------------------------------------------------------ */

const ep1: EpisodeScript = {
  id: "ep1",
  name: "第1集 · 雾夜来信",
  version: "剧本 v3 · 已定稿",
  status: { text: "✓ 已成片", tone: "done" },
  stages: [
    { label: "剧本 已通过", tone: "done" },
    { label: "设计 已确认", tone: "done" },
    { label: "成片 v3", tone: "done" },
  ],
  cast: [
    { label: "林晚", grad: "g1" },
    { label: "山路", grad: "g6" },
    { label: "邮差", grad: "g5" },
  ],
  planMeta: ["96s · 12 镜 · 9:16", "已发布，修改剧本将标记成片为过期"],
  synopsis: "暴雨夜，林晚收到匿名信，信中指向十年前雾山旧宅那场大火的真相。",
  blocks: [
    { kind: "scene", text: "场 1 · 外景 · 雾山山路 · 夜 · 暴雨" },
    {
      kind: "action",
      text: "雨幕砸在盘山公路上。远光灯划开浓雾，林晚的旧轿车缓慢爬坡。车窗内，她的指节在方向盘上发白。",
    },
    {
      kind: "line",
      character: "林晚",
      parenthetical: "画外，读信声",
      text: "\u201c如果你还记得十年前的那场火，就回雾山来。有人替你烧掉了不该烧的东西。\u201d",
    },
    { kind: "scene", text: "场 2 · 内景 · 林晚车内 · 夜" },
    {
      kind: "action",
      text: "副驾上摊着一封没有署名的信。信纸边缘有一道焦痕，邮戳是三天前的雾山镇。",
    },
    {
      kind: "line",
      character: "林晚",
      parenthetical: "自语",
      text: "\u201c十年了……到底是谁还记得。\u201d",
    },
    { kind: "scene", text: "场 3 · 外景 · 雾山镇口 · 夜" },
    {
      kind: "action",
      text: "铁皮路牌\u201c雾山镇\u201d在雨里晃。林晚下车，抬头望向山腰上那座黑影般的旧宅。闪电照亮宅子烧塌的东侧屋顶。",
    },
    {
      kind: "hook",
      text: "末镜钩子：信纸特写——落款处只有一个被雨水晕开的指印。（承接第2集开场）",
    },
  ],
};

const ep2: EpisodeScript = {
  id: "ep2",
  name: "第2集 · 旧宅疑云",
  version: "剧本 v2 · Agent 起草",
  status: { text: "◐ 生产中 65%", tone: "run", progress: 65 },
  stages: [
    { label: "剧本 已通过", tone: "done" },
    { label: "设计 已确认", tone: "done" },
    { label: "视频生成 65%", tone: "run" },
    { label: "成片 等待", tone: "idle" },
  ],
  cast: [
    { label: "林晚", grad: "g1" },
    { label: "大厅", grad: "g3" },
    { label: "书房", grad: "g4" },
    { label: "账册", grad: "g8" },
  ],
  planMeta: ["90s · 11 镜 · 9:16", "SC-04 生成中，SC-05 排队"],
  synopsis:
    "林晚潜入尘封的雾山旧宅，在书房暗格中发现半本烧焦的账册与一张合影。",
  blocks: [
    { kind: "scene", text: "场 1 · 外景 · 雾山旧宅正门 · 夜 · 雨渐小" },
    {
      kind: "action",
      text: "生锈的铁锁挂在门环上，早被人撬开过。林晚推门，铰链发出漫长的吱呀声。",
    },
    {
      kind: "line",
      character: "林晚",
      parenthetical: "低声",
      text: "\u201c这座宅子，十年没人敢进来了。\u201d",
    },
    { kind: "scene", text: "场 2 · 内景 · 旧宅大厅 · 夜" },
    {
      kind: "action",
      text: "煤油灯的光束扫过蒙尘的家具。白布下露出半架烧焦的钢琴。光束停在楼梯下——地板上有一串新鲜的泥脚印，不是她的。",
    },
    {
      kind: "line",
      character: "林晚",
      parenthetical: "屏息",
      text: "\u201c……有人比我先到。\u201d",
    },
    { kind: "scene", text: "场 3 · 内景 · 二层书房 · 夜" },
    {
      kind: "action",
      text: "书架第三层的木板有撬动痕迹。林晚数到第七本书，向内按下。\u201c咔\u201d——暗格弹开，半本烧焦的账册滑出，灰烬在灯光里翻飞。账册夹页里掉出一张泛黄合影。",
    },
    {
      kind: "line",
      character: "林晚",
      parenthetical: "旁白",
      text: "\u201c有人比我更早来过这里——而且，他不想让任何人知道。\u201d",
    },
    { kind: "scene", text: "场 4 · 内景 · 书房 · 夜 · 合影特写" },
    {
      kind: "action",
      text: "合影上五个人站在未烧毁的旧宅前。林晚的手电停在右侧一张年轻的脸上——镜头缓缓推近，那眉眼分明是如今镇上的新医生，沈修。",
    },
    {
      kind: "hook",
      text: "末镜钩子：合影背面一行小字：\u201c火起之前，他就在场。\u201d（引出第3集身份反转）",
    },
  ],
};

const ep3: EpisodeScript = {
  id: "ep3",
  name: "第3集 · 双重身份",
  version: "剧本 v1 · Agent 起草",
  status: { text: "⏱ 待你审阅", tone: "wait" },
  stages: [
    { label: "剧本 待审阅", tone: "wait" },
    { label: "设计 未开始", tone: "idle" },
    { label: "生成 未开始", tone: "idle" },
  ],
  cast: [
    { label: "林晚", grad: "g1" },
    { label: "沈修", grad: "g2" },
    { label: "诊所", grad: "g7" },
  ],
  planMeta: ["88s · 预排 10 镜 · 9:16", "审阅通过后开始视觉设计与分镜"],
  synopsis:
    "合影中的沈修竟是当年的纵火目击者，他以新身份回到镇上，接近林晚另有所图。",
  blocks: [
    { kind: "scene", text: "场 1 · 内景 · 镇卫生所 · 日" },
    {
      kind: "action",
      text: "沈修给老人量血压，白大褂干净得体。玻璃门开，林晚走进来，手里攥着那张合影。两人目光相接，沈修手上的动作停了半拍。",
    },
    {
      kind: "line",
      character: "沈修",
      parenthetical: "笑",
      text: "\u201c林小姐？镇上很少见生面孔。\u201d",
    },
    {
      kind: "line",
      character: "林晚",
      text: "\u201c我不是生面孔。十年前，我住在山腰那座宅子里。\u201d",
    },
    { kind: "scene", text: "场 2 · 内景 · 卫生所里间 · 日" },
    {
      kind: "action",
      text: "林晚把合影拍在桌上，指着右侧的年轻人。沈修沉默地摘下眼镜，擦了很久。",
    },
    {
      kind: "line",
      character: "沈修",
      parenthetical: "低声",
      text: "\u201c那天晚上我确实在场。但放火的不是我——我是去救人的。\u201d",
    },
    { kind: "line", character: "林晚", text: "\u201c救谁？\u201d" },
    { kind: "line", character: "沈修", text: "\u201c救你。\u201d" },
    { kind: "scene", text: "场 3 · 外景 · 卫生所后巷 · 黄昏" },
    {
      kind: "action",
      text: "沈修从柜底取出一只铁盒，里面是与账册同款的另一半——完好无损。他望着山腰的旧宅，眼神复杂。",
    },
    {
      kind: "hook",
      text: "本集结尾进入观众抉择点：林晚拿到关键证据后，是否当众揭发沈修？（分支 A / B 由此展开）",
    },
  ],
};

const ep4a: EpisodeScript = {
  id: "ep4a",
  name: "第4集A · 真相大白",
  version: "剧本草稿 · 待展开",
  status: { text: "○ 未开始", tone: "idle" },
  stages: [
    { label: "剧本 大纲", tone: "idle" },
    { label: "设计 未开始", tone: "idle" },
  ],
  cast: [
    { label: "林晚", grad: "g1" },
    { label: "沈修", grad: "g2" },
    { label: "广场", grad: "g7" },
  ],
  planMeta: ["规划 85s · 分支 A（揭发真相）", "确认第3集后 Agent 将展开全稿"],
  synopsis: "林晚在镇祭当晚公开账册，沈修被迫说出十年前火灾的真正主使。",
  blocks: [
    { kind: "scene", text: "大纲（分支 A · 选择\u201c揭发真相\u201d后进入）" },
    {
      kind: "action",
      text: "① 镇祭之夜，林晚登台，把两半账册拼合投影在祠堂白墙上；",
    },
    {
      kind: "action",
      text: "② 人群哗然，账册指向镇长十年前挪用修缮款、纵火灭账；",
    },
    { kind: "action", text: "③ 沈修当众作证，警车驶入雾山，镇长被带走；" },
    {
      kind: "action",
      text: "④ 末镜：林晚与沈修站在旧宅废墟前，雨停。转入结局 A《救赎》。",
    },
  ],
};

const ep4b: EpisodeScript = {
  id: "ep4b",
  name: "第4集B · 沉默代价",
  version: "剧本草稿 · 待展开",
  status: { text: "🔒 等待依赖", tone: "idle" },
  stages: [
    { label: "剧本 大纲", tone: "idle" },
    { label: "设计 未开始", tone: "idle" },
  ],
  cast: [
    { label: "林晚", grad: "g1" },
    { label: "旧宅", grad: "g3" },
  ],
  planMeta: ["规划 82s · 分支 B（保持沉默）", "与分支 A 共用 80% 视觉资产"],
  synopsis: "林晚选择隐瞒，却在深夜发现自己也成了下一封匿名信的收件人。",
  blocks: [
    { kind: "scene", text: "大纲（分支 B · 选择\u201c保持沉默\u201d后进入）" },
    {
      kind: "action",
      text: "① 林晚把账册塞回暗格，说服自己\u201c过去就让它过去\u201d；",
    },
    { kind: "action", text: "② 镇祭如常举行，镇长向她举杯，笑意深不可测；" },
    {
      kind: "action",
      text: "③ 深夜，门缝里滑进一封新的匿名信，字迹与十年前那封相同；",
    },
    {
      kind: "action",
      text: "④ 末镜：信纸边缘同样的焦痕。转入结局 B《迷雾》。",
    },
  ],
};

const enda: EpisodeScript = {
  id: "enda",
  name: "结局A · 救赎",
  version: "剧本草稿 · 待展开",
  status: { text: "○ 未开始", tone: "idle" },
  stages: [{ label: "剧本 大纲", tone: "idle" }],
  cast: [
    { label: "林晚", grad: "g1" },
    { label: "旧宅", grad: "g3" },
  ],
  planMeta: ["规划 60s · 结局线 A"],
  synopsis: "大火的阴影散去，林晚把旧宅改成图书馆，雾山第一次迎来晴天。",
  blocks: [
    { kind: "scene", text: "大纲（结局 A）" },
    {
      kind: "action",
      text: "时间跳跃一年：旧宅修葺一新，孩子们在院里读书。林晚在窗边整理书架，把那张合影摆进相框。阳光第一次穿透雾山的雾。",
    },
  ],
};

const endb: EpisodeScript = {
  id: "endb",
  name: "结局B · 迷雾",
  version: "剧本草稿 · 待展开",
  status: { text: "○ 未开始", tone: "idle" },
  stages: [{ label: "剧本 大纲", tone: "idle" }],
  cast: [
    { label: "林晚", grad: "g1" },
    { label: "账册", grad: "g8" },
  ],
  planMeta: ["规划 55s · 结局线 B（开放式）"],
  synopsis: "谎言堆叠成新的迷雾，片尾定格在林晚烧掉账册的那簇火光上。",
  blocks: [
    { kind: "scene", text: "大纲（结局 B · 开放式）" },
    {
      kind: "action",
      text: "林晚在后院点燃账册。火光映在她脸上，表情看不出释然还是恐惧。镜头缓缓拉远，雾重新漫上山腰。画面定格在那簇火光——像十年前的那一夜。",
    },
  ],
};

const dramaGraph: GraphData = {
  width: 1580,
  height: 420,
  nodes: [
    {
      ep: ep1,
      x: 24,
      y: 148,
      badge: "第 1 集",
      icon: "✓",
      iconClass: "text-[var(--color-success)]",
      meta: "96s · 12 镜",
    },
    {
      ep: ep2,
      x: 294,
      y: 148,
      badge: "第 2 集",
      icon: "◐",
      iconClass: "text-[var(--color-primary,#3b82f6)]",
      spin: true,
      meta: "90s · 11 镜",
    },
    {
      ep: ep3,
      x: 564,
      y: 148,
      badge: "第 3 集",
      icon: "⏱",
      iconClass: "text-[var(--color-warning)]",
      reviewing: true,
      meta: "88s · 草稿",
    },
    {
      ep: ep4a,
      x: 1074,
      y: 32,
      badge: "第 4 集 · A",
      icon: "○",
      iconClass: "text-[var(--color-text-tertiary)]",
      meta: "规划 85s",
    },
    {
      ep: ep4b,
      x: 1074,
      y: 264,
      badge: "第 4 集 · B",
      icon: "🔒",
      iconClass: "text-[var(--color-text-tertiary)]",
      meta: "规划 82s",
    },
    {
      ep: enda,
      x: 1344,
      y: 32,
      badge: "结局 A",
      ending: true,
      icon: "○",
      iconClass: "text-[var(--color-text-tertiary)]",
      meta: "规划 60s",
    },
    {
      ep: endb,
      x: 1344,
      y: 264,
      badge: "结局 B",
      ending: true,
      icon: "○",
      iconClass: "text-[var(--color-text-tertiary)]",
      meta: "规划 55s",
    },
  ],
  choice: {
    x: 834,
    y: 164,
    question: "林晚拿到关键证据后，是否当众揭发沈修？",
    state: "动效 v1 · 生成中 62%",
    tone: "run",
    detail: {
      type: "interaction",
      title: "观众抉择 · 揭发还是隐瞒",
      lastFrame: {
        grad: "g4",
        label: "承接帧：第3集 SC-10 末帧（铁盒特写定格）",
      },
      options: [
        { label: "选择 A · 揭发真相", target: "第4集A《真相大白》" },
        { label: "选择 B · 保持沉默", target: "第4集B《沉默代价》" },
      ],
      countdown: "10s 倒计时 · 超时默认走 A",
      kv: [
        ["载体", "interaction element（html_css 交互动效）"],
        ["挂载", "第3集时间线末尾 · span 4s 循环"],
        ["选项来源", "narrative_edges（单一事实源，改边即改选项）"],
        ["状态", "动效 v1 生成中 62% · 待你审阅"],
        ["导出", "互动容器：选项元数据 / 普通视频：定格 + 评论区分链"],
      ],
      prompt:
        "在末帧定格上做冷蓝呼吸式暗角，两个选项以火漆信封样式从画面底部浮起，倒计时以烧焦纸边缘的火线表现；选中时信封燃烧转场至对应分支首帧。",
      versions: ["v1 生成中 62%"],
      selected: 0,
    },
  },
  edges: [
    { d: "M 242 208 C 268 208, 268 208, 294 208", active: true },
    { d: "M 512 208 C 538 208, 538 208, 564 208", active: true },
    { d: "M 782 208 C 808 208, 808 208, 834 208", active: true },
    { d: "M 992 196 C 1040 190, 1030 96, 1074 92" },
    { d: "M 992 220 C 1040 226, 1030 320, 1074 324" },
    { d: "M 1292 92 C 1318 92, 1318 92, 1344 92" },
    { d: "M 1292 324 C 1318 324, 1318 324, 1344 324" },
  ],
  labels: [
    { x: 1033, y: 136, text: "选择 A · 揭发真相" },
    { x: 1033, y: 280, text: "选择 B · 保持沉默" },
  ],
};

/* ------------------------------------------------------------------ */
/* 小说改编 · 线性 12 集                                                */
/* ------------------------------------------------------------------ */

function outline(
  id: string,
  n: number,
  title: string,
  meta: string[],
  synopsis: string,
  beats: string[],
): EpisodeScript {
  return {
    id,
    name: `第${n}集 · ${title}`,
    version: "剧本大纲 · 待展开",
    status: { text: "○ 未开始", tone: "idle" },
    stages: [{ label: "剧本 大纲", tone: "idle" }],
    cast: [{ label: "沈青梧", grad: "g1" }],
    planMeta: meta,
    synopsis,
    blocks: [
      { kind: "scene", text: "大纲" },
      ...beats.map((beat): ScriptBlock => ({ kind: "action", text: beat })),
    ],
  };
}

const novel5: EpisodeScript = {
  id: "n5",
  name: "第5集 · 断航",
  version: "剧本 v1 · Agent 起草",
  status: { text: "⏱ 待你审阅", tone: "wait" },
  stages: [
    { label: "剧本 待审阅", tone: "wait" },
    { label: "设计 未开始", tone: "idle" },
    { label: "生成 未开始", tone: "idle" },
  ],
  cast: [
    { label: "沈青梧", grad: "g1" },
    { label: "周世钧", grad: "g5" },
    { label: "航道", grad: "g6" },
  ],
  planMeta: ["124s · 预排 13 镜 · 9:16", "审阅通过后开始视觉设计与分镜"],
  synopsis:
    "周世钧买通航政处封了沈家航线，青梧被迫走夜航老河道，船行至灯河最暗处，舵手却是周家的人。",
  blocks: [
    { kind: "scene", text: "场 1 · 内景 · 航政处 · 日" },
    {
      kind: "action",
      text: "公文拍在柜台上：沈家船队\u201c手续不全\u201d，即日停航。青梧看见公文末尾周世钧的私章印油还没干透。",
    },
    {
      kind: "line",
      character: "沈青梧",
      parenthetical: "平静",
      text: "\u201c周会长的章，盖得比航政处还快。\u201d",
    },
    { kind: "scene", text: "场 2 · 外景 · 老河道 · 夜" },
    {
      kind: "action",
      text: "为赶交割，青梧冒险走废弃的老河道。两岸没有灯，只有船头一盏风灯。舵手赵四的影子在灯下忽长忽短。",
    },
    {
      kind: "line",
      character: "赵四",
      parenthetical: "背对着",
      text: "\u201c小姐，前面滩浅，得减速。\u201d",
    },
    {
      kind: "line",
      character: "沈青梧",
      parenthetical: "手按进袖中",
      text: "\u201c赵叔，我爹的船，你掌了十二年舵——什么时候改抽周家的烟了？\u201d",
    },
    { kind: "scene", text: "场 3 · 外景 · 老河道浅滩 · 夜" },
    {
      kind: "action",
      text: "风灯骤灭。黑暗里一声闷响，船身猛地搁浅倾斜。远处，三条没有挂灯的小船正包抄过来。",
    },
    {
      kind: "hook",
      text: "末镜钩子：青梧摸黑点燃了整桶桐油——\u201c想看沈家的灯灭？我烧给你们看。\u201d（本集为全剧中点，情绪转折）",
    },
  ],
};

function doneEp(
  id: string,
  n: number,
  title: string,
  synopsis: string,
  beats: string[],
  mirror: string,
): EpisodeScript {
  return {
    id,
    name: `第${n}集 · ${title}`,
    version: "剧本 v2 · 已定稿",
    status: { text: "✓ 已成片", tone: "done" },
    stages: [
      { label: "剧本 已通过", tone: "done" },
      { label: "设计 已确认", tone: "done" },
      { label: "成片 v2", tone: "done" },
    ],
    cast: [
      { label: "沈青梧", grad: "g1" },
      { label: mirror, grad: "g7" },
    ],
    planMeta: ["已发布 · 9:16"],
    synopsis,
    blocks: [
      { kind: "scene", text: "场次概览（已定稿，点开时间线查看成片）" },
      ...beats.map((beat): ScriptBlock => ({ kind: "action", text: beat })),
    ],
  };
}

const novelEpisodes: ListEpisode[] = [
  {
    n: 1,
    title: "灯河初见",
    dur: "120s",
    icon: "✓",
    iconClass: "text-[var(--color-success)]",
    ep: doneEp(
      "n1",
      1,
      "灯河初见",
      "1936 年，沈青梧押着最后一船桐油抵达江城，撞见码头夜市的万家灯火与一场蓄谋的火并。",
      [
        "货船破雾入港，两岸灯河倒映江面；",
        "码头火并，青梧只身拦在油桶前；",
        "暗处有人记下「沈家的女儿到了」。",
      ],
      "码头",
    ),
  },
  {
    n: 2,
    title: "商会暗礁",
    dur: "118s",
    icon: "✓",
    iconClass: "text-[var(--color-success)]",
    ep: doneEp(
      "n2",
      2,
      "商会暗礁",
      "青梧代父出席商会，当场拆穿三大行囤货压价的把戏，彻底得罪会长周世钧。",
      [
        "商会长桌，青梧是唯一的女性；",
        "亮出仓单副本，满座哗然；",
        "散会后周世钧吩咐「查她的船」。",
      ],
      "商会",
    ),
  },
  {
    n: 3,
    title: "夜宴惊变",
    dur: "122s",
    icon: "✓",
    iconClass: "text-[var(--color-success)]",
    ep: doneEp(
      "n3",
      3,
      "夜宴惊变",
      "周家夜宴上青梧初遇报馆主笔顾岸声，宴席未散，沈家货栈起火。",
      [
        "顾岸声递来字条：今晚别喝他们敬的酒；",
        "火光冲天，货栈告急；",
        "火场边缘捡到半枚商会铜纽扣。",
      ],
      "酒楼",
    ),
  },
  {
    n: 4,
    title: "暗流",
    dur: "116s",
    icon: "◐",
    iconClass: "text-[var(--color-primary,#3b82f6)]",
    spin: true,
    ep: {
      id: "n4",
      name: "第4集 · 暗流",
      version: "剧本 v2 · Agent 起草",
      status: { text: "◐ 生产中 48%", tone: "run", progress: 48 },
      stages: [
        { label: "剧本 已通过", tone: "done" },
        { label: "设计 已确认", tone: "done" },
        { label: "视频生成 48%", tone: "run" },
      ],
      cast: [
        { label: "沈青梧", grad: "g1" },
        { label: "顾岸声", grad: "g2" },
        { label: "报馆", grad: "g7" },
      ],
      planMeta: ["116s · 12 镜 · 9:16", "镜头 04-07 生成中"],
      synopsis:
        "保险行拒赔，报馆连夜排版揭露纵火疑云，顾岸声的铅字还没干，报馆就被人砸了。",
      blocks: [
        { kind: "scene", text: "场 1 · 内景 · 保险行 · 日" },
        {
          kind: "action",
          text: "职员推回投保单：「失火原因存疑，暂不理赔。」青梧注意到经理袖口的商会徽记。",
        },
        { kind: "scene", text: "场 2 · 内景 · 江声报馆 · 夜" },
        {
          kind: "action",
          text: "排字工人捡字如飞，顾岸声亲自校对头版《谁烧了沈家栈》。窗外砖头破窗而入。",
        },
        {
          kind: "line",
          character: "顾岸声",
          parenthetical: "拾起砖头，冷笑",
          text: "\u201c看来，写对了。\u201d",
        },
        { kind: "hook", text: "末镜钩子：砖上绑着字条——「下一块砸的是人」。" },
      ],
    },
  },
  {
    n: 5,
    title: "断航",
    dur: "124s",
    icon: "⏱",
    iconClass: "text-[var(--color-warning)]",
    ep: novel5,
  },
  {
    n: 6,
    title: "双城",
    dur: "118s",
    icon: "○",
    iconClass: "text-[var(--color-text-tertiary)]",
    ep: outline(
      "n6",
      6,
      "双城",
      ["规划 118s", "第 5 集通过后展开全稿"],
      "青梧赴沪筹款，见识十里洋场的新式商战，也发现周世钧背后还站着更大的洋行。",
      [
        "① 沪上银行团谈判受挫；",
        "② 老同学引荐新式保险；",
        "③ 洋行经理的名片上印着熟悉的徽记。",
      ],
    ),
  },
  {
    n: 7,
    title: "火并",
    dur: "120s",
    icon: "○",
    iconClass: "text-[var(--color-text-tertiary)]",
    ep: outline(
      "n7",
      7,
      "火并",
      ["规划 120s"],
      "码头脚夫两帮火并再起，青梧发现这是周家转移视线的老手法，将计就计。",
      [
        "① 火并爆发，航运瘫痪；",
        "② 青梧查出挑事者的账；",
        "③ 以账换人，脚夫倒戈。",
      ],
    ),
  },
  {
    n: 8,
    title: "旧账",
    dur: "116s",
    icon: "○",
    iconClass: "text-[var(--color-text-tertiary)]",
    ep: outline(
      "n8",
      8,
      "旧账",
      ["规划 116s"],
      "父亲病榻前交出一本 1924 年的旧账，沈周两家的恩怨源头浮出水面。",
      [
        "① 沈父病重吐露旧事；",
        "② 1924 年沉船案真相；",
        "③ 周世钧欠沈家一条命。",
      ],
    ),
  },
  {
    n: 9,
    title: "决堤",
    dur: "126s",
    icon: "○",
    iconClass: "text-[var(--color-text-tertiary)]",
    ep: outline(
      "n9",
      9,
      "决堤",
      ["规划 126s"],
      "汛期决堤，两家船队被迫联手救灾，青梧与周世钧在洪水里第一次并肩。",
      [
        "① 洪水围城；",
        "② 商会粮仓开与不开之争；",
        "③ 救灾中窥见周世钧的另一面。",
      ],
    ),
  },
  {
    n: 10,
    title: "离岸",
    dur: "118s",
    icon: "○",
    iconClass: "text-[var(--color-text-tertiary)]",
    ep: outline(
      "n10",
      10,
      "离岸",
      ["规划 118s"],
      "顾岸声的报道触怒洋行被通缉，青梧用一船桐油换他离岸，灯河夜色里作别。",
      ["① 通缉令贴满码头；", "② 夜航送人；", "③ 未说出口的话随江灯漂远。"],
    ),
  },
  {
    n: 11,
    title: "灯灭",
    dur: "122s",
    icon: "○",
    iconClass: "text-[var(--color-text-tertiary)]",
    ep: outline(
      "n11",
      11,
      "灯灭",
      ["规划 122s"],
      "洋行收网，周世钧一夜倾家，临倒台前把江城航权的底牌交给了青梧。",
      [
        "① 洋行挤兑周家；",
        "② 周世钧的最后一局；",
        "③ 底牌：1924 年的另一半账。",
      ],
    ),
  },
  {
    n: 12,
    title: "长夜将明",
    dur: "130s",
    icon: "○",
    iconClass: "text-[var(--color-text-tertiary)]",
    ep: outline(
      "n12",
      12,
      "长夜将明",
      ["规划 130s · 全剧终"],
      "青梧联合脚夫与小船行重开航线，灯河两岸华灯再起，长夜将明。",
      [
        "① 新商会成立；",
        "② 洋行退让；",
        "③ 末镜呼应第 1 集：船头灯火与两岸灯河连成一片。",
      ],
    ),
  },
];

/* ------------------------------------------------------------------ */
/* 故事短片 · 单集生成                                                   */
/* ------------------------------------------------------------------ */

const storySingle: EpisodeScript = {
  id: "story",
  name: "末班车 · 单集",
  panelTitle: "剧本 · 末班车（场次体）",
  version: "剧本 v1 · 场次体 · Agent 起草",
  status: { text: "⏱ 待你审阅", tone: "wait" },
  stages: [
    { label: "剧本 待审阅", tone: "wait" },
    { label: "设计 2/4", tone: "run" },
    { label: "生成 未开始", tone: "idle" },
  ],
  cast: [
    { label: "老周", grad: "g5" },
    { label: "阿禾", grad: "g1" },
    { label: "车厢", grad: "g7" },
  ],
  planMeta: ["100s · 预排 10 镜 · 9:16", "审阅通过后补齐视觉设计并开始分镜"],
  synopsis:
    "雨夜末班车，司机老周载到一位和亡女相像的少女，一段沉默的同路让他终于敢驶过女儿出事的那个路口。",
  blocks: [
    { kind: "scene", text: "场 1 · 内景 · 末班公交车 · 夜 · 雨" },
    {
      kind: "action",
      text: "雨刷有节奏地摆。车厢空荡，只有顶灯一盏接一盏闪。老周瞥了一眼后视镜——最后一排坐着个抱着书包的少女，湿透的刘海贴在额前。",
    },
    {
      kind: "line",
      character: "老周",
      parenthetical: "喉咙发紧",
      text: "\u201c姑娘，到哪儿下？\u201d",
    },
    { kind: "line", character: "阿禾", text: "\u201c开到底。\u201d" },
    { kind: "scene", text: "场 2 · 内景 · 车厢 · 夜（回忆插叙）" },
    {
      kind: "action",
      text: "同一辆车、三年前：扎马尾的女儿坐在同一个位置写作业，抬头冲他笑。灯光暖黄。回到现实，座位空了一瞬，又是那个陌生少女。",
    },
    {
      kind: "line",
      character: "阿禾",
      parenthetical: "忽然",
      text: "\u201c师傅，前面那个路口……能开慢一点吗？\u201d",
    },
    { kind: "scene", text: "场 3 · 外景 · 十字路口 · 夜 · 雨停" },
    {
      kind: "action",
      text: "老周松开一直悬着的刹车，车稳稳驶过路口。后视镜里，少女靠窗睡着了，怀里的书包上挂着一只和女儿一模一样的平安符。",
    },
    {
      kind: "hook",
      text: "末镜：站牌灯箱亮起，末班车驶入雨后的雾气。字幕卡——\u201c有些告别，要开过那个路口才算数。\u201d",
    },
  ],
};

const storyVisual: VisualItem[] = [
  {
    name: "老周 · 主形象",
    grad: "g5",
    tag: "v1",
    state: "⏱ 待确认",
    tone: "wait",
    pending: true,
    detail: {
      type: "visual",
      title: "角色 · 司机老周",
      grad: "g5",
      versions: ["v1 ●"],
      selected: 0,
      kv: [
        ["状态", "待确认 · 阻塞场 1-3 全部镜头"],
        ["被引用", "10 镜（规划）"],
        ["设计依据", "剧本 v1 + 90 年代公交调研"],
      ],
      prompt:
        "55 岁公交司机，藏蓝制服洗得发白，鬓角花白，眼角疲惫但温和；车厢顶灯冷白光，胶片颗粒。",
    },
  },
  {
    name: "阿禾 · 主形象",
    grad: "g1",
    tag: "v2",
    state: "已确认",
    tone: "done",
    detail: {
      type: "visual",
      title: "角色 · 少女阿禾",
      grad: "g1",
      versions: ["v1", "v2 ●"],
      selected: 1,
      kv: [
        ["状态", "已确认"],
        ["被引用", "场 1-3"],
        ["修改原因", "v1 年龄感偏大，按批注调小两岁"],
      ],
      prompt:
        "16 岁少女，湿发校服，抱旧帆布书包，神情安静；冷蓝夜色 + 车窗霓虹反光。",
    },
  },
  {
    name: "末班车厢 · 场景",
    grad: "g7",
    tag: "生成中",
    state: "◐ 58%",
    tone: "run",
    detail: {
      type: "visual",
      title: "场景 · 末班车厢",
      grad: "g7",
      versions: ["v1 生成中 58%"],
      selected: 0,
      kv: [
        ["状态", "生成中 · 约 60s 后完成"],
        ["被引用", "场 1、2"],
        ["设计约束", "来自调研：90 年代公交内饰，绿皮座椅 + 拉环"],
      ],
      prompt:
        "90 年代末班公交车厢，绿皮座椅，顶灯间隔闪烁，雨夜车窗挂满水珠，空旷纵深构图。",
    },
  },
  {
    name: "雨夜街道 · 场景",
    grad: "g6",
    tag: "v1",
    state: "已确认",
    tone: "done",
    detail: {
      type: "visual",
      title: "场景 · 雨夜街道与路口",
      grad: "g6",
      versions: ["v1 ●"],
      selected: 0,
      kv: [
        ["状态", "已确认"],
        ["被引用", "场 3 + 末镜"],
      ],
      prompt: "雨后深夜十字路口，红绿灯倒映积水，站牌灯箱暖光，薄雾。",
    },
  },
];

const storyResearch: ResearchItem[] = [
  {
    icon: "📄",
    iconBg: "var(--color-success-soft)",
    title: "输入理解 · 短篇故事《末班车》（2200 字）",
    summary:
      "抽取 2 位角色、3 个场景、1 条情感主线（丧女→和解）；按三幕切分 10 镜。",
    tag: "已完成",
    tone: "done",
    detail: {
      type: "source",
      title: "输入理解 · 《末班车》",
      kv: [
        ["篇幅", "2200 字"],
        ["角色", "2 主要（老周 / 阿禾）"],
        ["场景", "3（车厢 / 回忆 / 路口）"],
        ["情感线", "回避 → 直面 → 和解"],
      ],
      segs: [
        ["第 1-3 段", "雨夜相遇，建立压抑基调 → 场 1"],
        ["第 4-6 段", "回忆插叙，亡女信息 → 场 2"],
        ["第 7-9 段", "驶过路口，平安符呼应 → 场 3"],
      ],
      note: "剧本 v1 由本理解索引起草；修改理解结论会标记剧本为过期。",
    },
  },
  {
    icon: "🌐",
    iconBg: "rgba(59,130,246,.1)",
    title: "调研 · 90 年代公交内饰与站牌（browser use · 5 个网页）",
    summary:
      "结论：绿皮座椅 + 顶部拉环 + 手写线路牌；站牌灯箱为暖黄背光。已注入车厢 / 街道场景约束。",
    tag: "已核验",
    tone: "done",
    detail: {
      type: "research",
      title: "调研 · 90 年代公交年代考据",
      conclusion:
        "90 年代城市公交以绿皮人造革座椅、金属拉环、手写线路牌为特征；夜间站牌为暖黄灯箱。负面提示词加入：刷卡机、LED 报站屏。",
      pages: [
        ["公交博物馆数字馆 · 车型图集", "内饰三视图，已存参考资产"],
        ["城市记忆论坛 · 90年代站牌照片", "9 张实景，灯箱色温参考"],
      ],
      inject: "已注入 2 个场景实体（末班车厢 / 雨夜街道）的设计约束",
    },
  },
];

/* ------------------------------------------------------------------ */
/* 商品宣传 / 素材剪辑 · 单节点                                          */
/* ------------------------------------------------------------------ */

const promoSingle: EpisodeScript = {
  id: "promo",
  name: "30s 商品宣传片",
  panelTitle: "剧本 · 30s 商品宣传片（口播体）",
  version: "剧本 v1 · 口播体 · Agent 起草",
  status: { text: "⏱ 待你审阅", tone: "wait" },
  stages: [
    { label: "剧本 待审阅", tone: "wait" },
    { label: "设计 1/3", tone: "run" },
    { label: "生成 未开始", tone: "idle" },
  ],
  cast: [
    { label: "产品瓶", grad: "g8" },
    { label: "深夜办公室", grad: "g7" },
    { label: "手部特写", grad: "g5" },
  ],
  planMeta: [
    "30s · 8 镜 · 9:16",
    "目标平台：抖音 / 小红书 · 前 3 秒必须出现产品",
  ],
  synopsis:
    "深夜赶稿场景切入，突出冷萃原液 0糖0脂 与 3 秒便捷，结尾小黄车转化。",
  blocks: [
    { kind: "scene", text: "0–3s · 钩子" },
    {
      kind: "action",
      text: "画面：深夜办公室，键盘声密集。主角灌下第三杯速溶咖啡，皱眉盯着屏幕。产品在桌角入画（2.4s）。",
    },
    {
      kind: "line",
      character: "口播",
      text: "\u201c熬夜赶稿的第 3 杯咖啡，为什么还是又苦又困？\u201d",
    },
    { kind: "scene", text: "4–12s · 卖点 · 冷萃原液" },
    {
      kind: "action",
      text: "画面：产品从冰块中抽出，原液倒入牛奶拉出大理石纹，慢镜 120fps。角标浮现\u201c0糖 0脂\u201d。",
    },
    {
      kind: "line",
      character: "口播",
      text: "\u201c冷萃 12 小时原液，0 糖 0 脂——苦味少一半，咖啡因刚刚好。\u201d",
    },
    { kind: "scene", text: "13–22s · 场景演示" },
    {
      kind: "action",
      text: "画面：手部特写摇匀 3 秒；工位 / 地铁 / 健身房三连快切，每个场景一口下肚的满足表情。",
    },
    {
      kind: "line",
      character: "口播",
      text: "\u201c3 秒摇一摇，冷热都能泡。工位、地铁、健身房，随手一杯。\u201d",
    },
    { kind: "scene", text: "23–30s · CTA" },
    {
      kind: "action",
      text: "画面：产品全家福定版，价格贴片弹出，箭头指向小黄车。",
    },
    {
      kind: "line",
      character: "口播",
      text: "\u201c点击下方小黄车——今晚开始，告别糊弄咖啡。\u201d",
    },
    {
      kind: "hook",
      text: "投放约束（来自平台规范调研）：前 3 秒必须出现产品；字幕避开右侧 88px / 底部 240px 遮挡区；BGM 用平台免版权曲库。",
    },
  ],
};

const editSingle: EpisodeScript = {
  id: "edit",
  name: "精华剪辑 90s",
  panelTitle: "剧本 · 精华剪辑 90s（剪辑体）",
  version: "剧本 v2 · 剪辑体 · Agent 起草",
  status: { text: "⏱ 待你审阅", tone: "wait" },
  stages: [
    { label: "素材理解 完成", tone: "done" },
    { label: "剧本 待审阅", tone: "wait" },
    { label: "粗剪 未开始", tone: "idle" },
  ],
  cast: [
    { label: "访谈 A", grad: "g1" },
    { label: "B-roll", grad: "g7" },
    { label: "老照片", grad: "g8" },
  ],
  planMeta: [
    "90s · 三段式 · 16:9",
    "素材覆盖率 87% · 缺 2 段过渡空镜（已建议图库补充）",
  ],
  synopsis:
    "以「差点倒闭」金句冷开场，三段式结构：至暗 — 转折 — 升华，结尾主题字卡。",
  blocks: [
    { kind: "scene", text: "段落 1 · 钩子 · 0–12s" },
    {
      kind: "action",
      text: "冷开场，黑场起字卡后直切金句：\u201c我们差点在第三年倒闭。\u201d随后叠空场馆空镜，环境音渐入。",
      refs: [
        "▶ 访谈A.mp4 01:02:13–01:02:21",
        "▶ B-roll_07 空场馆 00:00:04–00:00:09",
      ],
    },
    { kind: "scene", text: "段落 2 · 转折 · 13–48s" },
    {
      kind: "action",
      text: "第一个大客户的故事，中段插入车库老照片慢推 + 做旧调色，再切合伙人补充视角。",
      refs: [
        "▶ 访谈A.mp4 00:47:02–00:47:30",
        "🖼 老照片_003 车库办公",
        "▶ 访谈B.mp4 00:12:44–00:13:02",
      ],
    },
    {
      kind: "line",
      character: "字幕卡",
      text: "\u201c2016 · 第一份 47 页的方案，被拒了 11 次\u201d（年份口径见调研区待确认项）",
    },
    { kind: "scene", text: "段落 3 · 升华 · 49–82s" },
    {
      kind: "action",
      text: "发布会高光，现场欢呼声保留；回切金句\u201c运气好的人很多，撑得久的很少。\u201d",
      refs: [
        "▶ 发布会主题演讲 00:21:08–00:21:26",
        "▶ 访谈A.mp4 02:40:11–02:40:19",
      ],
    },
    { kind: "scene", text: "尾板 · 83–90s" },
    {
      kind: "action",
      text: "Logo 定版 + 字幕卡\u201c十年，才刚刚开始\u201d。音乐收在重音上，留 1s 黑场。",
    },
    {
      kind: "hook",
      text: "剪辑口味：开场快切（≤2s/镜），中段放缓留呼吸感；全片响度压 -14 LUFS；访谈底噪已由素材理解标记，粗剪时自动降噪。",
    },
  ],
};

/* ------------------------------------------------------------------ */
/* 视觉开发 / 调研与素材                                                */
/* ------------------------------------------------------------------ */

const dramaVisual: VisualItem[] = [
  {
    name: "林晚 · 主形象",
    grad: "g1",
    tag: "v2",
    state: "已确认 · 被 5 集引用",
    tone: "done",
    detail: {
      type: "visual",
      title: "角色 · 林晚 主形象",
      grad: "g1",
      versions: ["v1", "v2 ●", "v3 草稿"],
      selected: 1,
      kv: [
        ["状态", "已确认（design 检查点）"],
        ["被引用", "5 集 · 23 个镜头"],
        ["一致性锚", "三人阵容图 v1"],
        ["派生自", "v1（服装修正）"],
      ],
      prompt:
        "28 岁女性，齐肩黑发微湿，米色风衣深色高领，眼神警惕而疲惫；冷蓝夜色环境光，胶片颗粒，全身立绘 + 三视角。",
    },
  },
  {
    name: "沈修 · 主形象",
    grad: "g2",
    tag: "v3",
    state: "⏱ 待确认",
    tone: "wait",
    pending: true,
    detail: {
      type: "visual",
      title: "角色 · 沈修 主形象",
      grad: "g2",
      versions: ["v1", "v2", "v3 ●"],
      selected: 2,
      kv: [
        ["状态", "待确认 · 阻塞第 3 集设计"],
        ["被引用", "3 集（规划）"],
        ["一致性锚", "三人阵容图 v1"],
        ["修改原因", "v2 眼神过于阴鸷，按批注调温和"],
      ],
      prompt:
        "32 岁男性，白大褂内深灰毛衣，金丝眼镜，温和表面下藏着克制的紧张；暖橘室内光，浅景深，半身像 + 三视角。",
    },
  },
  {
    name: "旧宅大厅 · 场景",
    grad: "g3",
    tag: "v2",
    state: "已确认",
    tone: "done",
    detail: {
      type: "visual",
      title: "场景 · 雾山旧宅大厅",
      grad: "g3",
      versions: ["v1", "v2 ●"],
      selected: 1,
      kv: [
        ["状态", "已确认"],
        ["被引用", "第 1、2 集 · 7 个镜头"],
        ["设计约束", "来自调研：90 年代苏北民宅，青瓦木构"],
      ],
      prompt:
        "废弃十年的两层木构大厅，白布蒙家具，烧焦钢琴半露，煤油灯单光源，漂浮尘埃，潮湿冷蓝调。",
    },
  },
  {
    name: "旧宅书房 · 场景",
    grad: "g4",
    tag: "生成中",
    state: "◐ 72%",
    tone: "run",
    detail: {
      type: "visual",
      title: "场景 · 旧宅书房",
      grad: "g4",
      versions: ["v1 生成中 72%"],
      selected: 0,
      kv: [
        ["状态", "生成中 · 约 40s 后完成"],
        ["被引用", "第 2 集 SC-04"],
        ["依赖", "大厅 v2（同宅一致性）"],
      ],
      prompt:
        "二层书房，整面旧书架，第三层暗格微开，焦痕账册，煤油灯光束切割黑暗，9:16 纵深构图。",
    },
  },
  {
    name: "三人阵容图",
    grad: "g5",
    tag: "v1",
    state: "已确认 · 一致性锚",
    tone: "done",
    detail: {
      type: "visual",
      title: "阵容图 · 林晚 / 沈修 / 老管家",
      grad: "g5",
      versions: ["v1 ●"],
      selected: 0,
      kv: [
        ["状态", "已确认"],
        ["作用", "多角色同框一致性锚，所有合影镜头引用"],
        ["派生", "从各角色主形象合成"],
      ],
      prompt:
        "三人正面同框全身，统一冷蓝影调与比例标尺，用于跨镜头角色一致性对齐。",
    },
  },
];

const dramaResearch: ResearchItem[] = [
  {
    icon: "🌐",
    iconBg: "rgba(59,130,246,.1)",
    title: "调研 · 90 年代苏北山村建筑（browser use · 6 个网页）",
    summary:
      "结论：青瓦木构 + 夯土墙为主，窗棂为竖条木格；已注入旧宅大厅 / 书房设计约束。",
    tag: "已核验",
    tone: "done",
    detail: {
      type: "research",
      title: "调研 · 90 年代苏北山村建筑",
      conclusion:
        "民居以青瓦双坡顶木构为主，外墙夯土或青砖，窗棂竖条木格无玻璃者常见；室内照明 90 年代初仍有煤油灯与白炽灯混用。以上作为硬约束注入场景 prompt，禁止出现现代铝合金门窗。",
      pages: [
        [
          "建筑学报 · 苏北民居调查(1992)",
          "双坡青瓦顶结构详图，檐口高度 2.8-3.2m",
        ],
        [
          "地方志数字馆 · 雾灵乡影像集",
          "17 张 90 年代实景照片，已存入参考资产",
        ],
        ["知乎 · 90年代农村照明变迁", "煤油灯淘汰时间线，佐证道具合理性"],
      ],
      inject: "已注入 2 个场景实体的设计约束（旧宅大厅 / 书房）",
    },
  },
  {
    icon: "🔍",
    iconBg: "rgba(13,148,136,.1)",
    title: "调研 · 老式煤油灯与匿名信形制（browser use · 4 个网页）",
    summary:
      "结论：马灯为主流；90 年代信件为竖式信封 + 邮戳圆章。道具设计已对齐。",
    tag: "已核验",
    tone: "done",
    detail: {
      type: "research",
      title: "调研 · 煤油灯与信件道具",
      conclusion:
        "手提马灯（防风罩 + 提梁）为夜间外出主流；室内为座式玻璃罩灯。信封应为白底红框竖式，邮戳为县级圆形日戳。",
      pages: [
        ["博物馆数字藏品 · 民用马灯", "三视图与尺寸，已转为道具参考图"],
        ["集邮论坛 · 90年代邮戳样式", "圆形日戳规格，用于第 1 集信封特写"],
      ],
      inject: "已注入道具类视觉实体 2 项",
    },
  },
  {
    icon: "📄",
    iconBg: "var(--color-success-soft)",
    title: "输入理解 · 原著小说《雾山谜案》12 章",
    summary:
      "抽取 3 位主要角色、4 个核心场景、2 处开放式抉择点；人物关系图已生成。",
    tag: "已完成",
    tone: "done",
    detail: {
      type: "source",
      title: "输入理解 · 原著小说",
      kv: [
        ["篇幅", "12 章 / 8.4 万字"],
        ["角色", "3 主要 + 6 次要"],
        ["场景", "4 核心 + 9 过场"],
        ["抉择点", "2 处（第 3、9 章）"],
      ],
      segs: [
        ["第 1-2 章", "匿名信事件，建立林晚动机与雾山空间"],
        ["第 3-5 章", "旧宅探查，账册与合影线索链"],
        ["第 6-8 章", "沈修身份反转，双线叙事"],
        ["第 9-12 章", "抉择点展开，双结局分叉"],
      ],
      note: "分集结构草案由本理解索引派生；修改理解结论将触发结构重排提示。",
    },
  },
];

const novelVisual: VisualItem[] = [
  {
    name: "沈青梧 · 主形象",
    grad: "g1",
    tag: "v2",
    state: "已确认 · 被 12 集引用",
    tone: "done",
    detail: {
      type: "visual",
      title: "角色 · 沈青梧 主形象",
      grad: "g1",
      versions: ["v1", "v2 ●"],
      selected: 1,
      kv: [
        ["状态", "已确认"],
        ["被引用", "12 集（全剧）"],
        ["一致性锚", "主角阵容图 v1"],
        ["年代校验", "1936 服饰调研已通过"],
      ],
      prompt:
        "23 岁女性船商，靛蓝布旗袍外罩短褂，发髻利落，眉眼英气；民国码头夜色，油灯暖光，全身 + 三视角。",
    },
  },
  {
    name: "顾岸声 · 主形象",
    grad: "g2",
    tag: "v1",
    state: "已确认",
    tone: "done",
    detail: {
      type: "visual",
      title: "角色 · 顾岸声 主形象",
      grad: "g2",
      versions: ["v1 ●"],
      selected: 0,
      kv: [
        ["状态", "已确认"],
        ["被引用", "第 3-12 集"],
        ["一致性锚", "主角阵容图 v1"],
      ],
      prompt:
        "30 岁报馆主笔，灰长衫圆框眼镜，袖口沾铅字油墨，儒雅锐利；报馆暖黄灯光。",
    },
  },
  {
    name: "江城码头 · 场景",
    grad: "g7",
    tag: "v3",
    state: "⏱ 待确认",
    tone: "wait",
    pending: true,
    detail: {
      type: "visual",
      title: "场景 · 江城码头夜市",
      grad: "g7",
      versions: ["v1", "v2", "v3 ●"],
      selected: 2,
      kv: [
        ["状态", "待确认 · 阻塞第 4 集分镜"],
        ["被引用", "6 集"],
        ["设计约束", "调研：1930s 长江中游码头，桅灯 + 汽灯混光"],
        ["修改原因", "v2 灯河密度不足，按批注加倍"],
      ],
      prompt:
        "1936 年江城码头夜景，千盏桅灯连成灯河倒映江面，货船桅杆如林，雾气氤氲，大纵深。",
    },
  },
  {
    name: "商会大厅 · 场景",
    grad: "g4",
    tag: "v1",
    state: "已确认",
    tone: "done",
    detail: {
      type: "visual",
      title: "场景 · 江城商会大厅",
      grad: "g4",
      versions: ["v1 ●"],
      selected: 0,
      kv: [
        ["状态", "已确认"],
        ["被引用", "第 2、8、11 集"],
      ],
      prompt: "中西合璧商会大厅，红木长桌铜吊扇，彩玻窗透冷光，权力感构图。",
    },
  },
];

const novelResearch: ResearchItem[] = [
  {
    icon: "📄",
    iconBg: "var(--color-success-soft)",
    title: "输入理解 · 长篇小说《长夜灯河》36 章",
    summary:
      "抽取 5 位主要角色、8 个核心场景；按三幕结构切分 12 集，中点在第 5 集《断航》。",
    tag: "已完成",
    tone: "done",
    detail: {
      type: "source",
      title: "输入理解 · 《长夜灯河》",
      kv: [
        ["篇幅", "36 章 / 41 万字"],
        ["角色", "5 主要 + 14 次要"],
        ["场景", "8 核心"],
        ["切分", "三幕 · 12 集 · 每集 116-130s"],
      ],
      segs: [
        ["第 1-9 章 → 第 1-4 集", "入局：码头、商会、火并、暗流"],
        ["第 10-21 章 → 第 5-8 集", "相持：断航、双城、火并、旧账"],
        ["第 22-36 章 → 第 9-12 集", "破局：决堤、离岸、灯灭、将明"],
      ],
      note: "每集剧本从对应章节自动起草，删改分集会重新映射章节区间。",
    },
  },
  {
    icon: "🌐",
    iconBg: "rgba(59,130,246,.1)",
    title: "调研 · 1936 年长江航运与民国服饰（browser use · 9 个网页）",
    summary:
      "结论：中游码头桅灯 + 汽灯混光；女性船商着改良旗袍外罩短褂。已注入全部场景与角色约束。",
    tag: "已核验",
    tone: "done",
    detail: {
      type: "research",
      title: "调研 · 民国航运年代考据",
      conclusion:
        "1930s 长江中游码头以桅灯、汽灯混合照明，电灯仅限洋行区；船商女性常见改良旗袍 + 布短褂 + 平底鞋。年代错误项（霓虹灯、的确良面料）已列入负面提示词。",
      pages: [
        ["近代航运史料库 · 江运图志", "码头布局与灯具分布图"],
        ["民国服饰图鉴 · 1930s 商贾篇", "沈青梧服装设计直接参考"],
        ["老照片档案 · 汉口码头 1935-38", "26 张实景，已存参考资产"],
      ],
      inject: "已注入 8 个场景 + 5 个角色的设计约束",
    },
  },
];

const promoVisual: VisualItem[] = [
  {
    name: "产品主体 · 冷萃瓶",
    grad: "g8",
    tag: "v1",
    state: "⏱ 待确认",
    tone: "wait",
    pending: true,
    detail: {
      type: "visual",
      title: "产品 · 冷萃咖啡液瓶",
      grad: "g8",
      versions: ["v1 ●"],
      selected: 0,
      kv: [
        ["状态", "待确认 · 阻塞全部镜头"],
        ["来源", "详情页主图重建 + 三维打光"],
        ["校验", "瓶身文字与真实包装逐字核对 ✓"],
      ],
      prompt:
        "琥珀色玻璃瓶冷萃咖啡液，瓶身结霜水珠，冰块环绕，深色背景单侧柔光，商业静物级质感。",
    },
  },
  {
    name: "深夜办公室 · 场景",
    grad: "g7",
    tag: "v1",
    state: "已确认",
    tone: "done",
    detail: {
      type: "visual",
      title: "场景 · 深夜办公室",
      grad: "g7",
      versions: ["v1 ●"],
      selected: 0,
      kv: [
        ["状态", "已确认"],
        ["被引用", "镜头 1-2"],
        ["约束", "调研：竞品 TOP20 中 14 条用暗环境开场"],
      ],
      prompt:
        "凌晨办公室工位，屏幕蓝光为主光源，桌面杂乱堆着速溶咖啡空袋，压抑疲惫氛围。",
    },
  },
  {
    name: "手部模特 · 演示",
    grad: "g5",
    tag: "v2",
    state: "已确认",
    tone: "done",
    detail: {
      type: "visual",
      title: "角色 · 手部演示",
      grad: "g5",
      versions: ["v1", "v2 ●"],
      selected: 1,
      kv: [
        ["状态", "已确认"],
        ["被引用", "镜头 5（摇匀 3 秒）"],
        ["修改原因", "v1 指甲反光过强"],
      ],
      prompt:
        "女性手部特写握瓶摇匀，动作干净利落，浅色毛衣袖口，明亮厨房背景。",
    },
  },
];

const promoResearch: ResearchItem[] = [
  {
    icon: "📄",
    iconBg: "var(--color-success-soft)",
    title: "输入理解 · 商品详情页 + 卖点清单",
    summary: "抽取 3 个核心卖点、包装规格与瓶身文案；合规词表已生成。",
    tag: "已完成",
    tone: "done",
    detail: {
      type: "source",
      title: "输入理解 · 商品资料",
      kv: [
        ["输入", "详情页 14 屏 + 卖点清单"],
        ["卖点", "3 核心 + 5 次要"],
        ["合规", "禁用「最/第一/治愈」等 12 词"],
        ["包装", "250ml 琥珀瓶 · 文案已逐字核对"],
      ],
      segs: [
        ["卖点 1", "冷萃 12h 原液，0 糖 0 脂 → 镜头 3-4"],
        ["卖点 2", "3 秒摇匀速溶 → 镜头 5"],
        ["卖点 3", "冷热双泡多场景 → 镜头 6-7"],
      ],
      note: "文案中的每个卖点句都反向链接到此理解索引。",
    },
  },
  {
    icon: "🌐",
    iconBg: "rgba(59,130,246,.1)",
    title: "调研 · 竞品 TOP20 开头 3 秒拆解（browser use · 20 条视频）",
    summary:
      "结论：14/20 用暗环境痛点开场，完播率高 23%；口播首句均为疑问句。已应用于钩子段。",
    tag: "已核验",
    tone: "done",
    detail: {
      type: "research",
      title: "调研 · 竞品开场拆解",
      conclusion:
        "高完播样本共性：①暗环境痛点场景开场（14/20）；②首句疑问句口播；③产品在 2.4s 内入画。本片钩子段（0-3s）完全按此设计。",
      pages: [
        ["抖音 · 竞品A 咖啡液爆款(赞 32w)", "痛点开场 + 2s 产品入画"],
        ["抖音 · 竞品B 冷萃测评(赞 18w)", "疑问句口播首句范式"],
        ["蝉妈妈 · 咖啡液类目投放报告", "完播率与开场类型交叉数据"],
      ],
      inject: "已注入口播文案 v1 的钩子段与镜头 1-2 设计",
    },
  },
  {
    icon: "📋",
    iconBg: "var(--color-warning-soft)",
    title: "调研 · 平台投放规范（抖音 / 小红书）",
    summary:
      "字幕安全区、时长上限、BGM 版权与违禁词校验规则已生成，将在成片审查阶段自动执行。",
    tag: "已核验",
    tone: "done",
    detail: {
      type: "research",
      title: "调研 · 平台规范",
      conclusion:
        "抖音信息流：右侧 88px 与底部 240px 为交互遮挡区，字幕需避开；30s 内完整卖点闭环；BGM 使用平台曲库免版权曲目。",
      pages: [
        ["抖音开放平台 · 广告素材规范", "安全区与尺寸标准"],
        ["小红书 · 商业笔记视频要求", "封面与首帧规范"],
      ],
      inject: "已注入字幕轨约束 + 成片审查规则 2 条",
    },
  },
];

const editResearch: ResearchItem[] = [
  {
    icon: "🎬",
    iconBg: "rgba(59,130,246,.1)",
    title: "素材理解 · 访谈A.mp4（3h12m · 视觉+语音）",
    summary:
      "ASR 全文 4.2 万字，按 27 个话题分段；金句 Top10 已标注，含「差点倒闭」段落。",
    tag: "已解析",
    tone: "done",
    detail: {
      type: "source",
      title: "素材理解 · 访谈A.mp4",
      kv: [
        ["时长", "3h12m · 4K 25fps"],
        ["语音", "ASR 4.2 万字 · 置信度 98.2%"],
        ["话题", "27 段 · 金句 Top10 已标注"],
        ["质量", "底噪 -38dB 已标记 · 3 处跳焦"],
      ],
      segs: [
        ["01:02:13", "金句★「我们差点在第三年倒闭」→ 已用于段落 1"],
        ["00:47:02", "第一个大客户始末 → 已用于段落 2"],
        ["02:40:11", "金句★「运气好的人很多，撑得久的很少」→ 段落 3"],
        ["01:44:30", "团队争执往事（备选，情绪强烈）"],
      ],
      note: "点击时间码可回看原片段；剪辑脚本中的引用与此索引双向链接。",
    },
  },
  {
    icon: "🎬",
    iconBg: "rgba(59,130,246,.1)",
    title: "素材理解 · 发布会 B-roll（46 段）",
    summary:
      "按景别与内容自动标签：空镜 12 / 人群 9 / 产品 14 / 舞台 11；每段有质量评分。",
    tag: "已解析",
    tone: "done",
    detail: {
      type: "source",
      title: "素材理解 · 发布会 B-roll",
      kv: [
        ["数量", "46 段 · 共 38m"],
        ["标签", "空镜 12 · 人群 9 · 产品 14 · 舞台 11"],
        ["质量", "评分 ≥4 星 31 段"],
        ["缺口", "缺过渡空镜 2 段（已建议图库补充）"],
      ],
      segs: [
        ["B-roll_07", "空场馆缓摇 · 5 星 → 已用于段落 1 叠化"],
        ["B-roll_21", "主题演讲聚光 · 5 星 → 段落 3"],
        ["B-roll_33", "观众起立鼓掌 · 4 星（备选）"],
      ],
      note: "标签与评分可手动修正，修正后将标记依赖脚本为过期。",
    },
  },
  {
    icon: "🖼",
    iconBg: "rgba(139,92,246,.1)",
    title: "素材理解 · 老照片 ×12（OCR + 年代判定）",
    summary:
      "车库时期 5 张 / 首次融资 3 张 / 团建 4 张；背面手写日期已 OCR 建立时间轴。",
    tag: "已解析",
    tone: "done",
    detail: {
      type: "source",
      title: "素材理解 · 老照片",
      kv: [
        ["数量", "12 张 · 已扫描 600dpi"],
        ["OCR", "背面手写日期 11/12 识别成功"],
        ["时间轴", "2014-2019 · 已排序"],
      ],
      segs: [
        ["老照片_003", "2016 车库办公 → 已用于段落 2 慢推"],
        ["老照片_007", "2017 首份合同签约（备选）"],
      ],
      note: "做旧调色参数已按扫描色偏自动生成。",
    },
  },
  {
    icon: "🌐",
    iconBg: "rgba(59,130,246,.1)",
    title: "调研 · 公司公开大事记核验（browser use · 6 条）",
    summary:
      "访谈口述的 6 个关键时间点与公开报道逐一核对，1 处出入已标注（融资年份口误）。",
    tag: "1 处待确认",
    tone: "wait",
    detail: {
      type: "research",
      title: "调研 · 大事记核验",
      conclusion:
        "口述「2017 年 A 轮」与公开报道「2018 年 1 月」不符，疑为口误。建议字幕卡采用公开口径，或在脚本中回避具体年份。",
      pages: [
        ["36氪 · A轮融资报道(2018-01)", "与口述年份出入 → 待你确认口径"],
        ["公司官网 · 大事记页", "其余 5 项全部吻合"],
      ],
      inject: "段落 2 字幕卡年份暂用「2016」（照片 OCR 佐证），待确认",
    },
  },
];

/* ------------------------------------------------------------------ */
/* 场景汇总                                                            */
/* ------------------------------------------------------------------ */

export const SCENARIOS: ScenarioData[] = [
  {
    key: "drama",
    label: "互动短剧 · 分支",
    navName: "雾山谜案 · 互动短剧",
    navPreview: "原始脚本：暴雨夜，林晚收到一封没有署名的信…",
    chips: [
      { text: "互动短剧" },
      { text: "6 个叙事节点 · 2 条结局线" },
      { text: "⏱ 分集结构待确认", warn: true },
    ],
    structure: "graph",
    structureActions: true,
    graph: dramaGraph,
    visual: dramaVisual,
    research: dramaResearch,
    defaultEpisodeId: "ep3",
    running: [
      { label: "第2集 · SC-04 视频生成", progress: 62 },
      { label: "场景 · 旧宅书房 设计图", progress: 72 },
    ],
  },
  {
    key: "novel",
    label: "小说改编 · 12集",
    navName: "长夜灯河 · 小说改编 12 集",
    navPreview: "原始输入：长篇小说《长夜灯河》36 章 / 41 万字",
    chips: [
      { text: "小说改编" },
      { text: "线性 12 集 · 每集约 2 分钟" },
      { text: "⏱ 第 5 集剧本待审阅", warn: true },
    ],
    structure: "list",
    structureActions: true,
    episodes: novelEpisodes,
    visual: novelVisual,
    research: novelResearch,
    defaultEpisodeId: "n5",
    running: [
      { label: "第4集 · 镜头 04-07 视频生成", progress: 48 },
      { label: "场景 · 江城码头 v3 重生成", progress: 31 },
    ],
  },
  {
    key: "story",
    label: "故事短片 · 单集",
    navName: "末班车 · 故事短片",
    navPreview: "原始输入：用户创作的短篇故事《末班车》（2200 字）",
    chips: [
      { text: "单集生成" },
      { text: "100s · 9:16" },
      { text: "⏱ 剧本待审阅", warn: true },
    ],
    structure: "single",
    single: storySingle,
    singleHint:
      "单集生成项目 · 与多集共用同一套剧本（场次体）→ 设计 → 生成流程，只是没有分集结构",
    strip: [
      {
        name: "输入理解",
        sub: "已完成",
        tone: "done",
        icon: "✓",
        items: [
          {
            label: "故事文本 2200 字 已解析",
            tone: "done",
            ref: {
              kind: "research",
              title: "输入理解 · 短篇故事《末班车》（2200 字）",
            },
          },
          {
            label: "角色 2 · 场景 3 已抽取",
            tone: "done",
            ref: {
              kind: "research",
              title: "输入理解 · 短篇故事《末班车》（2200 字）",
            },
          },
          {
            label: "90 年代公交年代考据",
            tone: "done",
            ref: {
              kind: "research",
              title: "调研 · 90 年代公交内饰与站牌（browser use · 5 个网页）",
            },
          },
        ],
      },
      {
        name: "剧本",
        sub: "v1 场次体 · 待你审阅",
        tone: "wait",
        icon: "⏱",
        items: [
          {
            label: "剧本 v1 · 场次体 · 3 场 10 镜",
            sub: "点击审阅全文",
            tone: "wait",
            ref: { kind: "script" },
          },
        ],
      },
      {
        name: "视觉设计",
        sub: "2/4 已确认",
        tone: "run",
        icon: "◐",
        items: [
          {
            label: "老周 v1",
            sub: "待确认 · 阻塞全部镜头",
            tone: "wait",
            ref: { kind: "visual", name: "老周 · 主形象" },
          },
          {
            label: "阿禾 v2",
            sub: "已确认",
            tone: "done",
            ref: { kind: "visual", name: "阿禾 · 主形象" },
          },
          {
            label: "末班车厢",
            sub: "生成中 58%",
            tone: "run",
            ref: { kind: "visual", name: "末班车厢 · 场景" },
          },
          {
            label: "雨夜街道 v1",
            sub: "已确认",
            tone: "done",
            ref: { kind: "visual", name: "雨夜街道 · 场景" },
          },
        ],
      },
      {
        name: "视频生成",
        sub: "0/10 镜",
        tone: "idle",
        icon: "○",
        items: [
          {
            label: "镜头 1-4 · 车厢夜戏",
            sub: "等待剧本 + 老周确认",
            tone: "idle",
          },
          { label: "镜头 5-7 · 回忆插叙", sub: "等待依赖", tone: "idle" },
          { label: "镜头 8-10 · 路口与末镜", sub: "等待依赖", tone: "idle" },
        ],
      },
      {
        name: "成片",
        sub: "100s · 竖版",
        tone: "idle",
        icon: "🔒",
        items: [
          { label: "合成 100s · 9:16", sub: "等待 10 镜完成", tone: "idle" },
        ],
      },
    ],
    visual: storyVisual,
    research: storyResearch,
    defaultEpisodeId: "story",
    running: [{ label: "场景 · 末班车厢 设计图", progress: 58 }],
  },
  {
    key: "promo",
    label: "商品宣传 · 30s",
    navName: "晨光冷萃咖啡液 · 商品宣传",
    navPreview:
      "原始输入：商品详情页 + 卖点清单（0糖0脂 / 3秒速溶 / 冷热双泡）",
    chips: [
      { text: "单视频" },
      { text: "30s · 9:16" },
      { text: "⏱ 剧本待确认", warn: true },
    ],
    structure: "single",
    single: promoSingle,
    singleHint:
      "单视频项目 · 无分集结构，确认剧本（口播体）后 Agent 直接推进生产",
    strip: [
      {
        name: "输入理解",
        sub: "已完成",
        tone: "done",
        icon: "✓",
        items: [
          {
            label: "详情页 14 屏 已解析",
            tone: "done",
            ref: {
              kind: "research",
              title: "输入理解 · 商品详情页 + 卖点清单",
            },
          },
          {
            label: "卖点 3 核心 + 5 次要",
            tone: "done",
            ref: {
              kind: "research",
              title: "输入理解 · 商品详情页 + 卖点清单",
            },
          },
          {
            label: "合规词表 12 词 已生成",
            tone: "done",
            ref: {
              kind: "research",
              title: "调研 · 平台投放规范（抖音 / 小红书）",
            },
          },
          {
            label: "竞品 TOP20 开场拆解",
            tone: "done",
            ref: {
              kind: "research",
              title:
                "调研 · 竞品 TOP20 开头 3 秒拆解（browser use · 20 条视频）",
            },
          },
        ],
      },
      {
        name: "剧本",
        sub: "v1 口播体 · 待你审阅",
        tone: "wait",
        icon: "⏱",
        items: [
          {
            label: "剧本 v1 · 口播体 · 8 镜 30s",
            sub: "点击审阅全文",
            tone: "wait",
            ref: { kind: "script" },
          },
        ],
      },
      {
        name: "视觉设计",
        sub: "1/3 已确认",
        tone: "run",
        icon: "◐",
        items: [
          {
            label: "产品瓶 v1",
            sub: "待确认 · 阻塞全部镜头",
            tone: "wait",
            ref: { kind: "visual", name: "产品主体 · 冷萃瓶" },
          },
          {
            label: "深夜办公室 v1",
            sub: "已确认",
            tone: "done",
            ref: { kind: "visual", name: "深夜办公室 · 场景" },
          },
          {
            label: "手部演示 v2",
            sub: "已确认",
            tone: "done",
            ref: { kind: "visual", name: "手部模特 · 演示" },
          },
        ],
      },
      {
        name: "视频生成",
        sub: "0/8 镜",
        tone: "idle",
        icon: "○",
        items: [
          {
            label: "镜头 1-2 · 钩子",
            sub: "等待剧本 + 产品确认",
            tone: "idle",
          },
          { label: "镜头 3-4 · 卖点慢镜", sub: "等待依赖", tone: "idle" },
          { label: "镜头 5-7 · 场景三连", sub: "等待依赖", tone: "idle" },
          { label: "镜头 8 · CTA 定版", sub: "等待依赖", tone: "idle" },
        ],
      },
      {
        name: "成片",
        sub: "30s · 竖版",
        tone: "idle",
        icon: "🔒",
        items: [
          { label: "合成 30s · 9:16", sub: "等待 8 镜完成", tone: "idle" },
          {
            label: "平台审查规则 ×2",
            sub: "已就绪，将自动执行",
            tone: "done",
            ref: {
              kind: "research",
              title: "调研 · 平台投放规范（抖音 / 小红书）",
            },
          },
        ],
      },
    ],
    visual: promoVisual,
    research: promoResearch,
    defaultEpisodeId: "promo",
    running: [],
    runningEmpty: "生产未开始：等待你确认剧本与产品视觉",
  },
  {
    key: "edit",
    label: "素材剪辑 · 单集",
    navName: "创始人访谈 · 精华剪辑",
    navPreview: "原始输入：访谈素材 3h12m + 发布会 B-roll 46 段 + 老照片 12 张",
    chips: [
      { text: "素材剪辑 · 单视频" },
      { text: "90s · 16:9" },
      { text: "⏱ 剧本待确认", warn: true },
    ],
    structure: "single",
    single: editSingle,
    singleHint:
      "剪辑项目 · 素材理解已完成，剧本（剪辑体）每一段都引用素材时间码，点击可回看原片段",
    strip: [
      {
        name: "素材理解",
        sub: "14 个素材 · 已解析",
        tone: "done",
        icon: "✓",
        items: [
          {
            label: "访谈A.mp4 · 3h12m",
            sub: "ASR 4.2 万字 · 金句 Top10",
            tone: "done",
            ref: {
              kind: "research",
              title: "素材理解 · 访谈A.mp4（3h12m · 视觉+语音）",
            },
          },
          {
            label: "发布会 B-roll · 46 段",
            sub: "景别标签 + 质量评分",
            tone: "done",
            ref: {
              kind: "research",
              title: "素材理解 · 发布会 B-roll（46 段）",
            },
          },
          {
            label: "老照片 ×12",
            sub: "OCR 时间轴 2014-2019",
            tone: "done",
            ref: {
              kind: "research",
              title: "素材理解 · 老照片 ×12（OCR + 年代判定）",
            },
          },
        ],
      },
      {
        name: "信息核验",
        sub: "6 条 · 1 处待确认",
        tone: "wait",
        icon: "⏱",
        items: [
          {
            label: "大事记核验 6 条",
            sub: "融资年份口径待你确认",
            tone: "wait",
            ref: {
              kind: "research",
              title: "调研 · 公司公开大事记核验（browser use · 6 条）",
            },
          },
        ],
      },
      {
        name: "剧本",
        sub: "v2 剪辑体 · 待你审阅",
        tone: "wait",
        icon: "⏱",
        items: [
          {
            label: "剧本 v2 · 剪辑体 · 三段式 90s",
            sub: "点击审阅全文 · 覆盖率 87%",
            tone: "wait",
            ref: { kind: "script" },
          },
        ],
      },
      {
        name: "粗剪",
        sub: "等待剧本确认",
        tone: "idle",
        icon: "○",
        items: [
          {
            label: "段落 1-3 时间线装配",
            sub: "按剧本时间码自动装配",
            tone: "idle",
          },
          {
            label: "自动降噪 + 响度 -14 LUFS",
            sub: "规则已就绪",
            tone: "done",
          },
        ],
      },
      {
        name: "精剪成片",
        sub: "90s · 16:9",
        tone: "idle",
        icon: "🔒",
        items: [
          { label: "做旧调色（老照片段）", sub: "参数已生成", tone: "done" },
          { label: "缺 2 段过渡空镜", sub: "已建议图库补充", tone: "wait" },
        ],
      },
    ],
    visual: null,
    research: editResearch,
    defaultEpisodeId: "edit",
    running: [],
    runningEmpty: "粗剪未开始：等待你确认剧本与年份口径",
  },
];

export const DEMO_PROJECT_ID = "blueprint-demo";

/** A legal ProjectDocument so the real AgentDock / PlanPage render against the store. */
export function buildDemoProject(scenario: ScenarioData): ProjectDocument {
  const clone = structuredClone(projectDocument);
  clone.project_id = DEMO_PROJECT_ID;
  clone.name = scenario.navName;
  clone.description = scenario.navPreview;
  clone.scenario = scenario.key === "edit" ? "video_edit" : "short_drama";
  clone.strategy.creative_brief =
    "（演示数据）" + (scenario.single?.synopsis ?? "分集蓝图见项目蓝图页。");
  const timeline = clone.timelines.items["timeline:main"];
  if (timeline) {
    const labels: Record<string, string> = {
      "edit-opening": "SC-01 · 开场定场",
      "r2v-window": "SC-04 · 关键情节镜头",
      "overlay-title": "字幕 · 开场标题",
      "overlay-os": "悬念贴片",
      "audio-bgm": "BGM · 主题底乐",
      transition: "转场 · 叠化",
    };
    for (const [elementId, label] of Object.entries(labels)) {
      const element = timeline.elements_by_id[elementId];
      if (element) element.label = label;
    }
  }
  return clone;
}
