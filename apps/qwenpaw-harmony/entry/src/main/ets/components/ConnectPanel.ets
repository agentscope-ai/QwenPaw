/*
 * 连接面板 —— 会话 tab 主体（一期）。
 * 形态对齐 PR #7378：扫码/手输配对码 → redeem → verify → 持久化（preferences）。
 * 状态机：disconnected / connecting / connected / failed。
 */

import { common } from '@kit.AbilityKit';
import { uiMaterial } from '@kit.ArkUI';

import { GlassCard } from './GlassCard';
import { SegmentedControl } from './SegmentedControl';
import { SheetGate, moduleSheetOptions } from './SheetGate';
import { WorkspaceBadge } from './WorkspaceSwitcher';
import { HubRow } from './WorkbenchTab';

import { emitter } from '@kit.BasicServicesKit';
import { QpConnection, loadConnection, saveConnection } from '../services/ConnectionStore';
import { swapRoute, topRouteIs } from '../services/NavPush';
import {
  ChatActivityRecord, loadActivity, saveActivity, reconcileActivity, markActivityRead, resolveActivity
} from '../services/ChatActivity';
import {
  connectToQwenPaw, describeConnectError, verifyConnection, ConnectOutcome
} from '../services/ConnectionService';
import { parsePairingUri, parseManualInput } from '../services/PairingModel';
import { ScanRouteParam } from '../services/AppEvents';
import {
  fetchChats, ChatInfo, relativeTime, renameChat, ChatGroup, fetchChatGroups,
  createChatGroup, renameChatGroup, deleteChatGroup, moveChatToGroup, createChat,
  pinChat, setChatArchived, deleteChat
} from '../services/ChatsService';
import { ChatRouteParam, CHAT_CLOSED_EVENT } from '../services/ChatDetailService';
import { LastChat, saveLastChat, loadLastChat, clearLastChat } from '../services/LastChat';
import { AGENT_CHANGE_EVENT } from '../services/AgentsService';
import { CONN_STORE_EVENT } from '../services/AppEvents';
import { CONN_LIVENESS_EVENT, lastLiveness } from '../services/LivenessService';
import { ThemeManager, ThemeSnapshot, ThemeListener } from '../theme/ThemeManager';
import { UiTokens } from '../theme/UiTokens';
import { PRESS_SCALE, PressLatch, pressEffect, pressTouch } from '../theme/PressFx';
import { ApprovalInfo, fetchApprovals, approveRequest, denyRequest } from '../services/ApprovalsService';
import { ApprovalCard } from './ApprovalCard';
import { menuOptions } from '../theme/MenuMaterial';
import { t } from '../services/I18n';

// 会话 / 已归档 连排按钮几何：参考社区页第一排（一个大框 + 框内滑块跑过去），但取小号
// （社区 SEG_H = 32 + 上下各 4 内边距；这里 26 + 各 3，见 components/SegmentedControl.ets）
const SWITCH_H: number = 26;
const SWITCH_W: number = 170;

// 会话卡片行数据（行组件与数据一一对应）：轮询快照到达时按字段 upsert 到既有 VM，
// 而不是整体替换行持有的 ChatInfo——行组件（ForEach 键 = chat.id）得以保留，
// 运行脉冲的无限动画/按压状态不丢失，滚动中不产生整分区布局 pass
@Observed
export class ChatRowVM {
  chat: ChatInfo;
  activity: string;

  constructor(chat: ChatInfo, activity: string) {
    this.chat = chat;
    this.activity = activity;
  }
}

// 卡片行实际渲染依赖的字段（名称/相对时间/置顶）+ 驱动 activity 的 status：
// 全同则跳过赋值，避免无效的观察通知（轮询快照里大部分行每轮都不变）
function chatRowFieldsEqual(a: ChatInfo, b: ChatInfo): boolean {
  return a.name === b.name && a.updatedAtMs === b.updatedAtMs
    && a.pinned === b.pinned && a.status === b.status;
}

@Component
export struct ConnectPanel {
  navStack: NavPathStack = new NavPathStack();
  @State connected: boolean = false;
  @State connecting: boolean = false;
  @State statusText: string = '';
  // 服务端真实可达（LivenessService 广播）：已配对但断网时状态卡必须显示「未连接」
  @State online: boolean = false;
  @State errorMsg: string = '';
  @State baseUrlInput: string = '';
  @State ticketInput: string = '';
  @State connUser: string = '';
  @State agentNames: string[] = [];
  // 与 agentNames 一一对应的智能体 id（回显当前选中项用）
  @State agentIds: string[] = [];
  // 会话活动态记录（对齐 7378 chatActivityModel：running 看服务端 status，unread 由本地记录推导）
  @State activityMap: Map<string, ChatActivityRecord> = new Map<string, ChatActivityRecord>();
  // 工作区徽章重取信号（切换/取消配对后自增）
  @State wsToken: number = 0;
  @State chats: ChatInfo[] = [];
  // 会话行 VM 注册表（键 = chat.id）：行组件 @ObjectLink 的唯一数据源，
  // 每次快照/变更落地时由 upsertChatVMs 维护（成员增删 + 字段级 upsert + 清 stale）
  private chatVMs: Map<string, ChatRowVM> = new Map();
  @State showArchived: boolean = false;
  // 会话 / 已归档 连排按钮与弹层操作键的沉浸材质：内容区只有 Toggle(ToggleType.Button) 外壳能生效
  // （官方豁免名单 = 弹窗类 / Slider / Toggle / Select），故只建一次复用
  private switcherMaterial: SystemUiMaterial = new uiMaterial.ImmersiveMaterial({
    style: uiMaterial.ImmersiveStyle.THIN,
    interactive: true,
    lightEffect: {}
  });
  // 会话搜索关键词（对齐 7378 chats.tsx 的 query）与“新建会话”进行中态
  // 搜索词由标题栏工具条（SearchPill）持有并单向同步进来（变更即过滤；页内搜索条已移除）
  @Prop query: string = '';
  // 当前前台底部页签（0=会话）：会话列表只在会话页处于前台时轮询（对齐 7378 useFocusEffect 作用域）
  @Prop @Watch('onTabActive') activeTab: number = 0;
  // 窗宽 ≥ 断点 lg 且横排（= 会走分栏的形态）：由 Index 依据根容器实测尺寸传入。
  // 用于「切回会话页恢复上次会话」的形态判定（仅平板/电脑横屏需要）
  @Prop @Watch('onWideLandscapeChanged') wideLandscape: boolean = false;
  @State creating: boolean = false;
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

