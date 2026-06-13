import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import rehypeRaw from "rehype-raw";
import { MermaidBlock } from "@/components/MermaidBlock";
import { ImageZoom } from "@/components/ImageZoom";
import { CodeBlockWithCopy } from "./CodeBlockWithCopy";
import { slugifyHeading, headingText } from "../markdown";

/**
 * Per-render heading id factory so duplicate headings get -2, -3 suffixes,
 * matching the ids produced by parseToc.
 */
export function createHeadingIdFactory() {
  const counter = new Map<string, number>();
  return (children: React.ReactNode) => {
    const baseId = slugifyHeading(headingText(children));
    const count = (counter.get(baseId) ?? 0) + 1;
    counter.set(baseId, count);
    return count === 1 ? baseId : `${baseId}-${count}`;
  };
}

interface DocMarkdownProps {
  content: string;
  bannerSrc: string;
}

/** Renders a full doc article body from markdown. */
export function DocMarkdown({ content, bannerSrc }: DocMarkdownProps) {
  const { t } = useTranslation();
  const getHeadingId = createHeadingIdFactory();

  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      rehypePlugins={[rehypeRaw, rehypeHighlight]}
      components={{
        h1: ({ children }) => (
          <>
            <h1>{children}</h1>
            <img
              src={bannerSrc}
              alt=""
              aria-hidden="true"
              className="docs-title-banner mt-3 mb-5 block h-[270px] w-full object-cover"
            />
          </>
        ),
        pre: ({ children, ...props }) => {
          return (
            <CodeBlockWithCopy>
              <pre {...props}>{children}</pre>
            </CodeBlockWithCopy>
          );
        },
        a: ({ href, children }) => {
          const trimmed = href?.replace(/\.md$/, "") ?? "";
          const isRelative =
            trimmed.startsWith("./") || trimmed.startsWith("/docs/");
          if (isRelative) {
            const path = trimmed.startsWith("./")
              ? "/docs/" + trimmed.slice(2)
              : trimmed;
            const [pathname, hash] = path.split("#");
            const to = hash ? `${pathname}#${hash}` : pathname;
            return <Link to={to}>{children}</Link>;
          }
          return (
            <a href={href} target="_blank" rel="noopener noreferrer">
              {children}
            </a>
          );
        },
        h2: ({ children }) => {
          const id = getHeadingId(children);
          return <h2 id={id}>{children}</h2>;
        },
        h3: ({ children }) => {
          const id = getHeadingId(children);
          return <h3 id={id}>{children}</h3>;
        },
        table: ({ children }) => (
          <div className="docs-table-wrap">
            <table>{children}</table>
          </div>
        ),
        code: ({ className, children, ...props }) => {
          const match = /language-(\w+)/.exec(className || "");
          const langCode = match?.[1];
          if (langCode === "mermaid") {
            const chart = String(children).replace(/\n$/, "");
            return <MermaidBlock chart={chart} />;
          }
          return (
            <code className={className} {...props}>
              {children}
            </code>
          );
        },
        img: ({ src, alt, className }) => {
          const isVideo = /\.(mp4|webm|ogg|mov)(\?|$)/i.test(src ?? "");
          if (isVideo) {
            return (
              <video src={src ?? undefined} controls>
                {alt ?? t("docs.videoNotSupported")}
              </video>
            );
          }
          return (
            <ImageZoom src={src ?? ""} alt={alt ?? ""} className={className} />
          );
        },
      }}
    >
      {content}
    </ReactMarkdown>
  );
}
