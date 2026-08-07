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
import { Modal, Switch } from "antd";
import {
  ArrowLeftRight,
  ChevronDown,
  ChevronRight,
  File,
  FileCode2,
  FileText,
  Folder,
  FolderOpen,
  GripVertical,
  LoaderCircle,
  Network,
  Settings2,
  RefreshCw,
  Upload,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { UploadConflictError, workspaceApi } from "../../api/modules/workspace";
import { chatProjectDirectoryApi } from "../../api/modules/chatProjectDirectory";
import { projectDirectoryApi } from "../../api/modules/projectDirectory";
import { useCodingTabsStore } from "../../stores/codingTabsStore";
import SessionProjectDirectory from "../project-directory/SessionProjectDirectory";
import { getPendingProjectDirectory } from "../project-directory/pendingProjectDirectory";
import { directoriesMatch, workspaceRoots } from "./directorySources";
import { isDefaultWorkspaceMarkdown } from "./defaultWorkspaceMarkdown";
import {
  filesWorkspaceScopeKey,
  type FilesWorkspaceScope,
} from "./filesWorkspaceScope";
import { buildMemoryTree, type MemoryTreeEntry } from "./memoryTree";
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

function FileGlyph({ name }: { name: string }) {
  const extension = name.split(".").pop()?.toLowerCase();
  if (["md", "mdx", "txt", "log", "csv"].includes(extension ?? "")) {
    return <FileText size={15} />;
  }
  if (
    [
      "py",
      "ts",
      "tsx",
      "js",
      "jsx",
      "go",
      "rs",
      "java",
      "html",
      "css",
    ].includes(extension ?? "")
  ) {
    return <FileCode2 size={15} />;
  }
  return <File size={15} />;
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
  const [profileFiles, setProfileFiles] = useState<DirectoryEntry[]>([]);
  const [dailyFiles, setDailyFiles] = useState<MemoryTreeEntry[]>([]);
  const [digestFiles, setDigestFiles] = useState<MemoryTreeEntry[]>([]);
  const [enabledFiles, setEnabledFiles] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [cursor, setCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [pendingUploads, setPendingUploads] = useState<File[] | null>(null);
  const [conflictingNames, setConflictingNames] = useState<string[]>([]);
  const [source, setSource] = useState<NavigatorSource>("workspace");
  const [projectDirectory, setProjectDirectory] = useState("");
  const [workspaceDirectory, setWorkspaceDirectory] = useState("");
  const [workspaceRoot, setWorkspaceRoot] = useState<WorkspaceRoot>("project");
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
    const hasUnsavedProjectState = tabs.some(
      (tab) =>
        (tab.workspaceRoot ?? "project") === "project" &&
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

  const sameDirectory = useMemo(
    () =>
      directoriesMatch(projectDirectory, workspaceDirectory) &&
      Boolean(workspaceDirectory),
    [projectDirectory, workspaceDirectory],
  );
  const roots = useMemo(() => workspaceRoots(sameDirectory), [sameDirectory]);
  const managedProfileNames = useMemo(
    () => new Set(profileFiles.map((file) => file.path)),
    [profileFiles],
  );

  const loadDirectoryIdentity = useCallback(async () => {
    const agentInfo = await projectDirectoryApi.get();
    const effectiveProject = projectDirOverride
      ? projectDirOverride
      : chatId
      ? (await chatProjectDirectoryApi.get(chatId)).project_dir
      : agentInfo.path;
    setProjectDirectory(effectiveProject);
    setWorkspaceDirectory(agentInfo.workspace_dir ?? agentInfo.path);
  }, [chatId, projectDirOverride]);

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
      setEnabledFiles(order);
      setProfileFiles(
        files
          .filter((file) => isDefaultWorkspaceMarkdown(file.filename))
          .map((file) => ({
            name: file.filename.split("/").pop() ?? file.filename,
            path: file.filename,
            kind: "file" as const,
            size: file.size,
            modified_at: file.modified_time,
            preview_kind: "text" as const,
          }))
          .sort((left, right) => {
            const leftIndex = order.indexOf(left.path);
            const rightIndex = order.indexOf(right.path);
            if (leftIndex >= 0 && rightIndex >= 0) {
              return leftIndex - rightIndex;
            }
            if (leftIndex >= 0) return -1;
            if (rightIndex >= 0) return 1;
            return left.name.localeCompare(right.name);
          }),
      );
    } finally {
      setLoading(false);
    }
  }, []);

  const loadMemory = useCallback(async (section: "daily" | "digest") => {
    setLoading(true);
    try {
      const files = await workspaceApi.listMemoryFiles(section);
      const tree = buildMemoryTree(
        files.map((file) => ({
          name: file.filename.split("/").pop() ?? file.filename,
          path: file.filename,
          kind: "file" as const,
          size: file.size,
          modified_at: file.modified_time,
          preview_kind: "text" as const,
        })),
      );
      if (section === "daily") setDailyFiles(tree);
      else setDigestFiles(tree);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void Promise.all([loadDirectoryIdentity(), loadRoot(), loadProfile()]);
  }, [loadDirectoryIdentity, loadProfile, loadRoot]);

  useEffect(() => {
    if (sameDirectory) setWorkspaceRoot("workspace");
  }, [sameDirectory]);

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

  const reorderProfileFiles = async (event: DragEndEvent) => {
    if (!event.over || event.active.id === event.over.id) return;
    const oldIndex = enabledFiles.indexOf(String(event.active.id));
    const newIndex = enabledFiles.indexOf(String(event.over.id));
    if (oldIndex < 0 || newIndex < 0) return;
    const next = arrayMove(enabledFiles, oldIndex, newIndex);
    await workspaceApi.setSystemPromptFiles(next);
    setEnabledFiles(next);
    setProfileFiles((current) =>
      [...current].sort((left, right) => {
        const leftIndex = next.indexOf(left.path);
        const rightIndex = next.indexOf(right.path);
        if (leftIndex >= 0 && rightIndex >= 0) return leftIndex - rightIndex;
        if (leftIndex >= 0) return -1;
        if (rightIndex >= 0) return 1;
        return left.name.localeCompare(right.name);
      }),
    );
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
      data-root={workspaceRoot}
      aria-label={t("files.navigator")}
    >
      <header className={styles.navigatorHeader}>
        <div className={styles.directoryToolbar}>
          <div className={styles.directoryContext} data-root={workspaceRoot}>
            <span className={styles.directoryContextIcon}>
              {workspaceRoot === "project" ? (
                <FolderOpen size={15} />
              ) : (
                <Settings2 size={15} />
              )}
            </span>
            <div className={styles.directoryContextBody}>
              <span className={styles.directoryContextLabel}>
                {t(`files.${workspaceRoot}Directory`)}
              </span>
              {workspaceRoot === "project" ? (
                <SessionProjectDirectory
                  scope={scope}
                  showFullPath
                  beforeChange={confirmDirectoryChange}
                  onChanged={handleDirectoryChanged}
                />
              ) : (
                <span className={styles.directoryIdentity}>
                  <span className={styles.directoryIdentityText}>
                    <strong>
                      {workspaceDirectory
                        .replace(/[\\/]+$/, "")
                        .split(/[\\/]/)
                        .pop() || t("files.workspaceDirectory")}
                    </strong>
                    <span title={workspaceDirectory}>{workspaceDirectory}</span>
                  </span>
                </span>
              )}
            </div>
            {roots.length > 1 && (
              <button
                type="button"
                className={styles.directorySwitch}
                onClick={() =>
                  setWorkspaceRoot((current) =>
                    current === "project" ? "workspace" : "project",
                  )
                }
                aria-label={t("files.switchDirectory")}
                title={t("files.switchDirectory")}
              >
                <ArrowLeftRight size={14} />
              </button>
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
