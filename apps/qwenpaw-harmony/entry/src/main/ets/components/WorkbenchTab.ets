/*
 * 工作台 tab —— 移植 PR #7378 apps/qwenpaw-mobile/app/(tabs)/workbench.tsx：
 *   连接状态 + 搜索 + 快捷操作 + 4 分类（点开 → 模块列表）+ 模块 → 通用模块页（/module/{key}）。
 * 审批：GET /api/console/push-messages 真数据；有待审批且数量变化时发系统通知（一期能力保留）。
 */

import { common, ConfigurationConstant } from '@kit.AbilityKit';
import { preferences } from '@kit.ArkData';
import { emitter } from '@kit.BasicServicesKit';
import { loadConnection, QpConnection } from '../services/ConnectionStore';
import { hostOf } from '../services/PairingModel';
import { fetchApprovals, ApprovalInfo } from '../services/ApprovalsService';
import { AGENT_CHANGE_EVENT } from '../services/AgentsService';
import { publishNotice, requestNotificationPermission } from '../services/NotifyService';
import {
  WorkbenchCategory, WorkbenchModule, WORKBENCH_CATEGORIES, WORKBENCH_MODULES
} from '../services/WorkbenchModules';
import { UiTokens } from '../theme/UiTokens';
import { ThemeManager, ThemeSnapshot } from '../theme/ThemeManager';
import { PRESS_SCALE, PressLatch, pressEffect, pressTouch } from '../theme/PressFx';
import { GlassCard } from './GlassCard';

export const CONN_CHANGE_EVENT: string = 'qp_conn_change';

@Component
export struct WorkbenchTab {
  navStack: NavPathStack = new NavPathStack();
  @State connHost: string = '';
  @State connected: boolean = false;
  @State approvals: ApprovalInfo[] = [];
  @State query: string = '';
  @State theme: ThemeSnapshot = ThemeManager.get().snapshot();
  @State isDark: boolean = false;

  private accentColor(): ResourceColor {
    return this.isDark ? this.theme.accentDark : this.theme.accent;
  }

  // 快捷操作卡片按压反馈（内容区材质不生效 → 自绘：缩放 + 点光源）
  @State qaPressed: number = -1;
  private qaLatch: PressLatch = new PressLatch();

  private onQaTouch(idx: number, e: TouchEvent): void {
    pressTouch(this.getUIContext(), e, this.qaLatch, (v: boolean): void => {
      this.qaPressed = v ? idx : -1;
    });
  }

  private static readonly PREF_NAME: string = 'notify';
  private static readonly KEY_LAST_COUNT: string = 'lastApprovalCount';
  private connListener: (data: emitter.EventData) => void = (_data: emitter.EventData): void => {};
  private agentListener: (data: emitter.EventData) => void = (_data: emitter.EventData): void => {};

  aboutToAppear(): void {
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    this.loadConn(ctx);
    this.isDark = ctx.config.colorMode === ConfigurationConstant.ColorMode.COLOR_MODE_DARK;
    ThemeManager.get().load(ctx).then((): void => {
      this.theme = ThemeManager.get().snapshot();
      this.isDark = (ctx.config.colorMode === ConfigurationConstant.ColorMode.COLOR_MODE_DARK);
    });
    this.connListener = (_data: emitter.EventData): void => {
      this.loadConn(ctx);
    };
    // 智能体切换后审批按新 agent 重载（X-Agent-Id）
    this.agentListener = (_data: emitter.EventData): void => {
      this.loadConn(ctx);
    };
    emitter.on(CONN_CHANGE_EVENT, this.connListener);
    emitter.on(AGENT_CHANGE_EVENT, this.agentListener);
  }

  aboutToDisappear(): void {
    emitter.off(CONN_CHANGE_EVENT, this.connListener);
    emitter.off(AGENT_CHANGE_EVENT, this.agentListener);
  }

  private loadConn(ctx: common.UIAbilityContext): void {
    loadConnection(ctx).then((conn: QpConnection | null) => {
      if (conn !== null) {
        this.connected = true;
        this.connHost = hostOf(conn.baseUrl);
        this.refreshApprovals(conn, ctx);
      } else {
        this.connected = false;
        this.connHost = '';
        this.approvals = [];
      }
    });
  }

  private async refreshApprovals(conn: QpConnection, ctx: common.UIAbilityContext): Promise<void> {
    try {
      const list: ApprovalInfo[] = await fetchApprovals(conn.baseUrl, conn.token, conn.agentId);
      this.approvals = list;
      await this.notifyIfNew(ctx, list.length);
    } catch (e) {
      // 审批读取失败不打断页面
    }
  }

