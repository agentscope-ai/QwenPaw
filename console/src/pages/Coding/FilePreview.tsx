/**
 * FilePreview – renders a non-code file in the editor area.
 *
 * Supported types (auto-detected by extension):
 *   • image  – PNG / JPG / GIF / WebP / SVG / ICO / BMP
 *   • pdf    – inline <embed>
 *   • markdown – react-markdown with GFM
 *   • html   – read-only sandboxed document
 *   • csv    – parsed table
 *   • office – docx / xlsx / pptx, read client-side (read-only)
 */

import {
  ExternalLink,
  FileCode2,
  FileWarning,
  LoaderCircle,
} from "lucide-react";
import { useMemoizedFn } from "ahooks";
import DOMPurify from "dompurify";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import { workspaceApi } from "../../api/modules/workspace";
import { buildAuthHeaders } from "../../api/authHeaders";
import { RenderableCodeBlock } from "../../components/RenderableCodeBlock";
import type { WorkspaceRoot } from "../../features/files-workspace/types";
import { ExternalMarkdownLink } from "../../components/Markdown/externalLinkComponents";
import { useAgentStore } from "../../stores/agentStore";
import { openHtmlFile } from "../../utils/openHtmlFile";
import {
  parseMarkdownFrontmatter,
  parseMemoryTags,
} from "../../utils/markdown";
import { resolveMarkdownFilePath } from "./markdownFileReferences";
import {
  MAX_OFFICE_FILE_BYTES,
  MAX_SHEET_COLS,
  MAX_SHEET_ROWS,
  getOfficeKind,
  type SheetPreview,
  type SlidePreview,
} from "./officeTypes";
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
  | "office"
  | "none";

export function getPreviewType(filePath: string): PreviewType {
  const ext = filePath.split(".").pop()?.toLowerCase() ?? "";
  if (IMAGE_EXTS.has(ext)) return "image";
  if (ext === "pdf") return "pdf";
  if (ext === "md" || ext === "mdx") return "markdown";
  if (ext === "html" || ext === "htm") return "html";
  if (ext === "csv") return "csv";
  if (getOfficeKind(filePath)) return "office";
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
  projectDirOverride?: string,
): {
  blobUrl: string | null;
  blob: Blob | null;
  loading: boolean;
  failed: boolean;
} {
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  const [blob, setBlob] = useState<Blob | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const selectedAgent = useAgentStore((state) => state.selectedAgent);

  useEffect(() => {
    const controller = new AbortController();
    let objectUrl: string | null = null;
    setBlobUrl(null);
    setBlob(null);
    setLoading(true);
    setFailed(false);

    const loadBlob = async (): Promise<Blob | null> => {
      const url = binaryUrl ?? workspaceApi.getFileDownloadUrl(filePath, root);
      const res = await fetch(url, {
        headers: {
          ...buildAuthHeaders(),
          ...(chatId ? { "X-Chat-Id": chatId } : {}),
          ...(!chatId && projectDirOverride
            ? { "X-Session-Project-Dir": projectDirOverride }
            : {}),
        },
        signal: controller.signal,
      });
      if (!res.ok) throw new Error(`${res.status}`);
      return res.blob();
    };

    loadBlob()
      .then((loaded) => {
        if (controller.signal.aborted || !loaded) return;
        objectUrl = URL.createObjectURL(loaded);
        setBlobUrl(objectUrl);
        setBlob(loaded);
        setLoading(false);
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setBlobUrl(null);
          setBlob(null);
          setLoading(false);
          setFailed(true);
        }
      });

    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [binaryUrl, chatId, filePath, root, projectDirOverride, selectedAgent]);

  return { blobUrl, blob, loading, failed };
}

// ---------------------------------------------------------------------------
// Sub-renderers
// ---------------------------------------------------------------------------

