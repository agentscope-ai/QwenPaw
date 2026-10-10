/*
 * 连接面板 —— 会话 tab 主体（一期）。
 * 形态对齐 PR #7378：扫码/手输配对码 → redeem → verify → 持久化（preferences）。
 * 状态机：disconnected / connecting / connected / failed。
 */

import { common, Configuration, ConfigurationConstant, abilityAccessCtrl, Permissions } from '@kit.AbilityKit';

import { GlassCard } from './GlassCard';
import { SheetGate, moduleSheetOptions } from './SheetGate';
import { http } from '@kit.NetworkKit';
import { emitter } from '@kit.BasicServicesKit';
import { scanBarcode, scanCore } from '@kit.ScanKit';
import { QpConnection, loadConnection, saveConnection, clearConnection } from '../services/ConnectionStore';
import { connectToQwenPaw, describeConnectError, doRequest } from '../services/ConnectionService';
import { parsePairingUri, parseManualInput, hostOf } from '../services/PairingModel';
import {
  fetchChats, ChatInfo, relativeTime, renameChat, ChatGroup, fetchChatGroups,
  createChatGroup, renameChatGroup, deleteChatGroup, moveChatToGroup
} from '../services/ChatsService';
import { ChatRouteParam, CHAT_CLOSED_EVENT } from '../services/ChatDetailService';
import { AGENT_CHANGE_EVENT } from '../services/AgentsService';
import { CONN_CHANGE_EVENT } from './WorkbenchTab';
import { ThemeManager, ThemeSnapshot, ThemeListener } from '../theme/ThemeManager';
import { UiTokens } from '../theme/UiTokens';
import { PRESS_SCALE, PressLatch, pressEffect, pressTouch } from '../theme/PressFx';
import { ApprovalInfo, fetchApprovals, approveRequest, denyRequest } from '../services/ApprovalsService';
import { ApprovalCard } from './ApprovalCard';

// 会话置顶请求体（对齐 RN client.ts：PUT /chats/{id} {name?, pinned?, group_id?}）
interface ChatPinBody {
  pinned: boolean;
}

@Component
export struct ConnectPanel {
  navStack: NavPathStack = new NavPathStack();
  @State connected: boolean = false;
  @State connecting: boolean = false;
  @State statusText: string = '';
  @State statusColor: ResourceColor = $r('app.color.status_idle');
  @State errorMsg: string = '';
  @State baseUrlInput: string = '';
  @State ticketInput: string = '';
  @State connHost: string = '';
  @State connUser: string = '';
  @State connMode: string = '';
  @State agentNames: string[] = [];
  @State chats: ChatInfo[] = [];
  @State showArchived: boolean = false;
  // 会话分组（对齐 RN features/chats/grouping.ts + chats.tsx）
  @State groups: ChatGroup[] = [];
  // 统一半模态（重命名会话 / 新建·重命名分组 / 移动到分组）：
  // 单 bindSheet + 模式切换，避免「同一组件挂多个 bindSheet 只最后一个生效」
  @State modalShown: boolean = false;
  // 半模态开关统一走闸门（单向绑定 + 回退动画期间排队；材质由 moduleSheetOptions 统一给）
  private modalGate: SheetGate = new SheetGate();
  private inboxGate: SheetGate = new SheetGate();

  private openModalSheet(): void {
    if (!this.modalGate.request()) {
      return;
    }
    this.modalShown = true;
  }

  private closeModalSheet(): void {
    this.modalGate.beginClose();
    this.modalShown = false;
  }

  private openInboxSheet(): void {
    if (!this.inboxGate.request()) {
      return;
    }
    this.inboxShown = true;
  }

  private closeInboxSheet(): void {
    this.inboxGate.beginClose();
    this.inboxShown = false;
  }

  @State modalKind: string = '';     // rename / groupNew / groupRename / move
  @State modalText: string = '';
  @State modalChatId: string = '';
  @State modalGroupId: string = '';
  // 审批 Inbox（对齐 RN app/(tabs)/chats.tsx 的 Inbox 卡 + ApprovalInboxSheet）
  @State approvals: ApprovalInfo[] = [];
  @State inboxShown: boolean = false;
  @State chatsLoading: boolean = false;
  @State isDark: boolean = false;
  @State theme: ThemeSnapshot = ThemeManager.get().snapshot();
  // 各按钮按下的编号（0=连接 1=扫码 2=重连 3=断开，-1=无）：一个状态驱动四个按钮的弹性缩放与点光源
  @State pressedBtn: number = -1;
  private btnLatch: PressLatch = new PressLatch();     // 四个按钮共用的按压状态闩
  private conn: QpConnection | null = null;            // 当前连接（loadChats 时同步）
  private themeListener: ThemeListener | null = null;
  private agentListener: (data: emitter.EventData) => void = (_data: emitter.EventData): void => {};
  private chatClosedListener: (data: emitter.EventData) => void = (_data: emitter.EventData): void => {
    // 从会话详情返回：列表重载（最新消息排序/摘要跟随）
    if (!this.connected) {
      return;
    }
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    loadConnection(ctx).then((conn: QpConnection | null) => {
      if (conn !== null) {
        this.loadChats(conn);
      }
    });
  };

