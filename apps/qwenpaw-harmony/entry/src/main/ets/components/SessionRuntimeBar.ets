/*
 * 聊天页 · 会话运行状态条 —— 对齐 PR #7378 features/chat/SessionRuntimeControls.tsx 与
 * console LoopModeSelector（模型 / 循环 / 审批三芯片，点开是紧凑小弹窗）。
 *
 * 取数（本组件自持，不由页面下推）：
 *   GET /api/models/active                   → Agent 默认模型（面板标题标注用）
 *   GET /api/chats/{id}/thinking             → 本会话生效模型 + 思考强度视图（会话覆盖存在 chat.meta）
 *   GET /api/chats/thinking-default          → 未选模型的思考视图预览（模型面板点行实时跟随用）
 *   GET /api/loops                           → 运行方式目录（内置 + 自定义 + 插件）
 *   GET /api/loops/status?chat_id&session_id → 本会话循环状态（state + mode）
 *   PUT /api/chats/{id}/model                → 会话级模型覆盖（不动 Agent 默认）
 *   PUT /api/chats/{id}/thinking?model_key   → 会话级思考强度（偏好按 model_key 分键存储；
 *                                              409=会话模型已变、422=该档位对此模型非法）
 *
 * 循环（loops）契约（服务端 src/qwenpaw/app/routers/loops.py）：
 *   服务端没有「开关」API——模式是本地选择，发送时把消息文本改写成 "/<command> <原文>"
 *   （default 模式 command 为空，原样发送），只对下一条消息生效（一次性，存
 *   SessionControls.setLoopPick，由 ChatDetailPage.send 取出）。当前回合的阶段从
 *   /loops/status 轮询（state: idle/running/awaiting_user；普通单轮回合服务端恒为
 *   idle，只有 goal/mission/自定义模式激活后才报 running/awaiting_user）。发送成功后
 *   发送链路经注册表写入「starting」做发送保护，服务端跟上 running 后以服务端为准。
 *   循环非 idle 时面板为只读卡（服务端无「结束循环」接口，对齐 console 的 disabled 语义）。
 *
 * 为什么自持数据：本行挂在 Tabs 悬浮页签栏（barPosition=End 的 TabBar）内，该 builder 只在
 * 页面首次构建时执行一次，父组件之后的 @State/@Prop 变化进不了这棵子树（真机实证：传进来的
 * baseUrl/agentId 恒为空、@Link 值恒为「—」）；而子树内组件自身的 @State 变化照常刷新
 * （同一子树里的输入框打字、发送键置灰都正常）。故按其它模块组件的写法，在 aboutToAppear
 * 里自行 loadConnection + 取数，不依赖页面下推。
 *
 * 位置与材质：本行**浮在输入胶囊之上**（不在输入胶囊里：胶囊只包输入行），由聊天页用
 * Tabs 的 overlay 定位（官方《Tabs 使用 overlay 在页签栏添加自定义组件》）。
 * 材质：官方《沉浸光感常见问题》列了**全页面生效**的组件/接口——弹窗类组件与接口，以及
 * **Slider / Toggle / Select**；「其他组件仅在 Navigation/NavDestination 标题栏或横向 Tabs 中
 * barPosition=End 的底部 TabBar 中生效」（Button 属"其他组件"，在内容区挂材质会被打印
 * `Material inactive: out of scope`，真机实证）。故三个芯片用 **Toggle(ToggleType.Button)**
 * —— 官方口径「ToggleType.Button 效果与 Button 组件设置沉浸光感相同」，且在豁免名单内，
 * 内容区即可获得系统沉浸材质：档位随设备算力自适应、并跟随系统「沉浸光感」开关。
 * 交互形变（interactive）与点光源（lightEffect）替代默认按压态。
 *
 * 面板形态：紧凑小弹窗（OptionDialog = CustomDialog + systemMaterial(THICK)）。
 * CustomDialog 的 builder 参数不支持动态刷新（官方口径）→ 每次打开新建 controller、
 * 入参为打开瞬间的快照；controller 是本 struct 成员变量（官方口径要求），宿主持引用做 close。
 */

import { common } from '@kit.AbilityKit';
import { http } from '@kit.NetworkKit';
import { uiMaterial } from '@kit.ArkUI';
import { doRequest, jsonArrayOf, jsonOf } from '../services/ConnectionService';
import { loadConnection, QpConnection } from '../services/ConnectionStore';
import { fetchAgentApproval } from '../services/AgentApproval';
import { loadChatApproval, saveChatApproval } from '../services/ChatApprovalPrefs';
import {
  setSessionApproval,
  LoopPhase,
  loopPickOf,
  setLoopPick,
  getLoopPhase,
  setLoopPhase,
  isLoopActive,
  onLoopPhaseChange
} from '../services/SessionControls';
import {
  OptionDialog,
  DialogOption,
  dialogOptionOf,
  optionDialogMaterial,
  ThinkingPick
} from './OptionDialog';
import { parseThinkingView, ThinkingSnapshot } from './ThinkingView';
import { t } from '../services/I18n';

class ModelChoice {
  value: string = '';   // providerId||model
  label: string = '';
}

class LoopEntry {
  id: string = '';
  name: string = '';
  detail: string = '';
  command: string = '';
  icon: Resource = $r('app.media.circle_dot');
}

// 循环模式图标（对齐 console LoopModeSelector 的 ModeIcon 映射，超集：console 无 builtin
// default 的 CircleDot 之外的分支，我方按 console + 7378 口径补齐）
function loopIconFor(id: string): Resource {
  if (id === 'goal') {
    return $r('app.media.target');
  }
  if (id === 'mission') {
    return $r('app.media.rocket');
  }
  if (id.startsWith('custom:')) {
    return $r('app.media.sparkles');
  }
  if (id.startsWith('plugin:')) {
    return $r('app.media.boxes');
  }
  return $r('app.media.circle_dot');
}

