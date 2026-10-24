/*
 * 会话详情 —— 移植 PR #7378 apps/qwenpaw-mobile/app/chat/[id].tsx 一期形态：
 *   历史（GET /api/chats/{id}）+ 输入发送（POST /api/console/chat，stream:true）流式追加 + 停止当前轮。
 * 路由参数：{ chatId, chatName }（routerMap 名 chat，由「会话」tab 的会话行打开）。
 */

import {
  HdsNavDestination, ScrollEffectType, BlurStrategy, hdsMaterial,
  HdsNavigationMenuContentOptions, HdsNavigationMenuItemOptions
} from '@kit.UIDesignKit';
import { emitter } from '@kit.BasicServicesKit';
import { common } from '@kit.AbilityKit';
import { hilog } from '@kit.PerformanceAnalysisKit';
import {
  uiMaterial,
  KeyboardAvoidMode,
  curves,
  window,
} from '@kit.ArkUI';
import { QpConnection, loadConnection, connectionKey } from '../services/ConnectionStore';
import { CONN_STORE_EVENT } from '../services/AppEvents';
import {
  sessionApproval, setSessionApproval, applyLoopCommand, takeLoopPick, setLoopPhase, LoopPick
} from '../services/SessionControls';
import {
  PendingTurn, PendingAttachmentRef, loadPendingTurn, savePendingTurn, clearPendingTurn
} from '../services/PendingTurn';
import { fetchAgentApproval } from '../services/AgentApproval';
import { loadChatApproval } from '../services/ChatApprovalPrefs';
import {
  DisplayTurn, DisplayMessage, DisplayPart, ChatSnapshot, fetchChatMessages, streamChat, reconnectChat, stopChat,
  ChatStreamHandle, ChatInputPart, UploadResult, uploadAttachment, CHAT_CLOSED_EVENT,
  ResponseBlock, responseBlocks, textOfParts, partsTextLen, userEchoParts,
  toolMediaParts, mergeMediaParts, turnFilesOf
} from '../services/ChatDetailService';
import { pickFiles, removeTemp, PickedFile } from '../services/AttachmentPicker';
import { StreamDelta } from '../services/SseParser';
import { ApprovalInfo, fetchApprovals, approveRequest, denyRequest } from '../services/ApprovalsService';
import { fetchChats, ChatInfo, pinChat, setChatArchived, deleteChat } from '../services/ChatsService';
import { ApprovalCard } from '../components/ApprovalCard';
import { SessionRuntimeBar } from '../components/SessionRuntimeBar';
import {
  SlashItem, slashKeyword, filterSlashItems, slashInsertText, loadSlashCatalog
} from '../services/SlashCommands';
import { ChatRow, ConversationRow, rowOf, rowHasVisibleContent, mergeToolMessages, SelectionToolbar,
  copyTextToClipboard } from '../components/ChatRows';
import { stripScrollHeadlines } from '../services/StreamMarkdown';
import { ChatSkeleton } from '../components/ChatSkeleton';
import { areaWidthOf, wideClampW, CONTENT_MAX } from '../theme/Breakpoints';
import { ThemeManager, ThemeSnapshot, ThemeListener } from '../theme/ThemeManager';
import { UiTokens } from '../theme/UiTokens';
import { sampleFabBackdropIsDark, FabSampleRegionVp } from '../theme/FabContrast';
import { blendHex } from '../theme/Accent';
import { PRESS_SCALE, PressLatch, pressEffect, pressTouch } from '../theme/PressFx';
import { slideCoverTransition } from '../services/NavPush';
import { t } from '../services/I18n';

@Builder
export function ChatDetailPageBuilder(_name: string, param: Object) {
  ChatDetailPage({ params: param })
}

// 过程组展开/收起、行插入/消失的补间时长（对齐 tab 切换的 240ms 档，卡片增删是"放大/缩小"而不是瞬跳）
const EXPAND_ANIM_MS: number = 220;
// 「一键回到底部」按钮：直径与出现/隐藏过渡（对齐 console 那套 0.2s 过渡）
const BOTTOM_FAB_SIZE: number = 36;
const BOTTOM_FAB_ANIM_MS: number = 200;
// 输入胶囊之上运行状态条的高度预留（SessionRuntimeBar 一行芯片）
const RUNTIME_ROW_RESERVE: number = 28;

// 会话页的键盘避让持有计数：避让模式是「页」级配置，而分栏下换会话是「入栈新页 + 删旧页」，
// 两页会短暂并存 —— 只按计数归零时才恢复进入前的模式，否则旧页离场会把新页刚关掉的避让又打开。
let kbAvoidHolders: number = 0;
let kbAvoidDefault: KeyboardAvoidMode | null = null;

// 待发附件（已上传成功，发送时转成 content 分片）
interface PendingAttachment {
  id: string;
  name: string;
  kind: string;     // image / video / audio / file
  url: string;
  fileName: string;
}
// 会话页实例序号：第二个起 HDS 内部键盘 inset 会取缓存旧值（真机实测短 44px）


@Component
export struct ChatDetailPage {
  params: Object = new Object();
  @State chatId: string = '';
  @State chatName: string = '';
  // 置顶态（标题栏菜单用）：会话详情接口不回该字段，由会话列表里本会话那一项取得
  @State chatPinned: boolean = false;
  private stack: NavPathStack | null = null;
  // 二级页水平覆盖转场的位移（百分比）：由 NavPush.slideCoverTransition 驱动
  @State pageX: string = '0%';
  @State @Watch('onTurnsChanged') turns: DisplayTurn[] = [];
  // 过程组展开/收起：整组是单一列表项（ProcessGroup 高度插值开合），因此「哪一组展开」
  // 必须由页面持有，而不能留在组卡组件内部。默认展开态 = 活动组展开、其余收起（见 rows()）；
  // 两个列表只记「用户手动改过」的组（互斥），用户在默认态之外的选择以用户为准。
  @State expandedGroups: string[] = [];
  @State collapsedGroups: string[] = [];
  // 用户刚手动展开的组：ProcessGroup 首次挂载播入场动画；虚拟化重入不重播（bodySeen 判定）。
  // 挂载回调里消费掉（见 onBodyMounted），普通 flush 重算 rows() 时已无值
  private pendingAnimGk: string = '';
  // 曾挂载过的过程组键（重入不重播动画的判据；只增不减，进程内量级可忽略）
  private bodySeen: Set<string> = new Set();
  // 选择文本态（单一事实源）：当前进入「选择文本」的行键（行组件私有 @State 会被列表重建抹掉，
  // 且「点气泡外 / 返回手势」需要页面统一清退回 markdown 渲染）
  @State selectingId: string = '';
  // 选中行全文是否已复制（工具栏「复制完成」图标态；每次进入新选择态复位）
  @State selCopied: boolean = false;
  // 各过程组的默认展开态（键 → 是否活动组），rows() 每次重建写回；组头点击据此判断当前态
  private groupGen: Map<string, boolean> = new Map<string, boolean>();
  // 行对象缓存（键 → 实例）：同一键恒复用同一实例（在途 / 已完结一致），字段级判重赋值，
  // 行组件经 @ObjectLink 原地更新（不重建子树、不闪屏）；历史全量重载（loadHistory）时整体清空
  private liveRows: Map<string, ConversationRow> = new Map<string, ConversationRow>();
  @State draft: string = '';
  // 魔法命令（'/' 弹层）：当前过滤出的展示行 + 完整目录（循环/技能懒取一次，失败降级内置命令）
  @State slashOpen: boolean = false;
  @State slashItems: SlashItem[] = [];
  private slashCatalog: SlashItem[] = [];
  private slashLoaded: boolean = false;
  private slashLoading: boolean = false;
  @State sending: boolean = false;
  @State attachments: PendingAttachment[] = [];   // 已上传待发送的附件
  // 本会话待审批（对齐 RN chat/[id].tsx：root_session_id === chat.session_id || chat.id）
  @State approvals: ApprovalInfo[] = [];
  @State uploading: boolean = false;              // 附件上传中（按钮转圈）
  @State errorMsg: string = '';
  @StorageLink('appIsDark') isDark: boolean = false;
  @State theme: ThemeSnapshot = ThemeManager.get().snapshot();
  // 「回到底部」按钮字色档位：按钮脚下消息区深（图片/深色模式）→ 白字，否则主题深字
  // （采样翻转，见 requestFabContrast；字色插值由按钮既有的 .animation 完成）
  @State fabDark: boolean = false;
  private fabSampleBusy: boolean = false;
  private fabSampleTimer: number = -1;
  private fabHostWVp: number = 0;
  private fabHostHVp: number = 0;
  // 发送/停止按钮的按压态：0=发送 1=停止，-1=无（内容区材质不生效 → 按压反馈用通用属性自绘）
  @State btnPressed: number = -1;
  private btnLatch: PressLatch = new PressLatch();
  private scroller: Scroller = new Scroller();
  private stream: ChatStreamHandle | null = null;
  // 发送用的 session_id（对齐 RN store：sessionId = chat.session_id，与 chatId 可能不同）
  private sessionId: string = '';
  // 该会话归属的 user_id（详情响应带出；服务端按 (session_id, user_id) 定位 chat）
  private userId: string = '';
  // 在途回合的本地记录（对齐 7378 pendingChat：切走/重挂载后自己那条不丢）
  private pending: PendingTurn | null = null;
  // 当前流式增量要并入的回合 id：发送时指向本地回显回合，快照出现同一条用户消息后改指
  // 服务端那条回合（服务端回合 id 与本地 turn_<ts> 不同，故不能只认 id，须按用户文本对接）
  private liveTurnId: string = '';
  private pollTimer: number = -1;

  // 本会话待审批：按 root_session_id 归属过滤（与 RN 同口径）
  private async refreshApprovals(): Promise<void> {
    if (this.conn === null) {
      return;
    }
    try {
      const conn: QpConnection = this.conn;
      const all: ApprovalInfo[] = await fetchApprovals(conn.baseUrl, conn.token, conn.agentId);
      const sid: string = this.sessionId.length > 0 ? this.sessionId : this.chatId;
      this.approvals = all.filter((a: ApprovalInfo): boolean =>
        a.rootSessionId === sid || a.rootSessionId === this.chatId);
    } catch (e) {
      // 静默：不影响聊天
    }
  }

