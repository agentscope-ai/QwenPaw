/*
 * 账户与设备（设置页）—— 移植 PR #7378 app/(tabs)/me.tsx：
 *   账户卡 + 已配对连接（切换 / 移除）+ 外观（主题）+ 安全 + 关于与自检。
 * 路由：settings（由标题栏齿轮 / 工作台「连接与设置」打开；param.stack 用于跳转模块页）。
 */

import { common } from '@kit.AbilityKit';
import { pushRoute, topRouteIs } from '../services/NavPush';
import { ThemeManager, ThemeSnapshot, ThemePreset, THEME_PRESETS } from '../theme/ThemeManager';
import { MinePage } from '../components/MinePage';
import {
  QpConnection, loadConnection, loadConnections, switchConnection, removeConnection,
  clearConnection, connectionKey
} from '../services/ConnectionStore';
import { hostOf } from '../services/PairingModel';
import { syncConsoleThemeToManager } from '../services/ConsoleTheme';
import { UiTokens } from '../theme/UiTokens';
import { SheetGate, moduleSheetOptions } from '../components/SheetGate';
import { PRESS_SCALE, PressLatch, pressEffect, pressTouch } from '../theme/PressFx';
import { notifyConnectionStoreChange, ScanRouteParam, StackOnlyParam, requestTab } from '../services/AppEvents';
import { verifyConnection, describeConnectError } from '../services/ConnectionService';
import {
  PlatformRelayNode, PlatformRelayQuota, PlatformRelayStatus, RELAY_CONNECTED,
  getRelayStatus, authorizeRelay, getRelayQuota, listRelayNodes, revokeRelayNode
} from '../services/PlatformRelay';
import { getPlatformAccessToken, PLATFORM_BASE_URL, PlatformSession, loadPlatformSession, platformLogout } from '../services/PlatformSession';
import { RelayNodesSheet } from '../components/RelayNodesSheet';
import { t, tf } from '../services/I18n';

// 设置内容（半模态弹窗内容）：由 Index 的 bindSheet 承载（⋮ 菜单打开）——不再是一个
// NavDestination 页面；页内二级入口（模块页等）仍用传入的导航栈 push。
@Component
export struct SettingsContent {
  // 外层导航栈（页内「安全」等入口要 push 二级页）；由承载方传入
  stack: NavPathStack | null = null;
  // 内容自带「设置」标题（半模态弹窗用）；页面形态由标题栏出标题，传 false
  showTitle: boolean = true;
  @State theme: ThemeSnapshot = ThemeManager.get().snapshot();
  @StorageLink('appIsDark') isDark: boolean = false;
  @State conns: QpConnection[] = [];
  @State currentKey: string = '';
  // 半模态开关走统一闸门（单向绑定 + 回退动画期间排队；材质/避让由 moduleSheetOptions 统一给）
  @State syncEnabled: boolean = false;
  @State syncing: boolean = false;
  @State reconnecting: boolean = false;
  // —— Platform 远程访问（中继）——
  // 仅 hub 模式实例支持：状态取自实例 /remote-access/platform，额度与节点取自 Platform 汇总
  @State relayStatus: string = '';
  @State relayNodeId: string = '';
  @State relayError: string = '';
  @State relayBusy: boolean = false;
  @State relayNodes: PlatformRelayNode[] = [];
  @State relayQuota: PlatformRelayQuota = new PlatformRelayQuota();
  @State relayNodesShown: boolean = false;
  @State relayNodesLoading: boolean = false;
  @State relayNodesError: string = '';
  @State relayRemovingId: string = '';
  private relayGate: SheetGate = new SheetGate();
  // —— Platform 账号（对齐 7378 me.tsx「Platform 账号」组）——
  // 登录态取自本地会话；从登录/授权页返回时由 onShown 复查
  @State platformLoggedIn: boolean = false;
  @State platformUser: string = '';
  @State platformBusy: boolean = false;
  // 内容区沉浸光感（官方：内容区材质不生效）→ 自绘按压反馈：按下收缩 + 点光源
  @State pressed: number = -1;
  private pressLatch: PressLatch = new PressLatch();

  private onPress(idx: number, e: TouchEvent): void {
    pressTouch(this.getUIContext(), e, this.pressLatch, (v: boolean): void => {
      this.pressed = v ? idx : -1;
    });
  }

  private isPressed(idx: number): boolean {
    return this.pressed === idx;
  }

  aboutToAppear(): void {
    // 导航栈由承载方传入（构造时赋值），此处不再解析路由参数
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    ThemeManager.get().load(ctx).then((): void => {
      this.theme = ThemeManager.get().snapshot();
      this.syncEnabled = ThemeManager.get().isSyncEnabled();
    });
    this.reloadConns(ctx);
    this.refreshRelay(ctx);
    this.refreshPlatformSession(ctx);
  }

  // Platform 登录态（本地会话）：控制「Platform 账号」组显示登录入口还是账号 + 退出
  private refreshPlatformSession(ctx: common.UIAbilityContext): void {
    loadPlatformSession(ctx).then((session: PlatformSession | null): void => {
      this.platformLoggedIn = session !== null;
      this.platformUser = session === null ? '' : session.username;
    }).catch((e: Object): void => {
      this.platformLoggedIn = false;
      this.platformUser = '';
    });
  }

