/**
 * FilePreview – renders a non-code file in the editor area.
 *
 * Supported types (auto-detected by extension):
 *   • image  – PNG / JPG / GIF / WebP / SVG / ICO / BMP
 *   • pdf    – inline <embed>
 *   • markdown – react-markdown with GFM
 *   • html   – read-only sandboxed document
 *   • csv    – parsed table
 */

import { ExternalLink, FileWarning, LoaderCircle } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";
import { workspaceApi } from "../../api/modules/workspace";
import { buildAuthHeaders } from "../../api/authHeaders";
import type { WorkspaceRoot } from "../../features/files-workspace/types";
import { ExternalMarkdownLink } from "../../components/Markdown/externalLinkComponents";
import { useAgentStore } from "../../stores/agentStore";
import { openHtmlFile } from "../../utils/openHtmlFile";
import { parseMarkdownFrontmatter } from "../../utils/markdown";
import styles from "./FilePreview.module.less";

// ---------------------------------------------------------------------------
// Type detection
// ---------------------------------------------------------------------------

const IMAGE_EXTS = new Set([
  "png",
  "jpg",
  "jpeg",
  "gif",
  "webp",
  "svg",
  "ico",
  "bmp",
]);

export type PreviewType =
  | "image"
  | "pdf"
  | "markdown"
  | "html"
  | "csv"
  | "none";

export function getPreviewType(filePath: string): PreviewType {
  const ext = filePath.split(".").pop()?.toLowerCase() ?? "";
  if (IMAGE_EXTS.has(ext)) return "image";
  if (ext === "pdf") return "pdf";
  if (ext === "md" || ext === "mdx") return "markdown";
  if (ext === "html" || ext === "htm") return "html";
  if (ext === "csv") return "csv";
  return "none";
}

export function isPreviewable(filePath: string): boolean {
  return getPreviewType(filePath) !== "none";
}

// ---------------------------------------------------------------------------
// CSV parser (no external dep)
// ---------------------------------------------------------------------------

function parseCsv(raw: string): string[][] {
  const lines = raw.trimEnd().split(/\r?\n/);
  return lines.map((line) => {
    const cells: string[] = [];
    let cur = "";
    let inQuote = false;
    for (let i = 0; i < line.length; i++) {
      const ch = line[i];
      if (ch === '"') {
        if (inQuote && line[i + 1] === '"') {
          cur += '"';
          i++;
        } else {
          inQuote = !inQuote;
        }
      } else if (ch === "," && !inQuote) {
        cells.push(cur);
        cur = "";
      } else {
        cur += ch;
      }
    }
    cells.push(cur);
    return cells;
  });
}

// ---------------------------------------------------------------------------
// Authenticated blob loader — browser-native <img>/<embed> won't send
// X-Agent-Id, so we fetch with headers and create an object URL.
//
// ---------------------------------------------------------------------------

function useAuthBlobUrl(
  filePath: string,
  chatId?: string,
  binaryUrl?: string,
  root?: WorkspaceRoot,
): {
  blobUrl: string | null;
  loading: boolean;
  failed: boolean;
} {
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const selectedAgent = useAgentStore((state) => state.selectedAgent);

  useEffect(() => {
    let revoked = false;
    setLoading(true);
    setFailed(false);

    const loadBlob = async (): Promise<Blob | null> => {
      const url = binaryUrl ?? workspaceApi.getFileDownloadUrl(filePath, root);
      const res = await fetch(url, {
        headers: {
          ...buildAuthHeaders(),
          ...(chatId ? { "X-Chat-Id": chatId } : {}),
        },
      });
      if (!res.ok) throw new Error(`${res.status}`);
      return res.blob();
    };

    loadBlob()
      .then((blob) => {
        if (revoked || !blob) return;
        setBlobUrl(URL.createObjectURL(blob));
        setLoading(false);
      })
      .catch(() => {
        if (!revoked) {
          setBlobUrl(null);
          setLoading(false);
          setFailed(true);
        }
      });

    return () => {
      revoked = true;
      setBlobUrl((prev) => {
        if (prev) URL.revokeObjectURL(prev);
        return null;
      });
    };
  }, [binaryUrl, chatId, filePath, root, selectedAgent]);

  return { blobUrl, loading, failed };
}

// ---------------------------------------------------------------------------
// Sub-renderers
// ---------------------------------------------------------------------------

