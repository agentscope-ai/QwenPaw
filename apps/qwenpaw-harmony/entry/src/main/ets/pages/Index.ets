/*
 * QwenPaw HarmonyOS · 主界面
 * 底部 tab 对齐 PR #7378 移动端：会话 / 智能体 / 社区 / 工作台。
 * tab 图标 = PR 同款 lucide SVG（message-circle / bot / users-round / layout-grid），
 *   选中 = app 主题色（accent/accentDark），未选中 = PR faint 灰（tab_faint，深浅色自适应）。
 * 标题栏 = HdsNavigation FREE 模式（静止大标题，上滚缩小至 MINI 不消失）
 *   + 渐变模糊（GRADIENT_BLUR，配 ADAPTIVE 系统材质即沉浸光感；蒙层不外扩，见 style 处说明）。
 * 智能体页标题栏：mainTitle 恒 = tab 名；当页内首行智能体卡上滑碰到搜索框时，
 *   mainTitle 变为「智能体：当前智能体名」（保留 tab 名），滚回则还原；
 *   切换用 PaddingOptions.start 0→16vp 的位移实现"从左到右出现"的滑入动画
 *   （HDS 主标题是纯字符串、无文字过渡 API）。名字不使用菜单按钮承载。
 * bottomBuilder 挂搜索条（处于标题栏材质作用域内 → 沉浸光感生效）：
 *   - 常驻全宽搜索框，上滑随标题收至 MINI 后停在标题下方，不变形、无折叠态放大镜入口；
 *   - 页内当前智能体卡随列表上滑滚到标题栏/搜索条之下（沉浸 + 渐变模糊生效）。
 * 标题栏选项 @State 备忘：仅 tab 切换 / 胶囊量化翻转时重建；bindToScrollable 只绑当前 tab 的 Scroller
 *   （官方 FAQ faqs-arkui-1095：绑多个会让滚动模糊效果丢失）。
 * 手指跟随光 = 主题色（HDS 标题栏自身材质 API 无颜色参数，系统白）。
 * 根页不显示返回按钮（hideBackButton(true)）。
 * 各 tab 内容统一顶部留白（标题栏沉浸区，见 UiTokens.topInset）。
 */

import {
  DividerShowType,
  HdsNavigation,
  HdsNavigationTitleMode,
  HdsTabs,
  HdsTabsController,
  HdsNavigationMenuContentOptions,
  HdsNavigationMenuItemOptions,
  HdsNavigationTitleBarOptions,
  TitleBarContentOptions,
  ScrollEffectType,
  BlurStrategy,
  hdsMaterial
} from '@kit.UIDesignKit';
import { uiMaterial, display, LengthMetrics, ComponentContent, window, ColorMetrics } from '@kit.ArkUI';
import { emitter, BusinessError } from '@kit.BasicServicesKit';
import { inputMethod } from '@kit.IMEKit';
import { hilog } from '@kit.PerformanceAnalysisKit';
import {
  PAWAPP_OPEN_EVENT, PawAppParam, takePawAppRequest,
  LOCAL_PAWAPP_OPEN_EVENT, LocalPawAppParam, takeLocalPawAppRequest,
  NOTIFICATIONS_OPEN_EVENT, TAB_SWITCH_EVENT, takeTabRequest, CONN_CHANGE_EVENT,
  takeSeamPageProbe
} from '../services/AppEvents';
import { common, ConfigurationConstant } from '@kit.AbilityKit';
import { ThemeManager, ThemeSnapshot, ThemeListener } from '../theme/ThemeManager';
import { syncConsoleThemeToManager } from '../services/ConsoleTheme';
import { UiTokens } from '../theme/UiTokens';
import { AGENT_CREATE_EVENT } from '../services/AgentsService';
import { ConnectPanel } from '../components/ConnectPanel';
import { chatPlaceholderPane } from '../components/ChatPlaceholder';
import { BP_LG, clampWidthOf, wideOffsetOf } from '../theme/Breakpoints';
import { SearchPill } from '../components/SearchPill';
import { AgentsTab, AgentDetailParam } from '../components/AgentsTab';
import { CommunityTab, PlatformLoginParam, CommunityComposeParam, CommunityArticleParam
} from '../components/CommunityTab';
import {
  CommunityArticleType, CommunityMeta, getCommunityMeta
} from '../services/CommunityService';
import { getPlatformAccessToken } from '../services/PlatformSession';
import { WorkbenchTab } from '../components/WorkbenchTab';
import { SegmentedControl } from '../components/SegmentedControl';
import { SettingsContent } from '../components/SettingsContent';
import { SheetGate, moduleSheetOptions } from '../components/SheetGate';
import { pushRoute, swapRoute } from '../services/NavPush';
import { recallPage, LastPage } from '../services/LastPage';
import { startLivenessWatch, stopLivenessWatch } from '../services/LivenessService';

// 图标 = PR #7378 lucide-react-native 同款几何（lucide-static 官方 SVG）
const TAB_ICONS: Resource[] = [
  $r('app.media.message_circle'),
  $r('app.media.bot'),
  $r('app.media.users_round'),
  $r('app.media.layout_grid')
];

const TAB_LABELS: Resource[] = [
  $r('app.string.tab_chats'),
  $r('app.string.tab_agents'),
  $r('app.string.tab_community'),
  $r('app.string.tab_workbench')
];
// 标题栏起始端内间距（vp）：官方 PaddingOptions.start 默认值（页面宽 < 600vp 时 16vp，实测吻合）。
// 标题切换动画 = 先把该值归 0（无动画）再动画回 16 → 新标题从左侧滑入（HDS 主标题是纯字符串、无文字过渡 API）
const TITLE_PAD_START: number = 16;
// 分栏时左栏（会话列表）宽度（vp）：官方默认 240 太窄，会话卡放不下标题+时间+菜单
const NAV_BAR_W: number = 420;
// tab 内容切换动画时长（HdsTabs.animationDuration）：工具条横向滑走/滑入与它同步（240ms 更跟手）
const TABS_ANIM_MS: number = 240;
// 标题栏动态样式线性过渡终点（vp）：官方 GRADIENT_BLUR 示例取 0→20；
// 本页两端风格同为主题色，故该区间只影响模糊渐入快慢（避免"慢慢出现主题色"的长过渡）
const BLUR_EFFECT_END_VP: number = 20;
// 社区工具条：分段高亮高度 / 分类胶囊等宽尺寸（等宽 = 滑块位移可确定性推导，不依赖测量）
const SEG_H: number = 32;
const CHIP_W: number = 92;
const CHIP_H: number = 30;
const CHIP_GAP: number = 7;

const SEAM_LOG_DOMAIN: number = 0x0000;