  // 当前工作区对应的设备端 Agent 标识（本工程连接模型里 agentId 即该身份的锚点）
  private currentAgentId(): string {
    const conn: QpConnection | null = this.currentConn();
    return conn === null ? '' : conn.agentId;
  }

  private currentConn(): QpConnection | null {
    const key: string = this.currentKey;
    for (const c of this.conns) {
      if (connectionKey(c) === key) {
        return c;
      }
    }
    return this.conns.length > 0 ? this.conns[0] : null;
  }

  // 「当前 Agent」行：切到智能体页签（二级页拿到的是根页导航栈，先退回根再请求切页）
  private openAgentsTab(): void {
    const stack: NavPathStack | null = this.stack;
    if (stack !== null) {
      stack.pop(true);
    }
    requestTab(1);
  }

  // 「登录 Platform」行：进登录页（账号密码 / GitHub 两条路径都在那一页），返回后 onShown 复查
  private openPlatformLogin(): void {
    const stack: NavPathStack | null = this.stack;
    if (stack === null) {
      return;
    }
    const param: StackOnlyParam = { stack: stack };
    pushRoute(stack, 'platform-login', param);
  }

  // 「退出 Platform」：二次确认（对齐 7378 me.tsx confirmPlatformLogout 的文案口径）
  private confirmPlatformLogout(): void {
    this.getUIContext().showAlertDialog({
      title: $r('app.string.settings_platform_logout_title'),
      message: $r('app.string.settings_platform_logout_msg'),
      primaryButton: {
        value: t($r('app.string.common_cancel')),
        action: (): void => {}
      },
      secondaryButton: {
        value: t($r('app.string.settings_platform_logout')),
        fontColor: $r('app.color.status_error'),
        action: (): void => {
          this.doPlatformLogout();
        }
      }
    });
  }

  private doPlatformLogout(): void {
    if (this.platformBusy) {
      return;
    }
    this.platformBusy = true;
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    platformLogout(ctx).then((): void => {
      this.platformLoggedIn = false;
      this.platformUser = '';
      this.relayStatus = '';
      this.getUIContext().getPromptAction().showToast({
        message: t($r('app.string.settings_platform_logout_ok'))
      });
    }).catch((e: Object): void => {
      this.getUIContext().getPromptAction().showToast({
        message: (e as Error).message
      });
    }).finally((): void => {
      this.platformBusy = false;
    });
  }


  // 连接存储变更广播：CONN_STORE_EVENT 让会话页重取连接并复核；连接本身的变更广播
  // （CONN_CHANGE_EVENT，让其它 tab 刷新）由 ConnectionStore 在保存/切换/移除时统一发出
  private broadcastConnChange(): void {
    notifyConnectionStoreChange();
  }

  private async reloadConns(ctx: common.UIAbilityContext): Promise<void> {
    const list: QpConnection[] = await loadConnections(ctx);
    this.conns = list;
    const cur: QpConnection | null = await loadConnection(ctx);
    this.currentKey = cur !== null ? connectionKey(cur) : '';
  }

  // 与控制台同步：开 → 立即取一次色；关 → 回落本地预设
  private async onToggleSync(on: boolean): Promise<void> {
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    this.syncEnabled = on;
    if (!on) {
      await ThemeManager.get().setSyncEnabled(false, ctx);
      this.theme = ThemeManager.get().snapshot();
      return;
    }
    await this.onRefreshTheme();
  }

  private async onRefreshTheme(): Promise<void> {
    if (this.syncing) {
      return;
    }
    this.syncing = true;
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    const ok: boolean = await syncConsoleThemeToManager(ctx);
    this.theme = ThemeManager.get().snapshot();
    this.syncEnabled = ThemeManager.get().isSyncEnabled();
    this.syncing = false;
    if (!ok) {
      this.getUIContext().getPromptAction().showToast({ message: t($r('app.string.settings_sync_failed')) });
    }
  }

  private accentColor(): ResourceColor {
    return this.isDark ? this.theme.accentDark : this.theme.accent;
  }

  private async onPresetTap(preset: ThemePreset): Promise<void> {
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    const ok: boolean = await ThemeManager.get().selectPreset(preset.id, ctx);
    if (ok) {
      this.theme = ThemeManager.get().snapshot();
      // 选预设会显式关闭同步，开关状态跟着回落
      this.syncEnabled = ThemeManager.get().isSyncEnabled();
    }
  }

  private async onSwitch(key: string): Promise<void> {
    if (key === this.currentKey) {
      return;
    }
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    await switchConnection(ctx, key);
    await this.reloadConns(ctx);
    this.broadcastConnChange();
  }

  private confirmRemove(conn: QpConnection): void {
    const host: string = hostOf(conn.baseUrl);
    this.getUIContext().showAlertDialog({
      title: t($r('app.string.settings_remove_title')),
      message: `${host}\n${t($r('app.string.settings_remove_msg'))}`,
      primaryButton: {
        value: t($r('app.string.common_cancel')),
        action: (): void => {}
      },
      secondaryButton: {
        value: t($r('app.string.settings_remove')),
        fontColor: $r('app.color.status_error'),
        action: (): void => {
          this.doRemove(conn);
        }
      }
    });
  }

  private async doRemove(conn: QpConnection): Promise<void> {
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    await removeConnection(ctx, connectionKey(conn));
    await this.reloadConns(ctx);
    this.broadcastConnChange();
  }

