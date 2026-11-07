/*
 * 统一 UI token —— 全 tab 共用的间距/圆角/字号梯度。
 * 标题栏几何（真机实测，密度 3.5px/vp，屏幕坐标从 y=0 全出血起算）：
 *   HDS 标题栏本体 = 状态栏下沿 39vp + 标题栏 112vp → 下缘 151vp（实测 528px）；
 *   topInset = 磨砂压暗区下缘 123vp + 呼吸边距（其余 tab 内容起点，已验收）；
 *   agentsTopInset = 标题栏下缘 151 + 搜索条区 52 + 8 呼吸边距（实测搜索条底 710px=203vp，
 *     旧值 182vp 会让满宽搜索胶囊压住智能体卡顶部 21vp）。
 */

import { display } from '@kit.ArkUI';

// 设备密度（px / vp）：窗口避让区等量以 px 给出，换算 vp 不能写死密度（平板/PC 会算错）。
// 取不到时回落 3.5（手机实测值）。
export function pxPerVp(): number {
  try {
    return display.getDefaultDisplaySync().densityPixels;
  } catch (e) {
    return 3.5;
  }
}

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
  // 消息列表末尾留白：除悬浮输入胶囊外，还要让出浮在胶囊**之上**的会话运行状态条（模型/循环/审批
  // 三枚芯片），否则滚到底时最后一行（例如回合末的文件清单卡）会被状态条压住
  //（真机实测：芯片带 y2482..2559px，末行下沿 2598px → 被盖住）
  static readonly chatListEndInset: number = 142;
  // 悬浮输入胶囊本体高度 = 内边距 8×2 + 控件 42（显式给高，视效组件按百分比取高时依赖父容器确定尺寸）
  static readonly chatComposerHeight: number = 58;
  // 悬浮页签栏内容区高（实测栏体 203px → 内容区 175px = 58 - 栏体自身 8vp 留白）
  static readonly chatComposerBarInner: number = 50;
  // 状态条与输入胶囊之间的间距（贴紧输入框：留 3vp）
  static readonly chatRuntimeRowGap: number = 3;
  // 输入胶囊底边距屏幕底的距离（barFloatingStyle.barBottomMargin，状态条定位需用到）
  static readonly chatComposerBottomMargin: number = 12;
  static readonly titleSearchStripH: number = 52;  // 智能体页标题栏搜索条区高度（bottomBuilder 叠加在 FREE 标题栏之上）
  // 智能体页内容起点 = 标题栏下缘 151 + 搜索条 52 + 8 呼吸边距（实测：≤203vp 时搜索胶囊压住卡片）
  // 该值同时作为 List 首项占位（spacer）高度：内容可滚到标题栏/搜索条之下（沉浸 + 渐变模糊生效前提）
  static readonly searchStripTopInset: number = 211;
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
  // 社区页标题栏工具条（bottomBuilder）：分段（推荐/最新）+ 发布 一行（52）+ 分类胶囊一行（44），容器透明
  static readonly communityStripH: number = 96;
  // 社区页内容起点 = 标题栏下缘 151 + 工具条 96 + 8 呼吸边距（List 首项 spacer 占位）
  static readonly communityTopInset: number = 151 + 96 + 8;

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
