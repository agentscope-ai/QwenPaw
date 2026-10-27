/*
 * 在途回合的本地记录（对齐 PR #7378 storage/pendingChat.ts；console 侧等价物是
 * useMessageQueueStore + clientMessageId）。
 * 作用：发送后立刻落本地 —— 切走页面、重挂载、流断线再回来时，自己那条在途消息仍然在，
 * 并与服务端历史对账去重（历史里已有同文本的用户消息且不在跑 → 清掉本地记录）。
 * 存储用 @ohos.data.preferences（与 ConnectionStore / ChatActivity 同口径）。
 */

import { preferences } from '@kit.ArkData';
import { common } from '@kit.AbilityKit';

// 在途回合里已上传附件的引用（重进页面按它还原气泡里的媒体分片，并与历史对账时比对数量）
export interface PendingAttachmentRef {
  kind: string;     // image / video / audio / file（与消息 content 分片的 type 同域）
  url: string;      // 上传接口返回的落盘路径（/api/files/preview 可取）
  fileName: string; // 原始文件名（文件卡标题）
}

export interface PendingTurn {
  turnId: string;   // 本地 live 回合 id（对齐 7378 的 responseId）
  text: string;     // 已提交文本（含循环命令前缀），用于与历史里的用户消息比对（纯附件消息为空串）
  attach: PendingAttachmentRef[];  // 已上传附件（旧记录无此字段 → 空数组）
}

const STORE_NAME: string = 'qwenpaw.pendingturn';
const KEY_PREFIX: string = 'qwenpaw.mobile.pending-chat.v1';

function keyOf(connKey: string, agentId: string, chatId: string): string {
  return `${KEY_PREFIX}:${connKey.toLowerCase()}:${agentId}:${chatId}`;
}

export async function loadPendingTurn(ctx: common.Context, connKey: string, agentId: string,
  chatId: string): Promise<PendingTurn | null> {
  try {
    const store: preferences.Preferences = await preferences.getPreferences(ctx, STORE_NAME);
    const raw: preferences.ValueType = await store.get(keyOf(connKey, agentId, chatId), '');
    const text: string = typeof raw === 'string' ? raw as string : '';
    if (text.length === 0) {
      return null;
    }
    const rec: Record<string, Object> = JSON.parse(text) as Record<string, Object>;
    const turnId: string = typeof rec['turnId'] === 'string' ? rec['turnId'] as string : '';
    const body: string = typeof rec['text'] === 'string' ? rec['text'] as string : '';
    if (turnId.length === 0) {
      return null;
    }
    return { turnId: turnId, text: body, attach: parseAttach(rec['attach']) };
  } catch (e) {
    return null;
  }
}

// 附件引用解析（旧记录无 attach 字段 / 字段损坏 → 空数组，不拦正常回显）
function parseAttach(raw: Object): PendingAttachmentRef[] {
  const out: PendingAttachmentRef[] = [];
  if (!Array.isArray(raw)) {
    return out;
  }
  for (const item of raw as Object[]) {
    const rec: Record<string, Object> = item as Record<string, Object>;
    const kind: string = typeof rec['kind'] === 'string' ? rec['kind'] as string : '';
    const url: string = typeof rec['url'] === 'string' ? rec['url'] as string : '';
    if (kind.length === 0 || url.length === 0) {
      continue;
    }
    const fileName: string = typeof rec['fileName'] === 'string' ? rec['fileName'] as string : '';
    out.push({ kind: kind, url: url, fileName: fileName });
  }
  return out;
}

export async function savePendingTurn(ctx: common.Context, connKey: string, agentId: string,
  chatId: string, rec: PendingTurn): Promise<void> {
  try {
    const store: preferences.Preferences = await preferences.getPreferences(ctx, STORE_NAME);
    const attach: Record<string, string>[] = rec.attach.map((a: PendingAttachmentRef): Record<string, string> => {
      return { 'kind': a.kind, 'url': a.url, 'fileName': a.fileName };
    });
    const body: Record<string, Object> = { 'turnId': rec.turnId, 'text': rec.text, 'attach': attach };
    await store.put(keyOf(connKey, agentId, chatId), JSON.stringify(body));
    await store.flush();
  } catch (e) {
    // 记录属辅助信息，写失败不影响发送
  }
}

export async function clearPendingTurn(ctx: common.Context, connKey: string, agentId: string,
  chatId: string): Promise<void> {
  try {
    const store: preferences.Preferences = await preferences.getPreferences(ctx, STORE_NAME);
    await store.delete(keyOf(connKey, agentId, chatId));
    await store.flush();
  } catch (e) {
    // 清理失败留待下次对账
  }
}
