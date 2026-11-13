import { useLayoutEffect, useRef, useState } from "react";
import {
  createElement,
  type SyntaxHighlighterProps,
} from "react-syntax-highlighter";

type Rows = Parameters<NonNullable<SyntaxHighlighterProps["renderer"]>>[0];
const LINE_HEIGHT = 13 * 1.65;
export const CODE_ROW_LIMIT = 192;
const OVERSCAN = 16;
const SCROLLER =
  '[data-history-message-window], [class*="message-list-bubble-scroll"]';

/** Keep Prism's whole-document tokens, but mount only visible code lines. */
export function CodeRowWindow({ rows, stylesheet, useInlineStyles }: Rows) {
  const root = useRef<HTMLSpanElement>(null);
  const [start, setStart] = useState(0);
  useLayoutEffect(() => {
    const element = root.current;
    const scroll = element?.closest<HTMLElement>(SCROLLER);
    if (!element || !scroll) return;
    let frame = 0;
    const update = () => {
      frame = 0;
      const top =
        scroll.getBoundingClientRect().top -
        element.getBoundingClientRect().top;
      setStart(
        Math.max(
          0,
          Math.min(
            rows.length - CODE_ROW_LIMIT,
            Math.floor(top / LINE_HEIGHT) - OVERSCAN,
          ),
        ),
      );
    };
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(update);
    };
    const resize = new ResizeObserver(schedule);
    resize.observe(scroll);
    resize.observe(element);
    scroll.addEventListener("scroll", schedule, { passive: true });
    update();
    return () => {
      cancelAnimationFrame(frame);
      resize.disconnect();
      scroll.removeEventListener("scroll", schedule);
    };
  }, [rows.length]);
  const first = Math.min(start, Math.max(0, rows.length - CODE_ROW_LIMIT));
  return (
    <span
      ref={root}
      data-code-row-window="true"
      style={{
        display: "block",
        position: "relative",
        height: rows.length * LINE_HEIGHT,
      }}
    >
      {rows.slice(first, first + CODE_ROW_LIMIT).map((node, offset) => (
        <span
          key={first + offset}
          data-code-line={first + offset + 1}
          style={{
            position: "absolute",
            top: (first + offset) * LINE_HEIGHT,
            left: 0,
            height: LINE_HEIGHT,
            whiteSpace: "pre",
            lineHeight: `${LINE_HEIGHT}px`,
          }}
        >
          {createElement({
            node,
            stylesheet,
            useInlineStyles,
            key: first + offset,
          })}
        </span>
      ))}
    </span>
  );
}
