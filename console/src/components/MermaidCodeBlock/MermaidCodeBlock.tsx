import { useEffect, useState } from "react";
import mermaid from "mermaid";
import styles from "./index.module.less";

let mermaidInitialized = false;
let idCounter = 0;

function ensureMermaidInit() {
  if (mermaidInitialized) return;
  mermaid.initialize({
    startOnLoad: false,
    theme: "neutral",
    securityLevel: "loose",
  });
  mermaidInitialized = true;
}

interface MermaidCodeBlockProps {
  chart: string;
}

export function MermaidCodeBlock({ chart }: MermaidCodeBlockProps) {
  const trimmedChart = chart.trim();
  const [svg, setSvg] = useState<string>("");
  const [error, setError] = useState<string>("");
  const [isRendering, setIsRendering] = useState<boolean>(!!trimmedChart);

  useEffect(() => {
    if (!trimmedChart) {
      setSvg("");
      setError("");
      setIsRendering(false);
      return;
    }

    ensureMermaidInit();

    let cancelled = false;
    const id = `mermaid-${Date.now()}-${idCounter++}`;
    setSvg("");
    setError("");
    setIsRendering(true);

    mermaid
      .render(id, trimmedChart)
      .then(({ svg: rendered }) => {
        if (!cancelled) {
          setSvg(rendered);
          setError("");
          setIsRendering(false);
        }
      })
      .catch((renderError) => {
        if (!cancelled) {
          setError(String(renderError));
          setSvg("");
          setIsRendering(false);
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
      <pre className={styles.mermaidError}>
        <code>{chart}</code>
      </pre>
    );
  }

  return (
    <div
      className={`${styles.mermaidDiagram}${
        isRendering ? ` ${styles.isLoading}` : ""
      }`}
    >
      {isRendering ? (
        <div className={styles.placeholder} aria-hidden="true">
          Loading diagram…
        </div>
      ) : null}
      {svg ? (
        <div
          className={styles.content}
          dangerouslySetInnerHTML={{ __html: svg }}
        />
      ) : null}
    </div>
  );
}
