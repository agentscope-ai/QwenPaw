import { create } from "zustand";

import { QwenPawClient } from "../api/client";
import { startConnectionAttempt } from "../api/connectionAttempt";
import { isChatGroupsUnsupported } from "../api/compatibility";
import { inferPlatformAccessPath } from "../api/platformGatewayModel";
import { toDisplayMessages, toDisplayParts } from "../api/messages";
import type {
  AgentSummary,
  ApprovalLevel,
  ChatGroup,
  ChatSpec,
  Connection,
  ContentItem,
  DisplayMessage,
  LoopModeInfo,
  ModelSlotOverride,
  PendingApproval,
} from "../api/types";
import { applyLoopModeCommand } from "../features/chat/sessionControlsModel";
import { platformConnectionKeysForLogout } from "../features/platform/authModel";
import {
  type AgentAppearance,
  type AgentAppearanceMap,
  loadAgentAppearances,
  saveAgentAppearance,
} from "../storage/agentAppearance";
import {
  type ChatActivityMap,
  loadChatActivity,
  markActivityRead,
  reconcileChatActivity,
  saveChatActivity,
} from "../storage/chatActivity";
import {
  connectionKey,
  loadConnectionRegistry,
  saveConnectionRegistry,
  upsertConnection,
  withoutConnection,
} from "../storage/connection";
import {
  loadPinnedChatId,
  savePinnedChatId,
} from "../storage/pinnedChat";
import { clearPlatformSession } from "../storage/platformSession";
import { disablePushSubscription } from "../notifications/service";
import { loadNotificationPreferences } from "../notifications/storage";
import {
  clearPendingChatTurn,
  loadPendingChatTurn,
  mergePendingChatTurn,
  pendingUserMessagePersisted,
  savePendingChatTurn,
} from "../storage/pendingChat";

interface AppState {
  status: "booting" | "disconnected" | "connecting" | "ready";
  connection: Connection | null;
  connections: Connection[];
  agents: AgentSummary[];
  chats: ChatSpec[];
  archivedChats: ChatSpec[];
  chatGroups: ChatGroup[];
  supportsChatGroups: boolean;
  chatActivity: ChatActivityMap;
  agentAppearances: AgentAppearanceMap;
  pinnedChatId: string | null;
  pendingApprovals: PendingApproval[];
  messages: Record<string, DisplayMessage[]>;
  activeAbort: AbortController | null;
  activeStreamChatId: string | null;
  error: string | null;
  bootstrap: () => Promise<void>;
  connect: (connection: Connection, signal?: AbortSignal) => Promise<void>;
  disconnect: () => Promise<void>;
  switchConnection: (key: string) => Promise<void>;
  removeConnection: (key: string) => Promise<void>;
  logoutPlatform: () => Promise<void>;
  selectAgent: (agentId: string) => Promise<void>;
  refreshChats: () => Promise<void>;
  refreshArchivedChats: () => Promise<void>;
  createChat: () => Promise<ChatSpec>;
  createChatGroup: (name: string) => Promise<ChatGroup>;
  renameChatGroup: (groupId: string, name: string) => Promise<void>;
  deleteChatGroup: (groupId: string) => Promise<void>;
  moveChatToGroup: (chatId: string, groupId: string | null) => Promise<void>;
  archiveChat: (chatId: string) => Promise<void>;
  unarchiveChat: (chatId: string) => Promise<void>;
  deleteChat: (chatId: string) => Promise<void>;
  setPinnedChat: (chatId: string | null) => Promise<void>;
  loadChat: (
    chatId: string,
    markRead?: boolean,
  ) => Promise<"idle" | "running" | undefined>;
  reconnectChat: (chatId: string) => Promise<void>;
  detachStream: (chatId: string) => void;
  send: (
    chat: ChatSpec,
    text: string,
    attachments?: ContentItem[],
    controls?: {
      approvalLevel?: ApprovalLevel;
      loopMode?: LoopModeInfo;
      modelSlotOverride?: ModelSlotOverride | null;
    },
  ) => Promise<void>;
  stop: (chatId: string) => Promise<void>;
  refreshApprovals: () => Promise<void>;
  approveRequest: (
    approval: PendingApproval,
    scope?: "exact" | "similar",
  ) => Promise<void>;
  denyRequest: (approval: PendingApproval) => Promise<void>;
  setAgentAppearance: (
    agentId: string,
    appearance: AgentAppearance,
  ) => Promise<void>;
  clearError: () => void;
}

