import { Button, Input, Popover, Tooltip } from "antd";
import {
  AlertTriangle,
  ArrowUp,
  Check,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  Folder,
  FolderOpen,
  LoaderCircle,
  RotateCcw,
  RotateCw,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  chatProjectDirectoryApi,
  type ChatProjectDirs,
  type EffectiveProjectDirectory,
  type ProjectDirPayloadEntry,
} from "../../api/modules/chatProjectDirectory";
import { projectDirectoryApi } from "../../api/modules/projectDirectory";
import { useProjectDirectoryStore } from "../../stores/projectDirectoryStore";
import type {
  BrowseDirsResponse,
  ProjectListItem,
} from "../../api/modules/projectDirectory";
import styles from "./SessionProjectDirectory.module.less";
import {
  getPendingProjectDirs,
  setPendingProjectDirectory,
} from "./pendingProjectDirectory";
import type { FilesWorkspaceScope } from "../files-workspace/filesWorkspaceScope";
import { notifyProjectDirectoryChanged } from "./projectDirectoryChangeEvent";
import {
  isNativeDirectoryPickerAvailable,
  pickDirectory,
  PICK_CANCELLED,
} from "../../utils/pickDirectory";
import { useDirectoryBrowser } from "../../components/DirectoryBrowser/useDirectoryBrowser";

/** Last path segment, so labels stay short. Handles both separators. */
function basenameOf(path: string): string {
  const parts = path.split(/[/\\]/).filter(Boolean);
  return parts[parts.length - 1] || path;
}

/** Case-insensitive path compare, matching the server's dedupe rule. */
function samePath(a: string, b: string): boolean {
  return a.trim().toLowerCase() === b.trim().toLowerCase();
}

