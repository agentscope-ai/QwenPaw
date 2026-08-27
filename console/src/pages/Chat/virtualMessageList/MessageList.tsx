/**
 * Host replacement for the vendor Chat MessageList.
 *
 * `@agentscope-ai/chat` always mounts every item Bubble.List is given (its
 * PAGE_SIZE=10 "pagination" still accumulates into a full DOM once the user
 * scrolls). This file is swapped in via the Vite alias in vite.config.ts so
 * the visible Chat page virtualizes the transcript: only the viewport plus
 * overscan is mounted, with measured variable heights.
 */
import { Bubble, useProviderContext } from "@agentscope-ai/chat";
import { ChatAnywhereMessagesContext } from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/Context/ChatAnywhereMessagesContext";
import { ChatAnywhereSessionsContext } from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/Context/ChatAnywhereSessionsContext";
import { useChatAnywhereOptions } from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/Context/ChatAnywhereOptionsContext";
import Welcome from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/Chat/Welcome";
import UserMessageAnchors from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/Chat/MessageList/UserMessageAnchors";
import ScrollToBottom from "@agentscope-ai/chat/lib/Bubble/ScrollToBottom";
import Style from "@agentscope-ai/chat/lib/Bubble/style/list";
import type { IAgentScopeRuntimeWebUIMessage } from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/types/IMessages";
import { useCallback, useMemo, useRef } from "react";
import { useContextSelector } from "use-context-selector";
import sessionApi from "../sessionApi";
import VirtualizedBubbleList, {
  type VirtualizedBubbleListRef,
} from "./VirtualizedBubbleList";

function waitForNextFrame() {
  return new Promise<void>((resolve) => {
    requestAnimationFrame(() => resolve());
  });
}

export default function MessageList(props: {
  // Matches the vendor Welcome / MessageList submit payload.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  onSubmit: (data: { query: string; fileList?: any[] }) => void;
}) {
  const messages = useContextSelector(
    ChatAnywhereMessagesContext,
    (value) => value.messages,
  );
  const safeMessages = useMemo(
    () => [...(messages || [])].reverse() as IAgentScopeRuntimeWebUIMessage[],
    [messages],
  );
  const prefixCls = useProviderContext().getPrefixCls(
    "chat-anywhere-message-list",
  );
  const bubblePrefixCls = useProviderContext().getPrefixCls("bubble-list");
  const scrollContainerClassName = `${prefixCls}-bubble-scroll`;
  const currentSessionId = useContextSelector(
    ChatAnywhereSessionsContext,
    (value) => value.currentSessionId,
  );
  const userMessageAnchorsOptions = useChatAnywhereOptions(
    (value) => value.theme?.bubbleList?.userMessageAnchors,
  );
  const listRef = useRef<VirtualizedBubbleListRef | null>(null);

  const renderedItemsKey = useMemo(
    () => safeMessages.map((message) => message.id).join("|"),
    [safeMessages],
  );

  const ensureMessageVisible = useCallback(async (messageId: string) => {
    listRef.current?.scrollToItem(messageId);
    await waitForNextFrame();
  }, []);

  const handleStartReached = useCallback(() => {
    sessionApi.requestLoadEarlier();
  }, []);

  const renderItem = useCallback(
    (item: IAgentScopeRuntimeWebUIMessage, index: number, isLast: boolean) => {
      void index;
      return <Bubble {...item} isLast={isLast} />;
    },
    [],
  );

  if (safeMessages.length === 0) {
    return (
      <div className={`${prefixCls} ${prefixCls}-welcome`}>
        <Welcome onSubmit={props.onSubmit} />
      </div>
    );
  }

  return (
    <div className={prefixCls}>
      <Style />
      <VirtualizedBubbleList
        ref={listRef}
        key={currentSessionId}
        order="desc"
        prefixCls={bubblePrefixCls}
        items={safeMessages}
        classNames={{
          wrapper: `${prefixCls}-bubble-wrapper`,
          list: scrollContainerClassName,
        }}
        onStartReached={handleStartReached}
        renderItem={renderItem}
        renderScrollToBottom={(visible, onClick) => (
          <ScrollToBottom visible={visible} onClick={onClick} />
        )}
      />
      <UserMessageAnchors
        badgeMaxCount={userMessageAnchorsOptions?.badgeMaxCount}
        enabled={userMessageAnchorsOptions?.enabled !== false}
        items={safeMessages}
        minGap={userMessageAnchorsOptions?.minGap}
        minCount={userMessageAnchorsOptions?.minCount}
        onEnsureMessageVisible={ensureMessageVisible}
        prefixCls={prefixCls}
        renderedItemsKey={renderedItemsKey}
        scrollContainerClassName={scrollContainerClassName}
        variant={userMessageAnchorsOptions?.variant}
      />
    </div>
  );
}
