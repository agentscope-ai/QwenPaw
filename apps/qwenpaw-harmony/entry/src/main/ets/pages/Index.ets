/*
 * QwenPaw HarmonyOS · 主界面
 * 底部 tab 对齐 PR #7378 移动端：会话 / 智能体 / 社区 / 工作台。
 * tab 图标 = PR 同款 lucide SVG（message-circle / bot / users-round / layout-grid），
 *   选中 = app 主题色（accent/accentDark），未选中 = PR faint 灰（tab_faint，深浅色自适应）。
 * 标题栏 = HdsNavigation FREE 模式（静止大标题，上滚缩小至 MINI 不消失）
 *   + IMMERSIVE_GRADIENT_BLUR 沉浸式渐变模糊 + ADAPTIVE 系统材质（沉浸光感）。
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
import { uiMaterial, display, LengthMetrics } from '@kit.ArkUI';
import { emitter } from '@kit.BasicServicesKit';
import { common, Configuration, ConfigurationConstant } from '@kit.AbilityKit';
import { ThemeManager, ThemeSnapshot, ThemeListener } from '../theme/ThemeManager';
import { syncConsoleThemeToManager } from '../services/ConsoleTheme';
import { UiTokens } from '../theme/UiTokens';
import { AGENT_CREATE_EVENT } from '../services/AgentsService';
import { ConnectPanel } from '../components/ConnectPanel';
import { AgentsTab } from '../components/AgentsTab';
import { CommunityTab } from '../components/CommunityTab';
import { WorkbenchTab } from '../components/WorkbenchTab';

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

// 搜索胶囊高度（vp）
const SEARCH_PILL_H: number = 44;
// 标题栏起始端内间距（vp）：官方 PaddingOptions.start 默认值（页面宽 < 600vp 时 16vp，实测吻合）。
// 标题切换动画 = 先把该值归 0（无动画）再动画回 16 → 新标题从左侧滑入（HDS 主标题是纯字符串、无文字过渡 API）
const TITLE_PAD_START: number = 16;

@Entry
@Component
struct Index {
  private stack: NavPathStack = new NavPathStack();
  private controller: HdsTabsController = new HdsTabsController();
  private scrollerChats: Scroller = new Scroller();
  private scrollerAgents: Scroller = new Scroller();
  private scrollerCommunity: Scroller = new Scroller();
  private scrollerWorkbench: Scroller = new Scroller();
  private customMaterialLevel: hdsMaterial.MaterialLevel = hdsMaterial.MaterialLevel.EXQUISITE;
  @State currentIndex: number = 0;
  @State isDark: boolean = false;
  @State theme: ThemeSnapshot = ThemeManager.get().snapshot();
  // —— 智能体页标题栏联动状态 ——
  @State titleP: number = 0;                 // 头部滚动进度 0→1（AgentsTab.onDidScroll 上报，用于收起键盘等）
  @State agentsName: string = '';             // 当前智能体名（接管时作为标题显示）
  @State searchQuery: string = '';            // 标题栏搜索输入（@Prop 单向同步给 AgentsTab 过滤）
  // 标题接管态：智能体页首行卡碰到搜索框时翻转 → mainTitle 变为「智能体：名字」（带过渡动画）
  @State nameTitle: boolean = false;
  // 标题栏起始内间距：标题切换时 0→16vp 动画 = 新标题从左侧滑入
  @State titlePadStart: number = TITLE_PAD_START;
  // 屏宽（vp）懒算一次：标题栏恒等屏宽 → 搜索条全宽确定性推导，不实测 onAreaChange
  private screenW: number = 0;
  // 搜索条沉浸光感材质：手指跟随光 = 主题色（深浅各取其一）；仅主题/深浅变化时重建（避免滚动帧帧重建）
  private searchMaterial: uiMaterial.ImmersiveMaterial = new uiMaterial.ImmersiveMaterial({
    style: uiMaterial.ImmersiveStyle.REGULAR,
    interactive: true,
    lightEffect: { color: ThemeManager.get().snapshot().fingerGlow }
  });
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
          icon: $r('sys.symbol.plus'),
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
        action: () => {
          const param: Record<string, Object> = { 'stack': this.stack };
          this.stack.pushPath({ name: 'settings', param: param });
        }
      }
    });
    return { value: items };
  }

  aboutToAppear(): void {
    // 材质等级必须用 ADAPTIVE：hdsMaterial 官方推荐自适应等级（等效 uiMaterial 的设备自适应）；
    // 实测传 EXQUISITE 会被忽略 —— 标题栏 systemMaterialEffect 不生效，进而 originalStyle 的
    // 静止态背景色（API 26 起支持自定义）也被拒绝，表现为"进页面顶部透明、动一下才出磨砂"。
    // 设备不支持 IMMERSIVE 沉浸材质时降级 SMOOTH。
    let materialTypes: Array<hdsMaterial.MaterialType> = hdsMaterial.getSystemMaterialTypes();
    this.customMaterialLevel = materialTypes.indexOf(hdsMaterial.MaterialType.IMMERSIVE) >= 0
      ? hdsMaterial.MaterialLevel.ADAPTIVE
      : hdsMaterial.MaterialLevel.SMOOTH;
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
    this.rebuildTitleBarOpts();
  }

  aboutToDisappear(): void {
    if (this.themeListener !== null) {
      ThemeManager.get().unsubscribe(this.themeListener);
      this.themeListener = null;
    }
  }

  onConfigurationUpdate(newConfig: Configuration): void {
    this.isDark = newConfig.colorMode === ConfigurationConstant.ColorMode.COLOR_MODE_DARK;
    this.rebuildSearchMaterial();
  }

  // 主题色（深浅各取其一）：标题栏磨砂底色、搜索条手指光等的统一取色口径
  private accentColor(): ResourceColor {
    return this.isDark ? this.theme.accentDark : this.theme.accent;
  }

  // 主题快照应用 + 重建搜索条沉浸材质（手指光取主题色）+ 重建标题栏选项（磨砂底色取主题色）
  private applyTheme(snap: ThemeSnapshot): void {
    this.theme = snap;
    this.rebuildSearchMaterial();
    this.rebuildTitleBarOpts();
  }

  private rebuildSearchMaterial(): void {
    this.searchMaterial = new uiMaterial.ImmersiveMaterial({
      style: uiMaterial.ImmersiveStyle.REGULAR,
      interactive: true,
      lightEffect: { color: this.isDark ? this.theme.fingerGlowDark : this.theme.fingerGlow }
    });
  }

  // 对齐 PR #7378：选中 = app 主题色（浅 accent / 深 accentDark），未选中 = faint 灰。
  private tabColor(index: number): ResourceColor {
    if (this.currentIndex === index) {
      return this.isDark ? this.theme.accentDark : this.theme.accent;
    }
    return $r('app.color.tab_faint');
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
  // 智能体页追加 bottomBuilder 搜索条（其余 tab 无，标题栏高度不增）
  private titleBarContent(): TitleBarContentOptions {
    const showName: boolean = this.currentIndex === 1 && this.nameTitle && this.agentsName.length > 0;
    const mainTitle: ResourceStr = showName
      ? `${this.resText(TAB_LABELS[1])}：${this.agentsName}`
      : TAB_LABELS[this.currentIndex];
    const content: TitleBarContentOptions = {
      title: {
        mainTitle: mainTitle
      },
      menu: this.menuOptions()
    };
    if (this.currentIndex === 1) {
      content.bottomBuilder = {
        builder: (): void => this.titleSearchArea(),
        height: UiTokens.titleSearchStripH
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
      // 起始内间距（接管/切换时 0→16vp 动画 = 标题从左侧滑入）；end 用官方默认 16vp
      padding: {
        start: LengthMetrics.vp(this.titlePadStart)
      },
      content: this.titleBarContent(),
      style: {
        // 沉浸式渐变模糊：静止透明沉浸，上滚后柔和渐变模糊
        // blurStrategy 显式 ADAPTIVE（官方「HdsNavigation+HdsTabs 滚动模糊」示例同款）
        // 沉浸光感（选定方案 A）：沉浸式渐变模糊，标题栏与底部 TabBar 同处沉浸模式。
        // 平台行为：深色下沉浸材质是"变暗玻璃"，会把标题栏底色压低 → 静止态与页面底色接近
        //（观感偏"透明"，这是沉浸模式的固有表现，非未生效）。
        // 底色仍显式给主题色，滚动渐变终点态与静止态保持一致。
        scrollEffectOpts: {
          enableScrollEffect: true,
          scrollEffectType: ScrollEffectType.IMMERSIVE_GRADIENT_BLUR
        },
        blurStrategy: BlurStrategy.ADAPTIVE,
        originalStyle: {
          backgroundStyle: {
            blurRadius: 12.0,
            backgroundColor: this.accentColor()
          }
        },
        scrollEffectStyle: {
          backgroundStyle: {
            blurRadius: 12.0,
            backgroundColor: this.accentColor(),
            maskExtraHeight: this.currentIndex === 1 ? UiTokens.titleSearchStripH : 0
          }
        },
        systemMaterialEffect: {
          materialType: hdsMaterial.MaterialType.ADAPTIVE,
          materialLevel: this.customMaterialLevel
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

  // 搜索条内容宽（vp）：标题栏恒等屏宽 → 屏宽确定性推导（懒算缓存），
  // 取代 onAreaChange 实测（Area 尺寸 px/vp 语义跨版本分歧 → 量错即"又短"/飞出屏）
  private stripFullW(): number {
    if (this.screenW <= 0) {
      this.screenW = this.getUIContext().px2vp(display.getDefaultDisplaySync().width);
    }
    return Math.max(200, this.screenW - 8);   // 8 = 搜索条左右 padding 4+4
  }

  // 标题栏搜索条（bottomBuilder，位于标题栏材质作用域内 → 沉浸光感生效）：
  // 常驻全宽搜索框（不再跟随滚动变形/收起，也不再有折叠态放大镜入口）——
  // 上滑时随标题一起上移，停在标题（MINI）下方
  @Builder
  titleSearchArea() {
    Row() {
      Row() {
        TextInput({ placeholder: $r('app.string.agents_search_placeholder'), text: $$this.searchQuery })
          .id('agents_search_input')
          .fontSize(14)
          .placeholderFont({ size: 14 })
          .caretColor(this.isDark ? this.theme.accentDark : this.theme.accent)
          .backgroundColor(Color.Transparent)
          .layoutWeight(1)
          .margin({ left: 14 })
          .onChange((v: string): void => {
            this.searchQuery = v;
          })
        if (this.searchQuery.length > 0) {
          SymbolGlyph($r('sys.symbol.xmark_circle_fill'))
            .fontSize(16)
            .fontColor([$r('app.color.text_tertiary')])
            .margin({ left: 8 })
            .onClick((): void => {
              this.searchQuery = '';
            })
        }
        SymbolGlyph($r('sys.symbol.magnifyingglass'))
          .fontSize(18)
          .fontColor([$r('app.color.text_secondary')])
      }
      .height(SEARCH_PILL_H)
      .width(this.stripFullW())
      .borderRadius(SEARCH_PILL_H / 2)
      .alignItems(VerticalAlign.Center)
      .padding({ right: 12 })
      .systemMaterial(this.searchMaterial)
    }
    .width('100%')
    .height(UiTokens.titleSearchStripH)
    .padding({ left: 4, right: 4 })
    .justifyContent(FlexAlign.End)
    .alignItems(VerticalAlign.Center)
    // clip 兜底：胶囊宽度确定性推导，恒不超搜索条；即便推导有偏也不溢出标题栏（防飞出屏）
    .clip(true)
  }

  build() {
    HdsNavigation(this.stack) {
      HdsTabs({ controller: this.controller }) {
        TabContent() {
          Scroll(this.scrollerChats) {
            Column() {
              ConnectPanel({ navStack: this.stack })
            }
            .width('100%')
            .constraintSize({ minHeight: '100%' })
            .padding({ top: UiTokens.topInset, bottom: UiTokens.bottomInset })
            .backgroundColor($r('app.color.page_bg'))
          }
          .clipContent(ContentClipMode.SAFE_AREA)
          .height('100%')
        }
        .tabBar(this.tabItem(0))

        TabContent() {
          // 智能体页自持 List（内滚 + 下拉刷新）：
          // 标题栏搜索条 / 标题接管经 query + onHeaderState 联动
          AgentsTab({
            scroller: this.scrollerAgents,
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
        .tabBar(this.tabItem(1))

        TabContent() {
          Scroll(this.scrollerCommunity) {
            Column() {
              CommunityTab()
            }
            .width('100%')
            .constraintSize({ minHeight: '100%' })
            .padding({ top: UiTokens.topInset, bottom: UiTokens.bottomInset })
            .backgroundColor($r('app.color.page_bg'))
          }
          .clipContent(ContentClipMode.SAFE_AREA)
          .height('100%')
        }
        .tabBar(this.tabItem(2))

        TabContent() {
          Scroll(this.scrollerWorkbench) {
            WorkbenchTab({ navStack: this.stack })
          }
          .clipContent(ContentClipMode.SAFE_AREA)
          .height('100%')
        }
        .tabBar(this.tabItem(3))
      }
      .barOverlap(true)
      .vertical(false)
      .barPosition(BarPosition.End)
      .onChange((index: number) => {
        this.currentIndex = index;
        if (index === 1) {
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
      })
      .barFloatingStyle({
        barBottomMargin: 28,
        // 手指跟随光 = 主题色（比 accent 浅一档的 tint，深浅模式各取其一）
        lightColor: this.isDark ? this.theme.fingerGlowDark : this.theme.fingerGlow,
        systemMaterialEffect: {
          materialType: hdsMaterial.MaterialType.ADAPTIVE,
          materialLevel: this.customMaterialLevel
        }
      })
    }
    .mode(NavigationMode.Stack)
    // 选项走备忘录（同对象引用）：滚动帧 build() 重跑不重设 → 滚动效果（渐变模糊/沉浸光感）不被逐帧重置
    .titleBar(this.titleBarOpts)
    // 标题栏 FREE 滚动效果：上滚时大标题缩小至 MINI（各 tab 统一）；
    // 智能体页内容（当前卡等）随列表上滑滚到标题栏/搜索条之下 → 沉浸 + 渐变模糊生效
    // 只绑当前 tab 的 Scroller（官方 FAQ faqs-arkui-1095 场景二：绑多个会让滚动模糊效果丢失）
    .bindToScrollable([this.currentScroller()])
    .hideBackButton(true)
    .titleMode(HdsNavigationTitleMode.FREE)
    .ignoreLayoutSafeArea([LayoutSafeAreaType.SYSTEM], [LayoutSafeAreaEdge.TOP, LayoutSafeAreaEdge.BOTTOM])
  }
}