  aboutToAppear(): void {
    this.statusText = this.t($r('app.string.cp_status_disconnected'));
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    this.isDark = ctx.config.colorMode === ConfigurationConstant.ColorMode.COLOR_MODE_DARK;
    this.themeListener = (snap: ThemeSnapshot): void => {
      this.theme = snap;
    };
    ThemeManager.get().subscribe(this.themeListener);
    ThemeManager.get().load(ctx).then((): void => {
      this.theme = ThemeManager.get().snapshot();
    });
    loadConnection(ctx).then((conn: QpConnection | null) => {
      if (conn === null) {
        return;
      }
      this.baseUrlInput = conn.baseUrl;
      this.ticketInput = '';
      this.doConnect();
    });
    // 智能体切换后：会话列表按新 agent 重载（X-Agent-Id）
    this.agentListener = (_data: emitter.EventData): void => {
      if (!this.connected) {
        return;
      }
      loadConnection(ctx).then((conn: QpConnection | null) => {
        if (conn !== null) {
          this.loadChats(conn);
        }
      });
    };
    emitter.on(AGENT_CHANGE_EVENT, this.agentListener);
    emitter.on(CHAT_CLOSED_EVENT, this.chatClosedListener);
  }

  aboutToDisappear(): void {
    emitter.off(AGENT_CHANGE_EVENT, this.agentListener);
    emitter.off(CHAT_CLOSED_EVENT, this.chatClosedListener);
    if (this.themeListener !== null) {
      ThemeManager.get().unsubscribe(this.themeListener);
      this.themeListener = null;
    }
  }

  onConfigurationUpdate(newConfig: Configuration): void {
    this.isDark = newConfig.colorMode === ConfigurationConstant.ColorMode.COLOR_MODE_DARK;
  }

  // 沉浸光感生效范围（官方《沉浸光感常见问题》）：仅弹窗类组件/接口与 Slider/Toggle/Select 可全页面生效；
  // 其他组件（含 Button、布局容器）只在 Navigation/NavDestination 标题栏或 barPosition=End 的底部 TabBar
  // 内生效，放内容区会打印 `Material inactive: out of scope` 且材质完全不生效 →
  // 内容区一律用通用属性（玻璃底色 + 圆角 + 缩放 + 点光源）替代材质，官方措施同此。

  // 按钮按压（0=连接 1=扫码 2=重连 3=断开）：缩放动画与点光源由 pressTouch/pressEffect 统一驱动
  private onBtnTouch(idx: number, e: TouchEvent): void {
    pressTouch(this.getUIContext(), e, this.btnLatch, (v: boolean): void => {
      this.pressedBtn = v ? idx : -1;
    });
  }

  // 会话 / 已归档 视图切换（对齐 RN chats.tsx 的 showArchived）
  private toggleArchived(): void {
    this.showArchived = !this.showArchived;
    if (this.conn !== null) {
      this.loadChats(this.conn);
    }
  }

  private async loadChats(conn: QpConnection): Promise<void> {
    this.conn = conn;
    this.chatsLoading = true;
    fetchApprovals(conn.baseUrl, conn.token, conn.agentId).then((list: ApprovalInfo[]): void => {
      this.approvals = list;
    }).catch((): void => {});
    try {
      this.chats = await fetchChats(conn.baseUrl, conn.token, conn.agentId, this.showArchived);
      this.groups = await fetchChatGroups(conn.baseUrl, conn.token, conn.agentId);
    } catch (e) {
      this.chats = [];
    } finally {
      this.chatsLoading = false;
    }
  }

  // 会话卡片 ⋯ 菜单（对齐 RN app/(tabs)/chats.tsx）：
  // 非归档 = 重命名 / 置顶 / 归档 / 删除；已归档 = 恢复 / 永久删除
  private chatMenuOf(c: ChatInfo): MenuElement[] {
    const items: MenuElement[] = [];
    if (this.showArchived) {
      items.push({
        value: $r('app.string.chat_menu_restore'),
        action: (): void => {
          this.chatOp(c, 'unarchive');
        }
      });
      items.push({
        value: $r('app.string.chat_menu_delete_forever'),
        action: (): void => {
          this.confirmDeleteChat(c);
        }
      });
      return items;
    }
    items.push({
      value: $r('app.string.chat_menu_rename'),
      action: (): void => {
        this.openRenameModal(c);
      }
    });
    items.push({
      value: c.pinned ? $r('app.string.chat_menu_unpin') : $r('app.string.chat_menu_pin'),
      action: (): void => {
        this.chatOp(c, c.pinned ? 'unpin' : 'pin');
      }
    });
    items.push({
      value: $r('app.string.chat_menu_move'),
      action: (): void => {
        this.openMoveModal(c);
      }
    });
    items.push({
      value: $r('app.string.chat_menu_archive'),
      action: (): void => {
        this.chatOp(c, 'archive');
      }
    });
    items.push({
      value: $r('app.string.chat_menu_delete'),
      action: (): void => {
        this.confirmDeleteChat(c);
      }
    });
    return items;
  }

