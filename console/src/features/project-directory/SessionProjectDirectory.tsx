import { directoryBreadcrumbs } from "./directoryBreadcrumbs";
import { Button, Checkbox, Input, Popover, Tooltip } from "antd";
import {
  ArrowUp,
  Check,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  CircleHelp,
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
import InlineHelp from "../../components/InlineHelp";
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
  /** Edit the Agent default list instead of its legacy single-path view. */
  multiAgentDefault?: boolean;
  /** Render the editor directly in its parent instead of in an overlay. */
  inline?: boolean;
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
  multiAgentDefault = false,
  inline = false,
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
  const isListScope = !isAgentScope || multiAgentDefault;
  const [info, setInfo] = useState<EffectiveProjectDirectory | null>(null);
  const [draft, setDraft] = useState("");
  const draftRef = useRef("");
  const [uncontrolledOpen, setUncontrolledOpen] = useState(false);
  // Controlled when the caller passes `open`; otherwise the panel owns it.
  // Every internal close (Apply, Restore default, dismiss) goes through
  // `setOpen`, so a controlled parent hears about all of them.
  const open = inline ? true : controlledOpen ?? uncontrolledOpen;
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
  // List scope binds an ordered list of directories, index 0 = primary.
  // Sessions and the Agent default editor use it; legacy Agent scope keeps
  // the single-path field via `draft`.
  const [dirs, setDirs] = useState<ProjectDirEntry[]>([]);
  // What the server holds. Restored when the panel closes, so an abandoned
  // edit never leaves the trigger advertising directories that are not bound.
  const [appliedDirs, setAppliedDirs] = useState<ProjectDirEntry[]>([]);
  // A folder the user single-clicked and has not bound yet. Deliberately not
  // `draft`: navigating (double click, home, parent) must not queue anything.
  const [pendingPath, setPendingPath] = useState("");
  const listRef = useRef<HTMLUListElement>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [syncAsAgentDefault, setSyncAsAgentDefault] = useState(false);
  const syncAsAgentDefaultRef = useRef(false);
  const updateSyncAsAgentDefault = useCallback((next: boolean) => {
    syncAsAgentDefaultRef.current = next;
    setSyncAsAgentDefault(next);
  }, []);
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
    if (multiAgentDefault) {
      const next = await projectDirectoryApi.getDirs();
      applyList(
        next.project_dirs.length
          ? next.project_dirs
          : [
              {
                path: next.workspace_dir,
                label: null,
                exists: next.workspace_exists ?? true,
                nested_with: null,
                is_workspace: true,
              },
            ],
        {
          source: next.source,
          agent_project_dir: next.project_dirs[0]?.path ?? null,
        },
      );
      return;
    }
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
  }, [
    applyList,
    chatId,
    isAgentScope,
    multiAgentDefault,
    selectedAgent,
    sessionId,
    updateDraft,
  ]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    updateSyncAsAgentDefault(false);
  }, [
    chatId,
    isAgentScope,
    selectedAgent,
    sessionId,
    updateSyncAsAgentDefault,
  ]);

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

  // ── List scope: the bound directory list ─────────────────────────────
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

  const pendingIsAddable =
    !!pendingPath.trim() &&
    !isBound(pendingPath.trim()) &&
    dirs.length < MAX_PROJECT_DIRS;

  const dirsWithPending = useMemo(() => {
    if (!pendingIsAddable) return bindableDirs;
    const entry: ProjectDirEntry = {
      path: pendingPath.trim(),
      label: null,
      exists: true,
      nested_with: null,
      is_workspace: false,
    };
    if (!isUntouchedFallback) return [...bindableDirs, entry];
    return multiAgentDefault ? [entry] : [entry, ...bindableDirs];
  }, [
    bindableDirs,
    isUntouchedFallback,
    multiAgentDefault,
    pendingIsAddable,
    pendingPath,
  ]);

  /** Queue a single-clicked folder or a typed path as the next one to bind. */
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
      if (!isListScope) {
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

  /** Bind the queued directory. Additive — explicit entries are kept.
   *
   *  Appends, so whichever entry is first stays the primary and promoting the
   *  new one is "make primary", an explicit click. The one exception is the
   *  very first directory added when nothing is configured: the only entry
   *  shown is the Agent workspace fallback, not an explicit selection. A new
   *  session keeps that workspace behind its picked project; the Agent default
   *  editor replaces the fallback because it must only persist folders the
   *  user selected. */
  const addPending = () => {
    if (!pendingIsAddable) return;
    setDirs(dirsWithPending);
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

  /** Commit the given list. Index 0 becomes the server's primary.
   *
   *  The typed path and the graphical picker share this commit: both send the
   *  whole ordered list to `PUT /chats/{id}/project-dirs`, where the server
   *  normalises every entry and rejects non-directories — the text input is
   *  only another way to name a directory, never a wider permission. */
  const commitSessionList = async (entries: ProjectDirEntry[]) => {
    if (beforeChange && !(await beforeChange())) return;
    const payload: ProjectDirPayloadEntry[] = entries
      .filter((entry) => entry.path.trim())
      .map((entry) => ({
        path: entry.path.trim(),
        label: entry.label,
      }));
    const primaryPath = payload[0]?.path;
    if (!primaryPath) return;
    if (multiAgentDefault) {
      setSaving(true);
      setListError(null);
      try {
        const saved = await projectDirectoryApi.setDirs(payload);
        applyList(saved.project_dirs, {
          source: saved.source,
          agent_project_dir: saved.project_dirs[0]?.path ?? null,
        });
        useProjectDirectoryStore
          .getState()
          .setProjectDir(selectedAgent, saved.project_dirs[0]?.path ?? null);
        setPendingPath("");
        setOpen(false);
        announceChanged();
      } catch (err) {
        setListError(err instanceof Error ? err.message : String(err));
      } finally {
        setSaving(false);
      }
      return;
    }
    if (!chatId) {
      setSaving(true);
      setListError(null);
      try {
        if (syncAsAgentDefaultRef.current) {
          const next = await projectDirectoryApi.setDirs(payload);
          useProjectDirectoryStore
            .getState()
            .setProjectDir(selectedAgent, next.project_dirs[0]?.path ?? null);
        }
        setPendingProjectDirectory(
          selectedAgent,
          sessionId,
          payload.map((entry) => ({
            path: entry.path,
            label: entry.label ?? null,
          })),
        );
        setPendingPath("");
        updateSyncAsAgentDefault(false);
        setOpen(false);
        await refresh();
        announceChanged();
      } catch (err) {
        setListError(err instanceof Error ? err.message : String(err));
      } finally {
        setSaving(false);
      }
      return;
    }
    setSaving(true);
    setListError(null);
    try {
      if (syncAsAgentDefaultRef.current) {
        const next = await projectDirectoryApi.setDirs(payload);
        useProjectDirectoryStore
          .getState()
          .setProjectDir(selectedAgent, next.project_dirs[0]?.path ?? null);
      }
      const saved = await chatProjectDirectoryApi.setProjectDirs(
        chatId,
        payload,
      );
      applyList(saved.project_dirs, saved);
      setPendingPath("");
      updateSyncAsAgentDefault(false);
      setOpen(false);
      announceChanged();
    } catch (err) {
      setListError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  /** Commit the edited list. Index 0 becomes the server's primary. */
  const saveSessionList = async () => {
    if (isNoopSave && !pendingIsAddable && !syncAsAgentDefaultRef.current) {
      // Just dismiss: no request, no unsaved-changes warning, and no tab
      // teardown for a directory set that is already bound.
      setPendingPath("");
      setListError(null);
      setOpen(false);
      return;
    }
    await commitSessionList(dirsWithPending);
  };

  /** Switch the primary to the queued path, from a paste + Enter.
   *
   *  Restores the v2.1 "paste a path, press Enter, the directory switches"
   *  flow on top of the multi-directory list: the typed directory moves to
   *  (or is added at) the front and the list is committed at once, so every
   *  other bound directory is kept — switching the primary never drops one.
   *  An already-primary path just dismisses the queue; a full list keeps the
   *  pending row's cap hint instead of sending a request the server refuses. */
  const submitPendingAsPrimary = () => {
    const path = pendingPath.trim();
    if (!path || saving) return;
    const index = dirs.findIndex((entry) => exactSamePath(entry.path, path));
    if (index === 0) {
      setPendingPath("");
      setListError(null);
      return;
    }
    if (index > 0) {
      const next = [
        dirs[index] as ProjectDirEntry,
        ...dirs.filter((_, i) => i !== index),
      ];
      void commitSessionList(next);
      return;
    }
    if (dirs.length >= MAX_PROJECT_DIRS) return;
    const entry: ProjectDirEntry = {
      path,
      label: null,
      exists: true,
      nested_with: null,
      // A typed path is a project directory the same way a browser pick is.
      // Only the server can say otherwise, and it will on the next load.
      is_workspace: false,
    };
    void commitSessionList([
      entry,
      ...(isUntouchedFallback && multiAgentDefault ? [] : dirs),
    ]);
  };

  const save = async () => {
    if (isListScope) {
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
    if (multiAgentDefault) {
      setSaving(true);
      setListError(null);
      try {
        await projectDirectoryApi.clearDirs();
        useProjectDirectoryStore.getState().setProjectDir(selectedAgent, null);
        await refresh();
        setOpen(false);
        announceChanged();
      } catch (err) {
        setListError(err instanceof Error ? err.message : String(err));
      } finally {
        setSaving(false);
      }
      return;
    }
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
    if (isListScope) {
      setDirs(appliedDirs);
      setPendingPath("");
      updateSyncAsAgentDefault(false);
    }
    setListError(null);
  };

  const panel = (
    <div
      className={`${styles.panel} ${
        isListScope ? styles.panelWithList : ""
      }`.trim()}
    >
      {inline && multiAgentDefault ? (
        <div className={styles.inlineHeading}>
          <strong className={styles.inlineHint}>
            {t("projectDirectory.boundDirs")}
          </strong>
          <InlineHelp>{t("projectDirectory.primaryHint")}</InlineHelp>
          <span
            className={styles.headingCount}
            title={t("projectDirectory.countTitle")}
          >
            {dirs.length}
          </span>
        </div>
      ) : (
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
            {isListScope && (
              <small className={styles.boundHint}>
                {t("projectDirectory.primaryHint")}
              </small>
            )}
          </div>
          {isListScope && (
            <span
              className={styles.headingCount}
              title={t("projectDirectory.countTitle")}
            >
              {dirs.length}
            </span>
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
      )}

      {/* Agent scope keeps the single-path field; session scope shows the
          bound list here instead — it *is* the session's directory set. The
          path field above it is shared: typing or picking fills the same
          queued path, Enter switches the primary, Add appends instead. */}
      {!isListScope ? (
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
          <Input
            className={styles.pathInput}
            prefix={<Folder size={15} />}
            value={pendingPath}
            onChange={(event) => selectPending(event.target.value)}
            placeholder={t("projectDirectory.pathPlaceholder")}
            onPressEnter={() => submitPendingAsPrimary()}
            suffix={
              pendingPath ? (
                isBound(pendingPath) ? (
                  <small>{t("projectDirectory.alreadyBound")}</small>
                ) : dirs.length >= MAX_PROJECT_DIRS ? (
                  <small>
                    {t("projectDirectory.tooMany", { max: MAX_PROJECT_DIRS })}
                  </small>
                ) : (
                  <Button disabled={saving} onClick={addPending} size="small">
                    {t("projectDirectory.add")}
                  </Button>
                )
              ) : undefined
            }
            allowClear
          />
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
            <strong className={styles.sectionTitle}>
              {t("projectDirectory.workspaceProjects")}
              <Tooltip title={t("projectDirectory.workspaceProjectsHint")}>
                <CircleHelp
                  aria-label={t("projectDirectory.workspaceProjectsHint")}
                  className={styles.sectionHelp}
                  role="img"
                  size={12}
                />
              </Tooltip>
            </strong>
            <span>{projects.length}</span>
          </div>
          <div className={styles.recent}>
            {projects.map((project) => {
              const selected = !isListScope
                ? selectedRecentPath === project.path
                : exactSamePath(pendingPath, project.path);
              return (
                <button
                  type="button"
                  key={project.path}
                  className={selected ? styles.recentSelected : undefined}
                  title={project.path}
                  aria-pressed={selected}
                  onClick={() =>
                    !isListScope
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
                {t("projectDirectory.noWorkspaceProjects")}
              </small>
            )}
          </div>
        </section>

        <section className={styles.browserPane}>
          <div className={styles.browserHeading}>
            <div>
              <strong>{t("projectDirectory.browseDirectory")}</strong>
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

          {browser && (
            <nav
              className={styles.directoryBreadcrumbs}
              aria-label={t("projectDirectory.browseDirectory")}
            >
              {directoryBreadcrumbs(browser.current).map(
                (crumb, index, crumbs) => (
                  <span key={crumb.path}>
                    {index > 0 && <ChevronRight size={12} aria-hidden />}
                    <button
                      type="button"
                      title={crumb.path}
                      aria-current={
                        index === crumbs.length - 1 ? "location" : undefined
                      }
                      onClick={() => void browse(crumb.path)}
                    >
                      {crumb.label}
                    </button>
                  </span>
                ),
              )}
            </nav>
          )}

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
              const selected = !isListScope
                ? !selectedRecentPath && draft === directory.path
                : exactSamePath(pendingPath, directory.path);
              return (
                <div
                  key={directory.path}
                  className={`${styles.directoryRow} ${
                    selected ? styles.directorySelected : ""
                  }`}
                >
                  <button
                    type="button"
                    className={styles.directoryPick}
                    aria-pressed={selected}
                    onClick={() =>
                      !isListScope
                        ? selectCustomPath(directory.path)
                        : selectPending(directory.path)
                    }
                    onDoubleClick={() => void browse(directory.path, true)}
                  >
                    <Folder size={17} />
                    <span>{directory.name}</span>
                    {selected && <Check size={14} />}
                  </button>
                  <button
                    type="button"
                    className={styles.directoryEnter}
                    aria-label={t("projectDirectory.openDirectory", {
                      name: directory.name,
                    })}
                    title={t("projectDirectory.openDirectory", {
                      name: directory.name,
                    })}
                    onClick={() => void browse(directory.path)}
                  >
                    <ChevronRight size={17} />
                  </button>
                </div>
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

      {!isAgentScope && (
        <Checkbox
          className={styles.syncDefaultOption}
          checked={syncAsAgentDefault}
          disabled={saving}
          onChange={(event) => updateSyncAsAgentDefault(event.target.checked)}
        >
          {t("projectDirectory.syncAsAgentDefault")}
        </Checkbox>
      )}

      <div className={styles.actions}>
        {!multiAgentDefault && (
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
        )}
        <Button
          type="primary"
          loading={saving}
          onClick={() => void save()}
          disabled={
            !isListScope
              ? !draft.trim()
              : dirsWithPending.length === 0 ||
                (isUntouchedFallback && !pendingIsAddable)
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
          {isListScope && appliedCount > 1 && (
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

  if (inline) {
    return <div className={styles.inlineEditor}>{panel}</div>;
  }

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
