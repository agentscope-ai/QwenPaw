import { useLayoutEffect, useRef, useState } from "react";

/**
 * Copy-overlay rendering layer identical to the final render.
 *
 * Shares the exact geometry formulas (border/corner radius/tail/emoji/font-size
 * shrinking/per-character wrapping) with the backend deterministic renderer in
 * `services/media_files/overlay.py`, so the pet_os bubbles and
 * interview_summary captions in the live preview look the same as in the final
 * composed video.
 */

const VIBE_EMOJI: Record<string, string> = {
  action: "😾",
  surprise: "🙀",
  curious: "🐱",
  chill: "😺",
};

// Matches the backend _find_cjk_font's PingFang preference; non-macOS falls
// back to same-family CJK sans fonts.
const CJK_FONT_STACK =
  '"PingFang SC", "Hiragino Sans GB", "Noto Sans CJK SC", "Microsoft YaHei", sans-serif';

let sharedMeasureContext: CanvasRenderingContext2D | null = null;

function measureWidth(text: string, fontSize: number): number {
  if (!sharedMeasureContext) {
    sharedMeasureContext = document.createElement("canvas").getContext("2d");
  }
  if (!sharedMeasureContext) return text.length * fontSize;
  sharedMeasureContext.font = `${fontSize}px ${CJK_FONT_STACK}`;
  return sharedMeasureContext.measureText(text).width;
}

/** Per-character greedy wrapping, identical to the PIL renderer. */
function wrapGreedy(
  text: string,
  fontSize: number,
  availableWidth: number,
): string[] {
  const lines: string[] = [];
  let current = "";
  for (const character of text.trim()) {
    const candidate = current + character;
    if (current && measureWidth(candidate, fontSize) > availableWidth) {
      lines.push(current);
      current = character;
    } else {
      current = candidate;
    }
  }
  if (current) lines.push(current);
  return lines;
}

function useBoxSize(ref: React.RefObject<HTMLDivElement>) {
  const [size, setSize] = useState<{ width: number; height: number } | null>(
    null,
  );
  useLayoutEffect(() => {
    const node = ref.current;
    if (!node) return;
    const update = () =>
      setSize({ width: node.clientWidth, height: node.clientHeight });
    update();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(update);
    observer.observe(node);
    return () => observer.disconnect();
  }, [ref]);
  return size;
}

const lineHeightOf = (fontSize: number) => Math.round(fontSize * 1.15) + 2;

/** Mirrors backend _render_placed_pet_os_box: white bubble with black border +
 * tail + vibe emoji. */
