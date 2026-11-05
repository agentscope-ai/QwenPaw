import {
  WindowedMarkdownTable,
  WindowedMarkdownTableBody,
} from "./WindowedMarkdownTable";
import React, {
  createContext,
  useContext,
  useDeferredValue,
  useRef,
  useMemo,
} from "react";
import { Markdown } from "@agentscope-ai/chat";
import { useEffectiveFontSize } from "../../contexts/FontSizeContext";
import { RenderableCodeBlock } from "../../components/RenderableCodeBlock/RenderableCodeBlock";
import { useChatListSnapshot } from "../../plugins/registry/useChatExtensions";
import { PluginSlotBoundary } from "../../plugins/registry/PluginSlotBoundary";
import {
  useHostCurrentSession,
  useHostSelectedAgent,
} from "../../plugins/hostSdk/hooks";
import type { ChatListSnapshot } from "../../plugins/registry/chatExtensions";
import { resolveLanguage } from "../../components/RenderableCodeBlock/language";
import { CodeBlockSlot, StableCodeBlocks } from "./StableCodeBlocks";

import {
  segmentMarkdown,
  type MarkdownSegments,
} from "./historyMarkdownChunks";
import { MeasuredMessageWindow } from "./MeasuredMessageWindow";

import type { ComponentProps } from "@ant-design/x-markdown";

type MarkdownNode = NonNullable<NonNullable<ComponentProps["domNode"]>["next"]>;
const blockKeys = new WeakMap<MarkdownNode, string>();

/** Footnotes move after the body and can reorder as references resolve. Index
 * code blocks within the body or their stable footnote ID, not display order.
 * Reuse the vendor's parsed tree without parsing or splitting Markdown again.
 */
function getCodeBlockKey(node: MarkdownNode): string | undefined {
  if (!blockKeys.has(node)) {
    let root = node;
    while (root.parent) root = root.parent;
    while (root.prev) root = root.prev;
    const ordinals = new Map<string, number>();
    const visit = (current: MarkdownNode, scope = "body") => {
      const section = current.parent?.parent;
      if (
        "attribs" in current &&
        current.name === "li" &&
        current.attribs.id &&
        section &&
        "attribs" in section &&
        "data-footnotes" in section.attribs
      ) {
        scope = current.attribs.id;
      }
      if (
        "attribs" in current &&
        current.name === "code" &&
        current.attribs["data-block"] === "true"
      ) {
        const ordinal = ordinals.get(scope) ?? 0;
        blockKeys.set(current, `${scope}:${ordinal}`);
        ordinals.set(scope, ordinal + 1);
      }
      if ("children" in current)
        current.children.forEach((child) => visit(child, scope));
    };
    for (
      let current: MarkdownNode | null = root;
      current;
      current = current.next
    ) {
      visit(current);
    }
  }
  return blockKeys.get(node);
}

interface BlockContext {
  entries: ChatListSnapshot["response.codeBlocks"];
  streaming: boolean;
  messageId: string;
  agentId: string;
  sessionId: string;
}
const CodeBlockContext = createContext<BlockContext | null>(null);

function AssistantCodeBlock(
  props: React.ComponentProps<typeof RenderableCodeBlock>,
) {
  const ctx = useContext(CodeBlockContext);
  const language = resolveLanguage(props.lang, props.className);
  const entry =
    props.block === true
      ? ctx?.entries
          .slice()
          .reverse()
          .find((e) => e.item.language === language)
      : undefined;
  const fallback = () => <RenderableCodeBlock {...props} virtualize />;
  if (!entry || !ctx || typeof props.children !== "string" || !props.domNode)
    return fallback();
  const blockKey = getCodeBlockKey(props.domNode);
  if (blockKey === undefined) return fallback();
  const blockId = `${ctx.messageId}:code:${blockKey}`;
  const Component = entry.item.render;
  return (
    <CodeBlockSlot id={blockId}>
      <PluginSlotBoundary
        key={entry.registrationId}
        slot="response.codeBlocks"
        pluginId={entry.pluginId}
        fallback={fallback()}
      >
        <Component
          source={props.children}
          language={language}
          isStreaming={ctx.streaming && props.streamStatus !== "done"}
          messageId={ctx.messageId}
          blockId={blockId}
          agentId={ctx.agentId}
          sessionId={ctx.sessionId}
          fallback={fallback}
        />
      </PluginSlotBoundary>
    </CodeBlockSlot>
  );
}

