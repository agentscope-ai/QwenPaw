/**
 * ProjectSelectModal
 *
 * Shown when the user first enters Coding Mode (or clicks "Switch Project").
 * Four tabs:
 *   1. Default Workspace  – use the agent's default workspace_dir
 *   2. Clone Repository   – git clone a public URL with SSE progress
 *   3. Open Local Path    – enter an absolute path
 *   4. New Project        – create an empty dir + git init
 */

import { useState, useRef, useEffect } from "react";
import { Modal, Tabs, Input, Button, Alert, List } from "antd";
import {
  ChevronRight,
  Eye,
  EyeOff,
  Folder,
  FolderOpen,
  FolderSymlink,
  GitBranch,
  HardDrive,
  Home,
  PlusCircle,
  RotateCcw,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  codingProjectApi,
  type BrowseDirsResponse,
  type ProjectListItem,
} from "../../api/modules/codingProject";
import { useProjectDir } from "../../stores/codingModeStore";
import styles from "./index.module.less";

interface ProjectSelectModalProps {
  open: boolean;
  onClose: () => void;
  onConfirm: (path: string | null) => void;
}

// ---------------------------------------------------------------------------
// Clone progress event
// ---------------------------------------------------------------------------

interface CloneEvent {
  type: "log" | "done" | "error";
  line?: string;
  path?: string;
  name?: string;
  detail?: string;
}

// ---------------------------------------------------------------------------
// Tab: Workspace
// ---------------------------------------------------------------------------

