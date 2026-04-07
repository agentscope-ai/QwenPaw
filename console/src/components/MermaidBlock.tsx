import { useEffect, useState } from "react";
import mermaid from "mermaid";

let mermaidInitialized = false;

const MERMAID_RENDER_CACHE_MAX_ENTRIES = 100;

class BoundedMap<K, V> extends Map<K, V> {
  private readonly maxSize: number;

  constructor(maxSize: number) {
    super();
    this.maxSize = maxSize;
  }

  override set(key: K, value: V): this {
    if (!this.has(key) && this.size >= this.maxSize) {
      const firstKey = this.keys().next().value as K | undefined;
      if (firstKey !== undefined) {
        this.delete(firstKey);
      }
    }
    return super.set(key, value);
  }
}

const mermaidRenderCache = new BoundedMap<
  string,
  { svg: string; reservedHeight: number }
>(MERMAID_RENDER_CACHE_MAX_ENTRIES);

const MERMAID_MIN_HEIGHT = 100;

function ensureMermaidInit() {
  if (mermaidInitialized) return;
  mermaid.initialize({
    startOnLoad: false,
    theme: "neutral",
    securityLevel: "loose",
    fontFamily:
      '"DM Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
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
  const estimatedHeight = 60 + complexity * 16;
  return Math.max(MERMAID_MIN_HEIGHT, estimatedHeight);
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
          rendered.length > 0 ? estimatedHeight : 0,
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
        const orphan = document.getElementById("d" + id);
        orphan?.remove();
      });

    return () => {
      cancelled = true;
    };
  }, [trimmedChart]);

  if (error) {
    return (
      <pre
        style={{
          background: "#fff1f0",
          border: "1px solid #ffccc7",
          borderRadius: 6,
          padding: 8,
          color: "#ff4d4f",
          fontSize: 12,
          overflow: "auto",
        }}
      >
        <code>{chart}</code>
      </pre>
    );
  }

  return (
    <div
      style={{
        minHeight: isRendering ? `${reservedHeight}px` : undefined,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "#fafafa",
        borderRadius: 6,
        padding: 8,
        overflow: "auto",
      }}
    >
      {svg ? (
        <div dangerouslySetInnerHTML={{ __html: svg }} />
      ) : isRendering ? (
        <span style={{ color: "#999", fontSize: 12 }}>渲染中...</span>
      ) : null}
    </div>
  );
}
