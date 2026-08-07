import { create } from "zustand";
import type {
  AgentStatusBarView,
  CreatorConversation,
  CreatorEvent,
  CreatorMessage,
  CreatorSessionView,
  SendCreatorMessageRequest,
} from "@/contracts/creator";
import {
  createConversation,
  getCreatorSession,
  interruptCreator,
  listConversations,
  listMessages,
  newClientId,
  openCreatorEvents,
  sendCreatorMessage,
  type CreatorEventStream,
} from "@/api/creator";
import {
  isTechnicalControlText,
  isUserAuthorityMessage,
} from "@/lib/creatorMessagePresentation";
import i18n from "@/i18n";

const conversationRetryIds = new Map<string, string>();

async function createStableConversation(projectId: string) {
  const requestId =
    conversationRetryIds.get(projectId) ?? newClientId("conversation");
  conversationRetryIds.set(projectId, requestId);
  const created = await createConversation(projectId, requestId);
  conversationRetryIds.delete(projectId);
  return created;
}

interface QueuedUiMessage {
  clientMessageId: string;
  requestSignature: string;
  text: string;
  state: "sending" | "queued" | "failed";
  error?: string;
}

export interface StreamingAssistantMessage {
  messageId: string;
  runId?: string;
  firstEventSeq: number;
  deltas: Record<number, string>;
  thinkingDeltas: Record<number, string>;
  toolCall?: {
    id: string;
    name: string;
    arguments?: Record<string, unknown>;
    receivedBytes?: number;
    providerChunkCount?: number;
    argumentStreamComplete?: boolean;
  };
  createdAt: string;
}

export interface SubagentStreamMessage {
  messageId: string;
  runId: string;
  role: string;
  firstEventSeq: number;
  deltas: Record<number, string>;
  thinkingDeltas: Record<number, string>;
  completedText?: string;
  completedThinking?: string;
  completed: boolean;
  finishReason?: string;
}

export interface SubagentStreamTool {
  toolCallId: string;
  runId: string;
  tool: string;
  firstEventSeq: number;
  status: "started" | "succeeded" | "failed";
  arguments?: Record<string, unknown>;
  receivedBytes?: number;
  providerChunkCount?: number;
  argumentStreamComplete?: boolean;
  result?: unknown;
  state?: string;
  taskId?: string;
  outputEvents: Array<{
    seq: number;
    type: string;
    data: Record<string, unknown>;
  }>;
}

export interface SubagentActivity {
  parentActionId: string;
  runId: string;
  role: string;
  roleDisplayName?: string;
  delegationText?: string;
  targetRefs: string[];
  firstEventSeq: number;
  completed: boolean;
  waitingReview?: boolean;
  terminalKind?: "SUCCESS" | "BLOCKED" | "FAILED" | "STALE" | "CANCELLED";
  summaryText?: string;
  terminalEventSeq?: number;
  messages: Record<string, SubagentStreamMessage>;
  tools: Record<string, SubagentStreamTool>;
}

interface CreatorSessionState {
  projectId: string | null;
  session: CreatorSessionView | null;
  agentStatusBar: AgentStatusBarView | null;
  conversations: CreatorConversation[];
  activeConversationId: string | null;
  messages: CreatorMessage[];
  streamingAssistantMessages: Record<string, StreamingAssistantMessage>;
  subagentActivities: Record<string, SubagentActivity>;
  events: CreatorEvent[];
  lastEventSeq: number;
  queuedUi: QueuedUiMessage[];
  hasMoreMessages: boolean;
  loading: boolean;
  loadingOlder: boolean;
  connected: boolean;
  stopping: boolean;
  isReplaying: boolean;
  error: string | null;
  stream: CreatorEventStream | null;
  bootstrap: (projectId: string) => Promise<void>;
  setConversation: (conversationId: string) => Promise<void>;
  newConversation: () => Promise<string>;
  loadOlderMessages: () => Promise<void>;
  refreshSession: () => Promise<void>;
  refreshMessages: (after?: number) => Promise<void>;
  sendMessage: (
    request: Omit<
      SendCreatorMessageRequest,
      "clientMessageId" | "conversationId"
    > & {
      message?: string;
      clientMessageId?: string;
    },
  ) => Promise<void>;
  stopAllAgents: () => Promise<void>;
  ingestEvents: (events: CreatorEvent[]) => void;
  ingestEvent: (event: CreatorEvent) => void;
  disconnect: () => void;
  reset: () => void;
}

function mergeMessages(
  current: CreatorMessage[],
  incoming: CreatorMessage[],
): CreatorMessage[] {
  const bySeq = new Map(current.map((item) => [item.messageSeq, item]));
  incoming.forEach((item) => bySeq.set(item.messageSeq, item));
  return [...bySeq.values()].sort((a, b) => a.messageSeq - b.messageSeq);
}