/*
 * 行内按钮：一个圆角胶囊。
 * 图标统一用 QwenPaw 同款 lucide SVG（工程 media 资源）走 Image。
 * 注：SVG 走 media 而非 rawfile —— $rawfile 的资源经 @Prop 传给子组件后取不到内容
 * （真机实测：Image 节点根本不生成），$r 资源则正常。
 */
@Component
struct RuntimeChip {
  @Prop icon: Resource;
  @Prop label: Resource;
  @Prop value: string = '';
  @Prop tappable: boolean = false;
  onTap: () => void = (): void => {
  };

  build() {
    // Toggle(ToggleType.Button)：外观/行为与 Button 一致，但属全页面生效的沉浸材质组件。
    // isOn 固定 false（只借它的材质与交互反馈，不留选中态）；onChange 只用来触发点击动作。
    Toggle({ type: ToggleType.Button, isOn: false }) {
      Row({ space: 4 }) {
        Image(this.icon)
          .width(14)
          .height(14)
          .fillColor($r('app.color.text_secondary'))
          .draggable(false)
        Text(`${t(this.label)} ${this.value.length > 0 ? this.value : '—'}`)
          .fontSize(12)
          .fontColor($r('app.color.composer_label'))
          .maxLines(1)
      }
    }
    .padding({ left: 5, right: 5, top: 4, bottom: 4 })
    .borderRadius(12)
    // 透明底：材质自带玻璃观感（官方按钮示例即「透明底 + ImmersiveMaterial」）
    .backgroundColor(Color.Transparent)
    // 沉浸材质：THIN 与输入胶囊同档；实际效果随设备算力自适应（低算力仅保留一种样式）
    // interactive = 交互形变、lightEffect = 点光源反馈，二者替代组件默认按压态
    .systemMaterial(new uiMaterial.ImmersiveMaterial({
      style: uiMaterial.ImmersiveStyle.THIN,
      interactive: true,
      lightEffect: {}
    }))
    // Toggle 每次点按都会翻转内部开关态 → 若不抹掉选中底色，关掉弹窗后按钮会留在"选中"色上，
    // 再点一次只是把选中取消（不触发动作）。两处一起收拾：
    //   ① selectedColor 透明 → 选中态不着色（观感完全由沉浸材质给）；
    //   ② onChange 不区分方向都触发动作 —— 芯片只在弹窗之外可见（弹窗打开时被遮住），
    //      不存在"再点一次代表关闭"的语义，故每次都按"打开"处理。
    .selectedColor(Color.Transparent)
    .enabled(this.tappable)
    .onChange((isOn: boolean): void => {
      this.onTap();
    })
  }
}

@Component
export struct SessionRuntimeBar {
  // 本会话标识：页面 aboutToAppear 里已就绪，首帧即为真值
  @Prop chatId: string = '';
  @Prop sessionId: string = '';
  @State modelName: string = '';
  @State modelProvider: string = '';   // 生效模型所属 provider（用于在面板里标出当前项）
  @State agentModelName: string = '';  // Agent 默认模型（会话覆盖时在面板标题里标出默认值）
  @State loopText: string = '';
  @State loopIcon: Resource = $r('app.media.circle_dot');
  @State approval: string = '';
  @State busy: boolean = false;
  // 运行方式本地选择（idle 时芯片显示它；对齐 7378 selectedLoopMode 的 trigger 口径）
  @State selectedLoopId: string = 'default';
  // 本会话选择（对齐 7378：随发送生效，不写服务端）：审批取原始等级（空 = 跟随 Agent）
  @State pickedApproval: string = '';
  @State agentApproval: string = '';   // Agent 默认等级（审批面板「跟随 Agent」的说明用）
  private choices: ModelChoice[] = [];
  private loopEntries: LoopEntry[] = [];
  private conn: QpConnection | null = null;
  // 会话级运行态轻查定时器（-1 = 未启动）
  private liveTimer: number = -1;
  // 「starting 宽限」计数：发送后服务端可能还没感知到循环激活（恒回 idle），
  // 连续 N 次轮询仍 idle 才把注册表回落 idle，避免轮询把发送链路刚写的 starting 抹掉
  private idleStreak: number = 0;
  // 紧凑弹窗（OptionDialog）：builder 参数不支持动态刷新 → 打开前写好快照字段、每次新建
  // controller；dialogController 是本 struct 成员（官方口径要求）且持引用供 close
  private dialogController: CustomDialogController | null = null;
  private dialogTitle: string = '';
  private dialogSubtitle: string = '';
  private dialogOptions: DialogOption[] = [];
  private dialogCurrent: string = '';
  private dialogNoticeTitle: string = '';
  private dialogNoticeSub: string = '';
  private dialogNoticeIcon: Resource | null = null;
  // 思考强度节快照（模型面板才有，openModel 里从 GET /chats/{id}/thinking 解析写入；
  // 取数失败时 thinkKind 保持 '' → 弹窗内隐藏该节，不挡模型选择）
  private dialogThinkKind: string = '';
  private dialogThinkStops: string[] = [];
  private dialogThinkSupportsOff: boolean = false;
  private dialogThinkBudgetMin: number = 1;
  private dialogThinkBudgetMax: number = 1;
  private dialogThinkLevel: string = '';
  private dialogThinkBudgetTokens: number = 0;
  private dialogThinkCanReset: boolean = false;
  private dialogOnConfirm: (value: string, pick: ThinkingPick) => void =
    (v: string, p: ThinkingPick): void => {
    };

  aboutToAppear(): void {
    this.load();
    // phase 变化（发送链路写 starting / 轮询写 running、awaiting_user、idle）→ 芯片即时刷新，
    // 不必等下一次轮询；aboutToDisappear 注销（单监听，同一时刻只有一个会话详情页）
    onLoopPhaseChange((k: string, p: LoopPhase): void => {
      if (k === this.sessionKey()) {
        this.refreshLoopDisplay();
      }
    });
  }