@Entry
@Component
struct Index {
  private stack: NavPathStack = new NavPathStack();
  // PawApp 整屏全屏：二级页用 AppStorage.set 写入（官方 faqs-arkui-1644 场景一「特定子页面
  // 缩小与放大」——全局状态变量控 Navigation.mode，子页放大为单栏），本页 mode 据此联动
  @StorageLink('pawappFullScreen')
  pawappFs: boolean = false;
  private pawAppListener: () => void = (): void => {
  };
  // 本地 PawApp（本机安装的插件，离线运行）→ 本页导航栈 localpawapp 路由
  private localPawAppListener: () => void = (): void => {
  };
  private notifyListener: () => void = (): void => {
  };
  // 二级页请求切页签（如设置页「当前 Agent」行）→ 用控制器切页，走与点击页签同一路径
  private tabSwitchListener: () => void = (): void => {
  };
  // 连接（QwenPaw 服务端）切换 / 新增 / 移除 → 主题色跟到新服务端（见 CONN_CHANGE_EVENT）
  private connChangeListener: () => void = (): void => {
  };
  // 工作台等二级入口请求打开设置弹窗
  private controller: HdsTabsController = new HdsTabsController();
  private scrollerChats: Scroller = new Scroller();
  private scrollerAgents: Scroller = new Scroller();
  private scrollerCommunity: Scroller = new Scroller();
  private scrollerWorkbench: Scroller = new Scroller();
  @State currentIndex: number = 0;
  // 根节点实时窗口宽度（vp）：大屏限宽 / 标题偏移都按它算（见 theme/Breakpoints.ets）
  @State winW: number = 0;
  @State winH: number = 0;
  private onRootArea = (_old: Area, now: Area): void => {
    const w: number = typeof now.width === 'number' ? now.width as number : 0;
    const h: number = typeof now.height === 'number' ? now.height as number : 0;
    if (h > 0 && Math.abs(h - this.winH) > 0.5) {
      this.winH = h;
    }
    if (w > 0 && Math.abs(w - this.winW) > 0.5) {
      this.winW = w;
      // 标题栏选项是 @State 备忘录（滚动帧不重建）：窗口宽度变化后必须重建一次，
      // 否则大屏偏移量只在下次切页/接管标题时才生效（首屏标题会留在最左）
      this.rebuildTitleBarOpts();
    }
  };

  // 窗口底色是 EntryAbility.loadContent 里的一次性快照：切深浅色后若不重设，缝带/手势条/
  // 页签栏周围这些无组件覆盖的区域会露出旧模式底色（浅色下成"深带压浅底"，更刺眼）→
  // appIsDark 翻转时按当前模式重解析资源（resourceColor 在调用时按系统当前配色解析）
  private onIsDarkWatch(): void {
    // 分栏空态占位是 ComponentContent（静态内容树）：资源色在创建时解析、不参与页面重渲，
    // 切深浅色后不重建就停在旧模式底色（浅色下右栏仍一片深色）→ 随模式重建，build() 重渲时换新。
    this.placeholder = new ComponentContent(this.getUIContext(), wrapBuilder(chatPlaceholderPane));
    try {
      const ctx = this.getUIContext().getHostContext() as common.UIAbilityContext;
      window.getLastWindow(ctx).then((w: window.Window): void => {
        w.setWindowBackgroundColor(ColorMetrics.resourceColor($r('app.color.page_bg')));
      }).catch((err: BusinessError): void => {
        hilog.error(SEAM_LOG_DOMAIN, 'testTag', 'window bg re-set failed: %{public}s', JSON.stringify(err));
      });
    } catch (err) {
      hilog.error(SEAM_LOG_DOMAIN, 'testTag', 'window bg re-set failed: %{public}s', JSON.stringify(err));
    }
  }

  // 会话页搜索串变化：把会话列表拉回顶部（命中项可能落在当前视口之上，不拉回等于"搜了没反应"）
  private onChatsQueryChanged(): void {
    if (this.currentIndex !== 0) {
      return;
    }
    this.scrollerChats.scrollEdge(Edge.Top);
  }
  // 内容列限宽值：窄屏退回 '100%'（不限宽）；分栏模式下左栏本身已是窄栏，不再限宽
  private clampW(): Length {
    if (this.isSplit()) {
      return '100%';
    }
    const m: number = clampWidthOf(this.winW);
    return m > 0 ? m : '100%';
  }

  // 图 / 电脑端横屏走双栏：**四个页签都双栏**（左栏 = 页签栏 + 该页列表，右栏 = 该页详情 / 空态占位）。
  // 这样 Navigation.mode 在宽屏下恒为 Split，切页签不再触发单双栏切换 —— 平台那套"导航栏 420vp ⇄ 全宽"
  // 的形变消失，切页只剩一次横向滑动（形变与横滑叠在一起的"硬/乱"从结构上不再可能出现）。
  // 每页的详情仍走同一个 NavPathStack：push 出来的详情页在右栏渲染（平台行为），返回键回列表。
  private isSplit(): boolean {
    return this.winW >= BP_LG && this.winW > this.winH;
  }

  // 分栏右栏空态：由平台 splitPlaceholder 指定占位内容（见 build()），不占路由栈 ——
  // 之前把占位页 push 进栈，会留在会话页下面（单栏下返回先落在占位页上，而该页消费返回键）
  private placeholder: ComponentContent<Object> =
    new ComponentContent(this.getUIContext(), wrapBuilder(chatPlaceholderPane));
  // 设置 = 半模态弹窗
  @State settingsShown: boolean = false;
  private settingsGate: SheetGate = new SheetGate();
  @StorageLink('appIsDark') @Watch('onIsDarkWatch') isDark: boolean = false;
  @State theme: ThemeSnapshot = ThemeManager.get().snapshot();
  // —— 智能体页标题栏联动状态 ——
  @State titleP: number = 0;                 // 头部滚动进度 0→1（AgentsTab.onDidScroll 上报，用于收起键盘等）
  @State agentsName: string = '';             // 当前智能体名（接管时作为标题显示）
  @State searchQuery: string = '';            // 智能体页标题栏搜索输入（@Prop 单向同步给 AgentsTab 过滤）
  // 会话页搜索：搜索态变化时把列表拉回顶部（列表在页面 Scroll 内，命中项可能落在视口之上）
  @State @Watch('onChatsQueryChanged') chatsQuery: string = '';
  @State wbQuery: string = '';                // 工作台搜索（@Link 同步给 WorkbenchTab）
  // —— 社区页标题栏工具条状态（放在标题栏作用域内才吃到沉浸光感与滚动模糊）——
  @State communitySort: string = 'recommended';   // 推荐 / 最新
  @State communityType: string = '';              // 分类（空 = 全部）
  @State communityTypes: CommunityArticleType[] = [];
  // —— 标题栏工具条（智能体页搜索条 / 社区页分段+分类条）双槽进出场 ——
  // 两个槽可同时在场：常态槽横向滑出 + 新槽从页面来向滑入，与 HdsTabs 切页动画同步
  // （工具条跟着整个页面划走，不是原地淡入淡出）。两槽高可能不同（52 / 96），
  // 故并存时 bottomBuilder 高度取较大者且两槽都顶对齐 → 过渡结束只改高度不改位置，不跳。
  @State stripCurTab: number = -1;   // 常态在场槽所属 tab（-1 = 无）
  @State stripCurX: number = 0;      // 常态槽横向位移
  @State stripNewTab: number = -1;   // 过渡中滑入槽所属 tab（-1 = 无）
  @State stripNewX: number = 0;      // 滑入槽横向位移
  @State stripAreaH: number = 0;     // bottomBuilder 高度（vp）
  // 标题接管态：智能体页首行卡碰到搜索框时翻转 → mainTitle 变为「智能体：名字」（带过渡动画）
  @State nameTitle: boolean = false;
  // 标题栏起始内间距：标题切换时 0→16vp 动画 = 新标题从左侧滑入
  @State titlePadStart: number = TITLE_PAD_START;
  // 社区页工具条：列表已上滑（标题收起）→ 整条上提，贴标题更近
  @State communityCollapsed: boolean = false;
  // 工具条两类沉浸材质（THIN）：玻璃框 / 玻璃框+主题色；主题或深浅变化时统一重建
  private glassMaterial: SystemUiMaterial = new uiMaterial.ImmersiveMaterial({
    style: uiMaterial.ImmersiveStyle.THIN,
    interactive: true,
    lightEffect: {}
  });
  private accentMaterial: SystemUiMaterial = new uiMaterial.ImmersiveMaterial({
    style: uiMaterial.ImmersiveStyle.THIN,
    interactive: true,
    lightEffect: {}
  });
  // 工具条过渡序号：连点切 tab 时作废上一轮未执行的定时器/动画回调
  private stripSeq: number = 0;
  private themeListener: ThemeListener | null = null;
  // 标题栏选项：必须是 @State —— 普通字段赋值不触发重渲染，.titleBar() 永不更新
  // （表现为各 tab 标题卡死首个 tab 名 + 智能体页 bottomBuilder 搜索条不出现）。
  // 仅 tab 切换 / 收起量化态翻转时重建，滚动帧不重建（逐帧新对象重设会重置滚动效果）
  @State titleBarOpts: HdsNavigationTitleBarOptions = {};

