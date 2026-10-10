/*
 * 会话详情 —— 移植 PR #7378 apps/qwenpaw-mobile/app/chat/[id].tsx 一期形态：
 *   历史（GET /api/chats/{id}）+ 输入发送（POST /api/console/chat，stream:true）流式追加 + 停止当前轮。
 * 路由参数：{ chatId, chatName }（routerMap 名 chat，由「会话」tab 的会话行打开）。
 */

import { HdsNavDestination, ScrollEffectType, BlurStrategy, hdsMaterial } from '@kit.UIDesignKit';
import { emitter } from '@kit.BasicServicesKit';
import { common, Configuration, ConfigurationConstant } from '@kit.AbilityKit';
import { image } from '@kit.ImageKit';
import { util } from '@kit.ArkTS';
import { uiMaterial, KeyboardAvoidMode, window, curves } from '@kit.ArkUI';
import { QpConnection, loadConnection } from '../services/ConnectionStore';
import {
  DisplayTurn, DisplayMessage, DisplayPart, ChatSnapshot, fetchChatMessages, streamChat, stopChat,
  ChatStreamHandle, ChatInputPart, UploadResult, uploadAttachment, CHAT_CLOSED_EVENT
} from '../services/ChatDetailService';
import { pickFiles, removeTemp, PickedFile } from '../services/AttachmentPicker';
import { StreamDelta } from '../services/SseParser';
import { ApprovalInfo, fetchApprovals, approveRequest, denyRequest } from '../services/ApprovalsService';
import { ApprovalCard } from '../components/ApprovalCard';
import { ThemeManager, ThemeSnapshot, ThemeListener } from '../theme/ThemeManager';
import { UiTokens } from '../theme/UiTokens';
import { blendHex } from '../theme/Accent';
import { PRESS_SCALE, PressLatch, pressEffect, pressTouch } from '../theme/PressFx';

@Builder
export function ChatDetailPageBuilder(_name: string, param: Object) {
  ChatDetailPage({ params: param })
}

// 待发附件（已上传成功，发送时转成 content 分片）
interface PendingAttachment {
  id: string;
  name: string;
  kind: string;     // image / video / audio / file
  url: string;
  fileName: string;
}

