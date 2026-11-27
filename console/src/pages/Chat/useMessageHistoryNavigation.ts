import { useEffect, useRef, type RefObject } from "react";
import type { IAgentScopeRuntimeWebUIRef } from "@agentscope-ai/chat";
import sessionApi from "./sessionApi";
import { InputMessageRecall } from "./inputMessageRecall";
import { getInputHistoryTexts } from "./inputMessageHistory";
import { historyMessageWindow } from "./historyMessageWindowStore";
import { getSenderTextareaFromTarget, setTextareaValue } from "./utils";

export function useMessageHistoryNavigation(
  chatRef: RefObject<IAgentScopeRuntimeWebUIRef | null>,
  isChatActive: () => boolean,
  composing: RefObject<boolean>,
  sessionId: string | undefined,
) {
  const state = useRef<{
    recall?: InputMessageRecall;
    draft: string;
    busy: boolean;
    abort: AbortController;
  }>({ draft: "", busy: false, abort: new AbortController() });
  useEffect(() => {
    const reset = () => {
      state.current.abort.abort();
      state.current = { draft: "", busy: false, abort: new AbortController() };
    };
    reset();
    const focus = (event: FocusEvent) => {
      if (getSenderTextareaFromTarget(event.target)) reset();
    };
    const keydown = (event: KeyboardEvent) => {
      if (!isChatActive() || !["ArrowUp", "ArrowDown"].includes(event.key))
        return;
      const input = getSenderTextareaFromTarget(event.target);
      if (
        !input ||
        composing.current ||
        event.isComposing ||
        event.ctrlKey ||
        event.metaKey ||
        event.altKey ||
        event.shiftKey
      )
        return;
      if (
        input.selectionStart !== input.selectionEnd ||
        input.value.startsWith("/")
      )
        return;
      const older = event.key === "ArrowUp";
      const position = input.selectionStart ?? 0;
      if (
        older
          ? input.value.slice(0, position).includes("\n")
          : input.value.slice(position).includes("\n")
      )
        return;
      const current = state.current;
      if (!older && !current.recall) return;
      // History may require an async read. Keep native caret movement when
      // no matching text is found; a successful recall replaces the input.
      if (current.busy) return;
      if (!current.recall) {
        current.draft = input.value;
        const messages = chatRef.current?.messages?.getMessages?.() ?? [];
        const fallback = getInputHistoryTexts(
          messages,
          historyMessageWindow.getSnapshot(),
        );
        current.recall = new InputMessageRecall(
          (before) =>
            sessionId
              ? sessionApi.loadUserMessageIndexPage(
                  sessionId,
                  before,
                  current.abort.signal,
                )
              : Promise.resolve({ items: [] }),
          (id) =>
            sessionApi.loadUserMessageText(
              sessionId!,
              id,
              current.abort.signal,
            ),
          fallback,
        );
      }
      current.busy = true;
      const before = input.value;
      void current.recall
        .move(older)
        .then((text) => {
          if (
            current !== state.current ||
            current.abort.signal.aborted ||
            input.value !== before ||
            !input.isConnected
          )
            return;
          if (text !== undefined)
            setTextareaValue(input, text === null ? current.draft : text);
        })
        .catch(() => {
          // Leave the draft intact; another key press can retry the read.
        })
        .finally(() => {
          current.busy = false;
        });
    };
    document.addEventListener("keydown", keydown, true);
    document.addEventListener("focusin", focus, true);
    return () => {
      reset();
      document.removeEventListener("keydown", keydown, true);
      document.removeEventListener("focusin", focus, true);
    };
  }, [sessionId, chatRef, isChatActive, composing]);
}
