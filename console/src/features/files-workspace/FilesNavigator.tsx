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
  Settings2,
  RefreshCw,
  Upload,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { UploadConflictError, workspaceApi } from "../../api/modules/workspace";
import { chatProjectDirectoryApi } from "../../api/modules/chatProjectDirectory";
import { projectDirectoryApi } from "../../api/modules/projectDirectory";
import SessionProjectDirectory from "../project-directory/SessionProjectDirectory";
import { directoriesMatch, workspaceRoots } from "./directorySources";
import type {
  DirectoryEntry,
  FileSource,
  FileTarget,
  WorkspaceRoot,
} from "./types";
import styles from "./FilesWorkspace.module.less";

interface DirectoryNodeProps {
  entry: DirectoryEntry;
  chatId?: string;
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
    [chatId, entry.path, root],
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

interface FilesNavigatorProps {
  selectedPath: string;
  onSelect: (target: FileTarget) => void;
  chatId?: string;
  sessionId: string;
}

export default function FilesNavigator({
  selectedPath,
  onSelect,
  chatId,
  sessionId,
}: FilesNavigatorProps) {
  const { t } = useTranslation();
  const [entries, setEntries] = useState<DirectoryEntry[]>([]);
  const [profileFiles, setProfileFiles] = useState<DirectoryEntry[]>([]);
  const [memoryFiles, setMemoryFiles] = useState<DirectoryEntry[]>([]);
  const [enabledFiles, setEnabledFiles] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [cursor, setCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [pendingUploads, setPendingUploads] = useState<File[] | null>(null);
  const [conflictingNames, setConflictingNames] = useState<string[]>([]);
  const [source, setSource] = useState<FileSource>("workspace");
  const [projectDirectory, setProjectDirectory] = useState("");
  const [workspaceDirectory, setWorkspaceDirectory] = useState("");
  const [workspaceRoot, setWorkspaceRoot] = useState<WorkspaceRoot>("project");
  const uploadRef = useRef<HTMLInputElement>(null);
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
  );

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
    const effectiveProject = chatId
      ? (await chatProjectDirectoryApi.get(chatId)).project_dir
      : agentInfo.path;
    setProjectDirectory(effectiveProject);
    setWorkspaceDirectory(agentInfo.workspace_dir ?? agentInfo.path);
  }, [chatId]);

  const loadRoot = useCallback(async () => {
    setLoading(true);
    try {
      const page = await workspaceApi.listDirectory(
        "",
        undefined,
        200,
        chatId,
        workspaceRoot,
      );
      setEntries(page.entries);
      setCursor(page.next_cursor);
      setHasMore(page.has_more);
    } finally {
      setLoading(false);
    }
  }, [chatId, workspaceRoot]);

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

  const loadMemory = useCallback(async () => {
    setLoading(true);
    try {
      const files = await workspaceApi.listDailyMemory();
      setMemoryFiles(
        files.map((file) => ({
          name: file.filename.split("/").pop() ?? file.filename,
          path: file.filename,
          kind: "file" as const,
          size: file.size,
          modified_at: file.modified_time,
          preview_kind: "text" as const,
        })),
      );
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
    if (source === "memory") void loadMemory();
  }, [loadMemory, loadProfile, source]);

  const refreshCurrent = async () => {
    if (source === "memory") {
      await loadMemory();
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
    if (source === "memory") return memoryFiles;
    if (source === "profile") return profileFiles;
    if (source === "workspace") return entries;
    return [];
  }, [entries, memoryFiles, profileFiles, source]);

  const canUpload = source === "workspace";

  return (
    <aside
      className={styles.navigator}
      data-source={source}
      data-root={source === "workspace" ? workspaceRoot : undefined}
      aria-label={t("files.navigator")}
    >
      <header className={styles.navigatorHeader}>
        <div className={styles.navigatorLocation}>
          <span className={styles.eyebrow}>{t(`files.${source}`)}</span>
          {source === "workspace" ? (
            <>
              <button
                type="button"
                className={styles.rootSwitch}
                data-root={workspaceRoot}
                disabled={roots.length === 1}
                onClick={() =>
                  setWorkspaceRoot((current) =>
                    current === "project" ? "workspace" : "project",
                  )
                }
              >
                {workspaceRoot === "project" ? (
                  <FolderOpen size={14} />
                ) : (
                  <Settings2 size={14} />
                )}
                <span>{t(`files.${workspaceRoot}Directory`)}</span>
                {roots.length > 1 && <ArrowLeftRight size={12} />}
              </button>
              {workspaceRoot === "project" ? (
                <SessionProjectDirectory
                  chatId={chatId}
                  sessionId={sessionId}
                  showFullPath
                  onChanged={() =>
                    void Promise.all([loadDirectoryIdentity(), loadRoot()])
                  }
                />
              ) : (
                <span className={styles.directoryIdentity}>
                  <Settings2 size={13} aria-hidden="true" />
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
            </>
          ) : source === "profile" ? (
            <strong>{t("files.profile")}</strong>
          ) : (
            <strong>{t("files.memory")}</strong>
          )}
        </div>
        <div className={styles.navigatorActions}>
          <button
            type="button"
            className={styles.iconButton}
            onClick={() => void refreshCurrent()}
            aria-label={t("common.refresh")}
          >
            <RefreshCw size={15} />
          </button>
          {canUpload && (
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
          )}
        </div>
        {canUpload && (
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
        )}
      </header>
      <div className={styles.sourceTabs} role="tablist">
        {(["workspace", "profile", "memory"] as FileSource[]).map((item) => (
          <button
            type="button"
            role="tab"
            aria-selected={source === item}
            key={item}
            className={`${styles.sourceTab} ${
              source === item ? styles.sourceTabActive : ""
            }`}
            data-source={item}
            onClick={() => setSource(item)}
          >
            {t(`files.${item}`)}
          </button>
        ))}
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
                  return (
                    <DirectoryNode
                      key={entry.path}
                      entry={entry}
                      chatId={chatId}
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
                        source: source === "memory" ? "memory" : "workspace",
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