let connectGeneration = 0;
const detachedStreams = new WeakSet<AbortController>();

export const useAppStore = create<AppState>((set, get) => ({
  status: "booting",
  connection: null,
  connections: [],
  agents: [],
  chats: [],
  archivedChats: [],
  chatGroups: [],
  supportsChatGroups: false,
  chatActivity: {},
  agentAppearances: {},
  pinnedChatId: null,
  pendingApprovals: [],
  messages: {},
  activeAbort: null,
  activeStreamChatId: null,
  error: null,

  bootstrap: async () => {
    const stored = await Promise.all([
      loadConnectionRegistry(),
      loadPinnedChatId(),
      loadAgentAppearances(),
      loadChatActivity(),
    ]).catch((error) => {
      set({
        status: "disconnected",
        connection: null,
        connections: [],
        error: errorMessage(error),
      });
      return null;
    });
    if (!stored) return;
    const [registry, pinnedChatId, agentAppearances, chatActivity] = stored;
    const connection = registry.connections.find(
      (item) => connectionKey(item) === registry.activeKey,
    ) ?? registry.connections[0] ?? null;
    set({
      connections: registry.connections,
      pinnedChatId,
      agentAppearances,
      chatActivity,
    });
    if (!connection) {
      set({ status: "disconnected" });
      return;
    }
    set({ status: "connecting", connection, error: null });
    try {
      await get().connect(connection);
    } catch (error) {
      set({
        status: "disconnected",
        connection,
        error: errorMessage(error),
      });
    }
  },

  connect: async (connection, signal) => {
    const generation = ++connectGeneration;
    const previous = get();
    set({ status: "connecting", error: null });
    try {
      const workspace = await loadWorkspace(connection, signal);
      if (generation !== connectGeneration) return;
      const registry = upsertConnection({
        activeKey: previous.connection
          ? connectionKey(previous.connection)
          : null,
        connections: previous.connections,
      }, workspace.connection);
      const chatActivity = reconcileChatActivity(
        previous.chatActivity,
        workspace.connection,
        [...workspace.chats, ...workspace.archivedChats],
      );
      const persistence = [saveConnectionRegistry(registry)];
      if (chatActivity !== previous.chatActivity) {
        persistence.push(saveChatActivity(chatActivity));
      }
      await Promise.all(persistence);
      set({
        status: "ready",
        connection: workspace.connection,
        connections: registry.connections,
        agents: workspace.agents,
        chats: workspace.chats,
        archivedChats: workspace.archivedChats,
        chatGroups: workspace.chatGroups,
        supportsChatGroups: workspace.supportsChatGroups,
        chatActivity,
        pendingApprovals: [],
        messages: {},
        error: null,
      });
    } catch (error) {
      if (generation !== connectGeneration) return;
      set({
        status: previous.connection && previous.status === "ready"
          ? "ready"
          : "disconnected",
        connection: previous.connection,
        connections: previous.connections,
        agents: previous.agents,
        chats: previous.chats,
        archivedChats: previous.archivedChats,
        chatGroups: previous.chatGroups,
        supportsChatGroups: previous.supportsChatGroups,
        chatActivity: previous.chatActivity,
        messages: previous.messages,
        error: errorMessage(error),
      });
      throw error;
    }
  },

  disconnect: async () => {
    const connection = get().connection;
    if (connection) await get().removeConnection(connectionKey(connection));
  },

  switchConnection: async (key) => {
    const target = get().connections.find(
      (connection) => connectionKey(connection) === key,
    );
    if (!target || connectionKey(target) === connectionKey(
      requireConnection(get().connection),
    )) return;
    const active = get().activeAbort;
    if (active) {
      detachedStreams.add(active);
      active.abort();
      set({ activeAbort: null, activeStreamChatId: null });
    }
    await get().connect(target);
  },

  removeConnection: async (key) => {
    connectGeneration += 1;
    const state = get();
    const target = state.connections.find(
      (connection) => connectionKey(connection) === key,
    );
    if (!target) return;
    if (state.connection && connectionKey(state.connection) === key) {
      if (state.activeAbort) {
        detachedStreams.add(state.activeAbort);
        state.activeAbort.abort();
        set({ activeAbort: null, activeStreamChatId: null });
      }
    }
    const registry = withoutConnection({
      activeKey: state.connection ? connectionKey(state.connection) : null,
      connections: state.connections,
    }, key);
    const notificationPreferences = await loadNotificationPreferences(target)
      .catch(() => null);
    await saveConnectionRegistry(registry);
    const revokeAttempt = startConnectionAttempt();
    const cleanup = (async () => {
      if (notificationPreferences) {
        await disablePushSubscription(
          target,
          notificationPreferences,
          revokeAttempt.signal,
        ).catch(() => undefined);
      }
      await new QwenPawClient(target, revokeAttempt.signal)
        .revokeToken()
        .catch(() => undefined);
    })().finally(revokeAttempt.dispose);
    const activeRemoved = state.connection &&
      connectionKey(state.connection) === key;
    if (!activeRemoved) {
      set({ connections: registry.connections });
      void cleanup;
      return;
    }
    const next = registry.connections.find(
      (connection) => connectionKey(connection) === registry.activeKey,
    ) ?? registry.connections[0];
    if (next) {
      set({
        status: "disconnected",
        connection: next,
        connections: registry.connections,
        agents: [],
        chats: [],
        archivedChats: [],
        chatGroups: [],
        supportsChatGroups: false,
        pendingApprovals: [],
        messages: {},
        activeAbort: null,
        activeStreamChatId: null,
      });
      void cleanup;
      const attempt = startConnectionAttempt();
      try {
        await get().connect(next, attempt.signal);
      } catch {
        // The removed connection stays removed. The reconnect screen handles
        // an unavailable fallback workspace.
      } finally {
        attempt.dispose();
      }
      return;
    }
    set({
      status: "disconnected",
      connection: null,
      connections: [],
      agents: [],
      chats: [],
      archivedChats: [],
      chatGroups: [],
      supportsChatGroups: false,
      pendingApprovals: [],
      messages: {},
      activeAbort: null,
      activeStreamChatId: null,
    });
    void cleanup;
  },

  logoutPlatform: async () => {
    const state = get();
    const platformKeys = platformConnectionKeysForLogout(
      state.connections,
      state.connection,
    );
    for (const key of platformKeys) {
      await get().removeConnection(key);
    }
    await clearPlatformSession();
  },

  selectAgent: async (agentId) => {
    const current = requireConnection(get().connection);
    const connection = { ...current, agentId };
    const registry = upsertConnection({
      activeKey: connectionKey(current),
      connections: get().connections,
    }, connection);
    await saveConnectionRegistry(registry);
    const client = new QwenPawClient(connection);
    const [chats, archivedChats, chatGroupResult] = await Promise.all([
      client.listChats(),
      client.listChats(true),
      loadChatGroups(client),
    ]);
    const chatActivity = reconcileChatActivity(
      get().chatActivity,
      connection,
      [...chats, ...archivedChats],
    );
    if (chatActivity !== get().chatActivity) {
      await saveChatActivity(chatActivity);
    }
    set({
      connection,
      connections: registry.connections,
      chats,
      archivedChats,
      chatGroups: chatGroupResult.groups,
      supportsChatGroups: chatGroupResult.supported,
      chatActivity,
      pendingApprovals: [],
      messages: {},
    });
  },

  refreshChats: async () => {
    const connection = requireConnection(get().connection);
    const client = new QwenPawClient(connection);
    const chats = await client.listChats();
    const chatActivity = reconcileChatActivity(
      get().chatActivity,
      connection,
      chats,
    );
    if (chatActivity !== get().chatActivity) {
      await saveChatActivity(chatActivity);
    }
    set({ chats, chatActivity });
  },

  refreshArchivedChats: async () => {
    const connection = requireConnection(get().connection);
    const client = new QwenPawClient(connection);
    const archivedChats = await client.listChats(true);
    const chatActivity = reconcileChatActivity(
      get().chatActivity,
      connection,
      archivedChats,
    );
    if (chatActivity !== get().chatActivity) {
      await saveChatActivity(chatActivity);
    }
    set({ archivedChats, chatActivity });
  },

  createChat: async () => {
    const client = new QwenPawClient(requireConnection(get().connection));
    const chat = await client.createChat();
    set((state) => ({ chats: [chat, ...state.chats] }));
    return chat;
  },

  createChatGroup: async (name) => {
    const client = new QwenPawClient(requireConnection(get().connection));
    const group = await client.createChatGroup(name.trim());
    set((state) => ({ chatGroups: [...state.chatGroups, group] }));
    return group;
  },

  renameChatGroup: async (groupId, name) => {
    const client = new QwenPawClient(requireConnection(get().connection));
    const updated = await client.updateChatGroup(groupId, name.trim());
    set((state) => ({
      chatGroups: state.chatGroups.map((group) =>
        group.id === groupId ? updated : group),
    }));
  },

  deleteChatGroup: async (groupId) => {
    const client = new QwenPawClient(requireConnection(get().connection));
    await client.deleteChatGroup(groupId);
    const [chats, chatGroups] = await Promise.all([
      client.listChats(),
      client.listChatGroups(),
    ]);
    set({ chats, chatGroups });
  },

  moveChatToGroup: async (chatId, groupId) => {
    const client = new QwenPawClient(requireConnection(get().connection));
    const updated = await client.updateChat(chatId, { group_id: groupId });
    set((state) => ({
      chats: state.chats.map((chat) => chat.id === chatId ? updated : chat),
    }));
  },

  archiveChat: async (chatId) => {
    const client = new QwenPawClient(requireConnection(get().connection));
    const archived = await client.archiveChat(chatId);
    set((state) => ({
      chats: state.chats.filter((chat) => chat.id !== chatId),
      archivedChats: [archived, ...state.archivedChats],
    }));
    if (get().pinnedChatId === chatId) await get().setPinnedChat(null);
  },

  unarchiveChat: async (chatId) => {
    const client = new QwenPawClient(requireConnection(get().connection));
    const active = await client.unarchiveChat(chatId);
    set((state) => ({
      archivedChats: state.archivedChats.filter((chat) => chat.id !== chatId),
      chats: [active, ...state.chats],
    }));
  },

  deleteChat: async (chatId) => {
    const connection = requireConnection(get().connection);
    const client = new QwenPawClient(connection);
    await client.deleteChat(chatId);
    await clearPendingChatTurn(connection, chatId).catch(() => undefined);
    set((state) => ({
      chats: state.chats.filter((chat) => chat.id !== chatId),
      archivedChats: state.archivedChats.filter((chat) => chat.id !== chatId),
    }));
    if (get().pinnedChatId === chatId) {
      await get().setPinnedChat(null);
    }
  },

  setPinnedChat: async (chatId) => {
    await savePinnedChatId(chatId);
    set({ pinnedChatId: chatId });
  },

  loadChat: async (chatId, markRead = true) => {
    const connection = requireConnection(get().connection);
    const client = new QwenPawClient(connection);
    const history = await client.getChat(chatId);
    const historyMessages = toDisplayMessages(history.messages);
    const pending = await loadPendingChatTurn(connection, chatId);
    const pendingPersisted = pending
      ? pendingUserMessagePersisted(historyMessages, pending)
      : false;
    if (pending && pendingPersisted && history.status !== "running") {
      await clearPendingChatTurn(connection, chatId).catch(() => undefined);
    }
    const displayMessages = pending && (
      !pendingPersisted || history.status === "running"
    )
      ? mergePendingChatTurn(historyMessages, pending)
      : historyMessages;
    const chat = [...get().chats, ...get().archivedChats].find(
      (item) => item.id === chatId,
    );
    const chatActivity = chat && markRead
      ? markActivityRead(
        get().chatActivity,
        connection,
        { ...chat, status: history.status ?? chat.status },
        history.messages.length > 0,
      )
      : get().chatActivity;
    if (chat && markRead && chatActivity !== get().chatActivity) {
      await saveChatActivity(chatActivity);
    }
    set((state) => ({
      chatActivity,
      chats: history.status
        ? state.chats.map((item) => item.id === chatId
          ? { ...item, status: history.status }
          : item)
        : state.chats,
      messages: {
        ...state.messages,
        [chatId]: displayMessages,
      },
    }));
    return history.status;
  },

  send: async (chat, text, attachments = [], controls = {}) => {
    const connection = requireConnection(get().connection);
    const client = new QwenPawClient(connection);
    const controller = new AbortController();
    const userMessage: DisplayMessage = {
      id: createId(),
      role: "user",
      kind: "message",
      parts: toDisplayParts([
        ...(text ? [{ type: "text", text }] : []),
        ...attachments,
      ]),
    };
    const responseId = createId();
    const response: DisplayMessage = {
      id: responseId,
      role: "assistant",
      kind: "message",
      parts: [],
      pending: true,
    };
    const submittedText = controls.loopMode
      ? applyLoopModeCommand(text, controls.loopMode)
      : text;
    await savePendingChatTurn(connection, chat.id, {
      responseId,
      submittedText,
      userMessage,
    }).catch(() => undefined);
    const runningChat = { ...chat, status: "running" as const };
    const chatActivity = reconcileChatActivity(
      get().chatActivity,
      connection,
      [runningChat],
    );
    if (chatActivity !== get().chatActivity) {
      await saveChatActivity(chatActivity);
    }
    set((state) => ({
      activeAbort: controller,
      activeStreamChatId: chat.id,
      chatActivity,
      chats: state.chats.map((item) =>
        item.id === chat.id ? runningChat : item),
      messages: {
        ...state.messages,
        [chat.id]: [
          ...(state.messages[chat.id] ?? []),
          userMessage,
          response,
        ],
      },
    }));
    let activeMessageId = "";
    let displayText = "";
    let frame: number | null = null;
    let failed = false;
    const flushText = () => {
      frame = null;
      const nextText = displayText;
      set((state) => ({
        messages: {
          ...state.messages,
          [chat.id]: (state.messages[chat.id] ?? []).map((message) =>
            message.id === responseId
              ? {
                ...message,
                parts: nextText ? [{ type: "text", text: nextText }] : [],
              }
              : message,
          ),
        },
      }));
    };
    try {
      await client.streamChat({
        sessionId: chat.session_id,
        text: submittedText,
        attachments,
        approvalLevel: controls.approvalLevel,
        modelSlotOverride: controls.modelSlotOverride,
        signal: controller.signal,
        onDelta: (delta) => {
          if (delta.kind !== "message") return;
          if (activeMessageId !== delta.messageId) {
            activeMessageId = delta.messageId;
            displayText = delta.text;
          } else {
            displayText += delta.text;
          }
          if (frame === null) frame = requestAnimationFrame(flushText);
        },
      });
    } catch (error) {
      if (!controller.signal.aborted) {
        failed = true;
        await clearPendingChatTurn(connection, chat.id).catch(() => undefined);
        const message = errorMessage(error);
        set((state) => ({
          error: message,
          messages: {
            ...state.messages,
            [chat.id]: (state.messages[chat.id] ?? []).map((item) =>
              item.id === responseId ? { ...item, error: message } : item),
          },
        }));
      }
    } finally {
      if (frame !== null) cancelAnimationFrame(frame);
      flushText();
      const detached = detachedStreams.has(controller);
      if (detached) {
        set((state) => state.activeAbort === controller
          ? { activeAbort: null, activeStreamChatId: null }
          : state);
        await get().refreshChats().catch(() => undefined);
        return;
      }
      set((state) => ({
        activeAbort: state.activeAbort === controller
          ? null
          : state.activeAbort,
        activeStreamChatId: state.activeAbort === controller
          ? null
          : state.activeStreamChatId,
        messages: {
          ...state.messages,
          [chat.id]: (state.messages[chat.id] ?? []).map((message) =>
            message.id === responseId
              ? { ...message, pending: false }
              : message,
          ),
        },
      }));
      await get().refreshChats().catch(() => undefined);
      if (!failed) {
        await get().loadChat(chat.id, false).catch(() => undefined);
      }
    }
  },

  reconnectChat: async (chatId) => {
    const connection = requireConnection(get().connection);
    const chat = get().chats.find((item) => item.id === chatId);
    if (!chat || chat.status !== "running") return;
    if (get().activeStreamChatId === chatId && get().activeAbort) return;
    const previousController = get().activeAbort;
    if (previousController) {
      detachedStreams.add(previousController);
      previousController.abort();
    }
    const pending = await loadPendingChatTurn(connection, chatId);
    const responseId = pending?.responseId ?? createId();
    const controller = new AbortController();
    set((state) => ({
      activeAbort: controller,
      activeStreamChatId: chatId,
      messages: {
        ...state.messages,
        [chatId]: pending
          ? mergePendingChatTurn(state.messages[chatId] ?? [], pending)
          : ensurePendingResponse(
            state.messages[chatId] ?? [],
            responseId,
          ),
      },
    }));
    let activeMessageId = "";
    let displayText = "";
    let frame: number | null = null;
    let failed = false;
    const flushText = () => {
      frame = null;
      const nextText = displayText;
      set((state) => ({
        messages: {
          ...state.messages,
          [chatId]: (state.messages[chatId] ?? []).map((message) =>
            message.id === responseId
              ? {
                ...message,
                parts: nextText ? [{ type: "text", text: nextText }] : [],
              }
              : message,
          ),
        },
      }));
    };
    try {
      await new QwenPawClient(connection).reconnectChat({
        sessionId: chat.session_id,
        signal: controller.signal,
        onDelta: (delta) => {
          if (delta.kind !== "message") return;
          if (activeMessageId !== delta.messageId) {
            activeMessageId = delta.messageId;
            displayText = delta.text;
          } else {
            displayText += delta.text;
          }
          if (frame === null) frame = requestAnimationFrame(flushText);
        },
      });
    } catch (error) {
      if (!controller.signal.aborted) {
        failed = true;
        const message = errorMessage(error);
        set((state) => ({
          error: message,
          messages: {
            ...state.messages,
            [chatId]: (state.messages[chatId] ?? []).map((item) =>
              item.id === responseId ? { ...item, error: message } : item),
          },
        }));
      }
    } finally {
      if (frame !== null) cancelAnimationFrame(frame);
      flushText();
      const detached = detachedStreams.has(controller);
      if (detached) {
        set((state) => state.activeAbort === controller
          ? { activeAbort: null, activeStreamChatId: null }
          : state);
        await get().refreshChats().catch(() => undefined);
        return;
      }
      set((state) => ({
        activeAbort: state.activeAbort === controller
          ? null
          : state.activeAbort,
        activeStreamChatId: state.activeAbort === controller
          ? null
          : state.activeStreamChatId,
        messages: {
          ...state.messages,
          [chatId]: (state.messages[chatId] ?? []).map((message) =>
            message.id === responseId
              ? { ...message, pending: false }
              : message,
          ),
        },
      }));
      await get().refreshChats().catch(() => undefined);
      if (!failed) {
        await get().loadChat(chatId, false).catch(() => undefined);
      }
    }
  },

  detachStream: (chatId) => {
    const state = get();
    if (state.activeStreamChatId !== chatId || !state.activeAbort) return;
    detachedStreams.add(state.activeAbort);
    state.activeAbort.abort();
    set({ activeAbort: null, activeStreamChatId: null });
  },

  stop: async (chatId) => {
    const state = get();
    if (state.activeStreamChatId === chatId) state.activeAbort?.abort();
    const client = new QwenPawClient(requireConnection(get().connection));
    await client.stopChat(chatId).catch(() => undefined);
    set((current) => current.activeStreamChatId === chatId
      ? { activeAbort: null, activeStreamChatId: null }
      : current);
  },

  refreshApprovals: async () => {
    const client = new QwenPawClient(requireConnection(get().connection));
    const pendingApprovals = await client.listApprovals();
    set({ pendingApprovals });
  },

  approveRequest: async (approval, scope = "exact") => {
    const client = new QwenPawClient(requireConnection(get().connection));
    await client.approve(approval, scope);
    set((state) => ({
      pendingApprovals: state.pendingApprovals.filter(
        (item) => item.request_id !== approval.request_id,
      ),
    }));
  },

  denyRequest: async (approval) => {
    const client = new QwenPawClient(requireConnection(get().connection));
    await client.deny(approval);
    set((state) => ({
      pendingApprovals: state.pendingApprovals.filter(
        (item) => item.request_id !== approval.request_id,
      ),
    }));
  },

  setAgentAppearance: async (agentId, appearance) => {
    const connection = requireConnection(get().connection);
    const agentAppearances = await saveAgentAppearance(
      get().agentAppearances,
      connection,
      agentId,
      appearance,
    );
    set({ agentAppearances });
  },

  clearError: () => set({ error: null }),
}));

