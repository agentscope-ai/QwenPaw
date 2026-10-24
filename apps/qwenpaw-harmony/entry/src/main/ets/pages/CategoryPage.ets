/*
 * 工作台分类页（二级）—— 路由 workbench-category，展示某分类下的模块列表。
 * 对齐 PR #7378 workbench.tsx 的 CategoryDetail（分类 → 模块）。
 */

import { HdsNavDestination, ScrollEffectType, BlurStrategy, hdsMaterial } from '@kit.UIDesignKit';
import { swapRoute, popSelfOnBack, slideCoverTransition } from '../services/NavPush';
import { areaWidthOf, wideClampW } from '../theme/Breakpoints';
import { common } from '@kit.AbilityKit';
import { WorkbenchCategory, WorkbenchModule, WORKBENCH_CATEGORIES } from '../services/WorkbenchModules';
import { ThemeManager, ThemeSnapshot } from '../theme/ThemeManager';
import { UiTokens } from '../theme/UiTokens';
import { GlassCard } from '../components/GlassCard';

@Builder
export function CategoryPageBuilder(_name: string, param: Object) {
  CategoryPage({ params: param })
}

@Component
export struct CategoryPage {
  params: Object = new Object();
  @State category: WorkbenchCategory | null = null;
  @State theme: ThemeSnapshot = ThemeManager.get().snapshot();
  @StorageLink('appIsDark') isDark: boolean = false;
  private stack: NavPathStack | null = null;
  // 二级页水平覆盖转场的位移（百分比）：由 NavPush.slideCoverTransition 驱动
  @State pageX: string = '0%';

  // 大屏（平板/电脑）内容列限宽：官方《页面布局场景》缩进布局 —— 空间充足时内容列居中、两侧留白；
  // 宽度由外层满宽容器 onAreaChange 实时上报（跟随窗口缩放），实现见 theme/Breakpoints
  @State pageW: number = 0;

  private onPageArea = (_old: Area, now: Area): void => {
    this.pageW = areaWidthOf(now, this.pageW);
  };

  aboutToAppear(): void {
    const rec: Record<string, Object> = this.params as Record<string, Object>;
    const k: Object = rec['key'];
    const key: string = typeof k === 'string' ? k as string : '';
    for (const c of WORKBENCH_CATEGORIES) {
      if (c.key === key) {
        this.category = c;
        break;
      }
    }
    const st: Object = rec['stack'];
    this.stack = (st === undefined || st === null) ? null : st as NavPathStack;
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    ThemeManager.get().load(ctx).then((): void => {
      this.theme = ThemeManager.get().snapshot();
    });
  }

  private openModule(key: string): void {
    if (this.stack !== null) {
      const p: Record<string, string> = { 'key': key };
      swapRoute(this.stack, 'module', p);
    }
  }

  @Builder
  moduleRow(m: WorkbenchModule) {
    GlassCard({
      insetH: 0,
      onTap: (): void => {
        this.openModule(m.key);
      }
    }) {
      Row() {
        Image(m.icon)
          .width(22).height(22)
          .fillColor(this.isDark ? this.theme.accentDark : this.theme.accent)
          .margin({ right: 8 })
        Column() {
          Text(m.title)
            .fontSize(UiTokens.fsBody)
            .fontWeight(FontWeight.Medium)
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
          Text(m.subtitle)
            .fontSize(UiTokens.fsSecondary)
            .fontColor($r('app.color.text_tertiary'))
            .margin({ top: 2 })
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
        }
        .alignItems(HorizontalAlign.Start)
        .layoutWeight(1)
        Image($r('app.media.chevron_right'))
          .width(16).height(16)
          .fillColor($r('app.color.text_tertiary'))
          .margin({ left: 8 })
      }
      .width('100%')
    }
  }

