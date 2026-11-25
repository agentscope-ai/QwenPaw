/*
 * 通知偏好（本地）—— 对齐 7378 app/notifications.tsx 的偏好模型 + contracts 的 NotificationPreferences。
 * 存储：@ohos.data.preferences，键 qwenpaw.mobile.push.preferences.v1:<connKey>:<agentId>
 *   （按 连接 + 智能体 隔离；connectionKey = baseUrl 小写，与 ConnectionStore 同源）。
 * 无存储记录时 enabled 置 false、其余取默认（7378 同款）。
 * 说明：真推送通道（Push Kit / AGC 配置）属宿主侧范畴，本模块只负责偏好读写。
 */

import { preferences } from '@kit.ArkData';
import { common } from '@kit.AbilityKit';
import { QpConnection, connectionKey } from './ConnectionStore';

const STORE_NAME: string = 'qwenpaw.notification.prefs';
const KEY_PREFIX: string = 'qwenpaw.mobile.push.preferences.v1';

export const PREVIEW_FULL: string = 'full';
export const PREVIEW_TITLE_ONLY: string = 'title_only';
export const PREVIEW_HIDDEN: string = 'hidden';

export interface NotificationPrefs {
  enabled: boolean;
  runCompleted: boolean;
  inputRequired: boolean;
  approvalRequired: boolean;
  runFailed: boolean;
  preview: string;
}

export function defaultPrefs(): NotificationPrefs {
  // 与 contracts DEFAULT_NOTIFICATION_PREFERENCES 一致（各开关 true、预览仅标题）
  return {
    enabled: true,
    runCompleted: true,
    inputRequired: true,
    approvalRequired: true,
    runFailed: true,
    preview: PREVIEW_TITLE_ONLY
  };
}

function prefsKey(conn: QpConnection): string {
  const agent: string = conn.agentId.length > 0 ? conn.agentId : 'default';
  return `${KEY_PREFIX}:${connectionKey(conn)}:${agent}`;
}

function parsePrefs(raw: string): NotificationPrefs {
  const out: NotificationPrefs = defaultPrefs();
  try {
    const rec: Record<string, Object> = JSON.parse(raw) as Record<string, Object>;
    out.enabled = rec['enabled'] === true;
    out.runCompleted = rec['runCompleted'] === true;
    out.inputRequired = rec['inputRequired'] === true;
    out.approvalRequired = rec['approvalRequired'] === true;
    out.runFailed = rec['runFailed'] === true;
    const p: Object = rec['preview'];
    out.preview = typeof p === 'string' ? p as string : PREVIEW_TITLE_ONLY;
  } catch (e) {
    return out;
  }
  return out;
}

// 读取：无记录 → enabled=false（其余默认），与 7378 loadNotificationPreferences 同款
export async function loadNotificationPrefs(context: common.Context,
  conn: QpConnection): Promise<NotificationPrefs> {
  try {
    const store: preferences.Preferences = await preferences.getPreferences(context, STORE_NAME);
    const raw: preferences.ValueType = await store.get(prefsKey(conn), '');
    if (typeof raw === 'string' && raw.length > 0) {
      return parsePrefs(raw as string);
    }
  } catch (e) {
    // 读取失败按未开启处理，不打断页面
  }
  const fresh: NotificationPrefs = defaultPrefs();
  fresh.enabled = false;
  return fresh;
}

export async function saveNotificationPrefs(context: common.Context, conn: QpConnection,
  prefs: NotificationPrefs): Promise<void> {
  const store: preferences.Preferences = await preferences.getPreferences(context, STORE_NAME);
  const rec: Record<string, Object> = {};
  rec['enabled'] = prefs.enabled;
  rec['runCompleted'] = prefs.runCompleted;
  rec['inputRequired'] = prefs.inputRequired;
  rec['approvalRequired'] = prefs.approvalRequired;
  rec['runFailed'] = prefs.runFailed;
  rec['preview'] = prefs.preview;
  await store.put(prefsKey(conn), JSON.stringify(rec));
  await store.flush();
}
