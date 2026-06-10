import { useCallback, useEffect, useRef, useState } from "react";
import ReactDOM from "react-dom";
import type {
  IAgentScopeRuntimeWebUIRef,
  IAgentScopeRuntimeWebUIMessage,
} from "@agentscope-ai/chat";
import type { RefObject } from "react";
import { chatApi } from "../../api/modules/chat";
import type { TokenUsageBadgeSnapshot } from "./components/TokenUsageBadge";
import {
  loadTokenBadgeSnapshot,
  migrateTokenBadgeSnapshot,
  resolveTokenBadgeStorageKey,
  saveTokenBadgeSnapshot,
} from "./components/TokenUsageBadge";
import sessionApi from "./sessionApi";
import {
  appendUsageNoteToResponseCard,
  messageHasUsageNote,
  sessionKeyMatches,
} from "./utils";

declare global {
  interface Window {
    currentSessionId?: string;
  }
}

const readNumber = (obj: unknown, key: string): number => {
  if (!obj || typeof obj !== "object") return 0;
  const v = (obj as Record<string, unknown>)[key];
  return typeof v === "number" && Number.isFinite(v) ? v : 0;
};

function toSnapshotFromUsagePayload(
  usage: unknown,
  ctx: unknown,
): TokenUsageBadgeSnapshot | null {
  const usageTotal =
    readNumber(usage, "total_tokens") ||
    readNumber(usage, "prompt_tokens") + readNumber(usage, "completion_tokens");
  const hasUsage = usage && typeof usage === "object" && usageTotal > 0;
  const hasCtx =
    ctx && typeof ctx === "object" && readNumber(ctx, "estimated_tokens") > 0;
  if (!hasUsage && !hasCtx) return null;
  return {
    usage: hasUsage ? (usage as TokenUsageBadgeSnapshot["usage"]) : null,
    context: hasCtx ? (ctx as TokenUsageBadgeSnapshot["context"]) : null,
    receivedAt: Date.now(),
  };
}

function extractUsageSessionId(
  payload: Record<string, unknown>,
  nested: Record<string, unknown> | null,
): string | undefined {
  const meta = (nested ?? payload).metadata;
  if (meta && typeof meta === "object" && !Array.isArray(meta)) {
    const sid = (meta as Record<string, unknown>).session_id;
    if (typeof sid === "string" && sid) return sid;
  }
  for (const key of ["session_id", "sessionId"] as const) {
    const v = nested?.[key] ?? payload[key];
    if (typeof v === "string" && v) return v;
  }
  return undefined;
}

function usageSessionIdsMatch(a: string, b: string): boolean {
  if (!a || !b) return false;
  const entry = (id: string) => ({
    id,
    realId: sessionApi.getRealIdForSession(id) ?? undefined,
    sessionId: id,
  });
  return (
    sessionKeyMatches(entry(a), b) || sessionKeyMatches(entry(b), a)
  );
}

function snapshotValuesUnchanged(
  prev: TokenUsageBadgeSnapshot | null,
  usage: TokenUsageBadgeSnapshot["usage"],
  context: TokenUsageBadgeSnapshot["context"],
): boolean {
  if (!prev) return false;
  return (
    (prev.usage?.total_tokens || 0) === (usage?.total_tokens || 0) &&
    (prev.usage?.prompt_tokens || 0) === (usage?.prompt_tokens || 0) &&
    (prev.usage?.completion_tokens || 0) === (usage?.completion_tokens || 0) &&
    !!prev.usage?.estimated === !!usage?.estimated &&
    prev.context?.estimated_tokens === context?.estimated_tokens &&
    prev.context?.max_input_length === context?.max_input_length &&
    prev.context?.context_usage_ratio === context?.context_usage_ratio
  );
}

function getResponseCardData(
  cards: IAgentScopeRuntimeWebUIMessage["cards"],
): Record<string, unknown> | null {
  const card = (
    cards as Array<{ code?: string; data?: Record<string, unknown> }> | undefined
  )?.find((c) => c?.code === "AgentScopeRuntimeResponseCard");
  return card?.data ?? null;
}

