import {
  ArrowLeft,
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
import { workspaceApi } from "../../api/modules/workspace";
import { buildAuthHeaders } from "../../api/authHeaders";
import FilePreview, { isPreviewable } from "../../pages/Coding/FilePreview";
import { setTextareaValue } from "../../pages/Chat/utils";
import { downloadFileFromUrl } from "../../utils/downloadFileFromUrl";
import type { FileMetadata, FilesDrawerEvent, FilesDrawerState } from "./types";
import styles from "./FilesWorkspace.module.less";

const PREVIEW_WIDTH_STORAGE_KEY = "qwenpaw-files-preview-width";
const WORKSPACE_WIDTH_STORAGE_KEY = "qwenpaw-files-workspace-width";
const MIN_DRAWER_WIDTH = 420;
const MIN_CHAT_WIDTH = 420;
const FilesWorkspace = lazy(() => import("./FilesWorkspace"));

interface FilesDrawerProps {
  state: Exclude<FilesDrawerState, { kind: "closed" }>;
  dispatch: (event: FilesDrawerEvent) => void;
  chatId?: string;
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
  chatId,
}: FilesDrawerProps) {
  const { t } = useTranslation();
  const drawerRef = useRef<HTMLElement>(null);
  const [metadata, setMetadata] = useState<FileMetadata | null>(null);
  const [content, setContent] = useState("");
  const [loading, setLoading] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);
  const isWorkspace = state.kind === "workspace";
  const isDirect = isWorkspace && state.origin === "files";
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
            /\.(?:md|mdx|txt|csv|json|ya?ml|toml|xml|html|css|less|scss|js|jsx|ts|tsx|py|java|go|rs|sh)$/i.test(
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
          .getFileMetadata(target.path, chatId, target.root)
          .then(async (nextMetadata) => ({
            metadata: nextMetadata,
            content:
              nextMetadata.preview_kind === "text" ||
              nextMetadata.preview_kind === "csv"
                ? await workspaceApi.loadFileText(
                    target.path,
                    chatId,
                    target.root,
                  )
                : "",
          }))
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
      : target.source === "memory"
      ? workspaceApi.loadDailyMemory(target.path).then((file) => ({
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
  }, [chatId, target]);

  const resizeFromPointer = (event: React.PointerEvent) => {
    event.preventDefault();
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
      const current = drawerRef.current?.getBoundingClientRect().width;
      if (current) localStorage.setItem(widthStorageKey, String(current));
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  const drawerStyle =
    width > 0 && !isDirect ? { width: `${width}px` } : undefined;
  const filename = target?.path.split("/").pop() ?? t("files.title");

  return (
    <aside
      ref={drawerRef}
      className={`${styles.drawer} ${
        isWorkspace ? styles.drawerWorkspace : styles.drawerPreview
      } ${isDirect ? styles.drawerDirect : ""}`}
      style={drawerStyle}
      role="region"
      aria-label={t("files.title")}
      tabIndex={-1}
    >
      {!isDirect && (
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
                drawerRef.current?.parentElement?.getBoundingClientRect()
                  .width ?? window.innerWidth;
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
      )}
      <header className={styles.drawerHeader}>
        <div className={styles.fileMark}>
          <FileText size={17} />
        </div>
        <div className={styles.drawerTitle}>
          <strong>{filename}</strong>
          <span>
            {isWorkspace
              ? t("files.workspace")
              : metadata
              ? t("files.previewSize", { size: metadata.size })
              : t("files.preview")}
          </span>
        </div>
        {isWorkspace && state.origin === "chat" && (
          <button
            type="button"
            className={styles.secondaryButton}
            onClick={() => dispatch({ type: "COLLAPSE_TO_PREVIEW" })}
          >
            <ArrowLeft size={15} />
            {t("files.backToPreview")}
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

      {isWorkspace ? (
        <Suspense
          fallback={<div className={styles.empty}>{t("common.loading")}</div>}
        >
          <FilesWorkspace initialTarget={target} chatId={chatId} />
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
                  close();
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
    </aside>
  );
}
