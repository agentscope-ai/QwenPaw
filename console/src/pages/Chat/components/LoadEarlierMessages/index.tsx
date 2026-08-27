import { Button } from "antd";
import React, { useCallback, useSyncExternalStore } from "react";
import { useTranslation } from "react-i18next";
import { useChatAnywhereSessionsState } from "@agentscope-ai/chat";
import type { IAgentScopeRuntimeWebUIRef } from "@agentscope-ai/chat";
import { useAppMessage } from "../../../../hooks/useAppMessage";
import sessionApi from "../../sessionApi";
import {
  EMPTY_HISTORY_PAGE,
  restoreScrollAfterPrepend,
} from "../../sessionApi/historyWindow";
import styles from "./index.module.less";

const REVERSE_MESSAGE_SCROLL_SELECTOR =
  '[class*="chat-anywhere-message-list-bubble-scroll"]' +
  '[class*="bubble-list-order-desc"]';

interface SdkMessagesApi {
  getMessages?: () => unknown[];
  addMessage?: (message: unknown) => void;
  removeAllMessages?: () => void;
  setMessages?: (messages: unknown[]) => void;
}

function applyPrependedMessages(
  messagesApi: SdkMessagesApi | undefined,
  prepended: unknown[],
): void {
  if (!messagesApi || prepended.length === 0) return;
  const current = messagesApi.getMessages?.() ?? [];
  const combined = [...prepended, ...current];
  if (typeof messagesApi.setMessages === "function") {
    messagesApi.setMessages(combined);
    return;
  }
  if (
    typeof messagesApi.removeAllMessages === "function" &&
    typeof messagesApi.addMessage === "function"
  ) {
    messagesApi.removeAllMessages();
    for (const message of combined) {
      messagesApi.addMessage(message);
    }
  }
}

function findHistoryScroller(root: HTMLElement | null): HTMLElement | null {
  if (!root) return null;
  return root.querySelector<HTMLElement>(REVERSE_MESSAGE_SCROLL_SELECTOR);
}

export interface LoadEarlierMessagesProps {
  chatRef: React.RefObject<IAgentScopeRuntimeWebUIRef | null>;
  rootRef: React.RefObject<HTMLDivElement | null>;
}

const LoadEarlierMessages: React.FC<LoadEarlierMessagesProps> = ({
  chatRef,
  rootRef,
}) => {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const { currentSessionId } = useChatAnywhereSessionsState();
  const page = useSyncExternalStore(
    (onStoreChange) => sessionApi.subscribeHistoryPage(onStoreChange),
    () => sessionApi.getHistoryPage(currentSessionId),
    () => EMPTY_HISTORY_PAGE,
  );

  const handleLoad = useCallback(async () => {
    if (!currentSessionId || page.loading || !page.hasMore) return;
    const scroller = findHistoryScroller(rootRef.current);
    const previousScrollTop = scroller?.scrollTop ?? 0;
    const previousScrollHeight = scroller?.scrollHeight ?? 0;
    try {
      const { prepended } = await sessionApi.loadEarlierMessages(
        currentSessionId,
      );
      applyPrependedMessages(
        chatRef.current?.messages as SdkMessagesApi | undefined,
        prepended,
      );
      if (scroller) {
        scroller.scrollTop = restoreScrollAfterPrepend(
          scroller,
          previousScrollTop,
          previousScrollHeight,
        );
      }
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") return;
      message.error(t("chat.loadEarlierFailed"));
    }
  }, [
    chatRef,
    currentSessionId,
    message,
    page.hasMore,
    page.loading,
    rootRef,
    t,
  ]);

  if (!page.hasMore) return null;

  return (
    <div className={styles.bar}>
      <Button
        data-testid="load-earlier-messages"
        size="small"
        loading={page.loading}
        onClick={() => {
          void handleLoad();
        }}
      >
        {t("chat.loadEarlierMessages")}
      </Button>
    </div>
  );
};

export { applyPrependedMessages, findHistoryScroller };
export default LoadEarlierMessages;