function ImagePreview({
  filePath,
  chatId,
  binaryUrl,
  root,
}: {
  filePath: string;
  chatId?: string;
  binaryUrl?: string;
  root?: WorkspaceRoot;
}) {
  const { t } = useTranslation();
  const { blobUrl, loading, failed } = useAuthBlobUrl(
    filePath,
    chatId,
    binaryUrl,
    root,
  );
  if (loading) {
    return (
      <PreviewStatus icon={<LoaderCircle size={18} />} spinning>
        {t("common.loading")}
      </PreviewStatus>
    );
  }
  if (failed || !blobUrl) {
    return (
      <PreviewStatus icon={<FileWarning size={18} />}>
        {t("files.loadFailed")}
      </PreviewStatus>
    );
  }
  return (
    <div className={styles.imageWrap}>
      <img
        src={blobUrl}
        alt={filePath.split("/").pop()}
        className={styles.image}
      />
    </div>
  );
}

function PdfPreview({
  filePath,
  chatId,
  binaryUrl,
  root,
}: {
  filePath: string;
  chatId?: string;
  binaryUrl?: string;
  root?: WorkspaceRoot;
}) {
  const { t } = useTranslation();
  const { blobUrl, loading, failed } = useAuthBlobUrl(
    filePath,
    chatId,
    binaryUrl,
    root,
  );
  if (loading) {
    return (
      <PreviewStatus icon={<LoaderCircle size={18} />} spinning>
        {t("common.loading")}
      </PreviewStatus>
    );
  }
  if (failed || !blobUrl) {
    return (
      <PreviewStatus icon={<FileWarning size={18} />}>
        {t("files.loadFailed")}
      </PreviewStatus>
    );
  }
  return (
    <embed
      src={blobUrl}
      type="application/pdf"
      className={styles.pdfEmbed}
      title={filePath.split("/").pop()}
    />
  );
}

function PreviewStatus({
  children,
  icon,
  spinning = false,
}: {
  children: React.ReactNode;
  icon: React.ReactNode;
  spinning?: boolean;
}) {
  return (
    <div className={styles.previewStatus}>
      <span className={spinning ? styles.spinning : undefined}>{icon}</span>
      <span>{children}</span>
    </div>
  );
}

const markdownComponents = {
  a: ExternalMarkdownLink,
  pre({ children }: { children?: React.ReactNode }) {
    return <>{children}</>;
  },
  code({
    node,
    inline,
    className,
    children,
    ...rest
  }: React.ComponentPropsWithoutRef<"code"> & {
    node?: unknown;
    inline?: boolean;
  }) {
    void node;
    void inline;
    const match = /language-([\w-]+)/.exec(className || "");
    const codeText = String(children).replace(/\n$/, "");
    if (match) {
      return (
        <SyntaxHighlighter
          language={match[1]}
          style={oneDark}
          customStyle={{
            margin: 0,
            borderRadius: "6px",
            fontSize: "13px",
            lineHeight: "1.6",
          }}
        >
          {codeText}
        </SyntaxHighlighter>
      );
    }
    return (
      <code className={className} {...rest}>
        {children}
      </code>
    );
  },
};

function MarkdownPreview({ content }: { content: string }) {
  const { body, entries } = useMemo(
    () => parseMarkdownFrontmatter(content),
    [content],
  );

  return (
    <div className={styles.markdownWrap}>
      {entries.length > 0 && (
        <dl className={styles.frontmatter} aria-label="Front matter">
          {entries.map(({ key, value }, index) => (
            <div className={styles.frontmatterRow} key={`${key}:${index}`}>
              <dt className={styles.frontmatterKey}>{key}</dt>
              <dd className={styles.frontmatterValue}>{value}</dd>
            </div>
          ))}
        </dl>
      )}
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={markdownComponents}
      >
        {body}
      </ReactMarkdown>
    </div>
  );
}