  // 批准（exact/similar）/ 拒绝，成功后本地移除（对齐 RN approve/deny）
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
      this.errorMsg = t($r('app.string.approval_failed'));
    }
  }
  private conn: QpConnection | null = null;
  private themeListener: ThemeListener | null = null;
  // 设置页改写连接存储（切换/移除/断开/重新配对）后重取当前连接并复核：
  // 断开 → 停流清态、显示未连接（2.5s 轮询靠 conn===null 守卫自动停网）；
  // 换了服务端（key 或 token 变化）→ 停流后全量重载历史
  private connStoreListener: (data: emitter.EventData) => void = (_data: emitter.EventData): void => {
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    loadConnection(ctx).then((conn: QpConnection | null): void => {
      if (conn === null) {
        if (this.conn === null) {
          return;
        }
        if (this.stream !== null) {
          this.stream.stop();
          this.stream = null;
        }
        this.sending = false;
        this.conn = null;
        this.approvals = [];
        this.errorMsg = t($r('app.string.chat_no_conn'));
        return;
      }
      const changed: boolean = this.conn === null
        || connectionKey(conn) !== connectionKey(this.conn)
        || conn.token !== this.conn.token;
      if (changed) {
        if (this.stream !== null) {
          this.stream.stop();
          this.stream = null;
        }
        this.sending = false;
        this.loadHistory();
      }
    });
  };

  // 发送(0)/停止(1)按钮按压：缩放动画与点光源由 pressTouch/pressEffect 统一驱动
  private canSend(): boolean {
    return this.draft.trim().length > 0;
  }

  // 键盘避让 = RESIZE 压缩模式（官方 FAQ 1073 场景一「底部操作栏被键盘遮挡」的推荐布局）：
  // 软键盘弹起时页面整体压缩、栏体固定在页底 → 自然贴键盘上沿（无黑缝），且固定宽高组件
  // 保持原尺寸（背板不被压扁）。页级设置并在退出时恢复（与 CommunityArticlePage 同模式）。
  // OFFSET 上抬实测（真机）：抬升量含额外安全区量 → 栏底与键盘间留黑缝，分栏下背板还被压扁，故弃用。
  // avoidAreaChange 监听只用于输入态材质淡入淡出（见 kbFrost），不参与布局。
  // 输入内容区高度（vp）：文本换行行数由 measureTextSize 实测驱动——单行 = 基线 50，
  // 每多一行加一个行高，封顶 5 行（超出 5 行的文本在框内滚动，不限制继续输入）。
  // 悬浮页签栏的内容区高度是框架固定的（真机实测约 39vp），内容撑不开栏体，
  // 故高度必须显式测量驱动（行写死 height + barHeight 联动），不能靠子组件反推。
  @State inputBlockH: number = UiTokens.chatComposerBarInner;
  // 输入框实测文本宽度（onAreaChange 缓存）：作为 measureTextSize 的 constraintWidth
  private inputFieldW: number = 0;
  // 输入框控制器：长按系统选择菜单里点"复制"后，把光标定位到所选文本末端以取消选中态
  //（官方 FAQ faqs-arkui-1340：系统复制不会自动取消选中，需 onCopy 回调里 caretPosition）
  private taController: TextAreaController = new TextAreaController();
  // 最近一次选区末端（onTextSelectionChange 记录）：复制后回到末端即"选中态清零"
  private taSelEnd: number = 0;
  // 输入态磨砂背板档位（0~1 过渡值）：0 = 系统沉浸光感（基础材质透出），1 = 磨砂背板全显。
  // 系统材质的档位切换不可动画（官方无过渡接口）→ 基础材质常驻，背板做不透明度交叉淡变
  //（背板在 TabContent 内、材质之下，见 build 内「磨砂背板」）
  @State kbFrost: number = 0;
  // 键盘避让区当前档位（边沿记忆）：avoidAreaChange 在键盘升降**动画期间逐帧触发**，
  // 逐帧调 applyKeyboardFrost 会让 260ms 淡变永远在重启（键盘过渡期淡变完不成 + 逐帧状态写
  // 都是掉帧来源）；只记边沿、0→1/1→0 各驱动一次动画
  private kbFrostUp: boolean = false;
  // 键盘开启态：输入胶囊底边距从 12vp 收到 0（否则键盘上沿会留一条页面底色带，即"缝"）
  @State kbOpen: boolean = false;
  private kbHpx: number = 0;
  private winHpx: number = 0;
  private kbWindow: window.Window | null = null;
  // 键盘 inset 强制重算只做一次/页：每次键盘开启都切避让模式会整页重排（掉帧）
  // 键盘开启时的根容器底部让位（自管；全局已 NONE，不再有框架/ HDS 压缩）
  @State kbBottomVp: number = 0;
  private kbListener: ((data: window.AvoidAreaOptions) => void) | null = null;

  private onBtnTouch(idx: number, e: TouchEvent): void {
    pressTouch(this.getUIContext(), e, this.btnLatch, (v: boolean): void => {
      this.btnPressed = v ? idx : -1;
    });
  }

  // 输入条内容（挂在 Tabs 悬浮页签栏内）：材质、弹性形变、纯圆两端都由
  // barFloatingStyle.systemMaterial 提供，故控件一律透明底，让材质层透出。
  // 会话运行状态条**不在**输入胶囊里：capsule 只包输入行，状态条浮在胶囊之上
  // （见下方 runtimeRow + Tabs.overlay，官方《Tabs 使用 overlay 在页签栏添加自定义组件》写法）。
  // 会话运行状态条（浮在输入胶囊之上）：宽度与胶囊对齐（左右各留 pageHMargin）；
  // hitTestBehavior(Transparent) 让浮层空白处不阻挡下方消息列表滚动（官方 FAQ 明示）
  @Builder
  runtimeRow() {
    Stack({ alignContent: Alignment.Bottom }) {
      Row() {
        SessionRuntimeBar({
          chatId: this.chatId,
          sessionId: this.sessionId
        })
      }
      .width('100%')
      .height('100%')
      // 浮层容器是整个 Tabs 尺寸 → 内容必须显式底对齐，行底即胶囊顶上方 3vp
      .alignItems(VerticalAlign.Bottom)
      .padding({ left: UiTokens.pageHMargin, right: UiTokens.pageHMargin })
    }
    .width('100%')
    .height('100%')
    .hitTestBehavior(HitTestMode.Transparent)
  }

  // 「选择文本」态工具栏（页面级统一落位）：消息区 Stack 的出流兄弟层、贴标题栏底边
  // （顶距 = topInset，与 List 首项占位同口径）。为什么不在行内随气泡浮：高气泡卡顶可贴屏顶，
  // 行内上浮的工具栏会被自己卡顶推出屏外不可点（真机实证）；页面固定落位对任何气泡高度都可达。
  // 出流兄弟层不占列表高 ⇒ 进出选择态不改变行流高，贴底列表不重锚（零跳保持）。
  // 为什么不用 List.overlay：浮层 builder 内的条件子组件不参与合成（真机实证：dump 有完整
  // 布局与命中区、屏幕零像素；if 之外的探针 Text 正常可见）——改挂常规 build 树，条件分支
  // 与进出场过渡照常生效。命中天然只覆盖栏体自身：栏体空 onClick 拦冒泡（点栏体不触发
  // 「点气泡外退出」），其余区域输入照旧穿透到 List；退出只认 ✕ / 点气泡外 / 返回手势。
  // 选中用户气泡时整条取 inverted（实底 + 白字），与 7378 参照的两种前景一致。
  @Builder
  selBar() {
    Column() {
      SelectionToolbar({
        inverted: this.selectedIsUser(),
        copied: this.selCopied,
        theme: this.theme,
        onCopy: (): void => {
          void this.copySelected();
        },
        onDone: (): void => {
          this.selectingId = '';
        }
      })
    }
    .width('100%')
    // topInset + 8：与标题栏底留 8vp 呼吸边距（贴边太突兀）
    .margin({ top: UiTokens.topInset + 8 })
    // 包装层不设底色：SelectionToolbar 自带胶囊底色与左右 16vp 外边距，包装层若再铺全宽实底，
    // 胶囊四周会露出一圈方底（真机反馈"里面圆角外面还有方框"）。
    .transition(TransitionEffect.OPACITY.animation({ duration: 140, curve: Curve.EaseOut }))
    .onClick((): void => {
      // 点栏体（非按钮）：拦冒泡，不触发「点气泡外退出」
    })
  }

  // 工具栏是否可见（selectingId 非空且对应行仍在列表中；selectedRow 会遍历，勿在循环内调用）
  private selBarVisible(): boolean {
    return this.selectingId !== '' && this.selectedRow() !== null;
  }

  @Builder
  composerBar() {
    Stack({ alignContent: Alignment.Center }) {
      // 输入态的磨砂背板不在这里：框架把 tabBar 内容钳在胶囊内容区（左右 12vp / 上下 4vp
      // inset，显式给更大尺寸也会被布局钳回，真机实测）——栏内叠层永远盖不到胶囊边，
      // 背后亮色消息从 rim 透出、叠层直边横切亮 rim 呈"方形块不贴合"。背板改放在 TabContent
      // 的全屏 Stack（见 build 内「磨砂背板」）：系统材质之下、列表之上，满胶囊几何。
        Row() {
          Button() {
            if (this.uploading) {
              LoadingProgress()
                .width(20)
                .height(20)
                .color(this.isDark ? this.theme.accentDark : this.theme.accent)
            } else {
              // 附件图标用 QwenPaw 自己的 design 资产（creator 的 HeroComposerCard 同款
              // icon-add-file.svg）；源 SVG 深色填充在暗色主题下不可见 → fillColor 上色
              Image($r('app.media.icon_add_file'))
                .width(20)
                .height(20)
                .fillColor($r('app.color.btn_gray_text'))
                .draggable(false)
            }
          }
          .type(ButtonType.Normal)
          .width(40)
          .height(40)
          .padding(0)
          // 同上：透明底、不画边框，避免在材质层上再压一层实底/描边；
          // 按压反馈 = 跟手 scale 收缩 + 栏材质 lightEffect 光斑（见 composerBar 栏材质；
          // 键体不挂点光源——预设光参在键外留方形轮廓光晕，真机实测）
          .backgroundColor(Color.Transparent)
          .borderRadius(20)
          .enabled(!this.uploading)
          .scale({ x: this.btnPressed === 2 ? PRESS_SCALE : 1, y: this.btnPressed === 2 ? PRESS_SCALE : 1 })
          .stateEffect(false)
          .onTouch((e: TouchEvent): void => {
            this.onBtnTouch(2, e);
          })
          .onClick((): void => {
            this.attach();
          })
          .margin({ right: 8 })

          // 多行输入：高度由文本换行实测显式驱动（refreshDraftH）——悬浮页签栏的内容区
          // 高度是框架固定的（真机实测约 39vp），组件自身撑不开栏体。minLines(1) 定起步
          // 高度，maxLines(5, SCROLL) 视觉封顶 5 行、超出转框内滚动（API 20+）——封顶的是
          // 框体高度，不是输入：继续输入照常、内容在框内滚动。
          // 关键（官方 ts-text-common MaxLinesOptions）：overflowMode=SCROLL 仅在"非内联模式 +
          // 同时配置 textOverflow 且为 None/Clip"时生效，漏配 textOverflow 会落回默认 CLIP
          // 截断（表现为"超 5 行既不撑高也不能滚"）。故此处显式 None 配合 SCROLL。
          // 行长按/双击弹系统选择菜单，内置复制/剪切/全选（TextMenuItemId 默认项）；
          // "粘贴"项在 API 12+ 剪贴板管控下无 READ_PASTEBOARD 时由系统隐藏（见 module.json5 注释）。
          // 回车保留换行（默认 EnterKeyType.Normal，不设 Send）：发送只走发送按钮。
          TextArea({ text: $$this.draft, placeholder: $r('app.string.chat_input_placeholder'),
            controller: this.taController })
            .layoutWeight(1)
            .minLines(1)
            .textOverflow(TextOverflow.None)
            .maxLines(5, { overflowMode: MaxLinesMode.SCROLL })
            // 长按弹系统选择菜单（复制/剪切/全选），复制走本应用内剪贴板（免读权限）
            .copyOption(CopyOptions.LocalDevice)
            .fontSize(UiTokens.fsBody)
            // 透明：让胶囊的材质层（磨砂 + 受光渐层）连续透出，而不是被一层实底盖住
            .backgroundColor(Color.Transparent)
            .fontColor($r('app.color.input_text'))
            .placeholderColor($r('app.color.placeholder'))
            .borderRadius(21)
            .onChange((value: string): void => {
              this.refreshDraftH(value);
              this.updateSlash(value);
            })
            // 选区变化时记录末端：系统复制不会自动取消选中，复制后据此把光标归位（官方 FAQ faqs-1340）
            .onTextSelectionChange((start: number, end: number): void => {
              if (end >= start) {
                this.taSelEnd = end;
              }
            })
            .onCopy((): void => {
              this.taController.caretPosition(this.taSelEnd);
            })
            // 实测文本宽度（vp，areaWidthOf 为工程统一的 Area 取宽口径）：
            // 宽度变化（分栏拖拽/旋转）时换行行数随之重算
            .onAreaChange((_old: Area, now: Area): void => {
              this.inputFieldW = areaWidthOf(now, this.inputFieldW);
              if (this.inputFieldW > 0) {
                this.refreshDraftH(this.draft);
              }
            })
          if (this.sending) {
            Button($r('app.string.chat_stop'))
              .height(42)
              .margin({ left: 8 })
              // 玻璃底（内容区材质不生效，官方 FAQ 范围规则）
              .backgroundColor($r('app.color.card_glass'))
              .fontColor($r('app.color.status_error'))
              .scale({ x: this.btnPressed === 1 ? PRESS_SCALE : 1, y: this.btnPressed === 1 ? PRESS_SCALE : 1 })
              .stateEffect(false)
              .visualEffect(pressEffect(this.btnPressed === 1))
              .onTouch((e: TouchEvent): void => {
                this.onBtnTouch(1, e);
              })
              .onClick((): void => {
                this.stop();
              })
          } else {
            Button($r('app.string.chat_send'))
              .height(42)
              .margin({ left: 8 })
              // 实底按钮一律**不透明**：不用 enabled(false)（框架禁用态压到约 48%，实测 (57,82,122)），
              // 也不用 opacity（alpha 会被底衬影响、观感发虚）——弱化态用不透明混色表达；
              // 另显式关掉沉浸材质（官方组件级关闭开关 uiMaterial.Material.empty），避免材质层盖在实底上
              .backgroundColor(this.canSend()
                ? (this.isDark ? this.theme.accentDark : this.theme.accent)
                : blendHex(this.isDark ? this.theme.accentDark : this.theme.accent, '#000000', 0.55))
              .systemMaterial(uiMaterial.Material.empty)
              .fontColor(Color.White)
              .scale({ x: this.btnPressed === 0 ? PRESS_SCALE : 1, y: this.btnPressed === 0 ? PRESS_SCALE : 1 })
              .stateEffect(false)
              .visualEffect(pressEffect(this.btnPressed === 0))
              .onTouch((e: TouchEvent): void => {
                this.onBtnTouch(0, e);
              })
              .onClick((): void => {
                if (this.canSend()) {
                  this.send();
                }
              })
          }
        }
        .width('100%')
        // 显式高度 = inputBlockH（文本实测驱动，见 refreshDraftH）：悬浮页签栏内容区
        // 高度固定，constraintSize 的 minHeight 撑不开（真机实测被压回 33vp），
        // 只有显式 height 能溢出渲染（ArkUI 子节点默认不裁切）；栏体长高由
        // capsuleBarH() 联动（见 Tabs 侧 barHeight）。
        // 底内边距 8vp：栏内容区比胶囊顶短 8vp、底部齐胶囊底（真机实测内容整体偏下
        // 4vp）→ 内容盒中心上移 4vp，控件才居中在胶囊中心。偏移为常量（barHeight =
        // 行高+9vp、内容区 = 行高+1vp），任意输入行高下都成立
        .padding({ left: 3, right: 3, bottom: 8 })
        .alignItems(VerticalAlign.Center)
        .height(this.inputBlockH)
    }
    .width('100%')
    // 栏体高度 = capsuleBarH()：与 Tabs 侧 barHeight 同值，磨砂底色铺满整个胶囊
    .height(this.capsuleBarH())
  }

  // 大屏（平板/电脑）正文列限宽：官方《页面布局场景》缩进布局 —— 正文列居中、两侧留白；
  // 分栏态下本页位于右栏——大平板 / 2-in-1 的右栏亦可超 840vp，限宽同样生效；实现见 theme/Breakpoints
  @State pageW: number = 0;

  private onChatArea = (_old: Area, now: Area): void => {
    this.pageW = areaWidthOf(now, this.pageW);
  };

  // 输入胶囊底边距：键盘开启时收到 0（与键盘上沿贴合，消除页面底色带）；关闭时恢复悬浮间距
  private composerBottom(): number {
    return this.kbOpen ? 0 : UiTokens.chatComposerBottomMargin;
  }

  // 输入胶囊宽度（vp）= 内容列宽 − 左右边距：与正文列同一限宽口径（min(窗口宽, 840)）。
  // 窄屏 = 手机全宽形态（376vp → 344，与历史真机实测一致）；折叠屏展开态 / 平板竖屏 /
  // PC 宽窗口下跟随窗口，胶囊与其上方的运行状态条不再保持手机窄宽居中（官方折叠屏
  // 设计清单：展开态体验不得退化为手机 UI）。状态条宽 = Tabs 宽 − 左右 16，天然对齐。
  private capsuleBarW(): number {
    if (this.pageW <= 0) {
      return 344; // 首次 onAreaChange 前回落手机基线宽
    }
    const tabW: number = Math.min(this.pageW, CONTENT_MAX);
    return Math.max(tabW - UiTokens.pageHMargin * 2, 240);
  }

  aboutToAppear(): void {
    const rec: Record<string, Object> = this.params as Record<string, Object>;
    const id: Object = rec['chatId'];
    const name: Object = rec['chatName'];
    this.chatId = typeof id === 'string' ? id as string : '';
    this.chatName = typeof name === 'string' ? name as string : '';
    const sid: Object = rec['sessionId'];
    this.sessionId = typeof sid === 'string' && (sid as string).length > 0 ? sid as string : this.chatId;
    const uid: Object = rec['userId'];
    this.userId = typeof uid === 'string' ? uid as string : '';
    // 本页自己量键盘高度做让位（页根 padding.bottom），窗口保守避让必须只对本页关掉：
    // HdsNavDestination 按窗口缓存键盘 inset，从第二个会话起会把页底压到旧高度上（TabBar 下露一条缝）。
    // 避让模式是「页」级配置，所以只能在会话页自己这里设；最后一个会话页离场时恢复原值。
    if (kbAvoidHolders === 0) {
      kbAvoidDefault = this.getUIContext().getKeyboardAvoidMode();
      this.getUIContext().setKeyboardAvoidMode(KeyboardAvoidMode.NONE);
    }
    kbAvoidHolders++;
    window.getLastWindow(getContext(this)).then((w: window.Window): void => {
      this.kbWindow = w;
      this.winHpx = w.getWindowProperties().windowRect.height;
      const cb = (data: window.AvoidAreaOptions): void => {
        if (data.type === window.AvoidAreaType.TYPE_KEYBOARD) {
          const wasOpen: boolean = this.kbHpx > 14;
          this.kbHpx = data.area.bottomRect.height;
          this.kbOpen = this.kbHpx > 14;
          const vp: number = this.getUIContext().px2vp(this.kbHpx);
          this.getUIContext().animateTo({ curve: curves.springMotion(0.4, 0.68) }, (): void => {
            this.kbBottomVp = vp > 14 ? vp : 0;
          });


          // 输入栏材质淡入淡出（边沿触发，逐帧不重启动画）
          this.applyKeyboardFrost(this.kbHpx > 14);
        }
      };
      this.kbListener = cb;
      w.on('avoidAreaChange', cb);
    });
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    this.themeListener = (snap: ThemeSnapshot): void => {
      this.theme = snap;
      // 主题（深浅色）切换：消息区整幅换色，重渲染后补采按钮字色档位
      this.requestFabContrast(350);
    };
    ThemeManager.get().subscribe(this.themeListener);
    ThemeManager.get().load(ctx).then((): void => {
      this.theme = ThemeManager.get().snapshot();
      this.fabDark = this.isDark;
    });
    emitter.on(CONN_STORE_EVENT, this.connStoreListener);
    this.loadHistory();
    // 与 Console 保持同步（对齐 RN chat/[id].tsx 的 useFocusEffect + setInterval 轮询）：
    // 定时静默重取历史，Console 侧新消息也能进来；流式进行中不打扰
    this.pollTimer = setInterval((): void => {
      this.refreshApprovals();
      this.refreshHistory();
    }, 2500);
  }

  // 页面重新可见时，按窗口**当前**键盘避让区把输入态材质同步回真实值。
  // 覆盖事件时序缺口：进页时键盘已弹起、收起事件丢失、切会话复用实例等场景。
  private resyncKeyboardInset(): void {
    const w: window.Window | null = this.kbWindow;
    if (w === null) {
      return;
    }
    w.getAvoidArea(window.AvoidAreaType.TYPE_KEYBOARD).then((a: window.AvoidArea): void => {
      this.applyKeyboardFrost(a.bottomRect.height > 14);
    });
  }

  // 键盘弹起时输入胶囊的磨砂背板逐渐淡入、收起时逐渐恢复系统沉浸光感。
  // 官方口径：系统材质（ImmersiveMaterial）档位切换无动画接口（瞬切），但材质层位于
  // backgroundColor **之上**，且背景色、不透明度均为可动画属性（《属性动画概述》）→
  // 基础材质常驻，输入态在材质之下（TabContent 内「磨砂背板」）交叉淡入一块与胶囊同几何的
  // 背板，材质的实时磨砂模糊直接作用在背板上 → 底色均匀且保留磨砂质感；收起再淡出。
  // 背板几何与材质胶囊完全一致（同宽/同高/同底边距，见 TabContent），触点透传给输入条。
  // 边沿触发（见 kbFrostUp 注释）：键盘动画期间的逐帧事件只比对不驱动，档位翻转才动画一次
  private applyKeyboardFrost(up: boolean): void {
    if (up === this.kbFrostUp) {
      return;
    }
    this.kbFrostUp = up;
    this.getUIContext().animateTo({ duration: 260, curve: Curve.EaseInOut }, (): void => {
      this.kbFrost = up ? 1 : 0;
    });
  }

  // 胶囊栏体高度（vp）= 输入内容区实际高度 + 上下 chrome（基线 59 = 50 + 9，与
  // UiTokens.chatComposerHeight+1 一致）；内容长高时栏体同步长高
  private capsuleBarH(): number {
    const inner: number = Math.max(this.inputBlockH, UiTokens.chatComposerBarInner);
    return inner + (UiTokens.chatComposerHeight + 1 - UiTokens.chatComposerBarInner);
  }

  // 胶囊相对基线（59vp）长出的增量：栏体上方的留白（列表末尾 inset / 底部固定块边距 /
  // 回到底部按钮 / 运行状态条浮层）都要同量上抬，否则输入框长高会压住上方内容
  private capsuleGrow(): number {
    return this.capsuleBarH() - (UiTokens.chatComposerHeight + 1);
  }

  // 按文本换行实测算输入内容区高度（每次输入变化 / 宽度变化时调用）。
  // 官方口径：带布局约束（constraintWidth）的文本测量用 MeasureUtils.measureTextSize
  //（静态 measureText 只测单行宽，约束不生效），返回值单位 px → px2vp 换算。
  // 高度公式：单行 = 基线 50（与旧版写死高度一致，首帧不跳变），每多一行加一个实测行高，
  // 封顶 5 行（maxLines(5, SCROLL) 同口径：超出在框内滚动，输入不受阻）。
  // 高度变化用 160ms EaseOut 过渡：栏体、磨砂背板、状态条、列表留白随 inputBlockH
  // 同一状态量联动，一次过渡全部跟手。
  private refreshDraftH(value: string): void {
    const base: number = UiTokens.chatComposerBarInner;
    if (value.length === 0 || this.inputFieldW <= 0) {
      if (this.inputBlockH !== base) {
        this.inputBlockH = base;
        // 输入条回单行 → 按钮下移，落脚处内容换了，补采一次
        this.requestFabContrast(300);
      }
      return;
    }
    const oneVal: Length | undefined = this.getUIContext().getMeasureUtils().measureTextSize({
      textContent: '测',
      constraintWidth: this.inputFieldW,
      fontSize: UiTokens.fsBody
    }).height;
    const totalVal: Length | undefined = this.getUIContext().getMeasureUtils().measureTextSize({
      textContent: value,
      constraintWidth: this.inputFieldW,
      fontSize: UiTokens.fsBody
    }).height;
    const oneVp: number = typeof oneVal === 'number' ? this.getUIContext().px2vp(oneVal) : 0;
    const totalVp: number = typeof totalVal === 'number' ? this.getUIContext().px2vp(totalVal) : 0;
    const per: number = oneVp > 0 ? oneVp : totalVp;
    const lines: number = per > 0 ? Math.max(1, Math.round(totalVp / per)) : 1;
    const capped: number = Math.min(lines, 5);
    const next: number = base + per * (capped - 1);
    if (Math.abs(next - this.inputBlockH) < 0.5) {
      return;
    }
    this.getUIContext().animateTo({ duration: 160, curve: Curve.EaseOut }, (): void => {
      this.inputBlockH = next;
    });
    // 输入条多行长高 → 「回到底部」按钮上移，落脚处内容换了，补采一次
    this.requestFabContrast(300);
  }

  // ---- 魔法命令（'/' 弹层，对齐 console Sender suggestion） ----

  // 输入行每次变化重估弹层：'/' 开头且斜杠后无空白时打开并按关键词过滤；其余情况关闭。
  // 目录未取回前只暂存过滤条件，取回后按当前输入行补开（loadSlash 末尾回调本方法）。
  private updateSlash(value: string): void {
    const kw: string | null = slashKeyword(value);
    if (kw === null) {
      if (this.slashOpen) {
        this.slashOpen = false;
        this.slashItems = [];
      }
      return;
    }
    if (!this.slashLoaded && !this.slashLoading) {
      this.loadSlash();
    }
    this.slashItems = filterSlashItems(this.slashCatalog, kw);
    // 开关态以过滤结果为准：结果为空（关键词无匹配、或目录未取回）即收起，
    // 防止空弹层壳浮在输入胶囊上方
    if (this.slashItems.length === 0) {
      if (this.slashOpen) {
        this.slashOpen = false;
      }
    } else if (!this.slashOpen) {
      this.slashOpen = true;
    }
  }

  // 首次按 '/' 时懒取命令目录（循环 + 技能；网络失败只降级对应段，见 SlashCommands）。
  // 连接优先复用页面已加载的 conn，未加载时走 loadConnection（与历史取数同一入口）。
  private async loadSlash(): Promise<void> {
    if (this.slashLoading || this.slashLoaded) {
      return;
    }
    this.slashLoading = true;
    try {
      const conn: QpConnection | null = this.conn !== null
        ? this.conn
        : await loadConnection(getContext(this) as common.UIAbilityContext);
      if (conn !== null) {
        this.slashCatalog = await loadSlashCatalog(conn.baseUrl, conn.token, conn.agentId);
        this.slashLoaded = true;
      }
    } catch (e) {
      // 取数异常保持内置命令（loadSlashCatalog 自身已按段降级），弹层照常
    }
    this.slashLoading = false;
    this.updateSlash(this.draft);
  }

  // 选中命令：输入行整体替换为 "/command "（不自动发送，用户再按发送键才真正交给服务端）。
  // 键盘保持：行点击不夺 TextArea 焦点（ArkUI 焦点不随非焦点组件点按迁移），
  // 光标归位延迟到下一帧（$$ 绑定下一帧才更新文本，此时 caret 才落得进）。
  private pickSlash(item: SlashItem): void {
    const text: string = slashInsertText(item);
    this.draft = text;
    this.slashOpen = false;
    this.slashItems = [];
    setTimeout((): void => {
      this.taController.caretPosition(this.draft.length);
    }, 60);
  }

  aboutToDisappear(): void {
    // 待发的采样定时器随组件销毁清掉，避免回调落到已销毁组件上
    if (this.fabSampleTimer >= 0) {
      clearTimeout(this.fabSampleTimer);
      this.fabSampleTimer = -1;
    }
    // 最后一个会话页离场时恢复进页前的键盘避让模式（NONE 只对会话页生效）
    kbAvoidHolders = kbAvoidHolders > 0 ? kbAvoidHolders - 1 : 0;
    if (kbAvoidHolders === 0 && kbAvoidDefault !== null) {
      this.getUIContext().setKeyboardAvoidMode(kbAvoidDefault);
      kbAvoidDefault = null;
    }
    if (this.kbWindow !== null && this.kbListener !== null) {
      this.kbWindow.off('avoidAreaChange', this.kbListener);
      this.kbWindow = null;
      this.kbListener = null;
    }
    if (this.pollTimer >= 0) {
      clearInterval(this.pollTimer);
      this.pollTimer = -1;
    }
    // 会话页离栈：复位键盘缝探针（底边数据作废，避免其它页开键盘时误判）
    emitter.off(CONN_STORE_EVENT, this.connStoreListener);
    if (this.themeListener !== null) {
      ThemeManager.get().unsubscribe(this.themeListener);
      this.themeListener = null;
    }
    if (this.stream !== null) {
      this.stream.stop();
      this.stream = null;
    }
    emitter.emit(CHAT_CLOSED_EVENT);
  }

  // 在途记录（落盘）读取：只在进页面时读一次（重启/重新进页面后靠它把"自己那条"接回来）
  private async loadPendingRecord(): Promise<PendingTurn | null> {
    const conn: QpConnection | null = this.conn;
    if (conn === null) {
      return null;
    }
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    return await loadPendingTurn(ctx, conn.baseUrl, conn.agentId, this.chatId);
  }

  // 发送用的审批等级落定：模块级单例是全局的，页面上叠了别的会话页再退回本页时，单例可能还停在
  // 上一页的值（会被带进本页的发送）。本页每次进页面/回到前台都按**本会话生效值**重设一次：
  // 本会话覆盖（本机，见 ChatApprovalPrefs）优先，没有则用服务端 Agent 级 approval_level。
  private async applySessionApproval(): Promise<void> {
    const conn: QpConnection | null = this.conn;
    if (conn === null) {
      return;
    }
    try {
      const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
      const override: string = await loadChatApproval(ctx, conn.baseUrl, conn.agentId, this.chatId);
      setSessionApproval(override.length > 0 ? override
        : await fetchAgentApproval(conn.baseUrl, conn.token, conn.agentId));
    } catch (e) {
      setSessionApproval('');
    }
  }

  private dropPendingRecord(): void {
    const c: QpConnection | null = this.conn;
    if (c === null) {
      return;
    }
    clearPendingTurn(getContext(this) as common.UIAbilityContext, c.baseUrl, c.agentId, this.chatId);
  }

  private turnById(id: string): DisplayTurn | null {
    for (const t of this.turns) {
      if (t.id === id) {
        return t;
      }
    }
    return null;
  }

  // 服务端快照里是否已有这条用户消息（返回其回合下标，-1 = 还没有）。
  // 判据只认服务端下发的列表：不能用"本地列表最后一条用户消息"来判断——
  // 本地那条回显文本就是它自己，用本地列表判断会把自己判成"服务端已收到"而提前退役。
  // 除文本外再比媒体分片数量：纯附件消息的服务端用户消息无文本，只比文本会让本地
  // 回显永远对不上账（附件因此永远不显示）。
  private serverEchoIndex(list: DisplayTurn[], text: string, mediaCount: number): number {
    for (let i = list.length - 1; i >= 0; i--) {
      const u: DisplayMessage | null = list[i].user;
      if (u !== null && textOfParts(u.parts) === text) {
        let mc: number = 0;
        for (const p of u.parts) {
          if (p.type !== 'text') {
            mc++;
          }
        }
        if (mc === mediaCount) {
          return i;
        }
      }
    }
    return -1;
  }

  // 服务端快照落地的唯一出口（轮询 / 重取 / 进页面三条路径共用）。取数是异步的，
  // 「取数在途期间用户刚好按下发送」这段窗口里落地的快照若直接替换 turns，会把本地回显整条抹掉
  // （真机实测：长会话一次取数近 1s，命中窗口不小；表现为"看不到自己刚发的那条，等这轮跑完才出现"）。
  //   ① 服务端已收下这条 → 回显退役（流式增量改并入服务端那条回合），落盘的在途记录作废；
  //   ② 服务端还没有 → 保留本地在途回合接在快照末尾（自己发的那条绝不丢；没有本地回合时按记录重建）。
  private settleSnapshot(list: DisplayTurn[], rec: PendingTurn | null): DisplayTurn[] {
    if (rec === null) {
      return list;
    }
    const at: number = this.serverEchoIndex(list, rec.text, rec.attach.length);
    if (at >= 0) {
      // 快照可能落后于流式（服务端尚未落全 reasoning / tool 段）：本地在途回合段数更多时，
      // 保留本地已累积的响应（否则"运行中思考过程显示不全"——快照把更全的流式内容换掉）
      const local: DisplayTurn | null = this.turnById(rec.turnId);
      if (local !== null && local.responses.length > list[at].responses.length) {
        list[at] = { id: list[at].id, user: list[at].user, responses: local.responses,
          pending: list[at].pending };
      }
      this.liveTurnId = list[at].id;
      this.pending = null;
      this.dropPendingRecord();
      return list;
    }
    const found: DisplayTurn | null = this.turnById(rec.turnId);
    const echo: DisplayTurn = found !== null ? found : this.echoTurnOf(rec);
    this.liveTurnId = echo.id;
    this.pending = rec;
    // 快照尾部常带一条「无用户消息的在途回合」（服务端对同一次运行的视图）：它与本地回显
    // 是同一条 run 的两份视图，同时挂上会重复渲染，故以本地那份为准，去掉快照尾部的裸回合。
    const arr: DisplayTurn[] = list.slice();
    while (arr.length > 0 && arr[arr.length - 1].user === null) {
      arr.pop();
    }
    arr.push(echo);
    return arr;
  }

  // 按在途记录重建本地回显回合（记录里留了文本、附件引用与回合 id，重启/重新进页面时照它还原）
  private echoTurnOf(rec: PendingTurn): DisplayTurn {
    const up: DisplayPart[] = [];
    if (rec.text.length > 0) {
      up.push({ type: 'text', text: rec.text });
    }
    for (const a of rec.attach) {
      up.push({ type: this.displayKindOf(a.kind), url: a.url, name: a.fileName });
    }
    if (up.length === 0) {
      up.push({ type: 'text', text: rec.text });
    }
    const um: DisplayMessage = { id: `u_${rec.turnId}`, role: 'user', kind: 'message', parts: up };
    return { id: rec.turnId, user: um, responses: [], pending: true };
  }

  // 会话展平成行序列（一行 = 一个 ListItem 的载荷）。顺序：用户气泡 → 响应分段（消息段 / 步骤组）
  // → 待发占位（仅当该回合还没出可见文本）→ 该回合工具产出媒体。
  // 行对象复用规则：在途回合的行复用同一实例（行组件用 @ObjectLink 观察它 ⇒ 流式期间原地更新，
  // 不重建子树）；已完结回合的行每次新建，没有观察者、不产生无谓刷新。
  private rows(): ConversationRow[] {
    const out: ConversationRow[] = [];
    for (const turn of this.turns) {
      const tid: string = turn.id;
      if (turn.user !== null) {
        const u: DisplayMessage = turn.user;
        out.push(this.rowFor(`u:${tid}`, 'user', tid, turn.pending, [u], [], false, false, false));
      }
      // 响应按 console 口径分段（responseBlocks，语义不改）：message 段逐段可见、其余收进 steps 组
      const blocks: ResponseBlock[] = responseBlocks(turn.responses, turn.pending);
      // 活动组 = 最后一个步骤组（对齐 console HostBubbles：默认展示口径下
      // statusStepBlockIndex = findLastStepBlockIndex(messageBlocks)，即只认"最后一个步骤组"，
      // 其后即使还跟了文本段也仍是它）：只有活动组处于「生成中」，其状态文案与转圈随生成推进；
      // 其余组一律视为已完成（getCollapsedGroupStatus：非活动组 → Completed）。
      let activeStep: number = -1;
      if (turn.pending) {
        for (let i = blocks.length - 1; i >= 0; i--) {
          if (blocks[i].kind === 'steps') {
            activeStep = i;
            break;
          }
        }
      }
      for (let i = 0; i < blocks.length; i++) {
        const b: ResponseBlock = blocks[i];
        // 键 = 回合 + 块序号（结构键，不含内容指纹）：内容变化靠行对象原地更新，键变化即重建子树
        if (b.kind === 'message') {
          if (!messagesHaveContent(b.messages)) {
            continue;   // 空响应段（无可见文本 / 无媒体 / 无错误）不出行，否则渲染成一张空白气泡卡
          }
          out.push(this.rowFor(`m:${tid}:${i}`, 'message', tid, turn.pending, b.messages, [],
            !turn.pending, false, false));
        } else {
          // 过程组 = 单一列表项（ProcessGroup：组头 + 高度插值的 body 盒，展开/收起不产生
          // 任何列表条目增删 → 不触发 stackFromEnd 的重锚推顶，见组件头注释）
          const gk: string = `${tid}:${i}`;
          const gen: boolean = i === activeStep;
          // 默认展开态对齐 console getCollapsedStepPresentation（生成中 → defaultOpen = true，其余 false）：
          // 活动组默认展开、已完成的组默认收起；用户手动开合过的那一组以用户选择为准。
          // 默认态另记一份到 groupGen（组头点击时按它判断"点的是收起还是展开"，
          // 已完结回合的行不在 liveRows 里，不能从行对象读）。
          this.groupGen.set(gk, gen);
          const expanded: boolean = this.expandedGroups.indexOf(gk) >= 0 ? true
            : (this.collapsedGroups.indexOf(gk) >= 0 ? false : gen);
          // messages = 原始组消息（组头 summary 用）；bodyMessages = 工具行合并后的组内行
          //（body ForEach 数据源）。两者都按引用判重赋值，流式期间只重渲染真正变化的行
          const gr: ConversationRow = this.rowFor(`pg:${gk}`, 'stepsGroup', tid, turn.pending,
            b.messages, [], false, gen, expanded);
          gr.groupKey = gk;
          const procs: DisplayMessage[] = mergeToolMessages(b.messages);
          if (!sameMessageRefs(gr.bodyMessages, procs)) {
            gr.bodyMessages = procs;
          }
          // 手动展开 → 首帧挂载播入场动画；虚拟化重入（bodySeen 已见过）不重播
          const anim: boolean = gk === this.pendingAnimGk || !this.bodySeen.has(gk);
          if (gr.animateOpen !== anim) {
            gr.animateOpen = anim;
          }
          out.push(gr);
        }
      }
      if (turn.pending && !this.turnHasStreamText(turn)) {
        out.push(this.rowFor(`p:${tid}`, 'pending', tid, true, [], [], false, false, false));
      }
      // 回合文件清单挂在末尾：工具产出的文件（按 file_path 取，含相对路径与任意扩展名）+
      // 工具媒体分片（截图等），对齐 console 的 ResponseArtifactList——console 只在 run
      // 到达终态（SDK maybeDone：Completed/Canceled/Failed）才渲染清单，故在途回合不出现，
      // 回合跑完才在底部出现
      if (!turn.pending) {
        const media: DisplayPart[] = turnFilesOf(turn.responses);
        if (media.length > 0) {
          out.push(this.rowFor(`x:${tid}`, 'media', tid, false, [], media, false, false, false));
        }
      }
    }
    return out;
  }

  // 取该键的行对象：同一键恒复用同一实例（在途 / 已完结一致，行缓存随历史重载清）。
  // 只在字段真实变化时才赋值：流式期间每 60ms 一次 flush 都会重跑 rows()，若给未变化的行
  // 也赋新数组实例，@ObjectLink 会通知**整张列表**的行组件重建（官方「组件冗余刷新」的典型
  // 来源——状态变量作用面过宽）；真正变的只有活动行的 messages，其余行按引用/签名跳过赋值。
  private rowFor(key: string, kind: string, turnId: string, pending: boolean,
    messages: DisplayMessage[], parts: DisplayPart[], last: boolean, generating: boolean,
    expanded: boolean): ConversationRow {
    let r: ConversationRow | undefined = this.liveRows.get(key);
    if (r === undefined) {
      r = rowOf(kind, key, turnId, messages, parts);
      this.liveRows.set(key, r);
    }
    if (r.kind !== kind) {
      r.kind = kind;
    }
    if (r.turnId !== turnId) {
      r.turnId = turnId;
    }
    if (r.pending !== pending) {
      r.pending = pending;
    }
    if (r.last !== last) {
      r.last = last;
    }
    if (r.generating !== generating) {
      r.generating = generating;
    }
    if (r.expanded !== expanded) {
      r.expanded = expanded;
    }
    if (!sameMessageRefs(r.messages, messages)) {
      r.messages = messages;
    }
    if (!samePartSig(r.parts, parts)) {
      r.parts = parts;
    }
    return r;
  }

  // 过程组展开/收起切换（组头点击）。开合动画不在这里包 animateTo：整组是单一列表项，
  // ProcessGroup 自己持有 body 盒的高度插值（官方 FAQ 1400「内容到终点、容器盒插值」）。
  // 展开/收起在 List 层面没有任何条目增删，锚定 regime 完全由 stackFromEnd（= atBottom）决定：
  //  - 未贴底（长历史读到中段）：offset 恒定，组头钉在按点、body 展开向下滑开 / 收起向上
  //    滑回锚点（收起 = 展开的精确镜像）；
  //  - 贴底：官方 stackFromEnd(true) 重锚语义（底边钉住、顶边随内容上移/下移），与流式跟随
  //    同观感，该 regime 下开合自镜像。
  // regime 只在用户实际穿越贴底边界时切换（syncBottomFab），一次开合内不切 regime——
  // 此前「动画期临时关 stackFromEnd + 完成后再开」的混合期正是"收起不是展开相反"的根因。
  // 自动展开（活动组首现）不走这里——该场景底部跟随才是预期。
  // 当前实际展开态 = 用户覆盖（优先）> 默认态（活动组展开）；据此把该组记进互斥的
  // expandedGroups / collapsedGroups（用户选择覆盖默认态，对齐 console LazyAccordion 受控手风琴）。
  // 收起锚定补偿：贴底 regime 下框架钉住底边，过程组收起时内容整体下滑；按逐帧高度差反补
  // 滚动，让组头屏内位置不动 —— 收起即展开的精确镜像（非贴底时阅读位置本就静止，不补偿）。
  private anchorCollapseStep(deltaVp: number): void {
    if (!this.atBottom || deltaVp === 0) {
      return;
    }
    this.scroller.scrollBy(0, -deltaVp);
  }

  private toggleSteps(gk: string): void {
    const open: string[] = this.expandedGroups.slice();
    const closed: string[] = this.collapsedGroups.slice();
    const isOpen: boolean = this.expandedGroups.indexOf(gk) >= 0 ? true
      : (this.collapsedGroups.indexOf(gk) >= 0 ? false : this.groupGen.get(gk) === true);
    if (isOpen) {
      const a: number = open.indexOf(gk);
      if (a >= 0) {
        open.splice(a, 1);
      }
      if (closed.indexOf(gk) < 0) {
        closed.push(gk);
      }
    } else {
      const b: number = closed.indexOf(gk);
      if (b >= 0) {
        closed.splice(b, 1);
      }
      if (open.indexOf(gk) < 0) {
        open.push(gk);
      }
      // 本次为手动展开：首帧挂载播入场动画（onBodyMounted 消费）
      this.pendingAnimGk = gk;
    }
    this.expandedGroups = open;
    this.collapsedGroups = closed;
    // 列表总高变了但没有滚动事件，贴底 FAB 的 isAtEnd 会过期——主动复核一次
    // （贴底态下框架重锚把 offset 钉在新 max，atBottom 复核后保持 true，regime 不变）
    setTimeout((): void => {
      this.syncBottomFab();
    }, 60);
  }

  // 过程组挂载回调：记入 bodySeen（重入不重播动画）并消费手动展开标记
  private onBodyMounted(gk: string): void {
    this.bodySeen.add(gk);
    if (this.pendingAnimGk === gk) {
      this.pendingAnimGk = '';
    }
  }

  // 全部行（都进 ForEach，键稳定 ⇒ 不重建）。为什么不再把末行放在 ForEach 之外：新增响应段时，
  // "原来在外的末行"会移进 ForEach —— 对 ArkUI 而言是**销毁 + 重建**，那一行会闪一下（有过渡动画
  // 时更明显）。行数据经 @Observed/@ObjectLink 原地更新，键不变即不重建 subtree，故放在 ForEach 内
  // 同样能逐字刷新，且不会再出现"末行换位置"的重建。
  private allRows(): ConversationRow[] {
    return this.rows();
  }

  // 「选择文本」当前选中的行（工具栏的复制 / 判定用户气泡都从行数据取，不再依赖行组件状态）
  private selectedRow(): ConversationRow | null {
    const key: string = this.selectingId;
    for (const r of this.allRows()) {
      if (r.key === key) {
        return r;
      }
    }
    return null;
  }

  private selectedText(): string {
    const r = this.selectedRow();
    if (r === null || r.messages.length === 0) {
      return '';
    }
    // 与渲染管线一致：里程碑标题行（⟦ … ⟧）不进剪贴板
    return stripScrollHeadlines(textOfParts(r.messages[0].parts));
  }

  private selectedIsUser(): boolean {
    const r = this.selectedRow();
    return r !== null && r.kind === 'user';
  }

  private async copySelected(): Promise<void> {
    const text: string = this.selectedText();
    if (text.length === 0) {
      return;
    }
    const ok: boolean = await copyTextToClipboard(this.getUIContext(), text);
    const msg: string = ok ? t($r('app.string.chat_msg_copied')) : t($r('app.string.chat_msg_copy_failed'));
    this.getUIContext().getPromptAction().showToast({ message: msg });
    if (ok) {
      this.selCopied = true;
    }
  }

  // 该回合是否已有可见的流式文本段（没有则出「正在生成」占位）
  private turnHasStreamText(turn: DisplayTurn): boolean {
    for (const m of turn.responses) {
      if (m.role === 'assistant' && m.kind === 'message' && textOfParts(m.parts).length > 0) {
        return true;
      }
    }
    return false;
  }

  // 历史摘要：只反映内容（文本长度与过程条目数）；消息身份已是内容派生，同内容必同摘要
  private turnsDigest(list: DisplayTurn[]): string {
    const parts: string[] = list.map((t: DisplayTurn): string => {
      let n: number = 0;
      for (const m of t.responses) {
        n += partsTextLen(m.parts);
      }
      return `${partsTextLen(t.user !== null ? t.user.parts : [])}:${n}:${t.responses.length}`;
    });
    return parts.join('|');
  }

  // 静默轻查（与审批同拍 2.5s）：① 服务端已 running 而本页没挂流（例如从 Console 发起的 run）
  // → 补挂 reconnect 流，这是"别处跑起来本页也能实时看到"的关键；② 内容确有变化才替换
  // （差异化判断，避免无谓重建；不强制滚到底，避免拽走阅读位置）。
  private async refreshHistory(): Promise<void> {
    if (this.sending || this.conn === null) {
      return;
    }
    try {
      const conn: QpConnection = this.conn;
      const snap: ChatSnapshot = await fetchChatMessages(conn.baseUrl, conn.token, conn.agentId,
        this.chatId);
      // 取数期间用户按了发送/挂上了流：这份快照的尾部已过时（缺刚发的那条），丢弃本次对齐，
      // 由下一拍或流结束时的重取接手（守卫只写在取数之前会漏掉这段窗口）
      if (this.sending || this.stream !== null) {
        return;
      }
      if (snap.running && this.stream === null) {
        this.attachRunningStream();
        return;
      }
      const next: DisplayTurn[] = this.settleSnapshot(snap.turns, this.pending);
      if (this.turnsDigest(next) !== this.turnsDigest(this.turns)) {
        this.turns = next;
      }
    } catch (e) {
      // 静默刷新失败不影响页面
    }
  }

  // 强制重取历史（流式结束 / 停止后调用）：对齐 RN store.send 的 finally → loadChat(chat.id)
  // 全量重取——reasoning/tool 块靠重取呈现（流式 delta 只打 message 进 answer 气泡）。
  private async reloadTurns(): Promise<void> {
    if (this.conn === null) {
      return;
    }
    try {
      const conn: QpConnection = this.conn;
      const snap: ChatSnapshot = await fetchChatMessages(conn.baseUrl, conn.token, conn.agentId,
        this.chatId);
      this.turns = this.settleSnapshot(snap.turns, this.pending);
      this.scrollBottom();
    } catch (e) {
      // 重取失败：保留本地流式内容，下一轮轮询再对齐
    }
  }

  // 重连进行中的会话流：与 send 同一套 delta 渲染与收尾（对齐 7378 store.reconnectChat）
  private attachRunningStream(): void {
    const conn: QpConnection | null = this.conn;
    if (conn === null || this.stream !== null) {
      return;
    }
    this.sending = true;
    // 重连的增量并入列表末尾那条在途回合（服务端在跑的这一次 run 就挂在它上面）
    this.liveTurnId = this.turns.length > 0 ? this.turns[this.turns.length - 1].id : '';
    this.stream = reconnectChat(conn.baseUrl, conn.token, conn.agentId,
      this.sessionId.length > 0 ? this.sessionId : this.chatId, this.userId,
      (delta: StreamDelta): void => {
        this.appendDelta(delta);
      },
      (error: string | null): void => {
        this.sending = false;
        this.stream = null;
        if (error !== null) {
          this.errorMsg = error;
        }
        this.reloadTurns();
      });
  }

  private async loadHistory(): Promise<void> {
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    // 全量重取历史 = 整套回合换血：丢旧行对象（换会话 / 换连接重进时防上一份的行残进列表）
    this.liveRows.clear();
    // 换血会摘掉正在播开合动画的过程组——动画标记必须一并清，
    // 否则新列表会重播旧组的入场动画（贴底态统一在下方 atBottom=true 复位）
    this.pendingAnimGk = '';
    this.historyDone = false;
    this.listShown = false;
    this.armSettleCap();
    this.errorMsg = '';
    try {
      const conn: QpConnection | null = await loadConnection(ctx);
      if (conn === null) {
        this.errorMsg = t($r('app.string.chat_no_conn'));
        return;
      }
      this.conn = conn;
      this.applySessionApproval();
      this.refreshApprovals();
      this.loadChatMeta(conn);
      const snap: ChatSnapshot = await fetchChatMessages(conn.baseUrl, conn.token, conn.agentId,
        this.chatId);
      // 在途回显（自己发出去、服务端还没收下的那条）按落盘记录对齐：
      // 服务端已有 → 退役；还没有 → 接在快照末尾（进页面/重进都靠这一步不丢）
      this.pending = await this.loadPendingRecord();
      // 身份优先取列表项带来的 user_id（详情接口不返回该字段）；详情里若有则以它为准
      if (snap.userId.length > 0) {
        this.userId = snap.userId;
      }
      this.turns = this.settleSnapshot(snap.turns, this.pending);
      // 全新历史 = 从底部开始（跟随开启）：随后 landAtBottom / scrollBottom 落到末尾
      this.atBottom = true;
      if (this.listShown) {
        this.landAtBottom();
      }
      if (snap.running) {
        // 服务端上一轮仍在跑（本机离开后回来 / 从 Console 发起）：重连该流实时呈现剩余内容
        // （对齐 7378 app/chat/[id].tsx：loadChat 回 running 时调用 reconnectChat）
        this.errorMsg = '';
        this.attachRunningStream();
      }
      this.scrollBottom();
    } catch (e) {
      this.errorMsg = (e as Error).message;
    }
    this.historyDone = true;
    this.onTurnsChanged();
  }

  // 是否贴着底部（由列表可见区间推断：末项可见即视为在底部）
  // 贴底跟随：新内容进来只在这个开关打开时把视图钉到底部；用户一旦自己划走就关掉
  //（松手时用 Scroller.isAtEnd 判定，划回底部自动恢复跟随）。
  // 历史是否已到位：未到位只显示转圈（空屏），到位后列表才成形（并带 initialIndex 直接落在底部）
  @State historyDone: boolean = false;
  // 列表是否已首次呈现过：骨架屏只服务于"首次呈现之前"，呈现过就不再回退
  //（单向门：后续 turns 变化不得复位它，否则列表会被换回骨架屏 → 骨架/列表闪烁）
  @State listShown: boolean = false;
  private settleTimer: number = -1;
  private settleCapTimer: number = -1;

  // 状态变化的唯一出口（ArkUI 状态钩子）：每次 turns 被写入都重置 220ms 静默窗口，
  // 连续无变化才把骨架屏换成真实列表。实测进页面后行数会在 done 之后继续分批追加
  //（5→15→27→41，约 250ms 内），先落定再呈现可消除该批追加造成的闪现。
  private onTurnsChanged(): void {
    if (!this.historyDone) {
      return;
    }
    if (this.settleTimer >= 0) {
      clearTimeout(this.settleTimer);
    }
    this.settleTimer = setTimeout((): void => {
      this.settleTimer = -1;
      this.listShown = true;
      // 落定只在"真的在底部"时钉底（与置底按钮 / 流式跟随同一口径 atBottom）：
      // 首次呈现时 atBottom=true（进页即底部）照常落底；流式期间用户上滑阅读时
      // atBottom=false，落定不再把阅读位置拽回底部
      if (this.atBottom) {
        this.landAtBottom();
      }
    }, 220);
  }

  // 上限兜底：活跃流式会话会持续变化，静默窗口可能迟迟不到 → 1.2s 后强制落定
  private armSettleCap(): void {
    if (this.settleCapTimer >= 0) {
      clearTimeout(this.settleCapTimer);
    }
    this.settleCapTimer = setTimeout((): void => {
      this.settleCapTimer = -1;
      this.listShown = true;
      // 同 220ms 落定窗口：只在"真的在底部"时钉底（atBottom 与置底按钮同口径）
      if (this.atBottom) {
        this.landAtBottom();
      }
    }, 1200);
  }
  // 列表是否停在末尾（isAtEnd）：唯一的"真到底"判据——驱动「一键回到底部」按钮的进出场、
  // 流式贴底跟随（两者共用同一口径，结构上不可能出现"按钮显示着还在把阅读位置拽回底部"），
  // 并直接作为 List 的 stackFromEnd（贴底 regime / 锚定 regime 的切换源，见 List 处注释）。
  // 初值 true = 刚进来就是底部
  @State atBottom: boolean = true;
  // 手指是否正按在列表上：程序化 scrollEdge 不产生触摸事件，故用触摸态区分来源。
  // 不用时间型守卫——流式高频 append 期间时间窗口几乎常开，会持续吞掉用户拖动、
  // 随即又被拽回底部；触摸态只在手指真正按住列表时冻结贴底，松手即恢复，精准无副作用。
  private userTouching: boolean = false;

  private scrollBottom(force: boolean = false): void {
    // 手指在列表上就绝不自动贴底（无论是否 force）：这是"上滑被拽回底部"的直接原因
    if (this.userTouching) {
      return;
    }
    // 跟随门控 = 与置底按钮同一判据（isAtEnd）：只有"真的划到底"才随新内容贴底，
    // 划离底部即停（不再被拽回）；划回底部 / 点置底按钮时 atBottom 复位为 true 自动恢复
    if (!force && !this.atBottom) {
      return;
    }
    setTimeout((): void => {
      // 延迟执行前复核：40ms 窗口内用户落下手指 / 划离底部则放弃本次追底
      //（调用时判定、延迟执行之间的窗口会让"没真划到底"也被追一次底）
      if (this.userTouching || (!force && !this.atBottom)) {
        return;
      }
      this.scroller.scrollEdge(Edge.Bottom);
      this.syncBottomFab();
    }, 40);
  }

  // 开页面时把视口钉到底部。为什么要显式钉：List 的 initialIndex 只在**列表创建那一刻**生效，
  // 而长会话历史是分批到达的（解析慢时 1.2s 兜底会先放行列表）——数据后到就停在列表顶部，
  // 观感即"打开聊天页停在最上面"。列表首次呈现与历史落定两条路径各补一次到底。
  private landAtBottom(): void {
    setTimeout((): void => {
      this.scroller.scrollEdge(Edge.Bottom);
      this.syncBottomFab();
    }, 60);
  }

  // 「一键回到底部」按钮（对齐 console 用的 SDK 里的 BubbleList/ScrollToBottom）：
  // 判据 = 滚动位置是否真的在末尾（Scroller.isAtEnd），与 console 的"距底 >10px 才出现"同义；
  // 点击后平滑回到底并隐藏；出现/隐藏是 200ms 位移 + 透明度过渡（隐藏时下移自身高度、且不接收点击）。
  private syncBottomFab(): void {
    const atEnd: boolean = this.scroller.isAtEnd();
    if (atEnd !== this.atBottom) {
      this.atBottom = atEnd;
    }
  }

  // ──「回到底部」按钮字体对比度采样（机制见 theme/FabContrast.ets）──
  // 按钮浮在消息区之上：底下是图片/深色模式时深字看不见。只在滚动停稳（onScrollStop）、
  // 输入条高度变化、主题切换后采样（带去抖与在途守卫），翻转 fabDark；不逐帧，不干扰滚动。
  private fabGlyphColor(): ResourceColor {
    return this.fabDark ? Color.White : $r('app.color.text_primary_strong');
  }

  private requestFabContrast(delay: number): void {
    if (this.fabSampleTimer >= 0) {
      clearTimeout(this.fabSampleTimer);
      this.fabSampleTimer = -1;
    }
    this.fabSampleTimer = setTimeout((): void => {
      this.fabSampleTimer = -1;
      this.doFabContrast();
    }, delay);
  }

  private doFabContrast(): void {
    if (this.fabSampleBusy || this.fabHostWVp <= 0 || this.fabHostHVp <= 0) {
      return;
    }
    this.fabSampleBusy = true;
    sampleFabBackdropIsDark(this.getUIContext(), 'chatFabHost',
      this.fabSampleRegion(), this.fabHostWVp, this.fabHostHVp)
      .then((dark: boolean | null): void => {
        if (dark !== null && dark !== this.fabDark) {
          this.fabDark = dark;
        }
      })
      .catch((): void => {
        // 采样失败（组件离屏等）：保持当前字色
      })
      .then((): void => {
        this.fabSampleBusy = false;
      });
  }

  // 采样区域 = 以按钮中心为心、两倍直径的盒（按钮贴底居中，底距 = bottomFabOffset()）
  private fabSampleRegion(): FabSampleRegionVp {
    return {
      x: this.fabHostWVp / 2 - BOTTOM_FAB_SIZE,
      y: this.fabHostHVp - this.bottomFabOffset() - BOTTOM_FAB_SIZE * 1.5,
      w: BOTTOM_FAB_SIZE * 2,
      h: BOTTOM_FAB_SIZE * 2
    };
  }

  private jumpToBottom(): void {
    // 回到底部后 atBottom 由 syncBottomFab 置回 true → 跟随随之恢复（与划到底自动恢复同一口径）
    this.scroller.scrollToIndex(this.initialRowIndex(), true, ScrollAlign.END);
    this.syncBottomFab();
  }

  // 按钮底距：让开悬浮输入胶囊 + 其上方的运行状态条（两者高度见 UiTokens / runtimeRow）
  private bottomFabOffset(): number {
    return this.composerBottom() + this.capsuleBarH()
      + UiTokens.chatRuntimeRowGap + RUNTIME_ROW_RESERVE + 10;
  }

  // 列表初始落点 = 末尾留白项：List 创建即停在**最底部**（末条内容的底边贴着末尾留白，
  // 留白已含悬浮输入条 + 其上的运行状态条 ⇒ 末条不被遮挡）。不靠多次 scrollEdge 追底部。
  private initialRowIndex(): number {
    return this.allRows().length + 1;
  }

  // 流式增量归并（在 7378 基础上增强：message 实时进 answer；reasoning/tool 的流式文本
  // 亦实时累积进 process 对应消息，逐字呈现思考 / 工具文本，不再等流结束 reload）。
  // 归并进最后一个 turn（即发送时 push 的 live turn）。
  private pendingDeltas: StreamDelta[] = [];
  private deltaTimer: number = -1;

  // delta 先入缓冲，按 ~60ms 合并后再一次性落到 turns
  // （对齐 7378 store/app.ts 的 requestAnimationFrame 批量 flushText：逐 delta 重建会打爆渲染）
  private appendDelta(delta: StreamDelta): void {
    // user_message 回显帧必须最先处理：纯媒体回显 text 为空，会被下面的早退吞掉；
    // 它也不是助手的响应段，不能进 pendingDeltas 缓冲（那条路只并入在途回合的 responses）
    if (delta.kind === 'user') {
      this.applyUserEcho(delta);
      return;
    }
    // 工具段的载荷在 toolName/Input/Output 上（text 为空），不能按文本长度提前丢弃
    const hasTool: boolean = delta.toolName !== undefined || delta.toolInput !== undefined
      || delta.toolOutput !== undefined || delta.toolState !== undefined;
    if (delta.text.length === 0 && !hasTool) {
      return;
    }
    this.pendingDeltas.push(delta);
    if (this.deltaTimer < 0) {
      this.deltaTimer = setTimeout((): void => {
        this.flushDeltas();
      }, 60);
    }
  }

  // user_message 回显帧 → 用户自己那条消息的呈现。服务端只在回合结束时落盘用户消息，
  // 运行中仅靠这一帧送达——没有它，别处（console / 其它设备）发出的消息要等回合结束
  // 重取历史才可见。
  //   1. 幂等：回合 id 固定为 turn_${messageId}，已存在即跳过（reconnect 重放会再送同一帧）；
  //   2. 自发自收：列表末尾是本机刚建的乐观/在途回合（与 liveTurnId 一致且 pending），
  //      它正是这次 run 的回显——不新建回合，后续助手流按 liveTurnId 自然并入；
  //   3. 其余（别处发出）：新建用户回合并把在途指针指到它，滚动只跟随已贴底的状态
  //      （scrollBottom 内部自带 userTouching / atBottom 守卫，不拽走阅读位置）。
  private applyUserEcho(delta: StreamDelta): void {
    const turnId: string = `turn_${delta.messageId}`;
    const arr: DisplayTurn[] = this.turns.slice();
    for (const t of arr) {
      if (t.id === turnId) {
        return;
      }
    }
    const contentJson: string = delta.userContent !== undefined ? delta.userContent : '';
    const parsed: DisplayPart[] = userEchoParts(contentJson);
    let userParts: DisplayPart[] = parsed;
    if (userParts.length === 0 && delta.text.length > 0) {
      const tp: DisplayPart = { type: 'text', text: delta.text };
      userParts = [tp];
    }
    if (userParts.length === 0) {
      return;
    }
    const last: DisplayTurn | null = arr.length > 0 ? arr[arr.length - 1] : null;
    if (last !== null && last.pending === true && last.id === this.liveTurnId) {
      return;
    }
    const um: DisplayMessage = { id: `u_${turnId}`, role: 'user', kind: 'message', parts: userParts };
    const turn: DisplayTurn = { id: turnId, user: um, responses: [], pending: true };
    arr.push(turn);
    this.turns = arr;
    this.liveTurnId = turnId;
    this.scrollBottom();
  }

  private flushDeltas(): void {
    this.deltaTimer = -1;
    const buf: StreamDelta[] = this.pendingDeltas;
    this.pendingDeltas = [];
    if (buf.length === 0) {
      return;
    }
    // 并入「当前在途回合」而不是「列表最后一条」：中间若有服务端快照落地（或尾部多出一条
    // 无用户消息的在途回合），按位置并入会把这一段响应挂到别的回合上去（真机实测会出现
    // 上一轮的内容里混进这一轮的思考/工具行）。在途回合由 liveTurnId 指明。
    const arr: DisplayTurn[] = this.turns.slice();
    let li: number = -1;
    if (this.liveTurnId.length > 0) {
      for (let i = arr.length - 1; i >= 0; i--) {
        if (arr[i].id === this.liveTurnId) {
          li = i;
          break;
        }
      }
    }
    if (li < 0 && this.sending && arr.length > 0) {
      li = arr.length - 1;
    }
    if (li < 0) {
      return;
    }
    let t: DisplayTurn = arr[li];
    for (const d of buf) {
      t = this.mergeDeltaInto(t, d);
    }
    arr[li] = t;
    // 这里**不能**用 animateTo 包住数据写入：同一帧里所有布局变化都会被补间 —— 不只是新插入的
    // 卡片，还包括正在流式增长的那块文本（高度持续变大）⇒ 整块一直在"呼吸"（观感即"一直在闪"）。
    // 卡片进场的淡入 / 上移改由行自身负责（ChatRow 的进场动画），与其它行的布局完全解耦。
    this.turns = arr;
    this.scrollBottom();
  }

  // 流式增量并入响应段（对齐 console：服务端每个 msg_id 就是一段，reasoning / plugin_call / message 各自成段）
  //   同一 msg_id = 该段续写；换了 msg_id = 新起一段（旧段原地保留，不再像早先那样把 answer 覆盖掉）。
  //   重连时服务端从头重放整条流，段按序重建，故不需要另做去重。
  private mergeDeltaInto(t: DisplayTurn, delta: StreamDelta): DisplayTurn {
    const res: DisplayMessage[] = t.responses.slice();
    let idx: number = -1;
    for (let i = res.length - 1; i >= 0; i--) {
      if (res[i].id === delta.messageId && delta.messageId.length > 0) {
        idx = i;
        break;
      }
    }
    const hasTool: boolean = delta.toolName !== undefined || delta.toolInput !== undefined
      || delta.toolOutput !== undefined || delta.toolState !== undefined;
    // 工具段顺带抽取产出文件（与历史快照同一套判定）：运行中持续抽取、清单数据随流就绪；
    // 清单行只在回合结束后渲染（rows() 按 !turn.pending 门控，对齐 console maybeDone 终态口径）
    const files: DisplayPart[] = toolMediaParts(delta.toolInput, delta.toolOutput);
    if (idx >= 0) {
      const cur: DisplayMessage = res[idx];
      const parts: DisplayPart[] = mergeMediaParts(cur.parts.slice(), files);
      appendText(parts, delta.text);
      const nm: DisplayMessage = {
        id: cur.id, role: cur.role, kind: cur.kind, parts: parts,
        toolName: delta.toolName !== undefined ? delta.toolName : cur.toolName,
        toolState: delta.toolState !== undefined ? delta.toolState : cur.toolState,
        toolCallId: cur.toolCallId, toolInput: delta.toolInput !== undefined ? delta.toolInput
          : (hasTool ? cur.toolInput : cur.toolInput),
        toolOutput: delta.toolOutput !== undefined ? delta.toolOutput : cur.toolOutput,
        toolArgs: delta.toolInput !== undefined ? delta.toolInput : cur.toolArgs
      };
      res[idx] = nm;
    } else {
      const parts: DisplayPart[] = files.slice();
      appendText(parts, delta.text);
      const id: string = delta.messageId.length > 0 ? delta.messageId : `seg_${t.id}_${res.length}`;
      const seg: DisplayMessage = {
        id: id, role: 'assistant', kind: hasTool ? 'tool' : delta.kind, parts: parts,
        toolName: delta.toolName, toolState: delta.toolState,
        toolInput: delta.toolInput, toolOutput: delta.toolOutput, toolArgs: delta.toolInput
      };
      res.push(seg);
    }
    const nt: DisplayTurn = { id: t.id, user: t.user, responses: res, pending: true };
    return nt;
  }

  // 选择附件并逐个上传（对齐 RN pickAttachment：任意类型、多选、逐个 POST /api/console/upload）
  private async attach(): Promise<void> {
    if (this.conn === null || this.uploading) {
      return;
    }
    const conn: QpConnection = this.conn;
    this.uploading = true;
    this.errorMsg = '';
    try {
      const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
      const picked: PickedFile[] = await pickFiles(ctx);
      const added: PendingAttachment[] = [];
      for (const f of picked) {
        try {
          const up: UploadResult = await uploadAttachment(conn.baseUrl, conn.token, conn.agentId,
            f.path, f.name, f.mime);
          const item: PendingAttachment = {
            id: up.url, name: up.fileName, kind: f.kind, url: up.url, fileName: up.fileName
          };
          added.push(item);
        } finally {
          removeTemp(f.path);   // 上传完成即清理沙箱临时文件
        }
      }
      this.attachments = this.attachments.concat(added);
    } catch (e) {
      this.errorMsg = t($r('app.string.chat_attach_failed'));
    } finally {
      this.uploading = false;
    }
  }

  private removeAttachment(id: string): void {
    this.attachments = this.attachments.filter((a: PendingAttachment): boolean => a.id !== id);
  }

  // 附件 kind → 消息 content 分片 type（与 DisplayPart.type 同域；三种媒体之外一律文件卡）
  private displayKindOf(kind: string): string {
    return kind === 'image' || kind === 'video' || kind === 'audio' ? kind : 'file';
  }

  // 附件 → content 分片（对齐 RN：image/video/audio 前缀判定，其余按文件）
  private attachmentParts(): ChatInputPart[] {
    const out: ChatInputPart[] = [];
    for (const a of this.attachments) {
      if (a.kind === 'image') {
        const p: ChatInputPart = { type: 'image', image_url: a.url };
        out.push(p);
      } else if (a.kind === 'video') {
        const p: ChatInputPart = { type: 'video', video_url: a.url };
        out.push(p);
      } else if (a.kind === 'audio') {
        const p: ChatInputPart = { type: 'audio', data: a.url };
        out.push(p);
      } else {
        const p: ChatInputPart = { type: 'file', file_url: a.url, file_name: a.fileName };
        out.push(p);
      }
    }
    return out;
  }

  private send(): void {
    // 循环模式（运行方式）：本地选择一次性生效，发送时按 7378 口径对文本前置斜杠命令
    //（default 模式 command 为空、原样发送）；取出即复位，只对这一条消息生效
    const sessionKey: string = this.sessionId.length > 0 ? this.sessionId : this.chatId;
    const pick: LoopPick | null = takeLoopPick(sessionKey);
    const text: string = applyLoopCommand(this.draft.trim(), pick !== null ? pick.command : '');
    if ((text.length === 0 && this.attachments.length === 0) || this.sending || this.conn === null) {
      return;
    }
    const conn: QpConnection = this.conn;
    const parts: ChatInputPart[] = [];
    if (text.length > 0) {
      const tp: ChatInputPart = { type: 'text', text: text };
      parts.push(tp);
    }
    for (const p of this.attachmentParts()) {
      parts.push(p);
    }
    // 本地回显与发送内容同形：文本 + 附件分片（对齐 console，发出去的气泡即带附件）。
    // 附件引用在清空前取走一并落盘；落盘保留真实文本（纯附件消息为空串）。
    // 此前无文字时以附件名拼接代替文本，对账时该名永远匹配不到服务端消息（服务端纯附件
    // 用户消息无文本）→ 纯附件消息的本地回显常驻、附件永远不显示。
    const echoParts: DisplayPart[] = [];
    if (text.length > 0) {
      echoParts.push({ type: 'text', text: text });
    }
    const attachRefs: PendingAttachmentRef[] = this.attachments.map(
      (a: PendingAttachment): PendingAttachmentRef => {
        return { kind: this.displayKindOf(a.kind), url: a.url, fileName: a.fileName };
      });
    for (const r of attachRefs) {
      echoParts.push({ type: r.kind, url: r.url, name: r.fileName });
    }
    this.attachments = [];
    this.errorMsg = '';
    this.draft = '';
    this.sending = true;
    // 发送 = 回到底部并跟随新回合（随后 scrollBottom(true) 强制贴底）
    this.atBottom = true;
    const userMsg: DisplayMessage = { id: `user_${Date.now()}`, role: 'user', kind: 'message', parts: echoParts };
    const liveTurn: DisplayTurn = {
      id: `turn_${Date.now()}`, user: userMsg, responses: [], pending: true
    };
    const pendCtx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    const pend: PendingTurn = { turnId: liveTurn.id, text: text, attach: attachRefs };
    this.pending = pend;
    savePendingTurn(pendCtx, conn.baseUrl, conn.agentId, this.chatId, pend);
    const next: DisplayTurn[] = this.turns.slice();
    next.push(liveTurn);
    this.liveTurnId = liveTurn.id;
    this.turns = next;
    this.scrollBottom(true);
    this.stream = streamChat(conn.baseUrl, conn.token, conn.agentId,
      sessionKey, parts, sessionApproval(), this.userId,
      (delta: StreamDelta): void => {
        this.appendDelta(delta);
      },
      (error: string | null): void => {
        this.sending = false;
        this.stream = null;
        if (error !== null) {
          this.errorMsg = error;
          // 发送失败：本地在途记录一并清掉（对齐 7378 send 的 catch → clearPendingChatTurn）
          // 注意只清"在途标记"，列表里已挂上的那条回显不主动抹掉——消息多半已经发出去了，
          // 由紧随其后的重取按服务端实际内容对齐（服务端没有它，回显自然就退了）
          const c: QpConnection | null = this.conn;
          if (c !== null) {
            clearPendingTurn(getContext(this) as common.UIAbilityContext, c.baseUrl, c.agentId,
              this.chatId);
          }
          this.pending = null;
          this.liveTurnId = '';
        }
        // 流结束：先本地定稿（pending → false，id 与行对象不变）——过程组据此播「生成结束 →
        // 自动收起」的收合动画；随后再全量重取历史与服务端对齐（立刻重取会整表重建，
        // 收合变硬跳，正是"收起没有动画"的成因）。
        this.finalizeLiveTurn();
        setTimeout((): void => {
          this.reloadTurns();
        }, 420);
      });
    // 发送已受理：若这条消息带了循环命令（goal/mission/自定义），写「starting」到 phase
    // 注册表 —— 服务端 /loops/status 此刻可能仍回 idle（循环引擎还没激活），运行条按
    // 宽限判定保持「正在启动」，直到服务端报 running 后收敛到服务端阶段
    if (pick !== null && pick.command.length > 0) {
      setLoopPhase(sessionKey, 'starting', pick.modeId, pick.displayName);
    }
  }

  // 本地定稿在途回合：只翻 pending 标志（回合 id / 行对象引用不变）——过程组据此播自动收合动画，
  // 同时让「运行中」的转圈 / 生成态立即收敛；对齐服务端的动作交给随后的 reloadTurns。
  private finalizeLiveTurn(): void {
    if (this.liveTurnId.length === 0) {
      return;
    }
    const arr: DisplayTurn[] = this.turns.slice();
    for (let i = arr.length - 1; i >= 0; i--) {
      if (arr[i].id === this.liveTurnId) {
        if (arr[i].pending) {
          arr[i] = { id: arr[i].id, user: arr[i].user, responses: arr[i].responses, pending: false };
          this.turns = arr;
        }
        return;
      }
    }
  }

  private stop(): void {
    if (this.stream !== null) {
      this.stream.stop();
      this.stream = null;
    }
    this.sending = false;
    if (this.conn !== null) {
      const conn: QpConnection = this.conn;
      stopChat(conn.baseUrl, conn.token, conn.agentId, this.chatId)
        .then((): void => {
          this.reloadTurns();
        })
        .catch((): void => {
          // 停止失败不阻塞 UI：本地流已断开，仍重取已生成内容
          this.reloadTurns();
        });
    }
  }

  // ============ 标题栏菜单（对齐 7378 app/chat/[id].tsx 头部动作）============
  // 7378 菜单首项是「会话控制」（打开模型面板）；本页把模型/循环/审批做成常驻输入条
  // （components/SessionRuntimeBar），不再藏进菜单，故菜单只保留 置顶 / 归档 / 删除。
  private titleMenu(): HdsNavigationMenuContentOptions {
    const items: Array<HdsNavigationMenuItemOptions> = [];
    items.push({
      content: {
        label: this.chatPinned ? $r('app.string.chat_menu_unpin') : $r('app.string.chat_menu_pin'),
        // 图标 = 7378 同一枚 lucide（Pin / 已置顶时 PinOff），落到 base/media
        icon: this.chatPinned ? $r('app.media.pin_off') : $r('app.media.pin'),
        action: (): void => {
          this.togglePin();
        }
      }
    });
    items.push({
      content: {
        label: $r('app.string.chat_menu_archive'),
        icon: $r('app.media.archive'),
        action: (): void => {
          this.archiveChat();
        }
      }
    });
    items.push({
      content: {
        label: $r('app.string.chat_menu_delete'),
        icon: $r('app.media.trash_2'),
        action: (): void => {
          this.confirmDeleteChat();
        }
      }
    });
    return { value: items };
  }

  // 会话元信息（置顶态）：会话详情接口只回消息与运行状态，置顶态取自会话列表里本会话那一项
  private loadChatMeta(conn: QpConnection): void {
    fetchChats(conn.baseUrl, conn.token, conn.agentId, false).then((list: ChatInfo[]): void => {
      const chatId: string = this.chatId;
      const match: ChatInfo | undefined = list.find((c: ChatInfo): boolean => c.id === chatId);
      if (match !== undefined) {
        this.chatPinned = match.pinned;
      }
    }).catch((e: Object): void => {
      // 元信息取不到不影响会话本身，菜单里的置顶项按未置顶显示
    });
  }

  private togglePin(): void {
    const conn: QpConnection | null = this.conn;
    if (conn === null) {
      return;
    }
    const next: boolean = !this.chatPinned;
    pinChat(conn.baseUrl, conn.token, conn.agentId, this.chatId, next).then((): void => {
      this.chatPinned = next;
      this.getUIContext().getPromptAction().showToast({
        message: t(next ? $r('app.string.chat_menu_pin') : $r('app.string.chat_menu_unpin'))
      });
    }).catch((e: Object): void => {
      this.getUIContext().getPromptAction().showToast({
        message: t($r('app.string.chat_op_failed'))
      });
    });
  }

  // 归档：成功后退回会话列表（对齐 7378 archive → router.back()）
  private archiveChat(): void {
    const conn: QpConnection | null = this.conn;
    if (conn === null) {
      return;
    }
    setChatArchived(conn.baseUrl, conn.token, conn.agentId, this.chatId, true).then((): void => {
      this.closePage();
    }).catch((e: Object): void => {
      this.getUIContext().getPromptAction().showToast({
        message: t($r('app.string.chat_op_failed'))
      });
    });
  }

  // 删除：二次确认（对齐 7378 actionMenu 的 confirmDelete 态），成功后退回会话列表
  private confirmDeleteChat(): void {
    this.getUIContext().showAlertDialog({
      title: $r('app.string.chat_menu_delete_title'),
      message: $r('app.string.chat_menu_delete_msg'),
      primaryButton: {
        value: t($r('app.string.common_cancel')),
        action: (): void => {}
      },
      secondaryButton: {
        value: t($r('app.string.common_confirm_delete')),
        fontColor: $r('app.color.status_error'),
        action: (): void => {
          this.doDeleteChat();
        }
      }
    });
  }

  private doDeleteChat(): void {
    const conn: QpConnection | null = this.conn;
    if (conn === null) {
      return;
    }
    deleteChat(conn.baseUrl, conn.token, conn.agentId, this.chatId).then((): void => {
      this.closePage();
    }).catch((e: Object): void => {
      this.getUIContext().getPromptAction().showToast({
        message: t($r('app.string.chat_op_failed'))
      });
    });
  }

  private closePage(): void {
    const stack: NavPathStack | null = this.stack;
    if (stack !== null) {
      stack.pop(true);
    }
  }

  build() {
    HdsNavDestination() {
      Column() {
        Row() {
          // 输入条 = ArkUI Tabs 的「悬浮页签栏」：barPosition=End + barOverlap +
          // barFloatingStyle.systemMaterial 是官方「非标题栏、非 HdsTabs」的原生沉浸材质载体
          // （《组件适配沉浸光感》底部页签一节 / 《沉浸光感典型场景》底部 Tabs 悬浮 + ExpandSafeArea）。
          // 材质自带交互形变（interactive），栏体由系统绘制为两端纯圆胶囊；按压光由栏材质
          // lightEffect 承载（官方口径：为"按压、触摸"提供主题色光反馈）；键体自身不挂点光源
          // （预设光参在键外留方形轮廓光晕，真机实测"圆形外面有个方形"）。
          Tabs({ barPosition: BarPosition.End, index: 0 }) {
            TabContent() {
          // 悬浮层：Stack 底对齐——消息区（Column，铺满、底部留白）在下层，
          // 悬浮输入胶囊（圆角+玻璃底+实时磨砂+投影）浮于其上（对齐「悬浮圆角胶囊 + 沉浸光感」）。
          Stack({ alignContent: Alignment.Bottom }) {
            Column() {
            if (!this.listShown) {
              // 数据未到位用骨架屏占位（官方 FAQ faqs-arkui-1489：组件"突然出现"会造成闪动，
              // 建议用骨架屏）；历史到位后整块替换为真实列表。
              ChatSkeleton()
                .width('100%')
                .layoutWeight(1)
            } else {
            List({ scroller: this.scroller, initialIndex: this.initialRowIndex() }) {
              // 首项占位 = 沉浸标题栏高度：留白必须落在**列表内容**里，不能加在包住 List 的容器上
              // （容器 padding 会把视口裁到标题栏之下 → 消息滚不过去 → 磨砂/渐变模糊没有内容可模糊）
              ListItem() {
                Column().width('100%').height(UiTokens.topInset)
              }
              // 一行 = 一个 ListItem（用户气泡 / 消息段气泡 / 步骤组卡 / 工具产出媒体 / 待发占位）：
              // List 的虚拟化对每行生效，只有"正在长的那一行"参与重排（此前整回合一个 ListItem，
              // 流式期间每个 flush 都重排整个巨大 item，含数百行过程卡 → 滚动卡死）。
              // 末行也在这里（见 allRows 注释）：内容变化由行对象的 @ObjectLink 原地更新。
              ForEach(this.allRows(), (r: ConversationRow) => {
                ListItem() {
                  ChatRow({
                    row: r,
                    theme: this.theme,
                    baseUrl: this.conn !== null ? this.conn.baseUrl : '',
                    onToggleSteps: (k: string): void => {
                      this.toggleSteps(k);
                    },
                    onCollapseStep: (d: number): void => {
                      this.anchorCollapseStep(d);
                    },
                    selecting: this.selectingId === r.key,
                    onSelectingChange: (k: string, on: boolean): void => {
                      if (on) {
                        this.selCopied = false;
                        this.selectingId = k;
                      } else if (this.selectingId === k) {
                        this.selectingId = '';
                      }
                    },
                    onBodyMounted: (k: string): void => {
                      this.onBodyMounted(k);
                    }
                  })
                }
                // 出现过渡 = 淡入 + 轻微上移（过渡自带动画参数，不依赖外层 animateTo）。
                // 转场只在行**进出树**时触发（新块首次出现），过程组的高度插值开合不触发
                // 转场 —— 单列表项结构下开合不再有行增删，旧「body 行出入树叠转场」的
                // faq 1388 反模式已随结构消除
                .transition(rowTransition())
              }, (r: ConversationRow) => r.key)
              // 末项占位 = 悬浮输入胶囊 + 其上的运行状态条：滚到底时最后一条消息（含文件清单卡）
              // 停在两条之上，其余消息从两条下滚过被实时模糊；胶囊长高时同量加高（capsuleGrow）
              ListItem() {
                Column().width('100%').height(UiTokens.chatListEndInset + this.capsuleGrow())
              }
            }
            .layoutWeight(1)
            .width('100%')
            // 预加载（官方《List》组件文档"预加载"节）：空闲时隙预布局显示区域外上下各 cachedCount 行，
            // 滚动时新入屏行不再现场首次布局（markdown 行首布局最重），"减少滚动丢帧、提升流畅性"。
            // 取值按官方《长列表加载丢帧优化》建议 cachedCount=n/2（n=一屏行数，本列表约 5~7 行/屏）。
            .cachedCount(3)
            // 贴底跟随 regime = 用户真实位置（atBottom，isAtEnd 判定），不再用动画期临时开关：
            //  - true（贴底）：官方《List》stackFromEnd(true) 语义——内容不足一屏时整体贴底（短会话
            //    IM 口径，initialIndex 只定首个可见项、贴不了底），显示区域内条目变高/变矮时底边
            //    钉住、上方内容上移/下移（流式跟随与贴底态开合同一观感，开合自镜像）；
            //  - false（读长历史中段）：offset 恒定不重锚——开合锚定在按点，展开从锚点向下滑开、
            //    收起向上滑回锚点（收起 = 展开的精确镜像）。
            // regime 只在穿越贴底边界时翻转（syncBottomFab），一次开合内不变 → 动画中途无 regime
            // 切换，此前"动画期临时关 + 完成后开"的混合观感（顶边下移+底边上移）结构上消除。
            .stackFromEnd(this.atBottom)
            .scrollBar(BarState.Auto)
            // 底部不回弹（产品口径 2026-10-17）：会话页底是悬浮输入胶囊，冲底弹性下移会把
            // 末条消息顶到胶囊下；只保留顶边边缘效果
            .edgeEffect(EdgeEffect.Spring, { alwaysEnabled: true, effectEdge: EffectEdge.START })
            // 贴底跟随的判定 = 滚动位置是否真的到了内容末尾（Scroller.isAtEnd）。
            // 不能用「末项可见」当判据：末项是悬浮输入胶囊的留白（120vp 高），刚往上划一点它仍可见
            // → 被判成"还贴着底" → 下一次流式 flush 又 scrollEdge(Bottom) 把阅读位置拽回底部
            //（划到底后往上划会被跳回底部）。松手判定一次：划走即停止跟随，划回底部自动恢复。
            .onReachEnd((): void => {
              // 程序化 scrollEdge(Bottom)（流式 flush / 发送后贴底）也会触发 onReachEnd：
              // 手指还按在列表上时不据此判贴底 —— 否则"没真划到底"也被判成贴底。
              // 松手后的最终判底交给 onScrollStop 的 isAtEnd。
              if (this.userTouching) {
                return;
              }
              this.syncBottomFab();
            })
            // 手指一按即冻结自动贴底（userTouching 让 scrollBottom 直接返回，直到松手）
            .onTouch((e: TouchEvent): void => {
              if (e.type === TouchType.Down) {
                this.userTouching = true;
              } else if (e.type === TouchType.Up || e.type === TouchType.Cancel) {
                this.userTouching = false;
                this.syncBottomFab();
              }
            })
            // 滚动过程中持续同步：atBottom（isAtEnd）随手指实时更新 → 置底按钮出现/消失跟手，
            // 流式跟随也随之实时开/关（真的划离底部即停、划回底部即恢复）。
            // 官方口径：List 的 onScroll 自 API 12 废弃（布局后触发），用 onDidScroll 替代
            .onDidScroll((): void => {
              this.syncBottomFab();
            })
            .onScrollStop((): void => {
              this.syncBottomFab();
              // 滚动停稳 → 补采一次按钮脚下深浅（带去抖，不在滚动过程逐帧采）
              this.requestFabContrast(150);
            })
            // 点气泡外退「选择文本」态（回 markdown 渲染）：列表空白 / 未选中行卡上的点击
            // 冒泡到此处。选中的气泡卡片自带空 onClick 拦冒泡（行组件内），点它不误退；
            // 工具栏是 Stack 出流兄弟层（见 selBar 注释），栏体空 onClick 拦冒泡，点栏体不误退。
            .onClick((): void => {
              if (this.selectingId !== '') {
                this.selectingId = '';
              }
            })
            }

          // 底部固定块（错误行 / 待发附件 / 待审批卡）：只在确有内容时占位——整组抬到悬浮输入胶囊之上，
          // 避免被胶囊压住；无内容时不占位，消息列表保持整屏（底部实时模糊的前提）
          if (this.errorMsg.length > 0 || this.attachments.length > 0 || this.uploading
            || this.approvals.length > 0) {
          Column() {
          if (this.errorMsg.length > 0) {
            Text(this.errorMsg)
              .fontSize(UiTokens.fsCaption)
              .fontColor($r('app.color.status_error'))
              .width('100%')
              .padding({ left: 4, right: 4, bottom: 6 })
              .wordBreak(WordBreak.BREAK_ALL)
          }

          // 待发附件胶囊（点 ✕ 移除）；上传中显示转圈
          if (this.attachments.length > 0 || this.uploading) {
            Row() {
              if (this.uploading) {
                LoadingProgress()
                  .width(18)
                  .height(18)
                  .color(this.isDark ? this.theme.accentDark : this.theme.accent)
                  .margin({ right: 6 })
              }
              ForEach(this.attachments, (a: PendingAttachment) => {
                Row() {
                  Text(a.name)
                    .fontSize(UiTokens.fsCaption)
                    .fontColor($r('app.color.text_secondary'))
                    .maxLines(1)
                    .textOverflow({ overflow: TextOverflow.Ellipsis })
                    .constraintSize({ maxWidth: 180 })
                  Image($r('app.media.x'))
                    .width(12).height(12)
                    .fillColor($r('app.color.text_tertiary'))
                    .margin({ left: 6 })
                    .onClick((): void => {
                      this.removeAttachment(a.id);
                    })
                }
                .height(28)
                .padding({ left: 10, right: 10 })
                .margin({ right: 6, top: 4 })
                .borderRadius(UiTokens.chipRadius)
                .backgroundColor($r('app.color.card_bg'))
              }, (a: PendingAttachment) => a.id)
            }
            .width('100%')
            .alignItems(VerticalAlign.Center)
          }

          // 本会话待审批（对齐 RN：多条时显示计数，卡片显示第一条；composer 上方）
          if (this.approvals.length > 0) {
            Column() {
              if (this.approvals.length > 1) {
                Text(t($r('app.string.chat_approvals_count')).replace('%d',
                  this.approvals.length.toString()))
                  .fontSize(UiTokens.fsCaption)
                  .fontColor($r('app.color.text_tertiary'))
                  .margin({ bottom: 6 })
              }
              ApprovalCard({
                item: this.approvals[0],
                onDeny: (): void => {
                  this.actApproval(this.approvals[0], 'exact', true);
                },
                onApprove: (scope: string): void => {
                  this.actApproval(this.approvals[0], scope, false);
                }
              })
            }
            .width('100%')
            .alignItems(HorizontalAlign.Start)
          }
          }
          .width('100%')
          // 底部固定块（错误行/附件/审批）与胶囊顶的间距：胶囊长高时同量上抬
          .margin({ bottom: UiTokens.chatComposerInset + this.capsuleGrow() })
          }
            }
            .width('100%')
            .height('100%')
        // 磨砂背板：输入态磨砂底色的真正载体。位置 = 系统材质之下、消息列表之上（Stack 内
        // 声明在消息列之后即盖住列表，而悬浮页签栏是框架层、天然在 TabContent 之上）。
        // 为什么不在 tabBar 内做：框架把 tabBar 内容钳在胶囊内容区（左右 12vp / 上下 4vp
        // inset，真机实测，显式更大尺寸被布局钳回）——栏内叠层盖不到胶囊边，背后亮色消息
        // 从 rim 透出、叠层直边横切亮 rim 呈方形块。背板在全屏 Stack 里给满胶囊几何
        //（同宽/同高/同半径/同底边距），栏体材质的实时磨砂模糊直接作用在背板上 →
        // 底色均匀且保留磨砂质感，胶囊边缘不露亮带。
        // opacity 由 kbFrost 260ms 交叉淡入淡出（applyKeyboardFrost）；输入 1→5 行长高时
        // 随 capsuleBarH()/capsuleBarW() 同量长大（跟随动画与栏体同源）；hitTest None
        // 不挡列表滚动（胶囊区触点仍由上方页签栏接管，与背板无关）。
        Column()
          .width(this.capsuleBarW())
          .height(this.capsuleBarH())
          .borderRadius(this.capsuleBarH() / 2)
          .backgroundColor($r('app.color.composer_frost_bg'))
          .margin({ bottom: this.composerBottom() })
          .opacity(this.kbFrost)
          .hitTestBehavior(HitTestMode.None)
        // 「一键回到底部」：浮在消息区底部、让开输入胶囊与运行状态条（对齐 console 用的 SDK
        // BubbleList 里那颗 ScrollToBottom：圆形下箭头、贴底居中、距底超过阈值才出现）。
        // 隐藏态是"下移自身高度 + 透明 + 不接收点击"，进出场 200ms —— 与 console 的 0.2s 过渡一致。
        // 外观载体用 Toggle(ToggleType.Button) 而不是 Button：本按钮在内容区，官方口径下
        // Button 挂组件级 systemMaterial 会被打印 `Material inactive: out of scope` 而完全不生效
        // （真机实证），而 Toggle 在「全页面生效」名单内、官方明确 `ToggleType.Button` 效果与
        // Button 组件设置沉浸光感相同（聊天页底部状态条三枚芯片同一路径）。
        // isOn 固定 false：只借材质与交互形变，不留选中态（每次点按都当作"回到底部"）。
        Toggle({ type: ToggleType.Button, isOn: false }) {
          SymbolGlyph($r('sys.symbol.arrow_down'))
            .fontSize(20)
            // 字色随按钮脚下消息区明暗采样切换（fabDark，见 requestFabContrast）；
            // 200ms 插值由下方既有 .animation 覆盖
            .fontColor([this.fabGlyphColor()])
        }
        .width(BOTTOM_FAB_SIZE)
        .height(BOTTOM_FAB_SIZE)
        .borderRadius(BOTTOM_FAB_SIZE / 2)
        // 透明底：玻璃观感由沉浸材质给（官方示例即「透明底 + ImmersiveMaterial」）
        .backgroundColor(Color.Transparent)
        // 沉浸材质 THIN：档位随设备算力自适应、跟随系统「沉浸光感」开关；interactive = 交互形变、
        // lightEffect 取服务端同步的主题色（ThemeManager 的快照，console 主题改色这边跟着变）
        .systemMaterial(new uiMaterial.ImmersiveMaterial({
          style: uiMaterial.ImmersiveStyle.THIN,
          interactive: true,
          lightEffect: { color: this.theme.accent }
        }))
        .selectedColor(Color.Transparent)
        .shadow({ radius: 12, color: '#40000000', offsetX: 0, offsetY: 2 })
        .margin({ bottom: this.bottomFabOffset() })
        .opacity(this.atBottom ? 0 : 1)
        .translate({ y: this.atBottom ? BOTTOM_FAB_SIZE : 0 })
        .hitTestBehavior(this.atBottom ? HitTestMode.None : HitTestMode.Default)
        .animation({ duration: BOTTOM_FAB_ANIM_MS, curve: Curve.EaseOut })
        // Toggle 每次点按都翻转内部开关态 → 不区分方向都触发动作（本按钮没有"取消"语义）
        .onChange((isOn: boolean): void => {
          this.jumpToBottom();
        })
        // 魔法命令弹层：浮在输入胶囊之上（定位口径同底部固定块：margin 让开胶囊，胶囊长高时
        // 随 capsuleBarH() 同量上抬）。列表最高 210vp、框内滚动（对齐 console cascader 的
        // max-height 210px）；行 = 命令（主题色、固定列宽）+ 描述（两行截断）。点行替换输入行
        // 为 "/command "，不自动发送。z 序最后 = 打开时盖住回到底部按钮。
        if (this.slashOpen) {
          Scroll() {
            Column() {
              ForEach(this.slashItems, (it: SlashItem) => {
                Row() {
                  Text(it.command)
                    .fontSize(UiTokens.fsBody)
                    .fontWeight(FontWeight.Medium)
                    .fontColor(this.isDark ? this.theme.accentDark : this.theme.accent)
                    .maxLines(1)
                    .textOverflow({ overflow: TextOverflow.Ellipsis })
                    .constraintSize({ minWidth: 88 })
                  Text(it.description)
                    .fontSize(UiTokens.fsSecondary)
                    .fontColor($r('app.color.text_secondary'))
                    .maxLines(2)
                    .textOverflow({ overflow: TextOverflow.Ellipsis })
                    .layoutWeight(1)
                    .margin({ left: 10 })
                }
                .width('100%')
                .alignItems(VerticalAlign.Center)
                .padding({ left: 14, right: 14, top: 9, bottom: 9 })
                .onClick((): void => {
                  this.pickSlash(it);
                })
              }, (it: SlashItem) => it.value)
            }
            .width('100%')
          }
          .width('100%')
          .constraintSize({ maxHeight: 210 })
          .scrollBar(BarState.Auto)
          .edgeEffect(EdgeEffect.None)
          .borderRadius(UiTokens.cardRadius)
          .backgroundColor($r('app.color.card_bg'))
          .shadow({ radius: 16, color: '#33000000', offsetX: 0, offsetY: 6 })
          .padding({ top: 6, bottom: 6 })
          .margin({ bottom: this.composerBottom() + this.capsuleBarH() + 10 })
          .transition(TransitionEffect.OPACITY.animation({ duration: 140, curve: Curve.EaseOut }))
        }
        // 「选择文本」态工具栏（落位与理由见 selBar 注释）：出流兄弟层、贴标题栏底边。
        // 包装列 = 满尺寸透明命中层（Transparent：工具栏自身与下层 List 都参与命中，
        // 官方口径，runtimeRow 同路径实证）；justifyContent Start + 工具栏自身顶距定落位。
        Column() {
          if (this.selBarVisible()) {
            this.selBar()
          }
        }
        .width('100%')
        .height('100%')
        .justifyContent(FlexAlign.Start)
        .hitTestBehavior(HitTestMode.Transparent)
        }
        .width('100%')
        .height('100%')
        // id 供字体对比度采样（theme/FabContrast）：截本 Stack 最近一帧 → 读按钮脚下区域判深浅
        .id('chatFabHost')
        .onAreaChange((_old: Area, now: Area): void => {
          const w: number = typeof now.width === 'number' ? now.width as number : 0;
          const h: number = typeof now.height === 'number' ? now.height as number : 0;
          if (w === this.fabHostWVp && h === this.fabHostHVp) {
            return;
          }
          const first: boolean = this.fabHostWVp <= 0;
          this.fabHostWVp = w;
          this.fabHostHVp = h;
          if (first && w > 0) {
            this.requestFabContrast(500);
          }
        })
        // 左右留白挂在滚动区容器（外层 Stack）上，不是最外层 Column：外层铺满屏幕左右，
        // 输入条父容器（Tabs）才能扩到屏幕边缘，不在两侧露出窗口底色
        .padding({ left: UiTokens.pageHMargin, right: UiTokens.pageHMargin })
        // 左右留白条不被 List 覆盖：点它同样退「选择文本」态（与列表空白同口径）
        .onClick((): void => {
          if (this.selectingId !== '') {
            this.selectingId = '';
          }
        })
            }
            .tabBar(this.composerBar())
          }
          .barOverlap(true)
          .scrollable(false)
          // 胶囊只承载输入行（状态条已移出，浮在胶囊之上）；高度随输入内容长高联动
          //（capsuleBarH()：内容区实测高 + 上下 chrome 9vp，单行时 = 基线 59）
          .barHeight(this.capsuleBarH())
          // 会话运行状态条：浮层定位在胶囊之上 3vp（官方 overlay：不重新渲染 TabBar 即可叠加组件）
          .overlay(this.runtimeRow(), {
            align: Alignment.Bottom,
            offset: {
              x: 0,
              y: -(this.composerBottom() + this.capsuleBarH() + UiTokens.chatRuntimeRowGap)
            }
          })
          .barFloatingStyle({
            // 悬浮栏默认按内容自适应宽度（实测输入框被压到 112px）→ 显式给宽度：
            // 窄屏 344vp + 两侧 16vp = 376vp = 手机全宽（1316px @3.5）；宽屏（折叠屏展开 /
            // 平板竖屏 / PC）取实际内容列宽，见 capsuleBarW()
            barWidth: {
              smallBarWidth: this.capsuleBarW(),
              mediumBarWidth: this.capsuleBarW(),
              largeBarWidth: this.capsuleBarW()
            },
            barSideMargin: UiTokens.pageHMargin,
            // 栏体背板遮罩默认近黑：按压/拖动时栏体形变，遮罩露出即"黑边遮挡"（真机拖拽实测
            // 遮罩节点 BackgroundMask x56-1260 y2531-2832，漏出的行取值为 2~5）→ 置透明
            maskColor: Color.Transparent,
            // 键盘开启时框架仍按缓存旧预留高度把浮条再抬高 44px（页已按实测顶边对齐，
            // 浮条却停在旧底边上方）——用同一补偿量反向抵消，使栏体底边贴住键盘上沿
            barBottomMargin: this.composerBottom(),
            // 按压光由栏材质 lightEffect 承载（官方口径：为"按压、触摸"提供主题色光反馈）；
            // 键体自身不挂点光源（预设光参在键外留方形轮廓光晕，真机实测）；
            // 保留 interactive 交互形变
            systemMaterial: new uiMaterial.ImmersiveMaterial({
              style: uiMaterial.ImmersiveStyle.THIN,
              interactive: true,
              lightEffect: { color: this.theme.accent }
            })
          })
          .width('100%')
          .height('100%')
          // 框架陈旧 inset 把 Tabs 压短（真机底边 1107 vs 键盘顶 1151）→ 整体下移补偿；
          // 用 Tabs 自身实测底边判定，正常会话 gap=0 不动
        }
        .width(wideClampW(this.pageW))
        .layoutWeight(1)
        .justifyContent(FlexAlign.Center)
    }
      .width('100%')
      .height('100%')
      .padding({ bottom: this.kbBottomVp })
      .backgroundColor($r('app.color.page_bg'))
      .onAreaChange(this.onChatArea)
      // 沉浸到状态栏 / 导航栏 / 屏幕左右两侧：绘制区扩到安全区之外（官方 expandSafeArea），
      // 否则上带显示系统壁纸、下带露出导航条底色、左右露出窗口底色的黑带
      .expandSafeArea([SafeAreaType.SYSTEM],
        [SafeAreaEdge.TOP, SafeAreaEdge.BOTTOM, SafeAreaEdge.START, SafeAreaEdge.END])
    }
    // 内容也扩到安全区外（布局级）：官方 NavDestination.ignoreLayoutSafeArea，
    // 与 expandSafeArea 同时设置时它优先；前置条件要求标题栏隐藏或 STACK 模式
    .onShown((): void => {
      this.applySessionApproval();
      this.resyncKeyboardInset();
    })
    // 二级页转场：整页自右水平覆盖进来（退出滑回右侧）——见 services/NavPush.slideCoverTransition。
    // 系统默认档在分栏下动的是"内容区左边缘 0 → 分栏位"，观感从左侧摊过来（判"方向反了"），
    // 故改用官方 customTransition（NavDestinationTransitionDelegate）自己定方向。
    .customTransition((op: NavigationOperation, isEnter: boolean)
      : Array<NavDestinationTransition> | undefined => slideCoverTransition(op, isEnter,
        (v: string): void => { this.pageX = v; }))
    .translate({ x: this.pageX })
    // 返回键：本页显式出栈并消费。单栏/分栏下系统返回都不会自动弹本页
    // （平板横屏实测按返回直接退到桌面），出栈后右栏回到空态占位（QwenPaw 形象）。
    .onBackPressed((): boolean => {
      // 选择文本态：返回手势先退出选择态（回 markdown 渲染），不弹页——
      // 与「点气泡外」同义的第二退出路径，避免用户误以为退出了会话
      if (this.selectingId !== '') {
        this.selectingId = '';
        return true;
      }
      const stack: NavPathStack | null = this.stack;
      if (stack !== null && stack.size() > 0) {
        stack.pop();
      }
      return true;
    })
    .ignoreLayoutSafeArea([LayoutSafeAreaType.SYSTEM],
      [LayoutSafeAreaEdge.TOP, LayoutSafeAreaEdge.BOTTOM, LayoutSafeAreaEdge.START, LayoutSafeAreaEdge.END])
    .titleBar({
      // 静止态即磨砂（聊天详情页）：默认配置是"静止透明、动一下才出磨砂"，
      // 官方 GRADIENT_BLUR + enableScrollEffect=false 组合的 originalStyle 背景色默认 #99000000，
      // 进页面即有一条清晰磨砂顶栏；内容滚过时继续被模糊。
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
          mainTitle: this.chatName.length > 0 ? this.chatName : $r('app.string.chat_title')
        },
        // 标题栏菜单（置顶 / 归档 / 删除）：对齐 7378 chat/[id].tsx 头部动作菜单
        menu: this.titleMenu()
      },
      // 与主页一致：标题栏不避让安全区向上铺到状态栏区域，组件安全区关闭（否则状态栏带露系统底）
      avoidLayoutSafeArea: false,
      enableComponentSafeArea: false
    })
    // 归档/删除成功后需要退回会话列表：页面自身没有导航栈入参，
    // 按官方 NavDestinationContext.pathStack 在 ready 时取一次
    .onReady((ctx: NavDestinationContext): void => {
      this.stack = ctx.pathStack;
    })
  }
}

