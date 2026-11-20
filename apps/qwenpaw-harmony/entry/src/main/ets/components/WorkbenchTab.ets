/*
 * 工作台 tab —— 移植 PR #7378 apps/qwenpaw-mobile/app/(tabs)/workbench.tsx：
 *   连接状态 + 搜索 + 快捷操作 + 4 分类（点开 → 模块列表）+ 模块 → 通用模块页（/module/{key}）。
 * 审批：GET /api/console/push-messages 真数据；有待审批且数量变化时发系统通知（一期能力保留）。
 */

import { common } from '@kit.AbilityKit';
import { swapRoute } from '../services/NavPush';
import { rememberPage } from '../services/LastPage';
import { preferences } from '@kit.ArkData';
import { emitter } from '@kit.BasicServicesKit';
import { loadConnection, QpConnection } from '../services/ConnectionStore';
import { hostOf } from '../services/PairingModel';
import { fetchApprovals, ApprovalInfo } from '../services/ApprovalsService';
import { AGENT_CHANGE_EVENT } from '../services/AgentsService';
import { CONN_CHANGE_EVENT } from '../services/AppEvents';
import { CONN_LIVENESS_EVENT, ConnLiveness, lastLiveness } from '../services/LivenessService';
import { publishNotice, requestNotificationPermission } from '../services/NotifyService';
import {
  WorkbenchCategory, WorkbenchModule, findWorkbenchModule,
  WORKBENCH_CATEGORIES, WORKBENCH_MODULES
} from '../services/WorkbenchModules';
import { UiTokens } from '../theme/UiTokens';
import { ThemeManager, ThemeSnapshot } from '../theme/ThemeManager';
import { PRESS_SCALE, PressLatch, pressEffect, pressTouch } from '../theme/PressFx';
import { GlassCard } from './GlassCard';

@Component
export struct WorkbenchTab {
  navStack: NavPathStack = new NavPathStack();
  @State connHost: string = '';
  @State connected: boolean = false;
  // 搜索词由标题栏工具条（SearchPill）持有并单向同步进来（变更即过滤）
  @Prop query: string = '';
  @State theme: ThemeSnapshot = ThemeManager.get().snapshot();
  @StorageLink('appIsDark') isDark: boolean = false;

  private accentColor(): ResourceColor {
    return this.isDark ? this.theme.accentDark : this.theme.accent;
  }

  // 扩展与 App Center 入口（模块静态表定位一次）：从「运行与安全」分类挪到 hub 顶层
  private extModule: WorkbenchModule | null = findWorkbenchModule('extensions');

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
  // 连接存活（服务端真实可达）由 LivenessService 统一广播；本页只订阅
  private liveListener: (data: emitter.EventData) => void = (_data: emitter.EventData): void => {};

  aboutToAppear(): void {
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    this.loadConn(ctx);
    ThemeManager.get().load(ctx).then((): void => {
      this.theme = ThemeManager.get().snapshot();
    });
    this.connListener = (_data: emitter.EventData): void => {
      this.loadConn(ctx);
    };
    // 智能体切换后审批按新 agent 重载（X-Agent-Id）
    this.agentListener = (_data: emitter.EventData): void => {
      this.loadConn(ctx);
    };
    this.liveListener = (_data: emitter.EventData): void => {
      this.applyLiveness(lastLiveness());
    };
    emitter.on(CONN_CHANGE_EVENT, this.connListener);
    emitter.on(AGENT_CHANGE_EVENT, this.agentListener);
    emitter.on(CONN_LIVENESS_EVENT, this.liveListener);
    this.applyLiveness(lastLiveness());
  }

  aboutToDisappear(): void {
    emitter.off(CONN_CHANGE_EVENT, this.connListener);
    emitter.off(AGENT_CHANGE_EVENT, this.agentListener);
    emitter.off(CONN_LIVENESS_EVENT, this.liveListener);
  }

  private loadConn(ctx: common.UIAbilityContext): void {
    loadConnection(ctx).then((conn: QpConnection | null) => {
      if (conn !== null) {
        // 「是否有配置」与「服务端是否可达」是两件事：可达性由 LivenessService 广播，
        // 这里只落主机名（此前直接置 connected=true 是「断网也显示绿色」的根因）
        this.connHost = hostOf(conn.baseUrl);
        this.refreshApprovals(conn, ctx);
      } else {
        this.connected = false;
        this.connHost = '';
      }
    });
  }

  private applyLiveness(l: ConnLiveness): void {
    this.connected = l.online;
    if (l.online && l.host.length > 0) {
      this.connHost = l.host;
    }
  }