  aboutToDisappear(): void {
    onLoopPhaseChange(null);
    if (this.liveTimer >= 0) {
      clearInterval(this.liveTimer);
      this.liveTimer = -1;
    }
  }

  // 会话定位键：与 /loops/status 的 session_id、发送链路的会话键同一口径
  // （方法不能叫 key —— 与 CustomComponent 的 key 属性方法冲突，构建直接报错）
  private sessionKey(): string {
    return this.sessionId.length > 0 ? this.sessionId : this.chatId;
  }

  private toast(msg: string): void {
    this.getUIContext().getPromptAction().showToast({ message: msg });
  }

  private async send(path: string, method: http.RequestMethod,
    body: string | null): Promise<http.HttpResponse> {
    const c: QpConnection | null = this.conn;
    if (c === null) {
      throw new Error(t($r('app.string.wb_not_connected')));
    }
    return doRequest(`${c.baseUrl}/api${path}`, method, body,
      c.token.length > 0 ? c.token : null, c.agentId);
  }

  private async load(): Promise<void> {
    const ctx: common.UIAbilityContext = this.getUIContext().getHostContext() as common.UIAbilityContext;
    const c: QpConnection | null = await loadConnection(ctx);
    if (c === null) {
      return;
    }
    this.conn = c;
    try {
      const sessionModel: boolean = await this.readSessionModel();
      const act: http.HttpResponse = await this.send('/models/active', http.RequestMethod.GET, null);
      if (act.responseCode >= 200 && act.responseCode < 300) {
        const llm: Object = jsonOf(act)['active_llm'];
        if (llm !== undefined && llm !== null) {
          const rec: Record<string, Object> = llm as Record<string, Object>;
          const m: Object = rec['model'];
          this.agentModelName = typeof m === 'string' ? m as string : '';
          if (!sessionModel) {
            this.modelName = this.agentModelName;
            const p: Object = rec['provider_id'];
            this.modelProvider = typeof p === 'string' ? p as string : '';
          }
        }
      }
      // 循环目录（芯片图标/友好名映射用）与当前状态
      await this.loadLoopEntries();
      await this.refreshLoopStatus();
      // 审批等级：默认值 = 服务端 Agent 级 approval_level（console 的 Agent 配置页同源），
      // 本会话若在本机选过则以会话覆盖为准（只影响这一个会话，见 ChatApprovalPrefs）
      await this.refreshAgentApproval();
      this.pickedApproval = await loadChatApproval(ctx, c.baseUrl, c.agentId, this.chatId);
      this.applyApprovalValue(this.pickedApproval);
      this.startLivePoll();
    } catch (e) {
      // 状态条属辅助信息：取不到保持「—」，不打断聊天
    }
  }

  // 会话思考视图（console 同源 GET /chats/{id}/thinking）：响应即 ThinkingView——
  // 生效模型（provider_id/model，会话覆盖存在 chat.meta）+ control 规格 + value/effective 偏好。
  // 取不到（未连接/服务端不支持）返回 null：调用方按「无思考节」降级
  private async fetchThinkingView(): Promise<Record<string, Object> | null> {
    if (this.chatId.length === 0) {
      return null;
    }
    try {
      const tv: http.HttpResponse = await this.send(
        `/chats/${encodeURIComponent(this.chatId)}/thinking`, http.RequestMethod.GET, null);
      if (tv.responseCode < 200 || tv.responseCode >= 300) {
        return null;
      }
      return jsonOf(tv);
    } catch (e) {
      return null;
    }
  }

  // 面板点选模型时的思考视图预览（console 同源 thinking-default 端点，provider_id/model
  // 为查询参数）：模型面板点行后实时重排思考节用；取不到返回 null → 弹窗内思考节隐藏
  private async fetchThinkingDefault(providerId: string, model: string): Promise<Record<string, Object> | null> {
    try {
      const q: string = `?provider_id=${encodeURIComponent(providerId)}&model=${encodeURIComponent(model)}`;
      const tv: http.HttpResponse = await this.send(`/chats/thinking-default${q}`, http.RequestMethod.GET, null);
      if (tv.responseCode < 200 || tv.responseCode >= 300) {
        return null;
      }
      return jsonOf(tv);
    } catch (e) {
      return null;
    }
  }

  // 会话生效模型（console 同口径）：从思考视图里取 provider/model，返回是否取到会话值
  private async readSessionModel(): Promise<boolean> {
    const rec: Record<string, Object> | null = await this.fetchThinkingView();
    if (rec === null) {
      return false;
    }
    const m: Object = rec['model'];
    if (typeof m !== 'string' || (m as string).length === 0) {
      return false;
    }
    this.modelName = m as string;
    const p: Object = rec['provider_id'];
    this.modelProvider = typeof p === 'string' ? p as string : '';
    return true;
  }

  // 运行方式目录：GET /loops（顶层是 JSON 数组，用 jsonArrayOf 取——此前按对象取 ['loops']
  // 拿不到、fallback 又拿到原始字符串，面板永远是空的）
  private async loadLoopEntries(): Promise<void> {
    this.loopEntries = [];
    const resp: http.HttpResponse = await this.send('/loops', http.RequestMethod.GET, null);
    if (resp.responseCode < 200 || resp.responseCode >= 300) {
      return;
    }
    for (const it of jsonArrayOf(resp)) {
      const r: Record<string, Object> = it as Record<string, Object>;
      const id: Object = r['id'];
      if (typeof id !== 'string' || (id as string).length === 0) {
        continue;
      }
      const e: LoopEntry = new LoopEntry();
      e.id = id as string;
      e.command = typeof r['slash_command'] === 'string' ? r['slash_command'] as string : '';
      const nm: Object = r['name'];
      e.name = this.loopNameFor(e.id,
        typeof nm === 'string' ? nm as string : '', r['name_i18n']);
      e.detail = this.loopDescFor(e.id,
        typeof r['description'] === 'string' ? r['description'] as string : '', r['description_i18n']);
      e.icon = loopIconFor(e.id);
      this.loopEntries.push(e);
    }
  }