function requireConnection(connection: Connection | null): Connection {
  if (!connection) throw new Error("QwenPaw is not connected.");
  return connection;
}

async function loadWorkspace(
  connection: Connection,
  signal?: AbortSignal,
): Promise<{
  connection: Connection;
  agents: AgentSummary[];
  chats: ChatSpec[];
  archivedChats: ChatSpec[];
  chatGroups: ChatGroup[];
  supportsChatGroups: boolean;
}> {
  const compatibleConnection = connection.source === "platform"
    ? {
      ...connection,
      platformAccessPath: connection.platformAccessPath ??
        inferPlatformAccessPath(connection.baseUrl) ?? undefined,
    }
    : connection;
  const client = new QwenPawClient(compatibleConnection, signal);
  await client.verify();
  const agents = await client.listAgents();
  const selected = agents.some(
    (agent) => agent.id === compatibleConnection.agentId,
  )
    ? compatibleConnection.agentId
    : agents[0]?.id ?? "default";
  const resolved = { ...compatibleConnection, agentId: selected };
  const resolvedClient = new QwenPawClient(resolved, signal);
  const [chats, archivedChats, chatGroupResult] = await Promise.all([
    resolvedClient.listChats(),
    resolvedClient.listChats(true),
    loadChatGroups(resolvedClient),
  ]);
  return {
    connection: resolved,
    agents,
    chats,
    archivedChats,
    chatGroups: chatGroupResult.groups,
    supportsChatGroups: chatGroupResult.supported,
  };
}

async function loadChatGroups(client: QwenPawClient): Promise<{
  groups: ChatGroup[];
  supported: boolean;
}> {
  try {
    return { groups: await client.listChatGroups(), supported: true };
  } catch (error) {
    if (isChatGroupsUnsupported(error)) {
      return { groups: [], supported: false };
    }
    throw error;
  }
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Something went wrong.";
}

function ensurePendingResponse(
  messages: DisplayMessage[],
  responseId: string,
): DisplayMessage[] {
  if (messages.some((message) => message.id === responseId)) return messages;
  return [
    ...messages,
    {
      id: responseId,
      role: "assistant",
      kind: "message",
      parts: [],
      pending: true,
    },
  ];
}

function createId(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}