  // 审批：只用于「待审批数量变化时发系统通知」（列表不在此页呈现，故不落任何状态）
  private async refreshApprovals(conn: QpConnection, ctx: common.UIAbilityContext): Promise<void> {
    try {
      const list: ApprovalInfo[] = await fetchApprovals(conn.baseUrl, conn.token, conn.agentId);
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

  private t(res: ResourceStr): string {
    if (typeof res === 'string') {
      return res as string;
    }
    try {
      const host: common.Context = this.getUIContext().getHostContext() as common.Context;
      return host.resourceManager.getStringSync((res as Resource).id);
    } catch (e) {
      return '';
    }
  }

  private openModule(key: string): void {
    const param: Record<string, string> = { 'key': key };
    // 记下「最后打开的模块」：分栏下切走页签再切回来，右栏恢复这个模块（见 pages/Index.enterTab）
    rememberPage(3, 'module', key);
    swapRoute(this.navStack, 'module', param);
  }

  private searchResults(): WorkbenchModule[] {
    const q: string = this.query.trim().toLowerCase();
    if (q.length === 0) {
      return [];
    }
    return WORKBENCH_MODULES.filter((m: WorkbenchModule): boolean =>
      `${this.t(m.title)} ${this.t(m.subtitle)} ${m.keywords.join(' ')} ${m.scope.join(' ')}`.toLowerCase().includes(q));
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
          .fillColor(this.accentColor())
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

  @Builder
  quickAction(icon: Resource, label: string, key: string, idx: number) {
    Column() {
      Image(icon)
        .width(22).height(22)
        .fillColor(this.accentColor())
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
        const param: Record<string, Object> = { 'key': cat.key, 'stack': this.navStack };
        // 分类页同样是二级页：切页签回来时一并恢复（与模块页同一份记忆）
        rememberPage(3, 'workbench-category', cat.key);
        swapRoute(this.navStack, 'workbench-category', param);
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
        Image($r('app.media.chevron_right'))
          .width(16).height(16)
          .fillColor($r('app.color.text_tertiary'))
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

      // 搜索框已迁到标题栏工具条（SearchPill，沉浸光感 + 随 tab 切换一起滑；
      // 搜索框已上提为标题栏工具条内容（会话/智能体/工作台三处统一形态），此处只渲染结果
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
            this.quickAction($r('app.media.list'), this.t($r('app.string.workbench_qa_sessions')), 'sessions', 0)
            this.quickAction($r('app.media.timer_reset'), this.t($r('app.string.workbench_qa_automation')), 'automation', 1)
            this.quickAction($r('app.media.folder'), this.t($r('app.string.workbench_qa_files')), 'files', 2)
            this.quickAction($r('app.media.wrench'), this.t($r('app.string.workbench_qa_tools')), 'tools', 3)
          }
          .width('100%')
          .margin({ bottom: UiTokens.cardVGap })

          // 扩展与 App Center：hub 顶层入口（分类页里不再单列，模块表已移除）
          if (this.extModule !== null) {
            this.moduleRow(this.extModule)
          }

          Text($r('app.string.workbench_all'))
            .fontSize(UiTokens.fsCaption)
            .fontColor($r('app.color.text_tertiary'))
            .width('100%')
            .margin({ bottom: 4 })
          ForEach(WORKBENCH_CATEGORIES, (cat: WorkbenchCategory) => {
            this.categoryRow(cat)
          }, (cat: WorkbenchCategory) => cat.key)

          // 连接与设置 / 关于（一期入口保留）
          HubRow({
            titleRes: $r('app.string.workbench_conn'),
            hintRes: $r('app.string.workbench_conn_hint'),
            arrow: true,
            onTap: (): void => {
              // 设置已是根页承载的半模态弹窗（⋮ 菜单同一入口），此处只发事件
              // 工作台入口 = 正常二级页（⋮ 菜单入口才是半模态弹窗，见 pages/Index.openSettings）
              swapRoute(this.navStack, 'settings');
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
    // 顶部留白按「标题栏 + 搜索条 + 呼吸」给（工作台页搜索条已迁入标题栏 bottomBuilder）
    .padding({ top: UiTokens.searchStripTopInset, bottom: UiTokens.bottomInset, left: UiTokens.pageHMargin, right: UiTokens.pageHMargin })
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
          Image($r('app.media.chevron_right'))
            .width(16).height(16)
            .fillColor($r('app.color.text_tertiary'))
            .margin({ left: 8 })
        }
      }
      .width('100%')
    }
  }
}