  // 友好名（对齐 7378 loopName）：内置模式客户端 i18n（服务端 BUILTIN_LOOPS 不带 i18n，
  // name 是字面量 "default"/"goal"/"mission"）；自定义/插件优先服务端 name_i18n（zh），否则原名
  private loopNameFor(id: string, rawName: string, i18n: Object | undefined): string {
    if (id === 'default') {
      return t($r('app.string.chat_loop_name_default'));
    }
    if (id === 'goal') {
      return t($r('app.string.chat_loop_name_goal'));
    }
    if (id === 'mission') {
      return t($r('app.string.chat_loop_name_mission'));
    }
    if (i18n !== undefined && i18n !== null) {
      const rec: Record<string, Object> = i18n as Record<string, Object>;
      const zh: Object = rec['zh'] !== undefined ? rec['zh'] : rec['zh-CN'];
      if (typeof zh === 'string' && (zh as string).length > 0) {
        return zh as string;
      }
    }
    return rawName.length > 0 ? rawName : id;
  }

  // 描述（对齐 7378 loopDescription）：内置模式客户端 i18n；其余优先服务端 description_i18n
  private loopDescFor(id: string, rawDesc: string, i18n: Object | undefined): string {
    if (id === 'default') {
      return t($r('app.string.chat_loop_desc_default'));
    }
    if (id === 'goal') {
      return t($r('app.string.chat_loop_desc_goal'));
    }
    if (id === 'mission') {
      return t($r('app.string.chat_loop_desc_mission'));
    }
    if (i18n !== undefined && i18n !== null) {
      const rec: Record<string, Object> = i18n as Record<string, Object>;
      const zh: Object = rec['zh'] !== undefined ? rec['zh'] : rec['zh-CN'];
      if (typeof zh === 'string' && (zh as string).length > 0) {
        return zh as string;
      }
    }
    return rawDesc;
  }

  private loopNameOf(id: string): string {
    if (id === 'default') {
      return t($r('app.string.chat_loop_name_default'));
    }
    if (id === 'goal') {
      return t($r('app.string.chat_loop_name_goal'));
    }
    if (id === 'mission') {
      return t($r('app.string.chat_loop_name_mission'));
    }
    for (const e of this.loopEntries) {
      if (e.id === id) {
        return e.name;
      }
    }
    return id;
  }

  // 会话循环状态（服务端按 (chat_id, session_id) 记）。state 只有 idle/running/awaiting_user：
  // 普通单轮回合没有激活的循环模式 → 服务端恒 idle；goal/mission/自定义模式激活后才报
  // running（task_tracker 的 run 在进行）或 awaiting_user（模式等用户输入）。
  private async refreshLoopStatus(): Promise<void> {
    const st: http.HttpResponse = await this.send(
      `/loops/status?chat_id=${encodeURIComponent(this.chatId)}&session_id=${encodeURIComponent(this.sessionKey())}`,
      http.RequestMethod.GET, null);
    if (st.responseCode < 200 || st.responseCode >= 300) {
      return;
    }
    const rec: Record<string, Object> = jsonOf(st);
    const state: Object = rec['state'];
    const stateText: string = (typeof state === 'string' ? state as string : '').trim().toLowerCase();
    const mode: Object = rec['mode'];
    if (stateText === 'running' || stateText === 'awaiting_user') {
      // 服务端权威：回合在进行（或循环在等用户）
      this.idleStreak = 0;
      let modeId: string = '';
      let modeName: string = '';
      if (mode !== undefined && mode !== null) {
        const mr: Record<string, Object> = mode as Record<string, Object>;
        modeId = typeof mr['id'] === 'string' ? mr['id'] as string : '';
        modeName = this.loopNameFor(modeId,
          typeof mr['name'] === 'string' ? mr['name'] as string : '', mr['name_i18n']);
      }
      setLoopPhase(this.sessionKey(), stateText, modeId, modeName);
      return;
    }
    // 服务端 idle
    const reg: LoopPhase | undefined = getLoopPhase(this.sessionKey());
    if (reg !== undefined && reg.phase === 'starting') {
      // 宽限：刚发送、服务端还没感知到循环激活（也还没起 run）。连续超过 N 次仍 idle 才回落，
      // 给 goal/mission 引擎留足激活时间；期间芯片保持「正在启动」
      this.idleStreak += 1;
      if (this.idleStreak > 3) {
        this.idleStreak = 0;
        setLoopPhase(this.sessionKey(), 'idle', '', '');
      }
      return;
    }
    this.idleStreak = 0;
    if (reg !== undefined && reg.phase !== 'idle') {
      // 回合结束（running/awaiting_user → idle）：回落，芯片回到所选运行方式
      setLoopPhase(this.sessionKey(), 'idle', '', '');
    }
    // 无论走哪个分支都刷新一次显示：setLoopPhase 的监听器只在 phase 变化时触发，
    // 首载（注册表空 + 服务端 idle）不会有任何 phase 变化，不显式刷则芯片停在空串
    this.refreshLoopDisplay();
  }

