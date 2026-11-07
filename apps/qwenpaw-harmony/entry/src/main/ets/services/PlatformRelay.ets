/*
 * Platform 远程访问（中继）—— 移植 PR #7378 api/platformRelay.ts + api/client.ts 的
 * getPlatformRelayStatus / authorizePlatformRelay（另加 features/platform/RelayNodesSheet.tsx 的数据面）。
 *
 * 两段链路，别混：
 *   ① 本机 QwenPaw 侧（hub 模式实例，走 doRequest）：
 *        GET  /remote-access/platform                         → 远程访问状态
 *        POST /remote-access/platform/authorize-session       → 用 Platform access_token 绑定本机
 *   ② Platform 侧（走 platformRequest，需 Platform 登录）：
 *        GET    /api/v1/qwenpaw-relay/quota                   → 自部署连接额度
 *        GET    /api/v1/qwenpaw-relay/nodes                   → 已绑定节点
 *        DELETE /api/v1/qwenpaw-relay/nodes/{id}              → 解除绑定
 * 额度与节点列表由 Platform 汇总（云端 QwenPaw 不计入自部署额度），故管理面板走 ②。
 */

import { http } from '@kit.NetworkKit';
import { Context } from '@kit.AbilityKit';
import { doRequest, jsonOf, ConnectError } from './ConnectionService';
import { platformRequest } from './PlatformSession';
import { objOf, strOf, numOf, boolOf } from './JsonUtil';
import { t, tf } from './I18n';

// 状态口径与 7378 api/types.ts PlatformRelayStatus 一致
export const RELAY_NOT_CONNECTED: string = 'not_connected';
export const RELAY_CONNECTED: string = 'connected';

export interface PlatformRelayStatus {
  status: string;
  platformUrl: string;
  qwenpawId: string;
  name: string;
  nodeId: string;
  transportStatus: string;
  transportError: string;
}

// 额度与节点要经 @Prop 进半模态（ArkUI @Prop 以类实例为稳妥口径，与 SheetOption 同）
export class PlatformRelayQuota {
  used: number = 0;
  limit: number = -1;      // -1 = 不限量（7378 为 limit: number | null）
  canBind: boolean = true;
}

export class PlatformRelayNode {
  id: string = '';
  qwenpawId: string = '';
  name: string = '';
  status: string = '';     // online / offline
  lastSeenAt: string = '';
}

function parseRelayStatus(data: Object): PlatformRelayStatus {
  const o: Record<string, Object> | null = objOf(data);
  if (o === null) {
    throw new ConnectError(t($r('app.string.relay_err_unexpected')));
  }
  const status: string = strOf(o, 'status', RELAY_NOT_CONNECTED);
  return {
    status: status.length > 0 ? status : RELAY_NOT_CONNECTED,
    platformUrl: strOf(o, 'platform_url', ''),
    qwenpawId: strOf(o, 'qwenpaw_id', ''),
    name: strOf(o, 'name', ''),
    nodeId: strOf(o, 'node_id', ''),
    transportStatus: strOf(o, 'transport_status', ''),
    transportError: strOf(o, 'transport_error', '')
  };
}

// 本机远程访问状态（GET /remote-access/platform，hub 模式实例才有）
export async function getRelayStatus(baseUrl: string, token: string,
  agentId: string): Promise<PlatformRelayStatus> {
  const resp: http.HttpResponse = await doRequest(
    `${baseUrl}/remote-access/platform`, http.RequestMethod.GET, null,
    token.length > 0 ? token : null, agentId);
  if (resp.responseCode === 404) {
    throw new ConnectError(t($r('app.string.relay_err_unsupported')));
  }
  if (resp.responseCode === 401 || resp.responseCode === 403) {
    throw new ConnectError(tf($r('app.string.err_token_expired'), resp.responseCode));
  }
  if (resp.responseCode !== 200) {
    throw new ConnectError(tf($r('app.string.relay_err_load'), resp.responseCode));
  }
  return parseRelayStatus(jsonOf(resp));
}

// 开启/重授权本机 Platform 远程访问（POST /remote-access/platform/authorize-session）
export async function authorizeRelay(baseUrl: string, token: string, agentId: string,
  accessToken: string, platformUrl: string, name: string): Promise<PlatformRelayStatus> {
  const body: Record<string, Object> = {};
  body['access_token'] = accessToken;
  body['platform_url'] = platformUrl;
  body['name'] = name;
  const resp: http.HttpResponse = await doRequest(
    `${baseUrl}/remote-access/platform/authorize-session`, http.RequestMethod.POST,
    JSON.stringify(body), token.length > 0 ? token : null, agentId);
  if (resp.responseCode === 401 || resp.responseCode === 403) {
    throw new ConnectError(tf($r('app.string.err_token_expired'), resp.responseCode));
  }
  if (resp.responseCode < 200 || resp.responseCode >= 300) {
    throw new ConnectError(tf($r('app.string.relay_err_connect'), resp.responseCode));
  }
  return parseRelayStatus(jsonOf(resp));
}

// 自部署连接额度（GET /api/v1/qwenpaw-relay/quota）
export async function getRelayQuota(ctx: Context): Promise<PlatformRelayQuota> {
  const data: Object = await platformRequest(ctx, '/api/v1/qwenpaw-relay/quota',
    http.RequestMethod.GET, null);
  const o: Record<string, Object> = objOf(data) !== null
    ? objOf(data) as Record<string, Object> : {};
  const quota: PlatformRelayQuota = new PlatformRelayQuota();
  quota.used = numOf(o, 'used', 0);
  quota.limit = numOf(o, 'limit', -1);
  quota.canBind = boolOf(o, 'can_bind', true);
  return quota;
}

// 已绑定节点（GET /api/v1/qwenpaw-relay/nodes）
export async function listRelayNodes(ctx: Context): Promise<PlatformRelayNode[]> {
  const data: Object = await platformRequest(ctx, '/api/v1/qwenpaw-relay/nodes',
    http.RequestMethod.GET, null);
  const out: PlatformRelayNode[] = [];
  let entries: Object[] = [];
  if (Array.isArray(data)) {
    entries = data as Object[];
  } else {
    const o: Record<string, Object> | null = objOf(data);
    const nodes: Object = o !== null && o['nodes'] !== undefined ? o['nodes'] : new Object();
    entries = Array.isArray(nodes) ? nodes as Object[] : [];
  }
  for (const entry of entries) {
    const o: Record<string, Object> | null = objOf(entry);
    if (o === null) {
      continue;
    }
    const id: string = strOf(o, 'id', '');
    if (id.length === 0) {
      continue;
    }
    let lastSeen: string = strOf(o, 'last_seen_at', '');
    if (lastSeen.length === 0) {
      lastSeen = strOf(o, 'lastSeenAt', '');
    }
    const node: PlatformRelayNode = new PlatformRelayNode();
    node.id = id;
    node.qwenpawId = strOf(o, 'qwenpaw_id', '');
    node.name = strOf(o, 'name', '');
    node.status = strOf(o, 'status', '');
    node.lastSeenAt = lastSeen;
    out.push(node);
  }
  return out;
}

// 解除绑定（DELETE /api/v1/qwenpaw-relay/nodes/{id}）
export async function revokeRelayNode(ctx: Context, nodeId: string): Promise<void> {
  await platformRequest(ctx,
    `/api/v1/qwenpaw-relay/nodes/${encodeURIComponent(nodeId)}`,
    http.RequestMethod.DELETE, null);
}
