/*
 * 会话活动态记录（对齐 PR #7378 storage/chatActivityModel.ts）。
 * running 由服务端 chat.status 决定；unread 与 hasWork 由本地记录推导并持久化：
 *   - 之前在跑、现在不跑（completed）→ 标 unread；
 *   - 有工作且在离开期间 updated_at 变新（updatedWhileAway）→ 标 unread；
 *   - 进入会话（markRead）清 unread。
 * 存储用 @ohos.data.preferences（与 ConnectionStore 同口径）。
 */

import { preferences } from '@kit.ArkData';
import { common } from '@kit.AbilityKit';
import { ChatInfo } from './ChatsService';

export interface ChatActivityRecord {
  observedUpdatedAtMs: number;
  hasWork: boolean;
  unread: boolean;
  wasRunning: boolean;
}

// 持久化用带类型的条目数组（ArkTS 禁无类型对象字面量，也不便对 Record 做键遍历）
class ActivityEntry {
  key: string = '';
  observedUpdatedAtMs: number = 0;
  hasWork: boolean = false;
  unread: boolean = false;
  wasRunning: boolean = false;
}

const STORE_NAME: string = 'qwenpaw.chatactivity';
const KEY: string = 'qwenpaw.mobile.chat-activity.v1';

export function activityKey(connKey: string, agentId: string, chatId: string): string {
  return `${connKey}:${agentId}:${chatId}`;
}

export async function loadActivity(ctx: common.Context): Promise<Map<string, ChatActivityRecord>> {
  const out: Map<string, ChatActivityRecord> = new Map<string, ChatActivityRecord>();
  try {
    const store: preferences.Preferences = await preferences.getPreferences(ctx, STORE_NAME);
    const raw: preferences.ValueType = await store.get(KEY, '');
    const text: string = typeof raw === 'string' ? raw as string : '';
    if (text.length === 0) {
      return out;
    }
    const arr: Object = JSON.parse(text) as Object;
    if (!Array.isArray(arr)) {
      return out;
    }
    for (const item of arr as Object[]) {
      const e: ActivityEntry = item as ActivityEntry;
      if (typeof e.key !== 'string' || e.key.length === 0) {
        continue;
      }
      const rec: ChatActivityRecord = {
        observedUpdatedAtMs: typeof e.observedUpdatedAtMs === 'number' ? e.observedUpdatedAtMs : 0,
        hasWork: e.hasWork === true,
        unread: e.unread === true,
        wasRunning: e.wasRunning === true
      };
      out.set(e.key, rec);
    }
  } catch (e) {
    return out;
  }
  return out;
}

export async function saveActivity(ctx: common.Context, map: Map<string, ChatActivityRecord>): Promise<void> {
  const arr: ActivityEntry[] = [];
  map.forEach((rec: ChatActivityRecord, key: string): void => {
    const e: ActivityEntry = new ActivityEntry();
    e.key = key;
    e.observedUpdatedAtMs = rec.observedUpdatedAtMs;
    e.hasWork = rec.hasWork;
    e.unread = rec.unread;
    e.wasRunning = rec.wasRunning;
    arr.push(e);
  });
  try {
    const store: preferences.Preferences = await preferences.getPreferences(ctx, STORE_NAME);
    await store.put(KEY, JSON.stringify(arr));
    await store.flush();
  } catch (e) {
    // 记录属辅助信息，写失败不影响会话列表
  }
}

// 对齐 7378 hasExistingWork：非默认名，或创建到更新超过 2 秒即视为有过工作
function hasExistingWork(chat: ChatInfo): boolean {
  // 与服务端生成的默认名比较，不是展示文案，故不本地化（服务端两种默认名都判）
  const defaultName: boolean = chat.name.length === 0 || chat.name === '新会话' || chat.name === 'New Chat';
  if (!defaultName) {
    return true;
  }
  return chat.createdAtMs > 0 && chat.updatedAtMs - chat.createdAtMs > 2000;
}

function isLater(valueMs: number, baselineMs: number): boolean {
  return valueMs > 0 && baselineMs > 0 && valueMs > baselineMs;
}

/** 对齐 7378 reconcileChatActivity：按服务端列表校正本地记录（返回新 Map）。 */
export function reconcileActivity(current: Map<string, ChatActivityRecord>, connKey: string,
  agentId: string, chats: ChatInfo[]): Map<string, ChatActivityRecord> {
  const next: Map<string, ChatActivityRecord> = new Map<string, ChatActivityRecord>();
  current.forEach((v: ChatActivityRecord, k: string): void => {
    next.set(k, v);
  });
  for (const chat of chats) {
    const key: string = activityKey(connKey, agentId, chat.id);
    const existing: ChatActivityRecord | undefined = next.get(key);
    const running: boolean = chat.status === 'running';
    const observed: number = chat.updatedAtMs;
    let rec: ChatActivityRecord;
    if (existing === undefined) {
      rec = {
        observedUpdatedAtMs: observed,
        hasWork: running || hasExistingWork(chat),
        unread: false,
        wasRunning: running
      };
    } else {
      const completed: boolean = existing.wasRunning && !running;
      const updatedWhileAway: boolean = isLater(observed, existing.observedUpdatedAtMs)
        && existing.hasWork && !running;
      rec = {
        observedUpdatedAtMs: observed > 0 ? observed : existing.observedUpdatedAtMs,
        hasWork: existing.hasWork || running || hasExistingWork(chat),
        unread: existing.unread || completed || updatedWhileAway,
        wasRunning: running
      };
    }
    next.set(key, rec);
  }
  return next;
}

/** 对齐 7378 markActivityRead：进入会话即清 unread，并刷新基准时间。 */
export function markActivityRead(current: Map<string, ChatActivityRecord>, connKey: string,
  agentId: string, chat: ChatInfo, hasMessages: boolean): Map<string, ChatActivityRecord> {
  const next: Map<string, ChatActivityRecord> = new Map<string, ChatActivityRecord>();
  current.forEach((v: ChatActivityRecord, k: string): void => {
    next.set(k, v);
  });
  const key: string = activityKey(connKey, agentId, chat.id);
  const prev: ChatActivityRecord | undefined = next.get(key);
  const rec: ChatActivityRecord = {
    observedUpdatedAtMs: chat.updatedAtMs > 0 ? chat.updatedAtMs
      : (prev !== undefined ? prev.observedUpdatedAtMs : 0),
    hasWork: hasMessages || (prev !== undefined ? prev.hasWork : false) || hasExistingWork(chat),
    unread: false,
    wasRunning: chat.status === 'running'
  };
  next.set(key, rec);
  return next;
}

/** 对齐 7378 resolveChatActivity：'running' | 'unread' | 'read' | 'idle'。 */
export function resolveActivity(connKey: string, agentId: string, chat: ChatInfo,
  map: Map<string, ChatActivityRecord>): string {
  if (chat.status === 'running') {
    return 'running';
  }
  if (connKey.length === 0) {
    return 'idle';
  }
  const rec: ChatActivityRecord | undefined = map.get(activityKey(connKey, agentId, chat.id));
  if (rec !== undefined && rec.unread) {
    return 'unread';
  }
  if ((rec !== undefined && rec.hasWork) || hasExistingWork(chat)) {
    return 'read';
  }
  return 'idle';
}
