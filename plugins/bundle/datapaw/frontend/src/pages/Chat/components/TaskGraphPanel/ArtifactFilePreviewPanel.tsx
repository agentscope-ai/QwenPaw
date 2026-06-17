import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { filesApi } from "@/api/modules/files";
import { buildAuthHeaders } from "@/api/authHeaders";
import {
  inferArtifactMimeType,
  resolveArtifactPreviewKind,
  safeFormatJson,
  type ArtifactPreviewKind,
} from "./fileUtils";
import {
  downloadArtifactFile,
  type ArtifactFileLike,
} from "./artifactFileActions";
import styles from "./TaskNodeDrawer.module.less";

const MAX_CSV_ROWS = 500;

export interface ArtifactFilePreviewPanelProps {
  file: ArtifactFileLike;
  sessionId: string;
  userId: string;
  onBack: () => void;
}

function renderCodePreview(content: string) {
  return (
    <div className={styles.codePreview}>
      <pre className={styles.filePreviewText}>
        <code>{content}</code>
      </pre>
    </div>
  );
}

export default function ArtifactFilePreviewPanel({
  file,
  sessionId,
  userId,
  onBack,
}: ArtifactFilePreviewPanelProps) {
  const { t } = useTranslation();
  const [previewContent, setPreviewContent] = useState("");
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState("");
  const [previewKind, setPreviewKind] = useState<ArtifactPreviewKind>("text");
  const [imageBlobUrl, setImageBlobUrl] = useState("");
  const [htmlBlobUrl, setHtmlBlobUrl] = useState("");
  const [iframeHeight, setIframeHeight] = useState(500);
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const imageBlobUrlRef = useRef("");
  const htmlBlobUrlRef = useRef("");

  const effectiveMime = useMemo(
    () => inferArtifactMimeType(file.name, file.mime_type),
    [file.mime_type, file.name],
  );

  const revokeBlobUrls = useCallback(() => {
    if (imageBlobUrlRef.current) URL.revokeObjectURL(imageBlobUrlRef.current);
    if (htmlBlobUrlRef.current) URL.revokeObjectURL(htmlBlobUrlRef.current);
    imageBlobUrlRef.current = "";
    htmlBlobUrlRef.current = "";
    setImageBlobUrl("");
    setHtmlBlobUrl("");
  }, []);

  const loadPreview = useCallback(
    async (target: ArtifactFileLike) => {
      setPreviewError("");
      setPreviewContent("");
      revokeBlobUrls();
      setIframeHeight(500);

      const kind = resolveArtifactPreviewKind({
        ...target,
        mime_type: inferArtifactMimeType(target.name, target.mime_type),
      });
      setPreviewKind(kind);

      if (kind === "image") {
        setPreviewLoading(true);
        try {
          const url = filesApi.resolveArtifactUrl(
            target.preview_url,
            target.path,
            sessionId,
            userId,
            "preview",
          );
          const res = await fetch(url, { headers: buildAuthHeaders() });
          if (!res.ok) throw new Error(`Failed to load image: ${res.status}`);
          const blob = await res.blob();
          const blobUrl = URL.createObjectURL(blob);
          imageBlobUrlRef.current = blobUrl;
          setImageBlobUrl(blobUrl);
        } catch (e) {
          setPreviewError(
            e instanceof Error ? e.message : "Failed to load image",
          );
        } finally {
          setPreviewLoading(false);
        }
        return;
      }

      if (kind === "html") {
        setPreviewLoading(true);
        try {
          const url = filesApi.resolveArtifactUrl(
            target.preview_url,
            target.path,
            sessionId,
            userId,
            "preview",
          );
          const res = await fetch(url, { headers: buildAuthHeaders() });
          if (!res.ok) throw new Error(`Failed to load HTML: ${res.status}`);
          const blob = await res.blob();
          const blobUrl = URL.createObjectURL(blob);
          htmlBlobUrlRef.current = blobUrl;
          setHtmlBlobUrl(blobUrl);
        } catch (e) {
          setPreviewError(
            e instanceof Error ? e.message : "Failed to load HTML",
          );
        } finally {
          setPreviewLoading(false);
        }
        return;
      }

      setPreviewLoading(true);
      try {
        const content = await filesApi.fetchTextContent(
          target.path,
          sessionId,
          userId,
          target.preview_url,
        );
        setPreviewContent(content);
      } catch (e) {
        setPreviewError(
          e instanceof Error ? e.message : t("taskGraph.previewError"),
        );
      } finally {
        setPreviewLoading(false);
      }
    },
    [revokeBlobUrls, sessionId, t, userId],
  );

  useEffect(() => {
    void loadPreview(file);
    return () => revokeBlobUrls();
  }, [file.path, loadPreview, revokeBlobUrls]);

  const handleBack = () => {
    revokeBlobUrls();
    setPreviewContent("");
    setPreviewError("");
    onBack();
  };

  const handleDownload = async () => {
    try {
      await downloadArtifactFile(file, sessionId, userId);
    } catch (e) {
      console.error("Download failed:", e);
    }
  };

  const renderCsvTable = (csvContent: string) => {
    if (!csvContent.trim()) return null;
    const lines = csvContent.trim().split("\n").slice(0, MAX_CSV_ROWS + 1);
    const headers = lines[0]
      .split(",")
      .map((h) => h.trim().replace(/^"|"$/g, ""));
    const rows = lines
      .slice(1)
      .map((line) =>
        line.split(",").map((cell) => cell.trim().replace(/^"|"$/g, "")),
      );

    return (
      <div className={styles.csvTableWrapper}>
        <table className={styles.csvTable}>
          <thead>
            <tr>
              {headers.map((h, i) => (
                <th key={i}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, ri) => (
              <tr key={ri}>
                {row.map((cell, ci) => (
                  <td key={ci}>{cell}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  };

  const hasPreviewContent =
    !previewLoading &&
    !previewError &&
    (previewContent || imageBlobUrl || htmlBlobUrl);

  const renderPreviewContent = () => {
    if (previewLoading) {
      return (
        <div className={styles.previewLoading}>
          {t("taskGraph.previewLoading")}
        </div>
      );
    }
    if (previewError) {
      return <div className={styles.previewError}>{previewError}</div>;
    }

    if (previewKind === "image") {
      return (
        <div className={styles.imagePreview}>
          <img src={imageBlobUrl} alt={file.name} />
        </div>
      );
    }

    if (previewKind === "html") {
      return (
        <div className={styles.htmlPreview}>
          <iframe
            ref={iframeRef}
            src={htmlBlobUrl}
            title={file.name}
            sandbox="allow-scripts allow-same-origin allow-forms"
            style={{ height: iframeHeight }}
            onLoad={() => {
              try {
                const doc = iframeRef.current?.contentDocument;
                if (doc?.body) {
                  const height = Math.max(doc.body.scrollHeight + 32, 500);
                  setIframeHeight((prev) =>
                    Math.abs(prev - height) < 4 ? prev : height,
                  );
                }
              } catch {
                // blob URL 同源，通常不会跨域，但防御性处理
              }
            }}
          />
        </div>
      );
    }

    if (previewKind === "markdown") {
      return (
        <div className={styles.markdownBody}>
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {previewContent}
          </ReactMarkdown>
        </div>
      );
    }

    if (previewKind === "csv") {
      return renderCsvTable(previewContent);
    }

    if (previewKind === "json") {
      return renderCodePreview(safeFormatJson(previewContent));
    }

    if (previewKind === "python" || previewKind === "text") {
      return renderCodePreview(previewContent);
    }

    if (previewContent) {
      return renderCodePreview(previewContent);
    }

    return (
      <div className={styles.previewError}>{t("taskGraph.unsupportedFormat")}</div>
    );
  };

  return (
    <div className={styles.filePreview}>
      <div className={styles.filePreviewHeader}>
        <button type="button" className={styles.backBtn} onClick={handleBack}>
          {t("taskGraph.back")}
        </button>
        <span className={styles.filePreviewTitle}>{file.name}</span>
        <button
          type="button"
          className={styles.backBtn}
          onClick={() => void handleDownload()}
        >
          {t("taskGraph.download")}
        </button>
      </div>
      <div className={styles.filePreviewMeta}>
        <span>{effectiveMime || file.mime_type}</span>
        <span>
          {file.size_bytes
            ? `${(file.size_bytes / 1024).toFixed(1)} KB`
            : ""}
        </span>
      </div>
      <div
        className={`${styles.filePreviewContent}${
          hasPreviewContent ? ` ${styles.filePreviewContentActive}` : ""
        }`}
      >
        {renderPreviewContent()}
      </div>
    </div>
  );
}
