/*
 * 统一 UI token —— 全 tab 共用的间距/圆角/字号梯度。
 * 标题栏几何（真机实测，密度 3.5px/vp，屏幕坐标从 y=0 全出血起算）：
 *   HDS 标题栏本体 = 状态栏下沿 39vp + 标题栏 112vp → 下缘 151vp（实测 528px）；
 *   topInset = 磨砂压暗区下缘 123vp + 呼吸边距（其余 tab 内容起点，已验收）；
 *   agentsTopInset = 标题栏下缘 151 + 搜索条区 52 + 8 呼吸边距（实测搜索条底 710px=203vp，
 *     旧值 182vp 会让满宽搜索胶囊压住智能体卡顶部 21vp）。
 */

export class UiTokens {
  static readonly pageHMargin: number = 16;   // 页面水平边距（卡片左右留白）
  static readonly cardRadius: number = 14;    // 卡片圆角
  static readonly cardPad: number = 14;       // 卡片内边距
  static readonly cardVGap: number = 8;       // 卡片垂直间距
  static readonly chipRadius: number = 6;     // 小标签圆角
  static readonly topInset: number = 130;     // 其余 tab 内容起点（磨砂压暗区下缘 123vp + 边距）
  // 聊天详情页底部避让：悬浮输入胶囊（本体 58vp）浮在消息层之上且贴底，
  // 故消息列表与 composer 上方的审批卡/待发附件/错误行都要按此留白，否则会被胶囊压住
  // （真机实测：胶囊顶 y2489px，屏幕底 2832px → 需 104vp，取 108vp 留呼吸）
  static readonly chatComposerInset: number = 108;
  // 悬浮输入胶囊本体高度 = 内边距 8×2 + 控件 42（显式给高，视效组件按百分比取高时依赖父容器确定尺寸）
  static readonly chatComposerHeight: number = 58;
  static readonly titleSearchStripH: number = 52;  // 智能体页标题栏搜索条区高度（bottomBuilder 叠加在 FREE 标题栏之上）
  // 智能体页内容起点 = 标题栏下缘 151 + 搜索条 52 + 8 呼吸边距（实测：≤203vp 时搜索胶囊压住卡片）
  // 该值同时作为 List 首项占位（spacer）高度：内容可滚到标题栏/搜索条之下（沉浸 + 渐变模糊生效前提）
  static readonly agentsTopInset: number = 211;
  // 智能体页标题栏进度映射：List 偏移 0→144vp 映射 p 0→1（用于收起键盘等）
  static readonly agentsHeaderScrollVp: number = 144;
  // —— 智能体页列表几何（真机实测，决定「首行卡碰到搜索框」的标题接管时刻）——
  static readonly agentsCardItemH: number = 120;   // 当前卡 item 高（卡 108 + 下边距 12）
  static readonly agentsSectionH: number = 38;     // 「全部智能体」段头 item 高（代码内显式定高，保证几何确定）
  static readonly agentsRowGap: number = 8;        // 行卡上边距（AgentRow margin top）
  // 首行卡可见顶（内容偏移 vp）= spacer 211 + 卡 item 120 + 段头 38 + 行上边距 8（实测 377vp）
  static readonly agentsFirstRowTop: number = 211 + 120 + 38 + 8;
  // MINI 标题栏下缘（状态栏下沿 39 + MINI 标题 56 + 搜索条 52，实测 514px=146.9vp）：
  // 首行卡顶越过此线 = 「碰到搜索框」→ 标题切换为智能体名称
  static readonly titleBarMiniBottom: number = 147;
  static readonly titleGap: number = 12;      // 页标题与内容间距
  static readonly bottomInset: number = 96;   // 底部悬浮 tab 栏（barBottomMargin 28 + 栏高 ~64 + 缓冲），滚动内容末项防遮挡

  // 标题接管判定（唯一口径，Index/AgentsTab 共用）：首行智能体卡可见顶越过 MINI 标题栏 + 搜索条下缘
  // = "列表第一个智能体卡片碰到搜索框"
  static nameTakeover(yOffsetVp: number): boolean {
    return (UiTokens.agentsFirstRowTop - yOffsetVp) <= UiTokens.titleBarMiniBottom;
  }

  // 字号梯度
  static readonly fsTitle: number = 18;
  static readonly fsBody: number = 15;
  static readonly fsSecondary: number = 13;
  static readonly fsCaption: number = 12;
  static readonly fsChip: number = 11;
}
