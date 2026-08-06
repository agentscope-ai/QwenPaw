/** Render editor previews from an explicit artifact kind or file extension. */

import { useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";
import { invoke } from "@tauri-apps/api/core";
import { Spin } from "antd";
import { workspaceApi } from "../../api/modules/workspace";
import { buildAuthHeaders } from "../../api/authHeaders";
import { isDesktopTauriRuntime } from "../../utils/openExternalLink";
import { ExternalMarkdownLink } from "../../components/Markdown/externalLinkComponents";
import { useAgentStore } from "../../stores/agentStore";
import {
  getArtifactPreviewLimit,
  type WorkspaceArtifactPreviewKind,
} from "../../types/workspaceArtifacts";
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
  "avif",
  "svg",
  "ico",
  "bmp",
]);

const TEXT_EXTS = new Set([
  "css",
  "html",
  "ini",
  "js",
  "json",
  "log",
  "py",
  "toml",
  "ts",
  "tsx",
  "txt",
  "xml",
  "yaml",
  "yml",
]);

export type PreviewType = WorkspaceArtifactPreviewKind;

export function getPreviewType(filePath: string): PreviewType {
  const ext = filePath.split(".").pop()?.toLowerCase() ?? "";
  if (IMAGE_EXTS.has(ext)) return "image";
  if (ext === "pdf") return "pdf";
  if (ext === "md" || ext === "markdown" || ext === "mdx") {
    return "markdown";
  }
  if (ext === "csv" || ext === "tsv") return "csv";
  if (TEXT_EXTS.has(ext)) return "text";
  return "none";
}

export function isPreviewable(filePath: string): boolean {
  return ["image", "pdf", "markdown", "csv"].includes(getPreviewType(filePath));
}

// ---------------------------------------------------------------------------
// CSV parser (no external dep)
// ---------------------------------------------------------------------------

function parseDelimited(raw: string, delimiter: string): string[][] {
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
      } else if (ch === delimiter && !inQuote) {
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

interface BlobPreviewState {
  blobUrl: string | null;
  status: "loading" | "ready" | "error";
}

function useAuthBlobUrl(
  filePath: string,
  artifactAgentId?: string,
  artifactSize?: number,
): BlobPreviewState {
  const [state, setState] = useState<BlobPreviewState>({
    blobUrl: null,
    status: "loading",
  });
  const selectedAgent = useAgentStore((state) => state.selectedAgent);

  useEffect(() => {
    let disposed = false;
    let objectUrl: string | null = null;
    const controller = new AbortController();
    setState({ blobUrl: null, status: "loading" });
    const previewLimit = getArtifactPreviewLimit(getPreviewType(filePath));
    if (
      artifactSize !== undefined &&
      previewLimit !== null &&
      artifactSize > previewLimit
    ) {
      setState({ blobUrl: null, status: "error" });
      return () => controller.abort();
    }

    const loadBlob = async (): Promise<Blob | null> => {
      // Tauri: read file directly from disk for offline support
      if (isDesktopTauriRuntime() && !artifactAgentId) {
        try {
          const response = await invoke<ArrayBuffer | number[]>(
            "read_workspace_binary_file",
            {
              filePath,
              agentId: artifactAgentId || selectedAgent,
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
      const url = artifactAgentId
        ? workspaceApi.getArtifactPreviewUrl(artifactAgentId, filePath)
        : workspaceApi.getBinaryFileUrl(filePath);
      const res = await fetch(url, {
        headers: buildAuthHeaders(),
        signal: controller.signal,
      });
      if (!res.ok) throw new Error(`${res.status}`);
      const contentLength = Number(res.headers.get("Content-Length"));
      if (
        previewLimit !== null &&
        Number.isFinite(contentLength) &&
        contentLength > previewLimit
      ) {
        throw new Error("Preview file is too large");
      }
      const blob = await res.blob();
      if (previewLimit !== null && blob.size > previewLimit) {
        throw new Error("Preview file is too large");
      }
      return blob;
    };

    loadBlob()
      .then((blob) => {
        if (disposed || !blob) return;
        objectUrl = URL.createObjectURL(blob);
        setState({ blobUrl: objectUrl, status: "ready" });
      })
      .catch(() => {
        if (!disposed) setState({ blobUrl: null, status: "error" });
      });

    return () => {
      disposed = true;
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [artifactAgentId, artifactSize, filePath, selectedAgent]);

  return state;
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
    avif: "image/avif",
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

function ImagePreview({
  filePath,
  artifactAgentId,
  artifactSize,
}: {
  filePath: string;
  artifactAgentId?: string;
  artifactSize?: number;
}) {
  const { blobUrl, status } = useAuthBlobUrl(
    filePath,
    artifactAgentId,
    artifactSize,
  );
  if (status === "loading") return <Spin />;
  if (status === "error" || !blobUrl) {
    return <div className={styles.previewState}>Preview unavailable</div>;
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
  artifactAgentId,
  artifactSize,
}: {
  filePath: string;
  artifactAgentId?: string;
  artifactSize?: number;
}) {
  const { blobUrl, status } = useAuthBlobUrl(
    filePath,
    artifactAgentId,
    artifactSize,
  );
  if (status === "loading") return <Spin />;
  if (status === "error" || !blobUrl) {
    return <div className={styles.previewState}>Preview unavailable</div>;
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

const markdownComponents = {
  a: ExternalMarkdownLink,
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

function CsvPreview({
  content,
  delimiter,
}: {
  content: string;
  delimiter: string;
}) {
  const rows = useMemo(
    () => parseDelimited(content, delimiter),
    [content, delimiter],
  );
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

function TextPreview({
  filePath,
  content,
}: {
  filePath: string;
  content: string;
}) {
  const extension = filePath.split(".").pop()?.toLowerCase() || "text";
  return (
    <div className={styles.textWrap}>
      <SyntaxHighlighter
        language={extension}
        style={oneDark}
        showLineNumbers
        wrapLongLines
        customStyle={{ margin: 0, minHeight: "100%", borderRadius: 0 }}
      >
        {content}
      </SyntaxHighlighter>
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
  artifactAgentId?: string;
  artifactSize?: number;
  previewKind?: WorkspaceArtifactPreviewKind;
}

export default function FilePreview({
  filePath,
  content,
  artifactAgentId,
  artifactSize,
  previewKind,
}: FilePreviewProps) {
  const type = previewKind ?? getPreviewType(filePath);

  if (type === "image") {
    return (
      <ImagePreview
        filePath={filePath}
        artifactAgentId={artifactAgentId}
        artifactSize={artifactSize}
      />
    );
  }
  if (type === "pdf") {
    return (
      <PdfPreview
        filePath={filePath}
        artifactAgentId={artifactAgentId}
        artifactSize={artifactSize}
      />
    );
  }
  if (type === "markdown") return <MarkdownPreview content={content} />;
  if (type === "csv") {
    const delimiter = filePath.toLowerCase().endsWith(".tsv") ? "\t" : ",";
    return <CsvPreview content={content} delimiter={delimiter} />;
  }
  if (type === "text") {
    return <TextPreview filePath={filePath} content={content} />;
  }
  return <div className={styles.previewState}>Preview unavailable</div>;
}
