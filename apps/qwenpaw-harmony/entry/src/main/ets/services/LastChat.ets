/*
 * 最后打开的会话（用户意图记忆）：按「连接 + 智能体」持久化，回到「会话」页时恢复上次打开的会话。
 * 四项缺一不可：chatId 取详情、chatName 回显标题、sessionId 发送/重连定位会话、
 * userId 是该会话自己的归属（写死会让服务端按 (session_id, user_id) 定位到别的 chat、推流为空）。
 * 存储口径与 ConnectionStore / PendingTurn 一致（@ohos.data.preferences）。
 */

import { preferences } from '@kit.ArkData';
import { common } from '@kit.AbilityKit';

export interface LastChat {
  chatId: string;
  chatName: string;
  sessionId: string;
  userId: string;
}

const STORE_NAME: string = 'qwenpaw.lastchat';
const KEY_PREFIX: string = 'qwenpaw.mobile.last-chat.v1';

function keyOf(connKey: string, agentId: string): string {
  return `${KEY_PREFIX}:${connKey.toLowerCase()}:${agentId}`;
}

export async function saveLastChat(ctx: common.Context, connKey: string, agentId: string,
  rec: LastChat): Promise<void> {
  try {
    const store: preferences.Preferences = await preferences.getPreferences(ctx, STORE_NAME);
    const body: Record<string, string> = {
      'chatId': rec.chatId, 'chatName': rec.chatName,
      'sessionId': rec.sessionId, 'userId': rec.userId
    };
    await store.put(keyOf(connKey, agentId), JSON.stringify(body));
    await store.flush();
  } catch (e) {
    // 记忆属辅助信息，写失败不影响打开会话
  }
}

export async function loadLastChat(ctx: common.Context, connKey: string,
  agentId: string): Promise<LastChat | null> {
  try {
    const store: preferences.Preferences = await preferences.getPreferences(ctx, STORE_NAME);
    const raw: preferences.ValueType = await store.get(keyOf(connKey, agentId), '');
    const text: string = typeof raw === 'string' ? raw as string : '';
    if (text.length === 0) {
      return null;
    }
    const rec: Record<string, Object> = JSON.parse(text) as Record<string, Object>;
    const chatId: string = typeof rec['chatId'] === 'string' ? rec['chatId'] as string : '';
    if (chatId.length === 0) {
      return null;
    }
    return {
      chatId: chatId,
      chatName: typeof rec['chatName'] === 'string' ? rec['chatName'] as string : '',
      sessionId: typeof rec['sessionId'] === 'string' ? rec['sessionId'] as string : '',
      userId: typeof rec['userId'] === 'string' ? rec['userId'] as string : ''
    };
  } catch (e) {
    return null;
  }
}

export async function clearLastChat(ctx: common.Context, connKey: string,
  agentId: string): Promise<void> {
  try {
    const store: preferences.Preferences = await preferences.getPreferences(ctx, STORE_NAME);
    await store.delete(keyOf(connKey, agentId));
    await store.flush();
  } catch (e) {
    // 清理失败留待下次覆盖
  }
}
