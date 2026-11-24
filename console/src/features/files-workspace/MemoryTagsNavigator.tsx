import {
  ArrowLeft,
  ChevronLeft,
  ChevronRight,
  RefreshCw,
  Tag,
} from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { agentsApi } from "../../api/modules/agents";
import type { MemoryTagFilePage, MemoryTagPage } from "../../api/types/agents";
import type { FileSource, FileTarget, WorkspaceRoot } from "./types";
import { workspacePath } from "./fileIdentity";
import type { MemoryFileConfig } from "./useMemoryTagSupport";
import styles from "./FilesWorkspace.module.less";

interface MemoryTagsNavigatorProps {
  agentId: string;
  tag: string | null;
  selectedPath: string;
  selectedSource?: FileSource;
  selectedRoot?: WorkspaceRoot;
  revision: number;
  memoryConfig: MemoryFileConfig;
  onSelectTag: (tag: string | null) => void;
  onOpenFile: (target: FileTarget) => void;
}

export default function MemoryTagsNavigator({
  agentId,
  tag,
  selectedPath,
  selectedSource,
  selectedRoot,
  revision,
  memoryConfig,
  onSelectTag,
  onOpenFile,
}: MemoryTagsNavigatorProps) {
  const { t, i18n } = useTranslation();
  const [page, setPage] = useState(1);
  const [refresh, setRefresh] = useState(0);
  const [data, setData] = useState<MemoryTagPage | MemoryTagFilePage | null>(
    null,
  );
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setFailed(false);
    const pending =
      tag === null
        ? agentsApi.getMemoryTags(agentId, page, controller.signal)
        : agentsApi.getMemoryTagFiles(agentId, tag, page, controller.signal);
    void pending
      .then((result) => {
        if (controller.signal.aborted) return;
        const total =
          "total_files" in result ? result.total_files : result.total_tags;
        const lastPage = Math.max(1, Math.ceil(total / result.page_size));
        if (page > lastPage) {
          setPage(lastPage);
          return;
        }
        setData(result);
      })
      .catch(() => {
        if (!controller.signal.aborted) setFailed(true);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [agentId, tag, page, refresh, revision]);

  useEffect(() => {
    const onFocus = () => setRefresh((value) => value + 1);
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, []);

  const files = data && "total_files" in data ? data : null;
  const selectedWorkspacePath = selectedSource
    ? workspacePath(
        {
          source: selectedSource,
          path: selectedPath,
          root: selectedRoot,
        },
        memoryConfig,
      )
    : null;
  const tags = data && "total_tags" in data ? data : null;
  const total = files?.total_files ?? tags?.total_tags ?? 0;
  const pageCount = data ? Math.max(1, Math.ceil(total / data.page_size)) : 1;

  return (
    <section
      className={styles.tagsNavigator}
      aria-label={t("files.memoryTags")}
    >
      <header className={styles.tagsHeader}>
        {tag !== null && (
          <button
            type="button"
            className={styles.tagBack}
            onClick={() => onSelectTag(null)}
          >
            <ArrowLeft size={14} aria-hidden="true" />
            {t("files.memoryTagsAll")}
          </button>
        )}
        <div className={styles.tagsHeading}>
          <strong>{tag === null ? t("files.memoryTagsAll") : tag}</strong>
          <button
            type="button"
            className={styles.iconButton}
            disabled={loading}
            aria-label={t("files.memoryTagsRefresh")}
            onClick={() => setRefresh((value) => value + 1)}
          >
            <RefreshCw size={14} aria-hidden="true" />
          </button>
        </div>
        <p className={styles.tagsCount}>{t("files.memoryTagsScope")}</p>
        {!loading && !failed && data && (
          <p className={styles.tagsCount} role="status">
            {t(
              tag === null
                ? "files.memoryTagsCount"
                : "files.memoryTagFilesCount",
              { count: total },
            )}
          </p>
        )}
      </header>
      <div className={styles.tree} aria-busy={loading}>
        {loading ? (
          <p role="status">{t("common.loading")}</p>
        ) : failed ? (
          <div role="alert">
            <p>{t("files.memoryTagsLoadFailed")}</p>
            <button
              type="button"
              className={styles.secondaryButton}
              onClick={() => setRefresh((value) => value + 1)}
            >
              {t("common.retry")}
            </button>
          </div>
        ) : total === 0 ? (
          <p>
            {t(
              tag === null
                ? "files.memoryTagsEmpty"
                : "files.memoryTagFilesEmpty",
            )}
          </p>
        ) : (
          <ul className={styles.tagsList}>
            {tags?.items.map((item) => (
              <li key={item.tag}>
                <button
                  type="button"
                  className={styles.tagRow}
                  onClick={() => onSelectTag(item.tag)}
                >
                  <Tag size={14} aria-hidden="true" />
                  <span>{item.tag}</span>
                  <span className={styles.tagFileCount}>{item.file_count}</span>
                </button>
              </li>
            ))}
            {files?.items.map((file) => (
              <li key={file.path}>
                <button
                  type="button"
                  className={styles.tagFileRow}
                  aria-current={
                    file.path === selectedWorkspacePath ? "true" : undefined
                  }
                  onClick={() =>
                    onOpenFile({
                      source: file.source,
                      path: file.relative_path,
                      ...(file.source === "workspace"
                        ? { root: "workspace" as const }
                        : {}),
                    })
                  }
                >
                  <strong>{file.name || file.path.split("/").pop()}</strong>
                  {file.description && (
                    <span className={styles.tagDescription}>
                      {file.description}
                    </span>
                  )}
                  <span className={styles.tagFilePath}>{file.path}</span>
                  <time
                    dateTime={new Date(file.modified_at * 1000).toISOString()}
                  >
                    {new Date(file.modified_at * 1000).toLocaleString(
                      i18n.language,
                    )}
                  </time>
                  <span className={styles.tagFileTags}>
                    {file.memory_tags.join(" · ")}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
      {data && !failed && pageCount > 1 && (
        <footer className={styles.tagsPagination}>
          <button
            type="button"
            className={styles.iconButton}
            disabled={loading || page <= 1}
            aria-label={t("files.memoryTagsPrevious")}
            onClick={() => setPage((value) => value - 1)}
          >
            <ChevronLeft size={16} aria-hidden="true" />
          </button>
          <span>{t("files.memoryTagsPage", { page, total: pageCount })}</span>
          <button
            type="button"
            className={styles.iconButton}
            disabled={loading || page >= pageCount}
            aria-label={t("files.memoryTagsNext")}
            onClick={() => setPage((value) => value + 1)}
          >
            <ChevronRight size={16} aria-hidden="true" />
          </button>
        </footer>
      )}
    </section>
  );
}