  // 标题栏菜单：只有齿轮（设置）——名字不再用菜单按钮承载，
  // 改为接管时直接替换 mainTitle（见 titleBarContent），动画由 animateTo 驱动
  private menuOptions(): HdsNavigationMenuContentOptions {
    const items: Array<HdsNavigationMenuItemOptions> = [];
    // 智能体页：＋ = 创建 Agent（事件通知智能体页打开创建表单）
    if (this.currentIndex === 1) {
      items.push({
        content: {
          icon: $r('app.media.plus'),
          action: (): void => {
            emitter.emit(AGENT_CREATE_EVENT);
          }
        }
      });
    }
    items.push({
      content: {
        label: $r('app.string.menu_settings'),
        icon: $r('sys.symbol.gearshape'),
        action: (): void => {
          this.openSettings();
        }
      }
    });
    return { value: items };
  }

  aboutToAppear(): void {
    // 连接存活探测：全应用唯一定时器（各页只订阅 CONN_LIVENESS_EVENT）
    startLivenessWatch(getContext(this) as common.UIAbilityContext);

    // App Center 请求打开 pawapp 详情：用本页导航栈 pushPath（事件 + 暂存参数，见 services/AppEvents）
    this.pawAppListener = (): void => {
      const param: PawAppParam = takePawAppRequest();
      if (param.appId.length === 0) {
        return;
      }
      pushRoute(this.stack, 'pawapp', param);
    };
    emitter.on(PAWAPP_OPEN_EVENT, this.pawAppListener);
    // 本地 PawApp（扩展模块页「本地应用」行）→ 本页导航栈 localpawapp 路由（离线运行）
    this.localPawAppListener = (): void => {
      const param: LocalPawAppParam = takeLocalPawAppRequest();
      if (param.id.length === 0) {
        return;
      }
      pushRoute(this.stack, 'localpawapp', param);
    };
    emitter.on(LOCAL_PAWAPP_OPEN_EVENT, this.localPawAppListener);
    // 通知设置入口（设置区「通知」行）→ 本页导航栈打开通知页
    this.notifyListener = (): void => {
      pushRoute(this.stack, 'notifications');
    };
    emitter.on(NOTIFICATIONS_OPEN_EVENT, this.notifyListener);
    // 二级页请求切页签：用控制器切页（changeIndex → onChange → enterTab，与点击页签同路径）
    this.tabSwitchListener = (): void => {
      const index: number = takeTabRequest();
      if (index < 0 || index === this.currentIndex) {
        return;
      }
      this.controller.changeIndex(index);
    };
    emitter.on(TAB_SWITCH_EVENT, this.tabSwitchListener);
    // 服务端变了 → 主色按新服务端重取一次并应用：控制台主色存在服务端（GET /api/config/theme），
    // 换服务端后不重取就会继续沿用上一个服务端的颜色（默认跟随服务端，见 ThemeManager）
    this.connChangeListener = (): void => {
      const c: common.UIAbilityContext =
        this.getUIContext().getHostContext() as common.UIAbilityContext;
      syncConsoleThemeToManager(c).then((): void => {
        this.applyTheme(ThemeManager.get().snapshot());
      });
    };
    emitter.on(CONN_CHANGE_EVENT, this.connChangeListener);
    // 工作台等二级入口请求打开设置弹窗
    // 沉浸光感档位一律跟随系统：材质等级固定 ADAPTIVE（官方推荐档 —— 系统按设备算力在
    // 精美/轻柔/流畅间自行调整），不再手工 getSystemMaterialTypes() 探测后写死 SMOOTH 兜底；
    // 材质类型同样交给 ADAPTIVE。uiMaterial 侧的“档位”（ImmersiveStyle 厚薄）只是偏好，
    // 低算力设备由系统保留单一档位（getGlobalMaterialLevel 只读，不可自设）。
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    this.isDark = ctx.config.colorMode === ConfigurationConstant.ColorMode.COLOR_MODE_DARK;
    this.themeListener = (snap: ThemeSnapshot): void => {
      this.applyTheme(snap);
    };
    ThemeManager.get().subscribe(this.themeListener);
    ThemeManager.get().load(ctx).then((): void => {
      this.applyTheme(ThemeManager.get().snapshot());
      // 启动时若开启「与控制台同步」，取一次控制台主题色并应用
      if (ThemeManager.get().isSyncEnabled()) {
        syncConsoleThemeToManager(ctx).then((): void => {
          this.applyTheme(ThemeManager.get().snapshot());
        });
      }
    });
    // 初始工具条：当前 tab 的槽位直接就位（不走进场动画）——四个 tab 都有工具条，否则首屏没有
    this.stripCurTab = this.currentIndex;
    this.stripCurX = 0;
    this.stripAreaH = this.stripHeightOf(this.currentIndex);
    this.rebuildTitleBarOpts();
  }

  aboutToDisappear(): void {
    stopLivenessWatch();
    emitter.off(PAWAPP_OPEN_EVENT, this.pawAppListener);
    emitter.off(LOCAL_PAWAPP_OPEN_EVENT, this.localPawAppListener);
    emitter.off(NOTIFICATIONS_OPEN_EVENT, this.notifyListener);
    emitter.off(TAB_SWITCH_EVENT, this.tabSwitchListener);
    emitter.off(CONN_CHANGE_EVENT, this.connChangeListener);
    if (this.themeListener !== null) {
      ThemeManager.get().unsubscribe(this.themeListener);
      this.themeListener = null;
    }
  }

  // 系统返回键 / 侧滑：只有 @Entry 页面的 onBackPress 生命周期能接管
  //（官方 FAQ faqs-arkui-531：onBackPress 是自定义组件生命周期回调，仅 @Entry 装饰的组件生效；
  //  返回 true = 本页自己处理返回、不走默认路由逻辑，false = 走默认逻辑即退出应用）。
  // 栈里还有详情页 → 退栈：分栏下右栏随之回到"未打开详情"的占位态；栈空（正在看列表首页）→ 返回 false 交系统退出。
  onBackPress(): boolean {
    if (this.stack.size() > 0) {
      this.stack.pop(true);
      return true;
    }
    return false;
  }

