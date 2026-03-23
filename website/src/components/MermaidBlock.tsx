import { useEffect, useRef, useState } from "react";
import mermaid from "mermaid";

let mermaidInitialized = false;

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

interface MermaidBlockProps {
  chart: string;
}

export function MermaidBlock({ chart }: MermaidBlockProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [svg, setSvg] = useState<string>("");
  const [error, setError] = useState<string>("");

  useEffect(() => {
    if (!chart.trim()) return;
    ensureMermaidInit();

    let cancelled = false;
    const id = `mermaid-${Date.now()}-${idCounter++}`;

    mermaid
      .render(id, chart.trim())
      .then(({ svg: rendered }) => {
        if (!cancelled) {
          setSvg(rendered);
          setError("");
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(String(err));
          setSvg("");
        }
        // mermaid.render may leave an orphan element on failure
        const orphan = document.getElementById("d" + id);
        orphan?.remove();
      });

    return () => {
      cancelled = true;
    };
  }, [chart]);

  if (error) {
    return (
      <pre className="mermaid-error">
        <code>{chart}</code>
      </pre>
    );
  }

  return (
    <div
      ref={containerRef}
      className="mermaid-diagram"
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  );
}
