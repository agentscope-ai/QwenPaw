/*
 * 连接存活探测（全应用单一事实源）。
 *
 * 为什么需要它：「已连接」的含义此前是「本地存着连接配置」——只要配对过就一直显示绿色，
 * 断网、服务端停机、地址失效都看不出来（工作台顶部状态卡、智能体页徽章、会话页状态文案同病）。
 *
 * 做法：全应用只跑一个定时器（根页启停），每 12s 用 GET /api/agents 探一次可达性
 * （3s 超时，避免等满 10s 默认超时）；结果变化时广播 CONN_LIVENESS_EVENT，
 * 各页只订阅、不各自轮询，避免请求放大与状态不一致。
 * 连接变更（保存/切换/断开）与智能体切换都立即重探一次。
 */

import { Context } from '@kit.AbilityKit';
import { emitter } from '@kit.BasicServicesKit';
import { http } from '@kit.NetworkKit';
import { QpConnection, loadConnection } from './ConnectionStore';
import { hostOf } from './PairingModel';
import { doRequest } from './ConnectionService';
import { CONN_CHANGE_EVENT } from './AppEvents';
import { AGENT_CHANGE_EVENT } from './AgentsService';

export const CONN_LIVENESS_EVENT: string = 'qp_conn_liveness';

// 存活探测超时：远小于业务请求（10s），断网/停机时尽快翻红
const PROBE_TIMEOUT_MS: number = 3000;
// 轮询间隔：12s 足够「实时」，又不至于在弱网下堆请求
const PROBE_INTERVAL_MS: number = 12000;

export interface ConnLiveness {
  online: boolean;
  host: string;
}

let watchTimer: number = -1;
let probing: boolean = false;
let watching: boolean = false;
let current: ConnLiveness = { online: false, host: '' };
let changeListener: ((data: emitter.EventData) => void) | null = null;

export function lastLiveness(): ConnLiveness {
  return current;
}

function publish(next: ConnLiveness): void {
  const changed: boolean = next.online !== current.online || next.host !== current.host;
  current = next;
  if (changed) {
    // 不带载荷：订阅方读 lastLiveness()（避免 EventData 的 Record 取值在 ArkTS 下的类型纠缠，
    // 也与工程内「pending + 取用」的事件口径一致）
    emitter.emit(CONN_LIVENESS_EVENT);
  }
}

// 探一次：没有连接配置 = 离线；有配置但请求失败/非 200 = 离线
export async function probeLiveness(context: Context): Promise<ConnLiveness> {
  if (probing) {
    return current;
  }
  probing = true;
  let next: ConnLiveness = { online: false, host: '' };
  try {
    const conn: QpConnection | null = await loadConnection(context);
    if (conn !== null) {
      const host: string = hostOf(conn.baseUrl);
      try {
        const resp: http.HttpResponse = await doRequest(
          `${conn.baseUrl}/api/agents`, http.RequestMethod.GET, null,
          conn.token.length > 0 ? conn.token : null, 'default', PROBE_TIMEOUT_MS);
        next = { online: resp.responseCode === 200, host: resp.responseCode === 200 ? host : '' };
      } catch (e) {
        next = { online: false, host: '' };
      }
    }
  } catch (e) {
    next = { online: false, host: '' };
  }
  probing = false;
  publish(next);
  return next;
}

export function startLivenessWatch(context: Context): void {
  if (watching) {
    return;
  }
  watching = true;
  probeLiveness(context);
  watchTimer = setInterval((): void => {
    probeLiveness(context);
  }, PROBE_INTERVAL_MS);
  // 连接增删改 / 切换智能体：立即重探，不等下一个周期
  changeListener = (_data: emitter.EventData): void => {
    probeLiveness(context);
  };
  emitter.on(CONN_CHANGE_EVENT, changeListener);
  emitter.on(AGENT_CHANGE_EVENT, changeListener);
}

export function stopLivenessWatch(): void {
  if (!watching) {
    return;
  }
  watching = false;
  if (watchTimer >= 0) {
    clearInterval(watchTimer);
    watchTimer = -1;
  }
  if (changeListener !== null) {
    emitter.off(CONN_CHANGE_EVENT, changeListener);
    emitter.off(AGENT_CHANGE_EVENT, changeListener);
    changeListener = null;
  }
}
