import {
  DndContext,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  arrayMove,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { Dropdown, Modal, Switch, type MenuProps } from "antd";
import {
  Check,
  ChevronDown,
  ChevronRight,
  Folder,
  FolderOpen,
  GripVertical,
  LoaderCircle,
  Network,
  Plus,
  Settings2,
  RefreshCw,
  Upload,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { UploadConflictError, workspaceApi } from "../../api/modules/workspace";
import {
  chatProjectDirectoryApi,
  type ProjectDirEntry,
} from "../../api/modules/chatProjectDirectory";
import { projectDirectoryApi } from "../../api/modules/projectDirectory";
import { useCodingTabsStore } from "../../stores/codingTabsStore";
import SessionProjectDirectory from "../project-directory/SessionProjectDirectory";
import { getPendingProjectDirectory } from "../project-directory/pendingProjectDirectory";
import { loadSessionProjectDirs } from "../project-directory/loadSessionProjectDirs";
import {
  isProjectRoot,
  projectRootPath,
  workspaceRoots,
} from "./directorySources";
import FileGlyph from "./FileGlyph";
import {
  filesWorkspaceScopeKey,
  type FilesWorkspaceScope,
} from "./filesWorkspaceScope";
import {
  buildDailyMemoryTree,
  buildMemoryTree,
  type MemoryTreeEntry,
} from "./memoryTree";
import { selectProfileFiles } from "./profileFileSelection";
import type {
  DirectoryEntry,
  FileTarget,
  MemoryGraphRoot,
  WorkspaceRoot,
} from "./types";
import styles from "./FilesWorkspace.module.less";

interface DirectoryNodeProps {
  entry: DirectoryEntry;
  chatId?: string;
  projectDirOverride?: string;
  selectedPath: string;
  onSelect: (target: FileTarget) => void;
  depth: number;
  root: WorkspaceRoot;
}

interface ProfileFileRowProps {
  entry: DirectoryEntry;
  enabled: boolean;
  selected: boolean;
  onSelect: () => void;
  onToggle: () => void;
}

type NavigatorSource = "workspace" | "profile" | "daily" | "digest";

/** Switcher entry that opens the binding panel instead of changing the root. */
const MANAGE_DIRS_KEY = "__manage_project_dirs__";

/** Last path segment, for the short display name of a directory. */
function basenameOf(path: string): string {
  const trimmed = path.replace(/[\\/]+$/, "");
  return trimmed.split(/[\\/]/).pop() || trimmed;
}

function ProfileFileRow({
  entry,
  enabled,
  selected,
  onSelect,
  onToggle,
}: ProfileFileRowProps) {
  const { t } = useTranslation();
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({
    id: entry.path,
    disabled: !enabled,
  });

  return (
    <div
      ref={setNodeRef}
      className={`${styles.profileRow} ${
        selected ? styles.treeRowSelected : ""
      } ${isDragging ? styles.profileRowDragging : ""}`}
      style={{
        transform: CSS.Transform.toString(transform),
        transition,
      }}
    >
      <button type="button" className={styles.profileOpen} onClick={onSelect}>
        {enabled && (
          <span
            className={styles.dragHandle}
            {...attributes}
            {...listeners}
            onClick={(event) => event.stopPropagation()}
          >
            <GripVertical size={13} />
          </span>
        )}
        <FileGlyph name={entry.name} />
        <span>{entry.name}</span>
      </button>
      <Switch
        size="small"
        checked={enabled}
        aria-label={t("files.promptToggle", { name: entry.name })}
        onClick={(_checked, event) => {
          event.stopPropagation();
          onToggle();
        }}
      />
    </div>
  );
}

function DirectoryNode({
  entry,
  chatId,
  projectDirOverride,
  selectedPath,
  onSelect,
  depth,
  root,
}: DirectoryNodeProps) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [children, setChildren] = useState<DirectoryEntry[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);

  const load = useCallback(
    async (nextCursor?: string) => {
      setLoading(true);
      try {
        const page = await workspaceApi.listDirectory(
          entry.path,
          nextCursor,
          200,
          chatId,
          root,
          projectDirOverride,
        );
        setChildren((current) =>
          nextCursor ? [...current, ...page.entries] : page.entries,
        );
        setCursor(page.next_cursor);
        setHasMore(page.has_more);
      } finally {
        setLoading(false);
      }
    },
    [chatId, entry.path, projectDirOverride, root],
  );

  const toggle = () => {
    setExpanded((current) => !current);
    if (!expanded && children.length === 0) void load();
  };

  return (
    <>
      <button
        type="button"
        className={styles.treeRow}
        style={{ paddingInlineStart: 12 + depth * 16 }}
        onClick={toggle}
        aria-expanded={expanded}
      >
        {expanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
        {expanded ? <FolderOpen size={15} /> : <Folder size={15} />}
        <span>{entry.name}</span>
        {loading && <LoaderCircle className={styles.spin} size={13} />}
      </button>
      {expanded &&
        children.map((child) =>
          child.kind === "directory" ? (
            <DirectoryNode
              key={child.path}
              entry={child}
              chatId={chatId}
              projectDirOverride={projectDirOverride}
              depth={depth + 1}
              selectedPath={selectedPath}
              onSelect={onSelect}
              root={root}
            />
          ) : (
            <button
              type="button"
              key={child.path}
              className={`${styles.treeRow} ${
                child.path === selectedPath ? styles.treeRowSelected : ""
              }`}
              style={{ paddingInlineStart: 29 + (depth + 1) * 16 }}
              onClick={() =>
                onSelect({ source: "workspace", path: child.path, root })
              }
            >
              <FileGlyph name={child.name} />
              <span>{child.name}</span>
            </button>
          ),
        )}
      {expanded && hasMore && (
        <button
          type="button"
          className={styles.loadMore}
          onClick={() => void load(cursor ?? undefined)}
          disabled={loading}
        >
          {t("files.loadMore")}
        </button>
      )}
    </>
  );
}

function MemoryDirectoryNode({
  entry,
  selectedPath,
  onSelect,
  depth,
  source,
  activeGraphRoot,
  onShowGraph,
}: {
  entry: MemoryTreeEntry;
  selectedPath: string;
  onSelect: (target: FileTarget) => void;
  depth: number;
  source: "daily" | "digest";
  activeGraphRoot: MemoryGraphRoot | null;
  onShowGraph: (root: MemoryGraphRoot) => void;
}) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);
  const graphRoot =
    source === "digest" &&
    depth === 0 &&
    (["wiki", "procedure", "personal"] as string[]).includes(entry.name)
      ? (entry.name as MemoryGraphRoot)
      : null;

  return (
    <>
      <div
        className={`${styles.memoryDirectoryRow} ${
          graphRoot && graphRoot === activeGraphRoot
            ? styles.memoryDirectoryGraphActive
            : ""
        }`}
      >
        <button
          type="button"
          className={styles.treeRow}
          style={{ paddingInlineStart: 12 + depth * 16 }}
          onClick={() => setExpanded((current) => !current)}
          aria-expanded={expanded}
        >
          {expanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
          {expanded ? <FolderOpen size={15} /> : <Folder size={15} />}
          <span>{entry.name}</span>
        </button>
        {graphRoot && (
          <button
            type="button"
            className={styles.memoryDirectoryGraphButton}
            onClick={() => onShowGraph(graphRoot)}
            aria-label={`${t("files.memoryGraph")} · ${entry.name}`}
            title={`${t("files.memoryGraph")} · ${entry.name}`}
            aria-pressed={graphRoot === activeGraphRoot}
          >
            <Network size={14} />
            <span>{t("files.memoryGraphShort")}</span>
          </button>
        )}
      </div>
      {expanded &&
        entry.children?.map((child) =>
          child.kind === "directory" ? (
            <MemoryDirectoryNode
              key={child.path}
              entry={child}
              selectedPath={selectedPath}
              onSelect={onSelect}
              depth={depth + 1}
              source={source}
              activeGraphRoot={activeGraphRoot}
              onShowGraph={onShowGraph}
            />
          ) : (
            <button
              type="button"
              key={child.path}
              className={`${styles.treeRow} ${
                child.path === selectedPath ? styles.treeRowSelected : ""
              }`}
              style={{ paddingInlineStart: 29 + (depth + 1) * 16 }}
              onClick={() =>
                onSelect({
                  source,
                  path: child.path,
                })
              }
            >
              <FileGlyph name={child.name} />
              <span>{child.name}</span>
            </button>
          ),
        )}
    </>
  );
}

interface FilesNavigatorProps {
  selectedPath: string;
  onSelect: (target: FileTarget) => void;
  activeMemoryGraphRoot: MemoryGraphRoot | null;
  onShowMemoryGraph: (root: MemoryGraphRoot) => void;
  onShowFiles: () => void;
  scope: FilesWorkspaceScope;
}

export default function FilesNavigator({
  selectedPath,
  onSelect,
  activeMemoryGraphRoot,
  onShowMemoryGraph,
  onShowFiles,
  scope,
}: FilesNavigatorProps) {
  const { t } = useTranslation();
  const chatId = scope.kind === "session" ? scope.chatId : undefined;
  // Depend on these primitives rather than on `scope`: the parent rebuilds the
  // scope object on every render, so a callback keyed on it would re-run the
  // directory fetches whenever anything unrelated re-renders.
  const scopeKind = scope.kind;
  const agentId = scope.agentId;
  const sessionId = scope.kind === "session" ? scope.sessionId : "";
  const initialProjectDirOverride =
    scope.kind === "session" ? scope.projectDirOverride : undefined;
  const [pendingProjectDir, setPendingProjectDir] = useState(
    initialProjectDirOverride,
  );
  const projectDirOverride =
    scope.kind === "session" && !scope.chatId
      ? pendingProjectDir
      : initialProjectDirOverride;
  const scopeKey = filesWorkspaceScopeKey(scope);
  const [entries, setEntries] = useState<DirectoryEntry[]>([]);
  const [allProfileFiles, setAllProfileFiles] = useState<DirectoryEntry[]>([]);
  const [dailyFiles, setDailyFiles] = useState<MemoryTreeEntry[]>([]);
  const [digestFiles, setDigestFiles] = useState<MemoryTreeEntry[]>([]);
  const [enabledFiles, setEnabledFiles] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [cursor, setCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [pendingUploads, setPendingUploads] = useState<File[] | null>(null);
  const [conflictingNames, setConflictingNames] = useState<string[]>([]);
  const [profilePickerOpen, setProfilePickerOpen] = useState(false);
  const [profileSearch, setProfileSearch] = useState("");
  const [source, setSource] = useState<NavigatorSource>("workspace");
  const [projectDirectory, setProjectDirectory] = useState("");
  const [workspaceDirectory, setWorkspaceDirectory] = useState("");
  const [workspaceRoot, setWorkspaceRoot] = useState<WorkspaceRoot>("project");
  // Every directory bound to this session, primary first. Only session scope
  // can hold more than one — an agent default is a single directory — so agent
  // scope keeps the synthesized single-entry list below.
  const [boundDirs, setBoundDirs] = useState<ProjectDirEntry[]>([]);
  // Opens the binding panel from the switcher's "manage directories" item.
  const [managingDirs, setManagingDirs] = useState(false);
  const uploadRef = useRef<HTMLInputElement>(null);
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
  );

  useEffect(() => {
    setPendingProjectDir(initialProjectDirOverride);
  }, [initialProjectDirOverride, scopeKey]);

  const confirmDirectoryChange = useCallback(async () => {
    const state = useCodingTabsStore.getState();
    const tabs = state.tabsByAgent[scopeKey] ?? [];
    const diffs = state.diffsByAgent[scopeKey] ?? {};
    // Every project root, matching what `clearProjectTabs` tears down: an
    // unsaved file in an extra root would otherwise be discarded silently.
    const hasUnsavedProjectState = tabs.some(
      (tab) =>
        isProjectRoot(tab.workspaceRoot) &&
        (tab.dirty || Boolean(diffs[tab.path])),
    );
    if (!hasUnsavedProjectState) return true;
    return new Promise<boolean>((resolve) => {
      Modal.confirm({
        title: t("files.changeDirectoryTitle"),
        content: t("files.changeDirectoryWarning"),
        okText: t("common.confirm"),
        cancelText: t("common.cancel"),
        onOk: () => resolve(true),
        onCancel: () => resolve(false),
      });
    });
  }, [scopeKey, t]);

  const handleDirectoryChanged = useCallback(() => {
    useCodingTabsStore.getState().clearProjectTabs(scopeKey);
    if (scope.kind === "session" && !scope.chatId) {
      setPendingProjectDir(
        getPendingProjectDirectory(scope.agentId, scope.sessionId) ?? undefined,
      );
    }
  }, [scope, scopeKey]);

  /**
   * A chat with no server id has nothing persisted, and its pending selection
   * reaches the Files API as a single primary path — so only that directory can
   * actually be served. Offering the rest would produce rows that 403 on click.
   */
  const extraRootsPending = scopeKind === "session" && !chatId;

  /** The bound list, or the single known project dir while it is still loading
   *  (and always, on agent scope). Keeps the switcher stable during the first
   *  render instead of briefly collapsing to workspace-only. */
  const rootDirs = useMemo<ProjectDirEntry[]>(() => {
    const fallback: ProjectDirEntry[] = projectDirectory
      ? [
          {
            path: projectDirectory,
            label: null,
            exists: true,
            nested_with: null,
            // This is only the pre-fetch fallback. Both values come from the
            // same API response here; the server-provided entry replaces it
            // once the bound-directory snapshot has loaded.
            is_workspace: projectDirectory === workspaceDirectory,
          },
        ]
      : [];
    if (extraRootsPending || boundDirs.length === 0) return fallback;
    return boundDirs;
  }, [boundDirs, extraRootsPending, projectDirectory, workspaceDirectory]);

  /** How many bound directories the switcher cannot offer yet.
   *
   *  The primary travels as the single pending header, and the agent workspace
   *  always has a root of its own — neither is waiting on anything, so neither
   *  counts. A session that binds only those two must report zero, not one. */
  const pendingRootCount = useMemo(
    () =>
      extraRootsPending
        ? boundDirs
            .slice(1)
            .filter((entry) => entry.path && !entry.is_workspace).length
        : 0,
    [boundDirs, extraRootsPending],
  );
  const roots = useMemo(() => workspaceRoots(rootDirs), [rootDirs]);
  const profileFiles = useMemo(
    () => selectProfileFiles(allProfileFiles, enabledFiles),
    [allProfileFiles, enabledFiles],
  );
  /** Coarse flavour for styling; the precise root lives in `workspaceRoot`. */
  const rootFlavour = isProjectRoot(workspaceRoot) ? "project" : "workspace";

  /** Name, path and status to render for one root in the switcher. */
  const describeRoot = useCallback(
    (root: WorkspaceRoot) => {
      if (root === "workspace") {
        return {
          path: workspaceDirectory,
          name: basenameOf(workspaceDirectory) || t("files.workspaceDirectory"),
          missing: false,
          // A session with nothing bound resolves its primary to the workspace,
          // which collapses onto this root — so the tag belongs here too, or
          // the switcher would show no primary at all.
          primary: Boolean(rootDirs[0]?.is_workspace),
        };
      }
      const rootPath = projectRootPath(root);
      // Exact match: `rootPath` was copied verbatim out of one of these
      // entries by `projectRootFor`, so there is no spelling to reconcile —
      // and folding case here could match the wrong entry when two bound
      // roots differ only in case, which a case-sensitive volume allows.
      const index = rootPath
        ? rootDirs.findIndex((entry) => entry.path === rootPath)
        : 0;
      const entry = index >= 0 ? rootDirs[index] : undefined;
      const path = entry?.path ?? rootPath ?? projectDirectory;
      return {
        path,
        name: entry?.label || basenameOf(path) || t("files.projectDirectory"),
        // An entry the resolver could not find is flagged rather than hidden:
        // silently dropping it would look like the binding was lost.
        missing: entry ? !entry.exists : false,
        primary: index === 0,
      };
    },
    [projectDirectory, rootDirs, t, workspaceDirectory],
  );

  const activeRoot = describeRoot(workspaceRoot);

  const rootMenuItems = useMemo<MenuProps["items"]>(() => {
    const items: NonNullable<MenuProps["items"]> = [];
    roots.forEach((root) => {
      // The workspace is the agent's own storage, not project content — keep it
      // visually separate from the directories the session works in.
      if (root === "workspace" && items.length > 0) {
        items.push({ type: "divider" });
      }
      const info = describeRoot(root);
      items.push({
        key: root,
        label: (
          <span className={styles.rootOption}>
            <span className={styles.rootOptionIcon}>
              {root === "workspace" ? (
                <Settings2 size={14} />
              ) : (
                <FolderOpen size={14} />
              )}
            </span>
            <span className={styles.rootOptionCopy}>
              <strong>{info.name}</strong>
              <small title={info.path}>{info.path}</small>
            </span>
            {info.primary && (
              <em className={styles.rootOptionTag}>{t("files.primaryRoot")}</em>
            )}
            {info.missing && (
              <em className={styles.rootOptionTagMissing}>
                {t("files.rootMissing")}
              </em>
            )}
            {root === workspaceRoot && (
              <span className={styles.rootOptionCheck}>
                <Check size={13} />
              </span>
            )}
          </span>
        ),
      });
    });
    if (pendingRootCount > 0) {
      items.push({
        key: "__pending_roots__",
        disabled: true,
        label: (
          <small className={styles.rootOptionHint}>
            {t("files.rootsPending", { count: pendingRootCount })}
          </small>
        ),
      });
    }
    if (scopeKind === "session") {
      items.push(
        { type: "divider" },
        { key: MANAGE_DIRS_KEY, label: t("files.manageDirs") },
      );
    }
    return items;
  }, [describeRoot, pendingRootCount, roots, scopeKind, t, workspaceRoot]);
  const managedProfileNames = useMemo(
    () => new Set(profileFiles.map((file) => file.path)),
    [profileFiles],
  );
  const availableProfileFiles = useMemo(() => {
    const query = profileSearch.trim().toLocaleLowerCase();
    return allProfileFiles.filter(
      (file) =>
        !managedProfileNames.has(file.path) &&
        (!query || file.name.toLocaleLowerCase().includes(query)),
    );
  }, [allProfileFiles, managedProfileNames, profileSearch]);

  const loadDirectoryIdentity = useCallback(async () => {
    const agentInfo = await projectDirectoryApi.get();
    const effectiveProject = projectDirOverride
      ? projectDirOverride
      : chatId
      ? (await chatProjectDirectoryApi.get(chatId)).project_dir
      : agentInfo.path;
    setProjectDirectory(effectiveProject);
    setWorkspaceDirectory(agentInfo.workspace_dir ?? agentInfo.path);
    if (scopeKind !== "session") {
      // Agent scope binds a single directory; nothing to switch between.
      setBoundDirs([]);
      return;
    }
    try {
      const snapshot = await loadSessionProjectDirs(agentId, sessionId, chatId);
      setBoundDirs(snapshot.dirs);
    } catch {
      // Fall back to the single directory above rather than blanking the
      // switcher: the tree itself is still perfectly usable.
      setBoundDirs([]);
    }
  }, [agentId, chatId, projectDirOverride, scopeKind, sessionId]);

  const loadRoot = useCallback(async () => {
    setLoading(true);
    try {
      const page = await workspaceApi.listDirectory(
        "",
        undefined,
        200,
        chatId,
        workspaceRoot,
        projectDirOverride,
      );
      setEntries(page.entries);
      setCursor(page.next_cursor);
      setHasMore(page.has_more);
    } finally {
      setLoading(false);
    }
  }, [chatId, projectDirOverride, workspaceRoot]);

  const loadProfile = useCallback(async () => {
    setLoading(true);
    try {
      const [files, enabled] = await Promise.all([
        workspaceApi.listFiles(),
        workspaceApi.getSystemPromptFiles(),
      ]);
      const order = Array.isArray(enabled) ? enabled : [];
      const mappedFiles = files.map((file) => ({
        name: file.filename.split("/").pop() ?? file.filename,
        path: file.filename,
        kind: "file" as const,
        size: file.size,
        modified_at: file.modified_time,
        preview_kind: "text" as const,
      }));
      setEnabledFiles(order);
      setAllProfileFiles(mappedFiles);
    } finally {
      setLoading(false);
    }
  }, []);

  const loadMemory = useCallback(async (section: "daily" | "digest") => {
    setLoading(true);
    try {
      const files = await workspaceApi.listMemoryFiles(section);
      const entries = files.map((file) => ({
        name: file.filename.split("/").pop() ?? file.filename,
        path: file.filename,
        kind: "file" as const,
        size: file.size,
        modified_at: file.modified_time,
        preview_kind: "text" as const,
      }));
      const tree =
        section === "daily"
          ? buildDailyMemoryTree(entries)
          : buildMemoryTree(entries);
      if (section === "daily") setDailyFiles(tree);
      else setDigestFiles(tree);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void Promise.all([loadDirectoryIdentity(), loadRoot(), loadProfile()]);
  }, [loadDirectoryIdentity, loadProfile, loadRoot]);

  // Keep the viewed root one the switcher actually offers. Covers both the
  // primary-is-the-workspace case (where "project" is never offered) and a
  // rebind that dropped the directory currently on screen.
  //
  // `roots` is empty until the directory list arrives, and that is precisely
  // when this must not fire: switching to a provisional root would strand the
  // tree there, because the real list contains that root too and this effect
  // would have nothing left to correct.
  useEffect(() => {
    if (roots.length === 0 || roots.includes(workspaceRoot)) return;
    setWorkspaceRoot(roots[0]);
  }, [roots, workspaceRoot]);

  useEffect(() => {
    if (source === "profile") void loadProfile();
    if (source === "daily" || source === "digest") void loadMemory(source);
  }, [loadMemory, loadProfile, source]);

  const refreshCurrent = async () => {
    if (source === "daily" || source === "digest") {
      await loadMemory(source);
      return;
    }
    if (source === "profile") {
      await loadProfile();
      return;
    }
    await loadRoot();
  };

  const runUpload = async (
    files: File[],
    conflict?: "overwrite" | "skip" | "rename",
  ) => {
    setUploading(true);
    try {
      await workspaceApi.uploadFiles(
        files,
        "",
        conflict,
        chatId,
        workspaceRoot,
        projectDirOverride,
      );
      setPendingUploads(null);
      setConflictingNames([]);
      await Promise.all([loadRoot(), loadProfile()]);
    } catch (error) {
      if (error instanceof UploadConflictError) {
        setPendingUploads(files);
        setConflictingNames(error.files);
        return;
      }
      throw error;
    } finally {
      setUploading(false);
    }
  };

  const toggleProfileFile = async (filename: string) => {
    const next = enabledFiles.includes(filename)
      ? enabledFiles.filter((file) => file !== filename)
      : [...enabledFiles, filename];
    await workspaceApi.setSystemPromptFiles(next);
    setEnabledFiles(next);
  };

  const addProfileFile = async (filename: string) => {
    if (enabledFiles.includes(filename)) return;
    const next = [...enabledFiles, filename];
    await workspaceApi.setSystemPromptFiles(next);
    setEnabledFiles(next);
    setProfilePickerOpen(false);
    setProfileSearch("");
  };

  const reorderProfileFiles = async (event: DragEndEvent) => {
    if (!event.over || event.active.id === event.over.id) return;
    const oldIndex = enabledFiles.indexOf(String(event.active.id));
    const newIndex = enabledFiles.indexOf(String(event.over.id));
    if (oldIndex < 0 || newIndex < 0) return;
    const next = arrayMove(enabledFiles, oldIndex, newIndex);
    await workspaceApi.setSystemPromptFiles(next);
    setEnabledFiles(next);
  };

  const displayEntries = useMemo(() => {
    if (source === "daily") return dailyFiles;
    if (source === "digest") return digestFiles;
    if (source === "profile") return profileFiles;
    if (source === "workspace") return entries;
    return [];
  }, [dailyFiles, digestFiles, entries, profileFiles, source]);

  return (
    <aside
      className={styles.navigator}
      data-source={source}
      data-root={rootFlavour}
      aria-label={t("files.navigator")}
    >
      <header className={styles.navigatorHeader}>
        <div className={styles.directoryToolbar}>
          <div className={styles.directoryContext} data-root={rootFlavour}>
            <span className={styles.directoryContextIcon}>
              {isProjectRoot(workspaceRoot) ? (
                <FolderOpen size={15} />
              ) : (
                <Settings2 size={15} />
              )}
            </span>
            <div className={styles.directoryContextBody}>
              <span className={styles.directoryContextLabel}>
                {t(`files.${rootFlavour}Directory`)}
              </span>
              {/* One plain-text identity for every root. Binding is reached
                  through the switcher's "manage directories" item, so the
                  header does not carry a second interactive control. */}
              <span className={styles.directoryIdentity}>
                <span className={styles.directoryIdentityText}>
                  <strong>{activeRoot.name}</strong>
                  <span title={activeRoot.path}>{activeRoot.path}</span>
                </span>
                {activeRoot.missing && (
                  <em className={styles.rootOptionTagMissing}>
                    {t("files.rootMissing")}
                  </em>
                )}
              </span>
              {scopeKind === "session" && (
                <SessionProjectDirectory
                  scope={scope}
                  showFullPath
                  hideTrigger
                  open={managingDirs}
                  onOpenChange={setManagingDirs}
                  beforeChange={confirmDirectoryChange}
                  onChanged={() => {
                    handleDirectoryChanged();
                    void loadDirectoryIdentity();
                  }}
                />
              )}
            </div>
            {/* Session scope always gets the trigger, even with a single root:
                it is the only way to reach "manage directories", and a session
                with nothing bound yet has exactly one root — the case where
                binding a directory matters most. */}
            {(roots.length > 1 || scopeKind === "session") && (
              <Dropdown
                menu={{
                  items: rootMenuItems,
                  selectedKeys: [workspaceRoot],
                  onClick: ({ key }) => {
                    if (key === MANAGE_DIRS_KEY) {
                      setManagingDirs(true);
                      return;
                    }
                    // Only the viewed root changes — open editor tabs keep the
                    // root they were opened from, so nothing is invalidated and
                    // no unsaved-changes confirmation is owed here.
                    setWorkspaceRoot(key as WorkspaceRoot);
                  },
                }}
                trigger={["click"]}
                placement="bottomRight"
              >
                <button
                  type="button"
                  className={styles.directorySwitch}
                  aria-label={t("files.switchRoot")}
                  title={t("files.switchRoot")}
                >
                  <ChevronDown size={14} />
                </button>
              </Dropdown>
            )}
          </div>
          <div className={styles.directoryTools}>
            <button
              type="button"
              className={styles.iconButton}
              onClick={() => void refreshCurrent()}
              aria-label={t("common.refresh")}
            >
              <RefreshCw size={15} />
            </button>
            <button
              type="button"
              className={styles.iconButton}
              onClick={() => uploadRef.current?.click()}
              aria-label={t("files.upload")}
              disabled={uploading}
            >
              {uploading ? (
                <LoaderCircle className={styles.spin} size={15} />
              ) : (
                <Upload size={15} />
              )}
            </button>
          </div>
        </div>
        <input
          ref={uploadRef}
          type="file"
          multiple
          hidden
          onChange={(event) => {
            const files = Array.from(event.target.files ?? []);
            event.target.value = "";
            if (files.length > 0) void runUpload(files);
          }}
        />
      </header>
      <div className={styles.sourceTabs} role="tablist">
        {(["workspace", "profile", "daily", "digest"] as NavigatorSource[]).map(
          (item) => (
            <button
              type="button"
              role="tab"
              aria-selected={source === item}
              key={item}
              className={`${styles.sourceTab} ${
                source === item ? styles.sourceTabActive : ""
              }`}
              data-source={item}
              onClick={() => {
                setSource(item);
                onShowFiles();
              }}
            >
              {t(`files.${item}`)}
            </button>
          ),
        )}
      </div>
      <DndContext
        sensors={sensors}
        collisionDetection={closestCenter}
        onDragEnd={(event) => void reorderProfileFiles(event)}
      >
        <SortableContext
          items={enabledFiles}
          strategy={verticalListSortingStrategy}
        >
          <div className={styles.tree} role="tree" aria-busy={loading}>
            {source === "profile" && (
              <button
                type="button"
                className={styles.profileAddButton}
                onClick={() => setProfilePickerOpen(true)}
              >
                <Plus size={14} />
                <span>{t("files.addSystemPrompt")}</span>
              </button>
            )}
            {loading && displayEntries.length === 0 ? (
              <div className={styles.empty}>
                <LoaderCircle className={styles.spin} size={16} />
                {t("common.loading")}
              </div>
            ) : (
              displayEntries.map((entry) => {
                if (entry.kind === "directory") {
                  if (source === "daily" || source === "digest") {
                    return (
                      <MemoryDirectoryNode
                        key={entry.path}
                        entry={entry}
                        selectedPath={selectedPath}
                        onSelect={onSelect}
                        depth={0}
                        source={source}
                        activeGraphRoot={activeMemoryGraphRoot}
                        onShowGraph={onShowMemoryGraph}
                      />
                    );
                  }
                  return (
                    <DirectoryNode
                      key={entry.path}
                      entry={entry}
                      chatId={chatId}
                      projectDirOverride={projectDirOverride}
                      depth={0}
                      selectedPath={selectedPath}
                      onSelect={onSelect}
                      root={workspaceRoot}
                    />
                  );
                }
                const isProfileFile =
                  source === "profile" && managedProfileNames.has(entry.path);
                if (isProfileFile) {
                  return (
                    <ProfileFileRow
                      key={entry.path}
                      entry={entry}
                      enabled={enabledFiles.includes(entry.path)}
                      selected={entry.path === selectedPath}
                      onSelect={() =>
                        onSelect({ source: "profile", path: entry.path })
                      }
                      onToggle={() => void toggleProfileFile(entry.path)}
                    />
                  );
                }
                return (
                  <button
                    type="button"
                    key={entry.path}
                    className={`${styles.treeRow} ${
                      entry.path === selectedPath ? styles.treeRowSelected : ""
                    }`}
                    onClick={() =>
                      onSelect({
                        source,
                        path: entry.path,
                        root:
                          source === "workspace" ? workspaceRoot : undefined,
                      })
                    }
                  >
                    <FileGlyph name={entry.name} />
                    <span>{entry.name}</span>
                  </button>
                );
              })
            )}
            {!loading && displayEntries.length === 0 && (
              <div className={styles.empty}>{t("files.sourceEmpty")}</div>
            )}
            {source === "workspace" && hasMore && (
              <button
                type="button"
                className={styles.loadMore}
                onClick={async () => {
                  const page = await workspaceApi.listDirectory(
                    "",
                    cursor ?? undefined,
                    200,
                    chatId,
                    workspaceRoot,
                    projectDirOverride,
                  );
                  setEntries((current) => [...current, ...page.entries]);
                  setCursor(page.next_cursor);
                  setHasMore(page.has_more);
                }}
              >
                {t("files.loadMore")}
              </button>
            )}
          </div>
        </SortableContext>
      </DndContext>
      <Modal
        className={styles.profilePickerModal}
        open={profilePickerOpen}
        title={t("files.addSystemPromptTitle")}
        footer={null}
        centered
        onCancel={() => {
          setProfilePickerOpen(false);
          setProfileSearch("");
        }}
      >
        <p className={styles.profilePickerDescription}>
          {t("files.addSystemPromptDescription")}
        </p>
        <input
          className={styles.profilePickerSearch}
          value={profileSearch}
          onChange={(event) => setProfileSearch(event.target.value)}
          placeholder={t("files.searchSystemPromptFiles")}
          aria-label={t("files.searchSystemPromptFiles")}
          autoFocus
        />
        <div className={styles.profilePickerList}>
          {availableProfileFiles.map((file) => (
            <button
              type="button"
              key={file.path}
              className={styles.profilePickerItem}
              onClick={() => void addProfileFile(file.path)}
            >
              <FileGlyph name={file.name} />
              <span>{file.name}</span>
              <Plus size={14} />
            </button>
          ))}
          {availableProfileFiles.length === 0 && (
            <div className={styles.profilePickerEmpty}>
              {t("files.noSystemPromptCandidates")}
            </div>
          )}
        </div>
      </Modal>
      <Modal
        className={styles.conflictModal}
        open={pendingUploads !== null}
        title={t("files.uploadConflictTitle")}
        footer={null}
        centered
        onCancel={() => {
          setPendingUploads(null);
          setConflictingNames([]);
        }}
      >
        <p className={styles.conflictDescription}>
          {t("files.uploadConflictDescription", {
            files: conflictingNames.join(", "),
          })}
        </p>
        <div className={styles.conflictChoices}>
          {(["rename", "skip", "overwrite"] as const).map((policy) => (
            <button
              type="button"
              key={policy}
              className={styles.conflictChoice}
              data-danger={policy === "overwrite" || undefined}
              disabled={uploading}
              onClick={() => {
                if (pendingUploads) void runUpload(pendingUploads, policy);
              }}
            >
              <strong>
                {t(
                  `files.conflict${policy[0].toUpperCase()}${policy.slice(1)}`,
                )}
              </strong>
              <span>
                {t(
                  `files.conflict${policy[0].toUpperCase()}${policy.slice(
                    1,
                  )}Description`,
                )}
              </span>
            </button>
          ))}
        </div>
      </Modal>
    </aside>
  );
}