// ============ 会话详情页用的显示纯逻辑 ============
// 行渲染（气泡 / 步骤组卡 / 媒体 / 分发器）已拆到 components/ChatRows.ets；
// 这里只留页面自身用到的分片辅助函数。

// 行缓存判重：消息未变化的段在两次 flush 间保持同一实例（mergeDeltaInto 只替换正在写入的段，
// 响应分组也只重排引用）→ 逐元素比引用即可，命中就跳过 r.messages 赋值，该行不刷新。
function sameMessageRefs(a: DisplayMessage[], b: DisplayMessage[]): boolean {
  if (a === b) {
    return true;
  }
  if (a.length !== b.length) {
    return false;
  }
  for (let i = 0; i < a.length; i++) {
    if (a[i] !== b[i]) {
      return false;
    }
  }
  return true;
}

// 媒体分片每次 rows() 都从工具输出重建（新对象）→ 按内容签名比（type/url/name 齐才算同一条）
function samePartSig(a: DisplayPart[], b: DisplayPart[]): boolean {
  if (a === b) {
    return true;
  }
  if (a.length !== b.length) {
    return false;
  }
  for (let i = 0; i < a.length; i++) {
    const x: DisplayPart = a[i];
    const y: DisplayPart = b[i];
    if (x.type !== y.type || x.url !== y.url || x.name !== y.name) {
      return false;
    }
  }
  return true;
}