function ImagePreview({
  filePath,
  chatId,
  binaryUrl,
  root,
  projectDirOverride,
}: {
  filePath: string;
  chatId?: string;
  binaryUrl?: string;
  root?: WorkspaceRoot;
  projectDirOverride?: string;
}) {
  const { t } = useTranslation();
  const { blobUrl, loading, failed } = useAuthBlobUrl(
    filePath,
    chatId,
    binaryUrl,
    root,
    projectDirOverride,
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
  projectDirOverride,
}: {
  filePath: string;
  chatId?: string;
  binaryUrl?: string;
  root?: WorkspaceRoot;
  projectDirOverride?: string;
}) {
  const { t } = useTranslation();
  const { blobUrl, loading, failed } = useAuthBlobUrl(
    filePath,
    chatId,
    binaryUrl,
    root,
    projectDirOverride,
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
    return (
      <RenderableCodeBlock
        {...rest}
        block={!!match}
        className={className}
        lang={match?.[1]}
      >
        {children}
      </RenderableCodeBlock>
    );
  },
};

function MarkdownImage({
  filePath,
  chatId,
  root,
  projectDirOverride,
  ...props
}: React.ComponentPropsWithoutRef<"img"> & {
  filePath: string;
  chatId?: string;
  root?: WorkspaceRoot;
  projectDirOverride?: string;
}) {
  const { blobUrl, loading } = useAuthBlobUrl(
    filePath,
    chatId,
    undefined,
    root,
    projectDirOverride,
  );
  return <img {...props} src={blobUrl ?? undefined} aria-busy={loading} />;
}

type MarkdownAstNode = {
  type?: string;
  lang?: string;
  children?: MarkdownAstNode[];
};

function preserveMathCodeBlocks() {
  return (tree: MarkdownAstNode) => {
    const visit = (child: MarkdownAstNode) => {
      if (child.type === "code" && child.lang === "math") {
        child.lang = "latex";
      }
      for (const nested of child.children ?? []) visit(nested);
    };
    for (const child of tree.children ?? []) visit(child);
  };
}

function MarkdownPreview({
  filePath,
  content,
  chatId,
  root,
  projectDirOverride,
  workspaceBacked,
  onOpenFile,
  onMemoryTagClick,
}: FilePreviewProps) {
  const { t } = useTranslation();
  const tags = useMemo(() => parseMemoryTags(content), [content]);
  const { body, entries } = useMemo(
    () => parseMarkdownFrontmatter(content),
    [content],
  );
  const canOpenFile = !!onOpenFile;
  const handleOpenFile = useMemoizedFn((path: string) => onOpenFile?.(path));
  const components = useMemo<Components>(
    () => ({
      ...markdownComponents,
      a({ node, href, ...props }) {
        void node;
        const path = workspaceBacked
          ? resolveMarkdownFilePath(filePath, href)
          : null;
        if (!path || !canOpenFile) {
          return <ExternalMarkdownLink {...props} href={href} />;
        }
        return (
          <a
            {...props}
            href={workspaceApi.getFileDownloadUrl(path, root)}
            onClick={(event) => {
              event.preventDefault();
              event.stopPropagation();
              handleOpenFile(path);
            }}
          />
        );
      },
      img({ node, src, ...props }) {
        void node;
        const path = workspaceBacked
          ? resolveMarkdownFilePath(filePath, src)
          : null;
        return path ? (
          <MarkdownImage
            {...props}
            filePath={path}
            chatId={chatId}
            root={root}
            projectDirOverride={projectDirOverride}
          />
        ) : (
          <img {...props} src={src} />
        );
      },
    }),
    [
      filePath,
      chatId,
      root,
      projectDirOverride,
      workspaceBacked,
      canOpenFile,
      handleOpenFile,
    ],
  );
  // Tags come from the resolved YAML document, including merge keys and
  // quoted keys. Render one semantic tag row independently of raw metadata.
  const metadataEntries = tags.length
    ? [
        ...entries.filter(
          ({ key }) =>
            !["memory_tags", '"memory_tags"', "'memory_tags'"].includes(key),
        ),
        { key: "memory_tags", value: "" },
      ]
    : entries;

  return (
    <div className={styles.markdownWrap}>
      {metadataEntries.length > 0 && (
        <dl className={styles.frontmatter} aria-label="Front matter">
          {metadataEntries.map(({ key, value }, index) => (
            <div className={styles.frontmatterRow} key={`${key}:${index}`}>
              <dt className={styles.frontmatterKey}>
                {key === "memory_tags" ? t("files.memoryTagsLabel") : key}
              </dt>
              <dd className={styles.frontmatterValue}>
                {key === "memory_tags" && tags.length > 0 ? (
                  <span className={styles.memoryTags}>
                    {tags.map((tag) =>
                      onMemoryTagClick ? (
                        <button
                          type="button"
                          key={tag}
                          className={styles.memoryTag}
                          onClick={() => onMemoryTagClick(tag)}
                          aria-label={t("files.memoryTagBrowse", { tag })}
                          title={t("files.memoryTagBrowse", { tag })}
                        >
                          {tag}
                        </button>
                      ) : (
                        <span key={tag} className={styles.memoryTag}>
                          {tag}
                        </span>
                      ),
                    )}
                  </span>
                ) : (
                  value
                )}
              </dd>
            </div>
          ))}
        </dl>
      )}
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath, preserveMathCodeBlocks]}
        rehypePlugins={[rehypeKatex]}
        components={components}
      >
        {body}
      </ReactMarkdown>
    </div>
  );
}