  private confirmDisconnectAll(): void {
    this.getUIContext().showAlertDialog({
      title: t($r('app.string.settings_disconnect_title')),
      message: $r('app.string.settings_disconnect_msg'),
      primaryButton: {
        value: t($r('app.string.common_cancel')),
        action: (): void => {}
      },
      secondaryButton: {
        value: t($r('app.string.settings_disconnect')),
        fontColor: $r('app.color.status_error'),
        action: (): void => {
          const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
          clearConnection(ctx).then((): void => {
            this.reloadConns(ctx);
            this.broadcastConnChange();
          });
        }
      }
    });
  }

  private openModule(key: string): void {
    if (this.stack !== null) {
      const param: Record<string, string> = { 'key': key };
      pushRoute(this.stack, 'module', param);
    }
  }

  private openScan(): void {
    if (this.stack === null || topRouteIs(this.stack, 'scan')) {
      return;
    }
    const param: ScanRouteParam = { stack: this.stack };
    this.stack.pushPathByName('scan', param, (_info: PopInfo): void => {
      const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
      this.reloadConns(ctx);
      this.broadcastConnChange();
    });
  }

  @Builder
  sectionTitle(res: Resource) {
    Text(res)
      .fontSize(UiTokens.fsCaption)
      .fontColor($r('app.color.text_tertiary'))
      .width('100%')
      .margin({ top: 18, bottom: 6 })
  }

  // 主题色菜单（行上挂 bindMenu）：不再套第二层半模态 —— 嵌套 bindSheet 在真机上出现过
  // "点开无反应"，且这一层本来就不需要自己的玻璃背板（外层已是设置页/弹窗）
  // 主题色选项（面板内联行）：色点 + 名称 + 当前项描边加粗 —— 面板内不再套菜单/弹层
  @Builder
  themeRow(preset: ThemePreset, idx: number) {
    Row() {
      Circle()
        .width(22)
        .height(22)
        .fill(this.isDark ? preset.accentDark : preset.accent)
        .stroke(this.theme.presetId === preset.id
          ? (this.isDark ? preset.accentDark : preset.accent) : $r('app.color.line'))
        .strokeWidth(this.theme.presetId === preset.id ? 3 : 1)
      Text(preset.name)
        .fontSize(UiTokens.fsSecondary)
        .fontColor(this.theme.presetId === preset.id
          ? $r('app.color.text_primary_strong') : $r('app.color.text_secondary'))
        .margin({ left: 10 })
        .layoutWeight(1)
      if (this.theme.presetId === preset.id) {
        Image($r('app.media.check'))
          .width(16)
          .height(16)
          .fillColor(this.isDark ? this.theme.accentDark : this.theme.accent)
      }
    }
    .width('100%')
    .padding(12)
    .borderRadius(UiTokens.cardRadius)
    .backgroundColor($r('app.color.card_glass'))
    .margin({ top: 6 })
    .scale({ x: this.isPressed(idx) ? PRESS_SCALE : 1, y: this.isPressed(idx) ? PRESS_SCALE : 1 })
    .visualEffect(pressEffect(this.isPressed(idx)))
    .onTouch((e: TouchEvent): void => {
      this.onPress(idx, e);
    })
    .onClick((): void => {
      this.onPresetTap(preset);
    })
  }

  @Builder
  connRow(conn: QpConnection, idx: number) {
    Row() {
      Column() {
        Text(hostOf(conn.baseUrl))
          .fontSize(UiTokens.fsBody)
          .fontWeight(FontWeight.Medium)
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
        Text(conn.serverMode.length > 0 ? conn.serverMode : conn.source)
          .fontSize(UiTokens.fsCaption)
          .fontColor($r('app.color.text_tertiary'))
          .margin({ top: 2 })
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1)
      if (connectionKey(conn) === this.currentKey) {
        Text($r('app.string.settings_current'))
          .fontSize(UiTokens.fsChip)
          .fontColor(this.accentColor())
          .backgroundColor($r('app.color.card_bg'))
          .borderRadius(UiTokens.chipRadius)
          .padding({ left: 8, right: 8, top: 3, bottom: 3 })
          .margin({ right: 6 })
      } else {
        Text($r('app.string.settings_switch'))
          .fontSize(UiTokens.fsCaption)
          .fontColor($r('app.color.text_tertiary'))
          .margin({ right: 6 })
      }
      Image($r('app.media.x'))
        .width(16).height(16)
        .fillColor($r('app.color.text_tertiary'))
        .padding(6)
        .onClick((): void => {
          this.confirmRemove(conn);
        })
    }
    .width('100%')
    .padding(UiTokens.cardPad)
    .borderRadius(UiTokens.cardRadius)
    .backgroundColor($r('app.color.card_glass'))
    .margin({ bottom: 6 })
    .scale({ x: this.isPressed(idx) ? PRESS_SCALE : 1, y: this.isPressed(idx) ? PRESS_SCALE : 1 })
    .visualEffect(pressEffect(this.isPressed(idx)))
    .onTouch((e: TouchEvent): void => {
      this.onPress(idx, e);
    })
    .onClick((): void => {
      this.onSwitch(connectionKey(conn));
    })
  }

