/*
 * 智能体详情 —— 分栏右栏展示（对齐工作台 / 社区的二级页形态）。
 *
 * 为什么单独做一页：智能体页点一下智能体在 7378 里是"切换当前智能体"（`switchAgent` → `selectAgent`：
 * 换 agentId + 持久化 + 重载该智能体的会话数据），没有详情页；但平板分栏下右栏空着不好看，这里把
 * 该智能体的可读信息（名称 / id / 说明 / 状态 / 模型 / 后端 / 是否当前）放在右栏，切换动作仍在页内
 * 提供，逻辑与列表行一致（同一 selectAgent 出口，成功后广播 AGENT_CHANGE_EVENT）。
 */

import { HdsNavDestination, ScrollEffectType, BlurStrategy, hdsMaterial } from '@kit.UIDesignKit';
import { common } from '@kit.AbilityKit';
import { wideClampW } from '../theme/Breakpoints';
import { ThemeManager, ThemeSnapshot, ThemeListener } from '../theme/ThemeManager';
import { UiTokens } from '../theme/UiTokens';
import { AgentInfo, fetchAgents, selectAgent } from '../services/AgentsService';
import { loadConnection, QpConnection } from '../services/ConnectionStore';
import { popSelfOnBack, slideCoverTransition } from '../services/NavPush';
import { t, tf } from '../services/I18n';

@Builder
export function AgentDetailPageBuilder(_name: string, param: Object) {
  AgentDetailPage({ params: param })
}

@Component
export struct AgentDetailPage {
  params: Object = new Object();
  @State agent: AgentInfo | null = null;
  @State conn: QpConnection | null = null;
  @State loading: boolean = true;
  @State error: string = '';
  @State switching: boolean = false;
  @StorageLink('appIsDark') isDark: boolean = false;
  @State theme: ThemeSnapshot = ThemeManager.get().snapshot();
  // 二级页水平覆盖转场的位移（百分比）：由 NavPush.slideCoverTransition 驱动
  @State pageX: string = '0%';
  // 导航栈（onReady 时由框架注入）：标题栏返回按钮与系统侧滑都走它出栈
  private stack: NavPathStack | null = null;
  private agentId: string = '';
  private pageW: number = 0;
  private themeListener: ThemeListener | null = null;

  aboutToAppear(): void {
    const rec: Record<string, Object> = this.params as Record<string, Object>;
    const id: Object = rec['agentId'];
    this.agentId = typeof id === 'string' ? id as string : '';
    this.themeListener = (snap: ThemeSnapshot): void => {
      this.theme = snap;
    };
    ThemeManager.get().subscribe(this.themeListener);
    this.load();
  }

  aboutToDisappear(): void {
    if (this.themeListener !== null) {
      ThemeManager.get().unsubscribe(this.themeListener);
      this.themeListener = null;
    }
  }

  private async load(): Promise<void> {
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    this.loading = true;
    this.error = '';
    try {
      const conn: QpConnection | null = await loadConnection(ctx);
      if (conn === null) {
        this.error = tf($r('app.string.chat_no_conn'));
        return;
      }
      this.conn = conn;
      const all: AgentInfo[] = await fetchAgents(conn.baseUrl, conn.token, conn.agentId);
      this.agent = all.find((a: AgentInfo): boolean => a.id === this.agentId) ?? null;
      if (this.agent === null) {
        this.error = tf($r('app.string.agent_detail_missing'));
      }
    } catch (e) {
      this.error = e instanceof Error ? e.message : tf($r('app.string.agent_detail_load_failed'));
    } finally {
      this.loading = false;
    }
  }

  // 切换为当前智能体：与列表行同一出口（selectAgent 持久化 + 广播），成功后刷新本页"当前"态
  private async makeCurrent(): Promise<void> {
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    const conn: QpConnection | null = this.conn;
    if (conn === null || this.switching || this.agentId === conn.agentId) {
      return;
    }
    this.switching = true;
    try {
      const next: QpConnection = await selectAgent(ctx, conn, this.agentId);
      this.conn = next;
    } catch (e) {
      this.error = e instanceof Error ? e.message : tf($r('app.string.agent_detail_switch_failed'));
    } finally {
      this.switching = false;
    }
  }

  private isCurrent(): boolean {
    return this.conn !== null && this.conn.agentId === this.agentId;
  }

  private accent(): ResourceColor {
    return this.isDark ? this.theme.accentDark : this.theme.accent;
  }

  @Builder
  infoRow(label: Resource, value: string) {
    Row() {
      Text(t(label))
        .fontSize(UiTokens.fsSecondary)
        .fontColor($r('app.color.text_secondary'))
      Text(value.length > 0 ? value : '—')
        .fontSize(UiTokens.fsBody)
        .fontColor($r('app.color.text_primary_strong'))
        .layoutWeight(1)
        .textAlign(TextAlign.End)
        .maxLines(2)
        .textOverflow({ overflow: TextOverflow.Ellipsis })
    }
    .width('100%')
    .padding(UiTokens.cardPad)
    .backgroundColor($r('app.color.card_bg'))
    .borderRadius(UiTokens.cardRadius)
    .margin({ bottom: 8 })
  }