  @State modalKind: string = '';     // rename / groupNew / groupRename / move
  @State modalText: string = '';
  @State modalChatId: string = '';
  @State modalGroupId: string = '';
  // 审批 Inbox（对齐 RN app/(tabs)/chats.tsx 的 Inbox 卡 + ApprovalInboxSheet）
  @State approvals: ApprovalInfo[] = [];
  @State inboxShown: boolean = false;
  @State chatsLoading: boolean = false;
  // 列表展开动画的驱动位：取数期间为假（只显示转圈），数据到位后在 animateTo 里置真，
  // 由透明度 + 位移两条属性补间出「展开」观感（属性动画由状态驱动，不依赖 transition 触发时机）
  @State listRevealed: boolean = false;
  @StorageLink('appIsDark') isDark: boolean = false;
  @State theme: ThemeSnapshot = ThemeManager.get().snapshot();
  // 各按钮按下的编号（0=连接 1=扫码 2=重连 3=断开，-1=无）：一个状态驱动四个按钮的弹性缩放与点光源
  @State pressedBtn: number = -1;
  private btnLatch: PressLatch = new PressLatch();     // 四个按钮共用的按压状态闩
  private conn: QpConnection | null = null;            // 当前连接（loadChats 时同步）
  private themeListener: ThemeListener | null = null;
  private agentListener: (data: emitter.EventData) => void = (_data: emitter.EventData): void => {};
  private liveListener: (data: emitter.EventData) => void = (_data: emitter.EventData): void => {};
  private chatClosedListener: (data: emitter.EventData) => void = (_data: emitter.EventData): void => {
    // 从会话详情返回：只做静默对齐（最新消息排序/摘要/新卡片跟随），不重放展开补间。
    // 此前这里走 loadChats（整列表淡入 + 下移），于是每次退出会话，列表都要"刷一下"。
    if (!this.connected) {
      return;
    }
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    loadConnection(ctx).then((conn: QpConnection | null) => {
      if (conn !== null) {
        this.conn = conn;
        this.pollRefreshChats();
      }
    });
  };

  // 列表内容落地：静默替换；只有"确有新卡片到场"时才重放一次展开补间
  //（返回会话页不该整列表刷一下——新卡片才显示刷新动画）。
  private applyChats(list: ChatInfo[], animateNew: boolean): void {
    const prev: string[] = this.chats.map((c: ChatInfo): string => c.id);
    let fresh: boolean = false;
    if (animateNew) {
      for (const c of list) {
        if (prev.indexOf(c.id) < 0) {
          fresh = true;
          break;
        }
      }
    }
    // 先 upsert VM（行数据），再换数组（成员变化才真正重建行）：两步同帧落地，
    // 避免新行先以旧 VM 闪现
    this.upsertChatVMs(list);
    this.chats = list;
    if (fresh) {
      this.listRevealed = false;
      this.revealList();
    }
  }

  // 连接存储在别处被改写（设置页切换/移除/断开/重连）：重取当前连接并复核
  private connStoreListener: (data: emitter.EventData) => void = (_data: emitter.EventData): void => {
    this.reloadAfterSwitch();
  };

  // 工作区切换 / 取消配对 / 扫码配对回跳后：重取当前连接并复核（徽章回调）
  private async reloadAfterSwitch(): Promise<void> {
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    const conn: QpConnection | null = await loadConnection(ctx);
    this.wsToken++;
    if (conn === null) {
      this.connected = false;
      this.chatVMs.clear();
      this.chats = [];
      this.agentNames = [];
      this.statusText = t($r('app.string.cp_status_disconnected'));
      return;
    }
    this.baseUrlInput = conn.baseUrl;
    this.ticketInput = '';
    // 已落盘连接直接复核（含 token，不重新兑换配对码）
    await this.applyStoredConnection(conn);
  }

  // 扫码配对页（路由 scan）：配对成功后由该页落盘连接，回到本页用 onPop 刷新
  private openScan(): void {
    if (topRouteIs(this.navStack, 'scan')) {
      return;
    }
    const param: ScanRouteParam = { stack: this.navStack };
    this.navStack.pushPathByName('scan', param, (_info: PopInfo): void => {
      this.reloadAfterSwitch();
    });
  }

  // 落盘连接复核：票据校验 + 智能体探测（旧实现回落成"空配对码重连"，开账号体系的服务必然失败）
  private async applyStoredConnection(conn: QpConnection): Promise<void> {
    if (this.connecting) {
      return;
    }
    this.connecting = true;
    this.errorMsg = '';
    this.statusText = t($r('app.string.cp_status_connecting'));
    try {
      const outcome: ConnectOutcome = await verifyConnection(conn);
      this.applyOutcome(outcome);
    } catch (e) {
      const err: Error = e as Error;
      this.connected = false;
      this.statusText = t($r('app.string.cp_status_failed'));
      this.errorMsg = describeConnectError(conn.baseUrl, err);
    } finally {
      this.connecting = false;
    }
  }

  // 状态文案唯一出口：已配对（connected）+ 服务端可达（online）才显示「已连接 · N 个智能体」，
  // 否则显示「未连接」；连接过程/失败文案仍由各自调用点覆盖
  private refreshStatusText(): void {
    if (!this.connected) {
      return;
    }
    this.statusText = this.online
      ? `${t($r('app.string.cp_status_connected'))} · ${this.agentIds.length}${t($r('app.string.cp_agents_unit'))}`
      : t($r('app.string.cp_status_disconnected'));
  }

  // 连接成功后的统一收口（手输/扫码配对与已落盘复核共用）
  private applyOutcome(outcome: ConnectOutcome): void {
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    // 连接变化广播由 ConnectionStore 统一发出（保存即广播），这里不再重复发一条
    saveConnection(ctx, outcome.connection);
    this.connected = true;
    this.connUser = outcome.connection.username;
    this.agentNames = outcome.agentNames;
    this.agentIds = outcome.agentIds;
    this.refreshStatusText();
    this.loadChats(outcome.connection);
  }

