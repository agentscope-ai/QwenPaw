import { useMemo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { MermaidBlock } from "./MermaidBlock";

interface MarkdownRendererProps {
  content: string;
}

function extractMermaidBlocks(content: string): React.ReactNode {
  // Split content by mermaid code blocks
  const parts: React.ReactNode[] = [];
  const regex = /```mermaid\n([\s\S]*?)```/g;
  let lastIndex = 0;
  let match;
  let key = 0;

  const trimmedContent = content.trim();

  while ((match = regex.exec(trimmedContent)) !== null) {
    // Text before the mermaid block
    if (match.index > lastIndex) {
      const textBefore = trimmedContent.slice(lastIndex, match.index);
      if (textBefore.trim()) {
        parts.push(
          <ReactMarkdown
            key={`md-${key++}`}
            remarkPlugins={[remarkGfm]}
            components={{
              h1: ({ children }) => (
                <h1
                  style={{
                    fontSize: 18,
                    fontWeight: 600,
                    marginBottom: 8,
                    marginTop: 16,
                  }}
                >
                  {children}
                </h1>
              ),
              h2: ({ children }) => (
                <h2
                  style={{
                    fontSize: 16,
                    fontWeight: 600,
                    marginBottom: 6,
                    marginTop: 14,
                  }}
                >
                  {children}
                </h2>
              ),
              h3: ({ children }) => (
                <h3
                  style={{
                    fontSize: 14,
                    fontWeight: 600,
                    marginBottom: 4,
                    marginTop: 12,
                  }}
                >
                  {children}
                </h3>
              ),
              p: ({ children }) => (
                <p style={{ marginBottom: 8, lineHeight: 1.6 }}>{children}</p>
              ),
              table: ({ children }) => (
                <table
                  style={{
                    borderCollapse: "collapse",
                    width: "100%",
                    marginBottom: 12,
                    fontSize: 13,
                  }}
                >
                  {children}
                </table>
              ),
              th: ({ children }) => (
                <th
                  style={{
                    border: "1px solid #d9d9d9",
                    padding: "6px 10px",
                    background: "#fafafa",
                    fontWeight: 600,
                  }}
                >
                  {children}
                </th>
              ),
              td: ({ children }) => (
                <td
                  style={{ border: "1px solid #d9d9d9", padding: "6px 10px" }}
                >
                  {children}
                </td>
              ),
              ul: ({ children }) => (
                <ul style={{ marginBottom: 8, paddingLeft: 20 }}>{children}</ul>
              ),
              ol: ({ children }) => (
                <ol style={{ marginBottom: 8, paddingLeft: 20 }}>{children}</ol>
              ),
              li: ({ children }) => (
                <li style={{ marginBottom: 2, lineHeight: 1.6 }}>{children}</li>
              ),
              blockquote: ({ children }) => (
                <blockquote
                  style={{
                    borderLeft: "3px solid #d9d9d9",
                    marginLeft: 0,
                    paddingLeft: 12,
                    color: "#666",
                    marginBottom: 8,
                  }}
                >
                  {children}
                </blockquote>
              ),
              code: ({ className, children, ...props }) => {
                const isInline = !className;
                if (isInline) {
                  return (
                    <code
                      style={{
                        background: "#f5f5f5",
                        padding: "1px 4px",
                        borderRadius: 3,
                        fontSize: 12,
                        fontFamily: "monospace",
                      }}
                      {...props}
                    >
                      {children}
                    </code>
                  );
                }
                return (
                  <code className={className} {...props}>
                    {children}
                  </code>
                );
              },
              pre: ({ children }) => (
                <pre
                  style={{
                    background: "#f5f5f5",
                    padding: 12,
                    borderRadius: 6,
                    overflow: "auto",
                    fontSize: 12,
                    marginBottom: 12,
                  }}
                >
                  {children}
                </pre>
              ),
            }}
          >
            {textBefore}
          </ReactMarkdown>,
        );
      }
    }

    // The mermaid block itself
    const chart = match[1].trim();
    parts.push(
      <div key={`mermaid-${key++}`} style={{ marginBottom: 12 }}>
        <MermaidBlock chart={chart} />
      </div>,
    );

    lastIndex = match.index + match[0].length;
  }

  // Remaining text after last mermaid block
  if (lastIndex < trimmedContent.length) {
    const textAfter = trimmedContent.slice(lastIndex);
    if (textAfter.trim()) {
      parts.push(
        <ReactMarkdown
          key={`md-${key++}`}
          remarkPlugins={[remarkGfm]}
          components={{
            h1: ({ children }) => (
              <h1
                style={{
                  fontSize: 18,
                  fontWeight: 600,
                  marginBottom: 8,
                  marginTop: 16,
                }}
              >
                {children}
              </h1>
            ),
            h2: ({ children }) => (
              <h2
                style={{
                  fontSize: 16,
                  fontWeight: 600,
                  marginBottom: 6,
                  marginTop: 14,
                }}
              >
                {children}
              </h2>
            ),
            h3: ({ children }) => (
              <h3
                style={{
                  fontSize: 14,
                  fontWeight: 600,
                  marginBottom: 4,
                  marginTop: 12,
                }}
              >
                {children}
              </h3>
            ),
            p: ({ children }) => (
              <p style={{ marginBottom: 8, lineHeight: 1.6 }}>{children}</p>
            ),
            table: ({ children }) => (
              <table
                style={{
                  borderCollapse: "collapse",
                  width: "100%",
                  marginBottom: 12,
                  fontSize: 13,
                }}
              >
                {children}
              </table>
            ),
            th: ({ children }) => (
              <th
                style={{
                  border: "1px solid #d9d9d9",
                  padding: "6px 10px",
                  background: "#fafafa",
                  fontWeight: 600,
                }}
              >
                {children}
              </th>
            ),
            td: ({ children }) => (
              <td style={{ border: "1px solid #d9d9d9", padding: "6px 10px" }}>
                {children}
              </td>
            ),
            ul: ({ children }) => (
              <ul style={{ marginBottom: 8, paddingLeft: 20 }}>{children}</ul>
            ),
            ol: ({ children }) => (
              <ol style={{ marginBottom: 8, paddingLeft: 20 }}>{children}</ol>
            ),
            li: ({ children }) => (
              <li style={{ marginBottom: 2, lineHeight: 1.6 }}>{children}</li>
            ),
            blockquote: ({ children }) => (
              <blockquote
                style={{
                  borderLeft: "3px solid #d9d9d9",
                  marginLeft: 0,
                  paddingLeft: 12,
                  color: "#666",
                  marginBottom: 8,
                }}
              >
                {children}
              </blockquote>
            ),
            code: ({ className, children, ...props }) => {
              const isInline = !className;
              if (isInline) {
                return (
                  <code
                    style={{
                      background: "#f5f5f5",
                      padding: "1px 4px",
                      borderRadius: 3,
                      fontSize: 12,
                      fontFamily: "monospace",
                    }}
                    {...props}
                  >
                    {children}
                  </code>
                );
              }
              return (
                <code className={className} {...props}>
                  {children}
                </code>
              );
            },
            pre: ({ children }) => (
              <pre
                style={{
                  background: "#f5f5f5",
                  padding: 12,
                  borderRadius: 6,
                  overflow: "auto",
                  fontSize: 12,
                  marginBottom: 12,
                }}
              >
                {children}
              </pre>
            ),
          }}
        >
          {textAfter}
        </ReactMarkdown>,
      );
    }
  }

  return parts.length > 0 ? parts : null;
}

export function MarkdownRenderer({ content }: MarkdownRendererProps) {
  const nodes = useMemo(() => extractMermaidBlocks(content), [content]);

  if (!content?.trim()) {
    return null;
  }

  return <div>{nodes}</div>;
}
