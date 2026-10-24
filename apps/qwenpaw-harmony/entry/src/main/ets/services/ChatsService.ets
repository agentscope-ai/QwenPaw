/*
 * 会话列表服务 —— GET {base}/api/chats?archived=${archived}（对齐 PR #7378 client.ts listChats）。
 * ChatSpec 字段防御式解析；updated_at ISO 字符串转本地展示（相对时间）。
 */

import { http } from '@kit.NetworkKit';
import { util } from '@kit.ArkTS';
import { doRequest, jsonOf, ConnectError } from './ConnectionService';
import { t, tf } from './I18n';

export interface ChatInfo {
  id: string;
  sessionId: string;     // 会话的 session_id（发送用；对齐 RN store 的 sessionId: chat.session_id）
  // 会话归属的 user_id（服务端按 (session_id, user_id) 定位 chat，发/重连都要带；
  // 会话详情接口不返回该字段，只有列表/创建接口有 —— 故必须从列表项带到详情页）
  userId: string;
  name: string;
  updatedAtMs: number;   // 0 = 未知
  pinned: boolean;
  status: string;        // 服务端运行态（对齐 7378 ChatSpec.status；running 即会话正在跑）
  createdAtMs: number;   // 0 = 未知（对齐 7378 hasExistingWork 的 created_at）
  groupId: string;       // 所属分组（空 = 未分组；对齐 RN ChatSpec.group_id）
}

// 会话分组（对齐 PR #7378 client.ts ChatGroup：GET/POST/PUT/DELETE /chats/groups）
export interface ChatGroup {
  id: string;
  name: string;
  kind: string;          // default / cron / subagents / 自定义
  order: number;
}

function strOf(rec: Record<string, Object>, key: string): string {
  const v: Object = rec[key];
  return typeof v === 'string' ? v as string : '';
}

export function isoToMs(iso: string): number {
  if (iso.length === 0) {
    return 0;
  }
  const t: number = Date.parse(iso);
  return isNaN(t) ? 0 : t;
}