  // 芯片显示：idle → 所选运行方式（图标 + 友好名，7378 trigger 口径）；
  // starting/running/awaiting_user → 激活模式的图标 + 模式名 + 状态词
  private refreshLoopDisplay(): void {
    const p: LoopPhase | undefined = getLoopPhase(this.sessionKey());
    const phase: string = p !== undefined ? p.phase : 'idle';
    let text: string;
    if (phase === 'idle') {
      this.loopIcon = loopIconFor(this.selectedLoopId);
      text = this.loopNameOf(this.selectedLoopId);
    } else {
      const modeId: string = (p !== undefined && p.modeId.length > 0) ? p.modeId : this.selectedLoopId;
      const modeName: string = (p !== undefined && p.modeName.length > 0)
        ? p.modeName : this.loopNameOf(modeId);
      const word: string = this.loopStateWord(phase);
      text = word.length > 0 ? `${modeName} ${word}` : modeName;
      this.loopIcon = loopIconFor(modeId);
    }
    this.loopText = text;
  }

  // 状态词（7378 loopStateLabel 同位）：starting 是客户端派生态（发送后、服务端跟上前的窗口）
  private loopStateWord(phase: string): string {
    const st: string = phase.trim().toLowerCase();
    if (st === 'starting') {
      return t($r('app.string.chat_loop_starting'));
    }
    if (st === 'running') {
      return t($r('app.string.chat_loop_running'));
    }
    if (st === 'awaiting_user') {
      return t($r('app.string.chat_loop_awaiting'));
    }
    return '';
  }

  // 会话级运行态的定时轻查（3s）：循环状态与会话模型都是服务端按会话记的，别处（console /
  // 另一台设备）起停循环或改会话模型后，本页不重进也要跟着变 —— 只查这两项与审批，不重取目录
  private startLivePoll(): void {
    if (this.liveTimer >= 0 || this.conn === null) {
      return;
    }
    this.liveTimer = setInterval((): void => {
      this.refreshLive();
    }, 3000);
  }

  private async refreshLive(): Promise<void> {
    if (this.conn === null) {
      return;
    }
    try {
      await this.refreshLoopStatus();
      await this.readSessionModel();
      // 审批等级也是服务端状态：面板没开着时跟着刷新（console 侧改过这里也要跟上）
      await this.refreshAgentApproval();
    } catch (e) {
      // 轻查失败不影响界面
    }
  }

  // 读服务端 Agent 审批等级（'' = 服务端未给值）：它是没有会话覆盖时的默认值。
  // 服务端值变化（console 的 Agent 配置页改过）→ 没有会话覆盖时显示与发送都跟着变
  private async refreshAgentApproval(): Promise<void> {
    const c: QpConnection | null = this.conn;
    if (c === null) {
      return;
    }
    try {
      this.agentApproval = await fetchAgentApproval(c.baseUrl, c.token, c.agentId);
      this.applyApprovalValue(this.pickedApproval);
    } catch (e) {
      // 取不到保持原显示
    }
  }

  // 生效审批等级 = 本会话覆盖（优先）?? 服务端 Agent 默认值；'' = 服务端也没给值
  private effectiveApproval(): string {
    return this.pickedApproval.length > 0 ? this.pickedApproval : this.agentApproval;
  }

  // 把「本会话覆盖」落到显示与发送链路（对齐 console：sessionLevel ?? runningConfigApprovalLevel，
  // 而 request_context.approval_level 用生效值）
  private applyApprovalValue(override: string): void {
    const effective: string = this.effectiveApproval();
    setSessionApproval(effective);
    this.approval = effective.length > 0 ? this.approvalLabelOf(effective) : '';
  }

  // 本会话选择：只改这一个会话（本机按会话落盘，见 ChatApprovalPrefs），不写服务端 Agent 默认值
  private pickApproval(level: string): void {
    this.pickedApproval = level;
    this.applyApprovalValue(level);
    const c: QpConnection | null = this.conn;
    if (c !== null) {
      saveChatApproval(this.getUIContext().getHostContext() as common.Context,
        c.baseUrl, c.agentId, this.chatId, level);
    }
  }

  // 审批等级显示映射（对齐 7378 SessionRuntimeControls 的 APPROVAL_OPTIONS 标签）；
  // 未知值原样透出，避免凭空造标签。
  private approvalLabelOf(raw: string): string {
    const up: string = raw.trim().toUpperCase();
    if (up === 'STRICT') {
      return t($r('app.string.chat_approval_strict'));
    }
    if (up === 'SMART') {
      return t($r('app.string.chat_approval_smart'));
    }
    if (up === 'AUTO') {
      return t($r('app.string.chat_approval_auto'));
    }
    if (up === 'OFF') {
      return t($r('app.string.chat_approval_off'));
    }
    return raw;
  }

  // 审批等级描述（对齐 7378 APPROVAL_OPTIONS 的 hint）
  private approvalDescOf(raw: string): string {
    const up: string = raw.trim().toUpperCase();
    if (up === 'STRICT') {
      return t($r('app.string.chat_approval_strict_desc'));
    }
    if (up === 'SMART') {
      return t($r('app.string.chat_approval_smart_desc'));
    }
    if (up === 'AUTO') {
      return t($r('app.string.chat_approval_auto_desc'));
    }
    if (up === 'OFF') {
      return t($r('app.string.chat_approval_off_desc'));
    }
    return '';
  }

  private stringArray(v: Object): string[] {
    const out: string[] = [];
    if (v === undefined || v === null || !Array.isArray(v)) {
      return out;
    }
    for (const s of v as Object[]) {
      if (typeof s === 'string') {
        out.push(s as string);
      }
    }
    return out;
  }

  // provider 是否可用（对齐 7378 sessionControlsModel.selectableProviders）：
  // 自定义/本地/免密钥的看 base_url 是否配置，其余看 api_key 或已 OAuth 授权；
  // 未配置的 provider 一个模型都不列。
  private isConfigured(r: Record<string, Object>): boolean {
    const hasBaseUrl: boolean = (() => {
      const b: Object = r['base_url'];
      return typeof b === 'string' && (b as string).trim().length > 0;
    })();
    if (r['is_custom'] === true || r['is_local'] === true || r['require_api_key'] === false) {
      return hasBaseUrl;
    }
    const key: Object = r['api_key'];
    return (typeof key === 'string' && (key as string).length > 0) || r['oauth_connected'] === true;
  }