  @Builder
  pairNewRow() {
    Row() {
      Column() {
        Text($r('app.string.settings_pair_new'))
          .fontSize(UiTokens.fsBody)
          .fontWeight(FontWeight.Medium)
        Text($r('app.string.settings_pair_new_copy'))
          .fontSize(UiTokens.fsCaption)
          .fontColor($r('app.color.text_tertiary'))
          .margin({ top: 2 })
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1)
      Image($r('app.media.qr_code'))
        .width(18).height(18)
        .fillColor(this.accentColor())
    }
    .width('100%')
    .padding(UiTokens.cardPad)
    .borderRadius(UiTokens.cardRadius)
    .backgroundColor($r('app.color.card_glass'))
    .margin({ top: 6 })
    .scale({ x: this.isPressed(160) ? PRESS_SCALE : 1, y: this.isPressed(160) ? PRESS_SCALE : 1 })
    .visualEffect(pressEffect(this.isPressed(160)))
    .onTouch((e: TouchEvent): void => {
      this.onPress(160, e);
    })
    .onClick((): void => {
      this.openScan();
    })
  }

  // 云端 QwenPaw（平台部署）：创建 / 状态 / 日志 / 重启 / 切版本（对齐 7378 app/platform/deploy.tsx）
  private openDeploy(): void {
    if (this.stack === null) {
      return;
    }
    const param: StackOnlyParam = { stack: this.stack };
    pushRoute(this.stack, 'platform-deploy', param);
  }

  // 重新连接当前工作区（原首页连接卡的「重新连接」入口迁到此处，与连接管理同页）
  @Builder
  reconnectRow() {
    Row() {
      Column() {
        Text($r('app.string.settings_reconnect'))
          .fontSize(UiTokens.fsBody)
          .fontWeight(FontWeight.Medium)
        Text($r('app.string.settings_reconnect_copy'))
          .fontSize(UiTokens.fsCaption)
          .fontColor($r('app.color.text_tertiary'))
          .margin({ top: 2 })
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1)
      if (this.reconnecting) {
        LoadingProgress()
          .width(20)
          .height(20)
          .color(this.accentColor())
      } else {
        Image($r('app.media.refresh_cw'))
          .width(18).height(18)
          .fillColor(this.accentColor())
      }
    }
    .width('100%')
    .padding(UiTokens.cardPad)
    .borderRadius(UiTokens.cardRadius)
    .backgroundColor($r('app.color.card_glass'))
    .margin({ top: 6 })
    .scale({ x: this.isPressed(170) ? PRESS_SCALE : 1, y: this.isPressed(170) ? PRESS_SCALE : 1 })
    .visualEffect(pressEffect(this.isPressed(170)))
    .onTouch((e: TouchEvent): void => {
      this.onPress(170, e);
    })
    .onClick((): void => {
      this.reconnect();
    })
  }

  // 用已落盘连接（含 token）复核当前工作区：成功/失败都给出提示，不重新兑换配对码
  private async reconnect(): Promise<void> {
    if (this.reconnecting) {
      return;
    }
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    const conn: QpConnection | null = await loadConnection(ctx);
    if (conn === null) {
      this.getUIContext().getPromptAction().showToast({
        message: t($r('app.string.wb_not_connected'))
      });
      return;
    }
    this.reconnecting = true;
    try {
      await verifyConnection(conn);
      this.broadcastConnChange();
      this.getUIContext().getPromptAction().showToast({
        message: t($r('app.string.settings_reconnect_ok'))
      });
    } catch (e) {
      this.getUIContext().showAlertDialog({
        title: t($r('app.string.settings_reconnect_failed')),
        message: describeConnectError(conn.baseUrl, e as Error)
      });
    } finally {
      this.reconnecting = false;
    }
  }

  // ==================== Platform 远程访问（中继）====================
  // 只有 hub 模式实例才有 /remote-access/platform；LAN 直连实例整段不出现。

  private hubConn(): QpConnection | null {
    const key: string = this.currentKey;
    for (const c of this.conns) {
      if (connectionKey(c) === key && c.serverMode === 'hub') {
        return c;
      }
    }
    return null;
  }

  private async refreshRelay(ctx: common.UIAbilityContext): Promise<void> {
    const conn: QpConnection | null = this.hubConn();
    if (conn === null) {
      this.relayStatus = '';
      this.relayNodeId = '';
      this.relayError = '';
      return;
    }
    try {
      const status: PlatformRelayStatus = await getRelayStatus(conn.baseUrl, conn.token, conn.agentId);
      this.relayStatus = status.status;
      this.relayNodeId = status.nodeId;
      this.relayError = '';
    } catch (e) {
      this.relayStatus = '';
      this.relayNodeId = '';
      this.relayError = (e as Error).message;
    }
  }

