/*
 * 通用工作台模块页 —— 路由 /module/{key}（对齐 PR #7378 app/module/[key].tsx 入口形态）。
 * 按模块 key 分派到具体设置组件（逐个对齐 7378 features/workbench/*），
 * 尚未移植的模块先展示模块能力范围与接口端点。
 */

import { HdsNavDestination, ScrollEffectType, BlurStrategy, hdsMaterial } from '@kit.UIDesignKit';
import { BP_LG, areaWidthOf, wideClampW } from '../theme/Breakpoints';
import { common } from '@kit.AbilityKit';
import { emitter } from '@kit.BasicServicesKit';
import { CONN_CHANGE_EVENT } from '../services/AppEvents';
import { WorkbenchModule, findWorkbenchModule } from '../services/WorkbenchModules';
import { ModuleOffload } from '../components/ModuleOffload';
import { ModuleAcp } from '../components/ModuleAcp';
import { ModuleAgentConfig } from '../components/ModuleAgentConfig';
import { ModuleAutomation } from '../components/ModuleAutomation';
import { ModuleChannels } from '../components/ModuleChannels';
import { ModuleCheckpoints } from '../components/ModuleCheckpoints';
import { ModuleSnapshot } from '../components/ModuleSnapshot';
import { ModuleDebug } from '../components/ModuleDebug';
import { ModuleFiles } from '../components/ModuleFiles';
import { ModuleProjectGit } from '../components/ModuleProjectGit';
import { ModuleTools } from '../components/ModuleTools';
import { ModuleVoice } from '../components/ModuleVoice';
import { ModuleSkills } from '../components/ModuleSkills';
import { ModuleSkillPool } from '../components/ModuleSkillPool';
import { ModuleMcpAcp } from '../components/ModuleMcpAcp';
import { ModuleEnvironments } from '../components/ModuleEnvironments';
import { ModuleSecurity } from '../components/ModuleSecurity';
import { ModuleOperations } from '../components/ModuleOperations';
import { ModuleModels } from '../components/ModuleModels';
import { ModuleExtensions } from '../components/ModuleExtensions';
import { ModuleHub } from '../components/ModuleHub';
import { ThemeManager, ThemeSnapshot } from '../theme/ThemeManager';
import { UiTokens } from '../theme/UiTokens';

import { popSelfOnBack, slideCoverTransition } from '../services/NavPush';

@Builder
export function ModulePageBuilder(_name: string, param: Object) {
  ModulePage({ params: param })
}

@Component
export struct ModulePage {
  params: Object = new Object();
  @State module: WorkbenchModule | null = null;
  @State theme: ThemeSnapshot = ThemeManager.get().snapshot();
  @StorageLink('appIsDark') isDark: boolean = false;

  // 大屏（平板/电脑）内容列限宽：官方《页面布局场景》缩进布局 —— 空间充足时内容列居中、两侧留白；
  // 宽度由外层满宽容器 onAreaChange 实时上报（跟随窗口缩放），实现见 theme/Breakpoints
  @State pageW: number = 0;
  // 可见区高度：判断"横排"用（模块内某些交互按横竖屏分流，如文件页的树形呈现）
  @State pageH: number = 0;
  // 连接变化代次：内容子树 ForEach 的键。重连/切换连接后键变 → 模块组件整体重建，
  // aboutToAppear 重跑取新连接的快照（重连后右栏内容随之刷新）
  @State contentGen: number = 0;
  private connListener: (data: emitter.EventData) => void = (_data: emitter.EventData): void => {};

  private onPageArea = (_old: Area, now: Area): void => {
    this.pageW = areaWidthOf(now, this.pageW);
    const h: number = typeof now.height === 'number' ? now.height as number : 0;
    if (h > 0 && Math.abs(h - this.pageH) > 0.5) {
      this.pageH = h;
    }
  };

  // 宽屏横排（平板/电脑横屏）：与分栏、内容列限宽同一口径（宽 ≥ lg 且横排）
  private wideLandscape(): boolean {
    return this.pageW >= BP_LG && this.pageW > this.pageH;
  }

  // 导航栈（onReady 时由框架注入）：标题栏返回按钮与系统侧滑都走它出栈
  private stack: NavPathStack | null = null;
  // 二级页水平覆盖转场的位移（百分比）：由 NavPush.slideCoverTransition 驱动
  @State pageX: string = '0%';
  aboutToAppear(): void {
    const rec: Record<string, Object> = this.params as Record<string, Object>;
    const key: Object = rec['key'];
    const k: string = typeof key === 'string' ? key as string : '';
    this.module = findWorkbenchModule(k);
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    ThemeManager.get().load(ctx).then((): void => {
      this.theme = ThemeManager.get().snapshot();
    });
    // 重连/切换连接（ConnectionStore 保存/切换/删除/清空均发此事件）→ 代次 +1 重建内容
    this.connListener = (_data: emitter.EventData): void => {
      this.contentGen += 1;
    };
    emitter.on(CONN_CHANGE_EVENT, this.connListener);
  }

