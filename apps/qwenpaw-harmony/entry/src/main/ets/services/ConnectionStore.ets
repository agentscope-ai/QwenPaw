/*
 * 连接持久化（多连接 v2）—— @ohos.data.preferences。
 * 对齐 PR #7378 storage/connection.ts 的多连接模型：connections[] + current key
 * （connectionKey = baseUrl 小写）；v1 单连接自动迁移。
 * 已知差距：token 明文存应用沙箱 preferences，未进 HUKS 安全存储（LAN 调试可接受，商用前需补）。
 */

import { preferences } from '@kit.ArkData';
import { Context } from '@kit.AbilityKit';
import { registerGatewayConnection } from './PlatformGateway';
import { notifyConnectionChange } from './AppEvents';

export interface QpConnection {
  baseUrl: string;
  token: string;
  username: string;
  agentId: string;
  source: string;
  serverMode: string;
  // 云端实例经 Platform 网关的复签入口（'' = 不需要复签；'platform' 源的连接才有值）
  platformAccessPath: string;
}

export function connectionKey(conn: QpConnection): string {
  return conn.baseUrl.toLowerCase();
}

interface ConnectionsPayload {
  current: string;
  list: QpConnection[];
}

const STORE_NAME: string = 'qwenpaw.connection';
const KEY_V2: string = 'qwenpaw.connections.v2';
const KEY_V1: string = 'qwenpaw.mobile.connection.v1';

function parseConn(raw: string): QpConnection | null {
  try {
    const parsed: Record<string, Object> = JSON.parse(raw) as Record<string, Object>;
    if (typeof parsed['baseUrl'] !== 'string' || typeof parsed['token'] !== 'string') {
      return null;
    }
    const conn: QpConnection = {
      baseUrl: parsed['baseUrl'] as string,
      token: parsed['token'] as string,
      username: typeof parsed['username'] === 'string' ? parsed['username'] as string : '',
      agentId: typeof parsed['agentId'] === 'string' ? parsed['agentId'] as string : 'default',
      source: typeof parsed['source'] === 'string' ? parsed['source'] as string : 'private',
      serverMode: typeof parsed['serverMode'] === 'string' ? parsed['serverMode'] as string : '',
      platformAccessPath: typeof parsed['platformAccessPath'] === 'string'
        ? parsed['platformAccessPath'] as string : ''
    };
    // 请求层按 origin 查"要不要走网关复签"：装载即登记
    registerGatewayConnection(conn.baseUrl, conn.platformAccessPath);
    return conn;
  } catch (e) {
    return null;
  }
}

function payloadOf(current: string, list: QpConnection[]): ConnectionsPayload {
  const p: ConnectionsPayload = { current: current, list: list };
  return p;
}

async function loadPayload(context: Context): Promise<ConnectionsPayload> {
  try {
    const store: preferences.Preferences = await preferences.getPreferences(context, STORE_NAME);
    const raw: preferences.ValueType = await store.get(KEY_V2, '');
    if (typeof raw === 'string' && raw.length > 0) {
      const obj: Record<string, Object> = JSON.parse(raw) as Record<string, Object>;
      const listRaw: Object = obj['list'];
      const list: QpConnection[] = [];
      if (Array.isArray(listRaw)) {
        for (const item of listRaw as Object[]) {
          const c: QpConnection | null = parseConn(JSON.stringify(item));
          if (c !== null) {
            list.push(c);
          }
        }
      }
      const cur: Object = obj['current'];
      return payloadOf(typeof cur === 'string' ? cur as string : '', list);
    }
    // v1（单连接）→ v2 迁移
    const v1: preferences.ValueType = await store.get(KEY_V1, '');
    if (typeof v1 === 'string' && v1.length > 0) {
      const c: QpConnection | null = parseConn(v1);
      if (c !== null) {
        return payloadOf(connectionKey(c), [c]);
      }
    }
  } catch (e) {
    // 读取异常 → 空
  }
  return payloadOf('', []);
}

async function savePayload(context: Context, payload: ConnectionsPayload): Promise<void> {
  const store: preferences.Preferences = await preferences.getPreferences(context, STORE_NAME);
  await store.put(KEY_V2, JSON.stringify(payload));
  await store.flush();
}

// 全部已配对连接（对齐 7378 connections）
export async function loadConnections(context: Context): Promise<QpConnection[]> {
  const p: ConnectionsPayload = await loadPayload(context);
  return p.list;
}

// 当前连接（= current 命中项，缺省回落首个）
export async function loadConnection(context: Context): Promise<QpConnection | null> {
  const p: ConnectionsPayload = await loadPayload(context);
  for (const c of p.list) {
    if (connectionKey(c) === p.current) {
      return c;
    }
  }
  return p.list.length > 0 ? p.list[0] : null;
}

// 新增 / 更新（按 connectionKey 去重）并设为当前
export async function saveConnection(context: Context, conn: QpConnection): Promise<void> {
  const p: ConnectionsPayload = await loadPayload(context);
  const key: string = connectionKey(conn);
  const next: QpConnection[] = [];
  for (const c of p.list) {
    if (connectionKey(c) !== key) {
      next.push(c);
    }
  }
  next.push(conn);
  await savePayload(context, payloadOf(key, next));
  // 当前连接变了 → 广播（按服务端取值的东西要跟着重取，如主题色）
  notifyConnectionChange();
}

// 切换当前连接
export async function switchConnection(context: Context, key: string): Promise<void> {
  const p: ConnectionsPayload = await loadPayload(context);
  await savePayload(context, payloadOf(key, p.list));
  notifyConnectionChange();
}

// 移除一个连接（若为当前，则回落到剩余首个）
export async function removeConnection(context: Context, key: string): Promise<void> {
  const p: ConnectionsPayload = await loadPayload(context);
  const next: QpConnection[] = [];
  for (const c of p.list) {
    if (connectionKey(c) !== key) {
      next.push(c);
    }
  }
  let current: string = p.current;
  if (current === key) {
    current = next.length > 0 ? connectionKey(next[0]) : '';
  }
  await savePayload(context, payloadOf(current, next));
  // 移除当前连接会让当前落到另一个服务端上 → 同样要广播
  notifyConnectionChange();
}

// 断开：清空全部连接（v1/v2 一并清）
export async function clearConnection(context: Context): Promise<void> {
  const store: preferences.Preferences = await preferences.getPreferences(context, STORE_NAME);
  await store.delete(KEY_V2);
  await store.delete(KEY_V1);
  await store.flush();
  // 断开后当前连接为空 → 与保存/切换/移除同口径广播，订阅方（智能体列表/工作台/根页）即时失效
  notifyConnectionChange();
}