  // 开启 / 重授权：未登录先跳 Platform 登录页（与发布文章同一套口径）
  private async authorizeRelayNow(): Promise<void> {
    if (this.relayBusy) {
      return;
    }
    const conn: QpConnection | null = this.hubConn();
    if (conn === null) {
      return;
    }
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    this.relayBusy = true;
    try {
      const session: PlatformSession | null = await loadPlatformSession(ctx);
      if (session === null) {
        this.getUIContext().getPromptAction().showToast({
          message: t($r('app.string.relay_login_required'))
        });
        return;
      }
      const token: string = await getPlatformAccessToken(ctx);
      if (token.length === 0) {
        this.getUIContext().getPromptAction().showToast({
          message: t($r('app.string.relay_login_required'))
        });
        return;
      }
      const name: string = conn.username.length > 0 ? tf($r('app.string.relay_client_name'), conn.username) : hostOf(conn.baseUrl);
      const status: PlatformRelayStatus =
        await authorizeRelay(conn.baseUrl, conn.token, conn.agentId, token, PLATFORM_BASE_URL, name);
      this.relayStatus = status.status;
      this.relayNodeId = status.nodeId;
      this.relayError = '';
      this.getUIContext().showAlertDialog({
        title: t($r('app.string.relay_auth_ok_title')),
        message: t($r('app.string.relay_auth_ok_copy'))
      });
    } catch (e) {
      const msg: string = (e as Error).message;
      this.relayError = msg;
      this.getUIContext().showAlertDialog({
        title: t($r('app.string.relay_auth_fail_title')),
        message: msg
      });
    } finally {
      this.relayBusy = false;
    }
  }

  // 二次确认：已连接时重授权会换绑到当前 Platform 账号
  private confirmRelay(): void {
    if (this.relayBusy) {
      return;
    }
    if (this.relayStatus !== RELAY_CONNECTED) {
      this.authorizeRelayNow();
      return;
    }
    this.getUIContext().showAlertDialog({
      title: t($r('app.string.relay_group_title')),
      message: t($r('app.string.relay_reauthorize_copy')),
      primaryButton: {
        value: t($r('app.string.common_cancel')),
        action: (): void => {
        }
      },
      secondaryButton: {
        value: t($r('app.string.relay_reauthorize_action')),
        action: (): void => {
          this.authorizeRelayNow();
        }
      }
    });
  }

  private openRelayNodes(): void {
    if (this.relayGate.request()) {
      this.relayNodesShown = true;
    }
  }

  // 面板数据面：额度 + 节点（Platform 汇总）
  private async loadRelayNodes(): Promise<void> {
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    this.relayNodesLoading = true;
    this.relayNodesError = '';
    try {
      const quota: PlatformRelayQuota = await getRelayQuota(ctx);
      const nodes: PlatformRelayNode[] = await listRelayNodes(ctx);
      this.relayQuota = quota;
      this.relayNodes = nodes;
    } catch (e) {
      this.relayNodesError = (e as Error).message;
    } finally {
      this.relayNodesLoading = false;
    }
  }

  private async revokeRelayNodeNow(nodeId: string): Promise<void> {
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    this.relayRemovingId = nodeId;
    try {
      await revokeRelayNode(ctx, nodeId);
      this.relayNodes = this.relayNodes.filter((n: PlatformRelayNode): boolean => n.id !== nodeId);
      const next: PlatformRelayQuota = new PlatformRelayQuota();
      next.used = Math.max(0, this.relayQuota.used - 1);
      next.limit = this.relayQuota.limit;
      next.canBind = true;
      this.relayQuota = next;
      if (nodeId === this.relayNodeId) {
        this.relayStatus = '';
        this.relayNodeId = '';
      }
      // 本机状态以实例为准，回收后再核一次
      await this.refreshRelay(ctx);
    } catch (e) {
      this.relayNodesError = (e as Error).message;
    } finally {
      this.relayRemovingId = '';
    }
  }

  // Platform 远程访问：连接/重授权行（hub 模式实例专属）
  @Builder
  relayRow() {
    Row() {
      Column() {
        Text(this.relayStatus === RELAY_CONNECTED
          ? $r('app.string.relay_row_connected') : $r('app.string.relay_row_disconnected'))
          .fontSize(UiTokens.fsBody)
          .fontWeight(FontWeight.Medium)
        Text(this.relayError.length > 0 ? this.relayError
          : (this.relayStatus === RELAY_CONNECTED
            ? $r('app.string.relay_row_sub_on') : $r('app.string.relay_row_sub_off')))
          .fontSize(UiTokens.fsCaption)
          .fontColor(this.relayError.length > 0
            ? $r('app.color.status_error') : $r('app.color.text_tertiary'))
          .margin({ top: 2 })
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1)

      if (this.relayBusy) {
        LoadingProgress()
          .width(20)
          .height(20)
          .color(this.accentColor())
      } else {
        Text(this.relayStatus === RELAY_CONNECTED
          ? $r('app.string.relay_trailing_on') : $r('app.string.relay_trailing_off'))
          .fontSize(UiTokens.fsCaption)
          .fontColor($r('app.color.text_tertiary'))
        Image($r('app.media.chevron_right'))
          .width(16).height(16)
          .fillColor($r('app.color.text_tertiary'))
          .margin({ left: 6 })
      }
    }
    .width('100%')
    .padding(UiTokens.cardPad)
    .borderRadius(UiTokens.cardRadius)
    .backgroundColor($r('app.color.card_glass'))
    .margin({ bottom: 6 })
    .scale({ x: this.isPressed(190) ? PRESS_SCALE : 1, y: this.isPressed(190) ? PRESS_SCALE : 1 })
    .visualEffect(pressEffect(this.isPressed(190)))
    .onTouch((e: TouchEvent): void => {
      this.onPress(190, e);
    })
    .onClick((): void => {
      this.confirmRelay();
    })
  }

