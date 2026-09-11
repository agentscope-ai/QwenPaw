import { useId, useMemo, useRef, useState, type ReactNode } from "react";
import type { ComponentProps } from "@ant-design/x-markdown";
import katex from "katex";
import "katex/dist/katex.min.css";
import { Check, Code2, Copy, Download, Eye } from "lucide-react";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import {
  oneDark,
  oneLight,
} from "react-syntax-highlighter/dist/esm/styles/prism";
import { useTranslation } from "react-i18next";
import { useTheme } from "../../contexts/ThemeContext";
import { MermaidCodeBlock } from "../MermaidCodeBlock";
import styles from "./index.module.less";

type ViewMode = "preview" | "raw";
type RenderableLanguage = "latex" | "mermaid";
type RenderableCodeBlockProps = Partial<ComponentProps> & {
  children?: ReactNode;
};

const LANGUAGE_ALIASES: Record<string, RenderableLanguage> = {
  latex: "latex",
  math: "latex",
  mermaid: "mermaid",
  tex: "latex",
};

const LANGUAGE_EXTENSIONS: Record<string, string> = {
  bash: "sh",
  csharp: "cs",
  javascript: "js",
  kotlin: "kt",
  markdown: "md",
  mermaid: "mmd",
  python: "py",
  ruby: "rb",
  rust: "rs",
  shell: "sh",
  typescript: "ts",
  yaml: "yml",
  zsh: "sh",
};

function extractText(children: ReactNode): string {
  if (typeof children === "string") return children;
  if (typeof children === "number") return String(children);
  if (Array.isArray(children)) return children.map(extractText).join("");
  if (children && typeof children === "object" && "props" in children) {
    return extractText(
      (children as { props: { children?: ReactNode } }).props.children,
    );
  }
  return "";
}

function resolveLanguage(lang?: string, className?: string): string {
  const explicit = lang?.trim().split(/\s+/, 1)[0];
  const fromClassName = className?.match(/(?:^|\s)language-([^\s]+)/)?.[1];
  return (explicit || fromClassName || "").toLowerCase();
}

function downloadSource(source: string, language: string) {
  const extension =
    language === "latex" ? "tex" : LANGUAGE_EXTENSIONS[language] || language;
  const blob = new Blob([source], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `block.${extension}`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

function BlockActions({
  source,
  language,
}: {
  source: string;
  language: string;
}) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);
  const copyTimer = useRef<number>();

  const handleCopy = async () => {
    try {
      if (window.isSecureContext && navigator.clipboard) {
        await navigator.clipboard.writeText(source);
      } else {
        const textarea = document.createElement("textarea");
        textarea.value = source;
        textarea.style.cssText = "position:fixed;left:-9999px";
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand("copy");
        textarea.remove();
      }
      setCopied(true);
      window.clearTimeout(copyTimer.current);
      copyTimer.current = window.setTimeout(() => setCopied(false), 1200);
    } catch {
      setCopied(false);
    }
  };

  return (
    <div className={styles.actions}>
      <button
        aria-label={t("common.download")}
        onClick={() => downloadSource(source, language)}
        title={t("common.download")}
        type="button"
      >
        <Download aria-hidden="true" size={16} />
      </button>
      <button
        aria-label={copied ? t("common.copied") : t("common.copy")}
        onClick={() => void handleCopy()}
        title={copied ? t("common.copied") : t("common.copy")}
        type="button"
      >
        {copied ? (
          <Check aria-hidden="true" size={16} />
        ) : (
          <Copy aria-hidden="true" size={16} />
        )}
      </button>
    </div>
  );
}

function SourceCode({
  source,
  language,
}: {
  source: string;
  language: string;
}) {
  const { isDark } = useTheme();

  return (
    <SyntaxHighlighter
      codeTagProps={{ style: { background: "transparent" } }}
      customStyle={{
        background: "transparent",
        borderRadius: 0,
        fontSize: "13px",
        lineHeight: "1.65",
        margin: 0,
        padding: "18px 20px",
      }}
      language={language === "latex" ? "latex" : language || "text"}
      style={isDark ? oneDark : oneLight}
    >
      {source.replace(/\n$/, "")}
    </SyntaxHighlighter>
  );
}

function SourceOnlyBlock({
  source,
  language,
}: {
  source: string;
  language: string;
}) {
  return (
    <section
      className={`${styles.block} qwenpaw-code-block`}
      data-language={language || "text"}
    >
      <header className={styles.sourceHeader}>
        <span className={styles.language}>{language || "text"}</span>
        <BlockActions language={language || "text"} source={source} />
      </header>
      <div className={styles.panel}>
        <SourceCode language={language} source={source} />
      </div>
    </section>
  );
}