function buildReadOnlyHtml(content: string): {
  html: string;
  hasDynamicContent: boolean;
  hasStaticContent: boolean;
} {
  const document = new DOMParser().parseFromString(content, "text/html");
  let hasDynamicContent = Array.from(document.querySelectorAll("script")).some(
    (script) => {
      const type = (script.getAttribute("type") ?? "")
        .split(";")[0]
        .trim()
        .toLowerCase();
      return [
        "",
        "module",
        "text/javascript",
        "application/javascript",
        "text/ecmascript",
        "application/ecmascript",
      ].includes(type);
    },
  );
  document
    .querySelectorAll("script, meta[http-equiv='refresh']")
    .forEach((element) => element.remove());
  document.querySelectorAll("*").forEach((element) => {
    Array.from(element.attributes).forEach((attribute) => {
      if (attribute.name.toLowerCase().startsWith("on")) {
        hasDynamicContent ||= Boolean(attribute.value.trim());
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

  const staticBody = document.body.cloneNode(true) as HTMLElement;
  staticBody
    .querySelectorAll("style, template")
    .forEach((element) => element.remove());
  const hasStaticContent = Boolean(
    staticBody.textContent?.trim() ||
      staticBody.querySelector("img, svg, video, audio, iframe, object, embed"),
  );

  const style = document.createElement("style");
  style.textContent = [
    "a, button, input, select, textarea, form, iframe, object, embed,",
    "audio, video, [contenteditable] { pointer-events: none !important; }",
  ].join(" ");
  document.head.appendChild(style);
  return {
    html: `<!doctype html>\n${document.documentElement.outerHTML}`,
    hasDynamicContent,
    hasStaticContent,
  };
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
  const { html, hasDynamicContent, hasStaticContent } = useMemo(
    () => buildReadOnlyHtml(content),
    [content],
  );
  const showFallback = hasDynamicContent && !hasStaticContent;
  const openButton = (
    <button
      type="button"
      className={
        showFallback
          ? `${styles.htmlOpenButton} ${styles.htmlFallbackButton}`
          : styles.htmlOpenButton
      }
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
      <ExternalLink size={14} strokeWidth={1.5} aria-hidden="true" />
      {t("files.openHtmlInBrowser")}
    </button>
  );

  return (
    <div className={styles.htmlWrap}>
      {!showFallback && <div className={styles.htmlToolbar}>{openButton}</div>}
      {hasDynamicContent && (
        <div
          className={showFallback ? styles.htmlFallback : styles.htmlNotice}
          role="status"
        >
          {showFallback && (
            <span className={styles.htmlFallbackIcon}>
              <FileCode2 size={28} strokeWidth={1.5} aria-hidden="true" />
            </span>
          )}
          <div className={showFallback ? styles.htmlFallbackText : undefined}>
            {showFallback && (
              <h3 className={styles.htmlFallbackTitle}>
                {t("files.htmlReadOnlyTitle")}
              </h3>
            )}
            <p className={styles.htmlNoticeText}>
              {t("files.htmlReadOnlyNotice", {
                context: showFallback ? "fallback" : undefined,
              })}
            </p>
          </div>
          {showFallback && openButton}
        </div>
      )}
      {!showFallback && (
        <iframe
          className={styles.htmlFrame}
          srcDoc={html}
          sandbox=""
          tabIndex={-1}
          title={t("files.htmlPreview")}
        />
      )}
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
// Office documents (docx / xlsx / pptx)
// ---------------------------------------------------------------------------

type OfficeContent =
  | { kind: "docx"; html: string }
  | { kind: "xlsx"; sheets: SheetPreview[] }
  | { kind: "pptx"; slides: SlidePreview[] };

async function loadOfficeContent(
  filePath: string,
  blob: Blob,
): Promise<OfficeContent> {
  if (blob.size > MAX_OFFICE_FILE_BYTES) {
    throw new Error("Office file is too large to preview");
  }
  const kind = getOfficeKind(filePath);
  const data = await blob.arrayBuffer();
  // Loaded on demand so the zip / docx libraries stay out of the main chunk.
  const office = await import("./officeDocument");
  if (kind === "docx") {
    const html = DOMPurify.sanitize(await office.docxToHtml(data), {
      FORBID_TAGS: ["style"],
      // Links stay inert, like the read-only HTML preview.
      FORBID_ATTR: ["href", "target", "style"],
    });
    return { kind, html };
  }
  if (kind === "xlsx") return { kind, sheets: await office.readXlsx(data) };
  if (kind === "pptx") return { kind, slides: await office.readPptx(data) };
  throw new Error("Unsupported Office file");
}

function SheetTable({ sheet }: { sheet: SheetPreview }) {
  const { t } = useTranslation();
  const truncatedRows = sheet.totalRows > MAX_SHEET_ROWS;
  const truncatedCols = sheet.totalCols > MAX_SHEET_COLS;
  const colCount = Math.min(sheet.totalCols, MAX_SHEET_COLS);

  if (sheet.rows.length === 0) {
    return (
      <div className={styles.officeEmpty}>{t("files.officeSheetEmpty")}</div>
    );
  }
  return (
    <>
      {(truncatedRows || truncatedCols) && (
        <div className={styles.csvNote}>
          {t("files.officeSheetTruncated", {
            rows: Math.min(sheet.totalRows, MAX_SHEET_ROWS),
            totalRows: sheet.totalRows,
            cols: colCount,
            totalCols: sheet.totalCols,
          })}
        </div>
      )}
      <div className={styles.csvScroll}>
        <table className={styles.csvTable}>
          <tbody>
            {sheet.rows.map((row, ri) => (
              <tr key={ri}>
                {Array.from({ length: colCount }, (_, ci) => (
                  <td key={ci}>{row[ci] ?? ""}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function OfficeWorkbook({ sheets }: { sheets: SheetPreview[] }) {
  const { t } = useTranslation();
  const [active, setActive] = useState(0);
  const sheet = sheets[Math.min(active, sheets.length - 1)];
  if (!sheet) {
    return (
      <div className={styles.officeEmpty}>{t("files.officeSheetEmpty")}</div>
    );
  }
  return (
    <div className={styles.csvWrap}>
      {sheets.length > 1 && (
        <div className={styles.officeTabs} role="tablist">
          {sheets.map((item, index) => (
            <button
              key={`${index}:${item.name}`}
              type="button"
              role="tab"
              aria-selected={index === active}
              className={
                index === active
                  ? `${styles.officeTab} ${styles.officeTabActive}`
                  : styles.officeTab
              }
              onClick={() => setActive(index)}
            >
              {item.name}
            </button>
          ))}
        </div>
      )}
      <SheetTable sheet={sheet} />
    </div>
  );
}

function OfficeSlides({ slides }: { slides: SlidePreview[] }) {
  const { t } = useTranslation();
  return (
    <div className={styles.markdownWrap}>
      <div className={styles.csvNote}>{t("files.officeSlidesTextOnly")}</div>
      {slides.map((slide) => (
        <section key={slide.index} className={styles.officeSlide}>
          <h3>{t("files.officeSlide", { index: slide.index })}</h3>
          {slide.paragraphs.map((text, index) => (
            <p key={index}>{text}</p>
          ))}
        </section>
      ))}
    </div>
  );
}

function OfficePreview({
  filePath,
  chatId,
  binaryUrl,
  root,
  projectDirOverride,
}: {
  filePath: string;
  chatId?: string;
  binaryUrl?: string;
  root?: WorkspaceRoot;
  projectDirOverride?: string;
}) {
  const { t } = useTranslation();
  const { blob, loading, failed } = useAuthBlobUrl(
    filePath,
    chatId,
    binaryUrl,
    root,
    projectDirOverride,
  );
  const [parsed, setParsed] = useState<OfficeContent | null>(null);
  const [parseFailed, setParseFailed] = useState(false);

  useEffect(() => {
    setParsed(null);
    setParseFailed(false);
    if (!blob) return;
    let cancelled = false;
    loadOfficeContent(filePath, blob)
      .then((content) => {
        if (!cancelled) setParsed(content);
      })
      .catch(() => {
        if (!cancelled) setParseFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [blob, filePath]);

  if (loading || (blob && !parsed && !parseFailed)) {
    return (
      <PreviewStatus icon={<LoaderCircle size={18} />} spinning>
        {t("common.loading")}
      </PreviewStatus>
    );
  }
  if (failed || parseFailed || !parsed) {
    return (
      <PreviewStatus icon={<FileWarning size={18} />}>
        {t("files.previewUnavailable")}
      </PreviewStatus>
    );
  }
  if (parsed.kind === "xlsx") return <OfficeWorkbook sheets={parsed.sheets} />;
  if (parsed.kind === "pptx") return <OfficeSlides slides={parsed.slides} />;
  return (
    <div
      className={styles.markdownWrap}
      // Sanitised with DOMPurify in loadOfficeContent.
      dangerouslySetInnerHTML={{ __html: parsed.html }}
    />
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
  onOpenFile?: (path: string) => void;
  onMemoryTagClick?: (tag: string) => void;
}

export default function FilePreview({
  filePath,
  content,
  chatId,
  binaryUrl,
  root,
  projectDirOverride,
  workspaceBacked,
  onOpenFile,
  onMemoryTagClick,
}: FilePreviewProps) {
  const type = getPreviewType(filePath);

  if (type === "image") {
    return (
      <ImagePreview
        filePath={filePath}
        chatId={chatId}
        binaryUrl={binaryUrl}
        root={root}
        projectDirOverride={projectDirOverride}
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
        projectDirOverride={projectDirOverride}
      />
    );
  }
  if (type === "markdown")
    return (
      <MarkdownPreview
        filePath={filePath}
        content={content}
        chatId={chatId}
        root={root}
        projectDirOverride={projectDirOverride}
        workspaceBacked={workspaceBacked && !binaryUrl}
        onOpenFile={onOpenFile}
        onMemoryTagClick={onMemoryTagClick}
      />
    );
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
  if (type === "office") {
    return (
      <OfficePreview
        filePath={filePath}
        chatId={chatId}
        binaryUrl={binaryUrl}
        root={root}
        projectDirOverride={projectDirOverride}
      />
    );
  }
  return null;
}
