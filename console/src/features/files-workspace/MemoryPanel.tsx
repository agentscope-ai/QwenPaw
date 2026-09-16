import { Download, FileText, Folder, FolderOpen } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { AgentRequestContext } from "../../api/modules/agentRequestContext";
import { agentApi } from "../../api/modules/agent";
import { workspaceApi } from "../../api/modules/workspace";
import type { MemorySection } from "../../api/types/workspace";
import type { FileLocator } from "./fileLocator";
import {
  resolveMemoryScopeSelection,
  type MemoryScope,
  type MemoryScopeSummary,
} from "./filesWorkspaceScope";
import {
  buildDailyMemoryTree,
  buildMemoryTree,
  type MemoryTreeEntry,
} from "./memoryTree";
import styles from "./PersonalWorkspaceNavigator.module.less";

interface MemoryPanelProps {
  agentId: string;
  requestContext: AgentRequestContext;
  initialLocator?: FileLocator | null;
  onOpen?: (locator: FileLocator) => void;
}

function downloadText(filename: string, content: string): void {
  const url = URL.createObjectURL(
    new Blob([content], { type: "text/markdown;charset=utf-8" }),
  );
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

export default function MemoryPanel({
  agentId,
  requestContext,
  initialLocator,
  onOpen,
}: MemoryPanelProps) {
  const { t } = useTranslation();
  const initialMemory =
    initialLocator?.category === "memory" ? initialLocator : null;
  const [scopes, setScopes] = useState<MemoryScopeSummary[]>([]);
  const [scope, setScope] = useState<MemoryScope>(
    initialMemory?.memoryScope ?? "private",
  );
  const [section, setSection] = useState<MemorySection>(
    initialMemory?.memorySection ?? "daily",
  );
  const [files, setFiles] = useState<MemoryTreeEntry[]>([]);
  const [selectedPath, setSelectedPath] = useState("");
  const [content, setContent] = useState("");
  const [filesLoading, setFilesLoading] = useState(true);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [scopeError, setScopeError] = useState("");
  const [filesError, setFilesError] = useState("");
  const [previewError, setPreviewError] = useState("");
  const onOpenRef = useRef(onOpen);
  const fileListRequestRef = useRef(0);
  const previewRequestRef = useRef(0);
  const openedLocatorRef = useRef("");
  const stableRequestContext = useMemo<AgentRequestContext>(
    () => ({
      ...(requestContext.agentId ? { agentId: requestContext.agentId } : {}),
      ...(requestContext.governance ? { governance: true } : {}),
    }),
    [requestContext.agentId, requestContext.governance],
  );

  useEffect(() => {
    onOpenRef.current = onOpen;
  }, [onOpen]);

  useEffect(() => {
    let active = true;
    setFilesLoading(true);
    setScopeError("");
    setFilesError("");
    setPreviewError("");
    setFiles([]);
    setSelectedPath("");
    setContent("");
    openedLocatorRef.current = "";
    previewRequestRef.current += 1;
    void agentApi
      .getMemoryScopes(agentId, stableRequestContext)
      .then((response) => {
        if (!active) return;
        const readable = response.scopes.filter((item) => item.can_read);
        setScopes(readable);
        setScope((current) =>
          resolveMemoryScopeSelection(
            readable,
            initialMemory?.memoryScope ?? current,
          ),
        );
        if (!readable.length) {
          setScopeError(t("files.fileCenter.noMemoryAccess"));
        }
      })
      .catch(() => {
        if (!active) return;
        setScopes([]);
        setScopeError(t("files.fileCenter.memoryScopeLoadFailed"));
      })
      .finally(() => {
        if (active) setFilesLoading(false);
      });
    return () => {
      active = false;
    };
  }, [agentId, initialMemory?.memoryScope, stableRequestContext, t]);

  useEffect(() => {
    if (!initialMemory) return;
    setScope(initialMemory.memoryScope ?? "private");
    setSection(initialMemory.memorySection ?? "daily");
  }, [
    initialMemory?.memoryScope,
    initialMemory?.memorySection,
    initialMemory?.relativePath,
  ]);

  const loadFiles = useCallback(async () => {
    if (!scopes.some((item) => item.scope === scope)) return;
    const requestId = ++fileListRequestRef.current;
    setFilesLoading(true);
    setFilesError("");
    setPreviewError("");
    setFiles([]);
    setSelectedPath("");
    setContent("");
    openedLocatorRef.current = "";
    previewRequestRef.current += 1;
    try {
      const result = await workspaceApi.listMemoryFiles(
        section,
        scope,
        stableRequestContext,
      );
      if (requestId !== fileListRequestRef.current) return;
      const entries = result.map((file) => ({
        name: file.filename.split("/").pop() ?? file.filename,
        path: file.filename,
        kind: "file" as const,
        size: file.size,
        modified_at: file.modified_time,
        preview_kind: "text",
      }));
      setFiles(
        section === "daily"
          ? buildDailyMemoryTree(entries)
          : buildMemoryTree(entries),
      );
    } catch {
      if (requestId === fileListRequestRef.current) {
        setFilesError(t("files.fileCenter.memoryLoadFailed"));
      }
    } finally {
      if (requestId === fileListRequestRef.current) {
        setFilesLoading(false);
      }
    }
  }, [scope, scopes, section, stableRequestContext, t]);

  useEffect(() => {
    void loadFiles();
  }, [loadFiles]);

  const openFile = useCallback(
    async (path: string, notify = true) => {
      const requestId = ++previewRequestRef.current;
      const locatorKey = `${scope}:${section}:${path}`;
      openedLocatorRef.current = locatorKey;
      setPreviewError("");
      setPreviewLoading(true);
      setSelectedPath(path);
      const locator: FileLocator = {
        category: "memory",
        agentId,
        relativePath: path,
        memoryScope: scope,
        memorySection: section,
      };
      if (notify) onOpenRef.current?.(locator);
      try {
        const loaded = await workspaceApi.loadMemoryFile(
          path,
          section,
          scope,
          stableRequestContext,
        );
        if (requestId === previewRequestRef.current) {
          setContent(loaded.content);
        }
      } catch {
        if (requestId === previewRequestRef.current) {
          setContent("");
          setPreviewError(t("files.fileCenter.memoryPreviewFailed"));
        }
      } finally {
        if (requestId === previewRequestRef.current) {
          setPreviewLoading(false);
        }
      }
    },
    [agentId, scope, section, stableRequestContext, t],
  );

  useEffect(() => {
    if (
      initialMemory &&
      initialMemory.memoryScope === scope &&
      initialMemory.memorySection === section &&
      files.length > 0
    ) {
      const locatorKey = `${scope}:${section}:${initialMemory.relativePath}`;
      if (openedLocatorRef.current !== locatorKey) {
        void openFile(initialMemory.relativePath, false);
      }
    }
  }, [
    files,
    initialMemory?.memoryScope,
    initialMemory?.memorySection,
    initialMemory?.relativePath,
    openFile,
    scope,
    section,
  ]);

  const scopeSummary = useMemo(
    () => scopes.find((item) => item.scope === scope),
    [scope, scopes],
  );

  const renderEntries = (entries: MemoryTreeEntry[], depth = 0) =>
    entries.map((entry) => (
      <div key={`${entry.kind}:${entry.path}`}>
        {entry.kind === "directory" ? (
          <div
            className={styles.memoryDirectory}
            style={{ paddingLeft: depth * 14 }}
          >
            {entry.children?.length ? <FolderOpen size={15} /> : <Folder size={15} />}
            <span>{entry.name}</span>
          </div>
        ) : (
          <button
            type="button"
            className={styles.memoryFile}
            style={{ paddingLeft: 18 + depth * 14 }}
            aria-pressed={selectedPath === entry.path}
            onClick={() => void openFile(entry.path)}
          >
            <FileText size={14} />
            <span>{entry.name}</span>
          </button>
        )}
        {entry.children ? renderEntries(entry.children, depth + 1) : null}
      </div>
    ));

  return (
    <section className={styles.memoryPanel} aria-label={t("files.fileCenter.memory")}>
      <div className={styles.memoryToolbar}>
        <div
          className={styles.memoryFilterGroup}
          role="group"
          aria-label={t("files.fileCenter.memoryScopeLabel")}
        >
          <span className={styles.memoryFilterLabel}>
            {t("files.fileCenter.memoryScopeLabel")}
          </span>
          <div
            role="tablist"
            aria-label={t("files.fileCenter.memoryScopeLabel")}
          >
            {scopes.map((item) => (
              <button
                type="button"
                role="tab"
                aria-selected={scope === item.scope}
                key={item.scope}
                onClick={() => setScope(item.scope)}
              >
                {item.scope === "private" ? t("files.fileCenter.myMemory") : t("files.fileCenter.publicMemory")}
              </button>
            ))}
          </div>
        </div>
        <div
          className={styles.memoryFilterGroup}
          role="group"
          aria-label={t("files.fileCenter.memoryTypeLabel")}
        >
          <span className={styles.memoryFilterLabel}>
            {t("files.fileCenter.memoryTypeLabel")}
          </span>
          <div
            role="tablist"
            aria-label={t("files.fileCenter.memoryTypeLabel")}
          >
            {(["daily", "digest"] as const).map((item) => (
              <button
                type="button"
                role="tab"
                aria-selected={section === item}
                key={item}
                onClick={() => setSection(item)}
              >
                {item === "daily" ? t("files.fileCenter.conversationMemory") : t("files.fileCenter.distilledMemory")}
              </button>
            ))}
          </div>
        </div>
      </div>
      {scopeSummary && scopeSummary.index_state !== "ready" ? (
        <div className={styles.memoryStatus} role="status">
          {t(`files.fileCenter.memoryIndexNotice.${scopeSummary.index_state}`)}
        </div>
      ) : null}
      <div className={styles.memorySectionDescription}>
        {t(`files.fileCenter.memorySectionDescription.${section}`)}
      </div>
      {scopeError || filesError ? (
        <div role="alert" className={styles.memoryStatus}>
          {scopeError || filesError}
        </div>
      ) : null}
      <div className={styles.memoryBody}>
        <aside className={styles.memoryList} aria-busy={filesLoading}>
          {!filesLoading && !scopeError && !filesError && files.length === 0
            ? t("files.fileCenter.noMemoryFiles")
            : null}
          {renderEntries(files)}
        </aside>
        <article className={styles.memoryPreview}>
          {selectedPath ? (
            <header>
              <strong>{selectedPath}</strong>
              <button
                type="button"
                aria-label={`下载 ${selectedPath}`}
                onClick={() => downloadText(selectedPath.split("/").pop() ?? selectedPath, content)}
              >
                <Download size={15} />
              </button>
            </header>
          ) : null}
          {previewError ? (
            <div role="alert" className={styles.memoryPreviewError}>
              {previewError}
            </div>
          ) : null}
          <pre>
            {previewLoading
              ? t("common.loading")
              : content || (selectedPath ? "" : t("files.fileCenter.selectMemory"))}
          </pre>
        </article>
      </div>
    </section>
  );
}
