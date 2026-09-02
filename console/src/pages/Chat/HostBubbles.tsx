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
 * Request extensions use the SDK's public request.render/prepend/append seam.
 * Vendor response primitives remain private dependencies because CoPaw
 * replaces individual Markdown/media/tool rendering rather than only framing
 * the default response bubble.
 */
import React, { useDeferredValue, useMemo } from "react";
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
import { Avatar, Flex } from "antd";
import { useTranslation } from "react-i18next";
import { renderableCodeComponents } from "../../components/RenderableCodeBlock";
import {
  useChatScalarSnapshot,
  useChatListSnapshot,
} from "../../plugins/registry/useChatExtensions";
import { ChatScalar, ChatList } from "../../plugins/registry/slotKeys";
import { PluginSlotBoundary } from "../../plugins/registry/PluginSlotBoundary";
import type { ChatResponseData } from "../../plugins/registry/types";
import { DownloadableAudios } from "../../components/Chat/MediaDownload";
import ResponseArtifactList from "../../features/files-workspace/ResponseArtifactList";
import { isToolLikeResponseMessageType } from "./responseMessageTypes";
import {
  countCollapsedSteps,
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

function sortByOrder<T extends { item: { order?: number } }>(arr: T[]): T[] {
  return arr
    .slice()
    .sort((a, b) => (a.item.order ?? 100) - (b.item.order ?? 100));
}

function DeferredMarkdown({
  content,
  cursor,
}: {
  content: string;
  cursor: boolean;
}) {
  // Parsing Markdown, code fences, and diagrams is substantially more
  // expensive than appending stream text. A deferred value lets React skip
  // obsolete intermediate parses while keeping input and scrolling responsive.
  const deferredContent = useDeferredValue(content);

  return (
    <Markdown
      components={renderableCodeComponents}
      content={deferredContent}
      cursor={cursor}
    />
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

  if (!data.content?.length) return null;

  return (
    <>
      {data.content.map((item, index) => {
        switch (item.type) {
          case AgentScopeRuntimeContentType.TEXT:
            return (
              <DeferredMarkdown
                key={index}
                content={item.text}
                cursor={item.status === AgentScopeRuntimeRunStatus.InProgress}
              />
            );
          case AgentScopeRuntimeContentType.REFUSAL:
            return <Markdown key={index} content={item.refusal} raw />;
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
      })}
    </>
  );
});

function renderResponseMessage(item: IAgentScopeRuntimeMessage) {
  if (isToolLikeResponseMessageType(item.type)) {
    return <ResponseTool key={item.id} data={item} />;
  }
  switch (item.type) {
    case AgentScopeRuntimeMessageType.MESSAGE:
      return <HostMessage key={item.id} data={item} />;
    case AgentScopeRuntimeMessageType.MCP_APPROVAL_REQUEST:
      return <ResponseTool key={item.id} data={item} isApproval />;
    case AgentScopeRuntimeMessageType.REASONING:
      return <ResponseReasoning key={item.id} data={item} />;
    case AgentScopeRuntimeMessageType.ERROR:
      return <ResponseError key={item.id} data={item} />;
    case AgentScopeRuntimeMessageType.HEARTBEAT:
      return null;
    default:
      console.warn(`[WIP] Unknown message type: ${item.type}`);
      return null;
  }
}

function DefaultHostResponseCard({
  data,
  messageId,
  isLast,
  contentPrepend,
  contentAppend,
}: {
  data: IAgentScopeRuntimeResponse;
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
  const messages = useMemo(
    () => AgentScopeRuntimeResponseBuilder.mergeToolMessages(data.output),
    [data.output],
  );
  const messageDisplayMode = getResponseMessageDisplayMode(data.status);
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

  return (
    <>
      {avatar ? (
        <Flex align="center" gap={8} style={{ marginBottom: 8 }}>
          <Avatar src={avatar} />
          {nickNode ? <span>{nickNode}</span> : null}
        </Flex>
      ) : null}
      {contentPrepend}
      {messageBlocks.map((block, index) => {
        if (block.kind === "message") {
          return renderResponseMessage(block.message);
        }

        const groupStatus = getCollapsedGroupStatus(
          data.status,
          index === statusStepBlockIndex,
        );
        const presentation = getCollapsedStepPresentation(groupStatus);
        const firstId = block.messages[0]?.id ?? index;
        const stepCount = countCollapsedSteps(block.messages);
        if (stepCount === 0) {
          return (
            <React.Fragment key={`messages-${firstId}`}>
              {block.messages.map(renderResponseMessage)}
            </React.Fragment>
          );
        }
        return (
          <LazyAccordion
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
              <>{block.messages.map(renderResponseMessage)}</>
            )}
          />
        );
      })}
      {data.error ? <ResponseError data={data.error} /> : null}
      {contentAppend}
      {AgentScopeRuntimeResponseBuilder.maybeDone(data) ? (
        <ResponseArtifactList messages={messages} />
      ) : null}
      <ResponseActions data={data} messageId={messageId} isLast={isLast} />
    </>
  );
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
    <DefaultHostResponseCard
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
  return <MemoizedHostResponseCard {...props} />;
}
