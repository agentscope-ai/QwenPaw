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

import { useState, useRef } from "react";
import { Modal, Tabs, Input, Button, Alert, Progress, List } from "antd";
import { FolderOpen, GitBranch, HardDrive, PlusCircle } from "lucide-react";
import { useTranslation } from "react-i18next";
import { codingProjectApi, type ProjectListItem } from "../../api/modules/codingProject";
import { useProjectDir } from "../../stores/codingModeStore";
import FolderPicker from "./FolderPicker";
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
  currentProjectDir,
  onSelect,
}: {
  currentProjectDir: string | null;
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
      {currentProjectDir && (
        <div className={styles.currentInfo}>
          <span className={styles.currentLabel}>{t("codingMode.currentProject")}:</span>
          <code className={styles.currentPath}>{currentProjectDir}</code>
        </div>
      )}
      <Button type="primary" onClick={() => onSelect(null)} className={styles.actionBtn}>
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
      const res = await codingProjectApi.cloneStream(url.trim(), name.trim() || undefined);
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
      {error && <Alert type="error" message={error} className={styles.alert} showIcon />}
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
      {cloning && <Progress percent={99} status="active" size="small" className={styles.progress} />}
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
// Tab: Open Local Path
// ---------------------------------------------------------------------------

function LocalPathTab({ onSelect }: { onSelect: (path: string) => void }) {
  const { t } = useTranslation();
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleConfirm = async (path: string) => {
    if (!path.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const res = await codingProjectApi.set(path.trim());
      onSelect(res.path);
    } catch (err: unknown) {
      const detail = err instanceof Error ? err.message : "Failed to open path";
      setError(detail);
    } finally {
      setLoading(false);
    }
  };

  const handlePickerSelect = (path: string) => {
    setSelectedPath(path);
  };

  return (
    <div className={styles.tabContent}>
      {/* Folder picker browser */}
      <FolderPicker onSelect={handlePickerSelect} />

      {/* Selected path + confirm */}
      {selectedPath && (
        <>
          {error && <Alert type="error" message={error} className={styles.alert} showIcon />}
          <Button
            type="primary"
            onClick={() => void handleConfirm(selectedPath)}
            loading={loading}
            className={styles.actionBtn}
          >
            {t("codingMode.openBtn")}: {selectedPath.split("/").pop() || selectedPath}
          </Button>
        </>
      )}

      {/* Manual input fallback */}
      <details className={styles.manualDetails}>
        <summary className={styles.manualSummary}>
          {t("codingMode.localPathHint")}
        </summary>
        <Input
          placeholder={t("codingMode.localPathPlaceholder")}
          className={`${styles.input} ${styles.manualInput}`}
          onPressEnter={(e) => void handleConfirm((e.target as HTMLInputElement).value)}
          onBlur={(e) => e.target.value && void handleConfirm(e.target.value)}
        />
      </details>
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
      const detail = err instanceof Error ? err.message : "Failed to create project";
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
      {error && <Alert type="error" message={error} className={styles.alert} showIcon />}
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
            className={`${styles.recentItem} ${item.is_active ? styles.recentItemActive : ""}`}
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
  const { projectDir, setProjectDir } = useProjectDir();
  const [projects, setProjects] = useState<ProjectListItem[]>([]);
  const [activeTab, setActiveTab] = useState("workspace");

  // Load recent projects when modal opens
  const loadProjects = async () => {
    try {
      const list = await codingProjectApi.list();
      setProjects(list);
    } catch {
      // ignore
    }
  };

  const handleOpen = () => {
    void loadProjects();
  };

  const handleConfirm = async (path: string | null) => {
    if (path !== undefined) {
      // path was set via API call already (Local / Create),
      // or explicitly null (workspace default).
      setProjectDir(path);
      onConfirm(path);
    }
  };

  const handlePathSelected = (path: string | null) => {
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
          currentProjectDir={projectDir}
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
      <RecentProjects projects={projects} onSelect={handlePathSelected} />
    </Modal>
  );
}