/** A directory row while it is being edited locally, before Apply. */
interface LocalDirEntry {
  path: string;
  label: string | null;
  exists: boolean;
  nested_with: string | null;
}

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

  // ── Agent-scope state (single directory, unchanged) ──────────────────
  const [info, setInfo] = useState<EffectiveProjectDirectory | null>(null);
  const [draft, setDraft] = useState("");
  const draftRef = useRef("");
  const [projects, setProjects] = useState<ProjectListItem[]>([]);
  const [selectedRecentPath, setSelectedRecentPath] = useState<string | null>(
    null,
  );
  const [browser, setBrowser] = useState<BrowseDirsResponse | null>(null);
  const [browseLoading, setBrowseLoading] = useState(false);

  // ── Session-scope state (ordered list of directories) ────────────────
  const [dirsInfo, setDirsInfo] = useState<ChatProjectDirs | null>(null);
  const [draftList, setDraftList] = useState<LocalDirEntry[]>([]);
  const [customName, setCustomName] = useState<string | null>(null);
  const [projectNameDraft, setProjectNameDraft] = useState<
    string | undefined
  >();
  const [sessionError, setSessionError] = useState<string | null>(null);
  // Undefined until probed so the add button does not flash in and out.
  const [nativePicker, setNativePicker] = useState<boolean | undefined>();
  const [showBrowserPicker, setShowBrowserPicker] = useState(false);

  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);

  const announceChanged = () => {
    notifyProjectDirectoryChanged(scope);
    onChanged?.();
  };
  const updateDraft = useCallback((path: string) => {
    draftRef.current = path;
    setDraft(path);
  }, []);

  const applySnapshot = useCallback((next: ChatProjectDirs) => {
    setDirsInfo(next);
    setDraftList(
      next.project_dirs.map((entry) => ({
        path: entry.path,
        label: entry.label,
        exists: entry.exists,
        nested_with: entry.nested_with,
      })),
    );
    setCustomName(next.project_name_is_custom ? next.project_name : null);
    setProjectNameDraft(undefined);
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
      try {
        const next = await chatProjectDirectoryApi.getProjectDirs(chatId);
        applySnapshot(next);
      } catch {
        // Leave the previous snapshot in place; the panel will retry on
        // the next open/refresh.
      }
      return;
    }
    // Brand-new chat with no backend id yet: show the pending pick if one
    // exists, otherwise the agent default so the card is informative.
    const pending = getPendingProjectDirs(selectedAgent, sessionId);
    if (pending) {
      const first = pending.dirs[0];
      applySnapshot({
        project_dirs: pending.dirs.map((entry) => ({
          path: entry.path,
          label: entry.label,
          exists: true,
          nested_with: null,
        })),
        source: "session",
        agent_project_dir: null,
        project_name:
          pending.name ??
          (first ? first.label || basenameOf(first.path) : null),
        project_name_is_custom: Boolean(pending.name),
      });
      return;
    }
    const next = await projectDirectoryApi.get();
    if (next.is_workspace_default) {
      // The workspace fallback is deliberately not listed: an unbound chat
      // renders the empty state rather than the workspace path.
      applySnapshot({
        project_dirs: [],
        source: "workspace_fallback",
        agent_project_dir: null,
        project_name: null,
        project_name_is_custom: false,
      });
    } else {
      applySnapshot({
        project_dirs: [
          {
            path: next.path,
            label: null,
            exists: next.exists ?? true,
            nested_with: null,
          },
        ],
        source: "agent",
        agent_project_dir: next.path,
        project_name: next.name ?? null,
        project_name_is_custom: false,
      });
    }
  }, [
    applySnapshot,
    chatId,
    isAgentScope,
    selectedAgent,
    sessionId,
    updateDraft,
  ]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // ── Agent-scope directory browsing ───────────────────────────────────
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
    if (!open || !isAgentScope) return;
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
  }, [browse, info?.project_dir, isAgentScope, open]);

  // ── Session-scope fallback in-app browser ────────────────────────────
  const dirBrowser = useDirectoryBrowser({
    enabled: showBrowserPicker && !isAgentScope,
    initialPath: draftList[0]?.path || "~",
  });

  // Probe the native picker once, the first time the panel opens, so an
  // unopened selector costs no requests.
  useEffect(() => {
    if (!open || isAgentScope || nativePicker !== undefined) return;
    let alive = true;
    void isNativeDirectoryPickerAvailable().then((ok) => {
      if (alive) setNativePicker(ok);
    });
    return () => {
      alive = false;
    };
  }, [open, isAgentScope, nativePicker]);

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

  // ── Session-scope derived values ─────────────────────────────────────
  const isPending = !isAgentScope && !chatId && dirsInfo?.source === "session";
  const primary = draftList[0];
  // A pending path has not been server-checked yet, so do not claim it is
  // missing; the router validates it when the first message arrives.
  const primaryMissing = isPending ? false : primary ? !primary.exists : false;
  const derivedName = primary
    ? primary.label || basenameOf(primary.path)
    : undefined;
  const storedName = customName ?? derivedName;
  const cardName = projectNameDraft ?? storedName ?? "";

  const toPayload = (list: LocalDirEntry[]): ProjectDirPayloadEntry[] =>
    list.map((entry) => {
      const name = (entry.label ?? "").trim();
      const label = name && name !== basenameOf(entry.path) ? name : null;
      return { path: entry.path, label };
    });

  // ── Session-scope persistence ────────────────────────────────────────
  const persistList = async (
    list: ProjectDirPayloadEntry[],
    name: string | null,
  ) => {
    if (!chatId) {
      setPendingProjectDirectory(
        selectedAgent,
        sessionId,
        list.map((entry) => ({ path: entry.path, label: entry.label ?? null })),
        name,
      );
      setOpen(false);
      await refresh();
      announceChanged();
      return;
    }
    setSaving(true);
    setSessionError(null);
    try {
      const next = await chatProjectDirectoryApi.setProjectDirs(
        chatId,
        list,
        name,
      );
      applySnapshot(next);
      setOpen(false);
      announceChanged();
    } catch (err) {
      setSessionError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  const persistClear = async () => {
    if (!chatId) {
      setPendingProjectDirectory(selectedAgent, sessionId, null);
      setOpen(false);
      await refresh();
      announceChanged();
      return;
    }
    setSaving(true);
    setSessionError(null);
    try {
      const next = await chatProjectDirectoryApi.clearProjectDirs(chatId);
      applySnapshot(next);
      setOpen(false);
      announceChanged();
    } catch (err) {
      setSessionError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  // ── Session-scope list transforms (local only, committed by Apply) ───
  const addPath = (path: string) => {
    const trimmed = path.trim();
    if (!trimmed) return;
    if (draftList.some((entry) => samePath(entry.path, trimmed))) {
      setSessionError(t("projectDirectory.duplicate"));
      return;
    }
    setSessionError(null);
    setDraftList((current) => [
      ...current,
      { path: trimmed, label: null, exists: true, nested_with: null },
    ]);
    setShowBrowserPicker(false);
  };

  const removeAt = (index: number) => {
    setDraftList((current) => current.filter((_, i) => i !== index));
  };

  const makePrimary = (index: number) => {
    setDraftList((current) => {
      if (index <= 0 || index >= current.length) return current;
      const next = [...current];
      const [moved] = next.splice(index, 1);
      next.unshift(moved);
      return next;
    });
  };

  const renameAt = (index: number, value: string) => {
    setDraftList((current) =>
      current.map((entry, i) =>
        i === index ? { ...entry, label: value } : entry,
      ),
    );
  };

  const chooseFolder = async () => {
    setSessionError(null);
    if (nativePicker) {
      try {
        const picked = await pickDirectory({
          title: t("projectDirectory.pickTitle"),
          defaultPath: primary?.path,
        });
        if (picked === PICK_CANCELLED) return;
        addPath(picked);
      } catch (err) {
        setSessionError(err instanceof Error ? err.message : String(err));
        setNativePicker(false);
      }
      return;
    }
    // No OS dialog here (remote/headless): fall back to the in-app browser.
    const next = !showBrowserPicker;
    setShowBrowserPicker(next);
    if (next) dirBrowser.navigate(draftList[0]?.path || "~");
  };

  const commitProjectName = async (raw: string) => {
    setProjectNameDraft(undefined);
    const name = raw.trim();
    const nextName = !name || name === derivedName ? null : name;
    if (nextName === customName) return;
    if (draftList.length === 0) return;
    if (beforeChange && !(await beforeChange())) return;
    await persistList(toPayload(draftList), nextName);
  };

  const saveSession = async () => {
    if (saving) return;
    if (beforeChange && !(await beforeChange())) return;
    if (draftList.length === 0) {
      await persistClear();
    } else {
      await persistList(toPayload(draftList), customName);
    }
  };

  const clearSession = async () => {
    if (saving) return;
    if (beforeChange && !(await beforeChange())) return;
    await persistClear();
  };

  const save = async () => {
    if (!isAgentScope) {
      await saveSession();
      return;
    }
    if (!draft.trim()) return;
    if (beforeChange && !(await beforeChange())) return;
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
  };

  const clear = async () => {
    if (!isAgentScope) {
      await clearSession();
      return;
    }
    if (beforeChange && !(await beforeChange())) return;
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
  };

  const handleOpenChange = (next: boolean) => {
    setOpen(next);
    if (!next) {
      setProjectNameDraft(undefined);
      setShowBrowserPicker(false);
      setSessionError(null);
    }
  };

  // ── Restore-default enablement by source (session scope) ─────────────
  const effectiveSource = isPending ? "session" : dirsInfo?.source ?? "agent";
  let restoreDisabled = false;
  let restoreTooltip = "";
  switch (effectiveSource) {
    case "session":
      restoreDisabled = false;
      break;
    case "inherited":
      restoreDisabled = true;
      restoreTooltip = t("projectDirectory.inheritLockedParent");
      break;
    case "fork":
    case "active_mode":
      restoreDisabled = true;
      restoreTooltip = t("projectDirectory.inheritLockedFork");
      break;
    default:
      // request / agent / workspace_fallback: nothing to clear.
      restoreDisabled = true;
      break;
  }

  // ── Agent-scope panel (single directory, unchanged) ──────────────────
  const agentPanel = (
    <div className={styles.panel}>
      <div className={styles.panelHeading}>
        <span className={styles.headingIcon}>
          <FolderOpen size={18} />
        </span>
        <div>
          <strong>{t("projectDirectory.agentTitle")}</strong>
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
          disabled={info?.source === "workspace_fallback"}
        >
          {t("projectDirectory.useWorkspace")}
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

  // ── Session-scope inline fallback browser ────────────────────────────
  const browserPicker = (
    <div className={styles.browserPicker}>
      <div className={styles.browserHeading}>
        <div>
          <strong>{t("projectDirectory.browseDirectory")}</strong>
          {dirBrowser.data && (
            <code title={dirBrowser.data.current}>
              {dirBrowser.data.current}
            </code>
          )}
        </div>
        <div className={styles.browserActions}>
          <Button
            type="text"
            size="small"
            aria-label={t("projectDirectory.homeDirectory")}
            icon={<FolderOpen size={14} />}
            onClick={() => dirBrowser.navigate("~")}
          />
          <Button
            type="text"
            size="small"
            disabled={!dirBrowser.data?.parent}
            aria-label={t("projectDirectory.parentDirectory")}
            icon={<ArrowUp size={14} />}
            onClick={() => dirBrowser.navigate(dirBrowser.data?.parent ?? "~")}
          />
          <Button
            type="text"
            size="small"
            aria-label={t("projectDirectory.refreshDirectory")}
            icon={
              <RotateCw
                className={dirBrowser.loading ? styles.spin : undefined}
                size={14}
              />
            }
            onClick={() => dirBrowser.navigate(dirBrowser.data?.current ?? "~")}
          />
        </div>
      </div>

      <div className={styles.directories}>
        {dirBrowser.loading && !dirBrowser.data && (
          <span className={styles.browserLoading}>
            <LoaderCircle className={styles.spin} size={16} />
          </span>
        )}
        {dirBrowser.data?.dirs.map((directory) => (
          <button
            type="button"
            key={directory.path}
            onClick={() => dirBrowser.navigate(directory.path)}
          >
            <Folder size={15} />
            <span>{directory.name}</span>
            <ChevronRight size={13} />
          </button>
        ))}
        {dirBrowser.data && dirBrowser.data.dirs.length === 0 && (
          <small className={styles.emptyState}>
            {t("codingMode.openDirEmpty")}
          </small>
        )}
      </div>

      <Button
        block
        disabled={!dirBrowser.data?.current || saving}
        onClick={() => dirBrowser.data && addPath(dirBrowser.data.current)}
        size="small"
        type="primary"
      >
        {t("projectDirectory.add")}
      </Button>
    </div>
  );

  const restoreButton = (
    <Button
      disabled={saving || restoreDisabled}
      icon={<RotateCcw size={12} />}
      onClick={() => void clearSession()}
      size="small"
    >
      {t("projectDirectory.restoreDefault")}
    </Button>
  );

  // ── Session-scope panel (ordered list) ───────────────────────────────
  const sessionPanel = (
    <div className={styles.sessionPanel}>
      <div>
        <div className={styles.panelTitle}>
          {t("projectDirectory.sessionTitle")}
        </div>
        <div className={styles.panelHint}>{t("projectDirectory.listHint")}</div>
      </div>

      {draftList.length > 0 ? (
        <ul className={styles.dirList}>
          {draftList.map((entry, index) => {
            const isPrimary = index === 0;
            const displayName = entry.label || basenameOf(entry.path);
            return (
              <li
                className={styles.dirRow}
                data-missing={!isPending && !entry.exists}
                data-primary={isPrimary}
                key={entry.path}
              >
                <div className={styles.dirMain}>
                  <span className={styles.dirName}>
                    <Folder size={12} />
                    <Input
                      aria-label={t("projectDirectory.renameAria")}
                      className={styles.nameInput}
                      disabled={saving}
                      maxLength={50}
                      onChange={(event) => renameAt(index, event.target.value)}
                      size="small"
                      value={entry.label ?? displayName}
                      variant="borderless"
                    />
                    {!isPending && !entry.exists ? (
                      <span className={styles.missingTag}>
                        <AlertTriangle size={10} />
                        {t("projectDirectory.unavailable")}
                      </span>
                    ) : null}
                  </span>
                  {entry.nested_with ? (
                    <span className={styles.hint}>
                      {t("projectDirectory.nestedWarning", {
                        parent: basenameOf(entry.nested_with),
                      })}
                    </span>
                  ) : null}
                  <span className={styles.dirPath} title={entry.path}>
                    {entry.path}
                  </span>
                </div>
                <div className={styles.dirActions}>
                  {isPrimary ? (
                    <span className={styles.primaryLabel}>
                      {t("projectDirectory.primaryTag")}
                    </span>
                  ) : (
                    <Button
                      className={styles.makePrimaryBtn}
                      disabled={saving}
                      onClick={() => makePrimary(index)}
                      size="small"
                      type="text"
                    >
                      {t("projectDirectory.makePrimary")}
                    </Button>
                  )}
                  <Button
                    aria-label={t("projectDirectory.remove")}
                    disabled={saving}
                    icon={<X size={13} />}
                    onClick={() => removeAt(index)}
                    size="small"
                    title={t("projectDirectory.remove")}
                    type="text"
                  />
                </div>
              </li>
            );
          })}
        </ul>
      ) : (
        <div className={styles.emptyState}>{t("projectDirectory.unbound")}</div>
      )}

      {draftList.length > 1 ? (
        <div className={styles.panelHint}>
          {t("projectDirectory.filesShowsPrimaryOnly")}
        </div>
      ) : null}

      <div className={styles.addSection}>
        {nativePicker === false ? (
          <div className={styles.panelHint}>
            {t("projectDirectory.pickerUnavailable")}
          </div>
        ) : null}
        <Button
          block
          disabled={saving || nativePicker === undefined}
          icon={<FolderOpen size={14} />}
          onClick={() => void chooseFolder()}
          size="small"
          type="primary"
        >
          {t("projectDirectory.chooseFolder")}
        </Button>
        {showBrowserPicker ? browserPicker : null}
      </div>

      {sessionError ? (
        <div className={styles.errorNotice}>{sessionError}</div>
      ) : null}

      <div className={styles.sessionActions}>
        {restoreTooltip ? (
          <Tooltip title={restoreTooltip}>
            <span className={styles.restoreWrap}>{restoreButton}</span>
          </Tooltip>
        ) : (
          restoreButton
        )}
        <Button
          disabled={saving}
          loading={saving}
          onClick={() => void save()}
          type="primary"
        >
          {t("common.apply")}
        </Button>
      </div>
    </div>
  );

  // ── Agent-scope render (unchanged) ───────────────────────────────────
  if (isAgentScope) {
    return (
      <Popover
        content={agentPanel}
        trigger="click"
        open={open}
        onOpenChange={setOpen}
        placement="rightTop"
      >
        <Tooltip title={info?.project_dir}>
          <button
            type="button"
            className={`${styles.trigger} ${
              info && !info.exists ? styles.triggerError : ""
            } ${compact ? styles.triggerCompact : ""} ${
              showFullPath ? styles.triggerFullPath : ""
            }`}
            aria-label={t("projectDirectory.agentTitle")}
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

  // ── Session-scope render: collapsed card + popover on the chevron ────
  // The card uses native `title` attributes rather than an antd <Tooltip>:
  // nesting Tooltip and Popover around the same child makes both attach
  // handlers to it, and the hover-opened tooltip swallows the click that
  // should open the panel.
  return (
    <div
      className={`${styles.sessionCard} ${
        compact ? styles.sessionCardCompact : ""
      }`}
      data-missing={primaryMissing ? "true" : "false"}
      data-pending={isPending ? "true" : "false"}
      data-source={isPending ? "pending" : dirsInfo?.source ?? ""}
    >
      {dirsInfo === null ? (
        <LoaderCircle className={styles.spin} size={14} />
      ) : primaryMissing ? (
        <CircleAlert size={14} />
      ) : (
        <FolderOpen size={14} />
      )}

      {!compact &&
        (draftList.length > 0 ? (
          <Input
            aria-label={t("projectDirectory.projectNameLabel")}
            className={styles.cardNameInput}
            disabled={saving}
            maxLength={60}
            onBlur={(event) => void commitProjectName(event.target.value)}
            onChange={(event) => setProjectNameDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key !== "Escape") return;
              event.stopPropagation();
              setProjectNameDraft(undefined);
            }}
            onPressEnter={(event) => (event.target as HTMLInputElement).blur()}
            placeholder={derivedName}
            size="small"
            title={primary?.path}
            value={cardName}
            variant="borderless"
          />
        ) : (
          <span className={styles.cardUnbound}>
            {t("projectDirectory.unboundShort")}
          </span>
        ))}

      {!compact && draftList.length > 1 ? (
        <span
          className={styles.countTag}
          title={t("projectDirectory.countTitle")}
        >
          ·{draftList.length}
        </span>
      ) : null}

      {!compact && (
        <span className={styles.sourceTag}>
          {t(
            isPending
              ? "projectDirectory.tagPending"
              : dirsInfo?.source === "session"
              ? "projectDirectory.tagSession"
              : "projectDirectory.tagInherited",
          )}
        </span>
      )}

      {/* The chevron is the popover trigger, not the whole card: the name
          field lives in the card and must be typeable without opening the
          panel. Popover also takes exactly one child. */}
      <Popover
        arrow={false}
        content={sessionPanel}
        onOpenChange={handleOpenChange}
        open={open}
        overlayClassName={styles.sessionPopover}
        placement="topRight"
        trigger="click"
      >
        <button
          aria-expanded={open}
          aria-haspopup="dialog"
          aria-label={t("projectDirectory.manageAria")}
          className={styles.cardToggle}
          title={t("projectDirectory.manageAria")}
          type="button"
        >
          <ChevronDown size={13} />
        </button>
      </Popover>
    </div>
  );
}
