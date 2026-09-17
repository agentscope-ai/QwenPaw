import ReactMarkdown from "react-markdown";

import styles from "./InlineMarkdown.module.less";

/** Inline-only tags safe for compact menu / suggestion rows. */
const INLINE_ELEMENTS = ["p", "strong", "em", "code", "del"] as const;

/**
 * Render a short Markdown snippet as inline content (no block layout).
 * Disallowed nodes are unwrapped so surrounding text still appears.
 */
export function InlineMarkdown({
  markdown,
  className,
}: {
  markdown: string;
  className?: string;
}) {
  if (!markdown) return null;

  return (
    <span className={[styles.root, className].filter(Boolean).join(" ")}>
      <ReactMarkdown
        allowedElements={[...INLINE_ELEMENTS]}
        unwrapDisallowed
        components={{
          p: ({ children }) => <>{children}</>,
        }}
      >
        {markdown}
      </ReactMarkdown>
    </span>
  );
}
