import { Button, Input, Popover, Tooltip } from "antd";
import {
  ArrowUp,
  Check,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  Folder,
  FolderOpen,
  LoaderCircle,
  RotateCw,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  chatProjectDirectoryApi,
  type EffectiveProjectDirectory,
} from "../../api/modules/chatProjectDirectory";
import { projectDirectoryApi } from "../../api/modules/projectDirectory";
import { useProjectDirectoryStore } from "../../stores/projectDirectoryStore";
import type {
  BrowseDirsResponse,
  ProjectListItem,
} from "../../api/modules/projectDirectory";
import styles from "./SessionProjectDirectory.module.less";
import {
  getPendingProjectDirectory,
  setPendingProjectDirectory,
} from "./pendingProjectDirectory";
import type { FilesWorkspaceScope } from "../files-workspace/filesWorkspaceScope";
import { notifyProjectDirectoryChanged } from "./projectDirectoryChangeEvent";

interface SessionProjectDirectoryProps {
  scope: FilesWorkspaceScope;
  compact?: boolean;
  showFullPath?: boolean;
  beforeChange?: () => boolean | Promise<boolean>;
  onChanged?: () => void;
}

export default function SessionProjectDirectory({
  scope,
  compact = false,
  showFullPath = false,
  beforeChange,
  onChanged,
}: SessionProjectDirectoryProps) {
  const { t } = useTranslation();
  const selectedAgent = scope.agentId;
  const chatId = scope.kind === "session" ? scope.chatId : undefined;
  const sessionId = scope.kind === "session" ? scope.sessionId : "";
  const isAgentScope = scope.kind === "agent";
  const [info, setInfo] = useState<EffectiveProjectDirectory | null>(null);
  const [draft, setDraft] = useState("");
  const draftRef = useRef("");
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [projects, setProjects] = useState<ProjectListItem[]>([]);
  const [selectedRecentPath, setSelectedRecentPath] = useState<string | null>(
    null,
  );
  const [browser, setBrowser] = useState<BrowseDirsResponse | null>(null);
  const [browseLoading, setBrowseLoading] = useState(false);
  const announceChanged = () => {
    notifyProjectDirectoryChanged(scope);
    onChanged?.();
  };
  const updateDraft = useCallback((path: string) => {
    draftRef.current = path;
    setDraft(path);
  }, []);

  const refresh = useCallback(async () => {
    if (isAgentScope) {
      const next = await projectDirectoryApi.get();
      const fallback: EffectiveProjectDirectory = {
        project_dir: next.path,
        source: next.is_workspace_default ? "workspace_fallback" : "agent",
        agent_project_dir: next.is_workspace_default ? null : next.path,
        exists: next.exists ?? true,
      };
      setInfo(fallback);
      updateDraft(fallback.project_dir);
      return;
    }
    if (chatId) {
      const next = await chatProjectDirectoryApi.get(chatId);
      setInfo(next);
      updateDraft(next.project_dir);
      return;
    }
    const next = await projectDirectoryApi.get();
    const pending = getPendingProjectDirectory(selectedAgent, sessionId);
    const fallback: EffectiveProjectDirectory = {
      project_dir: pending ?? next.path,
      source: pending
        ? "session"
        : next.is_workspace_default
        ? "workspace_fallback"
        : "agent",
      agent_project_dir: next.is_workspace_default ? null : next.path,
      exists: next.exists ?? true,
    };
    setInfo(fallback);
    updateDraft(fallback.project_dir);
  }, [chatId, isAgentScope, selectedAgent, sessionId, updateDraft]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const browse = useCallback(
    async (path?: string, selectCurrent = false) => {
      setBrowseLoading(true);
      try {
        const next = await projectDirectoryApi.browseDirs(path);
        setBrowser(next);
        if (selectCurrent) {
          updateDraft(next.current);
          setSelectedRecentPath(null);
        }
      } finally {
        setBrowseLoading(false);
      }
    },
    [updateDraft],
  );

  useEffect(() => {
    if (!open) return;
    const currentPath = info?.project_dir ?? "";
    void projectDirectoryApi
      .list()
      .then((nextProjects) => {
        setProjects(nextProjects);
        setSelectedRecentPath(
          draftRef.current === currentPath &&
            nextProjects.some((project) => project.path === currentPath)
            ? currentPath
            : null,
        );
      })
      .catch(() => {
        setProjects([]);
        setSelectedRecentPath(null);
      });
    void browse(currentPath || undefined);
  }, [browse, info?.project_dir, open]);

  const basename = useMemo(() => {
    const path = info?.project_dir.replace(/[\\/]+$/, "") ?? "";
    return path.split(/[\\/]/).pop() || path || t("files.workspace");
  }, [info?.project_dir, t]);

  const selectedRecentProject = useMemo(
    () =>
      projects.find((project) => project.path === selectedRecentPath) ?? null,
    [projects, selectedRecentPath],
  );

  const selectRecentProject = (project: ProjectListItem) => {
    updateDraft(project.path);
    setSelectedRecentPath(project.path);
    void browse(project.path);
  };

  const selectCustomPath = (path: string) => {
    updateDraft(path);
    setSelectedRecentPath(null);
  };

  const clearDraft = () => {
    updateDraft("");
    setSelectedRecentPath(null);
  };

  const save = async () => {
    if (!draft.trim()) return;
    if (beforeChange && !(await beforeChange())) return;
    if (isAgentScope) {
      setSaving(true);
      try {
        const next = await projectDirectoryApi.set(draft.trim());
        useProjectDirectoryStore
          .getState()
          .setProjectDir(selectedAgent, next.path);
        setInfo({
          project_dir: next.path,
          source: next.is_workspace_default ? "workspace_fallback" : "agent",
          agent_project_dir: next.is_workspace_default ? null : next.path,
          exists: next.exists ?? true,
        });
        updateDraft(next.path);
        setOpen(false);
        announceChanged();
      } finally {
        setSaving(false);
      }
      return;
    }
    if (!chatId) {
      setPendingProjectDirectory(selectedAgent, sessionId, draft.trim());
      setInfo((current) => ({
        project_dir: draft.trim(),
        source: "session",
        agent_project_dir: current?.agent_project_dir ?? null,
        exists: true,
      }));
      setOpen(false);
      announceChanged();
      return;
    }
    setSaving(true);
    try {
      const next = await chatProjectDirectoryApi.set(chatId, draft.trim());
      setInfo(next);
      updateDraft(next.project_dir);
      setOpen(false);
      announceChanged();
    } finally {
      setSaving(false);
    }
  };

  const clear = async () => {
    if (beforeChange && !(await beforeChange())) return;
    if (isAgentScope) {
      setSaving(true);
      try {
        await projectDirectoryApi.set(null);
        useProjectDirectoryStore.getState().setProjectDir(selectedAgent, null);
        await refresh();
        setOpen(false);
        announceChanged();
      } finally {
        setSaving(false);
      }
      return;
    }
    if (!chatId) {
      setPendingProjectDirectory(selectedAgent, sessionId, null);
      await refresh();
      setOpen(false);
      announceChanged();
      return;
    }
    setSaving(true);
    try {
      const next = await chatProjectDirectoryApi.clear(chatId);
      setInfo(next);
      updateDraft(next.project_dir);
      setOpen(false);
      announceChanged();
    } finally {
      setSaving(false);
    }
  };

  const panel = (
    <div className={styles.panel}>
      <div className={styles.panelHeading}>
        <span className={styles.headingIcon}>
          <FolderOpen size={18} />
        </span>
        <div>
          <strong>
            {t(
              isAgentScope
                ? "projectDirectory.agentTitle"
                : "projectDirectory.sessionTitle",
            )}
          </strong>
        </div>
      </div>

      {selectedRecentProject ? (
        <div className={styles.pathChip}>
          <span className={styles.pathChipIcon}>
            <Folder size={16} />
          </span>
          <span className={styles.pathChipCopy}>
            <strong>{selectedRecentProject.name}</strong>
            <small>{selectedRecentProject.path}</small>
          </span>
          <button
            type="button"
            className={styles.pathChipClear}
            aria-label={t("projectDirectory.clearSelection")}
            onClick={clearDraft}
          >
            <X size={15} />
          </button>
        </div>
      ) : (
        <Input
          className={styles.pathInput}
          prefix={<Folder size={15} />}
          value={draft}
          onChange={(event) => selectCustomPath(event.target.value)}
          placeholder={t("projectDirectory.pathPlaceholder")}
          onPressEnter={() => void save()}
          allowClear
        />
      )}

      <div className={styles.splitBody}>
        <section className={styles.recentPane}>
          <div className={styles.sectionHeading}>
            <strong>{t("projectDirectory.recentProjects")}</strong>
            <span>{projects.length}</span>
          </div>
          <div className={styles.recent}>
            {projects.slice(0, 6).map((project) => {
              const selected = selectedRecentPath === project.path;
              return (
                <button
                  type="button"
                  key={project.path}
                  className={selected ? styles.recentSelected : undefined}
                  aria-pressed={selected}
                  onClick={() => selectRecentProject(project)}
                >
                  <span className={styles.recentIcon}>
                    <Folder size={15} />
                  </span>
                  <span className={styles.recentCopy}>
                    <strong>{project.name}</strong>
                    <small>{project.path}</small>
                  </span>
                  <span className={styles.recentCheck}>
                    {selected && <Check size={11} />}
                  </span>
                </button>
              );
            })}
            {projects.length === 0 && (
              <small className={styles.emptyState}>
                {t("projectDirectory.noRecentProjects")}
              </small>
            )}
          </div>
        </section>

        <section className={styles.browserPane}>
          <div className={styles.browserHeading}>
            <div>
              <strong>{t("projectDirectory.browseDirectory")}</strong>
              {browser && (
                <code title={browser.current}>{browser.current}</code>
              )}
            </div>
            <div className={styles.browserActions}>
              <Button
                type="text"
                size="small"
                aria-label={t("projectDirectory.homeDirectory")}
                icon={<FolderOpen size={14} />}
                onClick={() => void browse("~", true)}
              />
              <Button
                type="text"
                size="small"
                disabled={!browser?.parent}
                aria-label={t("projectDirectory.parentDirectory")}
                icon={<ArrowUp size={14} />}
                onClick={() => void browse(browser?.parent ?? undefined, true)}
              />
              <Button
                type="text"
                size="small"
                aria-label={t("projectDirectory.refreshDirectory")}
                icon={
                  <RotateCw
                    className={browseLoading ? styles.spin : undefined}
                    size={14}
                  />
                }
                onClick={() => void browse(browser?.current ?? draft)}
              />
            </div>
          </div>

          <div className={styles.directories}>
            {browseLoading && !browser && (
              <span className={styles.browserLoading}>
                <LoaderCircle className={styles.spin} size={16} />
              </span>
            )}
            {browser?.dirs.map((directory) => {
              const selected = !selectedRecentPath && draft === directory.path;
              return (
                <button
                  type="button"
                  key={directory.path}
                  className={selected ? styles.directorySelected : undefined}
                  aria-pressed={selected}
                  onClick={() => selectCustomPath(directory.path)}
                  onDoubleClick={() => void browse(directory.path, true)}
                >
                  <Folder size={15} />
                  <span>{directory.name}</span>
                  {selected ? <Check size={12} /> : <ChevronRight size={13} />}
                </button>
              );
            })}
            {browser && browser.dirs.length === 0 && (
              <small className={styles.emptyState}>
                {t("codingMode.openDirEmpty")}
              </small>
            )}
          </div>
        </section>
      </div>

      <div className={styles.actions}>
        <Button
          type="text"
          onClick={() => void clear()}
          disabled={
            isAgentScope
              ? info?.source === "workspace_fallback"
              : info?.source !== "session"
          }
        >
          {t(
            isAgentScope
              ? "projectDirectory.useWorkspace"
              : "projectDirectory.inheritAgent",
          )}
        </Button>
        <Button
          type="primary"
          loading={saving}
          onClick={() => void save()}
          disabled={!draft.trim()}
        >
          {t("common.apply")}
        </Button>
      </div>
    </div>
  );

  return (
    <Popover
      content={panel}
      trigger="click"
      open={open}
      onOpenChange={setOpen}
      placement={isAgentScope ? "rightTop" : "topRight"}
    >
      <Tooltip title={info?.project_dir}>
        <button
          type="button"
          className={`${styles.trigger} ${
            info && !info.exists ? styles.triggerError : ""
          } ${compact ? styles.triggerCompact : ""} ${
            showFullPath ? styles.triggerFullPath : ""
          }`}
          aria-label={t(
            isAgentScope
              ? "projectDirectory.agentTitle"
              : "projectDirectory.sessionTitle",
          )}
        >
          {!info ? (
            <LoaderCircle className={styles.spin} size={14} />
          ) : info.exists ? (
            <FolderOpen size={14} />
          ) : (
            <CircleAlert size={14} />
          )}
          {!compact && (
            <>
              {showFullPath ? (
                <span className={styles.triggerIdentity}>
                  <strong>{basename}</strong>
                  <small>{info?.project_dir}</small>
                </span>
              ) : (
                <span>{basename}</span>
              )}
              {!showFullPath && (
                <em>
                  {t(
                    info?.source === "session"
                      ? "projectDirectory.sessionSource"
                      : "projectDirectory.agentSource",
                  )}
                </em>
              )}
              <ChevronDown size={12} />
            </>
          )}
        </button>
      </Tooltip>
    </Popover>
  );
}