  build() {
    HdsNavDestination() {
      Scroll() {
        Column({ space: 8 }) {
          if (this.loading) {
            LoadingProgress()
              .width(40)
              .height(40)
              .color(this.accent())
              .margin({ top: 60 })
          } else if (this.agent !== null) {
            // 头像 + 名称 + 当前态
            Column({ space: 10 }) {
              Text(this.agent!.name.length > 0 ? this.agent!.name.charAt(0).toUpperCase() : 'A')
                .fontSize(30)
                .fontColor($r('app.color.text_primary_strong'))
                .width(72)
                .height(72)
                .textAlign(TextAlign.Center)
                .borderRadius(36)
                .backgroundColor($r('app.color.card_bg'))
              Text(this.agent!.name)
                .fontSize(UiTokens.fsTitle)
                .fontWeight(FontWeight.Bold)
                .fontColor($r('app.color.text_primary_strong'))
              if (this.isCurrent()) {
                Text($r('app.string.agents_current'))
                  .fontSize(UiTokens.fsChip)
                  .fontColor(this.accent())
                  .backgroundColor($r('app.color.card_bg'))
                  .borderRadius(9)
                  .padding({ left: 8, right: 8, top: 2, bottom: 2 })
              }
            }
            .width('100%')
            .padding({ top: 14, bottom: 14 })

            this.infoRow($r('app.string.agent_detail_id'), this.agent!.id)
            this.infoRow($r('app.string.agent_detail_desc'), this.agent!.description)
            this.infoRow($r('app.string.agent_detail_status'),
              this.agent!.enabled ? this.agent!.startupStatus : t($r('app.string.agent_detail_disabled')))
            this.infoRow($r('app.string.agent_detail_model'), this.agent!.activeModel)
            this.infoRow($r('app.string.agent_detail_backend'), this.agent!.backend)
            this.infoRow($r('app.string.agent_detail_workspace'),
              this.conn !== null ? this.conn.baseUrl : '')

            if (!this.isCurrent()) {
              Button(this.switching ? t($r('app.string.agent_detail_switching'))
                : t($r('app.string.agent_detail_make_current')))
                .width('100%')
                .height(48)
                .margin({ top: 8 })
                .backgroundColor($r('app.color.card_glass'))
                .fontColor(this.accent())
                .enabled(!this.switching)
                .onClick((): void => {
                  this.makeCurrent();
                })
            }
          } else {
            Text(this.error.length > 0 ? this.error : t($r('app.string.agent_detail_missing')))
              .fontSize(UiTokens.fsBody)
              .fontColor($r('app.color.text_secondary'))
              .margin({ top: 60 })
          }
        }
        .width(wideClampW(this.pageW))
        .padding({
          top: UiTokens.topInset + 8, bottom: 32,
          left: UiTokens.pageHMargin, right: UiTokens.pageHMargin
        })
      }
      .width('100%')
      .height('100%')
      .align(Alignment.Top)
      .scrollBar(BarState.Auto)
      .backgroundColor($r('app.color.page_bg'))
      .expandSafeArea([SafeAreaType.SYSTEM], [SafeAreaEdge.TOP, SafeAreaEdge.BOTTOM])
    }
    // 内容扩到安全区外（布局级）：二级页四边都扩，否则底部/左右两侧会露出窗口底色
    .ignoreLayoutSafeArea([LayoutSafeAreaType.SYSTEM],
      [LayoutSafeAreaEdge.TOP, LayoutSafeAreaEdge.BOTTOM, LayoutSafeAreaEdge.START, LayoutSafeAreaEdge.END])
    // 二级页转场：整页自右水平覆盖进来（退出滑回右侧）——见 services/NavPush.slideCoverTransition
    .customTransition((op: NavigationOperation, isEnter: boolean)
      : Array<NavDestinationTransition> | undefined => slideCoverTransition(op, isEnter,
        (v: string): void => { this.pageX = v; }))
    .translate({ x: this.pageX })
    .onReady((ctx: NavDestinationContext): void => {
      this.stack = ctx.pathStack;
    })
    .onBackPressed((): boolean => popSelfOnBack(this.stack))
    .onAreaChange((_o: Area, n: Area): void => {
      this.pageW = Number(n.width);
    })
    .titleBar({
      style: {
        scrollEffectOpts: {
          enableScrollEffect: false,
          scrollEffectType: ScrollEffectType.GRADIENT_BLUR
        },
        blurStrategy: BlurStrategy.ENABLE,
        originalStyle: {
          backgroundStyle: { blurRadius: 12.0, maskExtraHeight: 0.0, backgroundColor: this.accent() }
        },
        scrollEffectStyle: {
          backgroundStyle: { blurRadius: 12.0, backgroundColor: this.accent() }
        },
        systemMaterialEffect: {
          materialType: hdsMaterial.MaterialType.ADAPTIVE,
          materialLevel: hdsMaterial.MaterialLevel.ADAPTIVE
        }
      },
      content: {
        title: {
          mainTitle: this.agent !== null ? this.agent!.name : $r('app.string.agent_detail_title')
        }
      },
      avoidLayoutSafeArea: false,
      enableComponentSafeArea: false
    })
  }
}