  // 主题色（深浅各取其一）：标题栏磨砂底色、搜索条手指光等的统一取色口径
  private accentColor(): ResourceColor {
    return this.isDark ? this.theme.accentDark : this.theme.accent;
  }

  // 主题快照应用 + 重建搜索条沉浸材质（手指光取主题色）+ 重建标题栏选项（磨砂底色取主题色）
  private applyTheme(snap: ThemeSnapshot): void {
    this.theme = snap;
    this.buildMaterials();
    this.rebuildTitleBarOpts();
  }

  // 对齐 PR #7378：选中 = app 主题色（浅 accent / 深 accentDark），未选中 = faint 灰。
  private tabColor(index: number): ResourceColor {
    if (this.currentIndex === index) {
      return this.isDark ? this.theme.accentDark : this.theme.accent;
    }
    return $r('app.color.tab_faint');
  }

  private openSettings(): void {
    if (this.settingsGate.request()) {
      this.settingsShown = true;
    }
  }

  @Builder
  settingsSheet() {
    SettingsContent({ stack: this.stack })
  }

  @Builder
  tabItem(index: number) {
    Column() {
      Image(TAB_ICONS[index])
        .width(24)
        .height(24)
        .fillColor(this.tabColor(index))
      Text(TAB_LABELS[index])
        .fontSize(11)
        .fontWeight(FontWeight.Medium)
        .fontColor(this.tabColor(index))
        .margin({ top: 2 })
    }
    .width('100%')
    .justifyContent(FlexAlign.Center)
    .padding({ top: 8, bottom: 14 })
  }

  // 资源串取文本（组合标题需要字符串拼接，Resource 不能直接拼）
  private resText(res: Resource): string {
    try {
      const host: common.Context = this.getUIContext().getHostContext() as common.Context;
      return host.resourceManager.getStringSync(res.id);
    } catch (e) {
      return '';
    }
  }

  // 标题栏内容：mainTitle 恒 = tab 名；智能体页首行卡碰到搜索框后（nameTitle 翻转）→
  // mainTitle 换成「智能体：当前智能体名」组合串（保留 tab 名）：
  // HDS mainTitle 是纯字符串、无文字过渡 API → 切换时用 animateTo 包裹（由系统过渡驱动）；
  // 智能体页追加 bottomBuilder 搜索条、社区页追加 bottomBuilder 工具条（其余 tab 无，标题栏高度不增）
  private titleBarContent(): TitleBarContentOptions {
    const showName: boolean = this.currentIndex === 1 && this.nameTitle && this.agentsName.length > 0;
    const mainTitle: ResourceStr = showName
      ? `${this.resText(TAB_LABELS[1])}：${this.agentsName}`
      : TAB_LABELS[this.currentIndex];
    const content: TitleBarContentOptions = {
      title: {
        mainTitle: mainTitle
      },
      menu: this.menuOptions(),
      // 标题栏分割线默认 DividerShowType.AUTO（随内容区滚动跟手显示）；它会沿 bottomBuilder 槽区
      // 上下沿各画一条极淡的线（真机实测 y≈538 / y≈698-704，比页面底色暗 10~14，浅色下读作
      // "搜索框外围一个方框"）——按官方枚举关掉。
      divider: { showType: DividerShowType.OFF }
    };
    if (this.stripAreaH > 0) {
      // 工具条槽（智能体页搜索条 / 社区页分段+分类条）：由 titleStripArea 统一派发，
      // 高度取在场各槽的较大者（过渡期间两槽并存）
      content.bottomBuilder = {
        builder: (): void => this.titleStripArea(),
        height: this.stripAreaH
      };
    }
    return content;
  }

  // 重建标题栏选项 → 写入备忘录（仅 tab 切换 / 标题接管翻转时调用；滚动进度不调）
  private rebuildTitleBarOpts(): void {
    this.titleBarOpts = this.buildTitleBarOptions();
  }

  // 标题从左侧滑入：先把起始内间距归 0（无动画）再动画回 16vp
  // （HDS 主标题是纯字符串、无文字过渡 API，借 PaddingOptions.start 做位移实现"从左到右出现"）
  private slideTitleIn(): void {
    this.titlePadStart = 0;
    this.rebuildTitleBarOpts();
    this.getUIContext().animateTo({ duration: 300, curve: Curve.EaseOut }, (): void => {
      this.titlePadStart = TITLE_PAD_START;
      this.rebuildTitleBarOpts();
    });
  }

  // 标题接管/还原：改文案 + 滑入动画
  private switchTitle(nameTitle: boolean): void {
    this.nameTitle = nameTitle;
    this.slideTitleIn();
  }

  // 标题栏选项工厂
  private buildTitleBarOptions(): HdsNavigationTitleBarOptions {
    return {
      // 起始内间距（接管/切换时 0→16vp 动画 = 标题从左侧滑入）；end 用官方默认 16vp。
      // 大屏再加一个与内容列居中等量的偏移 → 主标题与内容列/工具条左边界对齐
      padding: {
        start: LengthMetrics.vp(this.titlePadStart + (this.isSplit() ? 0 : wideOffsetOf(this.winW)))
      },
      content: this.titleBarContent(),
      style: {
        // 沉浸式渐变模糊（选定方案 A）：沉浸式渐变模糊，标题栏与底部 TabBar 同处沉浸模式。
        // 平台行为：深色下沉浸材质是"变暗玻璃"，会把标题栏底色压低 → 静止态与页面底色接近
        //（观感偏"透明"，这是沉浸模式的固有表现，非未生效）。
        // 底色仍显式给主题色，滚动渐变终点态与静止态保持一致。
        scrollEffectOpts: {
          // enableScrollEffect = false：官方口径「不随内容区滚动动态生效标题栏样式，仅生效 originalStyle」，
          // 且 GRADIENT_BLUR 下「直接生效模糊。此方式适用于列表型非沉浸式场景」。
          // 为什么不用 true：为 true 时样式会在 originalStyle→scrollEffectStyle 之间随滚动**插值**，
          // 上滚过程出现"先变暗、再慢慢回到主题色"的过渡观感（反复被报的"往上滑突然变黑然后慢慢
          // 出现主题色"）；关掉后底色/模糊只有一个状态，结构上不可能再出现滚动时变色。
          // 标题栏随滚动收起（titleMode FREE）与内容穿过时的模糊都不受影响。
          enableScrollEffect: false,
          scrollEffectType: ScrollEffectType.GRADIENT_BLUR
        },
        // blurStrategy 用 ENABLE 而不是 ADAPTIVE：官方口径 ADAPTIVE「根据系统策略调整…只有精美档位
        // 配置能够生效模糊效果」—— 系统策略落在轻柔/流畅档时标题栏模糊整块不生效，内容滚过时就露出
        // 未模糊的暗色内容（观感即"往上滑突然变黑"）；ENABLE 恒生效，观感才稳定。
        blurStrategy: BlurStrategy.ENABLE,
        originalStyle: {
          backgroundStyle: {
            blurRadius: 12.0,
            // 蒙层外扩必须写在**生效态**里：enableScrollEffect=false 时只生效 originalStyle，
            // 写在 scrollEffectStyle 里会被忽略、退回平台默认外扩（真机实测蒙层 822 → 标题栏底边
            // 710 之下多出 112px≈56vp），那段在工具条正下方留下一条中性灰带（浅色模式即"接缝"）；
            // 归零后蒙层与标题栏同底（710），渐隐在标题栏内完成，内容区不再被蒙层压到。
            maskExtraHeight: 0.0,
            backgroundColor: this.accentColor()
          }
        },
        scrollEffectStyle: {
          backgroundStyle: {
            blurRadius: 12.0,
            backgroundColor: this.accentColor()
          }
        },
        systemMaterialEffect: {
          materialType: hdsMaterial.MaterialType.ADAPTIVE,
          materialLevel: hdsMaterial.MaterialLevel.ADAPTIVE
        }
      },
      avoidLayoutSafeArea: false,
      enableComponentSafeArea: false
    };
  }