@Component
export struct ChatDetailPage {
  params: Object = new Object();
  @State chatId: string = '';
  @State chatName: string = '';
  @State turns: DisplayTurn[] = [];
  @State draft: string = '';
  @State sending: boolean = false;
  @State attachments: PendingAttachment[] = [];   // 已上传待发送的附件
  // 本会话待审批（对齐 RN chat/[id].tsx：root_session_id === chat.session_id || chat.id）
  @State approvals: ApprovalInfo[] = [];
  @State uploading: boolean = false;              // 附件上传中（按钮转圈）
  @State loading: boolean = true;
  @State errorMsg: string = '';
  @State isDark: boolean = false;
  @State theme: ThemeSnapshot = ThemeManager.get().snapshot();
  // 发送/停止按钮的按压态：0=发送 1=停止，-1=无（内容区材质不生效 → 按压反馈用通用属性自绘）
  @State btnPressed: number = -1;
  private btnLatch: PressLatch = new PressLatch();
  private scroller: Scroller = new Scroller();
  private stream: ChatStreamHandle | null = null;
  // 发送用的 session_id（对齐 RN store：sessionId = chat.session_id，与 chatId 可能不同）
  private sessionId: string = '';
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
      this.errorMsg = this.t($r('app.string.approval_failed'));
    }
  }
  private streamMsgId: string = '';
  private conn: QpConnection | null = null;
  private themeListener: ThemeListener | null = null;

  // 发送(0)/停止(1)按钮按压：缩放动画与点光源由 pressTouch/pressEffect 统一驱动
  private canSend(): boolean {
    return this.draft.trim().length > 0;
  }

  // 键盘避让模式：本页必须用 OFFSET（页面整体上移）。用 RESIZE 时页面被压缩，
  // 悬浮页签栏（输入条）会被压扁并贴到键盘上沿，观感"键盘遮挡输入框"。
  private prevKeyboardAvoidMode: KeyboardAvoidMode | null = null;
  // 键盘高度（vp）：避让模式设 NONE 后页面不再被压缩/上抬，改由本页按此值让出底部，
  // 否则悬浮输入条会被键盘盖住（RESIZE 下则是被压扁贴在键盘上沿）。
  @State keyboardInset: number = 0;
  private kbWindow: window.Window | null = null;
  private kbListener: ((data: window.AvoidAreaOptions) => void) | null = null;

  private onBtnTouch(idx: number, e: TouchEvent): void {
    pressTouch(this.getUIContext(), e, this.btnLatch, (v: boolean): void => {
      this.btnPressed = v ? idx : -1;
    });
  }

  // 输入条内容（挂在 Tabs 悬浮页签栏内）：材质、弹性形变、纯圆两端都由
  // barFloatingStyle.systemMaterial 提供，故控件一律透明底，让材质层透出。
  @Builder
  composerBar() {
        Row() {
          Button() {
            if (this.uploading) {
              LoadingProgress()
                .width(20)
                .height(20)
                .color(this.isDark ? this.theme.accentDark : this.theme.accent)
            } else {
              SymbolGlyph($r('sys.symbol.plus'))
                .fontSize(20)
                // 可变字重加粗描边（默认字重下真机实测描边 5~6px，抬到 600 约 +2px）
                .fontWeight(600)
                .fontColor([$r('app.color.btn_gray_text')])
            }
          }
          .type(ButtonType.Normal)
          .width(40)
          .height(40)
          .padding(0)
          // 同上：透明底，避免在材质层上再压一块实底
          .backgroundColor(Color.Transparent)
          .borderWidth(1)
          .borderColor(this.isDark ? '#3DFFFFFF' : '#4D000000')
          .borderRadius(20)
          .enabled(!this.uploading)
          .scale({ x: this.btnPressed === 2 ? PRESS_SCALE : 1, y: this.btnPressed === 2 ? PRESS_SCALE : 1 })
          .stateEffect(false)
          .visualEffect(pressEffect(this.btnPressed === 2))
          .onTouch((e: TouchEvent): void => {
            this.onBtnTouch(2, e);
          })
          .onClick((): void => {
            this.attach();
          })
          .margin({ right: 8 })

          TextInput({ text: $$this.draft, placeholder: $r('app.string.chat_input_placeholder') })
            .layoutWeight(1)
            .height(42)
            .fontSize(UiTokens.fsBody)
            // 透明：让胶囊的材质层（磨砂 + 受光渐层）连续透出，而不是被一层实底盖住
            .backgroundColor(Color.Transparent)
            .fontColor($r('app.color.input_text'))
            .placeholderColor($r('app.color.placeholder'))
            .borderRadius(21)
            .enterKeyType(EnterKeyType.Send)
            .onSubmit((): void => {
              this.send();
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
        // 竖直方向不留内边距、高度交给栏体内容区（实测悬浮栏本体 203px、内容区 175px）：
        // 写死 58 + 上下各 8 内边距需要 203px > 内容区 175px → 行被压扁、内容贴底
        // 表现为"按钮没有垂直居中"。
        .padding({ left: 3, right: 3 })
        .alignItems(VerticalAlign.Center)
        .height('100%')
  }

  aboutToAppear(): void {
    const rec: Record<string, Object> = this.params as Record<string, Object>;
    const id: Object = rec['chatId'];
    const name: Object = rec['chatName'];
    this.chatId = typeof id === 'string' ? id as string : '';
    this.chatName = typeof name === 'string' ? name as string : '';
    const sid: Object = rec['sessionId'];
    this.sessionId = typeof sid === 'string' && (sid as string).length > 0 ? sid as string : this.chatId;
    this.prevKeyboardAvoidMode = this.getUIContext().getKeyboardAvoidMode();
    window.getLastWindow(getContext(this)).then((w: window.Window): void => {
      this.kbWindow = w;
      const cb = (data: window.AvoidAreaOptions): void => {
        if (data.type === window.AvoidAreaType.TYPE_KEYBOARD) {
          const inset: number = data.area.bottomRect.height / 3.5;
          // 显式动画（官方 animateTo）：本身直接改 padding 是瞬跳，键盘弹起/收起会"啪"一下；
          // 这里给布局变化插入过渡，恢复与框架避让同感的起落动画。
          // 弹簧曲线（springMotion）比时长曲线更有"弹"感；用弹簧时 duration 不生效，
          // 节奏由 response/dampingFraction 决定（响应越快越跟手，阻尼越小回弹越明显）。
          this.getUIContext().animateTo({ curve: curves.springMotion(0.4, 0.68) }, (): void => {
            this.keyboardInset = inset;
          });
        }
      };
      this.kbListener = cb;
      w.on('avoidAreaChange', cb);
    });
    this.getUIContext().setKeyboardAvoidMode(KeyboardAvoidMode.NONE);
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    this.isDark = ctx.config.colorMode === ConfigurationConstant.ColorMode.COLOR_MODE_DARK;
    this.themeListener = (snap: ThemeSnapshot): void => {
      this.theme = snap;
    };
    ThemeManager.get().subscribe(this.themeListener);
    ThemeManager.get().load(ctx).then((): void => {
      this.theme = ThemeManager.get().snapshot();
    });
    this.loadHistory();
    // 与 Console 保持同步（对齐 RN chat/[id].tsx 的 useFocusEffect + setInterval 轮询）：
    // 定时静默重取历史，Console 侧新消息也能进来；流式进行中不打扰
    this.pollTimer = setInterval((): void => {
      this.refreshHistory();
      this.refreshApprovals();
    }, 3000);
  }

  aboutToDisappear(): void {
    if (this.kbWindow !== null && this.kbListener !== null) {
      this.kbWindow.off('avoidAreaChange', this.kbListener);
      this.kbWindow = null;
      this.kbListener = null;
    }
    const kb: KeyboardAvoidMode | null = this.prevKeyboardAvoidMode;
    if (kb !== null) {
      this.getUIContext().setKeyboardAvoidMode(kb);
      this.prevKeyboardAvoidMode = null;
    }
    if (this.pollTimer >= 0) {
      clearInterval(this.pollTimer);
      this.pollTimer = -1;
    }
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

  onConfigurationUpdate(newConfig: Configuration): void {
    this.isDark = newConfig.colorMode === ConfigurationConstant.ColorMode.COLOR_MODE_DARK;
  }

  // 静默重取历史：Console 侧新增消息时同步过来（本地刚发的那条在服务端也已在列，条数一致则不动）
  private async refreshHistory(): Promise<void> {
    if (this.sending || this.conn === null) {
      return;
    }
    try {
      const conn: QpConnection = this.conn;
      const snap: ChatSnapshot = await fetchChatMessages(conn.baseUrl, conn.token, conn.agentId,
        this.chatId);
      if (snap.turns.length !== this.turns.length) {
        this.turns = snap.turns;
        this.scrollBottom();
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
      this.turns = snap.turns;
      this.scrollBottom();
    } catch (e) {
      // 重取失败：保留本地流式内容，下一轮轮询再对齐
    }
  }

  private async loadHistory(): Promise<void> {
    const ctx: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
    this.loading = true;
    this.errorMsg = '';
    try {
      const conn: QpConnection | null = await loadConnection(ctx);
      if (conn === null) {
        this.errorMsg = this.t($r('app.string.chat_no_conn'));
        return;
      }
      this.conn = conn;
      this.refreshApprovals();
      const snap: ChatSnapshot = await fetchChatMessages(conn.baseUrl, conn.token, conn.agentId,
        this.chatId);
      this.turns = snap.turns;
      if (snap.running) {
        // 服务端上一轮仍在跑：先取到历史，用户可继续输入（一期不做自动重连流）
        this.errorMsg = '';
      }
      this.scrollBottom();
    } catch (e) {
      this.errorMsg = (e as Error).message;
    } finally {
      this.loading = false;
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

  private scrollBottom(): void {
    setTimeout((): void => {
      this.scroller.scrollEdge(Edge.Bottom);
    }, 40);
  }

  // 流式增量归并（在 7378 基础上增强：message 实时进 answer；reasoning/tool 的流式文本
  // 亦实时累积进 process 对应消息，逐字呈现思考 / 工具文本，不再等流结束 reload）。
  // 归并进最后一个 turn（即发送时 push 的 live turn）。
  private appendDelta(delta: StreamDelta): void {
    if (delta.text.length === 0) {
      return;
    }
    const arr: DisplayTurn[] = this.turns.slice();
    const li: number = arr.length - 1;
    if (li < 0) {
      return;
    }
    const t: DisplayTurn = arr[li];
    arr[li] = delta.kind === 'message' ? this.withAnswerDelta(t, delta) : this.withProcessDelta(t, delta);
    this.turns = arr;
    this.scrollBottom();
  }

  // message delta → 追加到 answer 文本分片
  private withAnswerDelta(t: DisplayTurn, delta: StreamDelta): DisplayTurn {
    const prev: DisplayMessage | null = t.answer;
    const parts: DisplayPart[] = prev !== null ? prev.parts.slice() : [];
    appendText(parts, delta.text);
    const ansId: string = prev !== null ? prev.id
      : (this.streamMsgId.length > 0 ? this.streamMsgId : `ans_${Date.now()}`);
    const answer: DisplayMessage = { id: ansId, role: 'assistant', kind: 'message', parts: parts };
    const nt: DisplayTurn = {
      id: t.id, user: t.user, process: t.process.slice(), answer: answer,
      resultMedia: t.resultMedia.slice(), pending: true
    };
    return nt;
  }

  // reasoning / tool delta → 按 messageId 累积进 process 中对应消息的文本分片
  private withProcessDelta(t: DisplayTurn, delta: StreamDelta): DisplayTurn {
    const proc: DisplayMessage[] = t.process.slice();
    let idx: number = -1;
    for (let i = 0; i < proc.length; i++) {
      if (proc[i].id === delta.messageId) {
        idx = i;
        break;
      }
    }
    if (idx < 0) {
      const parts: DisplayPart[] = [];
      appendText(parts, delta.text);
      const id: string = delta.messageId.length > 0 ? delta.messageId : `proc_${Date.now()}`;
      const m: DisplayMessage = { id: id, role: 'assistant', kind: delta.kind, parts: parts };
      proc.push(m);
    } else {
      const cur: DisplayMessage = proc[idx];
      const parts: DisplayPart[] = cur.parts.slice();
      appendText(parts, delta.text);
      const nm: DisplayMessage = {
        id: cur.id, role: cur.role, kind: cur.kind, parts: parts,
        toolName: cur.toolName, toolState: cur.toolState, toolCallId: cur.toolCallId,
        toolInput: cur.toolInput, toolOutput: cur.toolOutput
      };
      proc[idx] = nm;
    }
    const nt: DisplayTurn = {
      id: t.id, user: t.user, process: proc, answer: t.answer,
      resultMedia: t.resultMedia.slice(), pending: true
    };
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
      this.errorMsg = this.t($r('app.string.chat_attach_failed'));
    } finally {
      this.uploading = false;
    }
  }

  private removeAttachment(id: string): void {
    this.attachments = this.attachments.filter((a: PendingAttachment): boolean => a.id !== id);
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
    const text: string = this.draft.trim();
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
    // 本地回显：无文字时以附件名代替（附件本体随 content 分片发送）
    const echo: string = text.length > 0 ? text
      : this.attachments.map((a: PendingAttachment): string => a.name).join('、');
    this.attachments = [];
    this.errorMsg = '';
    this.draft = '';
    this.sending = true;
    this.streamMsgId = '';
    const userPart: DisplayPart = { type: 'text', text: echo };
    const userMsg: DisplayMessage = { id: `user_${Date.now()}`, role: 'user', kind: 'message', parts: [userPart] };
    const liveTurn: DisplayTurn = {
      id: `turn_${Date.now()}`, user: userMsg, process: [], answer: null, resultMedia: [], pending: true
    };
    const next: DisplayTurn[] = this.turns.slice();
    next.push(liveTurn);
    this.turns = next;
    this.scrollBottom();
    this.stream = streamChat(conn.baseUrl, conn.token, conn.agentId,
      this.sessionId.length > 0 ? this.sessionId : this.chatId, parts,
      (delta: StreamDelta): void => {
        this.appendDelta(delta);
      },
      (error: string | null): void => {
        this.sending = false;
        this.stream = null;
        if (error !== null) {
          this.errorMsg = error;
        }
        // 流结束（成功或失败）都全量重取历史：补齐 reasoning/tool 块，并把 live turn 与
        // 服务端已落库的真实消息对齐（对齐 RN store.send 的 finally → loadChat）。
        this.reloadTurns();
      });
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

  build() {
    HdsNavDestination() {
      Column() {
        // 输入条 = ArkUI Tabs 的「悬浮页签栏」：barPosition=End + barOverlap +
        // barFloatingStyle.systemMaterial 是官方「非标题栏、非 HdsTabs」的原生沉浸材质载体
        // （《组件适配沉浸光感》底部页签一节 / 《沉浸光感典型场景》底部 Tabs 悬浮 + ExpandSafeArea）。
        // 材质自带交互形变（interactive）与点光源（lightEffect），栏体由系统绘制为两端纯圆胶囊。
        Tabs({ barPosition: BarPosition.End, index: 0 }) {
          TabContent() {
        // 悬浮层：Stack 底对齐——消息区（Column，铺满、底部留白）在下层，
        // 悬浮输入胶囊（圆角+玻璃底+实时磨砂+投影）浮于其上（对齐「悬浮圆角胶囊 + 沉浸光感」）。
        Stack({ alignContent: Alignment.Bottom }) {
          Column() {
        if (this.loading) {
          Text($r('app.string.chat_loading'))
            .fontSize(UiTokens.fsSecondary)
            .fontColor($r('app.color.text_tertiary'))
            .padding({ top: UiTokens.topInset })
        } else {
          List({ scroller: this.scroller }) {
            // 首项占位 = 沉浸标题栏高度：留白必须落在**列表内容**里，不能加在包住 List 的容器上
            // （容器 padding 会把视口裁到标题栏之下 → 消息滚不过去 → 磨砂/渐变模糊没有内容可模糊）
            ListItem() {
              Column().width('100%').height(UiTokens.topInset)
            }
            ForEach(this.turns, (t: DisplayTurn) => {
              ListItem() {
                TurnView({
                  turn: t,
                  isDark: this.isDark,
                  theme: this.theme,
                  baseUrl: this.conn !== null ? this.conn.baseUrl : ''
                })
              }
            }, (t: DisplayTurn) => t.id)
            // 末项占位 = 悬浮输入胶囊高度：滚到底时最后一条消息停在胶囊之上，其余消息从胶囊下滚过被实时模糊
            ListItem() {
              Column().width('100%').height(UiTokens.chatComposerInset)
            }
          }
          .layoutWeight(1)
          .width('100%')
          .scrollBar(BarState.Auto)
          .edgeEffect(EdgeEffect.Spring, { alwaysEnabled: true })
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
                Text('✕')
                  .fontSize(UiTokens.fsCaption)
                  .fontColor($r('app.color.text_tertiary'))
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
              Text(this.t($r('app.string.chat_approvals_count')).replace('%d',
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
        .margin({ bottom: UiTokens.chatComposerInset })
        }
          }
          .width('100%')
          .height('100%')
      }
      .width('100%')
      .height('100%')
      // 左右留白挂在滚动区容器（外层 Stack）上，不是最外层 Column：外层铺满屏幕左右，
      // 输入条父容器（Tabs）才能扩到屏幕边缘，不在两侧露出窗口底色
      .padding({ left: UiTokens.pageHMargin, right: UiTokens.pageHMargin })
          }
          .tabBar(this.composerBar())
        }
        .barOverlap(true)
        .scrollable(false)
        .barHeight(UiTokens.chatComposerHeight)
        .barFloatingStyle({
          // 悬浮栏默认按内容自适应宽度（实测输入框被压到 112px）→ 显式给宽度：
          // 344vp + 两侧 16vp = 376vp = 屏幕全宽（1316px @3.5）
          barWidth: { smallBarWidth: 344, mediumBarWidth: 344, largeBarWidth: 344 },
          barSideMargin: UiTokens.pageHMargin,
          // 栏体背板遮罩默认近黑：按压/拖动时栏体形变，遮罩露出即"黑边遮挡"（真机拖拽实测
          // 遮罩节点 BackgroundMask x56-1260 y2531-2832，漏出的行取值为 2~5）→ 置透明
          maskColor: Color.Transparent,
          barBottomMargin: 12,
          systemMaterial: new uiMaterial.ImmersiveMaterial({
            style: uiMaterial.ImmersiveStyle.THIN,
            interactive: true,
            lightEffect: { color: this.theme.accent }
          })
        })
        .width('100%')
        .height('100%')
    }
      .width('100%')
      .height('100%')
      // 键盘弹起时把底部让出来，悬浮输入条随之抬到键盘之上（与 NONE 模式配套）
      .padding({ bottom: this.keyboardInset })
      .backgroundColor($r('app.color.page_bg'))
      // 沉浸到状态栏 / 导航栏 / 屏幕左右两侧：绘制区扩到安全区之外（官方 expandSafeArea），
      // 否则上带显示系统壁纸、下带露出导航条底色、左右露出窗口底色的黑带
      .expandSafeArea([SafeAreaType.SYSTEM],
        [SafeAreaEdge.TOP, SafeAreaEdge.BOTTOM, SafeAreaEdge.START, SafeAreaEdge.END])
    }
    // 内容也扩到安全区外（布局级）：官方 NavDestination.ignoreLayoutSafeArea，
    // 与 expandSafeArea 同时设置时它优先；前置条件要求标题栏隐藏或 STACK 模式
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
          mainTitle: this.chatName.length > 0 ? this.chatName : $r('app.string.chat_title')
        }
      },
      // 与主页一致：标题栏不避让安全区向上铺到状态栏区域，组件安全区关闭（否则状态栏带露系统底）
      avoidLayoutSafeArea: false,
      enableComponentSafeArea: false
    })
  }
}

// ============ 消息 turn 渲染（对齐 PR #7378 features/chat/MessageTurn.tsx）============
// 结构：用户气泡（右）+ 「执行过程」折叠卡（思考/工具行）+ 「最终回复」气泡（左）。
// 纯逻辑（取文本/工具名/状态/合并）为模块级函数；文案翻译走 $r，含 %d 的走 host getStringSync。

// ============ 媒体渲染（对齐 PR #7378 features/chat/MessageParts.tsx）============
// 媒体 URL 解析对齐 7378 client.ts mediaSource：http/https/data 原样，
// 其余（相对路径 / file://）拼 {baseUrl}/api/files/preview{path}。
// 注：ArkTS Image 组件不支持自定义请求头（7378 的 mediaSource 会带 Authorization / X-Agent-Id），
// 开放模式免票据可直接访问；需票据的部署下带认证媒体暂不显示（后续以 ArrayBuffer 下载 → PixelMap 补齐）。
function mediaUrl(baseUrl: string, rawUrl: string): string {
  if (rawUrl.startsWith('http://') || rawUrl.startsWith('https://') || rawUrl.startsWith('data:')) {
    return rawUrl;
  }
  const path: string = rawUrl.startsWith('file://') ? rawUrl.slice(7) : rawUrl;
  const previewPath: string = path.startsWith('/') ? path : `/${path}`;
  return `${baseUrl}/api/files/preview${previewPath}`;
}

function mediaPartsOf(parts: DisplayPart[]): DisplayPart[] {
  return parts.filter((p: DisplayPart): boolean => p.type !== 'text');
}

// 媒体类型图标（用文本符号：SymbolGlyph.fontColor 不接受 string 主题色）
function mediaGlyph(type: string): string {
  if (type === 'video') {
    return '🎬';
  }
  if (type === 'audio') {
    return '🎵';
  }
  if (type === 'image') {
    return '🖼';
  }
  return '📄';
}

// 单个媒体块：图片 → Image（data URL 先转 PixelMap）；video/audio/file → 文件卡
@Component
struct MediaThumb {
  @Prop part: DisplayPart = { type: '' };
  @Prop baseUrl: string = '';
  @State pixelMap: image.PixelMap | undefined = undefined;
  @State failed: boolean = false;

  aboutToAppear(): void {
    const url: string = this.part.url !== undefined ? this.part.url : '';
    if (this.part.type === 'image' && url.startsWith('data:')) {
      this.decodeDataUrl(url);
    }
  }

  // base64 data URL → PixelMap（ArkTS Image 不直读 data URL；对齐 7378 base64 source 分支）
  private async decodeDataUrl(url: string): Promise<void> {
    const comma: number = url.indexOf(',');
    if (comma < 0) {
      return;
    }
    try {
      const bytes: Uint8Array = new util.Base64Helper().decodeSync(url.slice(comma + 1));
      const buf: ArrayBuffer =
        bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer;
      const src: image.ImageSource = image.createImageSource(buf);
      this.pixelMap = await src.createPixelMap();
    } catch (e) {
      this.failed = true;
    }
  }

  @Builder
  FileCard() {
    Row() {
      Text(mediaGlyph(this.part.type))
        .fontSize(20)
        .margin({ right: 10 })
      Column() {
        Text(this.part.name !== undefined && this.part.name.length > 0 ? this.part.name : this.part.type)
          .fontSize(UiTokens.fsSecondary)
          .fontColor($r('app.color.text_primary_strong'))
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
        Text(this.part.type)
          .fontSize(UiTokens.fsCaption)
          .fontColor($r('app.color.text_tertiary'))
          .margin({ top: 2 })
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1)
    }
    .width('100%')
    .padding({ left: 10, right: 10, top: 8, bottom: 8 })
    .borderRadius(12)
    .backgroundColor($r('app.color.card_bg'))
  }

  build() {
    if (this.part.type === 'image' && !this.failed) {
      if (this.pixelMap !== undefined) {
        Image(this.pixelMap)
          .width('100%')
          .aspectRatio(1.28)
          .objectFit(ImageFit.Cover)
          .borderRadius(UiTokens.cardRadius)
          .backgroundColor($r('app.color.card_bg'))
      } else {
        Image(mediaUrl(this.baseUrl, this.part.url !== undefined ? this.part.url : ''))
          .width('100%')
          .aspectRatio(1.28)
          .objectFit(ImageFit.Cover)
          .borderRadius(UiTokens.cardRadius)
          .backgroundColor($r('app.color.card_bg'))
          .onError((): void => {
            this.failed = true;
          })
      }
    } else {
      this.FileCard()
    }
  }
}

// 媒体块列表（跳过 text；文本已由气泡另行渲染）
@Component
struct MediaParts {
  @Prop parts: DisplayPart[] = [];
  @Prop baseUrl: string = '';

  build() {
    Column({ space: 6 }) {
      ForEach(mediaPartsOf(this.parts), (p: DisplayPart, i: number) => {
        MediaThumb({ part: p, baseUrl: this.baseUrl })
      }, (p: DisplayPart, i: number) => `${p.type}:${p.url !== undefined ? p.url : ''}:${i}`)
    }
    .width('100%')
  }
}

function textOfParts(parts: DisplayPart[]): string {
  let out: string = '';
  for (const p of parts) {
    if (p.type === 'text' && p.text !== undefined) {
      out = out.length > 0 ? `${out} ${p.text}` : p.text;
    }
  }
  return out;
}

// 追加文本到分片数组：合并进末尾 text 分片，否则新起一片
function appendText(parts: DisplayPart[], text: string): void {
  const lastIdx: number = parts.length - 1;
  if (lastIdx >= 0 && parts[lastIdx].type === 'text') {
    const lp: DisplayPart = parts[lastIdx];
    parts[lastIdx] = { type: 'text', text: (lp.text !== undefined ? lp.text : '') + text };
  } else {
    const np: DisplayPart = { type: 'text', text: text };
    parts.push(np);
  }
}

function toolLabel(name: string | undefined): string {
  if (name === undefined || name.length === 0) {
    return '';
  }
  return name.replace(/_/g, ' ');
}

// 工具状态等级（对齐 7378 toolStateLabel）：0=调用（无结果无状态）/1=失败/2=完成
function toolStateLevel(m: DisplayMessage): number {
  const hasOutput: boolean = m.toolOutput !== undefined && m.toolOutput.length > 0;
  const state: string = m.toolState !== undefined ? m.toolState : '';
  if (!hasOutput && state.length === 0) {
    return 0;
  }
  if (/error|failed|denied|interrupted/i.test(state)) {
    return 1;
  }
  return 2;
}

// 合并连续同工具消息（对齐 7378 mergeToolMessages：同 callId 或同 name 或无名同 input 无 output）
function mergeToolMessages(messages: DisplayMessage[]): DisplayMessage[] {
  const merged: DisplayMessage[] = [];
  for (const message of messages) {
    if (message.kind !== 'tool') {
      merged.push(message);
      continue;
    }
    const prev: DisplayMessage | null = merged.length > 0 ? merged[merged.length - 1] : null;
    if (prev !== null && prev.kind === 'tool') {
      const sameCall: boolean =
        (message.toolCallId !== undefined && message.toolCallId.length > 0
          && message.toolCallId === prev.toolCallId)
        || (message.toolName !== undefined && message.toolName.length > 0
          && message.toolName === prev.toolName)
        || (message.toolName === undefined && message.toolInput !== undefined
          && prev.toolInput !== undefined
          && (prev.toolOutput === undefined || prev.toolOutput.length === 0));
      if (sameCall) {
        const parts: DisplayPart[] = [];
        const seen: string[] = [];
        for (const p of prev.parts.concat(message.parts)) {
          const k: string = p.type === 'text' ? `t:${p.text !== undefined ? p.text : ''}`
            : `${p.type}:${p.url !== undefined ? p.url : ''}`;
          if (seen.indexOf(k) < 0) {
            seen.push(k);
            parts.push(p);
          }
        }
        const nm: DisplayMessage = {
          id: prev.id,
          role: prev.role,
          kind: 'tool',
          parts: parts,
          toolName: prev.toolName !== undefined ? prev.toolName : message.toolName,
          toolState: message.toolState !== undefined ? message.toolState : prev.toolState,
          toolCallId: prev.toolCallId !== undefined ? prev.toolCallId : message.toolCallId,
          toolInput: prev.toolInput !== undefined ? prev.toolInput : message.toolInput,
          toolOutput: message.toolOutput !== undefined ? message.toolOutput : prev.toolOutput
        };
        merged[merged.length - 1] = nm;
        continue;
      }
    }
    merged.push(message);
  }
  return merged;
}

@Component
struct TurnView {
  @Prop turn: DisplayTurn = { id: '', user: null, process: [], answer: null, resultMedia: [], pending: false };
  @Prop isDark: boolean = false;
  @Prop theme: ThemeSnapshot = ThemeManager.get().snapshot();
  @Prop baseUrl: string = '';
  @State answerExpanded: boolean = false;

  build() {
    Column() {
      if (this.turn.user !== null) {
        this.UserBubble()
      }
      if (this.turn.process.length > 0) {
        ProcessCard({ process: this.turn.process, isDark: this.isDark, theme: this.theme })
      }
      if (this.shouldShowAnswer()) {
        this.AnswerBubble()
      }
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
    .padding({ left: UiTokens.pageHMargin, right: UiTokens.pageHMargin })
  }

  private shouldShowAnswer(): boolean {
    if (this.turn.pending) {
      return true;
    }
    const a: DisplayMessage | null = this.turn.answer;
    if (a === null) {
      return false;
    }
    return a.parts.length > 0 || a.error !== undefined;
  }

  private userText(): string {
    const u: DisplayMessage | null = this.turn.user;
    return u !== null ? textOfParts(u.parts) : '';
  }

  private answerText(): string {
    const a: DisplayMessage | null = this.turn.answer;
    return a !== null ? textOfParts(a.parts) : '';
  }

  private answerError(): string {
    const a: DisplayMessage | null = this.turn.answer;
    return a !== null && a.error !== undefined ? a.error : '';
  }

  private answerCollapsible(): boolean {
    return this.answerText().length > 240;
  }

  private userMedia(): DisplayPart[] {
    const u: DisplayMessage | null = this.turn.user;
    return u !== null ? mediaPartsOf(u.parts) : [];
  }

  // 答案媒体：answer.parts 媒体 + 工具产出的 resultMedia（对齐 7378 MessageTurn 媒体归集）
  private answerMedia(): DisplayPart[] {
    const a: DisplayMessage | null = this.turn.answer;
    const own: DisplayPart[] = a !== null ? mediaPartsOf(a.parts) : [];
    return own.concat(this.turn.resultMedia);
  }

  @Builder
  UserBubble() {
    Row() {
      Blank()
      Column() {
        if (this.userText().length > 0) {
          Text(this.userText())
            .fontSize(UiTokens.fsBody)
            .fontColor(Color.White)
            .lineHeight(21)
            .wordBreak(WordBreak.BREAK_WORD)
        }
        if (this.userMedia().length > 0) {
          Column() {
            MediaParts({ parts: this.userMedia(), baseUrl: this.baseUrl })
          }
          .width('100%')
          .margin({ top: this.userText().length > 0 ? 6 : 0 })
        }
      }
      .alignItems(HorizontalAlign.Start)
      .constraintSize({ maxWidth: '78%' })
      .padding({ left: 12, right: 12, top: 10, bottom: 10 })
      .borderRadius(UiTokens.cardRadius)
      .backgroundColor(this.isDark ? this.theme.accentDark : this.theme.accent)
    }
    .width('100%')
    .margin({ top: 6, bottom: 6 })
    .justifyContent(FlexAlign.End)
  }

  @Builder
  AnswerBubble() {
    Column() {
      Text($r('app.string.chat_answer_label'))
        .fontSize(UiTokens.fsCaption)
        .fontColor($r('app.color.text_tertiary'))
        .margin({ bottom: 4 })
      if (this.answerError().length > 0) {
        Text($r('app.string.chat_answer_failed'))
          .fontSize(UiTokens.fsCaption)
          .fontColor($r('app.color.status_error'))
          .fontWeight(FontWeight.Bold)
          .margin({ bottom: 2 })
        Text(this.answerError())
          .fontSize(UiTokens.fsCaption)
          .fontColor($r('app.color.status_error'))
          .wordBreak(WordBreak.BREAK_ALL)
      } else if (this.answerText().length > 0) {
        Text(this.answerText())
          .fontSize(UiTokens.fsBody)
          .fontColor($r('app.color.input_text'))
          .lineHeight(21)
          .wordBreak(WordBreak.BREAK_WORD)
          .maxLines(this.answerExpanded ? 0 : 12)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
        if (this.answerCollapsible()) {
          Text(this.answerExpanded ? $r('app.string.chat_answer_collapse') : $r('app.string.chat_answer_expand'))
            .fontSize(UiTokens.fsCaption)
            .fontColor(this.isDark ? this.theme.accentDark : this.theme.accent)
            .margin({ top: 4 })
            .onClick((): void => {
              this.answerExpanded = !this.answerExpanded;
            })
        }
      } else if (this.turn.pending) {
        Text($r('app.string.chat_answer_pending'))
          .fontSize(UiTokens.fsSecondary)
          .fontColor($r('app.color.text_tertiary'))
      }
      // 答案媒体（答案自带图片 + 工具产出的媒体，如截图）
      if (this.answerMedia().length > 0) {
        Column() {
          MediaParts({ parts: this.answerMedia(), baseUrl: this.baseUrl })
        }
        .width('100%')
        .margin({ top: 8 })
      }
    }
    .alignItems(HorizontalAlign.Start)
    .width('100%')
    .padding({ left: 12, right: 12, top: 10, bottom: 10 })
    .borderRadius(UiTokens.cardRadius)
    .backgroundColor($r('app.color.card_surface'))
    .margin({ top: 6, bottom: 6 })
  }
}

@Component
struct ProcessCard {
  @Prop process: DisplayMessage[] = [];
  @Prop isDark: boolean = false;
  @Prop theme: ThemeSnapshot = ThemeManager.get().snapshot();
  @State expanded: boolean = false;

  private t(res: Resource): string {
    try {
      const host: common.Context = this.getUIContext().getHostContext() as common.Context;
      return host.resourceManager.getStringSync(res.id);
    } catch (e) {
      return '';
    }
  }

  private accentColor(): string {
    return this.isDark ? this.theme.accentDark : this.theme.accent;
  }

  private merged(): DisplayMessage[] {
    return mergeToolMessages(this.process);
  }

  private summary(): string {
    const msgs: DisplayMessage[] = this.process;
    let tools: number = 0;
    let toolCalls: number = 0;
    let hasReasoning: boolean = false;
    for (const m of msgs) {
      if (m.kind === 'tool') {
        tools++;
        if (m.toolState === undefined || m.toolState.length === 0) {
          toolCalls++;
        }
      } else if (m.kind === 'reasoning') {
        hasReasoning = true;
      }
    }
    const effectiveTools: number = toolCalls > 0 ? toolCalls : tools;
    const parts: string[] = [];
    if (hasReasoning) {
      parts.push(this.t($r('app.string.chat_process_summary_think')));
    }
    if (effectiveTools > 0) {
      parts.push(this.t($r('app.string.chat_process_summary_tools')).replace('%d', effectiveTools.toString()));
    }
    if (parts.length === 0) {
      parts.push(this.t($r('app.string.chat_process_summary_mid')).replace('%d', msgs.length.toString()));
    }
    return parts.join(' · ');
  }

  build() {
    Column() {
      Row() {
        Text('⚙')
          .fontSize(15)
          .fontColor(this.accentColor())
          .margin({ right: 8 })
        Column() {
          Text($r('app.string.chat_process_tool'))
            .fontSize(UiTokens.fsSecondary)
            .fontColor($r('app.color.text_secondary'))
            .fontWeight(FontWeight.Medium)
          Text(this.summary())
            .fontSize(UiTokens.fsCaption)
            .fontColor($r('app.color.text_tertiary'))
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
        }
        .alignItems(HorizontalAlign.Start)
        .layoutWeight(1)
        Text(this.expanded ? '▲' : '▼')
          .fontSize(12)
          .fontColor($r('app.color.text_tertiary'))
      }
      .width('100%')
      .padding({ left: 12, right: 12, top: 10, bottom: 10 })
      .onClick((): void => {
        this.expanded = !this.expanded;
      })
      if (this.expanded) {
        Column() {
          ForEach(this.merged(), (m: DisplayMessage) => {
            ProcessRow({ message: m, isDark: this.isDark, theme: this.theme })
          }, (m: DisplayMessage) => m.id)
        }
        .width('100%')
        .padding({ left: 12, right: 12, bottom: 8 })
      }
    }
    .width('100%')
    .borderRadius(UiTokens.cardRadius)
    .backgroundColor($r('app.color.card_surface'))
    .borderWidth(1)
    .borderColor($r('app.color.line'))
    .margin({ top: 6, bottom: 6 })
  }
}

@Component
struct ProcessRow {
  @Prop message: DisplayMessage = { id: '', role: 'assistant', kind: 'message', parts: [] };
  @Prop isDark: boolean = false;
  @Prop theme: ThemeSnapshot = ThemeManager.get().snapshot();
  @State detailExpanded: boolean = false;

  private accentColor(): string {
    return this.isDark ? this.theme.accentDark : this.theme.accent;
  }

  private title(): ResourceStr {
    if (this.message.kind === 'reasoning') {
      return $r('app.string.chat_process_thinking_label');
    }
    if (this.message.kind === 'tool') {
      const name: string = toolLabel(this.message.toolName);
      return name.length > 0 ? name : $r('app.string.chat_tool_default');
    }
    return $r('app.string.chat_process_mid');
  }

  private stateLabel(): ResourceStr {
    const lv: number = toolStateLevel(this.message);
    if (lv === 0) {
      return $r('app.string.chat_process_call');
    }
    if (lv === 1) {
      return $r('app.string.chat_process_failed');
    }
    return $r('app.string.chat_process_done');
  }

  private toolDetailText(which: string): string {
    if (which === 'input') {
      return this.message.toolInput !== undefined ? this.message.toolInput : '';
    }
    return this.message.toolOutput !== undefined ? this.message.toolOutput : '';
  }

  private detailCollapsible(): boolean {
    const a: number = this.message.toolInput !== undefined ? this.message.toolInput.length : 0;
    const b: number = this.message.toolOutput !== undefined ? this.message.toolOutput.length : 0;
    return a + b > 420;
  }

  @Builder
  ToolDetailBlock(which: string) {
    if (this.toolDetailText(which).length > 0) {
      Column() {
        Text(which === 'input' ? $r('app.string.chat_tool_input_label') : $r('app.string.chat_tool_output_label'))
          .fontSize(UiTokens.fsCaption)
          .fontColor($r('app.color.text_tertiary'))
          .fontWeight(FontWeight.Bold)
          .margin({ bottom: 2 })
        Text(this.toolDetailText(which))
          .fontSize(UiTokens.fsCaption)
          .fontColor($r('app.color.text_secondary'))
          .lineHeight(18)
          .wordBreak(WordBreak.BREAK_ALL)
          .maxLines(this.detailExpanded ? 0 : 6)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
      }
      .alignItems(HorizontalAlign.Start)
      .width('100%')
      .padding(8)
      .borderRadius(UiTokens.chipRadius)
      .backgroundColor($r('app.color.card_bg'))
      .margin({ top: 6 })
    }
  }

  build() {
    Row() {
      Text('✓')
        .fontSize(15)
        .fontColor(this.accentColor())
        .margin({ right: 8 })
      Column() {
        Row() {
          Text(this.title())
            .fontSize(UiTokens.fsSecondary)
            .fontColor($r('app.color.text_secondary'))
            .fontWeight(FontWeight.Medium)
            .layoutWeight(1)
          if (this.message.kind === 'tool') {
            Text(this.stateLabel())
              .fontSize(UiTokens.fsCaption)
              .fontColor($r('app.color.text_tertiary'))
              .padding({ left: 6, right: 6, top: 2, bottom: 2 })
              .borderRadius(6)
              .backgroundColor($r('app.color.card_bg'))
          }
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)
        if (this.message.kind === 'tool') {
          this.ToolDetailBlock('input')
          this.ToolDetailBlock('output')
          if (this.detailCollapsible()) {
            Text(this.detailExpanded ? $r('app.string.chat_tool_collapse') : $r('app.string.chat_tool_view_full'))
              .fontSize(UiTokens.fsCaption)
              .fontColor(this.isDark ? this.theme.accentDark : this.theme.accent)
              .margin({ top: 4 })
              .onClick((): void => {
                this.detailExpanded = !this.detailExpanded;
              })
          }
        } else {
          Text(textOfParts(this.message.parts))
            .fontSize(UiTokens.fsCaption)
            .fontColor($r('app.color.text_secondary'))
            .lineHeight(18)
            .wordBreak(WordBreak.BREAK_ALL)
            .maxLines(6)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
        }
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1)
    }
    .width('100%')
    .padding({ top: 10, bottom: 10 })
  }
}