function WorkspaceTab({
  workspaceDir,
  onSelect,
}: {
  workspaceDir: string | null;
  onSelect: (path: null) => void;
}) {
  const { t } = useTranslation();
  return (
    <div className={styles.tabContent}>
      <Alert
        type="info"
        showIcon
        message={t("codingMode.workspaceDesc")}
        className={styles.workspaceAlert}
      />
      {workspaceDir && (
        <div className={styles.currentInfo}>
          <span className={styles.currentLabel}>
            {t("codingMode.workingDir")}:
          </span>
          <code className={styles.currentPath}>{workspaceDir}</code>
        </div>
      )}
      <Button
        type="primary"
        onClick={() => onSelect(null)}
        className={styles.actionBtn}
      >
        {t("codingMode.confirmBtn")}
      </Button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab: Clone
// ---------------------------------------------------------------------------

function CloneTab({ onDone }: { onDone: (path: string) => void }) {
  const { t } = useTranslation();
  const [url, setUrl] = useState("");
  const [name, setName] = useState("");
  const [cloning, setCloning] = useState(false);
  const [logs, setLogs] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const logEndRef = useRef<HTMLDivElement>(null);

  const handleClone = async () => {
    if (!url.trim()) return;
    setCloning(true);
    setLogs([]);
    setError(null);
    try {
      const res = await codingProjectApi.cloneStream(
        url.trim(),
        name.trim() || undefined,
      );
      const reader = res.body?.getReader();
      if (!reader) throw new Error("No response body");

      const decoder = new TextDecoder();
      let buf = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const parts = buf.split("\n\n");
        buf = parts.pop() ?? "";
        for (const part of parts) {
          const line = part.startsWith("data: ") ? part.slice(6) : part;
          if (!line.trim()) continue;
          try {
            const evt: CloneEvent = JSON.parse(line);
            if (evt.type === "log" && evt.line) {
              setLogs((prev) => {
                const next = [...prev, evt.line!];
                setTimeout(() => logEndRef.current?.scrollIntoView(), 0);
                return next;
              });
            } else if (evt.type === "done" && evt.path) {
              setCloning(false);
              onDone(evt.path);
              return;
            } else if (evt.type === "error") {
              setError(evt.detail ?? "Unknown error");
              setCloning(false);
              return;
            }
          } catch {
            // ignore non-JSON lines
          }
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setCloning(false);
    }
  };

  return (
    <div className={styles.tabContent}>
      <label className={styles.fieldLabel}>{t("codingMode.cloneUrl")}</label>
      <Input
        placeholder={t("codingMode.cloneUrlPlaceholder")}
        value={url}
        onChange={(e) => setUrl(e.target.value)}
        disabled={cloning}
        className={styles.input}
      />
      <label className={styles.fieldLabel}>{t("codingMode.cloneName")}</label>
      <Input
        placeholder={t("codingMode.cloneNamePlaceholder")}
        value={name}
        onChange={(e) => setName(e.target.value)}
        disabled={cloning}
        className={styles.input}
      />
      {error && (
        <Alert type="error" message={error} className={styles.alert} showIcon />
      )}
      {logs.length > 0 && (
        <div className={styles.logBox}>
          {logs.map((l, i) => (
            // eslint-disable-next-line react/no-array-index-key
            <div key={i} className={styles.logLine}>
              {l}
            </div>
          ))}
          <div ref={logEndRef} />
        </div>
      )}
      <Button
        type="primary"
        onClick={() => void handleClone()}
        loading={cloning}
        disabled={!url.trim()}
        className={styles.actionBtn}
      >
        {cloning ? t("codingMode.cloning") : t("codingMode.cloneBtn")}
      </Button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Helpers for LocalPathTab: read a dropped directory recursively, skipping
// common large / generated directories so we don't upload gigabytes.
// ---------------------------------------------------------------------------

const SKIP_SEGMENTS = new Set([
  "node_modules",
  ".git",
  ".next",
  "dist",
  "build",
  "__pycache__",
  ".cache",
  ".venv",
  "venv",
  ".mypy_cache",
  ".tox",
]);

function shouldSkipPath(path: string): boolean {
  return path.split("/").some((seg) => SKIP_SEGMENTS.has(seg));
}

async function readDirFiltered(
  entry: FileSystemDirectoryEntry,
): Promise<Array<{ path: string; file: File }>> {
  const result: Array<{ path: string; file: File }> = [];
  const reader = entry.createReader();
  const readBatch = (): Promise<FileSystemEntry[]> =>
    new Promise((resolve, reject) => reader.readEntries(resolve, reject));
  let batch: FileSystemEntry[];
  do {
    batch = await readBatch();
    for (const item of batch) {
      if (shouldSkipPath(item.fullPath)) continue;
      if (item.isFile) {
        const file = await new Promise<File>((resolve, reject) =>
          (item as FileSystemFileEntry).file(resolve, reject),
        );
        result.push({ path: item.fullPath.replace(/^\//, ""), file });
      } else if (item.isDirectory) {
        const sub = await readDirFiltered(item as FileSystemDirectoryEntry);
        result.push(...sub);
      }
    }
  } while (batch.length > 0);
  return result;
}

type FolderSelection = {
  name: string;
  entries: Array<{ path: string; file: File }>;
};

// ---------------------------------------------------------------------------
// Tab: Open Local Path
// ---------------------------------------------------------------------------

function LocalPathTab({ onSelect }: { onSelect: (path: string) => void }) {
  const { t } = useTranslation();
  const [localSel, setLocalSel] = useState<FolderSelection | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dirInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const prevent = (e: DragEvent) => e.preventDefault();
    const clear = () => setDragOver(false);
    document.addEventListener("dragover", prevent);
    document.addEventListener("drop", prevent);
    window.addEventListener("dragend", clear);
    window.addEventListener("drop", clear);
    return () => {
      document.removeEventListener("dragover", prevent);
      document.removeEventListener("drop", prevent);
      window.removeEventListener("dragend", clear);
      window.removeEventListener("drop", clear);
    };
  }, []);

  // System folder picker — same hidden input pattern as plugin install modal
  const handleDirPicked = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []).filter(
      (f) => !shouldSkipPath(f.webkitRelativePath),
    );
    if (files.length === 0) return;
    const folderName = files[0].webkitRelativePath.split("/")[0];
    setLocalSel({
      name: folderName,
      entries: files.map((f) => ({ path: f.webkitRelativePath, file: f })),
    });
    e.target.value = "";
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragOver(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragOver(false);
  };

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragOver(false);
    const items = Array.from(e.dataTransfer.items);
    if (items.length === 0) return;
    const entry = items[0].webkitGetAsEntry();
    if (!entry?.isDirectory) return;
    try {
      const entries = await readDirFiltered(entry as FileSystemDirectoryEntry);
      setLocalSel({ name: entry.name, entries });
    } catch {
      setError(t("codingMode.dropFailed"));
    }
  };

  const handleImport = async () => {
    if (!localSel) return;
    setLoading(true);
    setError(null);
    try {
      const { default: JSZip } = await import("jszip");
      const zip = new JSZip();
      for (const { path, file } of localSel.entries) {
        zip.file(path, file);
      }
      const blob = await zip.generateAsync({ type: "blob" });
      const zipFile = new File([blob], `${localSel.name}.zip`, {
        type: "application/zip",
      });
      const res = await codingProjectApi.uploadZip(zipFile, localSel.name);
      onSelect(res.path);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Import failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className={styles.tabContent}>
      <Alert
        type="info"
        showIcon
        message={t("codingMode.importCopyDesc")}
        className={styles.alert}
      />
      <input
        ref={dirInputRef}
        type="file"
        // @ts-expect-error webkitdirectory is not in standard HTML typings
        webkitdirectory=""
        multiple
        style={{ display: "none" }}
        onChange={handleDirPicked}
      />

      {localSel ? (
        <>
          <div className={styles.selectionCard}>
            <FolderOpen size={18} />
            <span className={styles.selectionName}>{localSel.name}</span>
            <Button
              type="text"
              size="small"
              icon={<X size={14} />}
              onClick={() => {
                setLocalSel(null);
                setError(null);
              }}
            />
          </div>
          <Alert
            type="warning"
            showIcon
            message={t("codingMode.importCopyNote")}
            className={styles.alert}
          />
          {error && (
            <Alert
              type="error"
              message={error}
              showIcon
              className={styles.alert}
            />
          )}
          <Button
            type="primary"
            block
            loading={loading}
            onClick={() => void handleImport()}
          >
            {loading ? t("codingMode.importing") : t("codingMode.openBtn")}
          </Button>
        </>
      ) : (
        <div
          className={`${styles.dropZone} ${
            dragOver ? styles.dropZoneActive : ""
          }`}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={(e) => void handleDrop(e)}
          onClick={() => dirInputRef.current?.click()}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => e.key === "Enter" && dirInputRef.current?.click()}
        >
          <FolderOpen size={36} strokeWidth={1.2} className={styles.dropIcon} />
          <span className={styles.dropPrimary}>
            {t("codingMode.dropPrimary")}
          </span>
          <span className={styles.dropSecondary}>
            {t("codingMode.dropSecondary")}
          </span>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab: Open Existing Directory (server-side file browser, no copy)
// ---------------------------------------------------------------------------

function OpenDirTab({ onSelect }: { onSelect: (path: string) => void }) {
  const { t } = useTranslation();
  const [browsePath, setBrowsePath] = useState<string>("~");
  const [data, setData] = useState<BrowseDirsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showHidden, setShowHidden] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);
  const navSeq = useRef(0);

  const navigate = (path: string) => {
    const seq = ++navSeq.current;
    setBrowsePath(path);
    setLoading(true);
    setError(null);
    codingProjectApi
      .browseDirs(path, showHidden)
      .then((res) => {
        if (seq !== navSeq.current) return;
        setData(res);
        listRef.current?.scrollTo(0, 0);
      })
      .catch((err: unknown) => {
        if (seq !== navSeq.current) return;
        setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (seq === navSeq.current) setLoading(false);
      });
  };

  useEffect(() => {
    navigate("~");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Re-fetch current directory when the hidden-folders toggle changes.
  // navSeq already discards stale responses, so unconditional re-fetch is safe.
  useEffect(() => {
    navigate(browsePath);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showHidden]);

  const breadcrumbParts = data?.current.split("/").filter(Boolean) ?? [];

  return (
    <div className={styles.tabContent}>
      <Alert
        type="info"
        showIcon
        message={t("codingMode.openDirDesc")}
        className={styles.alert}
      />

      {/* Quick-access shortcuts */}
      <div className={styles.browseShortcuts}>
        <Button
          size="small"
          type="text"
          icon={<Home size={13} />}
          onClick={() => navigate("~")}
        >
          {t("codingMode.openDirHome")}
        </Button>
        <Button
          size="small"
          type="text"
          icon={<RotateCcw size={13} />}
          onClick={() => navigate(browsePath)}
        >
          {t("codingMode.openDirRefresh")}
        </Button>
        <Button
          size="small"
          type={showHidden ? "primary" : "text"}
          icon={showHidden ? <Eye size={13} /> : <EyeOff size={13} />}
          onClick={() => setShowHidden((v) => !v)}
        >
          {t("codingMode.openDirHiddenFolders")}
        </Button>
      </div>

      {/* Breadcrumb */}
      {data && (
        <div className={styles.browseBreadcrumb}>
          <span
            className={styles.breadcrumbSeg}
            onClick={() => navigate("/")}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                navigate("/");
              }
            }}
          >
            /
          </span>
          {breadcrumbParts.map((seg, i) => {
            const segPath = "/" + breadcrumbParts.slice(0, i + 1).join("/");
            const isLast = i === breadcrumbParts.length - 1;
            return (
              <span key={segPath} className={styles.breadcrumbItem}>
                <ChevronRight size={11} className={styles.breadcrumbSep} />
                <span
                  className={`${styles.breadcrumbSeg} ${
                    isLast ? styles.breadcrumbCurrent : ""
                  }`}
                  onClick={() => !isLast && navigate(segPath)}
                  role={isLast ? undefined : "button"}
                  tabIndex={isLast ? undefined : 0}
                  onKeyDown={(e) => {
                    if (!isLast && (e.key === "Enter" || e.key === " ")) {
                      e.preventDefault();
                      navigate(segPath);
                    }
                  }}
                >
                  {seg}
                </span>
              </span>
            );
          })}
        </div>
      )}

      {/* Directory listing */}
      <div className={styles.browseList} ref={listRef}>
        {loading && (
          <div className={styles.browseEmpty}>
            {t("codingMode.openDirLoading")}
          </div>
        )}
        {error && (
          <Alert
            type="error"
            message={error}
            showIcon
            className={styles.alert}
          />
        )}
        {!loading && !error && data && (
          <>
            {data.parent && (
              <div
                className={styles.browseItem}
                onClick={() => navigate(data.parent!)}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    navigate(data.parent!);
                  }
                }}
              >
                <Folder size={15} className={styles.browseItemIcon} />
                <span className={styles.browseItemName}>..</span>
              </div>
            )}
            {data.dirs.length === 0 && !data.parent && (
              <div className={styles.browseEmpty}>
                {t("codingMode.openDirEmpty")}
              </div>
            )}
            {data.dirs.map((dir) => (
              <div
                key={dir.path}
                className={styles.browseItem}
                onClick={() => navigate(dir.path)}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    navigate(dir.path);
                  }
                }}
              >
                <Folder size={15} className={styles.browseItemIcon} />
                <span className={styles.browseItemName}>{dir.name}</span>
                <ChevronRight size={13} className={styles.browseItemChevron} />
              </div>
            ))}
          </>
        )}
      </div>

      {/* Confirm button */}
      {data && !loading && data.selectable !== false && (
        <Button
          type="primary"
          onClick={() => onSelect(data.current)}
          className={styles.actionBtn}
        >
          {t("codingMode.openDirBtn")}
        </Button>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab: New Project
// ---------------------------------------------------------------------------

function NewProjectTab({ onDone }: { onDone: (path: string) => void }) {
  const { t } = useTranslation();
  const [name, setName] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleCreate = async () => {
    if (!name.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const res = await codingProjectApi.create(name.trim());
      onDone(res.path);
    } catch (err: unknown) {
      const detail =
        err instanceof Error ? err.message : "Failed to create project";
      setError(detail);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className={styles.tabContent}>
      <label className={styles.fieldLabel}>{t("codingMode.newName")}</label>
      <Input
        placeholder={t("codingMode.newNamePlaceholder")}
        value={name}
        onChange={(e) => setName(e.target.value)}
        className={styles.input}
      />
      {error && (
        <Alert type="error" message={error} className={styles.alert} showIcon />
      )}
      <Button
        type="primary"
        onClick={() => void handleCreate()}
        loading={loading}
        disabled={!name.trim()}
        className={styles.actionBtn}
      >
        {t("codingMode.createBtn")}
      </Button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Recent Projects list (shown below tabs)
// ---------------------------------------------------------------------------

function RecentProjects({
  projects,
  onSelect,
}: {
  projects: ProjectListItem[];
  onSelect: (path: string) => void;
}) {
  if (projects.length === 0) return null;
  return (
    <div className={styles.recentWrap}>
      <div className={styles.recentTitle}>Recent</div>
      <List
        size="small"
        dataSource={projects}
        renderItem={(item) => (
          <List.Item
            className={`${styles.recentItem} ${
              item.is_active ? styles.recentItemActive : ""
            }`}
            onClick={() => onSelect(item.path)}
          >
            <GitBranch size={13} className={styles.recentIcon} />
            <span className={styles.recentName}>{item.name}</span>
            <span className={styles.recentPath}>{item.path}</span>
          </List.Item>
        )}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Modal
// ---------------------------------------------------------------------------

export default function ProjectSelectModal({
  open,
  onClose,
  onConfirm,
}: ProjectSelectModalProps) {
  const { t } = useTranslation();
  const { setProjectDir } = useProjectDir();
  const [projects, setProjects] = useState<ProjectListItem[]>([]);
  const [activeTab, setActiveTab] = useState("workspace");
  // The agent's default workspace directory (fetched from backend)
  const [workspaceDir, setWorkspaceDir] = useState<string | null>(null);

  const handleOpen = () => {
    codingProjectApi
      .list()
      .then(setProjects)
      .catch(() => undefined);
    // GET returns workspace_dir field alongside the active project
    codingProjectApi
      .get()
      .then((info) => {
        if (info.workspace_dir) setWorkspaceDir(info.workspace_dir);
      })
      .catch(() => undefined);
  };

  const handleConfirm = async (path: string | null) => {
    if (path !== undefined) {
      // For workspace default (path === null), explicitly reset on backend too
      if (path === null) {
        try {
          await codingProjectApi.set(null);
        } catch {
          // ignore – best effort
        }
      }
      setProjectDir(path);
      onConfirm(path);
    }
  };

  const handlePathSelected = async (path: string) => {
    try {
      await codingProjectApi.set(path);
    } catch {
      // best effort
    }
    setProjectDir(path);
    onConfirm(path);
  };

  const handleCloneDone = async (path: string) => {
    // After clone, the server already set the active project; update store.
    setProjectDir(path);
    onConfirm(path);
  };

  const handleLocalDone = (path: string) => {
    setProjectDir(path);
    onConfirm(path);
  };

  const handleNewDone = (path: string) => {
    setProjectDir(path);
    onConfirm(path);
  };

  const tabItems = [
    {
      key: "workspace",
      label: (
        <span className={styles.tabLabel}>
          <HardDrive size={13} />
          {t("codingMode.tabWorkspace")}
        </span>
      ),
      children: (
        <WorkspaceTab
          workspaceDir={workspaceDir}
          onSelect={() => void handleConfirm(null)}
        />
      ),
    },
    {
      key: "clone",
      label: (
        <span className={styles.tabLabel}>
          <GitBranch size={13} />
          {t("codingMode.tabClone")}
        </span>
      ),
      children: <CloneTab onDone={(p) => void handleCloneDone(p)} />,
    },
    {
      key: "opendir",
      label: (
        <span className={styles.tabLabel}>
          <FolderSymlink size={13} />
          {t("codingMode.tabOpenDir")}
        </span>
      ),
      children: <OpenDirTab onSelect={(p) => void handlePathSelected(p)} />,
    },
    {
      key: "local",
      label: (
        <span className={styles.tabLabel}>
          <FolderOpen size={13} />
          {t("codingMode.tabLocal")}
        </span>
      ),
      children: <LocalPathTab onSelect={handleLocalDone} />,
    },
    {
      key: "new",
      label: (
        <span className={styles.tabLabel}>
          <PlusCircle size={13} />
          {t("codingMode.tabNew")}
        </span>
      ),
      children: <NewProjectTab onDone={handleNewDone} />,
    },
  ];

  return (
    <Modal
      open={open}
      title={t("codingMode.selectProject")}
      onCancel={onClose}
      footer={null}
      width={560}
      afterOpenChange={(isOpen) => isOpen && handleOpen()}
      className={styles.modal}
    >
      <p className={styles.desc}>{t("codingMode.selectProjectDesc")}</p>
      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        items={tabItems}
        size="small"
      />
      <RecentProjects
        projects={projects}
        onSelect={(p) => void handlePathSelected(p)}
      />
    </Modal>
  );
}