  // 当前 tab 的滚动控制器 —— bindToScrollable 只绑它：
  // 官方 FAQ（faqs-arkui-1095 场景二）明确「bindToScrollable 仅动态绑定当前 Tab 的 Scroller」，
  // 一次绑多个 Scroller 会让滚动模糊效果丢失（此前 4 个一起绑 = 沉浸/渐变模糊一直不出现的根因）
  private currentScroller(): Scroller {
    if (this.currentIndex === 1) {
      return this.scrollerAgents;
    }
    if (this.currentIndex === 2) {
      return this.scrollerCommunity;
    }
    if (this.currentIndex === 3) {
      return this.scrollerWorkbench;
    }
    return this.scrollerChats;
  }

  // 工具条滑动幅宽（vp）：标题栏恒等窗口宽 → 用实时窗口宽（winW），折叠/展开、PC 拖窗口
  // 后仍正确；仅首帧 area 未上报前回落当前屏宽
  private stripSlideW(): number {
    if (this.winW > 0) {
      return this.winW;
    }
    return this.getUIContext().px2vp(display.getDefaultDisplaySync().width);
  }

  // 工具条槽高度（vp）：社区页 96（分段 + 分类两排），其余三个 tab 都是 52（标题栏搜索条）
  private stripHeightOf(tab: number): number {
    return tab === 2 ? UiTokens.communityStripH : UiTokens.titleSearchStripH;
  }

  // 标题栏工具条容器：双槽 Stack（常态槽 + 过渡滑入槽），两槽顶对齐 + 整体裁切。
  // 位移由槽容器承载 —— @Builder 调用不能链式挂属性，故槽位各包一层 Column 承接 translate。
  @Builder
  titleStripArea() {
    Stack({ alignContent: Alignment.TopStart }) {
      if (this.stripCurTab >= 0) {
        Column() {
          this.stripOf(this.stripCurTab)
        }
        .width('100%')
        .height(this.stripHeightOf(this.stripCurTab))
        .translate({ x: this.stripCurX })
      }
      if (this.stripNewTab >= 0) {
        Column() {
          this.stripOf(this.stripNewTab)
        }
        .width('100%')
        .height(this.stripHeightOf(this.stripNewTab))
        .translate({ x: this.stripNewX })
      }
    }
    .width('100%')
    .height(this.stripAreaH)
    // 不整体裁切：槽位横向位移是 ±屏宽（本身就落在屏外，无溢出），而社区工具条上提要 -12vp，
    // 裁切会把上提那截直接切掉（表现为"贴不近标题"）。
  }

  // 槽位内容派发：0/1/3 = 标题栏搜索条（会话 / 智能体 / 工作台），2 = 社区页分段+分类条
  @Builder
  stripOf(tab: number) {
    if (tab === 2) {
      this.titleCommunityStrip()
    } else {
      this.titleSearchArea(tab)
    }
  }

  // 切页总入口（由 HdsTabs.onAnimationStart 调用）：落定当前页 + 工具条横向滑 + 标题联动
  private enterTab(from: number, to: number): void {
    this.currentIndex = to;
    // 换页签 = 换一栏内容：右栏不能留着上一个页签的详情页（双栏下会被当成"当前页的详情"），
    // 故与切页同帧退栈（NavPathStack 连续多次操作只渲染最终态）。用带过场的 pop，详情页顺势滑出。
    if (to !== from && this.stack.size() > 0) {
      for (let i = this.stack.size(); i > 0; i--) {
        this.stack.pop(true);
      }
    }
    // 退栈之后：按该页签的记忆把上次点进去的二级页放回右栏（顺序不能反 —— 先恢复会被上面的退栈弹掉）
    if (to !== from) {
      this.restoreLastPage(to);
    }
    if (to === 2) {
      // 社区页：分类胶囊取 Platform meta（缓存；失败只剩「全部」）。这是异步请求 + 一次状态落地
      //（会重建标题栏工具条与页内胶囊列），若与切页动画同帧发起，落地时机正好压在中途 →
      // 观感是"页面滑到一半自己抖一下"。故让开动画帧再取（与 moveStrip 的收尾同一节奏）。
      setTimeout((): void => {
        this.loadCommunityTypes();
      }, TABS_ANIM_MS + 40);
    }
    this.moveStrip(from, to, to > from ? 1 : -1);
    if (to === 1) {
      // 回到智能体页：按 List 当前偏移回同步（滚动进度 + 标题接管态），标题滑入
      const y: number = this.scrollerAgents.currentOffset().yOffset as number;
      this.titleP = Math.max(0, Math.min(1, y / UiTokens.agentsHeaderScrollVp));
      this.switchTitle(UiTokens.nameTakeover(y));
    } else if (this.nameTitle) {
      // 离开智能体页：标题还原为 tab 名（带滑入动画）
      this.switchTitle(false);
    } else {
      // 其余 tab 互切：标题换名同样从左侧滑入
      this.slideTitleIn();
    }
  }

  // 分栏下恢复该页签最后打开的二级页（智能体详情 / 社区文章 / 工作台模块与分类页）。
  // 只在分栏下做：单栏是整页推入式，"切回列表就该停在列表"；记忆由各页签在打开二级页时写入
  // （services/LastPage，进程内 —— 产品口径是"打开过、点过才要记忆"，启动不恢复）。
  private restoreLastPage(tab: number): void {
    if (!this.isSplit()) {
      return;
    }
    const rec: LastPage | null = recallPage(tab);
    if (rec === null) {
      return;
    }
    if (rec.route === 'agent') {
      const p: AgentDetailParam = { agentId: rec.key };
      swapRoute(this.stack, 'agent', p);
    } else if (rec.route === 'community-article') {
      const p: CommunityArticleParam = { articleId: rec.key, stack: this.stack };
      swapRoute(this.stack, 'community-article', p);
    } else if (rec.route === 'module') {
      const p: Record<string, string> = { 'key': rec.key };
      swapRoute(this.stack, 'module', p);
    } else if (rec.route === 'workbench-category') {
      const p: Record<string, Object> = { 'key': rec.key, 'stack': this.stack };
      swapRoute(this.stack, 'workbench-category', p);
    }
  }