// Keep the adapter type stable; portals also survive Markdown ancestor replacement.
const assistantCodeComponents = {
  code: AssistantCodeBlock,
  table: WindowedMarkdownTable,
  tbody: WindowedMarkdownTableBody,
};
const chatCodeComponents = {
  table: WindowedMarkdownTable,
  tbody: WindowedMarkdownTableBody,
  code: (props: React.ComponentProps<typeof RenderableCodeBlock>) => (
    <RenderableCodeBlock {...props} virtualize />
  ),
};

function AssistantMarkdownDocument({
  content,
  cursor,
  isStreaming = cursor,
  messageId,
}: {
  content: string;
  cursor: boolean;
  isStreaming?: boolean;
  messageId: string;
}) {
  const deferredContent = useDeferredValue(content);
  const baseFontSize = useEffectiveFontSize();
  const entries = useChatListSnapshot()["response.codeBlocks"];
  const agent = useHostSelectedAgent();
  const session = useHostCurrentSession();
  const scope = useRef({ agentId: agent.id, sessionId: session?.id || "" });
  // The SDK may allocate the session after the first render of a new response.
  if (
    !scope.current.sessionId &&
    agent.id === scope.current.agentId &&
    session?.id
  ) {
    scope.current.sessionId = session.id;
  }
  const extended = entries.length > 0;
  if (!extended) {
    return (
      <Markdown
        baseFontSize={baseFontSize}
        components={chatCodeComponents}
        content={deferredContent}
        cursor={cursor}
      />
    );
  }
  return (
    <CodeBlockContext.Provider
      value={{
        entries,
        // Do not finalize an unfinished block against the previous deferred
        // source when the last delta and completion arrive together.
        streaming: isStreaming || deferredContent !== content,
        messageId,
        ...scope.current,
      }}
    >
      <StableCodeBlocks key={messageId}>
        <Markdown
          baseFontSize={baseFontSize}
          components={assistantCodeComponents}
          content={deferredContent}
          // The vendor cursor appends a literal token, which corrupts unfinished DSL.
          cursor={false}
        />
      </StableCodeBlocks>
    </CodeBlockContext.Provider>
  );
}

const MemoizedMarkdownDocument = React.memo(AssistantMarkdownDocument);

/** Share one semantic rendering path between persisted and streaming text. */
export function AssistantMarkdown(props: {
  content: string;
  cursor: boolean;
  isStreaming?: boolean;
  messageId: string;
}) {
  const entries = useChatListSnapshot()["response.codeBlocks"];
  const previous = useRef<MarkdownSegments>();
  const segments = useMemo(() => {
    const next = entries.length
      ? { source: props.content, chunks: [props.content], stableLength: 0 }
      : segmentMarkdown(props.content, 32 * 1024, previous.current);
    previous.current = next;
    return next;
  }, [props.content, entries]);
  const ids = useMemo(() => {
    let offset = 0;
    return segments.chunks.map((chunk) => {
      const id = `${props.messageId}:markdown:${offset}`;
      offset += chunk.length;
      return id;
    });
  }, [segments, props.messageId]);
  const renderChunk = (index: number) => (
    <MemoizedMarkdownDocument
      content={segments.chunks[index]}
      messageId={ids[index]}
      cursor={index === ids.length - 1 && props.cursor}
      isStreaming={
        index === ids.length - 1 && (props.isStreaming ?? props.cursor)
      }
    />
  );
  // Preserve plugin block identities and small-message layout exactly.
  if (segments.chunks.length === 1)
    return <MemoizedMarkdownDocument {...props} />;
  return (
    <MeasuredMessageWindow ids={ids} cacheKey={`${props.messageId}:markdown`}>
      {renderChunk}
    </MeasuredMessageWindow>
  );
}