  // 自部署连接管理入口（额度 / 解绑 / 清理离线）
  @Builder
  relayNodesRow() {
    Row() {
      Column() {
        Text($r('app.string.relay_nodes_row'))
          .fontSize(UiTokens.fsBody)
          .fontWeight(FontWeight.Medium)
        Text($r('app.string.relay_nodes_row_sub'))
          .fontSize(UiTokens.fsCaption)
          .fontColor($r('app.color.text_tertiary'))
          .margin({ top: 2 })
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1)
      Image($r('app.media.chevron_right'))
        .width(16).height(16)
        .fillColor($r('app.color.text_tertiary'))
    }
    .width('100%')
    .padding(UiTokens.cardPad)
    .borderRadius(UiTokens.cardRadius)
    .backgroundColor($r('app.color.card_glass'))
    .scale({ x: this.isPressed(191) ? PRESS_SCALE : 1, y: this.isPressed(191) ? PRESS_SCALE : 1 })
    .visualEffect(pressEffect(this.isPressed(191)))
    .onTouch((e: TouchEvent): void => {
      this.onPress(191, e);
    })
    .onClick((): void => {
      this.openRelayNodes();
    })
  }

  @Builder
  relayNodesSheet() {
    RelayNodesSheet({
      nodes: this.relayNodes,
      quota: this.relayQuota,
      currentNodeId: this.relayNodeId,
      loading: this.relayNodesLoading,
      removingId: this.relayRemovingId,
      error: this.relayNodesError,
      onReload: (): void => {
        this.loadRelayNodes();
      },
      onRevoke: (nodeId: string): void => {
        this.revokeRelayNodeNow(nodeId);
      }
    })
  }

  // 云端部署入口行（与扫码配对/重连同区）
  @Builder
  deployRow() {
    Row() {
      Column() {
        Text($r('app.string.pd_title'))
          .fontSize(UiTokens.fsBody)
          .fontWeight(FontWeight.Medium)
        Text($r('app.string.pd_settings_copy'))
          .fontSize(UiTokens.fsCaption)
          .fontColor($r('app.color.text_tertiary'))
          .margin({ top: 2 })
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1)
      Image($r('app.media.cloud'))
        .width(18).height(18)
        .fillColor(this.accentColor())
    }
    .width('100%')
    .padding(UiTokens.cardPad)
    .borderRadius(UiTokens.cardRadius)
    .backgroundColor($r('app.color.card_glass'))
    .margin({ top: 6 })
    .scale({ x: this.isPressed(180) ? PRESS_SCALE : 1, y: this.isPressed(180) ? PRESS_SCALE : 1 })
    .visualEffect(pressEffect(this.isPressed(180)))
    .onTouch((e: TouchEvent): void => {
      this.onPress(180, e);
    })
    .onClick((): void => {
      this.openDeploy();
    })
  }