  private openRenameModal(c: ChatInfo): void {
    this.modalKind = 'rename';
    this.modalChatId = c.id;
    this.modalText = c.name;
    this.openModalSheet();
  }

  private openGroupEditor(groupId: string): void {
    this.modalKind = groupId.length > 0 ? 'groupRename' : 'groupNew';
    this.modalGroupId = groupId;
    let name: string = '';
    for (const g of this.groups) {
      if (g.id === groupId) {
        name = g.name;
      }
    }
    this.modalText = name;
    this.openModalSheet();
  }

  private openMoveModal(c: ChatInfo): void {
    this.modalKind = 'move';
    this.modalChatId = c.id;
    this.openModalSheet();
  }

  private modalTitleRes(): Resource {
    if (this.modalKind === 'rename') {
      return $r('app.string.chat_rename_title');
    }
    return this.modalKind === 'groupNew'
      ? $r('app.string.chat_group_new') : $r('app.string.chat_group_rename');
  }

  private async submitModal(): Promise<void> {
    if (this.conn === null) {
      return;
    }
    const conn: QpConnection = this.conn;
    const name: string = this.modalText.trim();
    if (name.length === 0) {
      return;
    }
    try {
      if (this.modalKind === 'rename') {
        await renameChat(conn.baseUrl, conn.token, conn.agentId, this.modalChatId, name);
      } else if (this.modalKind === 'groupNew') {
        await createChatGroup(conn.baseUrl, conn.token, conn.agentId, name);
      } else {
        await renameChatGroup(conn.baseUrl, conn.token, conn.agentId, this.modalGroupId, name);
      }
      this.closeModalSheet();
      await this.loadChats(conn);
    } catch (e) {
      this.getUIContext().getPromptAction().showToast({ message: this.t($r('app.string.chat_op_failed')) });
    }
  }

  private async moveSelected(groupId: string): Promise<void> {
    if (this.conn === null) {
      return;
    }
    const conn: QpConnection = this.conn;
    try {
      await moveChatToGroup(conn.baseUrl, conn.token, conn.agentId, this.modalChatId, groupId);
      this.closeModalSheet();
      await this.loadChats(conn);
    } catch (e) {
      this.getUIContext().getPromptAction().showToast({ message: this.t($r('app.string.chat_op_failed')) });
    }
  }

  private groupMenuOf(g: ChatGroup): MenuElement[] {
    const items: MenuElement[] = [];
    items.push({
      value: $r('app.string.chat_group_rename'),
      action: (): void => {
        this.openGroupEditor(g.id);
      }
    });
    items.push({
      value: $r('app.string.chat_group_delete'),
      action: (): void => {
        this.deleteGroup(g);
      }
    });
    return items;
  }

  private async deleteGroup(g: ChatGroup): Promise<void> {
    if (this.conn === null) {
      return;
    }
    const conn: QpConnection = this.conn;
    try {
      await deleteChatGroup(conn.baseUrl, conn.token, conn.agentId, g.id);
      await this.loadChats(conn);
    } catch (e) {
      this.getUIContext().getPromptAction().showToast({ message: this.t($r('app.string.chat_op_failed')) });
    }
  }

  // 统一半模态：输入型（重命名会话 / 新建·重命名分组）或选择型（移动到分组）
  @Builder
  modalSheet() {
    Column() {
      if (this.modalKind === 'move') {
        Text($r('app.string.chat_move_title'))
          .fontSize(UiTokens.fsBody)
          .fontWeight(FontWeight.Bold)
          .margin({ bottom: 8 })
        Column() {
          Text($r('app.string.chats_group_ungrouped'))
            .fontSize(UiTokens.fsBody)
            .fontColor($r('app.color.text_secondary'))
            .width('100%')
            .padding({ top: 12, bottom: 12 })
            .onClick((): void => {
              this.moveSelected('');
            })
          ForEach(this.groups, (g: ChatGroup) => {
            Text(g.name)
              .fontSize(UiTokens.fsBody)
              .fontColor($r('app.color.text_secondary'))
              .width('100%')
              .padding({ top: 12, bottom: 12 })
              .onClick((): void => {
                this.moveSelected(g.id);
              })
          }, (g: ChatGroup) => g.id)
        }
        .width('100%')
      } else {
        Text(this.modalTitleRes())
          .fontSize(UiTokens.fsBody)
          .fontWeight(FontWeight.Bold)
          .margin({ bottom: 12 })
        TextInput({ text: $$this.modalText, placeholder: $r('app.string.chat_rename_placeholder') })
          .height(44)
          .fontSize(UiTokens.fsBody)
          .backgroundColor($r('app.color.card_bg'))
          .fontColor($r('app.color.input_text'))
          .placeholderColor($r('app.color.placeholder'))
          .borderRadius(12)
          .onSubmit((): void => {
            this.submitModal();
          })
        Row() {
          Button($r('app.string.common_cancel'))
            .layoutWeight(1)
            .backgroundColor($r('app.color.card_bg'))
            .fontColor($r('app.color.text_secondary'))
            .onClick((): void => {
              this.closeModalSheet();
            })
          Button($r('app.string.common_confirm'))
            .layoutWeight(1)
            .margin({ left: 10 })
            .backgroundColor(this.isDark ? this.theme.accentDark : this.theme.accent)
            .fontColor(Color.White)
            .onClick((): void => {
              this.submitModal();
            })
        }
        .width('100%')
        .margin({ top: 16 })
      }
    }
    .width('100%')
    // 顶部留出系统关闭叉（✕）与拖拽条的高度
    .padding({ left: 20, right: 20, top: 64 })
  }

