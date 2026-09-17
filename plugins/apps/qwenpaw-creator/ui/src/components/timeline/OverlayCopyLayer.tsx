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
 * tail + vibe emoji. Auto-sizes to fit text content, centered in the location
 * box. */
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
    const { width: containerW, height: containerH } = size;
    const targetFontSize = Math.max(10, Math.round((stageWidth / 1280) * 30));
    const maxBubbleW = Math.round(containerW * 0.9);

    const tailHeight = Math.max(8, Math.round(containerH * 0.09));
    const emojiSize = Math.max(18, Math.round(containerH * 0.2));
    const emojiGap = Math.max(2, Math.round(containerH * 0.025));

    let fontSize = targetFontSize;
    let lines: string[] = [];
    let textW = 0;
    let textH = 0;
    let border = 2;
    let padding = 5;
    let bubbleW = 0;
    let bubbleH = 0;
    let bubbleBodyH = 0;

    while (fontSize >= 10) {
      border = Math.max(2, Math.round(containerH * 0.018));
      padding = Math.max(5, Math.round(containerH * 0.06));
      const availW = Math.max(1, maxBubbleW - padding * 2 - border * 2);
      lines = wrapGreedy(text, fontSize, availW);
      textW = Math.max(...lines.map((l) => measureWidth(l, fontSize)), 1);
      textH = lines.length * lineHeightOf(fontSize) - 2;
      bubbleW = Math.min(textW + padding * 2 + border * 2, maxBubbleW);
      bubbleBodyH = textH + padding * 2 + border * 2;
      bubbleH = bubbleBodyH + Math.max(tailHeight, emojiSize + emojiGap);
      if (
        textW + padding * 2 + border * 2 <= maxBubbleW &&
        bubbleH <= containerH
      )
        break;
      fontSize -= 1;
    }

    const bubbleX = Math.max(0, (containerW - bubbleW) / 2);
    const bubbleY = Math.max(0, (containerH - bubbleH) / 2);

    const lineHeight = lineHeightOf(fontSize);
    const actualTextH = lines.length * lineHeight - 2;
    const textAreaH = bubbleBodyH - border * 2 - padding * 2;
    const textTop =
      bubbleY + border + padding + Math.max(0, (textAreaH - actualTextH) / 2);

    const bubbleBottom = bubbleY + bubbleBodyH - border / 2;
    const bubbleRight = bubbleX + bubbleW - border;
    const radius = Math.max(
      5,
      Math.round(Math.min(bubbleW, bubbleBodyH) * 0.09),
    );

    const tailRelX = Math.min(
      bubbleW - border - tailHeight * 2,
      Math.max(border + tailHeight * 2, Math.round(bubbleW * 0.28)),
    );
    const tailX = bubbleX + tailRelX;
    const tailTip: [number, number] = [
      tailX - Math.round(tailHeight * 0.55),
      bubbleBottom + tailHeight,
    ];

    const emojiX = Math.max(
      bubbleX,
      Math.min(
        bubbleX + bubbleW - emojiSize,
        tailTip[0] - Math.floor(emojiSize / 2),
      ),
    );
    const emojiY = Math.min(containerH - emojiSize, bubbleBottom + emojiGap);

    content = (
      <svg
        viewBox={`0 0 ${containerW} ${containerH}`}
        width="100%"
        height="100%"
        aria-hidden
      >
        <rect
          x={bubbleX + border / 2}
          y={bubbleY + border / 2}
          width={bubbleW - border}
          height={bubbleBodyH - border}
          rx={radius}
          fill="#ffffff"
          fillOpacity={238 / 255}
          stroke="#141414"
          strokeWidth={border}
        />
        <polygon
          points={`${tailX},${bubbleBottom} ${tailTip[0]},${tailTip[1]} ${
            tailX + tailHeight
          },${bubbleBottom}`}
          fill="#ffffff"
        />
        <line
          x1={tailX}
          y1={bubbleBottom}
          x2={tailTip[0]}
          y2={tailTip[1]}
          stroke="#000000"
          strokeWidth={border}
        />
        <line
          x1={tailTip[0]}
          y1={tailTip[1]}
          x2={tailX + tailHeight}
          y2={bubbleBottom}
          stroke="#000000"
          strokeWidth={border}
        />
        {lines.map((line, index) => (
          <text
            key={index}
            x={bubbleX + border + padding}
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

/** Mirrors backend _render_placed_text_box(bubble=False): auto-sized dark box
 * with white text and black outline, matching the final render. */
export function InterviewSummaryBox({
  text,
  stageWidth,
  stageHeight,
}: {
  text: string;
  stageWidth: number;
  stageHeight: number;
}) {
  if (stageWidth < 4 || stageHeight < 4) return null;
  const targetFontSize = Math.max(12, Math.round((stageWidth / 1280) * 34));
  const maxBoxW = Math.round(stageWidth * 0.7);
  const maxBoxH = Math.round(stageHeight * 0.25);
  const padBase = Math.max(8, Math.round(stageWidth * 0.01));
  const lines = wrapGreedy(text, targetFontSize, maxBoxW - padBase * 2);
  const lineHeight = lineHeightOf(targetFontSize);
  const textW = Math.max(
    ...lines.map((l) => measureWidth(l, targetFontSize)),
    1,
  );
  const textH = lines.length * lineHeight - 2;
  let boxW = Math.min(textW + padBase * 2, maxBoxW);
  let boxH = Math.min(textH + padBase * 2, maxBoxH);
  let fontSize = targetFontSize;
  if (textW + padBase * 2 > maxBoxW || textH + padBase * 2 > maxBoxH) {
    const s = Math.min(
      maxBoxW / Math.max(textW + padBase * 2, 1),
      maxBoxH / Math.max(textH + padBase * 2, 1),
    );
    fontSize = Math.max(10, Math.round(targetFontSize * s));
    const reLines = wrapGreedy(text, fontSize, maxBoxW - padBase * 2).slice(
      0,
      2,
    );
    const reW = Math.max(...reLines.map((l) => measureWidth(l, fontSize)), 1);
    const reH = reLines.length * lineHeightOf(fontSize) - 2;
    boxW = Math.min(reW + padBase * 2, maxBoxW);
    boxH = Math.min(reH + padBase * 2, maxBoxH);
    lines.length = 0;
    lines.push(...reLines);
  }
  const padding = Math.max(8, Math.round(Math.min(boxW, boxH) * 0.12));
  const border = Math.max(2, Math.round(Math.min(boxW, boxH) * 0.04));
  const radius = Math.max(4, Math.round(Math.min(boxW, boxH) * 0.18));
  const lh = lineHeightOf(fontSize);
  const totalH = lines.length * lh - 2;
  const textTop = Math.max(0, (boxH - totalH) / 2);
  const strokeWidth = Math.max(1, Math.round(fontSize * 0.08));
  return (
    <div className="flex h-full w-full items-center justify-center">
      <svg
        viewBox={`0 0 ${boxW} ${boxH}`}
        width={boxW}
        height={boxH}
        aria-hidden
      >
        <rect
          x={0}
          y={0}
          width={boxW - 1}
          height={boxH - 1}
          rx={radius}
          fill="rgba(0,0,0,0.6)"
          stroke="rgba(255,255,255,0.2)"
          strokeWidth={border}
        />
        {lines.map((line, index) => (
          <text
            key={index}
            x={boxW / 2}
            y={textTop + index * lh + fontSize * 0.86}
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
    </div>
  );
}