  // 可选模型清单（对齐 7378）：models + extra_models 合并 → 去掉 hidden_model_ids →
  // 按 id 去重 → 丢弃空 id。
  private async loadChoices(): Promise<void> {
    const list: ModelChoice[] = [];
    const resp: http.HttpResponse = await this.send('/models', http.RequestMethod.GET, null);
    if (resp.responseCode >= 200 && resp.responseCode < 300) {
      for (const item of jsonArrayOf(resp)) {
        const r: Record<string, Object> = item as Record<string, Object>;
        const pid: Object = r['id'];
        if (typeof pid !== 'string' || (pid as string).length === 0 || !this.isConfigured(r)) {
          continue;
        }
        const pname: Object = r['name'];
        const pnameText: string = typeof pname === 'string' && (pname as string).length > 0
          ? pname as string : pid as string;
        const hidden: string[] = this.stringArray(r['hidden_model_ids']);
        const ids: string[] = [];
        const names: string[] = [];
        for (const key of ['models', 'extra_models']) {
          const arr: Object = r[key];
          if (arr === undefined || arr === null || !Array.isArray(arr)) {
            continue;
          }
          for (const m of arr as Object[]) {
            const rec: Record<string, Object> = m as Record<string, Object>;
            const id: Object = rec['id'];
            if (typeof id !== 'string' || (id as string).length === 0
              || hidden.includes(id as string) || ids.includes(id as string)) {
              continue;
            }
            const nm: Object = rec['name'];
            ids.push(id as string);
            names.push(typeof nm === 'string' && (nm as string).length > 0 ? nm as string : id as string);
          }
        }
        for (let i = 0; i < ids.length; i++) {
          const c: ModelChoice = new ModelChoice();
          c.value = `${pid as string}||${ids[i]}`;
          c.label = `${pnameText} · ${names[i]}`;
          list.push(c);
        }
      }
    }
    this.choices = list;
  }

  // ---- 紧凑小弹窗（OptionDialog）统一出口 ----

  // 打开前写好快照字段再调；已有弹窗打开中则忽略（芯片被弹窗遮着，正常点不到）。
  // withThinkingFetcher：模型面板传 true —— 点选模型行时实时取该模型思考视图重排思考节
  //（thinking-default 端点），不等点确定；循环/审批面板无思考节，传 false
  private openDialog(withThinkingFetcher: boolean): void {
    if (this.dialogController !== null) {
      return;
    }
    // builder 参数不支持动态刷新（官方口径）→ 每次打开新建 controller；
    // builder 直传组件调用（官方示例同款）；参数在构造时取值，天然快照
    const ctl: CustomDialogController = new CustomDialogController({
      builder: OptionDialog({
        title: this.dialogTitle,
        subtitle: this.dialogSubtitle,
        options: this.dialogOptions,
        current: this.dialogCurrent,
        noticeTitle: this.dialogNoticeTitle,
        noticeSub: this.dialogNoticeSub,
        noticeIcon: this.dialogNoticeIcon,
        thinkKind: this.dialogThinkKind,
        thinkStops: this.dialogThinkStops,
        thinkSupportsOff: this.dialogThinkSupportsOff,
        thinkBudgetMin: this.dialogThinkBudgetMin,
        thinkBudgetMax: this.dialogThinkBudgetMax,
        thinkLevel: this.dialogThinkLevel,
        thinkBudgetTokens: this.dialogThinkBudgetTokens,
        thinkCanReset: this.dialogThinkCanReset,
        thinkForModel: this.dialogCurrent,
        thinkingFetcher: withThinkingFetcher
          ? (model: string): Promise<Record<string, Object> | null> => {
            const parts: string[] = model.split('||');
            if (parts.length !== 2) {
              return Promise.resolve<Record<string, Object> | null>(null);
            }
            return this.fetchThinkingDefault(parts[0], parts[1]);
          }
          : null,
        onConfirm: (v: string, pick: ThinkingPick): void => {
          this.dialogOnConfirm(v, pick);
          this.closeDialog();
        },
        onCancel: (): void => {
          this.closeDialog();
        }
      }),
      autoCancel: true,
      customStyle: false,
      // 360：容纳模型面板的思考强度节（滑块 + 档位标签），循环/审批面板同宽观感一致
      width: 360,
      cornerRadius: 24,
      systemMaterial: optionDialogMaterial(),
      onWillDismiss: (action: DismissDialogAction): void => {
        // 官方示例同款：onWillDismiss 里显式 dismiss，否则返回键/点外不会真正关闭
        if (action.reason === DismissReason.PRESS_BACK || action.reason === DismissReason.TOUCH_OUTSIDE) {
          action.dismiss();
        }
        this.dialogController = null;
      },
      cancel: (): void => {
        this.dialogController = null;
      }
    });
    this.dialogController = ctl;
    ctl.open();
  }

  private closeDialog(): void {
    const ctl: CustomDialogController | null = this.dialogController;
    this.dialogController = null;
    if (ctl !== null) {
      ctl.close();
    }
  }