  private confirmDeleteChat(c: ChatInfo): void {
    this.getUIContext().showAlertDialog({
      title: $r('app.string.chat_menu_delete_title'),
      message: $r('app.string.chat_menu_delete_msg'),
      primaryButton: {
        value: this.t($r('app.string.common_cancel')),
        action: (): void => {}
      },
      secondaryButton: {
        value: this.t($r('app.string.chat_menu_delete')),
        fontColor: $r('app.color.status_error'),
        action: (): void => {
          this.chatOp(c, 'delete');
        }
      }
    });
  }

  // 会话操作：pin/unpin → PUT /chats/{id}；archive → POST /chats/{id}/archive；delete → DELETE /chats/{id}
  private async chatOp(c: ChatInfo, kind: string): Promise<void> {
    if (this.conn === null) {
      return;
    }
    const conn: QpConnection = this.conn;
    const base: string = `${conn.baseUrl}/api/chats/${encodeURIComponent(c.id)}`;
    try {
      if (kind === 'pin' || kind === 'unpin') {
        const body: ChatPinBody = { pinned: kind === 'pin' };
        await doRequest(base, http.RequestMethod.PUT, JSON.stringify(body),
          conn.token.length > 0 ? conn.token : null, conn.agentId);
      } else if (kind === 'archive') {
        await doRequest(`${base}/archive`, http.RequestMethod.POST, null,
          conn.token.length > 0 ? conn.token : null, conn.agentId);
      } else if (kind === 'unarchive') {
        await doRequest(`${base}/unarchive`, http.RequestMethod.POST, null,
          conn.token.length > 0 ? conn.token : null, conn.agentId);
      } else {
        await doRequest(base, http.RequestMethod.DELETE, null,
          conn.token.length > 0 ? conn.token : null, conn.agentId);
      }
      await this.loadChats(conn);
    } catch (e) {
      this.getUIContext().getPromptAction().showToast({ message: this.t($r('app.string.chat_op_failed')) });
    }
  }

  // 审批：批准（exact/similar）/ 拒绝，成功后本地移除
  private async actApproval(item: ApprovalInfo, scope: string, deny: boolean): Promise<void> {
    if (this.conn === null) {
      return;
    }
    const conn: QpConnection = this.conn;
    try {
      if (deny) {
        await denyRequest(conn.baseUrl, conn.token, conn.agentId, item.requestId, item.rootSessionId,
          'User denied');
      } else {
        await approveRequest(conn.baseUrl, conn.token, conn.agentId, item.requestId, item.rootSessionId,
          scope);
      }
      this.approvals = this.approvals.filter((a: ApprovalInfo): boolean => a.requestId !== item.requestId);
    } catch (e) {
      this.getUIContext().getPromptAction().showToast({ message: this.t($r('app.string.approval_failed')) });
    }
  }

  // 审批 Inbox 弹层（半模态属官方"全页面生效"范围）
  @Builder
  inboxSheet() {
    Column() {
      Text($r('app.string.chats_inbox_title'))
        .fontSize(UiTokens.fsTitle)
        .fontWeight(FontWeight.Bold)
        .margin({ top: 8, bottom: 8 })
      if (this.approvals.length === 0) {
        Text($r('app.string.chats_inbox_empty'))
          .fontSize(UiTokens.fsSecondary)
          .fontColor($r('app.color.text_secondary'))
      }
      ForEach(this.approvals, (a: ApprovalInfo) => {
        ApprovalCard({
          item: a,
          onDeny: (): void => {
            this.actApproval(a, 'exact', true);
          },
          onApprove: (scope: string): void => {
            this.actApproval(a, scope, false);
          }
        })
      }, (a: ApprovalInfo) => a.requestId)
    }
    .width('100%')
    // 顶部留出系统关闭叉（✕）与拖拽条的高度
    .padding({ left: UiTokens.pageHMargin, right: UiTokens.pageHMargin, top: 64 })
    .alignItems(HorizontalAlign.Start)
  }

  // 本地化字符串插值
  private t(res: Resource): string {
    try {
      const host: common.Context = this.getUIContext().getHostContext() as common.Context;
      return host.resourceManager.getStringSync(res.id);
    } catch (e) {
      return '';
    }
  }