function withoutDurableStreamingMessages(
  current: Record<string, StreamingAssistantMessage>,
  durable: CreatorMessage[],
): Record<string, StreamingAssistantMessage> {
  let next = current;
  durable.forEach((message) => {
    if (!next[message.messageId]) return;
    if (next === current) next = { ...current };
    delete next[message.messageId];
  });
  return next;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function eventString(
  data: Record<string, unknown>,
  key: string,
): string | undefined {
  const value = data[key];
  return typeof value === "string" && value ? value : undefined;
}

function eventStringArray(
  data: Record<string, unknown>,
  key: string,
): string[] | undefined {
  const value = data[key];
  if (!Array.isArray(value)) return undefined;
  return value.filter(
    (item): item is string => typeof item === "string" && Boolean(item),
  );
}

function subagentActivityBase(
  existing: SubagentActivity | undefined,
  parentActionId: string,
  event: CreatorEvent,
): SubagentActivity {
  // Parent delegate_to_agent lifecycle events carry the Creator Agent runId.
  // Only subagent events are authoritative for the SpecialistRun identity;
  // otherwise the trailing agent.tool_completed event looks like a new run
  // and clears the terminal state that subagent.completed/blocked/failed just
  // projected into AgentDock.
  const eventRunId = event.type.startsWith("subagent.")
    ? eventString(event.data, "runId")
    : undefined;
  const runChanged = Boolean(
    eventRunId && existing?.runId && eventRunId !== existing.runId,
  );
  return {
    parentActionId,
    runId: eventRunId ?? existing?.runId ?? "",
    role: eventString(event.data, "role") ?? existing?.role ?? "",
    roleDisplayName:
      eventString(event.data, "roleDisplayName") ??
      eventString(event.data, "displayName") ??
      existing?.roleDisplayName,
    delegationText:
      eventString(event.data, "delegationText") ??
      eventString(event.data, "task") ??
      existing?.delegationText,
    targetRefs:
      eventStringArray(event.data, "targetRefs") ?? existing?.targetRefs ?? [],
    firstEventSeq: runChanged
      ? event.seq
      : existing?.firstEventSeq ?? event.seq,
    completed: runChanged ? false : existing?.completed ?? false,
    waitingReview: runChanged ? undefined : existing?.waitingReview,
    terminalKind: runChanged ? undefined : existing?.terminalKind,
    summaryText: runChanged ? undefined : existing?.summaryText,
    terminalEventSeq: runChanged ? undefined : existing?.terminalEventSeq,
    messages: runChanged ? {} : existing?.messages ?? {},
    tools: runChanged ? {} : existing?.tools ?? {},
  };
}

function subagentToolStatus(state: unknown): SubagentStreamTool["status"] {
  const normalized = typeof state === "string" ? state.toLowerCase() : "";
  return normalized.includes("fail") ||
    normalized.includes("error") ||
    normalized.includes("cancel")
    ? "failed"
    : "succeeded";
}

const SUBAGENT_LIFECYCLE_EVENTS = new Set([
  "subagent.accepted",
  "subagent.started",
  "subagent.waiting_runtime",
  "subagent.resumed",
  "subagent.continuation_started",
  "subagent.continuation_completed",
  "subagent.completed",
  "subagent.blocked",
  "subagent.failed",
  "subagent.stale",
]);

const ACTIVE_SUBAGENT_LIFECYCLE_EVENTS = new Set([
  "subagent.accepted",
  "subagent.started",
  "subagent.waiting_runtime",
  "subagent.resumed",
  "subagent.continuation_started",
]);

function subagentTerminalKind(
  event: CreatorEvent,
): SubagentActivity["terminalKind"] | undefined {
  const marker = eventString(event.data, "marker");
  if (marker === "SUCCESS" || marker === "BLOCKED" || marker === "FAILED")
    return marker;
  if (event.type === "subagent.completed") return "SUCCESS";
  if (event.type === "subagent.blocked") return "BLOCKED";
  if (event.type === "subagent.stale") return "STALE";
  if (event.type === "subagent.failed") {
    return event.data.cancelled === true ? "CANCELLED" : "FAILED";
  }
  return undefined;
}

function subagentSummary(event: CreatorEvent): string | undefined {
  for (const key of [
    "summaryText",
    "summary",
    "reason",
    "cancelReason",
    "staleReason",
  ]) {
    const value = eventString(event.data, key);
    if (value && !isTechnicalControlText(value)) return value;
  }
  return undefined;
}

function isLegacyReviewPause(
  terminalKind: SubagentActivity["terminalKind"],
  summary: string | undefined,
): boolean {
  // Runs created before Runtime emitted waitingReview used a plain BLOCKED
  // event. Keep those durable histories neutral while all new events rely on
  // the structured flag.
  return (
    terminalKind === "BLOCKED" &&
    Boolean(summary && /等待(?:用户)?审阅|审阅通过后/u.test(summary))
  );
}

function settleSubagentMessages(
  activity: SubagentActivity,
  runId: string,
  finishReason: string,
  exceptMessageId?: string,
): SubagentActivity {
  let changed = false;
  const messages = Object.fromEntries(
    Object.entries(activity.messages).map(([key, message]) => {
      if (
        message.runId !== runId ||
        message.messageId === exceptMessageId ||
        message.completed
      )
        return [key, message];
      changed = true;
      return [key, { ...message, completed: true, finishReason }];
    }),
  );
  return changed ? { ...activity, messages } : activity;
}

function defaultState() {
  return {
    projectId: null,
    session: null,
    agentStatusBar: null,
    conversations: [] as CreatorConversation[],
    activeConversationId: null,
    messages: [] as CreatorMessage[],
    streamingAssistantMessages: {} as Record<string, StreamingAssistantMessage>,
    subagentActivities: {} as Record<string, SubagentActivity>,
    events: [] as CreatorEvent[],
    lastEventSeq: 0,
    queuedUi: [] as QueuedUiMessage[],
    hasMoreMessages: false,
    loading: false,
    loadingOlder: false,
    connected: false,
    stopping: false,
    isReplaying: false,
    error: null,
    stream: null as CreatorEventStream | null,
  };
}

export const useCreatorSessionStore = create<CreatorSessionState>(
  (set, get) => {
    let lifecycleGeneration = 0;
    let sessionRefreshGeneration = 0;
    let messageRefreshEpoch = 0;
    let pendingMessageRefresh: { epoch: number; after: number } | null = null;
    let messageRefreshRunner: { epoch: number; promise: Promise<void> } | null =
      null;
    const messageRefreshRetryWaiters = new Set<{
      timer: number;
      resolve: (current: boolean) => void;
    }>();

    const invalidateMessageRefresh = () => {
      messageRefreshEpoch += 1;
      pendingMessageRefresh = null;
      messageRefreshRetryWaiters.forEach((waiter) => {
        window.clearTimeout(waiter.timer);
        waiter.resolve(false);
      });
      messageRefreshRetryWaiters.clear();
    };

    const sessionResponsePatch = (
      projectId: string,
      response: Awaited<ReturnType<typeof getCreatorSession>>,
      generation: number,
      current: CreatorSessionState,
    ): Partial<CreatorSessionState> => {
      if (
        generation !== sessionRefreshGeneration ||
        current.projectId !== projectId ||
        response.session.projectId !== projectId
      )
        return {};

      // SSE is authoritative between revalidations. A response queried before a
      // later durable event must not roll Session/progress projection back.
      const currentEventSeq = Math.max(
        current.lastEventSeq,
        current.session?.lastEventSeq ?? 0,
      );
      if (response.session.lastEventSeq < currentEventSeq) return {};
      const patch: Partial<CreatorSessionState> = { session: response.session };
      const currentProgressSeq =
        current.agentStatusBar?.progress.sourceEventSeq ?? -1;
      if (
        response.agentStatusBar.progress.sourceEventSeq >= currentProgressSeq
      ) {
        patch.agentStatusBar = response.agentStatusBar;
      }
      return patch;
    };

    const waitForMessageRefreshRetry = (delay: number, epoch: number) =>
      new Promise<boolean>((resolve) => {
        const waiter = {
          timer: 0,
          resolve,
        };
        waiter.timer = window.setTimeout(() => {
          messageRefreshRetryWaiters.delete(waiter);
          resolve(epoch === messageRefreshEpoch);
        }, delay);
        messageRefreshRetryWaiters.add(waiter);
      });

    const pullMessages = async (
      after?: number,
      expectedEpoch = messageRefreshEpoch,
    ) => {
      const initial = get();
      const projectId = initial.projectId;
      const conversationId = initial.activeConversationId;
      if (!projectId || !conversationId) return;
      let cursor = Math.max(
        0,
        after ?? initial.messages.at(-1)?.messageSeq ?? 0,
      );
      while (expectedEpoch === messageRefreshEpoch) {
        const page = await listMessages(projectId, conversationId, cursor, 500);
        const current = get();
        if (
          expectedEpoch !== messageRefreshEpoch ||
          current.projectId !== projectId ||
          current.activeConversationId !== conversationId
        )
          return;
        set((state) => {
          if (
            state.projectId !== projectId ||
            state.activeConversationId !== conversationId
          )
            return {};
          const existingMessageSeqs = new Set(
            state.messages.map((item) => item.messageSeq),
          );
          const appendedUserCount = page.items.filter(
            (item) =>
              !existingMessageSeqs.has(item.messageSeq) &&
              isUserAuthorityMessage(item),
          ).length;
          const removable = new Set(
            state.queuedUi
              .filter((item) => item.state !== "failed")
              .slice(0, appendedUserCount)
              .map((item) => item.clientMessageId),
          );
          const messages = mergeMessages(state.messages, page.items);
          return {
            messages,
            streamingAssistantMessages: withoutDurableStreamingMessages(
              state.streamingAssistantMessages,
              messages,
            ),
            queuedUi: state.queuedUi.filter(
              (item) => !removable.has(item.clientMessageId),
            ),
          };
        });
        if (page.nextAfter == null || page.nextAfter <= cursor) return;
        cursor = page.nextAfter;
      }
    };

    const scheduleMessageRefresh = (after: number) => {
      const epoch = messageRefreshEpoch;
      if (pendingMessageRefresh?.epoch === epoch) {
        pendingMessageRefresh.after = Math.min(
          pendingMessageRefresh.after,
          after,
        );
      } else {
        pendingMessageRefresh = { epoch, after };
      }
      if (messageRefreshRunner?.epoch === epoch) return;

      const runner: { epoch: number; promise: Promise<void> } = {
        epoch,
        promise: Promise.resolve(),
      };
      const drain = async () => {
        while (pendingMessageRefresh?.epoch === epoch) {
          const cursor = pendingMessageRefresh.after;
          pendingMessageRefresh = null;
          const retryDelays = [50, 150, 500];
          for (let attempt = 0; attempt <= retryDelays.length; attempt += 1) {
            try {
              await pullMessages(cursor, epoch);
              break;
            } catch {
              if (
                attempt === retryDelays.length ||
                epoch !== messageRefreshEpoch
              )
                break;
              const current = await waitForMessageRefreshRetry(
                retryDelays[attempt],
                epoch,
              );
              if (!current) break;
            }
          }
        }
      };
      runner.promise = drain().finally(() => {
        if (messageRefreshRunner === runner) messageRefreshRunner = null;
        if (pendingMessageRefresh?.epoch === messageRefreshEpoch) {
          scheduleMessageRefresh(pendingMessageRefresh.after);
        }
      });
      messageRefreshRunner = runner;
    };

    return {
      ...defaultState(),

      bootstrap: async (projectId) => {
        const bootstrapGeneration = ++lifecycleGeneration;
        const sessionGeneration = ++sessionRefreshGeneration;
        const state = get();
        const sameProject = state.projectId === projectId;
        const initialResumeAfter = sameProject ? state.lastEventSeq : 0;
        const preferredConversationId = sameProject
          ? state.activeConversationId
          : null;
        state.stream?.close();
        invalidateMessageRefresh();
        if (sameProject) {
          set({
            stream: null,
            connected: false,
            loading: true,
            isReplaying: true,
            error: null,
          });
        } else {
          set({
            ...defaultState(),
            projectId,
            loading: true,
            isReplaying: true,
          });
        }
        try {
          const [sessionResponse, conversationPage] = await Promise.all([
            getCreatorSession(projectId),
            listConversations(projectId),
          ]);
          if (
            bootstrapGeneration !== lifecycleGeneration ||
            get().projectId !== projectId
          )
            return;
          // Sessions in a terminal state skip SSE replay.
          const TERMINAL_STATUSES = new Set(["IDLE", "CANCELLED", "ERROR"]);
          const resumeAfter = TERMINAL_STATUSES.has(
            sessionResponse.session.status,
          )
            ? sessionResponse.session.lastEventSeq
            : initialResumeAfter;
          console.log(
            "[bootstrap] session status:",
            sessionResponse.session.status,
          );
          console.log(
            "[bootstrap] lastEventSeq:",
            sessionResponse.session.lastEventSeq,
          );
          console.log("[bootstrap] initialResumeAfter:", initialResumeAfter);
          console.log("[bootstrap] final resumeAfter:", resumeAfter);
          let conversations = conversationPage.items;
          let activeConversationId =
            preferredConversationId &&
            conversations.some(
              (item) => item.conversationId === preferredConversationId,
            )
              ? preferredConversationId
              : conversations[0]?.conversationId ?? null;
          if (!activeConversationId) {
            const created = await createStableConversation(projectId);
            if (
              bootstrapGeneration !== lifecycleGeneration ||
              get().projectId !== projectId
            )
              return;
            activeConversationId = created.conversationId;
            conversations = [
              {
                conversationId: created.conversationId,
                title: created.title,
                isDefault: false,
                createdAt: created.createdAt,
              },
            ];
          }
          const page = await listMessages(
            projectId,
            activeConversationId,
            0,
            50,
          );
          if (
            bootstrapGeneration !== lifecycleGeneration ||
            get().projectId !== projectId
          )
            return;
          set((current) => {
            if (
              bootstrapGeneration !== lifecycleGeneration ||
              current.projectId !== projectId
            )
              return {};
            const messages =
              sameProject && activeConversationId === preferredConversationId
                ? mergeMessages(current.messages, page.items)
                : page.items;
            return {
              ...sessionResponsePatch(
                projectId,
                sessionResponse,
                sessionGeneration,
                current,
              ),
              conversations,
              activeConversationId,
              messages,
              streamingAssistantMessages: withoutDurableStreamingMessages(
                current.streamingAssistantMessages,
                messages,
              ),
              hasMoreMessages: page.nextAfter != null,
              lastEventSeq: resumeAfter,
              loading: false,
              stopping: false,
            };
          });
          const pendingEvents: CreatorEvent[] = [];
          let flushTimer: number | null = null;
          const flushEvents = () => {
            flushTimer = null;
            if (pendingEvents.length === 0) return;
            const batch = pendingEvents.splice(0, pendingEvents.length);
            get().ingestEvents(batch);
          };
          const durableStream = openCreatorEvents(
            projectId,
            resumeAfter,
            (event) => {
              pendingEvents.push(event);
              // Initial SSE replay can carry hundreds of durable events. Fold
              // one animation frame into one Zustand commit so refresh does not
              // remount the active Timeline page once per historical event.
              if (flushTimer == null)
                flushTimer = window.setTimeout(flushEvents, 16);
            },
            () => set({ connected: false }),
          );
          // With no events to replay, defer setting isReplaying: false.
          if (resumeAfter >= (sessionResponse.session.lastEventSeq ?? 0)) {
            window.setTimeout(() => {
              if (
                bootstrapGeneration === lifecycleGeneration &&
                get().projectId === projectId
              ) {
                set({ isReplaying: false });
              }
            }, 100);
          }
          const stream: CreatorEventStream = {
            close: () => {
              durableStream.close();
              if (flushTimer != null) window.clearTimeout(flushTimer);
              flushTimer = null;
              pendingEvents.splice(0, pendingEvents.length);
            },
          };
          if (
            bootstrapGeneration !== lifecycleGeneration ||
            get().projectId !== projectId
          ) {
            stream.close();
            return;
          }
          set({ stream, connected: true });
        } catch (error) {
          if (
            bootstrapGeneration === lifecycleGeneration &&
            get().projectId === projectId
          )
            set({ loading: false, error: (error as Error).message });
          throw error;
        }
      },

      setConversation: async (conversationId) => {
        const {
          projectId,
          activeConversationId,
          messages,
          streamingAssistantMessages,
          hasMoreMessages,
        } = get();
        if (!projectId || conversationId === activeConversationId) return;
        invalidateMessageRefresh();
        set({
          activeConversationId: conversationId,
          messages: [],
          streamingAssistantMessages: {},
          hasMoreMessages: false,
          loadingOlder: true,
        });
        try {
          const page = await listMessages(projectId, conversationId, 0, 50);
          set((current) => {
            if (
              current.projectId !== projectId ||
              current.activeConversationId !== conversationId
            )
              return {};
            return {
              messages: page.items,
              hasMoreMessages: page.nextAfter != null,
              loadingOlder: false,
            };
          });
        } catch (error) {
          set((current) => {
            if (
              current.projectId !== projectId ||
              current.activeConversationId !== conversationId
            )
              return {};
            return {
              activeConversationId,
              messages,
              streamingAssistantMessages,
              hasMoreMessages,
              loadingOlder: false,
            };
          });
          throw error;
        }
      },

      newConversation: async () => {
        const { projectId, activeConversationId } = get();
        if (!projectId) throw new Error(i18n.t("store.sessionNotInit"));
        const created = await createStableConversation(projectId);
        if (
          get().projectId !== projectId ||
          get().activeConversationId !== activeConversationId
        )
          return created.conversationId;
        invalidateMessageRefresh();
        const conversation: CreatorConversation = {
          conversationId: created.conversationId,
          title: created.title,
          isDefault: false,
          createdAt: created.createdAt,
        };
        set((state) => {
          if (
            state.projectId !== projectId ||
            state.activeConversationId !== activeConversationId
          )
            return {};
          return {
            conversations: [conversation, ...state.conversations],
            activeConversationId: conversation.conversationId,
            messages: [],
            streamingAssistantMessages: {},
            hasMoreMessages: false,
          };
        });
        return conversation.conversationId;
      },

      loadOlderMessages: async () => {
        const { projectId, activeConversationId, messages, loadingOlder } =
          get();
        if (!projectId || !activeConversationId || loadingOlder) return;
        const latest = messages.at(-1)?.messageSeq ?? 0;
        set({ loadingOlder: true });
        try {
          const page = await listMessages(
            projectId,
            activeConversationId,
            latest,
            50,
          );
          set((state) => {
            if (
              state.projectId !== projectId ||
              state.activeConversationId !== activeConversationId
            )
              return {};
            const messages = mergeMessages(state.messages, page.items);
            return {
              messages,
              streamingAssistantMessages: withoutDurableStreamingMessages(
                state.streamingAssistantMessages,
                messages,
              ),
              hasMoreMessages: page.nextAfter != null,
              loadingOlder: false,
            };
          });
        } catch (error) {
          set((state) =>
            state.projectId === projectId &&
            state.activeConversationId === activeConversationId
              ? { loadingOlder: false }
              : {},
          );
        }
      },

      refreshSession: async () => {
        const { projectId } = get();
        if (!projectId) return;
        const generation = ++sessionRefreshGeneration;
        const response = await getCreatorSession(projectId);
        set((current) =>
          sessionResponsePatch(projectId, response, generation, current),
        );
      },

      refreshMessages: async (after) => {
        await pullMessages(after);
      },

      sendMessage: async (input) => {
        const { projectId, session, activeConversationId } = get();
        if (!projectId || !session || !activeConversationId)
          throw new Error(i18n.t("store.sessionNotInit"));
        const text =
          input.message ??
          input.content?.find((part) => part.type === "text")?.text ??
          "";
        const requestSignature = JSON.stringify({
          message: input.message,
          content: input.content,
          assetVersionRefs: input.assetVersionRefs,
          context: input.context,
          conversationId: activeConversationId,
        });
        const failedRetry = get().queuedUi.find(
          (item) =>
            item.state === "failed" &&
            item.requestSignature === requestSignature,
        );
        const clientMessageId =
          input.clientMessageId ??
          failedRetry?.clientMessageId ??
          newClientId("message");
        set((state) => {
          if (
            state.projectId !== projectId ||
            state.activeConversationId !== activeConversationId
          )
            return {};
          return {
            queuedUi: [
              ...state.queuedUi.filter(
                (item) => item.clientMessageId !== clientMessageId,
              ),
              { clientMessageId, requestSignature, text, state: "sending" },
            ],
          };
        });
        try {
          const accepted = await sendCreatorMessage(projectId, {
            ...input,
            clientMessageId,
            creatorSessionId: session.id,
            conversationId: activeConversationId,
          });
          if (
            get().projectId !== projectId ||
            get().activeConversationId !== activeConversationId
          )
            return;
          set((state) => {
            if (
              state.projectId !== projectId ||
              state.activeConversationId !== activeConversationId
            )
              return {};
            return {
              queuedUi: state.queuedUi.map((item) =>
                item.clientMessageId === clientMessageId
                  ? { ...item, state: "queued" }
                  : item,
              ),
            };
          });
          if (accepted.appendState === "appended") {
            const page = await listMessages(
              projectId,
              activeConversationId,
              Math.max(0, accepted.messageSeq - 1),
              1,
            );
            set((state) => {
              if (
                state.projectId !== projectId ||
                state.activeConversationId !== activeConversationId
              )
                return {};
              return {
                messages: mergeMessages(state.messages, page.items),
                queuedUi: state.queuedUi.filter(
                  (item) => item.clientMessageId !== clientMessageId,
                ),
              };
            });
          }
        } catch (error) {
          set((state) => {
            if (
              state.projectId !== projectId ||
              state.activeConversationId !== activeConversationId
            )
              return {};
            return {
              queuedUi: state.queuedUi.map((item) =>
                item.clientMessageId === clientMessageId
                  ? {
                      ...item,
                      state: "failed",
                      error: (error as Error).message,
                    }
                  : item,
              ),
            };
          });
          throw error;
        }
      },

      stopAllAgents: async () => {
        const { session, stopping } = get();
        const projectId = get().projectId ?? session?.projectId ?? null;
        if (!projectId || stopping) return;
        const sessionId = session?.id;
        const previousStatus = session?.status;
        set((state) => ({
          stopping: true,
          session: state.session
            ? { ...state.session, status: "INTERRUPT_REQUESTED" }
            : state.session,
        }));
        try {
          await interruptCreator(projectId);
        } catch (error) {
          set((state) => ({
            stopping: false,
            session:
              sessionId &&
              state.session?.id === sessionId &&
              state.session.status === "INTERRUPT_REQUESTED"
                ? { ...state.session, status: previousStatus! }
                : state.session,
          }));
          throw error;
        }
        set({ stopping: false });
      },

      ingestEvents: (incoming) => {
        let messageRefreshAfter: number | null = null;
        set((current) => {
          const bySeq = new Map<number, CreatorEvent>();
          incoming.forEach((event) => {
            if (
              event.projectId === current.projectId &&
              event.seq > current.lastEventSeq
            ) {
              bySeq.set(event.seq, event);
            }
          });
          const accepted = [...bySeq.values()].sort(
            (left, right) => left.seq - right.seq,
          );
          if (accepted.length === 0) return {};
          let messages = current.messages;
          let streamingAssistantMessages = current.streamingAssistantMessages;
          let subagentActivities = current.subagentActivities;
          let queuedUi = current.queuedUi;
          let session = current.session;
          accepted.forEach((event) => {
            const actionId = eventString(event.data, "actionId");
            const subagentDetail =
              event.type === "subagent.message_delta" ||
              event.type === "subagent.message_completed" ||
              event.type === "subagent.tool_progress" ||
              event.type === "subagent.tool_started" ||
              event.type === "subagent.tool_completed";
            const subagentLifecycle = SUBAGENT_LIFECYCLE_EVENTS.has(event.type);
            const delegateBoundary =
              (event.type === "agent.tool_started" ||
                event.type === "agent.tool_completed") &&
              Boolean(
                actionId &&
                  (event.data.tool === "delegate_to_agent" ||
                    subagentActivities[actionId]),
              );
            const parentActionId =
              subagentDetail || subagentLifecycle
                ? eventString(event.data, "parentActionId")
                : delegateBoundary
                ? actionId
                : undefined;
            if (
              parentActionId &&
              (subagentDetail || subagentLifecycle || delegateBoundary)
            ) {
              const existingActivity = subagentActivities[parentActionId];
              let activity = subagentActivityBase(
                existingActivity,
                parentActionId,
                event,
              );
              if (ACTIVE_SUBAGENT_LIFECYCLE_EVENTS.has(event.type)) {
                activity = {
                  ...activity,
                  completed: false,
                  waitingReview: undefined,
                  terminalKind: undefined,
                  summaryText: undefined,
                  terminalEventSeq: undefined,
                };
              }
              const terminalKind = subagentTerminalKind(event);
              if (terminalKind) {
                const summary = subagentSummary(event) ?? activity.summaryText;
                activity = settleSubagentMessages(
                  activity,
                  activity.runId,
                  `terminal:${terminalKind.toLowerCase()}`,
                );
                activity = {
                  ...activity,
                  completed: true,
                  waitingReview:
                    event.data.waitingReview === true ||
                    isLegacyReviewPause(terminalKind, summary),
                  terminalKind,
                  summaryText: summary,
                  terminalEventSeq: event.seq,
                };
              }
              if (
                delegateBoundary &&
                event.type === "agent.tool_completed" &&
                event.data.failed === true
              ) {
                activity = settleSubagentMessages(
                  activity,
                  activity.runId,
                  "terminal:failed",
                );
                activity = {
                  ...activity,
                  completed: true,
                  terminalKind: "FAILED",
                  summaryText:
                    eventString(event.data, "error") ??
                    eventString(event.data, "errorType") ??
                    activity.summaryText,
                  terminalEventSeq: event.seq,
                };
              }

              if (
                event.type === "subagent.message_delta" ||
                event.type === "subagent.message_completed"
              ) {
                const messageId = eventString(event.data, "messageId");
                const runId =
                  eventString(event.data, "runId") ?? activity.runId;
                if (messageId && runId) {
                  const messageKey = `${runId}:${messageId}`;
                  const existingMessage = activity.messages[messageKey];
                  if (
                    event.type === "subagent.message_delta" &&
                    !existingMessage
                  ) {
                    activity = settleSubagentMessages(
                      activity,
                      runId,
                      "superseded_after_recovery",
                      messageId,
                    );
                  }
                  let nextMessage: SubagentStreamMessage = existingMessage ?? {
                    messageId,
                    runId,
                    role: eventString(event.data, "role") ?? activity.role,
                    firstEventSeq: event.seq,
                    deltas: {},
                    thinkingDeltas: {},
                    completed: false,
                  };
                  if (event.type === "subagent.message_delta") {
                    const deltaIndex = Number(event.data.deltaIndex);
                    const delta = event.data.delta;
                    const streamKind =
                      eventString(event.data, "streamKind") ?? "text";
                    if (
                      Number.isInteger(deltaIndex) &&
                      deltaIndex >= 0 &&
                      typeof delta === "string" &&
                      !(
                        deltaIndex in
                        (streamKind === "thinking"
                          ? nextMessage.thinkingDeltas
                          : nextMessage.deltas)
                      )
                    ) {
                      nextMessage = {
                        ...nextMessage,
                        ...(streamKind === "thinking"
                          ? {
                              thinkingDeltas: {
                                ...nextMessage.thinkingDeltas,
                                [deltaIndex]: delta,
                              },
                            }
                          : {
                              deltas: {
                                ...nextMessage.deltas,
                                [deltaIndex]: delta,
                              },
                            }),
                      };
                    }
                  } else {
                    nextMessage = {
                      ...nextMessage,
                      completedText:
                        typeof event.data.text === "string"
                          ? event.data.text
                          : nextMessage.completedText,
                      completedThinking:
                        typeof event.data.thinking === "string"
                          ? event.data.thinking
                          : nextMessage.completedThinking,
                      completed: true,
                      finishReason:
                        eventString(event.data, "finishReason") ??
                        nextMessage.finishReason,
                    };
                  }
                  if (nextMessage !== existingMessage) {
                    activity = {
                      ...activity,
                      messages: {
                        ...activity.messages,
                        [messageKey]: nextMessage,
                      },
                    };
                  }
                }
              }

              if (
                event.type === "subagent.tool_progress" ||
                event.type === "subagent.tool_started" ||
                event.type === "subagent.tool_completed"
              ) {
                const toolCallId = eventString(event.data, "toolCallId");
                const runId =
                  eventString(event.data, "runId") ?? activity.runId;
                if (toolCallId && runId) {
                  const toolKey = `${runId}:${toolCallId}`;
                  const existingTool = activity.tools[toolKey];
                  const parsedArguments = isRecord(event.data.arguments)
                    ? event.data.arguments
                    : existingTool?.arguments;
                  const nextTool: SubagentStreamTool = {
                    toolCallId,
                    runId,
                    tool:
                      eventString(event.data, "tool") ??
                      existingTool?.tool ??
                      "tool",
                    firstEventSeq: existingTool?.firstEventSeq ?? event.seq,
                    status:
                      event.type !== "subagent.tool_completed"
                        ? "started"
                        : subagentToolStatus(event.data.state),
                    arguments: parsedArguments,
                    receivedBytes:
                      typeof event.data.receivedBytes === "number"
                        ? event.data.receivedBytes
                        : existingTool?.receivedBytes,
                    providerChunkCount:
                      typeof event.data.providerChunkCount === "number"
                        ? event.data.providerChunkCount
                        : existingTool?.providerChunkCount,
                    argumentStreamComplete:
                      typeof event.data.complete === "boolean"
                        ? event.data.complete
                        : existingTool?.argumentStreamComplete,
                    result:
                      event.type === "subagent.tool_completed"
                        ? event.data.result
                        : existingTool?.result,
                    state:
                      eventString(event.data, "state") ?? existingTool?.state,
                    taskId:
                      eventString(event.data, "taskId") ?? existingTool?.taskId,
                    outputEvents: existingTool?.outputEvents ?? [],
                  };
                  activity = {
                    ...activity,
                    tools: { ...activity.tools, [toolKey]: nextTool },
                  };
                }
              }

              subagentActivities = {
                ...subagentActivities,
                [parentActionId]: activity,
              };
            }
            const clearsStreamingAssistant =
              event.type === "assistant.output_rejected" ||
              event.type === "session.error" ||
              (event.type === "session.status_changed" &&
                event.data.recoveredIncompleteAssistant === true);
            if (clearsStreamingAssistant) {
              const assistantMessageId =
                typeof event.data.assistantMessageId === "string"
                  ? event.data.assistantMessageId
                  : typeof event.data.messageId === "string"
                  ? event.data.messageId
                  : undefined;
              if (
                assistantMessageId &&
                streamingAssistantMessages[assistantMessageId]
              ) {
                streamingAssistantMessages = { ...streamingAssistantMessages };
                delete streamingAssistantMessages[assistantMessageId];
              }
            }
            if (
              event.type === "agent.run.failed" ||
              event.type === "agent.run.cancelled"
            ) {
              const terminalRunId = eventString(event.data, "runId");
              if (terminalRunId) {
                const remaining = Object.fromEntries(
                  Object.entries(streamingAssistantMessages).filter(
                    ([, message]) => message.runId !== terminalRunId,
                  ),
                );
                if (
                  Object.keys(remaining).length !==
                  Object.keys(streamingAssistantMessages).length
                ) {
                  streamingAssistantMessages = remaining;
                }
              }
              if (event.type === "agent.run.failed" && session) {
                const errorPayload = event.data.error as
                  | { code?: string; message?: string; retryable?: boolean }
                  | undefined;
                if (errorPayload?.message) {
                  session = {
                    ...session,
                    error: errorPayload as {
                      code: string;
                      message: string;
                      retryable: boolean;
                    },
                  };
                }
              }
            }
            if (event.type === "agent.message_delta") {
              const messageId =
                typeof event.data.messageId === "string"
                  ? event.data.messageId
                  : undefined;
              const deltaIndex = Number(event.data.deltaIndex);
              const delta = event.data.delta;
              const streamKind =
                eventString(event.data, "streamKind") ?? "text";
              const alreadyDurable = messageId
                ? messages.some((message) => message.messageId === messageId)
                : false;
              if (
                messageId &&
                Number.isInteger(deltaIndex) &&
                deltaIndex >= 0 &&
                typeof delta === "string" &&
                !alreadyDurable
              ) {
                const existing = streamingAssistantMessages[messageId];
                const target =
                  streamKind === "thinking"
                    ? existing?.thinkingDeltas
                    : existing?.deltas;
                if (!existing || !(deltaIndex in (target ?? {}))) {
                  streamingAssistantMessages = {
                    ...streamingAssistantMessages,
                    [messageId]: {
                      messageId,
                      runId:
                        eventString(event.data, "runId") ?? existing?.runId,
                      firstEventSeq: existing?.firstEventSeq ?? event.seq,
                      deltas:
                        streamKind === "thinking"
                          ? existing?.deltas ?? {}
                          : {
                              ...(existing?.deltas ?? {}),
                              [deltaIndex]: delta,
                            },
                      thinkingDeltas:
                        streamKind === "thinking"
                          ? {
                              ...(existing?.thinkingDeltas ?? {}),
                              [deltaIndex]: delta,
                            }
                          : existing?.thinkingDeltas ?? {},
                      toolCall: existing?.toolCall,
                      createdAt: existing?.createdAt ?? event.at,
                    },
                  };
                }
              }
            }
            if (event.type === "agent.tool_progress") {
              const messageId = eventString(event.data, "messageId");
              const toolCallId = eventString(event.data, "toolCallId");
              const toolName = eventString(event.data, "tool");
              const alreadyDurable = messageId
                ? messages.some((message) => message.messageId === messageId)
                : false;
              if (messageId && toolCallId && toolName && !alreadyDurable) {
                const existing = streamingAssistantMessages[messageId];
                const currentTool = existing?.toolCall;
                streamingAssistantMessages = {
                  ...streamingAssistantMessages,
                  [messageId]: {
                    messageId,
                    runId: eventString(event.data, "runId") ?? existing?.runId,
                    firstEventSeq: existing?.firstEventSeq ?? event.seq,
                    deltas: existing?.deltas ?? {},
                    thinkingDeltas: existing?.thinkingDeltas ?? {},
                    toolCall: {
                      id: toolCallId,
                      name: toolName,
                      arguments:
                        currentTool?.id === toolCallId
                          ? currentTool.arguments
                          : undefined,
                      receivedBytes:
                        typeof event.data.receivedBytes === "number"
                          ? event.data.receivedBytes
                          : currentTool?.receivedBytes,
                      providerChunkCount:
                        typeof event.data.providerChunkCount === "number"
                          ? event.data.providerChunkCount
                          : currentTool?.providerChunkCount,
                      argumentStreamComplete:
                        typeof event.data.complete === "boolean"
                          ? event.data.complete
                          : currentTool?.argumentStreamComplete,
                    },
                    createdAt: existing?.createdAt ?? event.at,
                  },
                };
              }
            }
            if (event.type.startsWith("task.")) {
              const runId = eventString(event.data, "specialistRunId");
              if (runId) {
                const activityEntry = Object.entries(subagentActivities).find(
                  ([, activity]) => activity.runId === runId,
                );
                if (activityEntry) {
                  const [activityKey, currentActivity] = activityEntry;
                  const taskId = eventString(event.data, "taskId");
                  const candidates = Object.entries(currentActivity.tools)
                    .filter(
                      ([, tool]) =>
                        tool.status === "started" &&
                        (!tool.taskId || tool.taskId === taskId),
                    )
                    .sort(
                      ([, left], [, right]) =>
                        right.firstEventSeq - left.firstEventSeq,
                    );
                  const candidate = candidates[0];
                  if (candidate) {
                    const [toolKey, tool] = candidate;
                    const updatedTool: SubagentStreamTool = {
                      ...tool,
                      taskId: taskId ?? tool.taskId,
                      outputEvents: [
                        ...tool.outputEvents,
                        { seq: event.seq, type: event.type, data: event.data },
                      ],
                    };
                    subagentActivities = {
                      ...subagentActivities,
                      [activityKey]: {
                        ...currentActivity,
                        tools: {
                          ...currentActivity.tools,
                          [toolKey]: updatedTool,
                        },
                      },
                    };
                  }
                }
              }
            }
            const persistsConversationMessage =
              !event.type.endsWith("message_delta") &&
              !event.type.startsWith("subagent.") &&
              !clearsStreamingAssistant &&
              (event.type === "message.appended" ||
                event.type === "message.completed" ||
                event.type === "agent.tool_completed" ||
                event.type === "runtime.work_update_appended" ||
                typeof event.data.messageId === "string" ||
                typeof event.data.messageSeq === "number");
            if (persistsConversationMessage) {
              const message = event.data.message as CreatorMessage | undefined;
              if (message) {
                messages = mergeMessages(messages, [message]);
                streamingAssistantMessages = withoutDurableStreamingMessages(
                  streamingAssistantMessages,
                  [message],
                );
              }
              const clientMessageId = event.data.clientMessageId as
                | string
                | undefined;
              if (clientMessageId)
                queuedUi = queuedUi.filter(
                  (item) => item.clientMessageId !== clientMessageId,
                );
              const rawMessageSeq = event.data.messageSeq ?? event.data.seq;
              const cursor =
                typeof rawMessageSeq === "number"
                  ? Math.max(0, rawMessageSeq - 1)
                  : messages.at(-1)?.messageSeq ?? 0;
              messageRefreshAfter =
                messageRefreshAfter == null
                  ? cursor
                  : Math.min(messageRefreshAfter, cursor);
            }
            if (
              event.type === "session.status_changed" ||
              event.type === "creator.woken"
            ) {
              const status =
                event.type === "creator.woken"
                  ? "RUNNING"
                  : ((event.data.status ?? event.data.to) as
                      | CreatorSessionView["status"]
                      | undefined);
              if (status && session) {
                session = { ...session, status, lastEventSeq: event.seq };
                if (
                  status === "IDLE" ||
                  status === "CANCELLED" ||
                  status === "ERROR"
                ) {
                  Object.entries(subagentActivities).forEach(
                    ([key, activity]) => {
                      if (activity.completed) return;
                      subagentActivities = {
                        ...subagentActivities,
                        [key]: {
                          ...activity,
                          completed: true,
                          terminalKind: "CANCELLED" as const,
                          summaryText:
                            activity.summaryText ?? i18n.t("store.userAbort"),
                          terminalEventSeq: event.seq,
                        },
                      };
                    },
                  );
                }
              }
            }
          });
          const lastEventSeq = accepted.at(-1)!.seq;
          if (session && session.lastEventSeq !== lastEventSeq)
            session = { ...session, lastEventSeq };
          const events = [...current.events, ...accepted].slice(-500);
          const patch: Partial<CreatorSessionState> = {
            events,
            lastEventSeq,
            connected: true,
          };
          if (current.isReplaying) patch.isReplaying = false;
          if (messages !== current.messages) patch.messages = messages;
          if (
            streamingAssistantMessages !== current.streamingAssistantMessages
          ) {
            patch.streamingAssistantMessages = streamingAssistantMessages;
          }
          if (subagentActivities !== current.subagentActivities) {
            patch.subagentActivities = subagentActivities;
          }
          if (queuedUi !== current.queuedUi) patch.queuedUi = queuedUi;
          if (session !== current.session) patch.session = session;
          return patch;
        });
        if (messageRefreshAfter != null)
          scheduleMessageRefresh(messageRefreshAfter);
      },

      ingestEvent: (event) => get().ingestEvents([event]),

      disconnect: () => {
        lifecycleGeneration += 1;
        sessionRefreshGeneration += 1;
        get().stream?.close();
        invalidateMessageRefresh();
        set({ stream: null, connected: false });
      },

      reset: () => {
        lifecycleGeneration += 1;
        sessionRefreshGeneration += 1;
        get().stream?.close();
        invalidateMessageRefresh();
        set(defaultState());
      },
    };
  },
);
