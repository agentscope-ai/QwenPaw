import type { CopyableResponse } from "./utils";
import { ForkBoundary } from "./ForkBoundary";
import {
  projectTurnTimeline,
  type TimelineRow,
  type SteerReceipt,
} from "./steerTimeline";
import { useSteerStore, EMPTY_STEERS } from "../../stores/steerStore";
/**
 * pages/Chat/HostBubbles.tsx — host-side response renderer for CoPaw-specific
 * Markdown, media download, artifact, and plugin behavior.
 *
 * Why wrappers:
 * - We register HostResponseCard into options.cards so the SDK Cards
 *   dispatcher invokes it instead of the vendor default.
 * - The wrapper itself subscribes to the chat extension registry via hooks,
 *   so it re-renders when plugins register/dispose — no need to rebuild the
 *   parent useMemo (and avoid re-mounting bubbles on every plugin change).
 *
 * SDK 1.2 integrations use the public request.render/prepend/append seam.
 * HostRequestCard retains the original vendor-card wrapper for callers that
 * register it directly; do not also configure the same public request slots.
 * Vendor response primitives remain private dependencies because CoPaw
 * replaces individual Markdown/media/tool rendering rather than only framing
 * the default response bubble.
 */
import React, {
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import VendorRequestCard from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/AgentScopeRuntime/Request/Card";
import AgentScopeRuntimeResponseBuilder from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/AgentScopeRuntime/Response/Builder";
import ResponseActions from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/AgentScopeRuntime/Response/Actions";
import ResponseError from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/AgentScopeRuntime/Response/Error";
import ResponseReasoning from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/AgentScopeRuntime/Response/Reasoning";
import ResponseTool from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/AgentScopeRuntime/Response/Tool";
import {
  AgentScopeRuntimeContentType,
  AgentScopeRuntimeMessageType,
  AgentScopeRuntimeRunStatus,
  Bubble,
  DefaultCards,
  Markdown,
  type IAgentScopeRuntimeMessage,
  type IAgentScopeRuntimeResponse,
} from "@agentscope-ai/chat";
import { useChatAnywhereOptions } from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/Context/ChatAnywhereOptionsContext";
import { Avatar, Button, Flex } from "antd";
import { useTranslation } from "react-i18next";
import { AlertTriangle } from "lucide-react";
import { hasTruncatedModelOutput } from "./completionNotice";
import { AssistantMarkdown } from "./AssistantMarkdown";
import { useEffectiveFontSize } from "@/contexts/FontSizeContext";
import { stripScrollHeadlines } from "./headlineFilter";
import {
  useChatScalarSnapshot,
  useChatListSnapshot,
} from "../../plugins/registry/useChatExtensions";
import { ChatScalar, ChatList } from "../../plugins/registry/slotKeys";
import { PluginSlotBoundary } from "../../plugins/registry/PluginSlotBoundary";
import type {
  ChatRequestData,
  ChatResponseData,
} from "../../plugins/registry/types";
import { DownloadableAudios } from "../../components/Chat/MediaDownload";
import { ToolCallTurnBoundary } from "./turnEndedProvider";
import ResponseArtifactList from "../../features/files-workspace/ResponseArtifactList";
import { isToolLikeResponseMessageType } from "./responseMessageTypes";
import {
  countCollapsedSteps,
  filterThinkingMessages,
  findActiveStepBlockIndex,
  findLastStepBlockIndex,
  getCollapsedGroupStatus,
  getCollapsedStepPresentation,
  getCollapsedStepRenderKey,
  getResponseMessageDisplayMode,
  groupResponseMessages,
} from "./messageDisplay";
import styles from "./HostBubbles.module.less";
import LazyAccordion from "./LazyAccordion";
import {
  getAssistantMessageDisplayPreference,
  getShowThinkingPreference,
  subscribeChatDisplayPreference,
  type AssistantMessageDisplayPreference,
} from "../../utils/chatDisplayPreference";
import {
  MeasuredMessageWindow,
  RESPONSE_WINDOW_LIMIT,
} from "./MeasuredMessageWindow";
import {
  createMessageWindowState,
  MessageWindowStateContext,
} from "./messageWindowState";

function ResponseWindow<T>({
  items,
  id,
  itemKey,
  render,
}: {
  items: T[];
  id: string;
  itemKey: (item: T, index: number) => string;
  render: (item: T, index: number) => React.ReactNode;
}) {
  return (
    <MeasuredMessageWindow
      cacheKey={id}
      ids={items.map(itemKey)}
      estimate={120}
      maxItems={RESPONSE_WINDOW_LIMIT}
    >
      {(index) => render(items[index], index)}
    </MeasuredMessageWindow>
  );
}

function sortByOrder<T extends { item: { order?: number } }>(arr: T[]): T[] {
  return arr
    .slice()
    .sort((a, b) => (a.item.order ?? 100) - (b.item.order ?? 100));
}

const DeferHistoryContentContext = React.createContext(true);

export function EagerHistoryContent({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <DeferHistoryContentContext.Provider value={false}>
      {children}
    </DeferHistoryContentContext.Provider>
  );
}

export function DeferredHistoryContent({
  children,
  enabled,
}: {
  children: React.ReactNode;
  enabled: boolean;
}) {
  const rootRef = useRef<HTMLDivElement>(null);
  const [nearViewport, setNearViewport] = useState(
    () => !enabled || typeof IntersectionObserver === "undefined",
  );

  useEffect(() => {
    if (!enabled || nearViewport || !rootRef.current) return undefined;
    const root = rootRef.current.closest<HTMLElement>(
      '[data-history-message-window="true"], ' +
        '[class*="chat-anywhere-message-list-bubble-scroll"]',
    );
    const observer = new IntersectionObserver(
      (entries) => {
        if (!entries.some((entry) => entry.isIntersecting)) return;
        setNearViewport(true);
        observer.disconnect();
      },
      { root, rootMargin: "300px 0px" },
    );
    observer.observe(rootRef.current);
    return () => observer.disconnect();
  }, [enabled, nearViewport]);

  return (
    <div
      ref={rootRef}
      className={nearViewport ? undefined : styles.deferredHistoryContent}
    >
      {nearViewport ? children : null}
    </div>
  );
}

const HostMessage = React.memo(function HostMessage({
  data,
}: {
  data: IAgentScopeRuntimeMessage;
}) {
  const replaceMediaURL = useChatAnywhereOptions(
    (options) => options.api?.replaceMediaURL,
  );
  const onFileCardClick = useChatAnywhereOptions(
    (options) => options.api?.onFileCardClick,
  );
  const formatMediaURL = (url?: string) =>
    url ? replaceMediaURL?.(url) || url : url;
  const baseFontSize = useEffectiveFontSize();
  const metadata = (
    data as IAgentScopeRuntimeMessage & {
      metadata?: Record<string, unknown> | null;
    }
  ).metadata;
  const history = Boolean(metadata?.qwenpaw_history);
  const deferHistoryContent = React.useContext(DeferHistoryContentContext);

  if (!data.content?.length) return null;

  return (
    <>
      <ResponseWindow
        items={data.content}
        id={`${data.id}:content`}
        itemKey={(_item, index) => `${data.id}:${index}`}
        render={(item, index) => {
          switch (item.type) {
            case AgentScopeRuntimeContentType.TEXT:
              return (
                <DeferredHistoryContent
                  key={index}
                  enabled={history && deferHistoryContent}
                >
                  <div
                    className={styles.quoteResponse}
                    data-quote-response={
                      data.role === "assistant" ? "true" : undefined
                    }
                  >
                    {history ? (
                      <AssistantMarkdown
                        messageId={`${data.id}:${index}`}
                        content={stripScrollHeadlines(item.text)}
                        cursor={false}
                        isStreaming={false}
                      />
                    ) : (
                      <AssistantMarkdown
                        messageId={`${data.id}:${index}`}
                        content={item.text}
                        cursor={
                          item.status === AgentScopeRuntimeRunStatus.InProgress
                        }
                        // Native text deltas omit content.status; the message owns
                        // their lifecycle. Keep the legacy cursor separate.
                        isStreaming={
                          (item.status ?? data.status) ===
                          AgentScopeRuntimeRunStatus.InProgress
                        }
                      />
                    )}
                  </div>
                </DeferredHistoryContent>
              );
            case AgentScopeRuntimeContentType.REFUSAL:
              return (
                <Markdown
                  key={index}
                  content={item.refusal}
                  raw
                  baseFontSize={baseFontSize}
                />
              );
            case AgentScopeRuntimeContentType.IMAGE:
              return (
                <DefaultCards.Images
                  key={index}
                  data={[{ url: formatMediaURL(item.image_url) }]}
                />
              );
            case AgentScopeRuntimeContentType.VIDEO:
              return (
                <DefaultCards.Videos
                  key={index}
                  data={[
                    {
                      poster: formatMediaURL(item.video_poster),
                      src: formatMediaURL(item.video_url) || "",
                    },
                  ]}
                />
              );
            case AgentScopeRuntimeContentType.FILE:
              return (
                <DefaultCards.Files
                  key={index}
                  data={[
                    {
                      name: item.file_name || item.fileName || item.file_id,
                      size: item.file_size,
                      url: formatMediaURL(item.file_url),
                    },
                  ]}
                  onClick={onFileCardClick}
                />
              );
            case AgentScopeRuntimeContentType.AUDIO:
              return (
                <DownloadableAudios
                  key={index}
                  data={[
                    { src: formatMediaURL(item.audio_url || item.data) || "" },
                  ]}
                />
              );
            default:
              return <div key={index}>{JSON.stringify(item)}</div>;
          }
        }}
      />
    </>
  );
});

const HistoryResponseMessage = React.memo(function HistoryResponseMessage({
  item,
}: {
  item: IAgentScopeRuntimeMessage;
}) {
  return renderResponseMessageContent(item);
});

function renderResponseMessage(item: IAgentScopeRuntimeMessage) {
  const metadata = (
    item as IAgentScopeRuntimeMessage & {
      metadata?: Record<string, unknown> | null;
    }
  ).metadata;
  // Durable items are immutable. Keep the overlapping rows of a moving
  // window from re-rendering expensive tool and reasoning components.
  return metadata?.qwenpaw_history ? (
    <HistoryResponseMessage key={responseMessageKey(item)} item={item} />
  ) : (
    renderResponseMessageContent(item)
  );
}

function responseMessageKey(item: IAgentScopeRuntimeMessage) {
  return isToolLikeResponseMessageType(item.type)
    ? AgentScopeRuntimeResponseBuilder.getToolMessageKey(item) || item.id
    : item.id;
}

function renderResponseMessageContent(item: IAgentScopeRuntimeMessage) {
  if (isToolLikeResponseMessageType(item.type)) {
    return <ResponseTool key={responseMessageKey(item)} data={item} />;
  }
  switch (item.type) {
    case AgentScopeRuntimeMessageType.MESSAGE:
      return <HostMessage key={responseMessageKey(item)} data={item} />;
    case AgentScopeRuntimeMessageType.MCP_APPROVAL_REQUEST:
      return (
        <ResponseTool key={responseMessageKey(item)} data={item} isApproval />
      );
    case AgentScopeRuntimeMessageType.REASONING:
      return (
        <div key={responseMessageKey(item)} className={styles.reasoningStep}>
          <ResponseReasoning
            data={
              item.content.length > 1
                ? {
                    ...item,
                    content: [
                      {
                        type: AgentScopeRuntimeContentType.TEXT,
                        status: item.status,
                        text: item.content
                          .filter(
                            (part) =>
                              part.type === AgentScopeRuntimeContentType.TEXT,
                          )
                          .map((part) => part.text)
                          .join("\n\n"),
                      },
                    ],
                  }
                : item
            }
          />
        </div>
      );
    case AgentScopeRuntimeMessageType.ERROR:
      return <ResponseError key={responseMessageKey(item)} data={item} />;
    case AgentScopeRuntimeMessageType.HEARTBEAT:
      return null;
    default:
      console.warn(`[WIP] Unknown message type: ${item.type}`);
      return null;
  }
}

function EmptyResponseFork({ data }: { data: IAgentScopeRuntimeResponse }) {
  const actions = useChatAnywhereOptions((options) => options.actions?.list);
  const action = actions?.find(
    (item) => (item as { key?: string }).key === "fork",
  );
  return action?.render ? (
    <div className={styles.emptyResponseActions}>
      {React.createElement(action.render, { data })}
    </div>
  ) : null;
}

function DefaultHostResponseCard({
  data,
  messageId,
  isLast,
  contentPrepend,
  contentAppend,
  hideActions = false,
}: {
  data: IAgentScopeRuntimeResponse;
  hideActions?: boolean;
  messageId: string;
  isLast?: boolean;
  contentPrepend?: React.ReactNode;
  contentAppend?: React.ReactNode;
}) {
  const { t } = useTranslation();
  const avatar = useChatAnywhereOptions((options) => options.welcome?.avatar);
  const nick = useChatAnywhereOptions((options) => options.welcome?.nick);
  const nickNode =
    typeof nick === "string" || React.isValidElement(nick) ? nick : null;
  const mergedMessages = useMemo(
    () => AgentScopeRuntimeResponseBuilder.mergeToolMessages(data.output),
    [data.output],
  );
  const canceledWithoutReply =
    data.status === "canceled" && !data.output?.length;
  const showThinking = useSyncExternalStore(
    subscribeChatDisplayPreference,
    getShowThinkingPreference,
    () => true,
  );
  const messages = useMemo(
    () => filterThinkingMessages(mergedMessages, showThinking),
    [mergedMessages, showThinking],
  );
  const assistantDisplayPreference =
    useSyncExternalStore<AssistantMessageDisplayPreference>(
      subscribeChatDisplayPreference,
      getAssistantMessageDisplayPreference,
      () => "result-collapsed",
    );
  const messageDisplayMode = getResponseMessageDisplayMode(
    data.status,
    assistantDisplayPreference,
  );
  const messageBlocks = useMemo(
    () => groupResponseMessages(messages, messageDisplayMode),
    [messageDisplayMode, messages],
  );
  const activeStepBlockIndex = findActiveStepBlockIndex(messageBlocks);
  const statusStepBlockIndex =
    messageDisplayMode === "text-only"
      ? activeStepBlockIndex
      : findLastStepBlockIndex(messageBlocks);

  if (
    !messages.length &&
    AgentScopeRuntimeResponseBuilder.maybeGenerating(data)
  ) {
    return <Bubble.Spin />;
  }
  if (
    hideActions &&
    !messages.length &&
    !data.error &&
    data.status !== "canceled"
  )
    return null;

  return (
    <div style={{ width: "100%", minWidth: 0 }}>
      {avatar ? (
        <Flex align="center" gap={8} style={{ marginBottom: 8 }}>
          <Avatar src={avatar} />
          {nickNode ? <span>{nickNode}</span> : null}
        </Flex>
      ) : null}
      {contentPrepend}
      <ResponseWindow
        items={messageBlocks}
        id={`${messageId}:blocks`}
        itemKey={(block, index) =>
          block.kind === "message"
            ? responseMessageKey(block.message)
            : `group:${
                block.messages[0]
                  ? responseMessageKey(block.messages[0])
                  : index
              }`
        }
        render={(block, index) => {
          if (block.kind === "message") {
            return renderResponseMessage(block.message);
          }

          const groupStatus = getCollapsedGroupStatus(
            data.status,
            index === statusStepBlockIndex,
          );
          const presentation = getCollapsedStepPresentation(groupStatus);
          const firstId = block.messages[0]
            ? responseMessageKey(block.messages[0])
            : index;
          const stepCount = countCollapsedSteps(block.messages);
          if (stepCount === 0) {
            return (
              <React.Fragment key={`messages-${firstId}`}>
                <ResponseWindow
                  items={block.messages}
                  id={`${messageId}:group:${firstId}`}
                  itemKey={responseMessageKey}
                  render={renderResponseMessage}
                />
              </React.Fragment>
            );
          }
          return (
            <LazyAccordion
              stateKey={`${messageId}:group:${index}:${messageDisplayMode}`}
              className={styles.collapsedSteps}
              key={getCollapsedStepRenderKey(
                firstId,
                messageDisplayMode,
                presentation.status,
              )}
              status={presentation.status}
              title={t(presentation.titleKey, {
                count: stepCount,
              })}
              defaultOpen={presentation.defaultOpen}
              renderChildren={() => (
                <ResponseWindow
                  items={block.messages}
                  id={`${messageId}:group:${firstId}`}
                  itemKey={responseMessageKey}
                  render={renderResponseMessage}
                />
              )}
            />
          );
        }}
      />
      {hasTruncatedModelOutput(data) ? (
        <div role="status" className={styles.completionWarning}>
          <AlertTriangle size={16} aria-hidden="true" />
          <span>{t("chat.outputTruncated")}</span>
        </div>
      ) : null}
      {data.error ? <ResponseError data={data.error} /> : null}
      {data.status === "canceled" && !messages.length && !data.error ? (
        <Bubble.Interrupted
          title={t(
            canceledWithoutReply
              ? "chat.canceledWithoutReply"
              : "chat.turnCanceled",
          )}
        />
      ) : null}
      {contentAppend}
      {AgentScopeRuntimeResponseBuilder.maybeDone(data) ? (
        <ResponseArtifactList messages={messages} />
      ) : null}
      {!hideActions ? (
        canceledWithoutReply ? (
          <EmptyResponseFork data={data} />
        ) : (
          <ResponseActions data={data} messageId={messageId} isLast={isLast} />
        )
      ) : null}
    </div>
  );
}

function SteerResponseCard(
  props: React.ComponentProps<typeof DefaultHostResponseCard>,
) {
  const { t } = useTranslation();
  const showThinking = useSyncExternalStore(
    subscribeChatDisplayPreference,
    getShowThinkingPreference,
    () => true,
  );
  const metadata = (
    props.data as unknown as {
      metadata?: {
        turn_id?: string;
        steer_scope?: string;
        initial_user_message_id?: string;
        qwenpaw_history?: boolean;
        fork_capability_status?: string;
        steer_receipts?: SteerReceipt[];
        steer_receipts_loaded?: boolean;
      };
    }
  ).metadata;
  const turnId = metadata?.turn_id || props.messageId;
  const retry = useSteerStore((s) => s.retry[metadata?.steer_scope || ""]);
  const allReceipts = useSteerStore(
    (s) => s.receipts[metadata?.steer_scope || ""] || EMPTY_STEERS,
  );
  const history =
    Boolean(metadata?.qwenpaw_history) ||
    props.data.output.some(
      (m) =>
        (m as unknown as { metadata?: Record<string, unknown> }).metadata
          ?.qwenpaw_history,
    );
  const pageOwned =
    history && metadata?.fork_capability_status !== "in_progress";
  const receipts = useMemo(() => {
    const live = allReceipts.filter((r) => r.turn_id === turnId);
    if (!pageOwned) return live;
    // Only rows owned by this history fragment may be recovered here.
    if (!metadata?.steer_receipts_loaded) return [];
    return (metadata.steer_receipts || []).map((receipt) => {
      const newer = live.find(
        (r) => r.client_message_id === receipt.client_message_id,
      );
      return newer && newer.revision > receipt.revision ? newer : receipt;
    });
  }, [
    allReceipts,
    turnId,
    pageOwned,
    metadata?.steer_receipts,
    metadata?.steer_receipts_loaded,
  ]);
  const hasSteer =
    receipts.length > 0 || props.data.output.some((m) => m.role === "user");
  const timelineEnabled =
    hasSteer || (!history && Boolean(metadata?.steer_scope));
  const rows = useMemo((): TimelineRow<IAgentScopeRuntimeMessage>[] => {
    if (!timelineEnabled) return [];
    // Stream message-start envelopes can precede their first text delta.
    // They own an ID, but must not leave a visible segment across a steer.
    const output = props.data.output.filter(
      (message) =>
        message.type !== AgentScopeRuntimeMessageType.HEARTBEAT &&
        ((message.type !== AgentScopeRuntimeMessageType.MESSAGE &&
          message.type !== AgentScopeRuntimeMessageType.REASONING) ||
          message.role === "user" ||
          message.content.some(
            (part) =>
              part.type !== AgentScopeRuntimeContentType.TEXT ||
              Boolean(part.text?.trim()),
          )),
    );
    const projected = projectTurnTimeline(output, receipts, turnId);
    if (!projected.some((row) => row.kind === "assistant") && !output.length) {
      projected.unshift({
        kind: "assistant",
        key: `${turnId}:${metadata?.initial_user_message_id || "initial"}`,
        messages: [],
      });
    }
    return projected;
  }, [
    props.data.output,
    receipts,
    turnId,
    timelineEnabled,
    metadata?.initial_user_message_id,
  ]);
  if (!timelineEnabled) return <DefaultHostResponseCard {...props} />;
  const lastAssistant = rows.reduce(
    (last, row, index) => (row.kind === "assistant" ? index : last),
    -1,
  );
  const actionSegment = rows.reduce(
    (last, row, index) =>
      row.kind === "assistant" &&
      filterThinkingMessages(row.messages, showThinking).length > 0
        ? index
        : last,
    -1,
  );
  const emptyForkSegment = rows.reduce(
    (last, row, index) =>
      row.kind === "assistant" || row.status === "applied" ? index : last,
    -1,
  );
  return (
    <div style={{ width: "100%", minWidth: 0 }}>
      {props.contentPrepend}
      {rows.map((row, index) => (
        <React.Fragment key={row.key}>
          {row.kind === "user" ? (
            <div
              key={row.key}
              data-steer-message-id={row.messageId}
              data-role="user"
              id={row.messageId}
              aria-label={t("chat.steer.user")}
              style={{
                display: "flex",
                flexDirection: "column",
                alignItems: "flex-end",
                width: "100%",
                margin: "24px 0",
              }}
            >
              <VendorRequestCard
                data={
                  {
                    input: [
                      {
                        role: "user",
                        type: AgentScopeRuntimeMessageType.MESSAGE,
                        content: row.content || [],
                      },
                    ],
                  } as React.ComponentProps<typeof VendorRequestCard>["data"]
                }
                contentAppend={
                  row.status !== "applied" ? (
                    <small role="status">
                      {t(`chat.steer.${row.status}`)}
                      {row.reason
                        ? `：${t(`chat.steer.reason.${row.reason}`, {
                            defaultValue: row.reason,
                          })}`
                        : ""}
                    </small>
                  ) : null
                }
              />
              {row.status === "sync_failed" && retry ? (
                <Button
                  type="text"
                  size="small"
                  onClick={() => void retry(turnId).catch(() => {})}
                >
                  {t("chat.steer.retry")}
                </Button>
              ) : null}
            </div>
          ) : (
            <React.Fragment key={row.key}>
              <DefaultHostResponseCard
                messageId={`${props.messageId}:${row.key}`}
                hideActions
                data={
                  {
                    ...props.data,
                    output: row.messages,
                    status:
                      index === lastAssistant ? props.data.status : "completed",
                    error: index === lastAssistant ? props.data.error : null,
                  } as IAgentScopeRuntimeResponse
                }
              />
              {index === actionSegment ? (
                <>
                  {props.contentAppend}
                  <ResponseActions
                    data={props.data}
                    messageId={props.messageId}
                    isLast={props.isLast}
                  />
                </>
              ) : null}
            </React.Fragment>
          )}
          {actionSegment < 0 && index === emptyForkSegment ? (
            <EmptyResponseFork data={props.data} />
          ) : null}
        </React.Fragment>
      ))}
      {actionSegment < 0 ? props.contentAppend : null}
    </div>
  );
}

function HostRequestCardContent(props: { data: ChatRequestData }) {
  const extScalar = useChatScalarSnapshot();
  const extLists = useChatListSnapshot();

  const renderEntry = extScalar[ChatScalar.requestRender];
  const renderFn = renderEntry?.value;
  const prependList = sortByOrder(extLists[ChatList.requestPrepend]);
  const appendList = sortByOrder(extLists[ChatList.requestAppend]);

  // prepend/append routed through vendor's contentPrepend/contentAppend
  // slot so actions stay last. Mirrors HostResponseCard.
  const contentPrepend =
    prependList.length === 0 ? null : (
      <>
        {prependList.map((e) => (
          <PluginSlotBoundary
            key={e.item.id}
            slot={ChatList.requestPrepend}
            pluginId={e.pluginId}
          >
            {e.item.render({ data: props.data })}
          </PluginSlotBoundary>
        ))}
      </>
    );
  const contentAppend =
    appendList.length === 0 ? null : (
      <>
        {appendList.map((e) => (
          <PluginSlotBoundary
            key={e.item.id}
            slot={ChatList.requestAppend}
            pluginId={e.pluginId}
          >
            {e.item.render({ data: props.data })}
          </PluginSlotBoundary>
        ))}
      </>
    );

  const fallback = () => (
    <VendorRequestCard
      data={
        props.data as unknown as React.ComponentProps<
          typeof VendorRequestCard
        >["data"]
      }
      contentPrepend={contentPrepend}
      contentAppend={contentAppend}
    />
  );

  if (renderFn) {
    return (
      <PluginSlotBoundary
        slot={ChatScalar.requestRender}
        pluginId={renderEntry!.pluginId}
        fallback={fallback()}
      >
        {renderFn({ data: props.data, fallback })}
      </PluginSlotBoundary>
    );
  }
  return fallback();
}

const MemoizedHostRequestCard = React.memo(HostRequestCardContent);

export function HostRequestCard(props: { data: ChatRequestData }) {
  return <MemoizedHostRequestCard {...props} />;
}

function HostResponseCardContent(props: {
  id: string;
  data: ChatResponseData;
  isLast?: boolean;
}) {
  const extScalar = useChatScalarSnapshot();
  const extLists = useChatListSnapshot();

  const renderEntry = extScalar[ChatScalar.responseRender];
  const renderFn = renderEntry?.value;
  const prependList = sortByOrder(extLists[ChatList.responsePrepend]);
  const appendList = sortByOrder(extLists[ChatList.responseAppend]);

  // prepend/append are routed through vendor's contentPrepend/contentAppend
  // slot so they land BETWEEN messages and Actions — actions always last.
  // Vendor change: see Response/Card.js DefaultResponseRender, which now
  // reads props.contentPrepend / props.contentAppend.
  const contentPrepend =
    prependList.length === 0 ? null : (
      <>
        {prependList.map((e) => (
          <PluginSlotBoundary
            key={e.item.id}
            slot={ChatList.responsePrepend}
            pluginId={e.pluginId}
          >
            {e.item.render({ data: props.data, isLast: props.isLast })}
          </PluginSlotBoundary>
        ))}
      </>
    );
  const contentAppend =
    appendList.length === 0 ? null : (
      <>
        {appendList.map((e) => (
          <PluginSlotBoundary
            key={e.item.id}
            slot={ChatList.responseAppend}
            pluginId={e.pluginId}
          >
            {e.item.render({ data: props.data, isLast: props.isLast })}
          </PluginSlotBoundary>
        ))}
      </>
    );

  const fallback = () => (
    <SteerResponseCard
      data={props.data as unknown as IAgentScopeRuntimeResponse}
      messageId={props.id}
      isLast={props.isLast}
      contentPrepend={contentPrepend}
      contentAppend={contentAppend}
    />
  );

  if (renderFn) {
    return (
      <PluginSlotBoundary
        slot={ChatScalar.responseRender}
        pluginId={renderEntry!.pluginId}
        fallback={fallback()}
      >
        {renderFn({
          data: props.data,
          isLast: props.isLast,
          fallback,
        })}
      </PluginSlotBoundary>
    );
  }
  return fallback();
}

const MemoizedHostResponseCard = React.memo(HostResponseCardContent);

export function HostResponseCard(props: {
  id: string;
  data: ChatResponseData;
  isLast?: boolean;
}) {
  const parentMemory = React.useContext(MessageWindowStateContext);
  const localMemory = useRef(createMessageWindowState());
  // Tool cards cannot tell a running call from one whose turn was interrupted
  // because both lack a result message. Wrapping the whole card publishes the
  // turn state without re-rendering its body: the memoized content bails out
  // on unchanged props.
  return (
    <MessageWindowStateContext.Provider
      value={parentMemory ?? localMemory.current}
    >
      <ToolCallTurnBoundary
        data={props.data as unknown as IAgentScopeRuntimeResponse}
      >
        <MemoizedHostResponseCard {...props} />
        <ForkBoundary data={props.data as unknown as CopyableResponse} />
      </ToolCallTurnBoundary>
    </MessageWindowStateContext.Provider>
  );
}
