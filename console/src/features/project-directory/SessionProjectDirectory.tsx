import { Button, Input, Popover, Tooltip } from "antd";
import {
  ArrowUp,
  ChevronDown,
  CircleAlert,
  Folder,
  FolderOpen,
  LoaderCircle,
  RotateCw,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  chatProjectDirectoryApi,
  type EffectiveProjectDirectory,
} from "../../api/modules/chatProjectDirectory";
import { projectDirectoryApi } from "../../api/modules/projectDirectory";
import { useAgentStore } from "../../stores/agentStore";
import type {
  BrowseDirsResponse,
  ProjectListItem,
} from "../../api/modules/projectDirectory";
import styles from "./SessionProjectDirectory.module.less";
import {
  getPendingProjectDirectory,
  setPendingProjectDirectory,
} from "./pendingProjectDirectory";

interface SessionProjectDirectoryProps {
  chatId?: string;
  compact?: boolean;
  showFullPath?: boolean;
  onChanged?: () => void;
}

export default function SessionProjectDirectory({
  chatId,
  compact = false,
  showFullPath = false,
  onChanged,
}: SessionProjectDirectoryProps) {
  const { t } = useTranslation();
  const selectedAgent = useAgentStore((state) => state.selectedAgent);
  const [info, setInfo] = useState<EffectiveProjectDirectory | null>(null);
  const [draft, setDraft] = useState("");
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [projects, setProjects] = useState<ProjectListItem[]>([]);
  const [browser, setBrowser] = useState<BrowseDirsResponse | null>(null);
  const [browseLoading, setBrowseLoading] = useState(false);

  const refresh = useCallback(async () => {
    if (chatId) {
      const next = await chatProjectDirectoryApi.get(chatId);
      setInfo(next);
      setDraft(next.project_dir);
      return;
    }
    const next = await projectDirectoryApi.get();
    const pending = getPendingProjectDirectory(selectedAgent);
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
    setDraft(fallback.project_dir);
  }, [chatId, selectedAgent]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const browse = useCallback(async (path?: string) => {
    setBrowseLoading(true);
    try {
      setBrowser(await projectDirectoryApi.browseDirs(path));
    } finally {
      setBrowseLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!open) return;
    void projectDirectoryApi
      .list()
      .then(setProjects)
      .catch(() => setProjects([]));
  }, [open]);

  const basename = useMemo(() => {
    const path = info?.project_dir.replace(/[\\/]+$/, "") ?? "";
    return path.split(/[\\/]/).pop() || path || t("files.workspace");
  }, [info?.project_dir, t]);

  const save = async () => {
    if (!draft.trim()) return;
    if (!chatId) {
      setPendingProjectDirectory(selectedAgent, draft.trim());
      setInfo((current) => ({
        project_dir: draft.trim(),
        source: "session",
        agent_project_dir: current?.agent_project_dir ?? null,
        exists: true,
      }));
      setOpen(false);
      onChanged?.();
      return;
    }
    setSaving(true);
    try {
      const next = await chatProjectDirectoryApi.set(chatId, draft.trim());
      setInfo(next);
      setDraft(next.project_dir);
      setOpen(false);
      onChanged?.();
    } finally {
      setSaving(false);
    }
  };

  const clear = async () => {
    if (!chatId) {
      setPendingProjectDirectory(selectedAgent, null);
      await refresh();
      setOpen(false);
      onChanged?.();
      return;
    }
    setSaving(true);
    try {
      const next = await chatProjectDirectoryApi.clear(chatId);
      setInfo(next);
      setDraft(next.project_dir);
      setOpen(false);
      onChanged?.();
    } finally {
      setSaving(false);
    }
  };

  const panel = (
    <div className={styles.panel}>
      <div className={styles.panelHeading}>
        <FolderOpen size={17} />
        <div>
          <strong>{t("projectDirectory.sessionTitle")}</strong>
          <span>{t("projectDirectory.sessionDescription")}</span>
        </div>
      </div>
      <Input
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        placeholder={t("projectDirectory.pathPlaceholder")}
        onPressEnter={() => void save()}
      />
      {projects.length > 0 && (
        <div className={styles.recent}>
          <span>{t("codingMode.currentProject")}</span>
          {projects.slice(0, 4).map((project) => (
            <button
              type="button"
              key={project.path}
              onClick={() => setDraft(project.path)}
            >
              <Folder size={13} />
              <strong>{project.name}</strong>
              <small>{project.path}</small>
            </button>
          ))}
        </div>
      )}
      <div className={styles.browser}>
        <div className={styles.browserBar}>
          <Button
            type="text"
            size="small"
            icon={<FolderOpen size={14} />}
            onClick={() => void browse(browser?.current ?? draft)}
          >
            {t("codingMode.tabOpenDir")}
          </Button>
          {browser && (
            <>
              <Button
                type="text"
                size="small"
                aria-label={t("codingMode.openDirHome")}
                icon={<Folder size={14} />}
                onClick={() => void browse("~")}
              />
              <Button
                type="text"
                size="small"
                disabled={!browser.parent}
                aria-label={t("common.back")}
                icon={<ArrowUp size={14} />}
                onClick={() => void browse(browser.parent ?? undefined)}
              />
              <Button
                type="text"
                size="small"
                aria-label={t("codingMode.openDirRefresh")}
                icon={
                  <RotateCw
                    className={browseLoading ? styles.spin : undefined}
                    size={14}
                  />
                }
                onClick={() => void browse(browser.current)}
              />
            </>
          )}
        </div>
        {browser && (
          <>
            <code>{browser.current}</code>
            <div className={styles.directories}>
              {browser.dirs.map((directory) => (
                <button
                  type="button"
                  key={directory.path}
                  onClick={() => void browse(directory.path)}
                  onDoubleClick={() => setDraft(directory.path)}
                >
                  <Folder size={13} />
                  <span>{directory.name}</span>
                </button>
              ))}
              {browser.dirs.length === 0 && (
                <small>{t("codingMode.openDirEmpty")}</small>
              )}
            </div>
            <Button
              block
              onClick={() => setDraft(browser.current)}
              icon={<FolderOpen size={14} />}
            >
              {t("codingMode.openDirBtn")}
            </Button>
          </>
        )}
      </div>
      <div className={styles.actions}>
        <Button
          type="text"
          onClick={() => void clear()}
          disabled={info?.source !== "session"}
        >
          {t("projectDirectory.inheritAgent")}
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
      placement="topLeft"
    >
      <Tooltip title={info?.project_dir}>
        <button
          type="button"
          className={`${styles.trigger} ${
            info && !info.exists ? styles.triggerError : ""
          } ${compact ? styles.triggerCompact : ""} ${
            showFullPath ? styles.triggerFullPath : ""
          }`}
          aria-label={t("projectDirectory.sessionTitle")}
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
              <span>
                {showFullPath ? info?.project_dir || basename : basename}
              </span>
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