  build() {
    HdsNavDestination() {
      Row() {
        Scroll() {
          Column() {
            if (this.category !== null) {
              Text(this.category!.subtitle)
                .fontSize(UiTokens.fsSecondary)
                .fontColor($r('app.color.text_tertiary'))
                .width('100%')
                .margin({ bottom: 6 })
              ForEach(this.category!.modules, (m: WorkbenchModule) => {
                this.moduleRow(m)
              }, (m: WorkbenchModule) => m.key)
            }
          }
          .width('100%')
          .padding({
            top: UiTokens.topInset, bottom: UiTokens.bottomInset,
            left: UiTokens.pageHMargin, right: UiTokens.pageHMargin
          })
        }
        .width(wideClampW(this.pageW))
        .height('100%')
        .scrollBar(BarState.Auto)
        // 页面底色 + 扩绘制区到状态栏/导航栏：二级页根容器不自带底色时，标题栏以下与下带会露出窗口黑底（真机实测 (0,0,0)）
        .backgroundColor($r('app.color.page_bg'))
        .expandSafeArea([SafeAreaType.SYSTEM], [SafeAreaEdge.TOP, SafeAreaEdge.BOTTOM])
      }
      .width('100%')
      .height('100%')
      .justifyContent(FlexAlign.Center)
      // 分栏下内容列限宽后两侧会留白：pane 根容器必须自己带页面底色，否则露出窗口默认白底，
      // 与左栏（页面底色）之间出现一条浅色接缝（真机像素实测：分栏边界处 255,255,255 vs 238,234,225）
      .backgroundColor($r('app.color.page_bg'))
      .onAreaChange(this.onPageArea)
    }
    // 内容也扩到安全区外（布局级）：官方 NavDestination.ignoreLayoutSafeArea，
    // 与 expandSafeArea 同时设置时它优先；前置条件要求标题栏隐藏或 STACK 模式
    .ignoreLayoutSafeArea([LayoutSafeAreaType.SYSTEM], [LayoutSafeAreaEdge.TOP, LayoutSafeAreaEdge.BOTTOM])
    // 二级页转场：整页自右水平覆盖进来（退出滑回右侧）——见 services/NavPush.slideCoverTransition。
    // 系统默认档在分栏下动的是"内容区左边缘 0 → 分栏位"，观感从左侧摊过来（判"方向反了"），
    // 故改用官方 customTransition（NavDestinationTransitionDelegate）自己定方向。
    .customTransition((op: NavigationOperation, isEnter: boolean)
      : Array<NavDestinationTransition> | undefined => slideCoverTransition(op, isEnter,
        (v: string): void => { this.pageX = v; }))
    .translate({ x: this.pageX })
    // 返回键：系统侧滑与标题栏左上角返回按钮都投递到当前 NavDestination 的 onBackPressed
    //（官方 FAQ faqs-arkui-1117：该回调"支持拦截系统侧滑及 NavDestination 标题栏的返回事件"）；
    // 没挂它时标题栏返回按钮点了没有反应 —— 这里自己出栈并消费。
    .onBackPressed((): boolean => popSelfOnBack(this.stack))
    .titleBar({
      style: {
        // 与主页同款沉浸：沉浸式渐变模糊 + 系统材质（等级 ADAPTIVE），静止态与滚动终点态都用主题色底。
        // 平台行为：深色下沉浸材质是"变暗玻璃"，会把底色压低（观感偏"透明"，属沉浸固有表现）。
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
            backgroundColor: this.isDark ? this.theme.accentDark : this.theme.accent
          }
        },
        scrollEffectStyle: {
          backgroundStyle: {
            blurRadius: 12.0,
            backgroundColor: this.isDark ? this.theme.accentDark : this.theme.accent
          }
        },
        systemMaterialEffect: {
          materialType: hdsMaterial.MaterialType.ADAPTIVE,
          materialLevel: hdsMaterial.MaterialLevel.ADAPTIVE
        }
      },
      content: {
        title: {
          mainTitle: this.category !== null ? this.category!.title : $r('app.string.tab_workbench')
        }
      },
      // 与主页一致：标题栏不避让安全区向上铺到状态栏区域，组件安全区关闭（否则状态栏带露系统底）
      avoidLayoutSafeArea: false,
      enableComponentSafeArea: false
    })
  }
}
