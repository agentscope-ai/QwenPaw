/*
 * 工作台分类页（二级）—— 路由 workbench-category，展示某分类下的模块列表。
 * 对齐 PR #7378 workbench.tsx 的 CategoryDetail（分类 → 模块）。
 */

import { HdsNavDestination, ScrollEffectType, BlurStrategy, hdsMaterial } from '@kit.UIDesignKit';
import { common, ConfigurationConstant } from '@kit.AbilityKit';
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
  @State isDark: boolean = false;
  private stack: NavPathStack | null = null;

  aboutToAppear(): void {
    const rec: Record<string, Object> = this.params as Record<string, Object>;
    const t: Object = rec['title'];
    const title: string = typeof t === 'string' ? t as string : '';
    for (const c of WORKBENCH_CATEGORIES) {
      if (c.title === title) {
        this.category = c;
        break;
      }
    }
    const st: Object = rec['stack'];
    this.stack = (st === undefined || st === null) ? null : st as NavPathStack;
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    this.isDark = ctx.config.colorMode === ConfigurationConstant.ColorMode.COLOR_MODE_DARK;
    ThemeManager.get().load(ctx).then((): void => {
      this.theme = ThemeManager.get().snapshot();
      this.isDark = (ctx.config.colorMode === ConfigurationConstant.ColorMode.COLOR_MODE_DARK);
    });
  }

  private openModule(key: string): void {
    if (this.stack !== null) {
      const p: Record<string, string> = { 'key': key };
      this.stack.pushPath({ name: 'module', param: p });
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
        SymbolGlyph(m.icon)
          .fontSize(22)
          .fontColor([this.isDark ? this.theme.accentDark : this.theme.accent])
          .width(40)
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
        Text('›')
          .fontSize(20)
          .fontColor($r('app.color.text_tertiary'))
          .margin({ left: 8 })
      }
      .width('100%')
    }
  }

  build() {
    HdsNavDestination() {
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
      .height('100%')
      .scrollBar(BarState.Auto)
      // 页面底色 + 扩绘制区到状态栏/导航栏：二级页根容器不自带底色时，标题栏以下与下带会露出窗口黑底（真机实测 (0,0,0)）
      .backgroundColor($r('app.color.page_bg'))
      .expandSafeArea([SafeAreaType.SYSTEM], [SafeAreaEdge.TOP, SafeAreaEdge.BOTTOM])
    }
    // 内容也扩到安全区外（布局级）：官方 NavDestination.ignoreLayoutSafeArea，
    // 与 expandSafeArea 同时设置时它优先；前置条件要求标题栏隐藏或 STACK 模式
    .ignoreLayoutSafeArea([LayoutSafeAreaType.SYSTEM], [LayoutSafeAreaEdge.TOP, LayoutSafeAreaEdge.BOTTOM])
    .titleBar({
      style: {
        // 与主页同款沉浸：沉浸式渐变模糊 + 系统材质（等级 ADAPTIVE），静止态与滚动终点态都用主题色底。
        // 平台行为：深色下沉浸材质是"变暗玻璃"，会把底色压低（观感偏"透明"，属沉浸固有表现）。
        scrollEffectOpts: {
          enableScrollEffect: true,
          scrollEffectType: ScrollEffectType.IMMERSIVE_GRADIENT_BLUR
        },
        blurStrategy: BlurStrategy.ADAPTIVE,
        originalStyle: {
          backgroundStyle: {
            blurRadius: 12.0,
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
