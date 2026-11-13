import { useEffect, useState } from "react";
import mermaid from "mermaid";
import { CircleAlert } from "lucide-react";
import { useTheme } from "../../contexts/ThemeContext";
import styles from "./index.module.less";

let initializedTheme: "light" | "dark" | null = null;
let idCounter = 0;

function ensureMermaidInit(isDark: boolean) {
  const theme = isDark ? "dark" : "light";
  if (initializedTheme === theme) return;

  mermaid.initialize({
    startOnLoad: false,
    theme: "base",
    securityLevel: "loose",
    themeVariables: isDark
      ? {
          background: "#17120f",
          clusterBkg: "#211914",
          clusterBorder: "#7a4728",
          edgeLabelBackground: "#17120f",
          lineColor: "#d19a78",
          mainBkg: "#2b211c",
          nodeBorder: "#f36b21",
          primaryBorderColor: "#f36b21",
          primaryColor: "#2b211c",
          primaryTextColor: "#fff4ec",
          secondaryColor: "#35251c",
          tertiaryColor: "#241b17",
          textColor: "#fff4ec",
          titleColor: "#fff4ec",
        }
      : {
          background: "#fffaf6",
          clusterBkg: "#fff3e9",
          clusterBorder: "#e8793b",
          edgeLabelBackground: "#fffaf6",
          lineColor: "#9a5a35",
          mainBkg: "#fff7f0",
          nodeBorder: "#e35f18",
          primaryBorderColor: "#e35f18",
          primaryColor: "#fff7f0",
          primaryTextColor: "#3b2416",
          secondaryColor: "#fff0e4",
          tertiaryColor: "#fffaf6",
          textColor: "#3b2416",
          titleColor: "#3b2416",
        },
  });
  initializedTheme = theme;
}

interface MermaidCodeBlockProps {
  chart: string;
}

export function MermaidCodeBlock({ chart }: MermaidCodeBlockProps) {
  const { isDark } = useTheme();
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

    ensureMermaidInit(isDark);

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
  }, [isDark, trimmedChart]);

  if (error) {
    return (
      <div className={styles.mermaidError} role="alert">
        <CircleAlert aria-hidden="true" size={18} />
        <div>
          <strong>Unable to render diagram</strong>
          <span>{error}</span>
        </div>
      </div>
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
