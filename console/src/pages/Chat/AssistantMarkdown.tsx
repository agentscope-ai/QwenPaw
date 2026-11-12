import React, {
  createContext,
  useContext,
  useDeferredValue,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Markdown } from "@agentscope-ai/chat";
import { useEffectiveFontSize } from "../../contexts/FontSizeContext";
import { renderableCodeComponents } from "../../components/RenderableCodeBlock";
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
  const fallback = () => <RenderableCodeBlock {...props} />;
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
const assistantCodeComponents = { code: AssistantCodeBlock };

/**
 * Streaming markdown is expensive: the SDK pushes a delta per token and the
 * vendor parser re-parses the whole message each time. Rendering at ~8 fps
 * keeps the transcript readable while cutting parse work by an order of
 * magnitude. Tests render synchronously (MODE=test) so their assertions keep
 * observing every delta.
 */
const STREAM_RENDER_INTERVAL_MS = import.meta.env.MODE === "test" ? 0 : 120;

export function AssistantMarkdown({
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
  const [displayContent, setDisplayContent] = useState(content);
  const lastFlushRef = useRef(0);
  const pendingContentRef = useRef(content);
  const flushTimerRef = useRef<number | null>(null);

  // Throttle (not debounce): keep flushing the latest delta every interval
  // while tokens keep arriving, so the transcript still streams.
  useEffect(() => {
    pendingContentRef.current = content;
    if (!isStreaming) {
      if (flushTimerRef.current !== null) {
        window.clearTimeout(flushTimerRef.current);
        flushTimerRef.current = null;
      }
      setDisplayContent(content);
      return;
    }
    if (STREAM_RENDER_INTERVAL_MS === 0) {
      setDisplayContent(content);
      return;
    }
    if (flushTimerRef.current !== null) return;
    const now = Date.now();
    const wait = Math.max(
      0,
      STREAM_RENDER_INTERVAL_MS - (now - lastFlushRef.current),
    );
    flushTimerRef.current = window.setTimeout(() => {
      flushTimerRef.current = null;
      lastFlushRef.current = Date.now();
      setDisplayContent(pendingContentRef.current);
    }, wait);
  }, [content, isStreaming]);

  useEffect(
    () => () => {
      if (flushTimerRef.current !== null) {
        window.clearTimeout(flushTimerRef.current);
        flushTimerRef.current = null;
      }
    },
    [],
  );

  const deferredContent = useDeferredValue(displayContent);
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
  // Reuse the same element while the throttled content is unchanged: React
  // then skips re-rendering (and re-parsing) the vendor Markdown per token.
  const plainMarkdown = useMemo(
    () => (
      <Markdown
        baseFontSize={baseFontSize}
        components={renderableCodeComponents}
        content={deferredContent}
        cursor={cursor}
      />
    ),
    [baseFontSize, deferredContent, cursor],
  );
  if (!extended) {
    return plainMarkdown;
  }
  return (
    <CodeBlockContext.Provider
      value={{
        entries,
        // Do not finalize an unfinished block against the previous deferred
        // source when the last delta and completion arrive together.
        streaming: isStreaming || deferredContent !== displayContent,
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
