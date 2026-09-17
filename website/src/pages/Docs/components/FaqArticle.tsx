import { useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import rehypeRaw from "rehype-raw";
import { ChevronDown } from "lucide-react";
import { ImageZoom } from "@/components/ImageZoom";
import { parseFaqContent } from "../markdown";
import { createHeadingIdFactory } from "./DocMarkdown";

interface FaqArticleProps {
  content: string;
  bannerSrc: string;
}

/** Renders the FAQ doc as an accordion list. */
export function FaqArticle({ content, bannerSrc }: FaqArticleProps) {
  const faqData = useMemo(() => parseFaqContent(content), [content]);
  const [openFaqSet, setOpenFaqSet] = useState<Set<number>>(() => new Set([0]));
  const getHeadingId = createHeadingIdFactory();

  return (
    <>
      {faqData.intro && (
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
            h2: ({ children }) => {
              const id = getHeadingId(children);
              return <h2 id={id}>{children}</h2>;
            },
            h3: ({ children }) => {
              const id = getHeadingId(children);
              return <h3 id={id}>{children}</h3>;
            },
            img: ({ src, alt, className }) => {
              return (
                <ImageZoom
                  src={src ?? ""}
                  alt={alt ?? ""}
                  className={className}
                />
              );
            },
          }}
        >
          {faqData.intro}
        </ReactMarkdown>
      )}
      <div className="mt-4">
        {faqData.items.map((item, idx) => {
          const opened = openFaqSet.has(idx);
          const questionId = getHeadingId(item.question);
          return (
            <section
              key={`${item.question}-${idx}`}
              id={questionId}
              className="mb-3 rounded-lg border border-border bg-(--surface)"
            >
              <button
                type="button"
                onClick={() => {
                  setOpenFaqSet((prev) => {
                    const next = new Set(prev);
                    if (next.has(idx)) next.delete(idx);
                    else next.add(idx);
                    return next;
                  });
                }}
                className="flex w-full items-center justify-between gap-3 bg-transparent px-4 py-4 text-left text-base font-semibold text-(--text)"
                aria-expanded={opened}
              >
                <span>{item.question}</span>
                <ChevronDown
                  size={16}
                  className={[
                    "shrink-0 transition-transform duration-150 ease-in-out",
                    opened ? "rotate-180" : "rotate-0",
                  ].join(" ")}
                />
              </button>
              {opened && (
                <div className="docs-faq-answer border-t border-border px-4 pb-2 pt-3 *:first:mt-0 *:last:mb-0">
                  <ReactMarkdown
                    remarkPlugins={[remarkGfm]}
                    rehypePlugins={[rehypeRaw, rehypeHighlight]}
                    components={{
                      img: ({ src, alt, className }) => {
                        return (
                          <ImageZoom
                            src={src ?? ""}
                            alt={alt ?? ""}
                            className={className}
                          />
                        );
                      },
                    }}
                  >
                    {item.answer}
                  </ReactMarkdown>
                </div>
              )}
            </section>
          );
        })}
      </div>
    </>
  );
}
