/*
 * 会话级审批覆盖（本机偏好，按会话落盘）。
 *
 * 口径与两端参照一致：Web console 的运行条把会话级审批存 localStorage（
 * `approval_level-<chatId>`，见 console/src/pages/Chat/components/ApprovalLevelToggle.tsx），
 * RN 版存 AsyncStorage（features/chat/sessionControls + storage）。后端**没有**会话级审批字段
 * （app/chats/manager.py 只有 set_session_model / set_session_thinking / set_session_project_dirs），
 * 审批只在请求上下文里按次生效（hooks/request_setup/contextvars_hook.py 消费
 * request_context.approval_level），所以"只改这一个会话"的正确落点就是**本机按会话记**。
 *
 * 服务端的 Agent 级 approval_level 仍是默认值（没有覆盖时跟随它），见 services/AgentApproval.ets。
 * 键里带 chatId（而不只是 sessionId）：同一 session 在不同连接/智能体下可能指向不同会话。
 */

import { preferences } from '@kit.ArkData';
import { common } from '@kit.AbilityKit';

const STORE_NAME: string = 'qwenpaw.chat.prefs';
const KEY_PREFIX: string = 'qwenpaw.mobile.chat-approval.v1';

function keyOf(connKey: string, agentId: string, chatId: string): string {
  return `${KEY_PREFIX}:${connKey.toLowerCase()}:${agentId}:${chatId}`;
}

/** 读本会话的审批覆盖（'' = 未设置 → 跟随 Agent 的服务端默认值）。 */
export async function loadChatApproval(ctx: common.Context, connKey: string, agentId: string,
  chatId: string): Promise<string> {
  if (chatId.length === 0) {
    return '';
  }
  try {
    const store: preferences.Preferences = await preferences.getPreferences(ctx, STORE_NAME);
    const raw: preferences.ValueType = await store.get(keyOf(connKey, agentId, chatId), '');
    return typeof raw === 'string' ? raw as string : '';
  } catch (e) {
    return '';
  }
}

/** 写本会话的审批覆盖（'' = 清掉覆盖、回到跟随 Agent）。 */
export async function saveChatApproval(ctx: common.Context, connKey: string, agentId: string,
  chatId: string, value: string): Promise<void> {
  if (chatId.length === 0) {
    return;
  }
  try {
    const store: preferences.Preferences = await preferences.getPreferences(ctx, STORE_NAME);
    if (value.length === 0) {
      await store.delete(keyOf(connKey, agentId, chatId));
    } else {
      await store.put(keyOf(connKey, agentId, chatId), value);
    }
    await store.flush();
  } catch (e) {
    // 偏好属辅助信息：写失败只影响下次进入会话时的回显，本次发送仍用内存里的当前值
  }
}
