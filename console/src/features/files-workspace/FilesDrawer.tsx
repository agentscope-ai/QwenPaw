import {
  ArrowLeft,
  Copy,
  Download,
  Expand,
  FileText,
  MessageSquarePlus,
  X,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  lazy,
  useRef,
  useState,
  Suspense,
} from "react";
import { useTranslation } from "react-i18next";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { workspaceApi } from "../../api/modules/workspace";
import { buildAuthHeaders } from "../../api/authHeaders";
import FilePreview, { isPreviewable } from "../../pages/Coding/FilePreview";
import { setTextareaValue } from "../../pages/Chat/utils";
import { downloadFileFromUrl } from "../../utils/downloadFileFromUrl";
import { copyText } from "../../utils/clipboard";
import { useAppMessage } from "../../hooks/useAppMessage";
import type { FileMetadata, FilesDrawerEvent, FilesDrawerState } from "./types";
import type { FilesWorkspaceScope } from "./filesWorkspaceScope";
import styles from "./FilesWorkspace.module.less";

const PREVIEW_WIDTH_STORAGE_KEY = "qwenpaw-files-preview-width";
const WORKSPACE_WIDTH_STORAGE_KEY = "qwenpaw-files-workspace-width";
const MIN_DRAWER_WIDTH = 420;
const MIN_CHAT_WIDTH = 420;
const FilesWorkspace = lazy(() => import("./FilesWorkspace"));

interface FilesDrawerProps {
  state: Exclude<FilesDrawerState, { kind: "closed" }>;
  dispatch: (event: FilesDrawerEvent) => void;
  scope: Extract<FilesWorkspaceScope, { kind: "session" }>;
}

function insertFileReference(path: string): void {
  const textarea = document.querySelector<HTMLTextAreaElement>(
    '[class*="sender"] textarea',
  );
  if (!textarea) return;
  const start = textarea.selectionStart ?? textarea.value.length;
  const end = textarea.selectionEnd ?? start;
  const reference = `@ ${path}`;
  const prefix = textarea.value.slice(0, start);
  const suffix = textarea.value.slice(end);
  const spacing = prefix && !/\s$/.test(prefix) ? " " : "";
  const next = `${prefix}${spacing}${reference} ${suffix}`;
  setTextareaValue(textarea, next);
  const caret = prefix.length + spacing.length + reference.length + 1;
  requestAnimationFrame(() => {
    textarea.focus();
    textarea.setSelectionRange(caret, caret);
  });
}