function buildReadOnlyHtml(content: string): string {
  const document = new DOMParser().parseFromString(content, "text/html");
  document
    .querySelectorAll("script, meta[http-equiv='refresh']")
    .forEach((element) => element.remove());
  document.querySelectorAll("*").forEach((element) => {
    Array.from(element.attributes).forEach((attribute) => {
      if (attribute.name.toLowerCase().startsWith("on")) {
        element.removeAttribute(attribute.name);
      }
    });
    element.removeAttribute("contenteditable");
  });
  document.querySelectorAll("a").forEach((element) => {
    element.removeAttribute("href");
    element.removeAttribute("target");
    element.removeAttribute("download");
  });
  document.querySelectorAll("form").forEach((element) => {
    element.removeAttribute("action");
    element.removeAttribute("method");
  });
  document
    .querySelectorAll("button, input, select, textarea")
    .forEach((element) => element.setAttribute("disabled", ""));

  const style = document.createElement("style");
  style.textContent = [
    "a, button, input, select, textarea, form, iframe, object, embed,",
    "audio, video, [contenteditable] { pointer-events: none !important; }",
  ].join(" ");
  document.head.appendChild(style);
  return `<!doctype html>\n${document.documentElement.outerHTML}`;
}

function HtmlPreview({
  content,
  filePath,
  chatId,
  projectDirOverride,
  root,
  workspaceBacked,
}: FilePreviewProps) {
  const { t } = useTranslation();
  const readOnlyHtml = useMemo(() => buildReadOnlyHtml(content), [content]);

  return (
    <div className={styles.htmlWrap}>
      <div className={styles.htmlToolbar}>
        <button
          type="button"
          className={styles.htmlOpenButton}
          onClick={() =>
            openHtmlFile({
              content,
              filePath,
              chatId,
              projectDirOverride,
              root,
              workspaceBacked,
            })
          }
        >
          <ExternalLink size={14} />
          {t("files.openHtmlInBrowser")}
        </button>
      </div>
      <iframe
        className={styles.htmlFrame}
        srcDoc={readOnlyHtml}
        sandbox=""
        tabIndex={-1}
        title={t("files.htmlPreview")}
      />
    </div>
  );
}

const MAX_CSV_ROWS = 500;
const MAX_CSV_COLS = 50;

function CsvPreview({ content }: { content: string }) {
  const rows = useMemo(() => parseCsv(content), [content]);
  const header = rows[0] ?? [];
  const body = rows.slice(1, MAX_CSV_ROWS + 1);
  const truncatedCols = header.length > MAX_CSV_COLS;
  const truncatedRows = rows.length - 1 > MAX_CSV_ROWS;

  return (
    <div className={styles.csvWrap}>
      {(truncatedCols || truncatedRows) && (
        <div className={styles.csvNote}>
          {truncatedRows &&
            `Showing first ${MAX_CSV_ROWS} of ${rows.length - 1} rows. `}
          {truncatedCols &&
            `Showing first ${MAX_CSV_COLS} of ${header.length} columns.`}
        </div>
      )}
      <div className={styles.csvScroll}>
        <table className={styles.csvTable}>
          <thead>
            <tr>
              {header.slice(0, MAX_CSV_COLS).map((h, i) => (
                <th key={`${i}:${h}`}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {body.map((row, ri) => (
              <tr key={`${ri}:${row.join("\u0000")}`}>
                {row.slice(0, MAX_CSV_COLS).map((cell, ci) => (
                  <td key={`${ci}:${cell}`}>{cell}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export interface FilePreviewProps {
  filePath: string;
  /** Text content – used by Markdown and CSV renderers. */
  content: string;
  chatId?: string;
  binaryUrl?: string;
  root?: WorkspaceRoot;
  projectDirOverride?: string;
  workspaceBacked?: boolean;
}

export default function FilePreview({
  filePath,
  content,
  chatId,
  binaryUrl,
  root,
  projectDirOverride,
  workspaceBacked,
}: FilePreviewProps) {
  const type = getPreviewType(filePath);

  if (type === "image") {
    return (
      <ImagePreview
        filePath={filePath}
        chatId={chatId}
        binaryUrl={binaryUrl}
        root={root}
      />
    );
  }
  if (type === "pdf") {
    return (
      <PdfPreview
        filePath={filePath}
        chatId={chatId}
        binaryUrl={binaryUrl}
        root={root}
      />
    );
  }
  if (type === "markdown") return <MarkdownPreview content={content} />;
  if (type === "html") {
    return (
      <HtmlPreview
        filePath={filePath}
        content={content}
        chatId={chatId}
        root={root}
        projectDirOverride={projectDirOverride}
        workspaceBacked={workspaceBacked}
      />
    );
  }
  if (type === "csv") return <CsvPreview content={content} />;
  return null;
}