  aboutToAppear(): void {
    this.statusText = t($r('app.string.cp_status_disconnected'));
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
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
    emitter.on(CONN_STORE_EVENT, this.connStoreListener);
    this.liveListener = (_data: emitter.EventData): void => {
      this.online = lastLiveness().online;
      this.refreshStatusText();
    };
    emitter.on(CONN_LIVENESS_EVENT, this.liveListener);
    this.online = lastLiveness().online;
  }

  aboutToDisappear(): void {
    this.stopChatPoll();
    emitter.off(AGENT_CHANGE_EVENT, this.agentListener);
    emitter.off(CHAT_CLOSED_EVENT, this.chatClosedListener);
    emitter.off(CONN_STORE_EVENT, this.connStoreListener);
    emitter.off(CONN_LIVENESS_EVENT, this.liveListener);
    if (this.themeListener !== null) {
      ThemeManager.get().unsubscribe(this.themeListener);
      this.themeListener = null;
    }
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

  private setArchived(want: boolean): void {
    if (want === this.showArchived) {
      return;
    }
    this.showArchived = want;
    if (this.conn !== null) {
      this.loadChats(this.conn);
    }
  }

  // 当前智能体名首字（口径同 AgentsTab.initialOf：取首字符大写）
  // 当前智能体显示名（选中的那一个，不是列表首个）——徽章与头像首字共用
  private currentAgentName(): string {
    const id: string = this.conn !== null ? this.conn.agentId : '';
    const i: number = this.agentIds.indexOf(id);
    if (i >= 0 && i < this.agentNames.length) {
      return this.agentNames[i];
    }
    return id.length > 0 ? id : this.connUser;
  }

  private agentInitial(): string {
    const n: string = this.currentAgentName();
    return n.length > 0 ? n.substring(0, 1).toUpperCase() : '';
  }

  private connKeyOf(): string {
    return this.conn !== null ? this.conn.baseUrl.toLowerCase() : '';
  }

  private agentKeyOf(): string {
    return this.conn !== null ? this.conn.agentId : '';
  }

  // 用服务端会话列表校正本地记录并持久化（对齐 7378 reconcileChatActivity）
  private async syncActivity(): Promise<void> {
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    const first: Map<string, ChatActivityRecord> = await loadActivity(ctx);
    this.activityMap = reconcileActivity(first, this.connKeyOf(), this.agentKeyOf(), this.chats);
    await saveActivity(ctx, this.activityMap);
    // activityMap 刷新后回写各行 activity（轮询时序：快照落地在前、活动态对账在后，
    // 行数据不靠整表替换刷新，必须显式走一遍）
    this.applyActivities();
  }

  // 行内活动态：read 归入 idle（7378 resolveChatActivity 四值里 read 与 idle 同档观感）
  private activityOf(chat: ChatInfo): string {
    const a: string = resolveActivity(this.connKeyOf(), this.agentKeyOf(), chat, this.activityMap);
    return a === 'read' ? 'idle' : a;
  }

  // 取行的 VM（无则建）：行组件 @ObjectLink 持有的是注册表里的同一引用，
  // 后续字段 upsert 直接触达已建行的渲染
  private vmOf(c: ChatInfo): ChatRowVM {
    let vm: ChatRowVM | undefined = this.chatVMs.get(c.id);
    if (vm === undefined) {
      vm = new ChatRowVM(c, this.activityOf(c));
      this.chatVMs.set(c.id, vm);
    }
    return vm;
  }

  // 分区内的行 VM 序列（供 ForEach 直接迭代；每次都是注册表里的同一批引用）
  private sectionVMsOf(sec: ChatSection): ChatRowVM[] {
    const out: ChatRowVM[] = [];
    for (const c of sec.chats) {
      out.push(this.vmOf(c));
    }
    return out;
  }

  // 快照落地 → 逐 VM upsert：新会话建行、既有行只写真正变化的字段
  //（@ObjectLink 观察 → 仅该行局部刷新，组件不重建）、不再存在的会话清 VM 防泄漏。
  // 这是「4s 轮询不再整分区重建」的核心：行组件与动画状态跨轮次保留。
  private upsertChatVMs(list: ChatInfo[]): void {
    const alive: Set<string> = new Set<string>();
    for (const c of list) {
      alive.add(c.id);
      const vm: ChatRowVM | undefined = this.chatVMs.get(c.id);
      if (vm === undefined) {
        this.chatVMs.set(c.id, new ChatRowVM(c, this.activityOf(c)));
        continue;
      }
      if (!chatRowFieldsEqual(vm.chat, c)) {
        vm.chat = c;
      }
      const a: string = this.activityOf(c);
      if (vm.activity !== a) {
        vm.activity = a;
      }
    }
    const stale: string[] = [];
    this.chatVMs.forEach((_vm: ChatRowVM, key: string): void => {
      if (!alive.has(key)) {
        stale.push(key);
      }
    });
    for (const key of stale) {
      this.chatVMs.delete(key);
    }
  }

  // 活动态对账完成后回写各行 activity（只写变化行，见 syncActivity 末尾调用）
  private applyActivities(): void {
    this.chatVMs.forEach((vm: ChatRowVM): void => {
      const a: string = this.activityOf(vm.chat);
      if (vm.activity !== a) {
        vm.activity = a;
      }
    });
  }

  // ForEach 行键 = chat.id（结构键）：行数据经 ChatRowVM @ObjectLink 交付，
  // 键不再拼行字段——否则每次轮询（时间戳/状态变化）全行键变 → 行组件全重建，
  // 脉冲无限动画重启、按压状态丢失、滚动中多一轮整列表布局 pass（划动掉帧主因之一）
  private chatKeyOf(c: ChatInfo): string {
    return c.id;
  }

  // 分区键 = 仅「分区 + 区内有序 id 串 + 过滤/主题视图位 + 分组指纹」：
  // 轮询快照只改行字段（名称/时间/状态/activity）时分区键不变 → 分区子树与行组件保留；
  // 只有成员增删、排序、搜索/归档/主题、分组结构真正变化才重建分区
  private sectionKeyOf(sec: ChatSection): string {
    const ids: string[] = sec.chats.map((c: ChatInfo): string => c.id);
    const groupsFingerprint: string =
      this.groups.map((g: ChatGroup): string => `${g.id}:${g.name}`).join(';');
    const view: string =
      `${this.showArchived ? 1 : 0}|${this.isDark ? 1 : 0}|${this.agentInitial().replace(/\s+/g, '').slice(0, 1)}`;
    return `${sec.key}|${ids.join(',')}|${this.query}|${view}|${groupsFingerprint}`;
  }

  // 进入会话：清 unread（对齐 7378 markActivityRead）
  private async markRead(chat: ChatInfo): Promise<void> {
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    this.activityMap = markActivityRead(this.activityMap, this.connKeyOf(), this.agentKeyOf(), chat, true);
    await saveActivity(ctx, this.activityMap);
    // 行数据不经整表刷新：unread 清掉后立即回写该行 VM（不等下一轮轮询对账）
    this.applyActivities();
  }

  private chatPollTimer: number = -1;
  private chatPollBusy: boolean = false;

  // 会话列表定时静默刷新（对齐 7378 (tabs)/chats.tsx 的 useFocusEffect + setInterval(poll, 4000)）：
  // 只在会话页处于前台时轮询，切走即停；失败静默保留原列表。
  private onTabActive(): void {
    if (this.activeTab === 0) {
      this.startChatPoll();
      // 从别的页面切回来：恢复上次打开的会话（本页没有已打开会话时）。
      // 只在"平板/电脑横屏（分栏）"下做——那时右栏空着，恢复上次会话才有意义；
      // 竖屏/手机是整页推入式，切回列表就该停在列表。
      if (this.wideLandscape) {
        this.maybeReopenLastChat();
      }
    } else {
      this.stopChatPoll();
    }
  }

  // 横竖屏切换：转为宽屏横排（分栏出现、右栏空着）时同样补一次恢复
  private onWideLandscapeChanged(): void {
    if (this.wideLandscape && this.activeTab === 0) {
      this.maybeReopenLastChat();
    }
  }

  private startChatPoll(): void {
    if (this.chatPollTimer >= 0 || this.conn === null) {
      return;
    }
    this.chatPollTimer = setInterval((): void => {
      this.pollRefreshChats();
    }, 4000);
  }

  private stopChatPoll(): void {
    if (this.chatPollTimer >= 0) {
      clearInterval(this.chatPollTimer);
      this.chatPollTimer = -1;
    }
  }

  // 静默刷新：不置 chatsLoading（避免闪烁）；顺带刷新待审批（与 RN poll 同两项）
  private async pollRefreshChats(): Promise<void> {
    if (this.chatPollBusy || this.conn === null) {
      return;
    }
    this.chatPollBusy = true;
    const conn: QpConnection = this.conn;
    try {
      this.applyChats(await fetchChats(conn.baseUrl, conn.token, conn.agentId, this.showArchived), true);
      await this.syncActivity();
    } catch (e) {
      // 静默刷新失败保留原列表
    }
    fetchApprovals(conn.baseUrl, conn.token, conn.agentId).then((list: ApprovalInfo[]): void => {
      this.approvals = list;
    }).catch((): void => {});
    this.chatPollBusy = false;
  }

  private async loadChats(conn: QpConnection): Promise<void> {
    this.conn = conn;
    this.chatsLoading = true;
    this.listRevealed = false;
    fetchApprovals(conn.baseUrl, conn.token, conn.agentId).then((list: ApprovalInfo[]): void => {
      this.approvals = list;
    }).catch((): void => {});
    let list: ChatInfo[] = [];
    try {
      list = await fetchChats(conn.baseUrl, conn.token, conn.agentId, this.showArchived);
      await this.syncActivity();
      this.groups = await fetchChatGroups(conn.baseUrl, conn.token, conn.agentId);
    } catch (e) {
      list = [];
    }
    this.upsertChatVMs(list);
    this.chats = list;
    this.chatsLoading = false;
    this.revealList();
    this.startChatPoll();
  }

  // 列表数据到位后展开：状态驱动 260ms 补间（透明度 + 位移），替代此前的 transition
  private revealList(): void {
    this.getUIContext().animateTo({ duration: 260, curve: Curve.EaseOut }, (): void => {
      this.listRevealed = true;
    });
  }

  // 会话卡片 ⋯ 菜单（对齐 RN app/(tabs)/chats.tsx）：
  // 非归档 = 重命名 / 置顶 / 归档 / 删除；已归档 = 恢复 / 永久删除。
  // c 只作 id 定位：行组件跨轮询保留、菜单由行内重建，动作执行时刻一律取 VM 里的
  // 最新 ChatInfo——置顶/归档态可能已被轮询刷新，用闭包里的旧快照会做反动作
  private chatMenuOf(c: ChatInfo): MenuElement[] {
    const live: () => ChatInfo = (): ChatInfo => this.vmOf(c).chat;
    const items: MenuElement[] = [];
    if (this.showArchived) {
      items.push({
        value: $r('app.string.chat_menu_restore'),
        action: (): void => {
          this.chatOp(live(), 'unarchive');
        }
      });
      items.push({
        value: $r('app.string.chat_menu_delete_forever'),
        action: (): void => {
          this.confirmDeleteChat(live());
        }
      });
      return items;
    }
    const ch: ChatInfo = live();
    items.push({
      value: $r('app.string.chat_menu_rename'),
      action: (): void => {
        this.openRenameModal(live());
      }
    });
    items.push({
      value: ch.pinned ? $r('app.string.chat_menu_unpin') : $r('app.string.chat_menu_pin'),
      action: (): void => {
        const now: ChatInfo = live();
        this.chatOp(now, now.pinned ? 'unpin' : 'pin');
      }
    });
    items.push({
      value: $r('app.string.chat_menu_move'),
      action: (): void => {
        this.openMoveModal(live());
      }
    });
    items.push({
      value: $r('app.string.chat_menu_archive'),
      action: (): void => {
        this.chatOp(live(), 'archive');
      }
    });
    items.push({
      value: $r('app.string.chat_menu_delete'),
      action: (): void => {
        this.confirmDeleteChat(live());
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
      this.getUIContext().getPromptAction().showToast({ message: t($r('app.string.chat_op_failed')) });
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
      this.getUIContext().getPromptAction().showToast({ message: t($r('app.string.chat_op_failed')) });
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
      this.getUIContext().getPromptAction().showToast({ message: t($r('app.string.chat_op_failed')) });
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
          // 面板操作键：Toggle 外壳 + 沉浸材质（内容区 Button 直接挂材质是空转；Toggle 在豁免名单内）
          Toggle({ type: ToggleType.Button, isOn: false }) {
            Text($r('app.string.common_cancel'))
              .fontSize(UiTokens.fsBody)
              .fontColor($r('app.color.text_secondary'))
          }
          .layoutWeight(1)
          .height(46)
          .padding(0)
          .backgroundColor(Color.Transparent)
          .selectedColor(Color.Transparent)
          .systemMaterial(this.switcherMaterial)
          .onChange((isOn: boolean): void => {
            if (isOn) {
              this.closeModalSheet();
            }
          })
          Toggle({ type: ToggleType.Button, isOn: false }) {
            Text($r('app.string.common_confirm'))
              .fontSize(UiTokens.fsBody)
              .fontColor(Color.White)
          }
          .layoutWeight(1)
          .height(46)
          .margin({ left: 10 })
          .padding(0)
          .backgroundColor(this.isDark ? this.theme.accentDark : this.theme.accent)
          .selectedColor(Color.Transparent)
          .systemMaterial(this.switcherMaterial)
          .onChange((isOn: boolean): void => {
            if (isOn) {
              this.submitModal();
            }
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
        value: t($r('app.string.common_cancel')),
        action: (): void => {}
      },
      secondaryButton: {
        value: t($r('app.string.chat_menu_delete')),
        fontColor: $r('app.color.status_error'),
        action: (): void => {
          this.chatOp(c, 'delete');
        }
      }
    });
  }

  // 会话操作（置顶 / 归档 / 删除）统一走 services/ChatsService（与会话详情页菜单同一实现）
  private async chatOp(c: ChatInfo, kind: string): Promise<void> {
    if (this.conn === null) {
      return;
    }
    const conn: QpConnection = this.conn;
    try {
      if (kind === 'pin' || kind === 'unpin') {
        await pinChat(conn.baseUrl, conn.token, conn.agentId, c.id, kind === 'pin');
      } else if (kind === 'archive') {
        await setChatArchived(conn.baseUrl, conn.token, conn.agentId, c.id, true);
      } else if (kind === 'unarchive') {
        await setChatArchived(conn.baseUrl, conn.token, conn.agentId, c.id, false);
      } else {
        await deleteChat(conn.baseUrl, conn.token, conn.agentId, c.id);
      }
      await this.loadChats(conn);
    } catch (e) {
      this.getUIContext().getPromptAction().showToast({ message: t($r('app.string.chat_op_failed')) });
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
      this.getUIContext().getPromptAction().showToast({ message: t($r('app.string.approval_failed')) });
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

  build() {
    Column() {
      // 搜索态只留结果：标题 + 工作区徽章 + 审批 Inbox 三块合计约 800px，键盘弹起时会把列表挤到
      // 只剩一条（实测窗口被压到 1061px、列表区不足 120px → "搜了看不到结果"）。搜索时收起这三块，
      // 列表直接落在搜索条下方，结果一目了然（清空搜索即恢复）
      if (!this.filtering()) {
      Text($r('app.string.cp_title'))
        .fontSize(UiTokens.fsTitle)
        .fontWeight(FontWeight.Bold)
        .margin({ top: 4, bottom: UiTokens.titleGap })

      // 工作区徽章（对齐 7378 features/workspaces/WorkspaceSwitcher.tsx 的 WorkspaceBadge）：
      // 工作区名 + 智能体名 · 运行状态 + 下拉箭头 → 切换面板（切换连接 / 左滑取消配对）
      WorkspaceBadge({
        statusText: this.statusText,
        agentName: this.currentAgentName(),
        reloadToken: this.wsToken,
        onSwitched: (): void => {
          this.reloadAfterSwitch();
        },
        onAdd: (): void => {
          // 再配对一只 → 扫码配对页（对齐 7378 的「再配对一只」直达配对页）
          this.openScan();
        }
      })
        .margin({ top: UiTokens.cardVGap, bottom: UiTokens.cardVGap })

      // 搜索会话已迁到标题栏工具条（SearchPill）——与智能体/工作台同一形态（沉浸光感 + 随 tab 切换滑动）

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
              ? `${this.approvals.length} ${t($r('app.string.chats_inbox_pending'))}`
              : t($r('app.string.chats_inbox_empty')))
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
      }

      if (this.connected) {
        Column() {
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

      // 扩展与 App Center（本地形态）：未连接也可进入浏览内置本地扩展（ModuleExtensions 本地形态），
      // 安装与管理需连接后使用
      Column() {
        HubRow({
          titleRes: $r('app.string.wb_mod_extensions_title'),
          hintRes: $r('app.string.cp_ext_hint'),
          arrow: true,
          onTap: (): void => {
            const param: Record<string, string> = { 'key': 'extensions' };
            swapRoute(this.navStack, 'module', param);
          }
        })
      }
      .margin({ top: 24 })
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

      Button(this.connecting ? t($r('app.string.cp_status_connecting')) : t($r('app.string.cp_connect')))
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
  chatList() {
    Column() {
      Text($r('app.string.cp_chats_title'))
        .fontSize(UiTokens.fsCaption)
        .fontColor($r('app.color.text_tertiary'))
        .margin({ top: UiTokens.titleGap, bottom: 4 })
      Row() {
        // 视图切换常驻：此前它只渲染在「有会话」分支里 → 归档为空时切进「已归档」后
        // 连切换条一起消失，没有任何按钮能切回来（已修）
        this.archivedSwitcher()
        Blank()
        if (!this.showArchived) {
          Text($r('app.string.chats_group_new'))
            .fontSize(UiTokens.fsCaption)
            .fontColor(this.isDark ? this.theme.accentDark : this.theme.accent)
            .onClick((): void => {
              this.openGroupEditor('');
            })
          // 新建会话（对齐 7378 chats.tsx 页头的主色「＋」）：主色胶囊
          Row({ space: 3 }) {
            Image($r('app.media.plus'))
              .width(13).height(13)
              .fillColor(Color.White)
            Text($r('app.string.chats_new'))
              .fontSize(UiTokens.fsChip)
              .fontColor(Color.White)
          }
          .height(28)
          .padding({ left: 10, right: 10 })
          .borderRadius(14)
          .backgroundColor(this.isDark ? this.theme.accentDark : this.theme.accent)
          .margin({ left: 10 })
          .onClick((): void => {
            this.doCreateChat();
          })
        }
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)
      .margin({ bottom: 2 })

      // 首帧取列表：先出转圈占位（对齐 console 列表加载态），取回后再整段淡入，
      // 避免空列表直接"刷"出一整队卡片
      if (this.chatsLoading && this.chats.length === 0) {
        Row() {
          LoadingProgress()
            .width(28)
            .height(28)
            .color(this.isDark ? this.theme.accentDark : this.theme.accent)
        }
        .width('100%')
        .justifyContent(FlexAlign.Center)
        .padding({ top: 48, bottom: 48 })
      } else if (this.filtering() && this.visibleChats().length === 0) {
        // 搜索无命中：与"空列表"分开给文案（对齐 7378 chats.tsx 的 filtered 空态）。
        // 两个约束：① 不套带 padding 的居中 Column、② 上下留白合计压到 ~40vp —— 键盘弹起时
        // 列表页会被压缩（Resize 避让），这是列表最后一个区块，留白大了文字行高会被挤没（实测只剩 4px）
        Text($r('app.string.chats_search_empty_title'))
          .fontSize(UiTokens.fsBody)
          .fontColor($r('app.color.text_secondary'))
          .width('100%')
          .textAlign(TextAlign.Center)
          .margin({ top: 16 })
        Text($r('app.string.chats_search_empty_hint'))
          .fontSize(UiTokens.fsCaption)
          .fontColor($r('app.color.text_tertiary'))
          .width('100%')
          .textAlign(TextAlign.Center)
          .margin({ top: 4, bottom: 16 })
      } else if (this.chats.length === 0) {
        // 归档视图的空态与在阅视图区分（对齐 7378：空归档不是"没有会话"）
        Text(this.showArchived
          ? $r('app.string.chats_archived_empty') : $r('app.string.cp_chats_empty'))
          .fontSize(UiTokens.fsSecondary)
          .fontColor($r('app.color.text_tertiary'))
          .margin({ top: UiTokens.cardVGap })
      } else {
        ForEach(buildChatSections(this.visibleChats(), this.groups,
          (c: ChatInfo): string => this.activityOf(c), this.filtering()), (sec: ChatSection) => {
          this.sectionBlock(sec)
        }, (sec: ChatSection) => this.sectionKeyOf(sec))
      }
    }
    .width('100%')
    .padding({ bottom: 32 })
  }

  // 会话 / 已归档：连排按钮（共用组件 components/SegmentedControl.ets —— 一个框 + 跟手滑块 +
  // 沉浸材质 + 点击/拖动两入口，几何取小号：170×26vp）
  @Builder
  archivedSwitcher() {
    Row() {
      SegmentedControl({
        labels: [$r('app.string.chats_tab_active'), $r('app.string.chats_tab_archived')],
        selectedIndex: this.showArchived ? 1 : 0,
        segHeight: SWITCH_H,
        material: this.switcherMaterial,
        onChange: (index: number): void => {
          this.setArchived(index === 1);
        }
      })
    }
    .width(SWITCH_W)
  }

  // 单个分区（对齐 RN chats.tsx SectionList：header + 会话行）
  @Builder
  sectionBlock(sec: ChatSection) {
    Column() {
      Row() {
        if (sec.pinned) {
          // 置顶标记用系统符号（对齐 7378 chats.tsx 的 lucide Pin；符号名取自 SDK id_defined.json）
          SymbolGlyph($r('sys.symbol.pin_fill'))
            .fontSize(UiTokens.fsCaption)
            .fontColor([this.isDark ? this.theme.accentDark : this.theme.accent])
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
          .bindMenu(this.groupMenuOf(sec.group), menuOptions())
        }
      }
      .width('100%')
      .alignItems(VerticalAlign.Center)
      .margin({ top: 14, bottom: 2 })

      // ForEach 直接迭代 VM 数组（参数即注册表里的 @Observed 引用，@ObjectLink 的正式传法；
      // 传函数调用结果会被 ArkTS 判为 "regular property" 并告警）
      ForEach(this.sectionVMsOf(sec), (vm: ChatRowVM) => {
        ChatCardRow({
          vm: vm,
          accent: this.isDark ? this.theme.accentDark : this.theme.accent,
          avatarText: this.agentInitial(),
          menuOf: (): MenuElement[] => this.chatMenuOf(vm.chat),
          onOpen: (): void => {
            // 点按时刻读 VM（注册表引用稳定，chat 字段始终是新快照）
            this.openChat(vm.chat);
          }
        })
      }, (vm: ChatRowVM) => this.chatKeyOf(vm.chat))
    }
    .width('100%')
    // 展开动画由 listRevealed 驱动（见 revealList）：取数完成前整段透明且下移，
    // 到位后补间到完全不透明、回到原位 —— 首帧不再"一次刷出一队卡片"
    .opacity(this.listRevealed ? 1 : 0)
    .translate({ y: this.listRevealed ? 0 : 18 })
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
      this.statusText = t($r('app.string.cp_status_connecting'));

      const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
      const stored: QpConnection | null = await loadConnection(ctx);
      const keepAgent: string = (stored !== null && sameBaseUrl(stored.baseUrl, rawUrl))
        ? stored.agentId : '';
      const outcome = await connectToQwenPaw(rawUrl, rawTicket, keepAgent);
      this.applyOutcome(outcome);
    } catch (e) {
      const err: Error = e as Error;
      this.connected = false;
      this.statusText = t($r('app.string.cp_status_failed'));
      this.errorMsg = describeConnectError(rawUrl, err);
    } finally {
      this.connecting = false;
    }
  }

  // 新建会话（对齐 7378 chats.tsx create()）：POST /chats → 列表前置 → 直接进详情页
  private async doCreateChat(): Promise<void> {
    const conn: QpConnection | null = this.conn;
    if (conn === null || this.creating) {
      return;
    }
    this.creating = true;
    try {
      const chat: ChatInfo = await createChat(conn.baseUrl, conn.token, conn.agentId, 'New Chat');
      this.chatVMs.set(chat.id, new ChatRowVM(chat, this.activityOf(chat)));
      const next: ChatInfo[] = [chat];
      for (const c of this.chats) {
        next.push(c);
      }
      this.chats = next;
      this.syncActivity();
      this.openChat(chat);
    } catch (e) {
      this.getUIContext().getPromptAction().showToast({
        message: t($r('app.string.chats_create_failed'))
      });
    } finally {
      this.creating = false;
    }
  }

  private openChat(chat: ChatInfo): void {
    this.markRead(chat);
    const param: ChatRouteParam = {
      chatId: chat.id, chatName: chat.name, sessionId: chat.sessionId, userId: chat.userId
    };
    this.rememberLastChat(chat);
    // 会话页始终只留一份：分栏下点另一个会话 = 换窗口（旧页销毁，返回直接回空态）
    swapRoute(this.navStack, 'chat', param);
  }

  // 记忆「最后打开的会话」（按连接 + 智能体）：四项都要存 —— sessionId 用于发送/重连定位，
  // userId 是该会话自己的归属，缺任一项都会挂到别的 chat 或推空流。
  private rememberLastChat(chat: ChatInfo): void {
    const conn: QpConnection | null = this.conn;
    if (conn === null) {
      return;
    }
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    const rec: LastChat = {
      chatId: chat.id, chatName: chat.name, sessionId: chat.sessionId, userId: chat.userId
    };
    saveLastChat(ctx, conn.baseUrl, conn.agentId, rec);
  }

  // 从别的页签切回「会话」页时恢复上次打开的会话（不在启动时自动打开）：仅当本页没有已打开的
  // 会话时才做，且只在会话仍属于当前智能体时才打开；已被删/换过智能体则静默清掉记忆，不弹错。
  private async maybeReopenLastChat(): Promise<void> {
    const conn: QpConnection | null = this.conn;
    if (conn === null || this.chats.length === 0) {
      return;
    }
    // 栈非空即"已打开了会话"（分栏右栏空态由 HdsNavigation.splitPlaceholder 承担，不进栈）
    if (this.navStack.getAllPathName().length > 0) {
      return;
    }
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    const rec: LastChat | null = await loadLastChat(ctx, conn.baseUrl, conn.agentId);
    if (rec === null) {
      return;
    }
    for (const c of this.chats) {
      if (c.id === rec.chatId) {
        this.openChat(c);
        return;
      }
    }
    await clearLastChat(ctx, conn.baseUrl, conn.agentId);
  }

  // 搜索过滤（对齐 7378 chats.tsx：名称不区分大小写包含）。在此基础上多匹配一层「分组名」：
  // 会话页的检索面本来就只有名称，而同工程的工作台搜索是「标题+副标题+关键词+范围」多字段匹配，
  // 用分组名一起匹配才能靠关键词把某组会话一次捞出来（如按分组名搜出该组全部会话）。
  private visibleChats(): ChatInfo[] {
    const q: string = this.query.trim().toLowerCase();
    if (q.length === 0) {
      return this.chats;
    }
    const out: ChatInfo[] = [];
    for (const c of this.chats) {
      if (c.name.toLowerCase().indexOf(q) >= 0
        || this.groupTitleOfId(c.groupId).toLowerCase().indexOf(q) >= 0) {
        out.push(c);
      }
    }
    return out;
  }

  // 会话所属分组的显示名（未分组/未知分组返回空串，不参与匹配）
  private groupTitleOfId(groupId: string): string {
    if (groupId.length === 0) {
      return '';
    }
    for (const g of this.groups) {
      if (g.id === groupId) {
        const ti: ResourceStr = groupTitleOf(g);
        return typeof ti === 'string' ? ti as string : t(ti as Resource);
      }
    }
    return '';
  }

  // 是否处于搜索态（决定空分组是否隐藏、是否显示"没有匹配"）
  private filtering(): boolean {
    return this.query.trim().length > 0;
  }

  private doScan(): void {
    this.openScan();
  }
}

// 会话卡片行（点按 = 打开会话详情）：卡片壳统一走 GlassCard。
// 命名 ChatCardRow（审计 P2-3）：与 ChatRows.ets 的 ChatRow 行调度器（聊天页气泡分发）
// 区分开，避免两个同名组件造成检索歧义。
// 数据经 ChatRowVM @ObjectLink 交付（ForEach 行键 = chat.id）：行组件跨轮询保留、
// 只变化行局部刷新；菜单由行内按需重建（menuOf），置顶/标签状态不随快照陈旧
@Component
export struct ChatCardRow {
  @Watch('onVmChange')
  @ObjectLink vm: ChatRowVM;
  // 主题强调色（置顶图标用）；自定义组件入参须用 @Prop 才会随父组件主题变化同步
  @Prop accent: ResourceColor = '#000000';
  // 头像首字（对齐 7378 卡片的 48vp AgentAvatar；本工程取当前智能体名首字，底色用主题色）
  @Prop avatarText: string = '';
  // 运行中呼吸脉冲的驱动位（对齐 7378 ActivityDot 的 withRepeat(pulse, -1, true)）；
  // 随 activity 同步启停——行组件保留后 activity 可在不重建的情况下 idle→running→idle
  @State private pulseOn: boolean = false;
  private pulseStarted: boolean = false;
  // ⋯ 菜单生成器：父组件只在建行时构建一次的 MenuElement[] 会随快照陈旧
  //（置顶标签/动作方向），故由行在出现与 VM 变化时按需重建
  menuOf: () => MenuElement[] = (): MenuElement[] => [];
  @State private menuItems: MenuElement[] = [];
  onOpen: () => void = (): void => {};

  // 三色口径同 7378：running 蓝、unread 绿、其它中性灰
  private activityColor(): ResourceColor {
    if (this.vm.activity === 'running') {
      return '#2F80ED';
    }
    if (this.vm.activity === 'unread') {
      return '#34C759';
    }
    return '#A9A5A1';
  }

  aboutToAppear(): void {
    this.menuItems = this.menuOf();
    this.syncPulse();
  }

  // @ObjectLink 观察回调：vm 任一字段（chat / activity）变化时触发——
  // 同步脉冲启停 + 重建菜单
  private onVmChange(): void {
    this.syncPulse();
    this.menuItems = this.menuOf();
  }

  private syncPulse(): void {
    if (this.vm.activity !== 'running') {
      if (!this.pulseStarted) {
        return;
      }
      this.pulseStarted = false;
      // 直接写取消该属性上的无限动画（脉冲节点已随 if 移除，此处仅复位状态）
      this.pulseOn = false;
      return;
    }
    if (this.pulseStarted) {
      return;
    }
    this.pulseStarted = true;
    // 无限循环呼吸（官方 animateTo：iterations -1 + PlayMode.Alternate，对应 7378 的 withRepeat(-1, true)）
    this.getUIContext().animateTo({
      duration: 900, curve: Curve.EaseInOut, iterations: -1, playMode: PlayMode.Alternate
    }, (): void => {
      this.pulseOn = true;
    });
  }

  build() {
    GlassCard({
      // 本页容器已给 16vp 水平留白 → 卡片不再叠加，保证三页卡片边界一致（x=56..1260）
      insetH: 0,
      onTap: (): void => {
        this.onOpen();
      }
    }) {
      Row() {
      // 头像 + 右下角运行状态灯（对齐 7378 chats.tsx 的 avatarWrap：48vp AgentAvatar + ActivityDot）
      Stack({ alignContent: Alignment.BottomEnd }) {
        Stack() {
          Circle()
            .fill(this.accent)
            .width(48)
            .height(48)
          Text(this.avatarText)
            .fontSize(18)
            .fontWeight(FontWeight.Bold)
            .fontColor(Color.White)
        }
        .width(48)
        .height(48)
        // 呼吸脉冲层（只 running 有）：同一枚圆放大到 1.8 并随放大淡出，叠在实心灯之下
        if (this.vm.activity === 'running') {
          Circle()
            .fill(this.activityColor())
            .width(12)
            .height(12)
            .margin({ right: 1, bottom: 1 })
            .scale({ x: this.pulseOn ? 1.8 : 1, y: this.pulseOn ? 1.8 : 1 })
            .opacity(this.pulseOn ? 0.26 : 0.7)
        }
        Circle()
          .fill(this.activityColor())
          .width(12)
          .height(12)
          .margin({ right: 1, bottom: 1 })
      }
      .width(52)
      .height(52)
      .margin({ right: 10 })
      Text(this.vm.chat.name)
        .fontSize(UiTokens.fsBody)
        .fontWeight(FontWeight.Medium)
        .layoutWeight(1)
        .maxLines(1)
        .textOverflow({ overflow: TextOverflow.Ellipsis })
      if (this.vm.chat.pinned) {
        // 卡片置顶标记 = 图标（对齐 7378：Pin 主题色实心、约 12vp），不再是文字胶囊 / emoji
        SymbolGlyph($r('sys.symbol.pin_fill'))
          .fontSize(UiTokens.fsCaption)
          .fontColor([this.accent])
          .margin({ right: 8 })
      }
        Text(relativeTime(this.vm.chat.updatedAtMs))
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
        .bindMenu(this.menuItems, menuOptions())
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

interface IndexedChat {
  chat: ChatInfo;
  index: number;
}

// 对齐 7378 features/chats/grouping.ts：running 优先、其次 unread，再按更新时间倒序
// （并列保持原序）。没有这层排序时，正在跑的会话会被埋在列表里，看不出运行状态。
function activityPriority(activity: string): number {
  if (activity === 'running') {
    return 0;
  }
  if (activity === 'unread') {
    return 1;
  }
  return 2;
}

function sortChatsByAttention(list: ChatInfo[], activityOf: (c: ChatInfo) => string): ChatInfo[] {
  const indexed: IndexedChat[] = list.map((c: ChatInfo, i: number): IndexedChat => {
    const item: IndexedChat = { chat: c, index: i };
    return item;
  });
  indexed.sort((left: IndexedChat, right: IndexedChat): number => {
    const byActivity: number = activityPriority(activityOf(left.chat))
      - activityPriority(activityOf(right.chat));
    if (byActivity !== 0) {
      return byActivity;
    }
    const byRecency: number = right.chat.updatedAtMs - left.chat.updatedAtMs;
    return byRecency !== 0 ? byRecency : left.index - right.index;
  });
  return indexed.map((item: IndexedChat): ChatInfo => item.chat);
}

// 地址是否同一目标（末尾斜杠与大小写不敏感）——决定自动重连是否沿用已选智能体
function sameBaseUrl(a: string, b: string): boolean {
  const na: string = a.trim().replace(/\/+$/, '').toLowerCase();
  const nb: string = b.trim().replace(/\/+$/, '').toLowerCase();
  return na.length > 0 && na === nb;
}

// filtering = 搜索态：搜索时分组只剩「命中的那些」，空分组与"无会话"占位不再列出
//（否则搜出来一屏的分组标题与空提示，命中项反而被挤散）。
function buildChatSections(chats: ChatInfo[], groups: ChatGroup[],
  activityOf: (c: ChatInfo) => string, filtering: boolean): ChatSection[] {
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
    const data: ChatInfo[] = sortChatsByAttention(remaining.filter((c: ChatInfo): boolean =>
      g.kind === 'default' ? (c.groupId.length === 0 || c.groupId === g.id) : c.groupId === g.id),
      activityOf);
    if (data.length > 0 || !filtering) {
      sections.push({ key: g.id, title: groupTitleOf(g), chats: data, pinned: false, group: g });
    }
  }
  const ungrouped: ChatInfo[] = remaining.filter((c: ChatInfo): boolean =>
    (c.groupId.length === 0 && !hasDefault) || (c.groupId.length > 0 && knownIds.indexOf(c.groupId) < 0));
  if (ungrouped.length > 0 || (!hasDefault && !filtering)) {
    sections.push({
      key: 'ungrouped', title: $r('app.string.chats_group_ungrouped'),
      chats: sortChatsByAttention(ungrouped, activityOf), pinned: false, group: null
    });
  }
  return sections;
}
