/**
 * FilePreview – renders a non-code file in the editor area.
 *
 * Supported types (auto-detected by extension):
 *   • image  – PNG / JPG / GIF / WebP / SVG / ICO / BMP
 *   • pdf    – inline <embed>
 *   • markdown – react-markdown with GFM
 *   • csv    – parsed table
 */

import { useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";
import { invoke } from "@tauri-apps/api/core";
import { workspaceApi } from "../../api/modules/workspace";
import { buildAuthHeaders } from "../../api/authHeaders";
import { isDesktopTauriRuntime } from "../../utils/openExternalLink";
import { useAgentStore } from "../../stores/agentStore";
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

export type PreviewType = "image" | "pdf" | "markdown" | "csv" | "none";

export function getPreviewType(filePath: string): PreviewType {
  const ext = filePath.split(".").pop()?.toLowerCase() ?? "";
  if (IMAGE_EXTS.has(ext)) return "image";
  if (ext === "pdf") return "pdf";
  if (ext === "md" || ext === "mdx") return "markdown";
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
// In Tauri desktop mode, reads the file directly from disk via a native
// command so binary previews work offline (no backend HTTP required).
// ---------------------------------------------------------------------------

function useAuthBlobUrl(filePath: string): string | null {
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  const selectedAgent = useAgentStore((state) => state.selectedAgent);

  useEffect(() => {
    let revoked = false;

    const loadBlob = async (): Promise<Blob | null> => {
      // Tauri: read file directly from disk for offline support
      if (isDesktopTauriRuntime()) {
        try {
          const response = await invoke<ArrayBuffer | number[]>(
            "read_workspace_binary_file",
            {
              filePath,
              agentId: selectedAgent,
            },
          );
          const mimeType = guessMimeType(filePath);
          // Tauri 2.11.1 on macOS may serialize a raw Vec<u8> as number[]
          // instead of ArrayBuffer. Normalize both shapes into a Uint8Array
          // so Blob construction uses the actual bytes, not a string join.
          const bytes = Array.isArray(response)
            ? new Uint8Array(response)
            : new Uint8Array(response);
          return new Blob([bytes], { type: mimeType });
        } catch {
          // Fall through to HTTP fetch as fallback
        }
      }

      // Browser / online: fetch via backend API with auth headers
      const url = workspaceApi.getBinaryFileUrl(filePath);
      const res = await fetch(url, { headers: buildAuthHeaders() });
      if (!res.ok) throw new Error(`${res.status}`);
      return res.blob();
    };

    loadBlob()
      .then((blob) => {
        if (revoked || !blob) return;
        setBlobUrl(URL.createObjectURL(blob));
      })
      .catch(() => {
        if (!revoked) setBlobUrl(null);
      });

    return () => {
      revoked = true;
      setBlobUrl((prev) => {
        if (prev) URL.revokeObjectURL(prev);
        return null;
      });
    };
  }, [filePath, selectedAgent]);

  return blobUrl;
}

/** Guess a MIME type from the file extension for blob creation. */
function guessMimeType(filePath: string): string {
  const ext = filePath.split(".").pop()?.toLowerCase() ?? "";
  const mimeMap: Record<string, string> = {
    png: "image/png",
    jpg: "image/jpeg",
    jpeg: "image/jpeg",
    gif: "image/gif",
    webp: "image/webp",
    svg: "image/svg+xml",
    ico: "image/x-icon",
    bmp: "image/bmp",
    pdf: "application/pdf",
  };
  return mimeMap[ext] ?? "application/octet-stream";
}

// ---------------------------------------------------------------------------
// Sub-renderers
// ---------------------------------------------------------------------------

function ImagePreview({ filePath }: { filePath: string }) {
  const blobUrl = useAuthBlobUrl(filePath);
  if (!blobUrl) return null;
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

function PdfPreview({ filePath }: { filePath: string }) {
  const blobUrl = useAuthBlobUrl(filePath);
  if (!blobUrl) return null;
  return (
    <embed
      src={blobUrl}
      type="application/pdf"
      className={styles.pdfEmbed}
      title={filePath.split("/").pop()}
    />
  );
}

const markdownComponents = {
  pre({ children }: { children?: React.ReactNode }) {
    return <>{children}</>;
  },
  code({ node: _node, inline: _inline, className, children, ...rest }: any) {
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
  return (
    <div className={styles.markdownWrap}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={markdownComponents}
      >
        {content}
      </ReactMarkdown>
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
                // eslint-disable-next-line react/no-array-index-key
                <th key={i}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {body.map((row, ri) => (
              // eslint-disable-next-line react/no-array-index-key
              <tr key={ri}>
                {row.slice(0, MAX_CSV_COLS).map((cell, ci) => (
                  // eslint-disable-next-line react/no-array-index-key
                  <td key={ci}>{cell}</td>
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
}

export default function FilePreview({ filePath, content }: FilePreviewProps) {
  const type = getPreviewType(filePath);

  if (type === "image") return <ImagePreview filePath={filePath} />;
  if (type === "pdf") return <PdfPreview filePath={filePath} />;
  if (type === "markdown") return <MarkdownPreview content={content} />;
  if (type === "csv") return <CsvPreview content={content} />;
  return null;
}
