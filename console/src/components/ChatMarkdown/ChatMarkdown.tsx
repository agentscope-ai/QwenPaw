/**
 * Local counterpart of the SDK's Markdown renderer.
 *
 * `@agentscope-ai/chat` builds its Markdown `config` internally and does not
 * forward one, so an instance-level marked tokenizer cannot be registered from
 * the outside. This component keeps the SDK composition unchanged — math,
 * footnotes, citations, streaming cursor, media, link handling, HTML
 * sanitisation and the code-block slot — and only appends the CJK emphasis
 * tokenizer to the extension list.
 *
 * Derived from `@agentscope-ai/chat@1.2.0-beta.1792133067831`
 * (lib/Markdown/Markdown.js). Keep the two in sync when the SDK changes.
 */
import { memo, useCallback, useMemo, type ComponentProps } from "react";
import { ErrorBoundary } from "react-error-boundary";
import classNames from "classnames";
import markedFootnote from "marked-footnote";
import Latex from "@ant-design/x-markdown/plugins/Latex";
import { useProviderContext } from "@agentscope-ai/chat";

import MarkdownX from "@agentscope-ai/chat/lib/Markdown/core";
import CodeBlock from "@agentscope-ai/chat/lib/Markdown/core/components/CodeBlock";
import DisabledImage from "@agentscope-ai/chat/lib/Markdown/core/components/DisableImage";
import Media from "@agentscope-ai/chat/lib/Markdown/core/components/Media";
import Null from "@agentscope-ai/chat/lib/Markdown/core/components/Null";
import Raw from "@agentscope-ai/chat/lib/Markdown/core/components/Raw";
import Link from "@agentscope-ai/chat/lib/Markdown/core/components/Link";
import useCitationsData from "@agentscope-ai/chat/lib/Markdown/core/hooks/useCitationsData";
import useTyping from "@agentscope-ai/chat/lib/Markdown/core/hooks/useTyping";
import { citationsExtension } from "@agentscope-ai/chat/lib/Markdown/core/plugins/citations";
import {
  CursorComponent,
  cursorExtension,
} from "@agentscope-ai/chat/lib/Markdown/core/plugins/cursor";

import { cjkStrongExtension } from "../../utils/markdownCjkStrong";

function supportsLookbehindAssertions(): boolean {
  try {
    new RegExp("(?<=a)b");
    return true;
  } catch {
    return false;
  }
}

const lookbehindSupported = supportsLookbehindAssertions();

type MarkdownProps = {
  content?: string;
  baseFontSize?: number;
  baseLineHeight?: number;
  components?: Record<string, unknown>;
  cursor?: boolean;
  animation?: boolean;
  animationConfig?: Record<string, unknown>;
  typing?: boolean;
  raw?: boolean;
  allowHtml?: boolean;
  citations?: unknown;
  citationsMap?: unknown;
  disableImage?: boolean;
  className?: string;
};

export const ChatMarkdown = memo(function ChatMarkdown(props: MarkdownProps) {
  const baseFontSize = props.baseFontSize || 14;
  const baseLineHeight = props.baseLineHeight || 1.7;
  const content = useTyping({
    content: props.content,
    typing: props.animation ? false : props.typing,
  });
  const prefixCls = useProviderContext().getPrefixCls("markdown");
  const raw = props.raw ?? false;
  const allowHtml = props.allowHtml ?? false;
  const { citationsData, citationsDataCount, CitationComponent } =
    useCitationsData({
      citations: props.citations,
      citationsMap: props.citationsMap,
    });
  const components = useMemo(
    () => ({
      code: CodeBlock,
      style: Null,
      script: Null,
      img: props.disableImage ? DisabledImage : Media,
      citation: CitationComponent,
      "custom-cursor": CursorComponent,
      a: Link,
      ...props.components,
    }),
    [props.disableImage, CitationComponent, props.components],
  ) as unknown as ComponentProps<typeof MarkdownX>["components"];
  const dompurifyConfig = useMemo(
    () => ({ ADD_TAGS: ["custom-cursor", "citation"] }),
    [],
  );
  const { extensions, walkTokens } = useMemo(() => {
    const exts = Latex();
    exts.push(cursorExtension());
    if (citationsDataCount > 0) exts.push(citationsExtension(citationsData));
    const footnote = markedFootnote({
      sectionClass: `${prefixCls}-footnotes`,
    });
    exts.push(...(footnote.extensions ?? []));
    return { extensions: exts, walkTokens: footnote.walkTokens };
  }, [citationsDataCount, citationsData, prefixCls]);
  const config = useMemo(
    () => ({
      extensions,
      walkTokens,
      ...cjkStrongExtension(),
      ...(!allowHtml && {
        renderer: {
          html(token: { text?: string; raw?: string }) {
            const text = token.text || token.raw || "";
            if (/^<br\s*\/?>$/i.test(text.trim())) return "<br />";
            return text.replace(/</g, "&lt;").replace(/>/g, "&gt;");
          },
        },
      }),
    }),
    [extensions, walkTokens, allowHtml],
  );
  const resolvedContent = content || "";
  const fallback = (
    <Raw
      content={resolvedContent}
      baseFontSize={baseFontSize}
      baseLineHeight={baseLineHeight}
    />
  );
  const fallbackRender = useCallback(
    (...args: unknown[]) => {
      console.error(...args);
      return (
        <Raw
          content={resolvedContent}
          baseFontSize={baseFontSize}
          baseLineHeight={baseLineHeight}
        />
      );
    },
    [resolvedContent, baseFontSize, baseLineHeight],
  );
  const markdownStyle = useMemo(
    () => ({ fontSize: baseFontSize, lineHeight: baseLineHeight }),
    [baseFontSize, baseLineHeight],
  );
  if (raw || !lookbehindSupported) return fallback;
  return (
    <ErrorBoundary fallbackRender={fallbackRender}>
      <MarkdownX
        dompurifyConfig={dompurifyConfig}
        cursor={props.cursor}
        animation={props.animation}
        animationConfig={props.animationConfig}
        components={components}
        style={markdownStyle}
        openLinksInNewTab
        className={classNames(prefixCls, props.className)}
        content={resolvedContent}
        config={config}
      />
    </ErrorBoundary>
  );
});
