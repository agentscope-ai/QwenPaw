import { Markdown } from "@agentscope-ai/chat";
import type { ComponentProps } from "@ant-design/x-markdown";
import { ExternalMarkdownLink } from "../../../components/Markdown/externalLinkComponents";

// Share Chat's Markdown engine without its media previews or session actions.
const components = {
  a: ({ href, children }: ComponentProps) => (
    <ExternalMarkdownLink href={typeof href === "string" ? href : undefined}>
      {children}
    </ExternalMarkdownLink>
  ),
  img: ({ src, alt, title }: ComponentProps) => (
    <img
      src={typeof src === "string" ? src : undefined}
      alt={typeof alt === "string" ? alt : ""}
      title={title}
    />
  ),
};

export function TraceMarkdown({
  text,
  className,
}: {
  text: string;
  className: string;
}) {
  return (
    <div className={className}>
      <Markdown
        content={text}
        cursor={false}
        typing={false}
        animation={false}
        components={components}
      />
    </div>
  );
}