  // 开关 tab 时工具条随页面横向滑动（与 HdsTabs.animationDuration 同长同步）：
  // 旧槽从 0 滑到页面滑动方向的外侧（"跟着整个页面划走"），新槽从反向外侧滑到 0。
  private moveStrip(was: number, next: number, dir: number): void {
    const wasH: number = this.stripHeightOf(was);
    const nextH: number = this.stripHeightOf(next);
    const w: number = this.stripSlideW();
    // 连点切 tab 时旧一轮的定时器会回写状态 → 用序号作废过期回调
    const seq: number = ++this.stripSeq;
    // 并存期间容器取较高者；两槽都顶对齐 → 过渡结束只回收高度，不产生纵向跳动
    this.stripAreaH = Math.max(wasH, nextH);
    this.stripCurTab = wasH > 0 ? was : -1;
    this.stripCurX = 0;
    this.stripNewTab = nextH > 0 ? next : -1;
    this.stripNewX = dir * w;
    this.rebuildTitleBarOpts();
    // 先让「新槽在页面外侧」这一帧渲染出来，再补间（否则动画没有起点帧）
    setTimeout((): void => {
      if (seq !== this.stripSeq) {
        return;
      }
      this.getUIContext().animateTo({ duration: TABS_ANIM_MS, curve: Curve.EaseOut }, (): void => {
        if (this.stripCurTab >= 0) {
          this.stripCurX = -dir * w;
        }
        if (this.stripNewTab >= 0) {
          this.stripNewX = 0;
        }
      });
    }, 16);
    // 动画结束后收敛到常态槽：旧槽退场、新槽就位（做常驻槽），高度回到该槽自身高度
    setTimeout((): void => {
      if (seq !== this.stripSeq) {
        return;
      }
      this.stripCurTab = nextH > 0 ? next : -1;
      this.stripCurX = 0;
      this.stripNewTab = -1;
      this.stripNewX = 0;
      this.stripAreaH = nextH;
      this.rebuildTitleBarOpts();
    }, TABS_ANIM_MS + 40);
  }

  // 标题栏搜索条（bottomBuilder，位于标题栏材质作用域内 → 沉浸光感生效）：
  // 会话 / 智能体 / 工作台三个 tab 共用同一形态（胶囊 = SearchPill，内容随 tab 换状态与占位符）——
  // 此前只有智能体页把搜索放进标题栏，会话页与工作台页的搜索留在页内（无材质、无进出场动画），
  // 三处此前不一致（会话/工作台的搜索留在页内，无材质也无进出场动画），故统一到标题栏。
  @Builder
  titleSearchArea(tab: number) {
    Row() {
      if (tab === 0) {
        SearchPill({
          query: $chatsQuery,
          placeholder: $r('app.string.chats_search_placeholder'),
          inputId: 'chats_search_input'
        })
      } else if (tab === 3) {
        SearchPill({
          query: $wbQuery,
          placeholder: $r('app.string.workbench_search'),
          inputId: 'workbench_search_input'
        })
      } else {
        SearchPill({
          query: $searchQuery,
          placeholder: $r('app.string.agents_search_placeholder'),
          inputId: 'agents_search_input'
        })
      }
    }
    .width('100%')
    .constraintSize({ maxWidth: this.clampW() })
    .height(UiTokens.titleSearchStripH)
    .padding({ left: 4, right: 4 })
    .justifyContent(FlexAlign.End)
    .alignItems(VerticalAlign.Center)
    // clip 兜底：胶囊宽度确定性推导，恒不超搜索条；即便推导有偏也不溢出标题栏（防飞出屏）
    .clip(true)
  }

  // ============ 社区页标题栏工具条（bottomBuilder）============
  // 为什么放标题栏而不是页内：① bottomBuilder 在标题栏材质作用域内 → 沉浸光感生效；
  // ② 随 FREE 标题上滑一起上移、缩到 MINI 标题下方但不消失（官方 FREE 标题栏行为）；
  // ③ 容器不铺底色/材质，不遮住下方内容，底色与模糊由标题栏自身托底。

  // 主题色玻璃：主题色按低 alpha 掺进材质层（不透明主题色会盖掉材质滤镜）—— 发布按钮用
  private accentGlass(): ResourceColor {
    const a: ResourceColor = this.accentColor();
    if (typeof a === 'string' && a.length === 7) {
      return `#4D${(a as string).substring(1)}`;
    }
    return a;
  }

  // 工具条两类沉浸材质（THIN 薄档）：① 玻璃框（无底色）② 玻璃框 + 主题色（选中/主行动）
  // 只建一次、主题或深浅变化时重建 —— 避免每帧构造材质对象（会重置材质渲染）
  private buildMaterials(): void {
    this.glassMaterial = new uiMaterial.ImmersiveMaterial({
      style: uiMaterial.ImmersiveStyle.THIN,
      interactive: true,
      lightEffect: {}
    });
    this.accentMaterial = new uiMaterial.ImmersiveMaterial({
      style: uiMaterial.ImmersiveStyle.THIN,
      interactive: true,
      lightEffect: {},
      materialColor: this.accentGlass()
    });
  }


  // 分类（Platform meta；失败则只剩「全部」）
  private loadCommunityTypes(): void {
    if (this.communityTypes.length > 0) {
      return;
    }
    getCommunityMeta().then((meta: CommunityMeta): void => {
      this.communityTypes = meta.filterTypes;
    }).catch((): void => {
    });
  }

  // 推荐/最新切换：animateTo 驱动滑块位移（有过渡，不瞬跳）
  private setCommunitySort(key: string): void {
    if (this.communitySort === key) {
      return;
    }
    this.getUIContext().animateTo({ duration: 220, curve: Curve.EaseOut }, (): void => {
      this.communitySort = key;
    });
  }

  private setCommunityType(code: string): void {
    if (this.communityType === code) {
      return;
    }
    this.getUIContext().animateTo({ duration: 200, curve: Curve.EaseOut }, (): void => {
      this.communityType = code;
    });
  }

  // 发布：未登录先去 Platform 登录页（对齐 7378 openComposer）
  private openCommunityCompose(): void {
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    getPlatformAccessToken(ctx).then((token: string): void => {
      if (token.length > 0) {
        const composeParam: CommunityComposeParam = { stack: this.stack };
        pushRoute(this.stack, 'community-compose', composeParam);
        return;
      }
      const param: PlatformLoginParam = { returnTo: 'compose', stack: this.stack };
      pushRoute(this.stack, 'platform-login', param);
    });
  }