export function PetOsBubble({
  text,
  vibe,
  stageWidth,
}: {
  text: string;
  vibe: string;
  stageWidth: number;
}) {
  const boxRef = useRef<HTMLDivElement>(null);
  const size = useBoxSize(boxRef);
  let content: React.ReactNode = null;
  if (size && size.width > 4 && size.height > 4) {
    const { width, height } = size;
    const border = Math.max(2, Math.round(Math.min(width, height) * 0.018));
    const padding = Math.max(5, Math.round(Math.min(width, height) * 0.06));
    const tailHeight = Math.max(8, Math.round(height * 0.09));
    const emojiSize = Math.max(18, Math.round(height * 0.2));
    const emojiGap = Math.max(2, Math.round(height * 0.025));
    const bubbleHeight = Math.max(
      16,
      height - tailHeight - emojiSize - emojiGap - border,
    );
    const bubbleRight = Math.max(border + 2, width - border - 1);
    const radius = Math.max(
      5,
      Math.round(Math.min(width, bubbleHeight) * 0.09),
    );
    const tailX = Math.min(
      bubbleRight - tailHeight * 2,
      Math.max(border + tailHeight * 2, Math.round(width * 0.28)),
    );
    const tailTip: [number, number] = [
      tailX - Math.round(tailHeight * 0.55),
      bubbleHeight + tailHeight,
    ];
    const availableWidth = Math.max(1, width - padding * 2 - border * 2);
    const availableHeight = Math.max(
      1,
      bubbleHeight - padding * 2 - border * 2,
    );
    let fontSize = Math.max(
      10,
      Math.min(
        Math.round((stageWidth / 1280) * 30),
        Math.round(availableHeight / 3.5),
      ),
    );
    let lines = wrapGreedy(text, fontSize, availableWidth);
    while (
      fontSize > 10 &&
      lines.length * lineHeightOf(fontSize) - 2 > availableHeight
    ) {
      fontSize -= 1;
      lines = wrapGreedy(text, fontSize, availableWidth);
    }
    const lineHeight = lineHeightOf(fontSize);
    const textHeight = lines.length * lineHeight - 2;
    const textTop =
      border + padding + Math.max(0, (availableHeight - textHeight) / 2);
    const emojiX = Math.max(
      0,
      Math.min(width - emojiSize, tailTip[0] - Math.floor(emojiSize / 2)),
    );
    const emojiY = Math.min(height - emojiSize, tailTip[1] + emojiGap);
    content = (
      <svg
        viewBox={`0 0 ${width} ${height}`}
        width="100%"
        height="100%"
        aria-hidden
      >
        <rect
          x={border}
          y={border}
          width={bubbleRight - border}
          height={bubbleHeight - border}
          rx={radius}
          fill="#ffffff"
          fillOpacity={238 / 255}
          stroke="#141414"
          strokeWidth={border}
        />
        <polygon
          points={`${tailX},${bubbleHeight} ${tailTip[0]},${tailTip[1]} ${
            tailX + tailHeight
          },${bubbleHeight}`}
          fill="#ffffff"
        />
        <line
          x1={tailX}
          y1={bubbleHeight}
          x2={tailTip[0]}
          y2={tailTip[1]}
          stroke="#000000"
          strokeWidth={border}
        />
        <line
          x1={tailTip[0]}
          y1={tailTip[1]}
          x2={tailX + tailHeight}
          y2={bubbleHeight}
          stroke="#000000"
          strokeWidth={border}
        />
        {lines.map((line, index) => (
          <text
            key={index}
            x={border + padding}
            y={textTop + index * lineHeight + fontSize * 0.86}
            fontSize={fontSize}
            fontFamily={CJK_FONT_STACK}
            fill="#111111"
          >
            {line}
          </text>
        ))}
        <text
          x={emojiX}
          y={emojiY + emojiSize * 0.86}
          fontSize={emojiSize}
          fontFamily='"Apple Color Emoji", "Noto Color Emoji", sans-serif'
        >
          {VIBE_EMOJI[vibe] ?? VIBE_EMOJI.chill}
        </text>
      </svg>
    );
  }
  return (
    <div ref={boxRef} data-overlay-copy="pet_os" className="h-full w-full">
      {content}
    </div>
  );
}

/** Mirrors backend _render_placed_text_box(bubble=False): white text with black
 * outline, truncated to two centered lines. */
export function InterviewSummaryBox({ text }: { text: string }) {
  const boxRef = useRef<HTMLDivElement>(null);
  const size = useBoxSize(boxRef);
  let content: React.ReactNode = null;
  if (size && size.width > 4 && size.height > 4) {
    const { width, height } = size;
    const padding = Math.max(3, Math.round(Math.min(width, height) * 0.1));
    const fontSize = Math.max(
      10,
      Math.min(
        Math.round(height * 0.42),
        Math.round((width / Math.max(4, text.length)) * 1.55),
      ),
    );
    const availableWidth = Math.max(1, width - padding * 2);
    const lines = wrapGreedy(text, fontSize, availableWidth).slice(0, 2);
    const lineHeight = lineHeightOf(fontSize);
    const textHeight = lines.length * lineHeight - 2;
    const textTop = Math.max(0, (height - textHeight) / 2);
    const strokeWidth = Math.max(1, Math.round(fontSize * 0.08));
    content = (
      <svg
        viewBox={`0 0 ${width} ${height}`}
        width="100%"
        height="100%"
        aria-hidden
      >
        {lines.map((line, index) => (
          <text
            key={index}
            x={width / 2}
            y={textTop + index * lineHeight + fontSize * 0.86}
            textAnchor="middle"
            fontSize={fontSize}
            fontFamily={CJK_FONT_STACK}
            fill="#ffffff"
            stroke="#000000"
            strokeWidth={strokeWidth}
            style={{ paintOrder: "stroke" }}
          >
            {line}
          </text>
        ))}
      </svg>
    );
  }
  return (
    <div
      ref={boxRef}
      data-overlay-copy="interview_summary"
      className="h-full w-full"
    >
      {content}
    </div>
  );
}