// 追加文本到分片数组：合并进末尾 text 分片，否则新起一片（流式 delta 归并用）。
// 空文本直接返回 —— 工具段本就没有文本载荷，不该因此多挂一个空 text 分片；
// 尚无文本分片时纯空白（服务端会发 "\n\n" 这类分片）也跳过，否则会先落一张空卡再等正文。
function appendText(parts: DisplayPart[], text: string): void {
  if (text.length === 0) {
    return;
  }
  const lastIdx: number = parts.length - 1;
  const hasText: boolean = lastIdx >= 0 && parts[lastIdx].type === 'text';
  if (!hasText && text.trim().length === 0) {
    return;
  }
  if (lastIdx >= 0 && parts[lastIdx].type === 'text') {
    const lp: DisplayPart = parts[lastIdx];
    parts[lastIdx] = { type: 'text', text: (lp.text !== undefined ? lp.text : '') + text };
  } else {
    const np: DisplayPart = { type: 'text', text: text };
    parts.push(np);
  }
}

// 卡片插入/移除的过渡：淡入淡出 + 轻微上移。显式给两段各自的 animation 参数 —— 过渡不依赖
// 外层 animateTo（把数据写入包进 animateTo 会把同一帧里"正在变高的流式文本"一起补间，整块会一直
// 呼吸/闪；官方 faqs-arkui-622 也把"过渡写错/依赖外部动画上下文"列为闪动来源）。
function rowTransition(): TransitionEffect {
  const anim: AnimateParam = { duration: EXPAND_ANIM_MS, curve: Curve.EaseOut };
  return TransitionEffect.OPACITY.animation(anim)
    .combine(TransitionEffect.translate({ y: 12 }).animation(anim));
}

// 该分段是否有可显示内容：按**可见性**判定（非空白文本 / 媒体分片 / 错误）——服务端会下发 text
// 只有 "\n\n" 的 message 记录（实测同一会话 26 条），按"分片非空"判定会放过它，结果渲染成一张
// 只有卡片底色的空白卡（真机表现为"每个气泡中间夹着一张空白卡"）。
function messagesHaveContent(msgs: DisplayMessage[]): boolean {
  for (const m of msgs) {
    if (rowHasVisibleContent(m)) {
      return true;
    }
  }
  return false;
}
