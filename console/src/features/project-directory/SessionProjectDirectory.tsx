import { Button, Input, Popover, Tooltip } from "antd";
import {
  ArrowUp,
  Check,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  Eye,
  EyeOff,
  Folder,
  FolderPlus,
  FolderOpen,
  House,
  LoaderCircle,
  RotateCw,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  chatProjectDirectoryApi,
  type ChatProjectDirs,
  type EffectiveProjectDirectory,
  type ProjectDirEntry,
  type ProjectDirPayloadEntry,
} from "../../api/modules/chatProjectDirectory";
import { projectDirectoryApi } from "../../api/modules/projectDirectory";
import { useIsMobile } from "../../hooks/useIsMobile";
import { OsDrawer } from "../../os/OsOverlay";
import { useProjectDirectoryStore } from "../../stores/projectDirectoryStore";
import type {
  BrowseDirsResponse,
  ProjectListItem,
} from "../../api/modules/projectDirectory";
import styles from "./SessionProjectDirectory.module.less";
import { setPendingProjectDirectory } from "./pendingProjectDirectory";
import { loadSessionProjectDirs } from "./loadSessionProjectDirs";
import type { FilesWorkspaceScope } from "../files-workspace/filesWorkspaceScope";
import { notifyProjectDirectoryChanged } from "./projectDirectoryChangeEvent";

/** Mirrors the server's MAX_PROJECT_DIRS: the whole list is capped at 10. */
const MAX_PROJECT_DIRS = 10;

/** Last path segment, for the short display name of a directory. */
function basenameOf(path: string): string {
  const trimmed = path.replace(/[\\/]+$/, "");
  // "/" collapses to an empty string, so keep the raw path as the label.
  return trimmed.split(/[\\/]/).pop() || trimmed || path;
}

/** Path compare for the picker — separators normalised, case never folded.
 *
 *  The console does not fold case any more. It used to, using a flag the
 *  server derived from `sys.platform`, which was wrong for a case-sensitive
 *  APFS volume, a Windows per-directory flag, or a network mount whose rule
 *  differs from its host: the picker then reported `/srv/repo` as already
 *  bound when `/srv/Repo` was, and refused a directory the user could
 *  legitimately add.
 *
 *  Every comparison left in this file is between two spellings that came
 *  from the same place, where exact text is the right test:
 *
 *  - the draft list against the saved one, asking "did the user change this
 *    slot" — and `/srv/Repo` → `/srv/repo` is a real re-bind there, not a
 *    no-op, so folding would silently drop the save;
 *  - a queued pick against the entry it was copied from, for the highlight.
 *
 *  {@link isBound} is the one place that compares a path the user typed, and
 *  it is documented there as a hint: the server decides, by inode. */
function exactSamePath(a: string, b: string): boolean {
  const norm = (value: string) =>
    value.trim().replace(/\\/g, "/").replace(/\/+$/, "");
  return norm(a) === norm(b);
}

interface SessionProjectDirectoryProps {
  scope: FilesWorkspaceScope;
  compact?: boolean;
  className?: string;
  showFullPath?: boolean;
  beforeChange?: () => boolean | Promise<boolean>;
  onChanged?: () => void;
  /** Drive the panel from outside. Omit to keep the built-in open state. */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  /**
   * Render the panel without its own trigger button, for callers that already
   * have one (the Files navigator opens this from its root switcher). Requires
   * `open` — with no trigger and no controlled state the panel is unreachable.
   */
  hideTrigger?: boolean;
}