  build() {
    Column() {
      Text($r('app.string.cp_title'))
        .fontSize(UiTokens.fsTitle)
        .fontWeight(FontWeight.Bold)
        .margin({ top: 4, bottom: UiTokens.titleGap })

      // 状态卡（只读信息块，无点击动作 → 与工作台连接状态卡同款玻璃块，不加按压反馈）
      Row() {
        Circle()
          .width(10)
          .height(10)
          .fill(this.statusColor)
          .margin({ right: 8 })
        Text(this.statusText)
          .fontSize(14)
          .fontColor(this.statusColor)
          .layoutWeight(1)
      }
      .width('100%')
      .padding(UiTokens.cardPad)
      .borderRadius(UiTokens.cardRadius)
      .backgroundColor($r('app.color.card_glass'))
      .margin({ top: UiTokens.cardVGap, bottom: UiTokens.cardVGap })

      // 审批 Inbox 卡（对齐 RN：有待审批时高亮，点开半模态列表）；弹层挂在外层 Column（bindSheet 只能挂内置组件）
      Column() {
        GlassCard({
          insetH: 0,
          onTap: (): void => {
            this.openInboxSheet();
          }
        }) {
          Row() {
            Text($r('app.string.chats_inbox_title'))
              .fontSize(UiTokens.fsBody)
              .fontWeight(FontWeight.Medium)
              .layoutWeight(1)
            Text(this.approvals.length > 0
              ? `${this.approvals.length} ${this.t($r('app.string.chats_inbox_pending'))}`
              : this.t($r('app.string.chats_inbox_empty')))
              .fontSize(UiTokens.fsCaption)
              .fontColor(this.approvals.length > 0
                ? $r('app.color.status_error') : $r('app.color.text_tertiary'))
          }
          .width('100%')
          .alignItems(VerticalAlign.Center)
        }
      }
      .width('100%')
      .bindSheet(this.inboxShown, this.inboxSheet(),
        moduleSheetOptions(560, this.inboxGate,
          (v: boolean): void => {
            this.inboxShown = v;
          }))

      if (this.connected) {
        Column() {
          this.connectedCard()
          this.chatList()
        }
        .width('100%')
        .bindSheet(this.modalShown, this.modalSheet(),
          moduleSheetOptions(340, this.modalGate,
            (v: boolean): void => {
              this.modalShown = v;
            }))
      } else {
        this.connectForm()
      }
    }
    .width('100%')
    .padding({ left: UiTokens.pageHMargin, right: UiTokens.pageHMargin })
    // 审批 Inbox 弹层（半模态属官方"全页面生效"范围，可上材质）
  }

  @Builder
  connectForm() {
    Column() {
      this.connectFormInner()

      if (this.errorMsg.length > 0) {
        Text(this.errorMsg)
          .fontSize(UiTokens.fsSecondary)
          .fontColor($r('app.color.status_error'))
          .margin({ top: 10 })
          .wordBreak(WordBreak.BREAK_ALL)
      }
    }
    .width('100%')
  }

  @Builder
  connectFormInner() {
    Column() {
      Text($r('app.string.cp_service_url'))
        .fontSize(UiTokens.fsSecondary)
        .fontColor($r('app.color.text_secondary'))
        .margin({ top: 18 })
      TextInput({ text: this.baseUrlInput, placeholder: $r('app.string.cp_url_placeholder') })
        .width('100%')
        .height(44)
        .backgroundColor($r('app.color.card_bg'))
        .fontColor($r('app.color.input_text'))
        .placeholderColor($r('app.color.placeholder'))
        .borderRadius(12)
        .onChange((v: string) => {
          this.baseUrlInput = v;
        })

      Text($r('app.string.cp_ticket'))
        .fontSize(UiTokens.fsSecondary)
        .fontColor($r('app.color.text_secondary'))
        .margin({ top: 14 })
      TextInput({ text: this.ticketInput, placeholder: $r('app.string.cp_ticket_placeholder') })
        .width('100%')
        .height(44)
        .backgroundColor($r('app.color.card_bg'))
        .fontColor($r('app.color.input_text'))
        .placeholderColor($r('app.color.placeholder'))
        .borderRadius(12)
        .onChange((v: string) => {
          this.ticketInput = v;
        })

      Button(this.connecting ? this.t($r('app.string.cp_status_connecting')) : this.t($r('app.string.cp_connect')))
        .width('100%')
        .height(46)
        .margin({ top: 20 })
        .enabled(!this.connecting)
        // 主题色底（内容区材质不生效，官方 FAQ 范围规则）；按压反馈由自绘弹性 + 点光源给出
        .backgroundColor(this.isDark ? this.theme.accentDark : this.theme.accent)
        .fontColor(Color.White)
        // 按压 = 弹性缩放 + 点光源；关掉系统按压态（水波纹），动画由 pressTouch 驱动
        .scale({ x: this.pressedBtn === 0 ? PRESS_SCALE : 1, y: this.pressedBtn === 0 ? PRESS_SCALE : 1 })
        .stateEffect(false)
        .visualEffect(pressEffect(this.pressedBtn === 0))
        .onTouch((e: TouchEvent): void => {
          this.onBtnTouch(0, e);
        })
        .onClick(() => {
          this.doConnect();
        })

      Button($r('app.string.cp_scan'))
        .width('100%')
        .height(42)
        .margin({ top: 10 })
        .enabled(!this.connecting)
        // 玻璃底（内容区材质不生效，官方 FAQ 范围规则）
        .backgroundColor($r('app.color.card_glass'))
        .fontColor($r('app.color.btn_gray_text'))
        .scale({ x: this.pressedBtn === 1 ? PRESS_SCALE : 1, y: this.pressedBtn === 1 ? PRESS_SCALE : 1 })
        .stateEffect(false)
        .visualEffect(pressEffect(this.pressedBtn === 1))
        .onTouch((e: TouchEvent): void => {
          this.onBtnTouch(1, e);
        })
        .onClick(() => {
          this.doScan();
        })

      Text($r('app.string.cp_hint'))
        .fontSize(UiTokens.fsCaption)
        .fontColor($r('app.color.text_tertiary'))
        .margin({ top: 14 })
        .lineHeight(18)
    }
    .width('100%')
  }