  @Builder
  titleCommunityStrip() {
    Column() {
      // 第一排：推荐/最新 —— **一个大框**（整条挂一次沉浸光感材质）+ 框内滑块「跑过去」的选中动画
      Row({ space: 8 }) {
        // 「一个大框」+ 框内滑块跟手跑过去（共用组件 components/SegmentedControl.ets）：
        // 整条一次 ImmersiveMaterial（沉浸光感），滑块只做浅色玻璃位移 —— 工具条底下就是标题栏主题色
        // 渐变带，主题色玻璃叠带 Δ≈6/255、浅色玻璃再挂材质 Δ≈8/255 均读不出来，纯浅色玻璃 Δ≈40/255
        // 才看得出"跑过去"（真机取样）。
        Row() {
          SegmentedControl({
            labels: [$r('app.string.community_sort_recommended'),
              $r('app.string.community_sort_latest')],
            selectedIndex: this.communitySort === 'latest' ? 1 : 0,
            segHeight: SEG_H,
            pad: 4,
            material: this.glassMaterial,
            onChange: (index: number): void => {
              this.setCommunitySort(index === 1 ? 'latest' : 'recommended');
            }
          })
        }
        .layoutWeight(1)

        Toggle({ type: ToggleType.Button, isOn: false }) {
          Row({ space: 4 }) {
            Image($r('app.media.square_pen'))
              .width(14).height(14)
              .fillColor(Color.White)
            Text($r('app.string.community_publish'))
              .fontSize(UiTokens.fsSecondary)
              .fontWeight(FontWeight.Medium)
              .fontColor(Color.White)
          }
        }
        .height(36)
        .padding({ left: 12, right: 12 })
        .backgroundColor(Color.Transparent)
        .systemMaterial(this.accentMaterial)
        .selectedColor(Color.Transparent)
        .onChange((_isOn: boolean): void => {
          this.openCommunityCompose();
        })
      }
      .width('100%')
      .height(52)
      .padding({ left: UiTokens.pageHMargin, right: UiTokens.pageHMargin })
      .alignItems(VerticalAlign.Center)

      // 第二排：分类胶囊 —— **每个按钮自带沉浸光感的框**，选中的叠一点主题色
      Scroll() {
        Row({ space: CHIP_GAP }) {
          this.communityTypeChip('', $r('app.string.community_all'))
          ForEach(this.communityTypes, (type: CommunityArticleType) => {
            this.communityTypeChip(type.code, type.label)
          }, (type: CommunityArticleType) => type.code)
        }
        .height(CHIP_H)
        .padding({ left: UiTokens.pageHMargin, right: UiTokens.pageHMargin })
      }
      .scrollable(ScrollDirection.Horizontal)
      .scrollBar(BarState.Off)
      .width('100%')
      .height(44)
      .align(Alignment.Start)
    }
    .width('100%')
    .constraintSize({ maxWidth: this.clampW() })
    .height(UiTokens.communityStripH)
    .alignItems(HorizontalAlign.Start)
    // 容器自身不铺颜色也不铺材质：底色与模糊由标题栏 GRADIENT_BLUR 托底（maskExtraHeight = 0，
    // 标题栏高度本身已含本条带）；横向进出场由 titleStripArea 的槽容器承载。
    // 上滑（标题收起）后整条上提 12vp → 贴标题更近（验收：上划往上收之后要贴标题再近一点）
    .translate({ y: this.communityCollapsed ? -12 : 0 })
  }

  // 主题色玻璃：把主题色按低 alpha 掺进材质层（不透明色会盖掉材质滤镜）
  // 分段按钮：等宽、无底色（选中态由上面的滑块承载）；选中与否字色一致（未选中不做变暗处理）
  // 分类胶囊：**每个按钮自带沉浸光感的框**（THIN 材质），选中的在材质上叠一点主题色
  // （materialColor = #4D+主题色 —— 半透明才不会被材质滤镜盖掉）；选中/未选中字色一致（不变暗）
  @Builder
  communityTypeChip(code: string, label: ResourceStr) {
    Row() {
      Text(label)
        .fontSize(UiTokens.fsCaption)
        .fontWeight(FontWeight.Medium)
        .fontColor($r('app.color.text_primary_strong'))
        .textAlign(TextAlign.Center)
    }
    .height(CHIP_H)
    .constraintSize({ minWidth: CHIP_W })
    .padding({ left: 14, right: 14 })
    .justifyContent(FlexAlign.Center)
    .borderRadius(CHIP_H / 2)
    .systemMaterial(this.communityType === code ? this.accentMaterial : this.glassMaterial)
    .onClick((): void => {
      this.setCommunityType(code);
    })
  }