  build() {
      Scroll() {
        Column() {
          // 弹窗（半模态）：顶部留出系统关闭叉（✕）与拖拽条，标题也放进来
          if (this.showTitle) {
            Text($r('app.string.menu_settings'))
              .fontSize(20)
              .fontWeight(FontWeight.Bold)
              .width('100%')
              .margin({ bottom: 4 })
          }
          // 账户卡（对齐 RN me.tsx profile：当前连接 + Agent）
          Row() {
            Column() {
              Text($r('app.string.settings_account'))
                .fontSize(UiTokens.fsCaption)
                .fontColor($r('app.color.text_tertiary'))
              Text(this.conns.length > 0
                ? hostOf(this.conns[0].baseUrl) : t($r('app.string.wb_not_connected')))
                .fontSize(UiTokens.fsBody)
                .fontWeight(FontWeight.Medium)
                .margin({ top: 3 })
            }
            .alignItems(HorizontalAlign.Start)
            .layoutWeight(1)
          }
          .width('100%')
          .padding(UiTokens.cardPad)
          .borderRadius(UiTokens.cardRadius)
          .backgroundColor($r('app.color.card_glass'))
          .margin({ top: UiTokens.cardVGap })

          this.sectionTitle($r('app.string.settings_paired'))
          ForEach(this.conns, (c: QpConnection, i: number) => {
            this.connRow(c, i)
          }, (c: QpConnection) => connectionKey(c))
          this.pairNewRow()
          this.reconnectRow()
          this.deployRow()

          // Platform 远程访问（中继）：仅 hub 模式实例（对齐 7378 me.tsx 的 serverMode === "hub" 条件）
          if (this.hubConn() !== null) {
            this.sectionTitle($r('app.string.relay_group_title'))
            this.relayRow()
            this.relayNodesRow()
          }

          this.sectionTitle($r('app.string.settings_current_agent'))
          // 当前 Agent：点按切到智能体页签（7378 me.tsx 的该组另有「重新连接」行，本页已在
          // 「已配对」组承载，故不重复）。trailing 不再重复 agentId —— 本工程连接模型里
          // agentId 就是该身份的锚点，7378 的 trailing 同样是 id。
          Row({ space: 10 }) {
            Image($r('app.media.bot'))
              .width(20)
              .height(20)
              .fillColor(this.accentColor())
            Column() {
              Text(this.currentAgentId().length > 0
                ? this.currentAgentId() : t($r('app.string.wb_not_connected')))
                .fontSize(UiTokens.fsBody)
                .fontWeight(FontWeight.Medium)
              Text($r('app.string.settings_current_agent_hint'))
                .fontSize(UiTokens.fsCaption)
                .fontColor($r('app.color.text_tertiary'))
                .margin({ top: 2 })
            }
            .alignItems(HorizontalAlign.Start)
            .layoutWeight(1)
            Image($r('app.media.chevron_right'))
              .width(16).height(16)
              .fillColor($r('app.color.text_tertiary'))
          }
          .width('100%')
          .padding(UiTokens.cardPad)
          .borderRadius(UiTokens.cardRadius)
          .backgroundColor($r('app.color.card_glass'))
          .scale({ x: this.isPressed(210) ? PRESS_SCALE : 1, y: this.isPressed(210) ? PRESS_SCALE : 1 })
          .visualEffect(pressEffect(this.isPressed(210)))
          .onTouch((e: TouchEvent): void => {
            this.onPress(210, e);
          })
          .onClick((): void => {
            this.openAgentsTab();
          })

          // Platform 账号（对齐 7378 me.tsx「Platform 账号」组）：账号态行 + 登录/退出。
          // 7378 该组内的「自部署连接」行在本页由「Platform 远程访问」组承载，故不重复。
          this.sectionTitle($r('app.string.settings_platform_group'))
          Row({ space: 10 }) {
            Image($r('app.media.cloud'))
              .width(20)
              .height(20)
              .fillColor(this.accentColor())
            Column() {
              Text($r('app.string.settings_platform_account'))
                .fontSize(UiTokens.fsBody)
                .fontWeight(FontWeight.Medium)
              Text(this.platformLoggedIn
                ? (this.platformUser.length > 0
                  ? this.platformUser : t($r('app.string.settings_platform_logged_hint')))
                : t($r('app.string.settings_platform_login_hint')))
                .fontSize(UiTokens.fsCaption)
                .fontColor($r('app.color.text_tertiary'))
                .margin({ top: 2 })
            }
            .alignItems(HorizontalAlign.Start)
            .layoutWeight(1)
            Text(this.platformLoggedIn
              ? $r('app.string.settings_platform_logged')
              : $r('app.string.settings_platform_logged_out'))
              .fontSize(UiTokens.fsCaption)
              .fontColor($r('app.color.text_tertiary'))
          }
          .width('100%')
          .padding(UiTokens.cardPad)
          .borderRadius(UiTokens.cardRadius)
          .backgroundColor($r('app.color.card_glass'))

          if (this.platformLoggedIn) {
            Row({ space: 10 }) {
              Image($r('app.media.log_out'))
                .width(20)
                .height(20)
                .fillColor($r('app.color.status_error'))
              Column() {
                Text($r('app.string.settings_platform_logout'))
                  .fontSize(UiTokens.fsBody)
                  .fontWeight(FontWeight.Medium)
                  .fontColor($r('app.color.status_error'))
              }
              .alignItems(HorizontalAlign.Start)
              .layoutWeight(1)
            }
            .width('100%')
            .padding(UiTokens.cardPad)
            .borderRadius(UiTokens.cardRadius)
            .backgroundColor($r('app.color.card_glass'))
            .margin({ top: 6 })
            .scale({ x: this.isPressed(220) ? PRESS_SCALE : 1, y: this.isPressed(220) ? PRESS_SCALE : 1 })
            .visualEffect(pressEffect(this.isPressed(220)))
            .onTouch((e: TouchEvent): void => {
              this.onPress(220, e);
            })
            .onClick((): void => {
              this.confirmPlatformLogout();
            })
          } else {
            Row({ space: 10 }) {
              Image($r('app.media.log_in'))
                .width(20)
                .height(20)
                .fillColor(this.accentColor())
              Column() {
                Text($r('app.string.settings_platform_login'))
                  .fontSize(UiTokens.fsBody)
                  .fontWeight(FontWeight.Medium)
                Text($r('app.string.settings_platform_login_sub'))
                  .fontSize(UiTokens.fsCaption)
                  .fontColor($r('app.color.text_tertiary'))
                  .margin({ top: 2 })
              }
              .alignItems(HorizontalAlign.Start)
              .layoutWeight(1)
              Image($r('app.media.chevron_right'))
                .width(16).height(16)
                .fillColor($r('app.color.text_tertiary'))
            }
            .width('100%')
            .padding(UiTokens.cardPad)
            .borderRadius(UiTokens.cardRadius)
            .backgroundColor($r('app.color.card_glass'))
            .margin({ top: 6 })
            .scale({ x: this.isPressed(220) ? PRESS_SCALE : 1, y: this.isPressed(220) ? PRESS_SCALE : 1 })
            .visualEffect(pressEffect(this.isPressed(220)))
            .onTouch((e: TouchEvent): void => {
              this.onPress(220, e);
            })
            .onClick((): void => {
              this.openPlatformLogin();
            })
          }

          // 设备（对齐 7378 me.tsx「设备」组：配对状态）
          this.sectionTitle($r('app.string.settings_device_group'))
          Row({ space: 10 }) {
            Image($r('app.media.shield_check'))
              .width(20)
              .height(20)
              .fillColor(this.accentColor())
            Column() {
              Text($r('app.string.settings_device_paired'))
                .fontSize(UiTokens.fsBody)
                .fontWeight(FontWeight.Medium)
              Text($r('app.string.settings_device_paired_hint'))
                .fontSize(UiTokens.fsCaption)
                .fontColor($r('app.color.text_tertiary'))
                .margin({ top: 2 })
            }
            .alignItems(HorizontalAlign.Start)
            .layoutWeight(1)
            Text($r('app.string.settings_device_paired_value'))
              .fontSize(UiTokens.fsCaption)
              .fontColor($r('app.color.text_tertiary'))
          }
          .width('100%')
          .padding(UiTokens.cardPad)
          .borderRadius(UiTokens.cardRadius)
          .backgroundColor($r('app.color.card_glass'))

          this.sectionTitle($r('app.string.settings_theme'))
          ForEach(THEME_PRESETS, (preset: ThemePreset, i: number) => {
            this.themeRow(preset, 100 + i)
          }, (preset: ThemePreset) => preset.id)

          this.sectionTitle($r('app.string.settings_theme_sync'))
          Row() {
            Column() {
              Text($r('app.string.settings_sync_title'))
                .fontSize(UiTokens.fsBody)
                .fontWeight(FontWeight.Medium)
              Text($r('app.string.settings_sync_hint'))
                .fontSize(UiTokens.fsCaption)
                .fontColor($r('app.color.text_tertiary'))
                .margin({ top: 2 })
            }
            .alignItems(HorizontalAlign.Start)
            .layoutWeight(1)
            Toggle({ type: ToggleType.Switch, isOn: this.syncEnabled })
              .selectedColor(this.accentColor())
              .onChange((on: boolean): void => {
                this.onToggleSync(on);
              })
          }
          .width('100%')
          .padding(UiTokens.cardPad)
          .borderRadius(UiTokens.cardRadius)
          .backgroundColor($r('app.color.card_glass'))

          Row() {
            Text($r('app.string.settings_sync_refresh'))
              .fontSize(UiTokens.fsBody)
              .fontWeight(FontWeight.Medium)
              .layoutWeight(1)
            if (this.syncing) {
              LoadingProgress()
                .width(20)
                .height(20)
                .color(this.accentColor())
            } else {
              Image($r('app.media.chevron_right'))
                .width(16).height(16)
                .fillColor($r('app.color.text_tertiary'))
            }
          }
          .width('100%')
          .padding(UiTokens.cardPad)
          .borderRadius(UiTokens.cardRadius)
          .backgroundColor($r('app.color.card_glass'))
          .margin({ top: 6 })
          .scale({ x: this.isPressed(160) ? PRESS_SCALE : 1, y: this.isPressed(160) ? PRESS_SCALE : 1 })
          .visualEffect(pressEffect(this.isPressed(160)))
          .onTouch((e: TouchEvent): void => {
            this.onPress(160, e);
          })
          .onClick((): void => {
            this.onRefreshTheme();
          })

          this.sectionTitle($r('app.string.settings_security_group'))
          Row() {
            Image($r('app.media.shield_check'))
              .width(20).height(20)
              .fillColor(this.accentColor())
              .margin({ right: 10 })
            Column() {
              Text($r('app.string.settings_security'))
                .fontSize(UiTokens.fsBody)
                .fontWeight(FontWeight.Medium)
              Text($r('app.string.settings_security_hint'))
                .fontSize(UiTokens.fsCaption)
                .fontColor($r('app.color.text_tertiary'))
                .margin({ top: 2 })
            }
            .alignItems(HorizontalAlign.Start)
            .layoutWeight(1)
            Image($r('app.media.chevron_right'))
              .width(16).height(16)
              .fillColor($r('app.color.text_tertiary'))
          }
          .width('100%')
          .padding(UiTokens.cardPad)
          .borderRadius(UiTokens.cardRadius)
          .backgroundColor($r('app.color.card_glass'))
          .scale({ x: this.isPressed(200) ? PRESS_SCALE : 1, y: this.isPressed(200) ? PRESS_SCALE : 1 })
          .visualEffect(pressEffect(this.isPressed(200)))
          .onTouch((e: TouchEvent): void => {
            this.onPress(200, e);
          })
          .onClick((): void => {
            this.openModule('security');
          })

          this.sectionTitle($r('app.string.about_title'))
          MinePage()

          Button($r('app.string.settings_disconnect'))
            .width('100%')
            .margin({ top: 20 })
            .backgroundColor($r('app.color.card_bg'))
            .fontColor($r('app.color.status_error'))
            .scale({ x: this.isPressed(300) ? PRESS_SCALE : 1, y: this.isPressed(300) ? PRESS_SCALE : 1 })
            .stateEffect(false)
            .visualEffect(pressEffect(this.isPressed(300)))
            .onTouch((e: TouchEvent): void => {
              this.onPress(300, e);
            })
            .onClick((): void => {
              this.confirmDisconnectAll();
            })
        }
        .width('100%')
        .padding({
          top: 64,
          bottom: 32,
          left: UiTokens.pageHMargin, right: UiTokens.pageHMargin
        })
        // 自部署连接管理：与主题面板同一套闸门口径（避免回退动画期间被框架回写关掉）
        .bindSheet(this.relayNodesShown, this.relayNodesSheet(),
          moduleSheetOptions(560, this.relayGate,
            (v: boolean): void => {
              this.relayNodesShown = v;
            }))
      }
      .height('100%')
      .scrollBar(BarState.Auto)
      // 不铺底色：本组件是半模态面板的内容，面板背板由 systemMaterial(ULTRA_THICK) 提供 ——
      // 官方口径，面板内铺实底会把材质自带的背景盖掉（观感即"没有沉浸光感"）
  }
}
