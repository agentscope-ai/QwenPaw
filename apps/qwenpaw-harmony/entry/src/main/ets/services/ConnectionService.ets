/*
 * LAN 直连服务 —— 对齐 PR #7378 src/api/client.ts 的直连链路：
 *   1. 有配对码：POST {base}/api/auth/pairing/redeem {ticket} → {token, username, mode?}
 *   2. GET {base}/api/auth/status → {enabled, has_users}
 *      - 未开账号体系（enabled=false）且无 token → 开放模式直连
 *      - 有 token → GET {base}/api/auth/verify（Bearer）
 *      - 开了账号体系且无 ticket → 拒绝
 *   3. 探测 GET {base}/api/agents → {agents: [...]}
 * 超时语义与 connectionAttempt.ts 一致：10s，127.0.0.1 专项提示。
 */

import { http } from '@kit.NetworkKit';
import { BusinessError } from '@kit.BasicServicesKit';
import { QpConnection } from './ConnectionStore';
import { normalizeBaseUrl, hostOf } from './PairingModel';

const CONNECT_TIMEOUT_MS: number = 10000;

export class ConnectError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ConnectError';
  }
}

export interface ConnectOutcome {
  connection: QpConnection;
  agentCount: number;
  agentNames: string[];
  openMode: boolean;
}

export function doRequest(url: string, method: http.RequestMethod, body: string | null,
  token: string | null, agentId: string): Promise<http.HttpResponse> {
  const req: http.HttpRequest = http.createHttp();
  const header: Record<string, Object> = {
    'Content-Type': 'application/json',
    'Accept': 'application/json'
  };
  if (token !== null && token.length > 0) {
    header['Authorization'] = `Bearer ${token}`;
  }
  // 对齐 PR #7378 client.ts headers()：所有 /api 请求携带当前智能体（会话/审批按 agent 隔离）
  if (agentId.length > 0) {
    header['X-Agent-Id'] = agentId;
  }
  const options: http.HttpRequestOptions = {
    method: method,
    header: header,
    connectTimeout: CONNECT_TIMEOUT_MS,
    readTimeout: CONNECT_TIMEOUT_MS,
    expectDataType: http.HttpDataType.STRING
  };
  if (body !== null) {
    options.extraData = body;
  }
  const promise: Promise<http.HttpResponse> = req.request(url, options);
  promise.then(() => req.destroy()).catch(() => req.destroy());
  return promise;
}

export function jsonOf(response: http.HttpResponse): Record<string, Object> {
  const result: Object = response.result;
  if (typeof result !== 'string') {
    throw new ConnectError('服务端返回了非 JSON 内容。');
  }
  try {
    return JSON.parse(result) as Record<string, Object>;
  } catch (e) {
    throw new ConnectError('服务端返回了非 JSON 内容。');
  }
}

// 顶层返回数组的端点（/tools、/skills、/workspace/git/log 等）：jsonOf 是对象口径，数组需单独解析
export function jsonArrayOf(response: http.HttpResponse): Object[] {
  const result: Object = response.result;
  if (typeof result !== 'string') {
    return [];
  }
  try {
    const parsed: Object = JSON.parse(result as string);
    return Array.isArray(parsed) ? parsed as Object[] : [];
  } catch (e) {
    return [];
  }
}

export function timeoutHint(baseUrl: string): string {
  const host: string = hostOf(baseUrl);
  if (host === '127.0.0.1' || host === 'localhost' || host === '[::1]' || host === '::1') {
    return '连接超时。手机上的 127.0.0.1 指向手机自身；真机请填写电脑的局域网 IP。';
  }
  return '连接超时。请确认手机与 QwenPaw 在同一网络、地址和端口正确，并使用 --host 0.0.0.0 启动服务。';
}