  // 数量较上次已通知时增长 → 发系统通知（避免每次进入页面重复打扰）
  private async notifyIfNew(ctx: common.UIAbilityContext, count: number): Promise<void> {
    if (count <= 0) {
      return;
    }
    try {
      const pref: preferences.Preferences = await preferences.getPreferences(ctx,
        WorkbenchTab.PREF_NAME);
      const last: number = (await pref.get(WorkbenchTab.KEY_LAST_COUNT, -1)) as number;
      if (last === count) {
        return;
      }
      await pref.put(WorkbenchTab.KEY_LAST_COUNT, count);
      await pref.flush();
      const ok: boolean = await requestNotificationPermission(ctx);
      if (ok) {
        await publishNotice(ctx, this.t($r('app.string.notify_approval_title')),
          this.t($r('app.string.notify_approval_body')).replace('%d', count.toString()));
      }
    } catch (e) {
      // 通知失败不影响页面
    }
  }

  private t(res: Resource): string {
    try {
      const host: common.Context = this.getUIContext().getHostContext() as common.Context;
      return host.resourceManager.getStringSync(res.id);
    } catch (e) {
      return '';
    }
  }

  private openModule(key: string): void {
    const param: Record<string, string> = { 'key': key };
    this.navStack.pushPath({ name: 'module', param: param });
  }