// 相对时间：今天 HH:mm / 今年 M月d日 / 跨年 yyyy/M/d
export function relativeTime(ms: number): string {
  if (ms <= 0) {
    return '';
  }
  const d: Date = new Date(ms);
  const now: Date = new Date();
  const sameYear: boolean = d.getFullYear() === now.getFullYear();
  const sameDay: boolean = sameYear && d.getMonth() === now.getMonth()
    && d.getDate() === now.getDate();
  if (sameDay) {
    return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`;
  }
  if (sameYear) {
    return tf($r('app.string.date_month_day'), d.getMonth() + 1, d.getDate());
  }
  return `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()}`;
}

export async function fetchChats(baseUrl: string, token: string, agentId: string,
  archived: boolean = false): Promise<ChatInfo[]> {
  const resp: http.HttpResponse = await doRequest(
    `${baseUrl}/api/chats?archived=${archived}`, http.RequestMethod.GET, null,
    token.length > 0 ? token : null, agentId);
  if (resp.responseCode === 401 || resp.responseCode === 403) {
    throw new ConnectError(tf($r('app.string.err_token_expired'), resp.responseCode));
  }
  if (resp.responseCode !== 200) {
    throw new ConnectError(tf($r('app.string.err_load_chats'), resp.responseCode));
  }
  const data: Object = jsonOf(resp)['chats'] !== undefined ? jsonOf(resp)['chats'] : jsonOf(resp);
  if (!Array.isArray(data)) {
    // /chats 直接返回数组（PR listChats 类型 = ChatSpec[]）
    return [];
  }
  const items: Object[] = data as Object[];
  const out: ChatInfo[] = [];
  for (const item of items) {
    const c: Record<string, Object> = item as Record<string, Object>;
    const id: string = strOf(c, 'id');
    const name: string = strOf(c, 'name').length > 0 ? strOf(c, 'name') : id;
    const pinned: Object = c['pinned'];
    const info: ChatInfo = {
      id: id,
      name: name,
      sessionId: strOf(c, 'session_id').length > 0 ? strOf(c, 'session_id') : strOf(c, 'id'),
      userId: strOf(c, 'user_id'),
      updatedAtMs: isoToMs(strOf(c, 'updated_at')),
      pinned: typeof pinned === 'boolean' ? pinned as boolean : false,
      status: strOf(c, 'status'),
      createdAtMs: isoToMs(strOf(c, 'created_at')),
      groupId: strOf(c, 'group_id')
    };
    out.push(info);
  }
  // 对齐 RN sortChatsByAttention 的 recency 排序：新 → 旧（一期无活跃度优先级；
  // 时间戳未知(0)的会话稳定沉底）
  // 置顶会话排最前（对齐 RN chats.tsx 的 pinned 分组），其余按新→旧
  out.sort((a: ChatInfo, b: ChatInfo): number => {
    if (a.pinned !== b.pinned) {
      return a.pinned ? -1 : 1;
    }
    return b.updatedAtMs - a.updatedAtMs;
  });
  return out;
}

// ============ 会话分组与操作（对齐 PR #7378 client.ts）============
function authOf(token: string): string | null {
  return token.length > 0 ? token : null;
}

function assertOk(resp: http.HttpResponse, what: string): void {
  if (resp.responseCode === 401 || resp.responseCode === 403) {
    throw new ConnectError(tf($r('app.string.err_token_expired'), resp.responseCode));
  }
  if (resp.responseCode < 200 || resp.responseCode >= 300) {
    throw new ConnectError(tf($r('app.string.err_action_failed'), what, resp.responseCode));
  }
}

function groupFrom(rec: Record<string, Object>): ChatGroup {
  const ord: Object = rec['order'];
  return {
    id: strOf(rec, 'id'),
    name: strOf(rec, 'name'),
    kind: strOf(rec, 'kind').length > 0 ? strOf(rec, 'kind') : 'default',
    order: typeof ord === 'number' ? ord as number : 0
  };
}

// 分组列表：GET /chats/groups（返回数组）
export async function fetchChatGroups(baseUrl: string, token: string, agentId: string): Promise<ChatGroup[]> {
  const resp: http.HttpResponse = await doRequest(`${baseUrl}/api/chats/groups`,
    http.RequestMethod.GET, null, authOf(token), agentId);
  if (resp.responseCode !== 200) {
    return [];
  }
  const data: Object = jsonOf(resp);
  if (!Array.isArray(data)) {
    return [];
  }
  const out: ChatGroup[] = [];
  for (const item of data as Object[]) {
    out.push(groupFrom(item as Record<string, Object>));
  }
  out.sort((a: ChatGroup, b: ChatGroup): number => a.order - b.order);
  return out;
}

// 新建分组：POST /chats/groups {name}
export async function createChatGroup(baseUrl: string, token: string, agentId: string,
  name: string): Promise<void> {
  const body: Record<string, string> = { 'name': name };
  assertOk(await doRequest(`${baseUrl}/api/chats/groups`, http.RequestMethod.POST,
    JSON.stringify(body), authOf(token), agentId), t($r('app.string.chat_group_create')));
}

// 重命名分组：PUT /chats/groups/{id} {name}
export async function renameChatGroup(baseUrl: string, token: string, agentId: string,
  groupId: string, name: string): Promise<void> {
  const body: Record<string, string> = { 'name': name };
  assertOk(await doRequest(`${baseUrl}/api/chats/groups/${encodeURIComponent(groupId)}`,
    http.RequestMethod.PUT, JSON.stringify(body), authOf(token), agentId), t($r('app.string.chat_group_rename')));
}

// 删除分组：DELETE /chats/groups/{id}
export async function deleteChatGroup(baseUrl: string, token: string, agentId: string,
  groupId: string): Promise<void> {
  assertOk(await doRequest(`${baseUrl}/api/chats/groups/${encodeURIComponent(groupId)}`,
    http.RequestMethod.DELETE, null, authOf(token), agentId), t($r('app.string.chat_group_delete')));
}

// 新建会话：POST /chats {name, session_id, user_id, channel}（对齐 PR #7378 client.createChat）
// 返回新会话（列表前置展示 + 直接进详情）
export async function createChat(baseUrl: string, token: string, agentId: string,
  name: string): Promise<ChatInfo> {
  const sessionId: string = `mobile:${util.generateRandomUUID()}`;
  const body: Record<string, string> = {
    'name': name,
    'session_id': sessionId,
    'user_id': 'mobile',
    'channel': 'console'
  };
  const resp: http.HttpResponse = await doRequest(`${baseUrl}/api/chats`,
    http.RequestMethod.POST, JSON.stringify(body), authOf(token), agentId);
  assertOk(resp, t($r('app.string.chat_create')));
  const rec: Record<string, Object> = jsonOf(resp);
  const info: ChatInfo = {
    id: strOf(rec, 'id'),
    name: strOf(rec, 'name').length > 0 ? strOf(rec, 'name') : name,
    sessionId: strOf(rec, 'session_id').length > 0 ? strOf(rec, 'session_id') : sessionId,
    // 新建会话归属本应用身份（与请求体的 user_id 一致），带回详情页用于发送/重连定位
    userId: strOf(rec, 'user_id').length > 0 ? strOf(rec, 'user_id') : 'mobile',
    updatedAtMs: isoToMs(strOf(rec, 'updated_at')),
    status: strOf(rec, 'status'),
    createdAtMs: isoToMs(strOf(rec, 'created_at')),
    pinned: false,
    groupId: strOf(rec, 'group_id')
  };
  return info;
}

// 重命名会话：PUT /chats/{id} {name}
export async function renameChat(baseUrl: string, token: string, agentId: string,
  chatId: string, name: string): Promise<void> {
  const body: Record<string, string> = { 'name': name };
  assertOk(await doRequest(`${baseUrl}/api/chats/${encodeURIComponent(chatId)}`,
    http.RequestMethod.PUT, JSON.stringify(body), authOf(token), agentId), t($r('app.string.chat_rename')));
}

// 移动会话到分组：PUT /chats/{id} {group_id}（空 = 移出分组 → null）
export async function moveChatToGroup(baseUrl: string, token: string, agentId: string,
  chatId: string, groupId: string): Promise<void> {
  const payload: Record<string, string | null> = { 'group_id': groupId.length > 0 ? groupId : null };
  assertOk(await doRequest(`${baseUrl}/api/chats/${encodeURIComponent(chatId)}`,
    http.RequestMethod.PUT, JSON.stringify(payload), authOf(token), agentId), t($r('app.string.chat_move')));
}

// 会话置顶：PUT /chats/{id} {pinned}
export async function pinChat(baseUrl: string, token: string, agentId: string,
  chatId: string, pinned: boolean): Promise<void> {
  const body: Record<string, boolean> = { 'pinned': pinned };
  assertOk(await doRequest(`${baseUrl}/api/chats/${encodeURIComponent(chatId)}`,
    http.RequestMethod.PUT, JSON.stringify(body), authOf(token), agentId), t($r('app.string.chat_pin')));
}

// 归档 / 取消归档：POST /chats/{id}/archive | /chats/{id}/unarchive
export async function setChatArchived(baseUrl: string, token: string, agentId: string,
  chatId: string, archived: boolean): Promise<void> {
  const action: string = archived ? 'archive' : 'unarchive';
  assertOk(await doRequest(`${baseUrl}/api/chats/${encodeURIComponent(chatId)}/${action}`,
    http.RequestMethod.POST, null, authOf(token), agentId), archived ? t($r('app.string.chat_archive')) : t($r('app.string.chat_unarchive')));
}

// 删除会话：DELETE /chats/{id}
export async function deleteChat(baseUrl: string, token: string, agentId: string,
  chatId: string): Promise<void> {
  assertOk(await doRequest(`${baseUrl}/api/chats/${encodeURIComponent(chatId)}`,
    http.RequestMethod.DELETE, null, authOf(token), agentId), t($r('app.string.chat_delete')));
}
