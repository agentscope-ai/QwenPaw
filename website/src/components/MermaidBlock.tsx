import { useEffect, useState } from "react";
import mermaid from "mermaid";

let mermaidInitialized = false;
const mermaidRenderCache = new Map<
  string,
  {
    svg: string;
    reservedHeight: number;
  }
>();

const MERMAID_MIN_HEIGHT = 176;
const MERMAID_MAX_HEIGHT = 360;

function ensureMermaidInit() {
  if (mermaidInitialized) return;
  mermaid.initialize({
    startOnLoad: false,
    theme: "neutral",
    securityLevel: "loose",
    fontFamily: '"DM Sans", -apple-system, BlinkMacSystemFont, sans-serif',
  });
  mermaidInitialized = true;
}

let idCounter = 0;

function estimateMermaidHeight(chart: string): number {
  const lines = chart
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
  const signalLines = lines.filter(
    (line) =>
      /(?:-->|---|==>|-.->|===|~~~)/.test(line) ||
      /\[[^\]]+\]|\([^)]+\)|\{[^}]+\}/.test(line) ||
      /^(?:subgraph|classDef|class|style|click)\b/.test(line),
  ).length;
  const complexity = Math.max(lines.length, signalLines);
  return Math.max(
    MERMAID_MIN_HEIGHT,
    Math.min(MERMAID_MAX_HEIGHT, 88 + complexity * 18),
  );
}

function extractSvgHeight(svg: string): number | null {
  const doc = new DOMParser().parseFromString(svg, "image/svg+xml");
  const svgEl = doc.querySelector("svg");

  if (!svgEl) return null;

  const viewBox = svgEl.getAttribute("viewBox");
  if (viewBox) {
    const parts = viewBox
      .trim()
      .split(/\s+/)
      .map((value) => Number(value));
    const height = parts[3];
    if (Number.isFinite(height) && height > 0) {
      return Math.round(height);
    }
  }

  const heightAttr = svgEl.getAttribute("height");
  if (!heightAttr) return null;

  const height = Number.parseFloat(heightAttr);
  return Number.isFinite(height) && height > 0 ? Math.round(height) : null;
}

interface MermaidBlockProps {
  chart: string;
}

export function MermaidBlock({ chart }: MermaidBlockProps) {
  const trimmedChart = chart.trim();
  const cachedEntry = mermaidRenderCache.get(trimmedChart);
  const [svg, setSvg] = useState<string>(cachedEntry?.svg ?? "");
  const [error, setError] = useState<string>("");
  const [isRendering, setIsRendering] = useState<boolean>(
    !!trimmedChart && !cachedEntry,
  );
  const [reservedHeight, setReservedHeight] = useState<number>(
    cachedEntry?.reservedHeight ?? estimateMermaidHeight(trimmedChart),
  );

  useEffect(() => {
    if (!trimmedChart) {
      setSvg("");
      setError("");
      setIsRendering(false);
      setReservedHeight(MERMAID_MIN_HEIGHT);
      return;
    }

    ensureMermaidInit();

    const cached = mermaidRenderCache.get(trimmedChart);
    if (cached) {
      setSvg(cached.svg);
      setError("");
      setIsRendering(false);
      setReservedHeight(cached.reservedHeight);
      return;
    }

    let cancelled = false;
    const estimatedHeight = estimateMermaidHeight(trimmedChart);
    const id = `mermaid-${Date.now()}-${idCounter++}`;
    setSvg("");
    setError("");
    setIsRendering(true);
    setReservedHeight(estimatedHeight);

    mermaid
      .render(id, trimmedChart)
      .then(({ svg: rendered }) => {
        const reserved = Math.max(
          estimatedHeight,
          extractSvgHeight(rendered) ?? 0,
        );
        mermaidRenderCache.set(trimmedChart, {
          svg: rendered,
          reservedHeight: reserved,
        });
        if (!cancelled) {
          setSvg(rendered);
          setError("");
          setIsRendering(false);
          setReservedHeight(reserved);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(String(err));
          setSvg("");
          setIsRendering(false);
          setReservedHeight(estimatedHeight);
        }
        // mermaid.render may leave an orphan element on failure
        const orphan = document.getElementById("d" + id);
        orphan?.remove();
      });

    return () => {
      cancelled = true;
    };
  }, [trimmedChart]);

  if (error) {
    return (
      <pre className="mermaid-error">
        <code>{chart}</code>
      </pre>
    );
  }

  return (
    <div
      className={`mermaid-diagram${isRendering ? " is-loading" : ""}`}
      style={{ minHeight: `${reservedHeight}px` }}
    >
      {isRendering ? (
        <div className="mermaid-diagram__placeholder" aria-hidden="true" />
      ) : null}
      {svg ? (
        <div
          className="mermaid-diagram__content"
          dangerouslySetInnerHTML={{ __html: svg }}
        />
      ) : null}
    </div>
  );
}