  aboutToDisappear(): void {
    emitter.off(CONN_CHANGE_EVENT, this.connListener);
  }

  // 模块分派子树（对齐 7378 features/workbench/*）：build 里包 ForEach([contentGen])，
  // 连接变化键变 → 子树重建，各模块组件 aboutToAppear 重跑重新取数
  @Builder
  moduleContent() {
    if (this.module!.key === 'offload') {
      ModuleOffload()
    } else if (this.module!.key === 'acp') {
      ModuleAcp()
    } else if (this.module!.key === 'agent-config') {
      ModuleAgentConfig()
    } else if (this.module!.key === 'automation') {
      ModuleAutomation()
    } else if (this.module!.key === 'channels') {
      ModuleChannels()
    } else if (this.module!.key === 'checkpoints') {
      ModuleCheckpoints()
    } else if (this.module!.key === 'debug') {
      ModuleDebug()
    } else if (this.module!.key === 'files') {
      ModuleFiles({ wide: this.wideLandscape() })
    } else if (this.module!.key === 'projects-git') {
      ModuleProjectGit()
    } else if (this.module!.key === 'tools') {
      ModuleTools()
    } else if (this.module!.key === 'voice') {
      ModuleVoice()
    } else if (this.module!.key === 'skills') {
      ModuleSkills()
    } else if (this.module!.key === 'skill-pool') {
      ModuleSkillPool()
    } else if (this.module!.key === 'mcp-acp') {
      ModuleMcpAcp()
    } else if (this.module!.key === 'environments') {
      ModuleEnvironments()
    } else if (this.module!.key === 'security') {
      ModuleSecurity()
    } else if (this.module!.key === 'operations') {
      ModuleOperations()
    } else if (this.module!.key === 'models') {
      ModuleModels()
    } else if (this.module!.key === 'extensions') {
      ModuleExtensions()
    } else if (this.module!.key === 'hub') {
      ModuleHub()
    } else {
      // 尚未逐个移植设置项的模块：直接用该模块端点取真实数据（对齐 7378 SnapshotSettings）。
      // sessions 亦走此处：7378 该模块本身就是 /chats?archived=false 的通用视图。
      ModuleSnapshot({
        endpoint: this.module!.endpoint,
        icon: this.module!.icon
      })
    }
  }

  build() {
    HdsNavDestination() {
      Row() {
        Scroll() {
          Column() {
            if (this.module !== null) {
              Row() {
                Image(this.module!.icon)
                  .width(26).height(26)
                  .fillColor(this.isDark ? this.theme.accentDark : this.theme.accent)
                  .margin({ right: 8 })
                Column() {
                  Text(this.module!.title)
                    .fontSize(20)
                    .fontWeight(FontWeight.Bold)
                  Text(this.module!.subtitle)
                    .fontSize(UiTokens.fsSecondary)
                    .fontColor($r('app.color.text_tertiary'))
                    .margin({ top: 2 })
                }
                .alignItems(HorizontalAlign.Start)
                .layoutWeight(1)
              }
              .width('100%')
              .margin({ top: 16, bottom: 14 })

              // 模块内容子树：连接变化时 contentGen 键变 → 整棵子树重建、各模块重取数据
              ForEach([this.contentGen], (_g: number) => {
                this.moduleContent()
              }, (g: number) => g.toString())
            }
          }
          .width('100%')
          .padding({
            top: UiTokens.topInset, bottom: 32,
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
    // 本页未从入栈参数带 NavPathStack：按官方口径在 onReady 取导航栈（NavDestinationContext.pathStack）
    .onReady((ctx: NavDestinationContext): void => {
      this.stack = ctx.pathStack;
    })
    // 返回键：系统侧滑与标题栏左上角返回按钮都投递到当前 NavDestination 的 onBackPressed
    //（官方 FAQ faqs-arkui-1117：该回调"支持拦截系统侧滑及 NavDestination 标题栏的返回事件"）；
    // 没挂它时标题栏返回按钮点了没有反应 —— 这里自己出栈并消费。
    .onBackPressed((): boolean => popSelfOnBack(this.stack))
    .titleBar({
      // 二级页各自配标题栏（含返回图标区）：静止态即磨砂 + 系统转场动画。
      // 不开 systemMaterialEffect：官方《组件适配沉浸光感》称返回键在标题栏材质生效范围内，
      // 但该组合在 NavDestination 详情页会把整页渲染成纯黑（真机像素复核），故维持磨砂 + 静止态不滚动。
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
          mainTitle: this.module !== null ? this.module!.title : $r('app.string.tab_workbench')
        }
      },
      // 与主页一致：标题栏不避让安全区向上铺到状态栏区域，组件安全区关闭（否则状态栏带露系统底）
      avoidLayoutSafeArea: false,
      enableComponentSafeArea: false
    })
  }

}