export default function SessionProjectDirectory({
  scope,
  compact = false,
  className,
  showFullPath = false,
  beforeChange,
  onChanged,
  open: controlledOpen,
  onOpenChange,
  hideTrigger = false,
}: SessionProjectDirectoryProps) {
  const { t } = useTranslation();
  const isMobile = useIsMobile();
  const selectedAgent = scope.agentId;
  const chatId = scope.kind === "session" ? scope.chatId : undefined;
  const sessionId = scope.kind === "session" ? scope.sessionId : "";
  const isAgentScope = scope.kind === "agent";
  const [info, setInfo] = useState<EffectiveProjectDirectory | null>(null);
  const [draft, setDraft] = useState("");
  const draftRef = useRef("");
  const [uncontrolledOpen, setUncontrolledOpen] = useState(false);
  // Controlled when the caller passes `open`; otherwise the panel owns it.
  // Every internal close (Apply, Restore default, dismiss) goes through
  // `setOpen`, so a controlled parent hears about all of them.
  const open = controlledOpen ?? uncontrolledOpen;
  const setOpen = useCallback(
    (next: boolean) => {
      if (controlledOpen === undefined) setUncontrolledOpen(next);
      onOpenChange?.(next);
    },
    [controlledOpen, onOpenChange],
  );
  const [saving, setSaving] = useState(false);
  const [projects, setProjects] = useState<ProjectListItem[]>([]);
  const [selectedRecentPath, setSelectedRecentPath] = useState<string | null>(
    null,
  );
  const [browser, setBrowser] = useState<BrowseDirsResponse | null>(null);
  const [browseLoading, setBrowseLoading] = useState(false);
  const [showHidden, setShowHidden] = useState(false);
  const [createDirectoryOpen, setCreateDirectoryOpen] = useState(false);
  const [newDirectoryName, setNewDirectoryName] = useState("");
  const [createDirectoryLoading, setCreateDirectoryLoading] = useState(false);
  const [createDirectoryError, setCreateDirectoryError] = useState("");
  // Mirrored in a ref so `browse` keeps a stable identity: it is a dependency
  // of the panel-open effect, which would otherwise re-run on every toggle and
  // navigate back to the project directory.
  const showHiddenRef = useRef(false);
  // Monotonically increasing sequence number for browse requests.
  // Only the most recent request is allowed to update state, preventing stale
  // responses from overwriting newer results when requests complete out of order.
  const browseSeq = useRef(0);
  // Session scope binds an ordered list of directories, index 0 = primary.
  // It replaces the single-path field, so the list is the whole selection.
  // Only used when !isAgentScope; agent scope stays single-valued via `draft`.
  const [dirs, setDirs] = useState<ProjectDirEntry[]>([]);
  // What the server holds. Restored when the panel closes, so an abandoned
  // edit never leaves the trigger advertising directories that are not bound.
  const [appliedDirs, setAppliedDirs] = useState<ProjectDirEntry[]>([]);
  // A folder the user single-clicked and has not bound yet. Deliberately not
  // `draft`: navigating (double click, home, parent) must not queue anything.
  const [pendingPath, setPendingPath] = useState("");
  const listRef = useRef<HTMLUListElement>(null);
  const [listError, setListError] = useState<string | null>(null);
  const announceChanged = () => {
    notifyProjectDirectoryChanged(scope);
    onChanged?.();
  };
  const updateDraft = useCallback((path: string) => {
    draftRef.current = path;
    setDraft(path);
  }, []);

  /** Adopt a session directory list. Index 0 is the primary, which also
   *  feeds `info` so the trigger keeps rendering as it does on agent scope. */
  const applyList = useCallback(
    (
      next: ProjectDirEntry[],
      snapshot: Pick<ChatProjectDirs, "source" | "agent_project_dir">,
    ) => {
      const primary = next[0];
      setDirs(next);
      setAppliedDirs(next);
      setInfo({
        project_dir: primary?.path ?? "",
        source: snapshot.source,
        agent_project_dir: snapshot.agent_project_dir,
        exists: primary ? primary.exists : true,
      });
      // `draft` is the pending-add preview on session scope, so it is left
      // alone here: adopting a saved list must not repopulate it.
    },
    [],
  );

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
    // Shared with the Files navigator so the panel and the tree can never
    // disagree about which directories the session is bound to.
    const snapshot = await loadSessionProjectDirs(
      selectedAgent,
      sessionId,
      chatId,
    );
    applyList(snapshot.dirs, {
      source: snapshot.source,
      agent_project_dir: snapshot.agentProjectDir,
    });
  }, [applyList, chatId, isAgentScope, selectedAgent, sessionId, updateDraft]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const browse = useCallback(
    async (path?: string, selectCurrent = false) => {
      const seq = ++browseSeq.current;
      setBrowseLoading(true);
      try {
        const next = await projectDirectoryApi.browseDirs(
          path,
          showHiddenRef.current,
        );
        if (seq !== browseSeq.current) return;
        setBrowser(next);
        if (selectCurrent) {
          updateDraft(next.current);
          setSelectedRecentPath(null);
        }
      } catch {
        // Stale or failed requests are silently discarded; only the latest
        // request is allowed to clear the loading indicator.
        if (seq !== browseSeq.current) return;
      } finally {
        if (seq === browseSeq.current) setBrowseLoading(false);
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
    // Start at the home directory, not inside the current project. Opening on
    // the project dir only ever listed its *subfolders*, so picking a second
    // project meant clicking "home" first every single time.
    void browse("~");
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

  /** How many directories the server holds. Drives the trigger badge.
   *  An unbound session resolves to a single directory, so it never trips
   *  the badge's `> 1` threshold. */
  const appliedCount = appliedDirs.length;

  /** The entries that may actually be saved.
   *
   *  Every listed directory, including the one the panel inherited. Adding a
   *  second directory must not silently drop the first — the inherited entry
   *  is the current primary, so dropping it would move the base for relative
   *  paths without the user asking. Removing it is the × button's job. */
  const bindableDirs = useMemo(
    () => dirs.filter((entry) => entry.path.trim()),
    [dirs],
  );

  /** Nothing is bound and nothing has been queued, so Apply has nothing to
   *  pin: the list is still exactly the workspace entry the panel shows for an
   *  unbound session. Pinning it would only trade the inherited default for an
   *  identical explicit one — at the cost of the unsaved-changes warning and
   *  every project editor tab. */
  const isUntouchedFallback = useMemo<boolean>(
    () =>
      info?.source === "workspace_fallback" &&
      dirs.length === appliedDirs.length &&
      dirs.every((entry, index) =>
        exactSamePath(entry.path, appliedDirs[index]?.path ?? ""),
      ),
    [appliedDirs, dirs, info?.source],
  );

  /** An Apply that would change nothing on an already-bound chat.
   *
   *  Worth detecting because Apply is not side-effect-free: `beforeChange`
   *  warns about discarding unsaved editor changes and `onChanged` closes
   *  every project editor tab (FilesNavigator). Both are wrong when the
   *  directories did not move — opening the panel and pressing Apply should
   *  not cost the user their open tabs.
   *
   *  Restricted to `source === "session"`: when the list is merely inherited,
   *  an identical list still has to be PUT, because that is what pins it as
   *  this chat's own override. */
  const isNoopSave = useMemo(
    () =>
      info?.source === "session" &&
      bindableDirs.length === appliedDirs.length &&
      bindableDirs.every((entry, index) => {
        const applied = appliedDirs[index];
        return (
          !!applied &&
          exactSamePath(entry.path, applied.path) &&
          (entry.label ?? "") === (applied.label ?? "")
        );
      }),
    [appliedDirs, bindableDirs, info?.source],
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

  const toggleHidden = () => {
    const next = !showHidden;
    showHiddenRef.current = next;
    setShowHidden(next);
    void browse(browser?.current ?? draft);
  };

  // ── Session scope: the bound directory list ──────────────────────────
  /** Whether a path is already in the list — a hint, not the verdict.
   *
   *  Exact text, so a path the user typed with different case than the bound
   *  spelling is not recognised here. That is deliberate: the client cannot
   *  know whether the filesystem folds case, and the two ways of being wrong
   *  are not equal. Guessing "already bound" refuses a directory the user is
   *  entitled to add, with no recourse; guessing "not bound" merely offers a
   *  candidate that the server then collapses into the entry it duplicates,
   *  because the server compares by inode. */
  const isBound = (path: string) =>
    dirs.some((entry) => exactSamePath(entry.path, path));

  /** Queue a single-clicked folder as the next one to bind. */
  const selectPending = (path: string) => {
    setListError(null);
    setPendingPath(path);
  };

  const cancelCreateDirectory = () => {
    setCreateDirectoryOpen(false);
    setNewDirectoryName("");
    setCreateDirectoryError("");
  };

  const createDirectory = async () => {
    const name = newDirectoryName.trim();
    if (!browser || !name) return;
    setCreateDirectoryLoading(true);
    setCreateDirectoryError("");
    try {
      const created = await projectDirectoryApi.createDirectory(
        browser.current,
        name,
      );
      // Agent scope types a single path, so the new folder becomes the
      // draft; session scope queues it as the next directory to bind.
      if (isAgentScope) {
        selectCustomPath(created.path);
      } else {
        selectPending(created.path);
      }
      await browse(browser.current);
      cancelCreateDirectory();
    } catch (error) {
      setCreateDirectoryError(
        error instanceof Error
          ? error.message.split(" - ")[0]
          : t("projectDirectory.createDirectoryFailed"),
      );
    } finally {
      setCreateDirectoryLoading(false);
    }
  };

  // The queued row is appended, so scroll to it: otherwise a full list hides
  // the Add button below the fold.
  useEffect(() => {
    if (!pendingPath) return;
    const list = listRef.current;
    if (list) list.scrollTop = list.scrollHeight;
  }, [pendingPath]);

  /** Bind the queued directory. Additive — nothing already listed is dropped.
   *
   *  Appends, so whichever entry is first stays the primary and promoting the
   *  new one is "make primary", an explicit click. The one exception is the
   *  very first directory added to a session that has nothing bound: the only
   *  entry there is the agent's own workspace — its configuration and memory
   *  store, not somewhere the user works — so the real directory they just
   *  picked takes the primary slot, and the workspace is kept behind it rather
   *  than dictating where relative paths and the Files tree resolve. */
  const addPending = () => {
    const path = pendingPath.trim();
    if (!path || isBound(path) || dirs.length >= MAX_PROJECT_DIRS) return;
    const entry: ProjectDirEntry = {
      path,
      label: null,
      exists: true,
      nested_with: null,
      // A directory picked in the browser is a project directory. Only the
      // server can say otherwise, and it will on the next load — the flag is
      // read by the Files switcher, which has nothing to collapse until then.
      is_workspace: false,
    };
    setDirs((current) =>
      isUntouchedFallback ? [entry, ...current] : [...current, entry],
    );
    setPendingPath("");
  };

  const removeAt = (index: number) => {
    setListError(null);
    setDirs((current) => current.filter((_, i) => i !== index));
  };

  /** Move an entry to the front: relative paths then resolve from it. */
  const makePrimary = (index: number) => {
    setListError(null);
    setDirs((current) => {
      if (index <= 0 || index >= current.length) return current;
      const next = [...current];
      const [moved] = next.splice(index, 1);
      next.unshift(moved);
      return next;
    });
  };

  /** Commit the edited list. Index 0 becomes the server's primary. */
  const saveSessionList = async () => {
    if (isNoopSave) {
      // Just dismiss: no request, no unsaved-changes warning, and no tab
      // teardown for a directory set that is already bound.
      setPendingPath("");
      setListError(null);
      setOpen(false);
      return;
    }
    if (beforeChange && !(await beforeChange())) return;
    const payload: ProjectDirPayloadEntry[] = bindableDirs.map((entry) => ({
      path: entry.path,
      label: entry.label,
    }));
    if (payload.length === 0) return;
    if (!chatId) {
      setPendingProjectDirectory(
        selectedAgent,
        sessionId,
        payload.map((entry) => ({
          path: entry.path,
          label: entry.label ?? null,
        })),
      );
      setListError(null);
      setPendingPath("");
      setOpen(false);
      await refresh();
      announceChanged();
      return;
    }
    setSaving(true);
    setListError(null);
    try {
      const saved = await chatProjectDirectoryApi.setProjectDirs(
        chatId,
        payload,
      );
      applyList(saved.project_dirs, saved);
      setPendingPath("");
      setOpen(false);
      announceChanged();
    } catch (err) {
      setListError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  const save = async () => {
    if (!isAgentScope) {
      await saveSessionList();
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
    setListError(null);
    try {
      await chatProjectDirectoryApi.clearProjectDirs(chatId);
      // Re-read rather than applying the response: dropping the override
      // usually leaves an empty list, and refresh() knows how to fall back
      // to the effective directory instead of showing an empty panel.
      await refresh();
      setOpen(false);
      announceChanged();
    } catch (err) {
      setListError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  /** Dismissing discards session edits that were never applied, so the
   *  trigger keeps describing what the server has. Agent scope keeps its
   *  typed draft across a dismiss, as it always has. */
  const handleOpenChange = (next: boolean) => {
    setOpen(next);
    if (next) return;
    if (!isAgentScope) {
      setDirs(appliedDirs);
      setPendingPath("");
    }
    setListError(null);
  };

  const panel = (
    <div
      className={`${styles.panel} ${
        isAgentScope ? "" : styles.panelWithList
      }`.trim()}
    >
      <div className={styles.panelHeading}>
        <span className={styles.headingIcon}>
          <FolderOpen size={18} />
        </span>
        <div>
          <strong>
            {t(
              isAgentScope
                ? "projectDirectory.agentTitle"
                : "projectDirectory.boundDirs",
            )}
          </strong>
          {!isAgentScope && (
            <small className={styles.boundHint}>
              {t("projectDirectory.primaryHint")}
            </small>
          )}
        </div>
        {!isAgentScope && (
          <span className={styles.headingCount}>{dirs.length}</span>
        )}
        {isMobile && (
          <Button
            type="text"
            className={styles.panelClose}
            aria-label={t("common.close")}
            icon={<X size={18} />}
            onClick={() => handleOpenChange(false)}
          />
        )}
      </div>

      {/* Agent scope keeps the single-path field; session scope shows the
          bound list here instead — it *is* the session's directory set. */}
      {isAgentScope ? (
        selectedRecentProject ? (
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
        )
      ) : (
        <div className={styles.boundDirs}>
          {dirs.length > 0 || pendingPath ? (
            <ul className={styles.boundList} ref={listRef}>
              {dirs.map((entry, index) => (
                <li
                  key={entry.path}
                  data-missing={!entry.exists}
                  data-primary={index === 0}
                >
                  <span className={styles.boundIcon}>
                    <Folder size={15} />
                  </span>
                  <span className={styles.boundCopy}>
                    <strong>{entry.label || basenameOf(entry.path)}</strong>
                    <small title={entry.path}>{entry.path}</small>
                  </span>
                  {!entry.exists && (
                    <em className={styles.boundTag}>
                      {t("projectDirectory.unavailable")}
                    </em>
                  )}
                  {index === 0 ? (
                    <em className={styles.boundTag}>
                      {t("projectDirectory.primaryTag")}
                    </em>
                  ) : (
                    <button
                      type="button"
                      className={styles.boundAction}
                      disabled={saving}
                      onClick={() => makePrimary(index)}
                    >
                      {t("projectDirectory.makePrimary")}
                    </button>
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
                </li>
              ))}

              {/* A folder that was clicked but not bound yet sits at the end,
                  where it will land once it is added. */}
              {pendingPath && (
                <li className={styles.pendingRow} data-pending="true">
                  <span className={styles.boundIcon}>
                    <Folder size={15} />
                  </span>
                  <span className={styles.boundCopy}>
                    <strong>{basenameOf(pendingPath)}</strong>
                    <small title={pendingPath}>{pendingPath}</small>
                  </span>
                  {isBound(pendingPath) ? (
                    <em className={styles.boundTag}>
                      {t("projectDirectory.alreadyBound")}
                    </em>
                  ) : dirs.length >= MAX_PROJECT_DIRS ? (
                    <em className={styles.boundTag}>
                      {t("projectDirectory.tooMany", { max: MAX_PROJECT_DIRS })}
                    </em>
                  ) : (
                    <Button
                      disabled={saving}
                      onClick={addPending}
                      size="small"
                      type="primary"
                    >
                      {t("projectDirectory.add")}
                    </Button>
                  )}
                </li>
              )}
            </ul>
          ) : (
            <small className={styles.emptyState}>
              {t("projectDirectory.unbound")}
            </small>
          )}
          {listError && <small className={styles.listError}>{listError}</small>}
        </div>
      )}

      <div className={styles.splitBody}>
        <section className={styles.recentPane}>
          <div className={styles.sectionHeading}>
            <strong>{t("projectDirectory.recentProjects")}</strong>
            <span>{projects.length}</span>
          </div>
          <div className={styles.recent}>
            {projects.slice(0, 6).map((project) => {
              const selected = isAgentScope
                ? selectedRecentPath === project.path
                : exactSamePath(pendingPath, project.path);
              return (
                <button
                  type="button"
                  key={project.path}
                  className={selected ? styles.recentSelected : undefined}
                  aria-pressed={selected}
                  onClick={() =>
                    isAgentScope
                      ? selectRecentProject(project)
                      : selectPending(project.path)
                  }
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
                icon={<House size={14} />}
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
              <Button
                type={createDirectoryOpen ? "primary" : "text"}
                size="small"
                disabled={!browser || browser.selectable === false}
                aria-label={t("projectDirectory.createDirectory")}
                aria-pressed={createDirectoryOpen}
                icon={<FolderPlus size={14} />}
                onClick={() => {
                  if (createDirectoryOpen) {
                    cancelCreateDirectory();
                  } else {
                    setCreateDirectoryOpen(true);
                  }
                }}
              />
              <Button
                type={showHidden ? "primary" : "text"}
                size="small"
                aria-label={t("codingMode.openDirHiddenFolders")}
                aria-pressed={showHidden}
                icon={showHidden ? <Eye size={14} /> : <EyeOff size={14} />}
                onClick={toggleHidden}
              />
            </div>
          </div>

          {createDirectoryOpen && (
            <div className={styles.createDirectoryForm}>
              <Input
                size="small"
                autoFocus
                status={createDirectoryError ? "error" : undefined}
                value={newDirectoryName}
                placeholder={t("projectDirectory.directoryNamePlaceholder")}
                onChange={(event) => {
                  setNewDirectoryName(event.target.value);
                  setCreateDirectoryError("");
                }}
                onPressEnter={() => void createDirectory()}
              />
              <Button
                type="primary"
                size="small"
                loading={createDirectoryLoading}
                disabled={!newDirectoryName.trim()}
                aria-label={t("common.confirm")}
                icon={<Check size={14} />}
                onClick={() => void createDirectory()}
              />
              <Button
                type="text"
                size="small"
                disabled={createDirectoryLoading}
                aria-label={t("common.cancel")}
                icon={<X size={14} />}
                onClick={cancelCreateDirectory}
              />
              {createDirectoryError && (
                <small role="alert">{createDirectoryError}</small>
              )}
            </div>
          )}

          <div className={styles.directories}>
            {browseLoading && !browser && (
              <span className={styles.browserLoading}>
                <LoaderCircle className={styles.spin} size={16} />
              </span>
            )}
            {browser?.dirs.map((directory) => {
              const selected = isAgentScope
                ? !selectedRecentPath && draft === directory.path
                : exactSamePath(pendingPath, directory.path);
              return (
                <button
                  type="button"
                  key={directory.path}
                  className={selected ? styles.directorySelected : undefined}
                  aria-pressed={selected}
                  onClick={() =>
                    isAgentScope
                      ? selectCustomPath(directory.path)
                      : selectPending(directory.path)
                  }
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
              : "projectDirectory.restoreDefault",
          )}
        </Button>
        <Button
          type="primary"
          loading={saving}
          onClick={() => void save()}
          disabled={
            isAgentScope
              ? !draft.trim()
              : bindableDirs.length === 0 || isUntouchedFallback
          }
        >
          {t("common.apply")}
        </Button>
      </div>
    </div>
  );

  const triggerButton = (
    <button
      type="button"
      className={`${styles.trigger} ${
        info && !info.exists ? styles.triggerError : ""
      } ${compact ? styles.triggerCompact : ""} ${
        showFullPath ? styles.triggerFullPath : ""
      } ${className ?? ""}`}
      aria-expanded={open}
      aria-label={t(
        isAgentScope
          ? "projectDirectory.agentTitle"
          : "projectDirectory.sessionTitle",
      )}
      onClick={isMobile ? () => handleOpenChange(!open) : undefined}
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
          {/* Extra roots are not listed here; the count signals that
              more than the primary is bound. Driven by the applied list
              so an abandoned edit never shows up as bound. */}
          {!isAgentScope && appliedCount > 1 && (
            <em title={t("projectDirectory.countTitle")}>·{appliedCount}</em>
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
  );
  const trigger = isMobile ? (
    triggerButton
  ) : (
    <Tooltip title={info?.project_dir}>{triggerButton}</Tooltip>
  );

  const mobileDrawer = (
    <OsDrawer
      aria-label={t(
        isAgentScope
          ? "projectDirectory.agentTitle"
          : "projectDirectory.boundDirs",
      )}
      open={open}
      placement="bottom"
      height="min(72dvh, 620px)"
      closable={false}
      destroyOnHidden
      rootClassName={styles.mobileDrawer}
      onClose={() => handleOpenChange(false)}
      styles={{
        body: { padding: 0, overflow: "hidden" },
        content: {
          borderRadius: "14px 14px 0 0",
          overflow: "hidden",
        },
      }}
    >
      {panel}
    </OsDrawer>
  );

  if (isMobile) {
    return (
      <>
        {!hideTrigger && trigger}
        {mobileDrawer}
      </>
    );
  }

  // `hideTrigger` callers drive `open` themselves and already render their own
  // control, so the Popover only needs a zero-size element to anchor to — and
  // no trigger events, which would otherwise reopen it on a stray click.
  if (hideTrigger) {
    return (
      <Popover
        content={panel}
        trigger={[]}
        open={open}
        onOpenChange={handleOpenChange}
        placement={isAgentScope ? "rightTop" : "topRight"}
        overlayClassName={styles.desktopPopover}
      >
        <span className={styles.hiddenAnchor} aria-hidden="true" />
      </Popover>
    );
  }

  return (
    <Popover
      content={panel}
      trigger="click"
      open={open}
      onOpenChange={handleOpenChange}
      placement={isAgentScope ? "rightTop" : "topRight"}
      overlayClassName={styles.desktopPopover}
    >
      {trigger}
    </Popover>
  );
}