function LatexPreview({ source }: { source: string }) {
  const result = useMemo(() => {
    try {
      return {
        html: katex.renderToString(source.trim(), {
          displayMode: true,
          output: "htmlAndMathml",
          throwOnError: true,
        }),
        error: "",
      };
    } catch (error) {
      return {
        html: "",
        error: error instanceof Error ? error.message : String(error),
      };
    }
  }, [source]);

  if (result.error) {
    return (
      <div className={styles.error} role="alert">
        <Code2 aria-hidden="true" size={18} />
        <div>
          <strong>Unable to render formula</strong>
          <span>{result.error}</span>
        </div>
      </div>
    );
  }

  return (
    <div
      className={styles.latexPreview}
      dangerouslySetInnerHTML={{ __html: result.html }}
    />
  );
}

function RenderableBlock({
  source,
  language,
}: {
  source: string;
  language: RenderableLanguage;
}) {
  const { t } = useTranslation();
  const [view, setView] = useState<ViewMode>("preview");
  const tabGroupId = useId();
  const tabRefs = useRef<Record<ViewMode, HTMLButtonElement | null>>({
    preview: null,
    raw: null,
  });
  const previewTabId = `${tabGroupId}-preview-tab`;
  const rawTabId = `${tabGroupId}-raw-tab`;
  const panelId = `${tabGroupId}-panel`;

  const selectTab = (nextView: ViewMode) => {
    setView(nextView);
    tabRefs.current[nextView]?.focus();
  };

  const handleTabKeyDown = (
    event: React.KeyboardEvent<HTMLButtonElement>,
    currentView: ViewMode,
  ) => {
    let nextView: ViewMode | undefined;

    if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      nextView = currentView === "preview" ? "raw" : "preview";
    } else if (event.key === "Home") {
      nextView = "preview";
    } else if (event.key === "End") {
      nextView = "raw";
    }

    if (nextView) {
      event.preventDefault();
      selectTab(nextView);
    }
  };

  return (
    <section
      className={`${styles.block} qwenpaw-code-block`}
      data-language={language}
    >
      <header className={styles.header}>
        <span className={styles.language}>{language}</span>
        <div className={styles.tabs} role="tablist" aria-label="Block view">
          <button
            aria-controls={panelId}
            aria-selected={view === "preview"}
            className={view === "preview" ? styles.activeTab : styles.tab}
            id={previewTabId}
            onKeyDown={(event) => handleTabKeyDown(event, "preview")}
            onClick={() => setView("preview")}
            ref={(node) => {
              tabRefs.current.preview = node;
            }}
            role="tab"
            tabIndex={view === "preview" ? 0 : -1}
            type="button"
          >
            <Eye aria-hidden="true" size={14} />
            {t("common.preview")}
          </button>
          <button
            aria-controls={panelId}
            aria-selected={view === "raw"}
            className={view === "raw" ? styles.activeTab : styles.tab}
            id={rawTabId}
            onKeyDown={(event) => handleTabKeyDown(event, "raw")}
            onClick={() => setView("raw")}
            ref={(node) => {
              tabRefs.current.raw = node;
            }}
            role="tab"
            tabIndex={view === "raw" ? 0 : -1}
            type="button"
          >
            <Code2 aria-hidden="true" size={14} />
            {t("common.raw")}
          </button>
        </div>
        <BlockActions language={language} source={source} />
      </header>
      <div
        aria-labelledby={view === "preview" ? previewTabId : rawTabId}
        className={styles.panel}
        id={panelId}
        role="tabpanel"
      >
        {view === "preview" ? (
          language === "mermaid" ? (
            <MermaidCodeBlock chart={source} />
          ) : (
            <LatexPreview source={source} />
          )
        ) : (
          <SourceCode language={language} source={source} />
        )}
      </div>
    </section>
  );
}

export function RenderableCodeBlock(props: RenderableCodeBlockProps) {
  const {
    children,
    lang,
    block,
    className,
    domNode,
    streamStatus,
    ...htmlProps
  } = props;
  const language = resolveLanguage(lang, className);
  const renderableLanguage = LANGUAGE_ALIASES[language];

  void domNode;
  void streamStatus;

  if (!block && !className?.includes("language-")) {
    return (
      <code {...htmlProps} className={className}>
        {children}
      </code>
    );
  }

  if (!renderableLanguage) {
    return (
      <SourceOnlyBlock language={language} source={extractText(children)} />
    );
  }

  return (
    <RenderableBlock
      language={renderableLanguage}
      source={extractText(children)}
    />
  );
}