  private searchResults(): WorkbenchModule[] {
    const q: string = this.query.trim().toLowerCase();
    if (q.length === 0) {
      return [];
    }
    return WORKBENCH_MODULES.filter((m: WorkbenchModule): boolean =>
      `${m.title} ${m.subtitle} ${m.keywords.join(' ')} ${m.scope.join(' ')}`.toLowerCase().includes(q));
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
          .fontColor([this.accentColor()])
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

  @Builder
  quickAction(icon: Resource, label: string, key: string, idx: number) {
    Column() {
      SymbolGlyph(icon)
        .fontSize(22)
        .fontColor([this.accentColor()])
      Text(label)
        .fontSize(UiTokens.fsCaption)
        .fontWeight(FontWeight.Medium)
        .margin({ top: 6 })
        .maxLines(1)
    }
    .layoutWeight(1)
    .padding({ top: 12, bottom: 12 })
    .borderRadius(UiTokens.cardRadius)
    .backgroundColor($r('app.color.card_glass'))
    .scale({ x: this.qaPressed === idx ? PRESS_SCALE : 1, y: this.qaPressed === idx ? PRESS_SCALE : 1 })
    .visualEffect(pressEffect(this.qaPressed === idx))
    .onTouch((e: TouchEvent): void => {
      this.onQaTouch(idx, e);
    })
    .onClick((): void => {
      this.openModule(key);
    })
  }

  @Builder
  categoryRow(cat: WorkbenchCategory) {
    GlassCard({
      insetH: 0,
      onTap: (): void => {
        const param: Record<string, Object> = { 'title': cat.title, 'stack': this.navStack };
        this.navStack.pushPath({ name: 'workbench-category', param: param });
      }
    }) {
      Row() {
        Column() {
          Text(cat.title)
            .fontSize(UiTokens.fsBody)
            .fontWeight(FontWeight.Medium)
          Text(cat.subtitle)
            .fontSize(UiTokens.fsSecondary)
            .fontColor($r('app.color.text_tertiary'))
            .margin({ top: 2 })
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
        }
        .alignItems(HorizontalAlign.Start)
        .layoutWeight(1)
        Text(`${cat.modules.length} ${this.t($r('app.string.workbench_items_unit'))}`)
          .fontSize(UiTokens.fsCaption)
          .fontColor($r('app.color.text_tertiary'))
          .margin({ right: 6 })
        Text('›')
          .fontSize(20)
          .fontColor($r('app.color.text_tertiary'))
      }
      .width('100%')
    }
  }

  build() {
    Column() {
      // 连接状态卡（只读信息块：与「会话」页状态卡同款玻璃块）
      Row() {
        Circle()
          .width(10)
          .height(10)
          .fill(this.connected ? $r('app.color.status_success') : $r('app.color.status_idle'))
          .margin({ right: 8 })
        Text(this.connected ? this.connHost : $r('app.string.wb_not_connected'))
          .fontSize(14)
          .fontColor(this.connected ? $r('app.color.status_success') : $r('app.color.status_idle'))
          .layoutWeight(1)
      }
      .width('100%')
      .padding(UiTokens.cardPad)
      .borderRadius(UiTokens.cardRadius)
      .backgroundColor($r('app.color.card_glass'))
      .margin({ top: UiTokens.cardVGap, bottom: UiTokens.cardVGap })

      // 搜索条（对齐 7378 workbench 搜索；放大镜用系统符号，不用 emoji）
        Row() {
          SymbolGlyph($r('sys.symbol.magnifyingglass'))
            .fontSize(17)
            .fontColor([$r('app.color.text_secondary')])
            .margin({ right: 8 })
          TextInput({ text: $$this.query, placeholder: $r('app.string.workbench_search') })
            .layoutWeight(1)
            .height(38)
            .fontSize(UiTokens.fsSecondary)
            .backgroundColor(Color.Transparent)
            .fontColor($r('app.color.input_text'))
            .placeholderColor($r('app.color.placeholder'))
        }
        .width('100%')
        .padding({ left: 12, right: 12 })
        .borderRadius(UiTokens.cardRadius)
        .backgroundColor($r('app.color.card_bg'))
        .margin({ bottom: UiTokens.cardVGap })

        if (this.query.trim().length > 0) {
          // 搜索结果
          ForEach(this.searchResults(), (m: WorkbenchModule) => {
            this.moduleRow(m)
          }, (m: WorkbenchModule) => m.key)
        } else {
          Text($r('app.string.workbench_quick'))
            .fontSize(UiTokens.fsCaption)
            .fontColor($r('app.color.text_tertiary'))
            .width('100%')
            .margin({ bottom: 4 })
          Row({ space: 10 }) {
            this.quickAction($r('sys.symbol.list_bullet'), this.t($r('app.string.workbench_qa_sessions')), 'sessions', 0)
            this.quickAction($r('sys.symbol.clock_arrow_2_circlepath'), this.t($r('app.string.workbench_qa_automation')), 'automation', 1)
            this.quickAction($r('sys.symbol.folder'), this.t($r('app.string.workbench_qa_files')), 'files', 2)
            this.quickAction($r('sys.symbol.wrench_and_screwdriver'), this.t($r('app.string.workbench_qa_tools')), 'tools', 3)
          }
          .width('100%')
          .margin({ bottom: UiTokens.cardVGap })

          Text($r('app.string.workbench_all'))
            .fontSize(UiTokens.fsCaption)
            .fontColor($r('app.color.text_tertiary'))
            .width('100%')
            .margin({ bottom: 4 })
          ForEach(WORKBENCH_CATEGORIES, (cat: WorkbenchCategory) => {
            this.categoryRow(cat)
          }, (cat: WorkbenchCategory) => cat.title)

          // 连接与设置 / 关于（一期入口保留）
          HubRow({
            titleRes: $r('app.string.workbench_conn'),
            hintRes: $r('app.string.workbench_conn_hint'),
            arrow: true,
            onTap: (): void => {
              const param: Record<string, Object> = { 'stack': this.navStack };
              this.navStack.pushPath({ name: 'settings', param: param });
            }
          })
          HubRow({
            titleRes: $r('app.string.workbench_about'),
            hintRes: null,
            arrow: false,
            onTap: (): void => {
              this.getUIContext().showAlertDialog({
                title: $r('app.string.about_title'),
                message: $r('app.string.about_message'),
                confirm: { value: 'OK', action: () => {} }
              });
            }
          })
        }
    }
    .width('100%')
    .constraintSize({ minHeight: '100%' })
    .padding({ top: UiTokens.topInset, bottom: UiTokens.bottomInset, left: UiTokens.pageHMargin, right: UiTokens.pageHMargin })
    .backgroundColor($r('app.color.page_bg'))
  }
}

// 工作台 hub 行卡（卡片壳统一走 GlassCard）
@Component
export struct HubRow {
  titleRes: Resource = $r('app.string.tab_workbench');
  hintRes: ResourceStr | null = null;
  arrow: boolean = false;
  onTap: () => void = () => {};

  build() {
    GlassCard({
      insetH: 0,
      onTap: (): void => {
        this.onTap();
      }
    }) {
      Row() {
        Column() {
          Text(this.titleRes)
            .fontSize(UiTokens.fsBody)
            .fontWeight(FontWeight.Medium)
          if (this.hintRes !== null) {
            Text(this.hintRes)
              .fontSize(UiTokens.fsSecondary)
              .fontColor($r('app.color.text_tertiary'))
              .margin({ top: 2 })
          }
        }
        .alignItems(HorizontalAlign.Start)
        .layoutWeight(1)
        if (this.arrow) {
          Text('›')
            .fontSize(22)
            .fontColor($r('app.color.text_tertiary'))
            .margin({ left: 8 })
        }
      }
      .width('100%')
    }
  }
}