  @Builder
  connectedCard() {
    Column() {
      Row() {
        Text(this.connHost)
          .fontSize(15)
          .fontWeight(FontWeight.Medium)
          .layoutWeight(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
        Text(this.connMode)
          .fontSize(11)
          .fontColor($r('app.color.status_success'))
          .backgroundColor($r('app.color.success_bg'))
          .borderRadius(8)
          .padding({ left: 8, right: 8, top: 2, bottom: 2 })
      }
      .width('100%')

      if (this.connUser.length > 0) {
        Text(`${this.t($r('app.string.cp_user'))}：${this.connUser}`)
          .fontSize(13)
          .fontColor($r('app.color.text_secondary'))
          .margin({ top: 6 })
      }

      if (this.agentNames.length > 0) {
        Text(`${this.t($r('app.string.cp_agents'))}（${this.agentNames.length}）`)
          .fontSize(13)
          .fontColor($r('app.color.text_secondary'))
          .margin({ top: 10 })
        Text(this.agentNames.join('、'))
          .fontSize(14)
          .margin({ top: 4 })
          .wordBreak(WordBreak.BREAK_ALL)
      }

      Row() {
        Button($r('app.string.cp_reconnect'))
          .layoutWeight(1)
          .height(42)
          // 玻璃底（内容区材质不生效，官方 FAQ 范围规则）
          .backgroundColor($r('app.color.card_glass'))
          .fontColor($r('app.color.btn_gray_text'))
          .enabled(!this.connecting)
          .margin({ right: 8 })
          .scale({ x: this.pressedBtn === 2 ? PRESS_SCALE : 1, y: this.pressedBtn === 2 ? PRESS_SCALE : 1 })
          .stateEffect(false)
          .visualEffect(pressEffect(this.pressedBtn === 2))
          .onTouch((e: TouchEvent): void => {
            this.onBtnTouch(2, e);
          })
          .onClick(() => {
            this.doConnect();
          })
        Button($r('app.string.cp_disconnect'))
          .layoutWeight(1)
          .height(42)
          // 半透明玻璃底（内容区材质不生效，故显式给底色）；红色语义由 fontColor（status_error）承载
          .backgroundColor($r('app.color.card_glass'))
          .fontColor($r('app.color.status_error'))
          .enabled(!this.connecting)
          .margin({ left: 8 })
          .scale({ x: this.pressedBtn === 3 ? PRESS_SCALE : 1, y: this.pressedBtn === 3 ? PRESS_SCALE : 1 })
          .stateEffect(false)
          .visualEffect(pressEffect(this.pressedBtn === 3))
          .onTouch((e: TouchEvent): void => {
            this.onBtnTouch(3, e);
          })
          .onClick(() => {
            this.doDisconnect();
          })
      }
      .width('100%')
      .margin({ top: 16 })
    }
    .width('100%')
    .padding(16)
    .borderRadius(UiTokens.cardRadius)
    .backgroundColor($r('app.color.card_bg'))
    .margin({ top: UiTokens.cardVGap })
  }

  @Builder
  chatList() {
    if (this.chatsLoading && this.chats.length === 0) {
      Text($r('app.string.cp_chats_loading'))
        .fontSize(UiTokens.fsSecondary)
        .fontColor($r('app.color.text_tertiary'))
        .margin({ top: UiTokens.cardVGap })
    } else if (this.chats.length === 0) {
      Text($r('app.string.cp_chats_empty'))
        .fontSize(UiTokens.fsSecondary)
        .fontColor($r('app.color.text_tertiary'))
        .margin({ top: UiTokens.cardVGap })
    } else {
      Column() {
        Text($r('app.string.cp_chats_title'))
          .fontSize(UiTokens.fsCaption)
          .fontColor($r('app.color.text_tertiary'))
          .margin({ top: UiTokens.titleGap, bottom: 2 })
        Row() {
          Text($r('app.string.chats_tab_active'))
            .fontSize(UiTokens.fsSecondary)
            .fontWeight(this.showArchived ? FontWeight.Normal : FontWeight.Bold)
            .fontColor(this.showArchived ? $r('app.color.text_tertiary') : $r('app.color.text_secondary'))
            .onClick((): void => {
              if (this.showArchived) {
                this.toggleArchived();
              }
            })
          Text($r('app.string.chats_tab_archived'))
            .fontSize(UiTokens.fsSecondary)
            .fontWeight(this.showArchived ? FontWeight.Bold : FontWeight.Normal)
            .fontColor(this.showArchived ? $r('app.color.text_secondary') : $r('app.color.text_tertiary'))
            .margin({ left: 16 })
            .onClick((): void => {
              if (!this.showArchived) {
                this.toggleArchived();
              }
            })
          Blank()
          if (!this.showArchived) {
            Text($r('app.string.chats_group_new'))
              .fontSize(UiTokens.fsCaption)
              .fontColor(this.isDark ? this.theme.accentDark : this.theme.accent)
              .onClick((): void => {
                this.openGroupEditor('');
              })
          }
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)
        .margin({ top: UiTokens.titleGap, bottom: 2 })

        ForEach(buildChatSections(this.chats, this.groups), (sec: ChatSection) => {
          this.sectionBlock(sec)
        }, (sec: ChatSection) => sec.key)
      }
      .width('100%')
      .padding({ bottom: 32 })
    }
  }

  // 单个分区（对齐 RN chats.tsx SectionList：header + 会话行）
  @Builder
  sectionBlock(sec: ChatSection) {
    Column() {
      Row() {
        if (sec.pinned) {
          Text('📌')
            .fontSize(UiTokens.fsChip)
            .margin({ right: 4 })
        }
        Text(sec.title)
          .fontSize(UiTokens.fsCaption)
          .fontWeight(FontWeight.Medium)
          .fontColor($r('app.color.text_tertiary'))
        Text(sec.chats.length.toString())
          .fontSize(UiTokens.fsCaption)
          .fontColor($r('app.color.text_tertiary'))
          .margin({ left: 6 })
        if (sec.chats.length === 0) {
          Text($r('app.string.chats_group_empty'))
            .fontSize(UiTokens.fsChip)
            .fontColor($r('app.color.text_tertiary'))
            .margin({ left: 6 })
        }
        Blank()
        if (sec.group !== null && sec.group.kind === 'custom') {
          Button() {
            Text('⋯')
              .fontSize(18)
              .fontColor($r('app.color.text_tertiary'))
          }
          .type(ButtonType.Normal)
          .width(32)
          .height(32)
          .padding(0)
          .backgroundColor(Color.Transparent)
          .bindMenu(this.groupMenuOf(sec.group))
        }
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)
      .margin({ top: 14, bottom: 2 })

      ForEach(sec.chats, (c: ChatInfo) => {
        ChatRow({
          chat: c,
          menu: this.chatMenuOf(c),
          onOpen: (): void => {
            const param: ChatRouteParam = { chatId: c.id, chatName: c.name, sessionId: c.sessionId };
            this.navStack.pushPath({ name: 'chat', param: param });
          }
        })
      }, (c: ChatInfo) => c.id)
    }
    .width('100%')
  }

  private async doConnect(): Promise<void> {
    if (this.connecting) {
      return;
    }
    this.errorMsg = '';
    let rawUrl: string = this.baseUrlInput.trim();
    let rawTicket: string = this.ticketInput.trim();
    try {
      // 支持整串粘贴配对码
      if (rawUrl.startsWith('qwenpaw://')) {
        const pairing = parsePairingUri(rawUrl);
        rawUrl = pairing.baseUrl;
        rawTicket = pairing.ticket;
        this.ticketInput = rawTicket;
      }
      const parsed = parseManualInput(rawUrl, rawTicket);
      rawUrl = parsed.baseUrl;
      rawTicket = parsed.ticket;
      this.baseUrlInput = rawUrl;

      this.connecting = true;
      this.statusText = this.t($r('app.string.cp_status_connecting'));
      this.statusColor = $r('app.color.status_warning');

      const outcome = await connectToQwenPaw(rawUrl, rawTicket);
      const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
      await saveConnection(ctx, outcome.connection);

      this.connected = true;
      this.connHost = hostOf(outcome.connection.baseUrl);
      this.connUser = outcome.connection.username;
      this.connMode = outcome.openMode ? this.t($r('app.string.cp_mode_open')) : this.t($r('app.string.cp_mode_paired'));
      this.agentNames = outcome.agentNames;
      this.statusText = `${this.t($r('app.string.cp_status_connected'))} · ${outcome.agentCount}${this.t($r('app.string.cp_agents_unit'))}`;
      this.statusColor = $r('app.color.status_success');
      emitter.emit(CONN_CHANGE_EVENT);
      this.loadChats(outcome.connection);
    } catch (e) {
      const err: Error = e as Error;
      this.connected = false;
      this.statusText = this.t($r('app.string.cp_status_failed'));
      this.statusColor = $r('app.color.status_error');
      this.errorMsg = describeConnectError(rawUrl, err);
    } finally {
      this.connecting = false;
    }
  }

  private doDisconnect(): void {
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    clearConnection(ctx).then(() => {
      this.connected = false;
      this.connUser = '';
      this.connMode = '';
      this.agentNames = [];
      this.chats = [];
      this.statusText = this.t($r('app.string.cp_status_disconnected'));
      this.statusColor = $r('app.color.status_idle');
      emitter.emit(CONN_CHANGE_EVENT);
    });
  }

  private doScan(): void {
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    const atManager: abilityAccessCtrl.AtManager = abilityAccessCtrl.createAtManager();
    const permissions: Permissions[] = ['ohos.permission.CAMERA'];
    atManager.requestPermissionsFromUser(ctx, permissions).then((result) => {
      const granted: boolean = result.authResults.every((r: number) => r === 0);
      if (!granted) {
        this.errorMsg = this.t($r('app.string.cp_err_no_camera'));
        return;
      }
      this.startScan();
    }).catch(() => {
      this.errorMsg = this.t($r('app.string.cp_err_no_camera'));
    });
  }

  private startScan(): void {
    scanBarcode.startScan({
      scanTypes: [scanCore.ScanType.QR_CODE],
      enableMultiMode: true
    }).then((result: scanBarcode.ScanResult) => {
      try {
        const pairing = parsePairingUri(result.originalValue);
        this.baseUrlInput = pairing.baseUrl;
        this.ticketInput = pairing.ticket;
        this.errorMsg = '';
        this.doConnect();
      } catch (e) {
        this.errorMsg = `${this.t($r('app.string.cp_err_scan_invalid'))}：${String((e as Error).message)}`;
      }
    }).catch(() => {
      this.errorMsg = this.t($r('app.string.cp_err_scan_cancel'));
    });
  }
}

// 会话行卡（点按 = 打开会话详情）：卡片壳统一走 GlassCard
@Component
export struct ChatRow {
  chat: ChatInfo = { id: '', sessionId: '', name: '', updatedAtMs: 0, pinned: false, groupId: '' };
  menu: MenuElement[] = [];
  onOpen: () => void = (): void => {};