export function useTokenUsageSnapshot({
  chatId,
  chatIdRef,
  chatRef,
  language,
  sessions,
  isChatActive,
}: {
  chatId: string | undefined;
  chatIdRef: RefObject<string | undefined>;
  chatRef: RefObject<IAgentScopeRuntimeWebUIRef | null>;
  language: string;
  sessions: unknown;
  isChatActive: () => boolean;
}) {
  const [tokenSnapshot, setTokenSnapshot] =
    useState<TokenUsageBadgeSnapshot | null>(null);
  const tokenSnapshotRef = useRef<TokenUsageBadgeSnapshot | null>(null);
  tokenSnapshotRef.current = tokenSnapshot;

  const tokenBadgeAliases = useCallback(
    (rawSessionId: string): string[] => {
      const aliases = new Set<string>();
      if (rawSessionId) aliases.add(rawSessionId);
      if (window.currentSessionId) aliases.add(window.currentSessionId);
      if (chatIdRef.current) aliases.add(chatIdRef.current);
      return [...aliases];
    },
    [chatIdRef],
  );

  const readTokenSnapshotForSession = useCallback(
    (rawSessionId: string) => {
      let latest: TokenUsageBadgeSnapshot | null = null;
      for (const id of tokenBadgeAliases(rawSessionId)) {
        const loaded = loadTokenBadgeSnapshot(id);
        if (!loaded) continue;
        if (!latest || (loaded.receivedAt || 0) >= (latest.receivedAt || 0)) {
          latest = loaded;
        }
      }
      return latest;
    },
    [tokenBadgeAliases],
  );

  const saveTokenSnapshotForSession = useCallback(
    (rawSessionId: string, snapshot: TokenUsageBadgeSnapshot) => {
      for (const id of tokenBadgeAliases(rawSessionId)) {
        const key = resolveTokenBadgeStorageKey(id);
        if (key) saveTokenBadgeSnapshot(key, snapshot);
      }
    },
    [tokenBadgeAliases],
  );

  const reloadTokenSnapshot = useCallback(
    (rawSessionId: string) => {
      if (!rawSessionId) {
        setTokenSnapshot(null);
        return;
      }
      const resolvedId =
        sessionApi.getRealIdForSession(rawSessionId) ?? rawSessionId;
      setTokenSnapshot(readTokenSnapshotForSession(resolvedId) ?? null);
    },
    [readTokenSnapshotForSession],
  );

  const applyTokenSnapshotUpdate = useCallback(
    (usage: unknown, ctx: unknown, preferredSessionId?: string) => {
      const base = toSnapshotFromUsagePayload(usage, ctx);
      if (!base) return;
      const eventSessionId =
        preferredSessionId || window.currentSessionId || "";
      const activeSessionId =
        chatIdRef.current || window.currentSessionId || "";
      const isActiveSession =
        !eventSessionId ||
        !activeSessionId ||
        usageSessionIdsMatch(eventSessionId, activeSessionId);
      setTokenSnapshot((prev) => {
        const mergedUsage = base.usage ?? prev?.usage ?? null;
        const mergedContext = base.context ?? prev?.context ?? null;
        if (snapshotValuesUnchanged(prev, mergedUsage, mergedContext)) {
          return prev;
        }
        const next: TokenUsageBadgeSnapshot = {
          usage: mergedUsage,
          context: mergedContext,
          receivedAt: Date.now(),
        };
        if (eventSessionId) saveTokenSnapshotForSession(eventSessionId, next);
        if (!isActiveSession) return prev;
        return next;
      });
    },
    [chatIdRef, saveTokenSnapshotForSession],
  );

  const applyUsageFromStreamChunk = useCallback(
    (chunk: string): Record<string, unknown> => {
      const payload = JSON.parse(chunk) as Record<string, unknown>;
      const nested =
        payload.data &&
        typeof payload.data === "object" &&
        !Array.isArray(payload.data)
          ? (payload.data as Record<string, unknown>)
          : null;
      const meta = (nested ?? payload).metadata;
      const metadataCtxUsage =
        meta && typeof meta === "object" && !Array.isArray(meta)
          ? (meta as Record<string, unknown>).context_usage
          : undefined;
      applyTokenSnapshotUpdate(
        nested?.usage ?? payload.usage,
        metadataCtxUsage ?? nested?.context_usage ?? payload.context_usage,
        extractUsageSessionId(payload, nested),
      );
      return payload;
    },
    [applyTokenSnapshotUpdate],
  );

  const appendStopUsageNoteToChat = useCallback(
    (note: string): boolean => {
      const messagesApi = chatRef.current?.messages;
      if (!messagesApi) return false;

      const lastAssistantMsg = [...(messagesApi.getMessages() ?? [])]
        .reverse()
        .find((m) => m.role === "assistant");
      if (!lastAssistantMsg) return false;
      if (messageHasUsageNote(lastAssistantMsg)) return true;

      const updatedMsg = JSON.parse(
        JSON.stringify(lastAssistantMsg),
      ) as IAgentScopeRuntimeWebUIMessage;
      const data = getResponseCardData(updatedMsg.cards);
      if (!data) return false;
      appendUsageNoteToResponseCard(data, note);
      ReactDOM.flushSync(() => {
        messagesApi.updateMessage(updatedMsg);
      });
      return true;
    },
    [chatRef],
  );

  const scheduleStopUsageNoteAppend = useCallback(
    (note: string, onSuccess?: () => void) => {
      const tryAppend = () => {
        if (!appendStopUsageNoteToChat(note)) return false;
        onSuccess?.();
        return true;
      };
      if (tryAppend()) return;
      let attempt = 0;
      const retry = () => {
        if (tryAppend() || attempt >= 10) return;
        attempt += 1;
        window.setTimeout(retry, 50);
      };
      window.setTimeout(retry, 0);
    },
    [appendStopUsageNoteToChat],
  );

  const handleStopChat = useCallback(
    (sessionId: string) => {
      const resolvedChatId =
        sessionApi.getRealIdForSession(sessionId) ?? sessionId;
      if (!resolvedChatId) return Promise.resolve(null);

      return chatApi
        .stopChat(resolvedChatId, language)
        .then((res) => {
          applyTokenSnapshotUpdate(
            res?.usage,
            res?.context_usage,
            resolvedChatId,
          );

          const note = res?.usage_note;
          if (!note) return res;

          const noteIds =
            sessionId && sessionId !== resolvedChatId
              ? [resolvedChatId, sessionId]
              : [resolvedChatId];
          for (const id of noteIds) sessionApi.setLastStopUsageNote(id, note);

          scheduleStopUsageNoteAppend(note, () => {
            for (const id of noteIds) sessionApi.setLastStopUsageNote(id, null);
          });
          return res;
        })
        .catch((err) => {
          console.error("Failed to stop chat:", err);
          throw err;
        });
    },
    [applyTokenSnapshotUpdate, language, scheduleStopUsageNoteAppend],
  );

  const onRealIdResolved = useCallback(
    (tempId: string, resolvedRealId: string) => {
      migrateTokenBadgeSnapshot(tempId, resolvedRealId);
      const fromStorage = readTokenSnapshotForSession(resolvedRealId);
      if (!fromStorage && tokenSnapshotRef.current) {
        saveTokenSnapshotForSession(resolvedRealId, tokenSnapshotRef.current);
        setTokenSnapshot(tokenSnapshotRef.current);
      } else {
        setTokenSnapshot(fromStorage);
      }
    },
    [readTokenSnapshotForSession, saveTokenSnapshotForSession],
  );

  const clearBadge = useCallback(() => setTokenSnapshot(null), []);

  useEffect(() => {
    if (!isChatActive()) return;
    reloadTokenSnapshot(chatId || "");
  }, [chatId, sessions, isChatActive, reloadTokenSnapshot]);

  return {
    tokenSnapshot,
    applyUsageFromStreamChunk,
    handleStopChat,
    reloadTokenSnapshot,
    onRealIdResolved,
    clearBadge,
  };
}
