/*
 * 会话运行控制的本机传值（对齐 PR #7378：审批等级随「发送」生效；循环选择是一次性的）。
 * 为什么用模块级单例：运行条挂在 Tabs 的 tabBar builder 内，该子树只构建一次、父组件状态传不进去
 * （见 harmony-arkui-tabbar-builder-runs-once），故由运行条写入、发送链路在发送时读取。
 *
 * 循环 phase 注册表（loopPhase）：运行条轮询 GET /loops/status 推导当前回合的阶段，
 * 发送链路在发送成功后写入「starting」。两侧是不同组件（tabBar builder 子树传不进状态），
 * 经此注册表传值；发送保护（isLoopActive）必须查注册表而不是任一组件的本地状态，
 * 否则轮询与服务端状态之间会互相覆盖（比如服务端还没感知到 running 时把 starting 抹回 idle）。
 */

// 审批等级：值来自服务端（Agent 级 approval_level，见 services/AgentApproval）。
// 空串 = 服务端未给值 → 发送不带 request_context.approval_level，由 Agent 配置决定。
let approvalLevel: string = '';

export function setSessionApproval(value: string): void {
  approvalLevel = value;
}

export function sessionApproval(): string {
  return approvalLevel;
}

// ---- 循环选择（一次性，按会话存） ----

export class LoopPick {
  command: string = '';
  modeId: string = '';
  displayName: string = '';
}

export function loopPickOf(command: string, modeId: string, displayName: string): LoopPick {
  const p: LoopPick = new LoopPick();
  p.command = command;
  p.modeId = modeId;
  p.displayName = displayName;
  return p;
}

let loopPick: LoopPick | null = null;
let loopPickKey: string = '';

export function setLoopPick(pick: LoopPick, sessionKey: string): void {
  loopPick = pick;
  loopPickKey = sessionKey;
}

/** 取出并复位（一次性，对齐 7378 beginSubmission 的 one-shot）；无选择或属于别的会话时返回 null。 */
export function takeLoopPick(sessionKey: string): LoopPick | null {
  if (loopPick === null || loopPickKey !== sessionKey) {
    return null;
  }
  const p: LoopPick = loopPick;
  loopPick = null;
  loopPickKey = '';
  return p;
}

// ---- 循环 phase 注册表（phase 取值：idle | starting | running | awaiting_user） ----

export class LoopPhase {
  phase: string = 'idle';
  modeId: string = '';
  modeName: string = '';
}

let loopPhaseTable: Map<string, LoopPhase> = new Map<string, LoopPhase>();
// 单监听：同一时刻只有一个会话详情页（运行条），够用且避免多订阅管理
let loopPhaseListener: ((sessionKey: string, phase: LoopPhase) => void) | null = null;

export function setLoopPhase(sessionKey: string, phase: string, modeId: string, modeName: string): void {
  const cur: LoopPhase | undefined = loopPhaseTable.get(sessionKey);
  if (cur !== undefined && cur.phase === phase && cur.modeId === modeId) {
    return;
  }
  const p: LoopPhase = new LoopPhase();
  p.phase = phase;
  p.modeId = modeId;
  p.modeName = modeName;
  loopPhaseTable.set(sessionKey, p);
  if (loopPhaseListener !== null) {
    loopPhaseListener(sessionKey, p);
  }
}

export function getLoopPhase(sessionKey: string): LoopPhase | undefined {
  return loopPhaseTable.get(sessionKey);
}

/** 当前回合是否在进行（发送保护）：starting/running/awaiting_user 时丢弃新的循环选择。 */
export function isLoopActive(sessionKey: string): boolean {
  const p: LoopPhase | undefined = loopPhaseTable.get(sessionKey);
  return p !== undefined && p.phase !== 'idle';
}

/** phase 变化监听（运行条 aboutToAppear 订阅 / aboutToDisappear 注销；传 null 注销）。 */
export function onLoopPhaseChange(listener: ((sessionKey: string, phase: LoopPhase) => void) | null): void {
  loopPhaseListener = listener;
}

/**
 * 对齐 7378 features/chat/sessionControlsModel.ts 的 applyLoopModeCommand：
 * 无命令 → 原样；用户已写斜杠命令 → 不覆盖；否则前置 "/<command> "。
 */
export function applyLoopCommand(text: string, command: string): string {
  const cmd: string = command.trim();
  if (cmd.length === 0) {
    return text;
  }
  if (text.trimStart().startsWith('/')) {
    return text;
  }
  return `/${cmd} ${text}`;
}