export default function FilesDrawer({
  state,
  dispatch,
  scope,
}: FilesDrawerProps) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const drawerRef = useRef<HTMLElement>(null);
  const [metadata, setMetadata] = useState<FileMetadata | null>(null);
  const [content, setContent] = useState("");
  const [loading, setLoading] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);
  const [isResizing, setIsResizing] = useState(false);
  const prefersReducedMotion = useReducedMotion();
  const isWorkspace = state.kind === "workspace";
  const chatId = scope.chatId;
  const projectDirOverride = scope.projectDirOverride;
  const target = state.target;
  const widthStorageKey = isWorkspace
    ? WORKSPACE_WIDTH_STORAGE_KEY
    : PREVIEW_WIDTH_STORAGE_KEY;
  const [width, setWidth] = useState(0);

  useEffect(() => {
    const stored = Number(localStorage.getItem(widthStorageKey));
    setWidth(Number.isFinite(stored) && stored > 0 ? stored : 0);
  }, [widthStorageKey]);

  const close = useCallback(() => {
    const trigger = state.trigger;
    dispatch({ type: "CLOSE" });
    requestAnimationFrame(() => trigger?.focus());
  }, [dispatch, state.trigger]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        close();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    drawerRef.current?.focus();
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [close]);

  useEffect(() => {
    if (!target) {
      setMetadata(null);
      setContent("");
      setLoadFailed(false);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    setLoadFailed(false);
    const loadMetadata = target.artifactUrl
      ? fetch(target.artifactUrl, {
          headers: buildAuthHeaders(),
          signal: controller.signal,
        }).then(async (response) => {
          if (!response.ok) throw new Error(`${response.status}`);
          const contentType = response.headers.get("Content-Type") ?? "";
          const isText =
            contentType.startsWith("text/") ||
            /\.(?:md|mdx|txt|csv|json|ya?ml|toml|xml|html?|css|less|scss|js|jsx|ts|tsx|py|java|go|rs|sh)$/i.test(
              target.path,
            );
          const previewKind = /\.(?:png|jpe?g|gif|webp|svg|ico|bmp)$/i.test(
            target.path,
          )
            ? "image"
            : /\.pdf$/i.test(target.path)
            ? "pdf"
            : /\.csv$/i.test(target.path)
            ? "csv"
            : isText
            ? "text"
            : "binary";
          const nextContent = isText ? await response.text() : "";
          return {
            metadata: {
              path: target.path,
              size: Number(response.headers.get("Content-Length")) || 0,
              modified_at: response.headers.get("Last-Modified") ?? "",
              preview_kind: previewKind,
              etag: response.headers.get("ETag") ?? "",
            } as FileMetadata,
            content: nextContent,
          };
        })
      : target.source === "workspace"
      ? workspaceApi
          .getFileMetadata(target.path, chatId, target.root, projectDirOverride)
          .then(async (nextMetadata) => {
            const loaded =
              nextMetadata.preview_kind === "text" ||
              nextMetadata.preview_kind === "csv"
                ? await workspaceApi.loadFileText(
                    target.path,
                    chatId,
                    target.root,
                    projectDirOverride,
                  )
                : null;
            return {
              metadata: loaded
                ? { ...nextMetadata, etag: loaded.etag }
                : nextMetadata,
              content: loaded?.content ?? "",
            };
          })
      : target.source === "profile"
      ? workspaceApi.loadFile(target.path).then((file) => ({
          metadata: {
            path: target.path,
            size: new Blob([file.content]).size,
            modified_at: "",
            preview_kind: "text" as const,
            etag: "",
          },
          content: file.content,
        }))
      : target.source === "memory" ||
        target.source === "daily" ||
        target.source === "digest"
      ? (target.source === "daily" || target.source === "digest"
          ? workspaceApi.loadMemoryFile(target.path, target.source)
          : workspaceApi.loadDailyMemory(target.path)
        ).then((file) => ({
          metadata: {
            path: target.path,
            size: new Blob([file.content]).size,
            modified_at: "",
            preview_kind: "text" as const,
            etag: "",
          },
          content: file.content,
        }))
      : Promise.reject(new Error("Unsupported preview source"));
    void loadMetadata
      .then(({ metadata: nextMetadata, content: nextContent }) => {
        if (controller.signal.aborted) return;
        setMetadata(nextMetadata);
        setContent(nextContent);
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setMetadata(null);
          setContent("");
          setLoadFailed(true);
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [chatId, projectDirOverride, target]);

  const resizeFromPointer = (event: React.PointerEvent) => {
    event.preventDefault();
    setIsResizing(true);
    const startX = event.clientX;
    const initial = drawerRef.current?.getBoundingClientRect().width ?? 0;
    const containerWidth =
      drawerRef.current?.parentElement?.getBoundingClientRect().width ??
      window.innerWidth;
    const maximum = Math.max(MIN_DRAWER_WIDTH, containerWidth - MIN_CHAT_WIDTH);
    const move = (nextEvent: PointerEvent) => {
      const next = Math.min(
        Math.max(MIN_DRAWER_WIDTH, initial + nextEvent.clientX - startX),
        maximum,
      );
      setWidth(next);
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      window.removeEventListener("pointercancel", up);
      setIsResizing(false);
      const current = drawerRef.current?.getBoundingClientRect().width;
      if (current) localStorage.setItem(widthStorageKey, String(current));
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    window.addEventListener("pointercancel", up);
  };

  const drawerStyle = width > 0 ? { width: `${width}px` } : undefined;
  const filename = target?.path.split("/").pop() ?? t("files.title");
  const canCopy =
    metadata?.preview_kind === "text" || metadata?.preview_kind === "csv";

  const handleCopy = useCallback(async () => {
    try {
      await copyText(content);
      message.success(t("common.copied"));
    } catch {
      message.error(t("common.copyFailed"));
    }
  }, [content, message, t]);

  return (
    <motion.aside
      ref={drawerRef}
      className={`${styles.drawer} ${
        isWorkspace ? styles.drawerWorkspace : styles.drawerPreview
      } ${isResizing ? styles.drawerResizing : ""}`}
      style={drawerStyle}
      layout={isResizing || prefersReducedMotion ? false : "size"}
      initial={
        prefersReducedMotion ? false : { opacity: 0, x: -18, scale: 0.995 }
      }
      animate={{ opacity: 1, x: 0, scale: 1 }}
      exit={
        prefersReducedMotion
          ? { opacity: 0 }
          : { opacity: 0, x: -14, scale: 0.995 }
      }
      transition={
        prefersReducedMotion
          ? { duration: 0 }
          : {
              layout: {
                type: "spring",
                stiffness: 360,
                damping: 38,
                mass: 0.82,
              },
              opacity: { duration: 0.2, ease: "easeOut" },
              x: { duration: 0.28, ease: [0.22, 0.78, 0.24, 1] },
              scale: { duration: 0.28, ease: [0.22, 0.78, 0.24, 1] },
            }
      }
      role="region"
      aria-label={t("files.title")}
      tabIndex={-1}
    >
      <div
        className={styles.resizeHandle}
        role="separator"
        aria-orientation="vertical"
        aria-label={t("files.resize")}
        aria-valuenow={Math.round(width)}
        tabIndex={0}
        onPointerDown={resizeFromPointer}
        onKeyDown={(event) => {
          if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") {
            return;
          }
          event.preventDefault();
          setWidth((current) => {
            const base = current || 640;
            const containerWidth =
              drawerRef.current?.parentElement?.getBoundingClientRect().width ??
              window.innerWidth;
            const maximum = Math.max(
              MIN_DRAWER_WIDTH,
              containerWidth - MIN_CHAT_WIDTH,
            );
            const next = Math.min(
              Math.max(
                MIN_DRAWER_WIDTH,
                base + (event.key === "ArrowRight" ? 24 : -24),
              ),
              maximum,
            );
            localStorage.setItem(widthStorageKey, String(next));
            return next;
          });
        }}
      />
      <header className={styles.drawerHeader}>
        <div className={styles.fileMark}>
          <FileText size={17} />
        </div>
        <div className={styles.drawerTitle}>
          <strong>{filename}</strong>
          {!isWorkspace && (
            <span>
              {metadata
                ? t("files.previewSize", { size: metadata.size })
                : t("files.preview")}
            </span>
          )}
        </div>
        {isWorkspace && target && (
          <button
            type="button"
            className={styles.secondaryButton}
            onClick={() => dispatch({ type: "COLLAPSE_TO_PREVIEW" })}
          >
            <ArrowLeft size={15} />
            {t("files.backToPreview")}
          </button>
        )}
        {target && canCopy && (
          <button
            type="button"
            className={styles.iconButton}
            aria-label={t("common.copy")}
            onClick={() => void handleCopy()}
          >
            <Copy size={16} />
          </button>
        )}
        {target && (target.source === "workspace" || target.artifactUrl) && (
          <button
            type="button"
            className={styles.iconButton}
            aria-label={t("files.download")}
            onClick={() =>
              void downloadFileFromUrl(
                target.artifactUrl ??
                  workspaceApi.getFileDownloadUrl(target.path, target.root),
                filename,
                {
                  headers: {
                    ...buildAuthHeaders(),
                    ...(chatId ? { "X-Chat-Id": chatId } : {}),
                    ...(!chatId && projectDirOverride
                      ? {
                          "X-Session-Project-Dir": projectDirOverride,
                        }
                      : {}),
                  },
                  errorMessage: t("files.downloadFailed"),
                },
              )
            }
          >
            <Download size={16} />
          </button>
        )}
        <button
          type="button"
          className={styles.iconButton}
          aria-label={t("common.close")}
          onClick={close}
        >
          <X size={17} />
        </button>
      </header>

      <AnimatePresence initial={false} mode="popLayout">
        <motion.div
          key={isWorkspace ? "workspace" : "preview"}
          className={styles.drawerContent}
          initial={
            prefersReducedMotion
              ? false
              : { opacity: 0, x: isWorkspace ? 10 : -10 }
          }
          animate={{ opacity: 1, x: 0 }}
          exit={
            prefersReducedMotion
              ? { opacity: 0 }
              : { opacity: 0, x: isWorkspace ? -8 : 8 }
          }
          transition={
            prefersReducedMotion
              ? { duration: 0 }
              : { duration: 0.2, ease: [0.22, 0.78, 0.24, 1] }
          }
        >
          {isWorkspace ? (
            <Suspense
              fallback={
                <div className={styles.empty}>{t("common.loading")}</div>
              }
            >
              <FilesWorkspace initialTarget={target} scope={scope} />
            </Suspense>
          ) : (
            <>
              <div className={styles.previewSurface} aria-busy={loading}>
                {loading ? (
                  <div className={styles.empty}>{t("common.loading")}</div>
                ) : loadFailed ? (
                  <div className={styles.empty}>{t("files.loadFailed")}</div>
                ) : target && metadata && isPreviewable(target.path) ? (
                  <FilePreview
                    filePath={target.path}
                    content={content}
                    chatId={chatId}
                    binaryUrl={target.artifactUrl}
                    root={target.root}
                    projectDirOverride={projectDirOverride}
                    workspaceBacked={target.source === "workspace"}
                  />
                ) : metadata?.preview_kind === "text" ? (
                  <pre className={styles.textPreview}>{content}</pre>
                ) : (
                  <div className={styles.empty}>
                    {t("files.previewUnavailable")}
                  </div>
                )}
              </div>
              <footer className={styles.drawerFooter}>
                {target && (
                  <button
                    type="button"
                    className={styles.secondaryButton}
                    onClick={() => {
                      insertFileReference(target.path);
                    }}
                  >
                    <MessageSquarePlus size={15} />
                    {t("files.mentionInChat")}
                  </button>
                )}
                {target && (
                  <button
                    type="button"
                    className={styles.primaryButton}
                    onClick={() => dispatch({ type: "EXPAND_WORKSPACE" })}
                  >
                    <Expand size={15} />
                    {t("files.expandWorkspace")}
                  </button>
                )}
              </footer>
            </>
          )}
        </motion.div>
      </AnimatePresence>
    </motion.aside>
  );
}
