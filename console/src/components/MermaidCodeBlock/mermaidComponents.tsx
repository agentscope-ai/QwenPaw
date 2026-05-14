import type { ReactNode } from "react";
import type { ComponentProps } from "@ant-design/x-markdown";
import { MermaidCodeBlock } from "./MermaidCodeBlock";

/**
 * Extracts plain text from React children recursively.
 * XMarkdown may pass children as string or nested ReactNode elements.
 */
function extractText(children: ReactNode): string {
  if (typeof children === "string") return children;
  if (typeof children === "number") return String(children);
  if (Array.isArray(children)) return children.map(extractText).join("");
  if (children && typeof children === "object" && "props" in children) {
    return extractText(
      (children as { props: { children?: ReactNode } }).props.children,
    );
  }
  return "";
}

/**
 * Custom code component for XMarkdown that renders mermaid code blocks
 * as interactive diagrams, while leaving other code blocks as default.
 */
function CodeWithMermaid({
  children,
  lang,
  block,
  className,
  domNode: _domNode,
  streamStatus: _streamStatus,
  ...rest
}: ComponentProps) {
  if (block && lang === "mermaid") {
    const chartSource = extractText(children);
    if (chartSource.trim()) {
      return <MermaidCodeBlock chart={chartSource} />;
    }
  }

  return (
    <code className={className} {...rest}>
      {children}
    </code>
  );
}

/**
 * XMarkdown components mapping that enables Mermaid diagram rendering.
 *
 * Usage:
 * ```tsx
 * <XMarkdown content={markdown} components={mermaidComponents} />
 * ```
 */
export const mermaidComponents: Record<
  string,
  React.ComponentType<ComponentProps>
> = {
  code: CodeWithMermaid,
};