  build() {
    HdsNavigation(this.stack) {
      HdsTabs({ controller: this.controller }) {
        TabContent() {
          Scroll(this.scrollerChats) {
            Column() {
              ConnectPanel({
                navStack: this.stack,
                query: this.chatsQuery,
                activeTab: this.currentIndex,
                wideLandscape: this.winW >= BP_LG && this.winW > this.winH
              })
            }
            .width('100%')
            .constraintSize({ minHeight: '100%', maxWidth: this.clampW() })
            // 顶部留白按「标题栏 + 搜索条 + 呼吸」给（会话/智能体/工作台三个 tab 都有搜索条）
            .padding({ top: UiTokens.searchStripTopInset, bottom: UiTokens.bottomInset })
            .backgroundColor($r('app.color.page_bg'))
          }
          .align(Alignment.Top)
          .clipContent(ContentClipMode.SAFE_AREA)
          .height('100%')
          // 底部不回弹（产品口径 2026-10-17）：只保留起始边（顶边下拉刷新）的边缘效果，
          // 冲底不再弹性下移，内容不会被悬浮页签栏压住
          .edgeEffect(EdgeEffect.Spring, { alwaysEnabled: true, effectEdge: EffectEdge.START })
        }
        .tabBar(this.tabItem(0))

        TabContent() {
          // 大屏内容列限宽（官方《页面布局场景》缩进布局）：与其余 tab 同一口径
          Row() {
            Column() {
              // 智能体页自持 List（内滚 + 下拉刷新）：
              // 标题栏搜索条 / 标题接管经 query + onHeaderState 联动
              AgentsTab({
                scroller: this.scrollerAgents,
                navStack: this.stack,
                split: this.isSplit(),
                query: this.searchQuery,
                onHeaderState: (p: number, name: string, takeover: boolean): void => {
                  const was: number = this.titleP;
                  const nameChanged: boolean = name !== this.agentsName;
                  this.titleP = p;
                  this.agentsName = name;
                  if (takeover !== this.nameTitle) {
                    // 接管/还原：换文案 + 滑入动画
                    this.switchTitle(takeover);
                  } else if (nameChanged && this.nameTitle) {
                    // 接管态下切换了智能体：标题组合串随之更新（同样带滑入动画）
                    this.slideTitleIn();
                  }
                  if (was <= 0.5 && p > 0.5) {
                    // 滚动过半：释放输入焦点（收起键盘），让位标题栏
                    this.getUIContext().getFocusController().clearFocus();
                  }
                }
              })
            }
            .width(this.clampW())
            .height('100%')
          }
          .width('100%')
          .height('100%')
          .justifyContent(FlexAlign.Center)
        }
        .tabBar(this.tabItem(1))

        TabContent() {
          // 大屏内容列限宽（官方《页面布局场景》缩进布局）：与其余 tab 同一口径
          Row() {
            Column() {
              // 社区页自持 List（内滚 + 下拉刷新 + 滑到底翻页）：标题栏滚动模糊只绑当前 tab 的 Scroller；
              // 排序/分类状态由标题栏工具条持有（@Prop 单向同步过来，变更即重取）
              CommunityTab({
                scroller: this.scrollerCommunity,
                navStack: this.stack,
                onScrollY: (y: number): void => {
                  // 标题收起（列表滚过一点）→ 工具条上提 12vp 贴标题
                  const collapsed: boolean = y > 16;
                  if (collapsed !== this.communityCollapsed) {
                    this.communityCollapsed = collapsed;
                  }
                },
                sort: this.communitySort,
                type: this.communityType
              })
            }
            .width(this.clampW())
            .height('100%')
          }
          .width('100%')
          .height('100%')
          .justifyContent(FlexAlign.Center)
        }
        .tabBar(this.tabItem(2))

        TabContent() {
          Scroll(this.scrollerWorkbench) {
            Column() {
              WorkbenchTab({ navStack: this.stack, query: this.wbQuery })
            }
            .width('100%')
            .constraintSize({ maxWidth: this.clampW() })
          }
          .align(Alignment.Top)
          .clipContent(ContentClipMode.SAFE_AREA)
          .height('100%')
          // 底部不回弹（同会话页签）：只保留顶边边缘效果
          .edgeEffect(EdgeEffect.Spring, { alwaysEnabled: true, effectEdge: EffectEdge.START })
        }
        .tabBar(this.tabItem(3))
      }
      .barOverlap(true)
      // 关闭左右滑动切换：HdsTabs 只暴露 onChange / onAnimationStart / onContentWillChange，
      // **没有拖动过程中的偏移回调**，所以"手指还在拖"时工具条无法跟着页面走（页面已位移、工具条不动
      // 观感就是"我还没切换它就先动了"）。7378 的 tab 布局同样没有滑动切换（animation: "fade"，
      // 只按页签切换），故这里与之一致：只走点击切换 → 工具条与页面动画严格同步。
      .scrollable(false)
      // tab 内容切换动画时长：工具条的横向滑走/滑入用它同步（否则页面滑了、工具条原地跳）
      .animationDuration(TABS_ANIM_MS)
      .vertical(false)
      .barPosition(BarPosition.End)
      // 底部悬浮页签栏浮在内容之上（barOverlap + barBottomMargin），页签栏以下的区域属于 Tabs 自身 →
      // 不给底色就会露出窗口默认色（暗色下就是一条黑带）。统一铺页面底色 + 扩安全区到窗口四边
      // （只铺底色不扩安全区时，落到手势条一带仍是窗口底色）。
      .backgroundColor($r('app.color.page_bg'))
      .expandSafeArea([SafeAreaType.SYSTEM],
        [SafeAreaEdge.TOP, SafeAreaEdge.BOTTOM, SafeAreaEdge.START, SafeAreaEdge.END])
      // 工具条的横向滑走/滑入必须挂在 **onAnimationStart**（切换动画开始时）而不是 onChange：
      // 官方 FAQ faqs-arkui-568《如何解决自定义tabBar切换动画有明显延迟感的问题》——onChange 在页签
      // 切换**完成后**才触发，于是"页面滑完了工具条才开始动"，观感即"反应太慢"。onAnimationStart 的
      // 参数是 (源下标, 目标下标) → 正好给出方向；注意两者不能用同一个状态变量，否则页面切换动画会消失。
      .onAnimationStart((from: number, to: number) => {
        // 一进入动画就把 currentIndex 落定到目标页：标题栏的回缩程度由 bindToScrollable 绑的
        // Scroller 决定（currentScroller() 读 currentIndex）——留到 onChange（动画结束）才换绑，
        // 就会出现"两页滚动位置不同 → 标题栏回缩程度不同 → 切换动画突兀/结束后跳一下"。
        // 一并驱动工具条双槽横向滑（与页面动画同时开始，不慢于页面）。
        this.enterTab(from, to);
      })
      .onChange((index: number) => {
        // 安全网：极端情况（如控制器 changeIndex）下与 onAnimationStart 不同步时补一次
        if (index !== this.currentIndex) {
          this.enterTab(this.currentIndex, index);
        }
      })
      .barFloatingStyle({
        barBottomMargin: 28,
        // 手指跟随光 = 主题色（比 accent 浅一档的 tint，深浅模式各取其一）
        lightColor: this.isDark ? this.theme.fingerGlowDark : this.theme.fingerGlow,
        systemMaterialEffect: {
          materialType: hdsMaterial.MaterialType.ADAPTIVE,
          materialLevel: hdsMaterial.MaterialLevel.ADAPTIVE
        }
      })
    }
    // 平板 / PC（lg 档）走分栏：平台自带「左导航栏 + 右内容区」——会话页即「左会话栏 + 右聊天栏」
    //（官方口径：mode = Stack / Split / Auto；Auto 在折叠屏与平板默认分栏）。窄屏仍单栏。
    // PawApp 整屏全屏时强制单栏：路由栈顶的 PawApp 页放大为整屏（官方 faqs-arkui-1644 场景一），
    // 左导航栏随之收起；退出全屏（或该页出栈）自动回到分栏
    .mode(this.pawappFs ? NavigationMode.Stack : (this.isSplit() ? NavigationMode.Split : NavigationMode.Stack))
    // 单双栏切换动画保持平台默认开启：本页 navBar 就是整条 HdsTabs，切 tab 触发的"导航栏
    // 420vp ⇄ 全宽"由平台做形变（enableModeChangeAnimation 默认 true）。关掉它会变成一帧内的
    // 硬跳位（观感"硬"）；保留形变后单双栏是连续过渡，切页观感只剩横向滑动 + 形变两条。
    // （官方 arkts-navigation-split-mode：enableModeChangeAnimation 控制单双栏切换动画，默认开启）
    .enableModeChangeAnimation(true)
    // 分栏右栏空态内容：官方 splitPlaceholder —— 占位内容不进路由栈（详见 components/ChatPlaceholder.ets）
    .splitPlaceholder(this.placeholder)
    // 左栏宽度：官方默认 240vp 偏窄（会话列表挤在一起）→ 给 420vp
    .navBarWidth(NAV_BAR_W)
    // 双栏是四个页签共用的一条左栏：各页列表宽度需求不同（工作台/智能体的卡片更宽），
    // 按官方 enableDragBar + navBarWidthRange 放开分隔条拖拽，由使用者拖到合适宽度
    .enableDragBar(true)
    .navBarWidthRange({ minWidth: 320, maxWidth: 760 })
    // 根容器铺页面底色 + 扩安全区到窗口四边（与二级页同一口径）：底部悬浮页签栏周围、
    // 手势条一带、屏幕左右两侧都由这里托底，避免露出窗口默认的黑带。
    .backgroundColor($r('app.color.page_bg'))
    .expandSafeArea([SafeAreaType.SYSTEM],
      [SafeAreaEdge.TOP, SafeAreaEdge.BOTTOM, SafeAreaEdge.START, SafeAreaEdge.END])
    // 选项走备忘录（同对象引用）：滚动帧 build() 重跑不重设 → 滚动效果（渐变模糊/沉浸光感）不被逐帧重置
    .titleBar(this.titleBarOpts)
    // 标题栏 FREE 滚动效果：上滚时大标题缩小至 MINI（各 tab 统一）；
    // 智能体页内容（当前卡等）随列表上滑滚到标题栏/搜索条之下 → 沉浸 + 渐变模糊生效
    // 只绑当前 tab 的 Scroller（官方 FAQ faqs-arkui-1095 场景二：绑多个会让滚动模糊效果丢失）
    .bindToScrollable([this.currentScroller()])
    .hideBackButton(true)
    .titleMode(HdsNavigationTitleMode.FREE)
    .ignoreLayoutSafeArea([LayoutSafeAreaType.SYSTEM], [LayoutSafeAreaEdge.TOP, LayoutSafeAreaEdge.BOTTOM])
    // 根节点实测宽度 → 大屏限宽与标题偏移的唯一来源（跟随窗口缩放；PC 拖窗口同样生效）
    .onAreaChange(this.onRootArea)
    // 设置 = 半模态弹窗（沉浸材质与闸门口径同工作台各半模态）
    .bindSheet(this.settingsShown, this.settingsSheet(),
      moduleSheetOptions(SheetSize.LARGE, this.settingsGate,
        (v: boolean): void => {
          this.settingsShown = v;
        },
        // 宽屏横屏（平板/PC）改用居中形态：底部形态在宽屏铺满，没有"弹窗外"可点
        this.winW >= BP_LG && this.winW > this.winH))
  }
}