  // 模型面板：标题带 Agent 默认值说明（会话覆盖时），副标题「只影响当前会话，不修改 Agent」。
  // 思考视图与模型清单并行取（builder 参数是打开时快照，必须打开前取好）；
  // 思考取数失败只隐藏思考节，不挡模型选择
  private openModel(): void {
    const thinking: Promise<Record<string, Object> | null> = this.fetchThinkingView();
    this.loadChoices().then((): void => {
      const out: DialogOption[] = [];
      for (const c of this.choices) {
        out.push(dialogOptionOf(c.value, c.label, '', null));
      }
      this.dialogTitle = this.agentModelName.length > 0 && this.agentModelName !== this.modelName
        ? `${t($r('app.string.chat_runtime_pick_model'))}（${t($r('app.string.chat_runtime_agent_default'))}：${this.agentModelName}）`
        : t($r('app.string.chat_runtime_pick_model'));
      this.dialogSubtitle = t($r('app.string.chat_runtime_model_subtitle'));
      this.dialogOptions = out;
      // 当前生效项打勾（与 DialogOption.value 同形：providerId||modelId）
      this.dialogCurrent = `${this.modelProvider}||${this.modelName}`;
      this.dialogNoticeTitle = '';
      this.dialogNoticeSub = '';
      this.dialogNoticeIcon = null;
      thinking.then((view: Record<string, Object> | null): void => {
        this.applyThinkingSnapshot(view);
        this.dialogOnConfirm = (v: string, pick: ThinkingPick): void => {
          this.onPick(v, pick);
        };
        this.openDialog(true);
      });
    }).catch((e: Object): void => {
      this.toast(`${t($r('app.string.chat_runtime_switch_failed'))}：${(e as Error).message}`);
    });
  }

  // 思考快照清零：循环/审批面板没有思考节，打开前必须清掉上一轮模型面板留下的值
  //（每次打开新建 controller，不清零会把上次的思考节原样带出来）
  private resetThinkingSnapshot(): void {
    this.dialogThinkKind = '';
    this.dialogThinkStops = [];
    this.dialogThinkSupportsOff = false;
    this.dialogThinkBudgetMin = 1;
    this.dialogThinkBudgetMax = 1;
    this.dialogThinkLevel = '';
    this.dialogThinkBudgetTokens = 0;
    this.dialogThinkCanReset = false;
  }

  // 把思考视图写成弹窗快照：解析走 ThinkingView 共享层（与弹窗内点行实时跟随同一口径），
  // control 缺失/非对象（视图 null）→ 快照保持清零态，思考节隐藏
  private applyThinkingSnapshot(view: Record<string, Object> | null): void {
    this.resetThinkingSnapshot();
    const snap: ThinkingSnapshot | null = parseThinkingView(view);
    if (snap === null) {
      return;
    }
    this.dialogThinkKind = snap.kind;
    this.dialogThinkStops = snap.stops;
    this.dialogThinkSupportsOff = snap.supportsOff;
    this.dialogThinkBudgetMin = snap.budgetMin;
    this.dialogThinkBudgetMax = snap.budgetMax;
    this.dialogThinkLevel = snap.level;
    this.dialogThinkBudgetTokens = snap.budgetTokens;
    this.dialogThinkCanReset = snap.canReset;
  }

  // 循环面板：idle 时可选项（图标 + 友好名 + 描述）；非 idle 时只读卡（对齐 console 的
  // disabled 语义——服务端没有「结束循环」接口，本轮完成前不能切）
  private openLoop(): void {
    this.resetThinkingSnapshot();
    if (isLoopActive(this.sessionKey())) {
      const p: LoopPhase | undefined = getLoopPhase(this.sessionKey());
      const phase: string = p !== undefined ? p.phase : 'running';
      const modeId: string = (p !== undefined && p.modeId.length > 0) ? p.modeId : this.selectedLoopId;
      const modeName: string = (p !== undefined && p.modeName.length > 0)
        ? p.modeName : this.loopNameOf(modeId);
      const word: string = this.loopStateWord(phase);
      this.dialogTitle = t($r('app.string.chat_runtime_loop_title'));
      this.dialogSubtitle = '';
      this.dialogOptions = [];
      this.dialogNoticeTitle = word.length > 0 ? `${modeName} ${word}` : modeName;
      this.dialogNoticeSub = t($r('app.string.chat_loop_locked'));
      this.dialogNoticeIcon = loopIconFor(modeId);
      this.dialogOnConfirm = (v: string): void => {
      };
      this.openDialog(false);
      return;
    }
    this.loadLoopEntries().then((): void => {
      const out: DialogOption[] = [];
      for (const e of this.loopEntries) {
        out.push(dialogOptionOf(e.id, e.name, e.detail, e.icon));
      }
      this.dialogTitle = t($r('app.string.chat_runtime_loop_title'));
      this.dialogSubtitle = t($r('app.string.chat_loop_subtitle'));
      this.dialogOptions = out;
      this.dialogCurrent = this.selectedLoopId;
      this.dialogNoticeTitle = '';
      this.dialogNoticeSub = '';
      this.dialogNoticeIcon = null;
      this.dialogOnConfirm = (v: string): void => {
        this.applyLoopChoice(v);
      };
      this.openDialog(false);
    }).catch((e: Object): void => {
      this.toast(`${t($r('app.string.chat_runtime_switch_failed'))}：${(e as Error).message}`);
    });
  }

  // 选中运行方式（一次性：只对下一条消息生效，对齐 7378 beginSubmission 的 one-shot 语义）
  private applyLoopChoice(id: string): void {
    let entry: LoopEntry | null = null;
    for (const e of this.loopEntries) {
      if (e.id === id) {
        entry = e;
        break;
      }
    }
    if (entry === null) {
      return;
    }
    this.selectedLoopId = id;
    setLoopPick(loopPickOf(entry.command, entry.id, entry.name), this.sessionKey());
    // 芯片即时刷新（发送前就显示所选模式，不必等下一次轮询）
    this.refreshLoopDisplay();
  }

