import type { ReactNode, ComponentPropsWithoutRef } from "react";
import type { Element } from "hast";
import { MermaidCodeBlock } from "./MermaidCodeBlock";

/** react-markdown v10 `code` component props. */
interface CodeProps extends ComponentPropsWithoutRef<"code"> {
  node?: Element;
  /** Whether this is a fenced block vs inline code span. */
  inline?: boolean;
  children?: ReactNode;
}

/**
 * Extracts plain text from React children recursively.
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
 * Custom `code` component for react-markdown that renders mermaid fenced
 * blocks as interactive diagrams, leaving all other code as default.
 *
 * Language is encoded in `className` as `language-mermaid` by react-markdown.
 */
function CodeWithMermaid({
  children,
  className,
  inline,
  node: _node,
  ...rest
}: CodeProps) {
  const isMermaid = !inline && className === "language-mermaid";
  if (isMermaid) {
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
 * react-markdown `components` mapping that enables Mermaid diagram rendering.
 *
 * Usage:
 * ```tsx
 * <ReactMarkdown remarkPlugins={[remarkGfm]} components={mermaidComponents}>
 *   {markdown}
 * </ReactMarkdown>
 * ```
 */
export const mermaidComponents = {
  code: CodeWithMermaid,
} as const;
