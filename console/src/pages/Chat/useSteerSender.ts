import { useCallback, useEffect, useRef } from "react";
import { request, ApiError } from "../../api/request";
import { useSteerStore } from "../../stores/steerStore";
import i18n from "../../i18n";
import type { SteerContent, SteerReceipt } from "./steerTimeline";

interface Status {
  scope: string;
  turn_id: string | null;
  can_steer: boolean;
  needs_sync: boolean;
  reason?: string;
  receipts: SteerReceipt[];
}
interface Pending {
  scope: string;
  receipt: SteerReceipt;
}

// Preserve ambiguous submission identity across reloads, separately from Queue.
function pendingInput(
  visit: string,
  value?: Pending | null,
): Pending | undefined {
  const key = `qwenpaw-steer:${visit}`;
  if (value === null) {
    sessionStorage.removeItem(key);
    return;
  }
  if (value) {
    sessionStorage.setItem(key, JSON.stringify(value));
    return value;
  }
  try {
    return JSON.parse(sessionStorage.getItem(key) || "null") || undefined;
  } catch {
    return undefined;
  }
}

export function useSteerSender(
  chatId: string | undefined,
  agentId: string,
  enabled: boolean,
  running = false,
) {
  const visit = `${agentId}:${chatId || ""}`;
  const currentVisit = useRef(visit);
  currentVisit.current = visit;
  const mounted = useRef(true);
  const syncing = useRef(new Map<string, number>());
  const scope = useRef<string>();
  const active = useRef(running);
  active.current = running;
  const wakePoll = useRef(() => {});
  const refresh = useCallback(
    async (turnId?: string): Promise<Status | null> => {
      if (!chatId || !enabled) return null;
      const query = turnId ? `?turn_id=${encodeURIComponent(turnId)}` : "";
      const result = await request<Status>(
        `/chats/${encodeURIComponent(chatId)}/steer${query}`,
        {
          headers: { "X-Agent-Id": agentId },
          signal: AbortSignal.timeout(10000),
        },
      );
      if (currentVisit.current !== visit || !mounted.current) return result;
      for (const receipt of result.receipts) {
        const key = `${result.scope}:${receipt.client_message_id}`;
        if (receipt.status === "applied" && !receipt.message) {
          const attempts = (syncing.current.get(key) || 0) + 1;
          syncing.current.set(key, attempts);
          if (attempts >= 2) receipt.status = "sync_failed";
        } else syncing.current.delete(key);
      }
      scope.current = result.scope;
      if (!useSteerStore.getState().retry[result.scope]) {
        useSteerStore.getState().bindRetry(result.scope, async (targetTurn) => {
          syncing.current.clear();
          const restored = await refresh(targetTurn);
          wakePoll.current();
          return restored;
        });
      }
      useSteerStore.getState().merge(result.scope, result.receipts);
      const pending = pendingInput(visit);
      if (
        pending?.scope === result.scope &&
        !result.receipts.some(
          (r) => r.client_message_id === pending.receipt.client_message_id,
        )
      ) {
        useSteerStore
          .getState()
          .merge(result.scope, [{ ...pending.receipt, status: "unknown" }]);
      }
      return result;
    },
    [chatId, agentId, enabled, visit],
  );
  useEffect(() => {
    mounted.current = true;
    if (!enabled || !chatId) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    let polling = false;
    const poll = async () => {
      if (polling || stopped) return;
      polling = true;
      clearTimeout(timer);
      const unresolvedReceipt = (r: SteerReceipt) =>
        ["accepted", "unknown", "submitting"].includes(r.status) ||
        (r.status === "applied" &&
          !r.message &&
          syncing.current.has(`${scope.current}:${r.client_message_id}`));
      let needsSync = true;
      try {
        const pending = pendingInput(visit);
        const unresolved = (
          useSteerStore.getState().receipts[scope.current || ""] || []
        ).find(unresolvedReceipt);
        const status = await refresh(
          pending?.receipt.turn_id || unresolved?.turn_id,
        );
        if (stopped || currentVisit.current !== visit) return;
        if (
          pending &&
          pendingInput(visit)?.receipt.client_message_id ===
            pending.receipt.client_message_id &&
          status?.receipts.some(
            (r) => r.client_message_id === pending.receipt.client_message_id,
          )
        )
          pendingInput(visit, null);
        const unsettled = (
          useSteerStore.getState().receipts[scope.current || ""] || []
        ).some(unresolvedReceipt);
        needsSync = Boolean(
          status?.needs_sync ||
            active.current ||
            pendingInput(visit) ||
            unsettled,
        );
      } catch {
        // Keep retrying uncertain results without discarding the input identity.
      } finally {
        polling = false;
      }
      if (!stopped && needsSync) wakePoll.current();
    };
    wakePoll.current = () => {
      clearTimeout(timer);
      if (!stopped) timer = setTimeout(poll, 1500);
    };
    const hint = useSteerStore.getState().historySync[visit];
    if (hint) {
      scope.current = hint.scope;
      useSteerStore.getState().bindRetry(hint.scope, async (turnId) => {
        const result = await refresh(turnId);
        if (result?.needs_sync || pendingInput(visit)) wakePoll.current();
        return result;
      });
    }
    if (!hint || hint.needs_sync || active.current || pendingInput(visit))
      void poll();
    const unsubscribe = useSteerStore.subscribe((state, previous) => {
      const hint = state.historySync[visit];
      if (hint && hint !== previous.historySync[visit]) {
        scope.current = hint.scope;
        if (hint.needs_sync) wakePoll.current();
      }
      const receipts = state.receipts[scope.current || ""];
      if (
        receipts !== previous.receipts[scope.current || ""] &&
        receipts?.some((r) =>
          ["accepted", "unknown", "submitting"].includes(r.status),
        )
      )
        wakePoll.current();
    });
    const onFocus = () => void poll();
    window.addEventListener("focus", onFocus);
    return () => {
      stopped = true;
      unsubscribe();
      mounted.current = false;
      clearTimeout(timer);
      window.removeEventListener("focus", onFocus);
      if (scope.current) useSteerStore.getState().bindRetry(scope.current);
    };
  }, [refresh, enabled, chatId, visit]);
  const wasRunning = useRef(running);
  useEffect(() => {
    if (enabled && running !== wasRunning.current) wakePoll.current();
    wasRunning.current = running;
  }, [enabled, running]);

  const submitInput = useCallback(
    async (input: SteerContent) => {
      const content: SteerContent = structuredClone(input);
      if (!enabled) throw new Error(i18n.t("chat.steer.unsupportedBackend"));
      if (!content.length) throw new Error(i18n.t("chat.steer.emptyInput"));
      const status = await refresh();
      if (currentVisit.current !== visit || !mounted.current || !status)
        return false;
      let previous = pendingInput(visit);
      if (previous) {
        const prior =
          previous.receipt.turn_id === status.turn_id
            ? status
            : await refresh(previous.receipt.turn_id);
        if (currentVisit.current !== visit || !mounted.current) return false;
        const known = prior?.receipts.find(
          (r) => r.client_message_id === previous?.receipt.client_message_id,
        );
        if (known) {
          pendingInput(visit, null);
          if (
            JSON.stringify(previous.receipt.content) === JSON.stringify(content)
          ) {
            if (known.status === "failed")
              throw new Error(i18n.t("chat.steer.failed"));
            return true;
          }
          previous = undefined;
        } else if (
          JSON.stringify(previous.receipt.content) !== JSON.stringify(content)
        ) {
          throw new Error(i18n.t("chat.steer.resolvePrevious"));
        }
      }
      if (!previous && (!status.can_steer || !status.turn_id)) {
        throw new Error(
          i18n.t("chat.steer.unavailable", {
            reason: status.reason || i18n.t("chat.steer.statusUnknown"),
          }),
        );
      }
      const receipt: SteerReceipt = previous?.receipt || {
        turn_id: status.turn_id!,
        client_message_id: crypto.randomUUID(),
        user_message_id: "",
        content,
        append_seq: Number.MAX_SAFE_INTEGER,
        revision: 0,
        status: "submitting",
      };
      pendingInput(visit, { scope: status.scope, receipt });
      useSteerStore.getState().merge(status.scope, [receipt]);
      let accepted: SteerReceipt;
      try {
        accepted = await request<SteerReceipt>(
          `/chats/${encodeURIComponent(chatId!)}/steer`,
          {
            method: "POST",
            signal: AbortSignal.timeout(10000),
            headers: { "X-Agent-Id": agentId },
            body: JSON.stringify({
              turn_id: receipt.turn_id,
              client_message_id: receipt.client_message_id,
              content,
            }),
          },
        );
      } catch (error) {
        const rejected =
          error instanceof ApiError &&
          error.status >= 400 &&
          error.status < 500;
        useSteerStore.getState().merge(status.scope, [
          {
            ...receipt,
            status: rejected ? "failed" : "unknown",
            reason: String(error),
          },
        ]);
        if (rejected) pendingInput(visit, null);
        throw error;
      }
      if (currentVisit.current === visit && mounted.current)
        useSteerStore.getState().merge(status.scope, [accepted]);
      pendingInput(visit, null);
      if (accepted.status === "failed")
        throw new Error(i18n.t("chat.steer.failed"));
      return currentVisit.current === visit && mounted.current;
    },
    [chatId, agentId, enabled, refresh, visit],
  );
  const submitting = useRef(false);
  const submit = useCallback(
    async (content: SteerContent) => {
      if (submitting.current) return false;
      submitting.current = true;
      try {
        return await submitInput(content);
      } finally {
        wakePoll.current();
        submitting.current = false;
      }
    },
    [submitInput],
  );
  const hasPending = useCallback(() => Boolean(pendingInput(visit)), [visit]);
  return { submit, refresh, hasPending };
}