  // 审批面板：跟随 Agent + 四级（对齐 7378 APPROVAL_OPTIONS 与「Agent 默认：…」说明）
  private openApproval(): void {
    this.resetThinkingSnapshot();
    const followLabel: string = this.agentApproval.length > 0
      ? `${t($r('app.string.chat_runtime_follow_agent'))}（${t($r('app.string.chat_runtime_agent_default'))}：${this.approvalLabelOf(this.agentApproval)}）`
      : t($r('app.string.chat_runtime_follow_agent'));
    const out: DialogOption[] = [
      dialogOptionOf('', followLabel, '', null),
      dialogOptionOf('STRICT', t($r('app.string.chat_approval_strict')),
        this.approvalDescOf('STRICT'), null),
      dialogOptionOf('SMART', t($r('app.string.chat_approval_smart')),
        this.approvalDescOf('SMART'), null),
      dialogOptionOf('AUTO', t($r('app.string.chat_approval_auto')),
        this.approvalDescOf('AUTO'), null),
      dialogOptionOf('OFF', t($r('app.string.chat_approval_off')),
        this.approvalDescOf('OFF'), null)
    ];
    this.dialogTitle = t($r('app.string.chat_runtime_approval_title'));
    this.dialogSubtitle = t($r('app.string.chat_runtime_approval_subtitle'));
    this.dialogOptions = out;
    this.dialogCurrent = this.pickedApproval;
    this.dialogNoticeTitle = '';
    this.dialogNoticeSub = '';
    this.dialogNoticeIcon = null;
    this.dialogOnConfirm = (v: string): void => {
      // 只改本会话（本机落盘 + 发送值）；选「跟随 Agent」（空值）= 清掉会话覆盖
      this.pickApproval(v);
    };
    this.openDialog(false);
  }

  // 模型面板确定：模型与思考强度合并提交（弹窗内是同一个「确定」）。
  // 换模型先写模型（PUT 响应即新模型的思考视图）再按新 model_key 写思考；
  // 只改思考则按当前 model_key 写；两者都没变不产生网络写
  private async onPick(value: string, pick: ThinkingPick): Promise<void> {
    const parts: string[] = value.split('||');
    const c: QpConnection | null = this.conn;
    if (parts.length !== 2 || c === null || this.busy) {
      return;
    }
    const modelChanged: boolean = parts[0] !== this.modelProvider || parts[1] !== this.modelName;
    if (!modelChanged && !pick.changed) {
      return;
    }
    this.busy = true;
    try {
      if (modelChanged) {
        const body: Record<string, Object> = {};
        body['provider_id'] = parts[0];
        body['model'] = parts[1];
        // 会话级写入（console 同口径）：PUT /chats/{id}/model 只改本会话，不动 Agent 默认模型
        //（此前写 /models/active scope=agent，等于把整个 Agent 的模型换掉）
        const resp: http.HttpResponse = await this.send(
          `/chats/${encodeURIComponent(this.chatId)}/model`, http.RequestMethod.PUT,
          JSON.stringify(body));
        if (resp.responseCode < 200 || resp.responseCode >= 300) {
          throw new Error(`HTTP ${resp.responseCode}`);
        }
        this.modelProvider = parts[0];
        this.modelName = parts[1];
        if (pick.changed) {
          // 思考偏好按 model_key 分键存储：换模型后按新键写；档位对新模型非法时
          // 服务端回 422（applyThinking 提示，新会话偏好本就从 inherit 起，不影响模型切换）
          await this.applyThinking(parts[0], parts[1], pick);
        }
      } else if (pick.changed) {
        await this.applyThinking(this.modelProvider, this.modelName, pick);
      }
      await this.load();
    } catch (e) {
      this.toast(`${t($r('app.string.chat_runtime_switch_failed'))}：${(e as Error).message}`);
    } finally {
      this.busy = false;
    }
  }

  // 写思考强度（console 同口径：body 即偏好逐字，budget 与 budget_tokens 成对；
  // level '' = 回落默认 inherit）。409 = 会话模型已变（随后的 load 会重取），
  // 422 = 该档位对此模型非法 → 都只提示，不当作整体失败
  private async applyThinking(providerId: string, model: string, pick: ThinkingPick): Promise<void> {
    const body: Record<string, Object> = {};
    body['level'] = pick.level.length > 0 ? pick.level : 'inherit';
    if (pick.level === 'budget') {
      body['budget_tokens'] = pick.budgetTokens;
    }
    const key: string = encodeURIComponent(`${providerId}:${model}`);
    const resp: http.HttpResponse = await this.send(
      `/chats/${encodeURIComponent(this.chatId)}/thinking?model_key=${key}`,
      http.RequestMethod.PUT, JSON.stringify(body));
    if (resp.responseCode === 409 || resp.responseCode === 422) {
      this.toast(t($r('app.string.chat_thinking_apply_failed')));
      return;
    }
    if (resp.responseCode < 200 || resp.responseCode >= 300) {
      throw new Error(`HTTP ${resp.responseCode}`);
    }
  }

  build() {
    Column() {
      // 横向滚动：控制项多时不换行、不挤压（7378 同为横向可滚的控制条）
      Scroll() {
        Row({ space: 4 }) {
          RuntimeChip({
            icon: $r('app.media.model_llm'),
            label: $r('app.string.chat_runtime_model'),
            value: this.modelName,
            tappable: !this.busy,
            onTap: (): void => {
              this.openModel();
            }
          })
          RuntimeChip({
            icon: this.loopIcon,
            label: $r('app.string.chat_runtime_loop'),
            value: this.loopText,
            tappable: !this.busy,
            onTap: (): void => {
              this.openLoop();
            }
          })
          RuntimeChip({
            icon: $r('app.media.shield_check'),
            label: $r('app.string.chat_runtime_approval'),
            value: this.approval,
            tappable: !this.busy,
            onTap: (): void => {
              this.openApproval();
            }
          })
        }
        .padding({ left: 3, right: 3 })
      }
      .scrollable(ScrollDirection.Horizontal)
      .scrollBar(BarState.Off)
      .width('100%')
      // 按压/拖动的交互形变会超出按钮自身范围：滚动容器默认裁切子节点 →
      // 关掉裁切并给上下留出形变空间，拖动时不再被切边
      .clip(false)
      .padding({ top: 4, bottom: 4 })
    }
    .width('100%')
  }
}