export function describeConnectError(baseUrl: string, e: Error): string {
  if (e instanceof ConnectError) {
    return e.message;
  }
  const msg: string = e.message ? e.message : String(e);
  const code: number = (e as BusinessError).code !== undefined ? (e as BusinessError).code : -1;
  if (code === 2300006 || code === 2300005 || code === 2300004 || code === 2300003 ||
    /time\s?out|timed out/i.test(msg)) {
    return timeoutHint(baseUrl);
  }
  if (code >= 2300000 && code < 2400000) {
    return `网络错误（code ${code}）。请确认手机与 QwenPaw 在同一网络、地址和端口正确，并使用 --host 0.0.0.0 启动服务。`;
  }
  if (/refused|ECONNREFUSED|no route|unreachable|EHOSTUNREACH/i.test(msg)) {
    return `无法连接 ${baseUrl}。请确认服务正在运行、地址和端口正确。`;
  }
  return `连接失败：${msg}`;
}

export async function connectToQwenPaw(baseUrlRaw: string, ticketRaw: string): Promise<ConnectOutcome> {
  const baseUrl: string = normalizeBaseUrl(baseUrlRaw);
  const ticket: string = ticketRaw.trim();

  let token: string = '';
  let username: string = '';
  let serverMode: string = '';
  if (ticket.length > 0) {
    const redeemBody: Record<string, string> = { 'ticket': ticket };
    const redeemResp: http.HttpResponse = await doRequest(
      `${baseUrl}/api/auth/pairing/redeem`, http.RequestMethod.POST,
      JSON.stringify(redeemBody), null, 'default');
    if (redeemResp.responseCode !== 200) {
      throw new ConnectError(`配对码兑换失败（HTTP ${redeemResp.responseCode}）。请确认配对码未过期且属于该地址。`);
    }
    const data: Record<string, Object> = jsonOf(redeemResp);
    token = typeof data['token'] === 'string' ? data['token'] as string : '';
    username = typeof data['username'] === 'string' ? data['username'] as string : '';
    serverMode = data['mode'] === 'hub' ? 'hub' : '';
    if (token.length === 0) {
      throw new ConnectError('服务端未返回有效会话票据。');
    }
  }

  const statusResp: http.HttpResponse = await doRequest(
    `${baseUrl}/api/auth/status`, http.RequestMethod.GET, null, null, 'default');
  if (statusResp.responseCode !== 200) {
    throw new ConnectError(`无法访问服务（HTTP ${statusResp.responseCode}）。`);
  }
  const status: Record<string, Object> = jsonOf(statusResp);
  const authEnabled: boolean = status['enabled'] === true;
  if (token.length === 0 && !authEnabled) {
    // 开放模式：无账号体系，直连
  } else if (token.length > 0) {
    const verifyResp: http.HttpResponse = await doRequest(
      `${baseUrl}/api/auth/verify`, http.RequestMethod.GET, null, token, 'default');
    if (verifyResp.responseCode !== 200) {
      throw new ConnectError(`票据校验失败（HTTP ${verifyResp.responseCode}）。配对码可能无效或已过期。`);
    }
  } else {
    throw new ConnectError('该 QwenPaw 已开启账号登录，请输入配对码（QwenPaw 工作区配对页）。');
  }

  const connection: QpConnection = {
    baseUrl: baseUrl,
    token: token,
    username: username,
    agentId: 'default',
    source: 'private',
    serverMode: serverMode
  };

  let agentCount: number = 0;
  const agentNames: string[] = [];
  try {
    const agentsResp: http.HttpResponse = await doRequest(
      `${baseUrl}/api/agents`, http.RequestMethod.GET, null,
      token.length > 0 ? token : null, 'default');
    if (agentsResp.responseCode === 200) {
      const data: Record<string, Object> = jsonOf(agentsResp);
      const arr: Object = data['agents'];
      if (Array.isArray(arr)) {
        const items: Object[] = arr as Object[];
        agentCount = items.length;
        for (const item of items) {
          const a: Record<string, Object> = item as Record<string, Object>;
          if (typeof a['name'] === 'string' && (a['name'] as string).length > 0) {
            agentNames.push(a['name'] as string);
          } else if (typeof a['id'] === 'string') {
            agentNames.push(a['id'] as string);
          }
        }
      }
    }
  } catch (e) {
    // agents 探测失败不阻断连接（可能服务版本差异）
  }

  const outcome: ConnectOutcome = {
    connection: connection,
    agentCount: agentCount,
    agentNames: agentNames,
    openMode: token.length === 0 && !authEnabled
  };
  return outcome;
}
