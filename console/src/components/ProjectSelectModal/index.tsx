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
import {
  ChevronRight,
  Folder,
  FolderOpen,
  FolderSymlink,
  GitBranch,
  HardDrive,
  Home,
  Info,
  Loader2,
  PlusCircle,
  RotateCcw,
  TriangleAlert,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  codingProjectApi,
  type BrowseDirsResponse,
  type ProjectListItem,
} from "../../api/modules/codingProject";
import { useProjectDir } from "../../stores/codingModeStore";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

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
// InfoAlert helper – replaces antd Alert
// ---------------------------------------------------------------------------

type AlertType = "info" | "warning" | "error";

function InfoAlert({ type, message }: { type: AlertType; message: string }) {
  const iconMap: Record<AlertType, React.ReactNode> = {
    info: <Info size={14} className="text-blue-500 shrink-0 mt-0.5" />,
    warning: (
      <TriangleAlert size={14} className="text-yellow-500 shrink-0 mt-0.5" />
    ),
    error: (
      <TriangleAlert size={14} className="text-destructive shrink-0 mt-0.5" />
    ),
  };
  const bgMap: Record<AlertType, string> = {
    info: "bg-blue-50 border-blue-200 dark-mode:bg-blue-950/30 dark-mode:border-blue-800",
    warning:
      "bg-yellow-50 border-yellow-200 dark-mode:bg-yellow-950/30 dark-mode:border-yellow-800",
    error:
      "bg-red-50 border-red-200 dark-mode:bg-red-950/30 dark-mode:border-red-800",
  };
  return (
    <div
      className={`flex gap-2 p-3 rounded-md border text-sm mb-3 ${bgMap[type]}`}
    >
      {iconMap[type]}
      <span>{message}</span>
    </div>
  );
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
    <div className="flex flex-col gap-3 mt-3">
      <InfoAlert type="info" message={t("codingMode.workspaceDesc")} />
      {workspaceDir && (
        <div className="flex items-center gap-2 text-sm">
          <span className="text-muted-foreground">
            {t("codingMode.workingDir")}:
          </span>
          <code className="bg-muted px-1.5 py-0.5 rounded text-xs font-mono">
            {workspaceDir}
          </code>
        </div>
      )}
      <Button onClick={() => onSelect(null)}>
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
    <div className="flex flex-col gap-3 mt-3">
      <div className="flex flex-col gap-1">
        <label className="text-xs font-medium text-muted-foreground">
          {t("codingMode.cloneUrl")}
        </label>
        <Input
          placeholder={t("codingMode.cloneUrlPlaceholder")}
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          disabled={cloning}
        />
      </div>
      <div className="flex flex-col gap-1">
        <label className="text-xs font-medium text-muted-foreground">
          {t("codingMode.cloneName")}
        </label>
        <Input
          placeholder={t("codingMode.cloneNamePlaceholder")}
          value={name}
          onChange={(e) => setName(e.target.value)}
          disabled={cloning}
        />
      </div>
      {error && <InfoAlert type="error" message={error} />}
      {logs.length > 0 && (
        <div className="bg-muted rounded-md p-3 max-h-36 overflow-y-auto text-xs font-mono">
          {logs.map((l, i) => (
            // eslint-disable-next-line react/no-array-index-key
            <div key={i} className="leading-relaxed">
              {l}
            </div>
          ))}
          <div ref={logEndRef} />
        </div>
      )}
      <Button
        onClick={() => void handleClone()}
        disabled={cloning || !url.trim()}
      >
        {cloning && <Loader2 size={14} className="animate-spin mr-2" />}
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
    <div className="flex flex-col gap-3 mt-3">
      <InfoAlert type="info" message={t("codingMode.importCopyDesc")} />
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
          <div className="flex items-center gap-2 p-2 rounded-md border bg-muted/40">
            <FolderOpen size={16} className="text-muted-foreground" />
            <span className="flex-1 text-sm truncate">{localSel.name}</span>
            <button
              type="button"
              className="p-0.5 rounded hover:bg-muted"
              onClick={() => {
                setLocalSel(null);
                setError(null);
              }}
            >
              <X size={13} />
            </button>
          </div>
          <InfoAlert type="warning" message={t("codingMode.importCopyNote")} />
          {error && <InfoAlert type="error" message={error} />}
          <Button disabled={loading} onClick={() => void handleImport()}>
            {loading && <Loader2 size={14} className="animate-spin mr-2" />}
            {loading ? t("codingMode.importing") : t("codingMode.openBtn")}
          </Button>
        </>
      ) : (
        <div
          className={`flex flex-col items-center justify-center gap-2 p-8 rounded-lg border-2 border-dashed cursor-pointer transition-colors
            ${
              dragOver
                ? "border-primary bg-primary/5"
                : "border-border hover:border-muted-foreground/50 hover:bg-muted/30"
            }`}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={(e) => void handleDrop(e)}
          onClick={() => dirInputRef.current?.click()}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => e.key === "Enter" && dirInputRef.current?.click()}
        >
          <FolderOpen
            size={36}
            strokeWidth={1.2}
            className="text-muted-foreground"
          />
          <span className="text-sm font-medium">
            {t("codingMode.dropPrimary")}
          </span>
          <span className="text-xs text-muted-foreground">
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
  const listRef = useRef<HTMLDivElement>(null);
  const navSeq = useRef(0);

  const navigate = (path: string) => {
    const seq = ++navSeq.current;
    setBrowsePath(path);
    setLoading(true);
    setError(null);
    codingProjectApi
      .browseDirs(path)
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
  }, []);

  const breadcrumbParts = data?.current.split("/").filter(Boolean) ?? [];

  return (
    <div className="flex flex-col gap-3 mt-3">
      <InfoAlert type="info" message={t("codingMode.openDirDesc")} />

      {/* Quick-access shortcuts */}
      <div className="flex gap-1">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => navigate("~")}
          className="h-7 text-xs gap-1"
        >
          <Home size={12} />
          {t("codingMode.openDirHome")}
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => navigate(browsePath)}
          className="h-7 text-xs gap-1"
        >
          <RotateCcw size={12} />
          {t("codingMode.openDirRefresh")}
        </Button>
      </div>

      {/* Breadcrumb */}
      {data && (
        <div className="flex items-center flex-wrap gap-0.5 text-xs text-muted-foreground">
          <button
            type="button"
            className="hover:text-foreground"
            onClick={() => navigate("/")}
          >
            /
          </button>
          {breadcrumbParts.map((seg, i) => {
            const segPath = "/" + breadcrumbParts.slice(0, i + 1).join("/");
            const isLast = i === breadcrumbParts.length - 1;
            return (
              <span key={segPath} className="flex items-center gap-0.5">
                <ChevronRight size={10} />
                <button
                  type="button"
                  className={
                    isLast
                      ? "text-foreground font-medium"
                      : "hover:text-foreground"
                  }
                  onClick={() => !isLast && navigate(segPath)}
                  disabled={isLast}
                >
                  {seg}
                </button>
              </span>
            );
          })}
        </div>
      )}

      {/* Directory listing */}
      <div
        ref={listRef}
        className="border rounded-md overflow-y-auto max-h-52 divide-y"
      >
        {loading && (
          <div className="flex items-center justify-center gap-2 p-4 text-sm text-muted-foreground">
            <Loader2 size={14} className="animate-spin" />
            {t("codingMode.openDirLoading")}
          </div>
        )}
        {error && (
          <div className="p-2">
            <InfoAlert type="error" message={error} />
          </div>
        )}
        {!loading && !error && data && (
          <>
            {data.parent && (
              <button
                type="button"
                className="w-full flex items-center gap-2 px-3 py-2 text-sm hover:bg-muted/50 text-left"
                onClick={() => navigate(data.parent!)}
              >
                <Folder size={14} className="text-muted-foreground" />
                <span>..</span>
              </button>
            )}
            {data.dirs.length === 0 && !data.parent && (
              <div className="p-4 text-sm text-center text-muted-foreground">
                {t("codingMode.openDirEmpty")}
              </div>
            )}
            {data.dirs.map((dir) => (
              <button
                type="button"
                key={dir.path}
                className="w-full flex items-center gap-2 px-3 py-2 text-sm hover:bg-muted/50 text-left"
                onClick={() => navigate(dir.path)}
              >
                <Folder size={14} className="text-muted-foreground" />
                <span className="flex-1 truncate">{dir.name}</span>
                <ChevronRight size={12} className="text-muted-foreground" />
              </button>
            ))}
          </>
        )}
      </div>

      {/* Confirm button */}
      {data && !loading && data.selectable !== false && (
        <Button onClick={() => onSelect(data.current)}>
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
    <div className="flex flex-col gap-3 mt-3">
      <div className="flex flex-col gap-1">
        <label className="text-xs font-medium text-muted-foreground">
          {t("codingMode.newName")}
        </label>
        <Input
          placeholder={t("codingMode.newNamePlaceholder")}
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </div>
      {error && <InfoAlert type="error" message={error} />}
      <Button
        onClick={() => void handleCreate()}
        disabled={loading || !name.trim()}
      >
        {loading && <Loader2 size={14} className="animate-spin mr-2" />}
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
    <div className="mt-4 border-t pt-3">
      <div className="text-xs font-medium text-muted-foreground mb-2">
        Recent
      </div>
      <div className="flex flex-col divide-y border rounded-md overflow-hidden">
        {projects.map((item) => (
          <button
            key={item.path}
            type="button"
            className={`flex items-center gap-2 px-3 py-2 text-sm text-left hover:bg-muted/50 transition-colors
              ${item.is_active ? "bg-primary/5 font-medium" : ""}`}
            onClick={() => onSelect(item.path)}
          >
            <GitBranch size={12} className="text-muted-foreground shrink-0" />
            <span className="truncate">{item.name}</span>
            <span className="ml-auto text-xs text-muted-foreground truncate max-w-[180px]">
              {item.path}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab definitions
// ---------------------------------------------------------------------------

type TabKey = "workspace" | "clone" | "opendir" | "local" | "new";

interface TabDef {
  key: TabKey;
  icon: React.ReactNode;
  labelKey: string;
}

const TAB_DEFS: TabDef[] = [
  {
    key: "workspace",
    icon: <HardDrive size={13} />,
    labelKey: "codingMode.tabWorkspace",
  },
  {
    key: "clone",
    icon: <GitBranch size={13} />,
    labelKey: "codingMode.tabClone",
  },
  {
    key: "opendir",
    icon: <FolderSymlink size={13} />,
    labelKey: "codingMode.tabOpenDir",
  },
  {
    key: "local",
    icon: <FolderOpen size={13} />,
    labelKey: "codingMode.tabLocal",
  },
  { key: "new", icon: <PlusCircle size={13} />, labelKey: "codingMode.tabNew" },
];

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
  const [activeTab, setActiveTab] = useState<TabKey>("workspace");
  const [workspaceDir, setWorkspaceDir] = useState<string | null>(null);

  const handleOpen = () => {
    codingProjectApi
      .list()
      .then(setProjects)
      .catch(() => undefined);
    codingProjectApi
      .get()
      .then((info) => {
        if (info.workspace_dir) setWorkspaceDir(info.workspace_dir);
      })
      .catch(() => undefined);
  };

  // Trigger data fetch when modal opens
  useEffect(() => {
    if (open) handleOpen();
  }, [open]);

  const handleConfirm = async (path: string | null) => {
    if (path !== undefined) {
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

  const renderTabContent = () => {
    switch (activeTab) {
      case "workspace":
        return (
          <WorkspaceTab
            workspaceDir={workspaceDir}
            onSelect={() => void handleConfirm(null)}
          />
        );
      case "clone":
        return <CloneTab onDone={(p) => void handleCloneDone(p)} />;
      case "opendir":
        return <OpenDirTab onSelect={(p) => void handlePathSelected(p)} />;
      case "local":
        return <LocalPathTab onSelect={handleLocalDone} />;
      case "new":
        return <NewProjectTab onDone={handleNewDone} />;
    }
  };

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="w-[560px] max-w-[95vw] max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t("codingMode.selectProject")}</DialogTitle>
          <DialogDescription className="sr-only">
            {t("codingMode.selectProjectDesc")}
          </DialogDescription>
        </DialogHeader>

        <p className="text-sm text-muted-foreground -mt-1">
          {t("codingMode.selectProjectDesc")}
        </p>

        {/* Tabs */}
        <div className="flex gap-0.5 border-b">
          {TAB_DEFS.map((tab) => (
            <button
              key={tab.key}
              type="button"
              onClick={() => setActiveTab(tab.key)}
              className={`flex items-center gap-1.5 px-3 py-2 text-xs font-medium border-b-2 -mb-px transition-colors whitespace-nowrap
                ${
                  activeTab === tab.key
                    ? "border-primary text-primary"
                    : "border-transparent text-muted-foreground hover:text-foreground"
                }`}
            >
              {tab.icon}
              {t(tab.labelKey)}
            </button>
          ))}
        </div>

        {/* Tab Content */}
        {renderTabContent()}

        {/* Recent projects */}
        <RecentProjects
          projects={projects}
          onSelect={(p) => void handlePathSelected(p)}
        />
      </DialogContent>
    </Dialog>
  );
}