  build() {
    GlassCard({
      // 本页容器已给 16vp 水平留白 → 卡片不再叠加，保证三页卡片边界一致（x=56..1260）
      insetH: 0,
      onTap: (): void => {
        this.onOpen();
      }
    }) {
      Row() {
      Text(this.chat.name)
        .fontSize(UiTokens.fsBody)
        .fontWeight(FontWeight.Medium)
        .layoutWeight(1)
        .maxLines(1)
        .textOverflow({ overflow: TextOverflow.Ellipsis })
      if (this.chat.pinned) {
        Text($r('app.string.cp_chat_pinned'))
          .fontSize(UiTokens.fsChip)
          .fontColor($r('app.color.text_secondary'))
          .backgroundColor($r('app.color.card_bg'))
          .borderRadius(UiTokens.chipRadius)
          .padding({ left: 6, right: 6, top: 2, bottom: 2 })
          .margin({ right: 8 })
      }
        Text(relativeTime(this.chat.updatedAtMs))
          .fontSize(UiTokens.fsCaption)
          .fontColor($r('app.color.text_tertiary'))
        Button() {
          Text('⋯')
            .fontSize(18)
            .fontColor($r('app.color.text_tertiary'))
        }
        .type(ButtonType.Normal)
        .width(32)
        .height(32)
        .padding(0)
        .backgroundColor(Color.Transparent)
        .margin({ left: 4 })
        .bindMenu(this.menu)
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)
    }
  }
}

// ============ 会话分区（对齐 PR #7378 features/chats/grouping.ts buildChatSections）============
interface ChatSection {
  key: string;
  title: ResourceStr;
  chats: ChatInfo[];
  pinned: boolean;
  group: ChatGroup | null;
}

function groupTitleOf(g: ChatGroup): ResourceStr {
  if (g.kind === 'default') {
    return $r('app.string.chats_group_ungrouped');
  }
  if (g.kind === 'cron') {
    return $r('app.string.chats_group_cron');
  }
  if (g.kind === 'subagents') {
    return $r('app.string.chats_group_subagents');
  }
  return g.name;
}

function buildChatSections(chats: ChatInfo[], groups: ChatGroup[]): ChatSection[] {
  const pinned: ChatInfo[] = chats.filter((c: ChatInfo): boolean => c.pinned);
  const remaining: ChatInfo[] = chats.filter((c: ChatInfo): boolean => !c.pinned);
  const sections: ChatSection[] = [];
  if (pinned.length > 0) {
    sections.push({
      key: 'pinned', title: $r('app.string.chats_group_pinned'),
      chats: pinned, pinned: true, group: null
    });
  }
  const ordered: ChatGroup[] = groups.slice().sort((a: ChatGroup, b: ChatGroup): number => a.order - b.order);
  const knownIds: string[] = [];
  let hasDefault: boolean = false;
  for (const g of ordered) {
    knownIds.push(g.id);
    if (g.kind === 'default') {
      hasDefault = true;
    }
    const data: ChatInfo[] = remaining.filter((c: ChatInfo): boolean =>
      g.kind === 'default' ? (c.groupId.length === 0 || c.groupId === g.id) : c.groupId === g.id);
    sections.push({ key: g.id, title: groupTitleOf(g), chats: data, pinned: false, group: g });
  }
  const ungrouped: ChatInfo[] = remaining.filter((c: ChatInfo): boolean =>
    (c.groupId.length === 0 && !hasDefault) || (c.groupId.length > 0 && knownIds.indexOf(c.groupId) < 0));
  if (ungrouped.length > 0 || !hasDefault) {
    sections.push({
      key: 'ungrouped', title: $r('app.string.chats_group_ungrouped'),
      chats: ungrouped, pinned: false, group: null
    });
  }
  return sections;
}
