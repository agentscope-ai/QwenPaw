import { ArrowLeft, FileWarning, Files, GitBranch } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { buildAuthHeaders } from "../../api/authHeaders";
import { projectDirectoryApi } from "../../api/modules/projectDirectory";
import { getPendingProjectDirectory } from "../project-directory/pendingProjectDirectory";
import { loadSessionProjectDirs } from "../project-directory/loadSessionProjectDirs";
import { listenForProjectDirectoryChanges } from "../project-directory/projectDirectoryChangeEvent";
import { workspaceApi } from "../../api/modules/workspace";
import GitPanel from "../../pages/Coding/GitPanel";
import TabbedEditor from "../../pages/Coding/TabbedEditor";
import {
  useCodingTabsStore,
  useActiveTabPathForScope,
  useTabsForScope,
  type EditorTab,
  type PendingDiff,
} from "../../stores/codingTabsStore";
import { useCodingMode } from "../../stores/codingModeStore";
import { downloadFileFromUrl } from "../../utils/downloadFileFromUrl";
import FilesNavigator from "./FilesNavigator";
import MemoryGraphView from "./MemoryGraphView";
import MemoryTagsNavigator from "./MemoryTagsNavigator";
import { useMemoryFileConfig } from "./useMemoryTagSupport";
import { fileTabPath, fileTabTarget, findOpenFileTab } from "./fileIdentity";
import { projectRootPath, workspaceRoots } from "./directorySources";
import {
  filesWorkspaceScopeKey,
  type FilesWorkspaceScope,
} from "./filesWorkspaceScope";
import { toProjectRelativePath } from "./internalFileLinks";
import type {
  FileMetadata,
  FileTarget,
  MemoryGraphRoot,
  WorkspaceRoot,
} from "./types";
import styles from "./FilesWorkspace.module.less";

interface FilesWorkspaceProps {
  initialTarget?: FileTarget;
  initialMemoryTag?: string;
  scope: FilesWorkspaceScope;
}

function inferPreviewKind(
  path: string,
  contentType = "",
): FileMetadata["preview_kind"] {
  if (/\.(?:png|jpe?g|gif|webp|svg|ico|bmp)$/i.test(path)) return "image";
  if (/\.pdf$/i.test(path)) return "pdf";
  if (/\.csv$/i.test(path)) return "csv";
  if (
    contentType.startsWith("text/") ||
    /\.(?:md|mdx|txt|log|json|ya?ml|toml|xml|html?|css|less|scss|js|jsx|ts|tsx|py|java|go|rs|sh)$/i.test(
      path,
    ) ||
    !path.split("/").pop()?.includes(".")
  ) {
    return "text";
  }
  return "binary";
}

export default function FilesWorkspace({
  initialTarget,
  initialMemoryTag,
  scope,
}: FilesWorkspaceProps) {
  const { t } = useTranslation();
  const { codingMode } = useCodingMode();
  const scopeKey = filesWorkspaceScopeKey(scope);
  const chatId = scope.kind === "session" ? scope.chatId : undefined;
  // Primitives rather than `scope`: the object is rebuilt by the parent on
  // every render, and callbacks keyed on it feed effects that would then
  // refetch and re-activate the initial tab on unrelated re-renders.
  const scopeKind = scope.kind;
  const agentId = scope.agentId;
  const { config: memoryConfig, getConfig: getMemoryConfig } =
    useMemoryFileConfig(agentId);
  const memoryTagsSupported = memoryConfig !== null;
  const sessionId = scope.kind === "session" ? scope.sessionId : "";
  const projectDirOverride =
    scope.kind === "session" && !scope.chatId
      ? getPendingProjectDirectory(scope.agentId, scope.sessionId) ??
        scope.projectDirOverride ??
        undefined
      : undefined;
  const effectiveScope: FilesWorkspaceScope =
    scope.kind === "session" ? { ...scope, projectDirOverride } : scope;
  const tabs = useTabsForScope(scopeKey);
  const activeTabPath = useActiveTabPathForScope(scopeKey);
  const activeTab = tabs.find((tab) => tab.path === activeTabPath);
  const activeTarget = activeTab ? fileTabTarget(activeTab) : undefined;
  const {
    clearProjectTabs,
    closeTab,
    openTab,
    refreshTab,
    setActiveTab,
    setTabContent,
    setTabDirty,
    setTabEtag,
  } = useCodingTabsStore();
  const hydratedTabs = useRef(new Set<string>());
  const revalidatedScope = useRef("");
  const revalidationSequence = useRef(new Map<string, number>());
  const mountedRef = useRef(false);
  const scopeKeyRef = useRef(scopeKey);
  scopeKeyRef.current = scopeKey;
  const tabsRef = useRef(tabs);
  tabsRef.current = tabs;
  const targetsByTab = useRef(new Map<string, FileTarget>());
  const navigationSequence = useRef(0);
  const [loadError, setLoadError] = useState("");
  const [memoryGraphRoot, setMemoryGraphRoot] =
    useState<MemoryGraphRoot | null>(null);
  const [memoryTagsActive, setMemoryTagsActive] = useState(false);
  const [selectedMemoryTag, setSelectedMemoryTag] = useState<string | null>(
    null,
  );
  const [memoryTagsRevision, setMemoryTagsRevision] = useState(0);
  const [activity, setActivity] = useState<"files" | "git">("files");
  const [mobilePane, setMobilePane] = useState<
    "navigator" | "source" | "document"
  >(tabs.length > 0 ? "document" : "navigator");
  const [directoryRevision, setDirectoryRevision] = useState(0);
  const [editorNavigation, setEditorNavigation] = useState<{
    path: string;
    line: number;
    endLine: number;
    column?: number;
    sequence: number;
  } | null>(null);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(
    () =>
      listenForProjectDirectoryChanges((changedScopeKey) => {
        if (changedScopeKey === scopeKey) {
          clearProjectTabs(scopeKey);
          setDirectoryRevision((current) => current + 1);
        }
      }),
    [clearProjectTabs, scopeKey],
  );

  const resolveEditableTarget = useCallback(
    async (target: FileTarget): Promise<FileTarget> => {
      if (target.source !== "attachment" || !target.path) {
        return target;
      }
      try {
        const agentInfo = await projectDirectoryApi.get();
        const workspaceDirectory = agentInfo.workspace_dir ?? agentInfo.path;
        // An attachment can live under any directory the session is bound to,
        // so every one is a candidate — checking only the primary would leave
        // a file in an extra root stuck as a read-only historical artifact.
        const boundDirs =
          scopeKind === "session"
            ? (await loadSessionProjectDirs(agentId, sessionId, chatId)).dirs
            : [
                {
                  path: agentInfo.path,
                  label: null,
                  exists: true,
                  nested_with: null,
                },
              ];
        const directPath = toProjectRelativePath(target.path);
        const candidates: Array<{
          path: string;
          root: WorkspaceRoot;
        }> = [];
        const addCandidate = (path: string | null, root: WorkspaceRoot) => {
          if (
            path &&
            !candidates.some((item) => item.path === path && item.root === root)
          ) {
            candidates.push({ path, root });
          }
        };

        workspaceRoots(boundDirs).forEach((root) => {
          const directory =
            root === "workspace"
              ? workspaceDirectory
              : projectRootPath(root) ?? boundDirs[0]?.path ?? "";
          addCandidate(
            directPath ?? toProjectRelativePath(target.path, directory),
            root,
          );
        });

        for (const candidate of candidates) {
          try {
            await workspaceApi.getFileMetadata(
              candidate.path,
              chatId,
              candidate.root,
              projectDirOverride,
            );
            return {
              ...target,
              source: "workspace",
              path: candidate.path,
              root: candidate.root,
            };
          } catch {
            // Try the next visible directory root.
          }
        }
      } catch {
        // Keep historical attachments read-only when directory lookup fails.
      }
      return target;
    },
    [agentId, chatId, projectDirOverride, scopeKind, sessionId],
  );

  const loadTarget = useCallback(
    async (target: FileTarget) => {
      if (target.source === "profile") {
        return {
          content: (await workspaceApi.loadFile(target.path, agentId)).content,
          previewKind: "text" as const,
          readOnly: false,
          etag: "",
        };
      }
      if (
        target.source === "memory" ||
        target.source === "daily" ||
        target.source === "digest"
      ) {
        const section =
          target.source === "daily" || target.source === "digest"
            ? target.source
            : undefined;
        return {
          content: (
            await (section
              ? workspaceApi.loadMemoryFile(target.path, section)
              : workspaceApi.loadDailyMemory(target.path))
          ).content,
          previewKind: "text" as const,
          readOnly: false,
          etag: "",
        };
      }
      if (target.source === "workspace") {
        const metadata = await workspaceApi.getFileMetadata(
          target.path,
          chatId,
          target.root,
          projectDirOverride,
        );
        const isText =
          metadata.preview_kind === "text" || metadata.preview_kind === "csv";
        const loaded = isText
          ? await workspaceApi.loadFileText(
              target.path,
              chatId,
              target.root,
              projectDirOverride,
            )
          : null;
        return {
          content: loaded?.content ?? "",
          previewKind: metadata.preview_kind,
          readOnly: !isText,
          etag: loaded?.etag ?? metadata.etag,
        };
      }
      if (!target.artifactUrl) {
        throw new Error(`Missing artifact URL for ${target.source}`);
      }
      const response = await fetch(target.artifactUrl, {
        headers: buildAuthHeaders(),
      });
      if (!response.ok) throw new Error(`${response.status}`);
      const previewKind = inferPreviewKind(
        target.path,
        response.headers.get("Content-Type") ?? "",
      );
      return {
        content:
          previewKind === "text" || previewKind === "csv"
            ? await response.text()
            : "",
        previewKind,
        readOnly: true,
        etag: response.headers.get("ETag") ?? "",
      };
    },
    [agentId, chatId, projectDirOverride],
  );

  const loadTab = useCallback(
    async (tabPath: string) => {
      const tab = tabsRef.current.find((item) => item.path === tabPath);
      const target =
        targetsByTab.current.get(tabPath) ??
        fileTabTarget(tab ?? { path: tabPath, content: "", dirty: false });
      return loadTarget(target);
    },
    [loadTarget],
  );

  const getLiveTab = useCallback(
    (tabPath: string) =>
      useCodingTabsStore
        .getState()
        .tabsByAgent[scopeKey]?.find((item) => item.path === tabPath),
    [scopeKey],
  );

  const isTabSnapshotCurrent = useCallback(
    (
      tabPath: string,
      snapshot: EditorTab | undefined,
      diffSnapshot: PendingDiff | undefined,
    ) => {
      if (!mountedRef.current || !snapshot) return false;
      const currentTab = getLiveTab(tabPath);
      const currentDiff =
        useCodingTabsStore.getState().diffsByAgent[scopeKey]?.[tabPath];
      // Diffs can change independently, including individual hunk decisions.
      return (
        scopeKeyRef.current === scopeKey &&
        currentTab === snapshot &&
        !currentTab.dirty &&
        currentDiff === diffSnapshot
      );
    },
    [getLiveTab, scopeKey],
  );

  const loadTabContent = useCallback(
    async (tabPath: string) => {
      const snapshot = getLiveTab(tabPath);
      const diffSnapshot =
        useCodingTabsStore.getState().diffsByAgent[scopeKey]?.[tabPath];
      const loaded = await loadTab(tabPath);
      if (!isTabSnapshotCurrent(tabPath, snapshot, diffSnapshot)) {
        throw new Error("File state changed while loading");
      }
      refreshTab(scopeKey, tabPath, loaded.content, loaded.etag);
      return loaded.content;
    },
    [getLiveTab, isTabSnapshotCurrent, loadTab, refreshTab, scopeKey],
  );

  const revalidateTab = useCallback(
    async (tabPath: string) => {
      const tab = getLiveTab(tabPath);
      const diffSnapshot =
        useCodingTabsStore.getState().diffsByAgent[scopeKey]?.[tabPath];
      const previewKind =
        tab?.previewKind ??
        inferPreviewKind(tab?.displayPath ?? tab?.path ?? tabPath);
      if (
        !tab ||
        tab.dirty ||
        (previewKind !== "text" && previewKind !== "csv")
      ) {
        return;
      }

      const sequence = (revalidationSequence.current.get(tabPath) ?? 0) + 1;
      revalidationSequence.current.set(tabPath, sequence);
      try {
        const loaded = await loadTab(tabPath);
        if (
          scopeKeyRef.current !== scopeKey ||
          revalidationSequence.current.get(tabPath) !== sequence ||
          !isTabSnapshotCurrent(tabPath, tab, diffSnapshot)
        ) {
          return;
        }
        refreshTab(scopeKey, tabPath, loaded.content, loaded.etag);
      } catch {
        if (
          mountedRef.current &&
          scopeKeyRef.current === scopeKey &&
          revalidationSequence.current.get(tabPath) === sequence &&
          isTabSnapshotCurrent(tabPath, tab, diffSnapshot)
        ) {
          setLoadError(t("files.loadFailed"));
        }
      }
    },
    [getLiveTab, isTabSnapshotCurrent, loadTab, refreshTab, scopeKey, t],
  );

  const activateTab = useCallback(
    (tabPath: string) => {
      revalidatedScope.current = scopeKey;
      setLoadError("");
      setActiveTab(scopeKey, tabPath);
      setMobilePane("document");
      void revalidateTab(tabPath);
    },
    [revalidateTab, scopeKey, setActiveTab],
  );

  const openTarget = useCallback(
    async (target: FileTarget) => {
      try {
        const resolvedTarget = await resolveEditableTarget(target);
        const canAlias =
          resolvedTarget.source === "daily" ||
          resolvedTarget.source === "digest" ||
          resolvedTarget.source === "memory" ||
          (resolvedTarget.source === "workspace" &&
            resolvedTarget.root === "workspace");
        let memory = null;
        try {
          memory =
            canAlias && tabsRef.current.length ? await getMemoryConfig() : null;
        } catch (error) {
          // Exact identities remain usable offline. Without one, retry later
          // rather than opening a second buffer for a potentially dirty alias.
          if (!findOpenFileTab(tabsRef.current, resolvedTarget, null))
            throw error;
        }
        if (scopeKeyRef.current !== scopeKey) return;
        const existing = findOpenFileTab(
          tabsRef.current,
          resolvedTarget,
          memory,
        );
        const tabPath = existing?.path ?? fileTabPath(resolvedTarget);
        if (resolvedTarget.line) {
          navigationSequence.current += 1;
          setEditorNavigation({
            path: tabPath,
            line: resolvedTarget.line,
            endLine: resolvedTarget.endLine ?? resolvedTarget.line,
            column: resolvedTarget.column,
            sequence: navigationSequence.current,
          });
        }
        if (existing) {
          activateTab(tabPath);
          return;
        }
        targetsByTab.current.set(tabPath, resolvedTarget);
        const loaded = await loadTarget(resolvedTarget);
        if (scopeKeyRef.current !== scopeKey) return;
        setLoadError("");
        openTab(scopeKey, {
          path: tabPath,
          displayPath: resolvedTarget.path,
          content: loaded.content,
          dirty: false,
          source: resolvedTarget.source,
          workspaceRoot: resolvedTarget.root,
          artifactUrl: resolvedTarget.artifactUrl,
          previewKind: loaded.previewKind,
          readOnly: loaded.readOnly,
          etag: loaded.etag,
        });
        revalidatedScope.current = scopeKey;
        setActiveTab(scopeKey, tabPath);
        setMobilePane("document");
      } catch (error) {
        if (
          scopeKeyRef.current === scopeKey &&
          !(error instanceof DOMException && error.name === "AbortError")
        ) {
          setLoadError(t("files.loadFailed"));
        }
      }
    },
    [
      activateTab,
      getMemoryConfig,
      loadTarget,
      openTab,
      resolveEditableTarget,
      scopeKey,
      setActiveTab,
      t,
    ],
  );

  useEffect(() => {
    hydratedTabs.current.clear();
    revalidationSequence.current.clear();
    setMemoryTagsActive(false);
    setSelectedMemoryTag(null);
  }, [scopeKey]);

  const showMemoryTag = useCallback((tag: string) => {
    setActivity("files");
    setMemoryTagsActive(true);
    setSelectedMemoryTag(tag);
    setMobilePane("navigator");
  }, []);

  useEffect(() => {
    if (!chatId && projectDirOverride) {
      setActivity("files");
    }
  }, [chatId, projectDirOverride]);

  useEffect(() => {
    tabs.forEach((tab) => {
      if (tab.content || tab.dirty || hydratedTabs.current.has(tab.path)) {
        return;
      }
      hydratedTabs.current.add(tab.path);
      const diffSnapshot =
        useCodingTabsStore.getState().diffsByAgent[scopeKey]?.[tab.path];
      void loadTab(tab.path)
        .then((loaded) => {
          if (!isTabSnapshotCurrent(tab.path, tab, diffSnapshot)) return;
          refreshTab(scopeKey, tab.path, loaded.content, loaded.etag);
        })
        .catch(() => {
          if (!isTabSnapshotCurrent(tab.path, tab, diffSnapshot)) return;
          closeTab(scopeKey, tab.path);
          setLoadError(t("files.loadFailed"));
        });
    });
  }, [closeTab, isTabSnapshotCurrent, loadTab, refreshTab, scopeKey, t, tabs]);

  useEffect(() => {
    let cancelled = false;
    if (initialTarget) {
      void openTarget(initialTarget).then(() => {
        if (!cancelled && initialMemoryTag) setMobilePane("navigator");
      });
    }
    return () => {
      cancelled = true;
    };
  }, [initialTarget, initialMemoryTag, openTarget]);

  useEffect(() => {
    if (initialMemoryTag && memoryTagsSupported)
      showMemoryTag(initialMemoryTag);
  }, [initialMemoryTag, memoryTagsSupported, scopeKey, showMemoryTag]);

  useEffect(() => {
    if (!activeTabPath || revalidatedScope.current === scopeKey) return;
    revalidatedScope.current = scopeKey;
    const activeTab = tabsRef.current.find((tab) => tab.path === activeTabPath);
    // Empty restored tabs are already handled by the hydration effect above.
    if (activeTab?.content) void revalidateTab(activeTabPath);
  }, [activeTabPath, revalidateTab, scopeKey]);

  useEffect(() => {
    if (tabs.length === 0 && !memoryGraphRoot) {
      setMobilePane(activity === "git" && codingMode ? "source" : "navigator");
    }
  }, [activity, codingMode, memoryGraphRoot, tabs.length]);

  const handleClose = (path: string) => {
    const index = tabs.findIndex((tab) => tab.path === path);
    closeTab(scopeKey, path);
    if (tabs.length === 1 && !memoryGraphRoot) {
      setMobilePane(activity === "git" && codingMode ? "source" : "navigator");
    }
    if (activeTabPath === path) {
      const nextPath = tabs[index + 1]?.path ?? tabs[index - 1]?.path ?? "";
      if (nextPath) activateTab(nextPath);
      else setActiveTab(scopeKey, "");
    }
  };

  const handleCloseOthers = (path: string) => {
    tabs.forEach((tab) => {
      if (tab.path !== path) closeTab(scopeKey, tab.path);
    });
    activateTab(path);
  };

  const hasDocument = tabs.length > 0 || memoryGraphRoot !== null;

  return (
    <div className={styles.workspace} data-mobile-pane={mobilePane}>
      {codingMode && (
        <nav className={styles.activityRail} aria-label={t("files.workspace")}>
          <button
            type="button"
            className={activity === "files" ? styles.activityActive : ""}
            aria-label={t("files.navigator")}
            onClick={() => {
              setActivity("files");
              setMobilePane("navigator");
            }}
          >
            <Files size={18} />
          </button>
          {chatId || !projectDirOverride ? (
            <button
              type="button"
              className={activity === "git" ? styles.activityActive : ""}
              aria-label={t("files.sourceControl")}
              onClick={() => {
                setActivity("git");
                setMobilePane("source");
              }}
            >
              <GitBranch size={18} />
            </button>
          ) : null}
        </nav>
      )}
      {activity === "files" || !codingMode ? (
        <div className={styles.navigatorPane}>
          {hasDocument && (
            <button
              type="button"
              className={styles.mobilePaneSwitch}
              aria-label={t("files.openFilesLabel")}
              onClick={() => setMobilePane("document")}
            >
              <Files size={16} />
              <span>{t("files.openFilesLabel")}</span>
            </button>
          )}
          <FilesNavigator
            key={`${scopeKey}:${projectDirOverride ?? ""}:${directoryRevision}`}
            scope={effectiveScope}
            selectedPath={activeTab?.displayPath ?? activeTabPath}
            onSelect={(target) => {
              setMemoryGraphRoot(null);
              void openTarget(target);
            }}
            activeMemoryGraphRoot={memoryGraphRoot}
            onShowMemoryGraph={(root) => {
              setMemoryGraphRoot(root);
              setMobilePane("document");
            }}
            onShowFiles={() => {
              setMemoryTagsActive(false);
              setMemoryGraphRoot(null);
            }}
            memoryTagsActive={memoryTagsSupported && memoryTagsActive}
            onShowMemoryTags={() => setMemoryTagsActive(true)}
            memoryTagsPanel={
              memoryTagsSupported ? (
                <MemoryTagsNavigator
                  key={`${scopeKey}:${selectedMemoryTag ?? ""}`}
                  agentId={agentId}
                  tag={selectedMemoryTag}
                  revision={memoryTagsRevision}
                  memoryConfig={memoryConfig}
                  selectedPath={activeTarget?.path ?? ""}
                  selectedSource={activeTarget?.source}
                  selectedRoot={activeTarget?.root}
                  onSelectTag={setSelectedMemoryTag}
                  onOpenFile={(target) => {
                    setMemoryGraphRoot(null);
                    void openTarget(target);
                  }}
                />
              ) : undefined
            }
          />
        </div>
      ) : (
        <aside className={styles.sourcePanel}>
          {hasDocument && (
            <button
              type="button"
              className={styles.mobilePaneSwitch}
              aria-label={t("files.openFilesLabel")}
              onClick={() => setMobilePane("document")}
            >
              <ArrowLeft size={16} />
              <span>{t("files.openFilesLabel")}</span>
            </button>
          )}
          <header>
            <GitBranch size={15} />
            <span>{t("files.sourceControl")}</span>
          </header>
          <GitPanel chatId={chatId} />
        </aside>
      )}
      <main className={styles.documentSurface}>
        <button
          type="button"
          className={styles.mobilePaneSwitch}
          aria-label={t(
            activity === "git" ? "files.sourceControl" : "files.navigator",
          )}
          onClick={() =>
            setMobilePane(activity === "git" ? "source" : "navigator")
          }
        >
          {activity === "git" ? <GitBranch size={16} /> : <Files size={16} />}
          <span>
            {t(activity === "git" ? "files.sourceControl" : "files.navigator")}
          </span>
        </button>
        {loadError && (
          <div className={styles.loadError} role="alert">
            <FileWarning size={24} />
            <span>{loadError}</span>
          </div>
        )}
        {memoryGraphRoot ? (
          <MemoryGraphView
            agentId={scope.agentId}
            root={memoryGraphRoot}
            onOpenFile={(source, path) => {
              setMemoryGraphRoot(null);
              void openTarget({ source, path });
            }}
          />
        ) : (
          <TabbedEditor
            key={`${scopeKey}:${directoryRevision}`}
            tabs={tabs}
            activeTabPath={activeTabPath}
            scopeKey={scopeKey}
            onTabSelect={activateTab}
            onTabClose={handleClose}
            onCloseOtherTabs={handleCloseOthers}
            onTabDirtyChange={(path, dirty) =>
              setTabDirty(scopeKey, path, dirty)
            }
            onTabContentChange={(path, content) =>
              setTabContent(scopeKey, path, content)
            }
            onLoadFile={loadTabContent}
            chatId={chatId}
            projectDirOverride={projectDirOverride}
            navigation={editorNavigation}
            onMemoryTagClick={memoryTagsSupported ? showMemoryTag : undefined}
            onFileSaved={() => setMemoryTagsRevision((value) => value + 1)}
            onDownloadFile={async (path) => {
              const tab = tabsRef.current.find((item) => item.path === path);
              const target = fileTabTarget(
                tab ?? { path, content: "", dirty: false },
              );
              const sourcePath = target.path;
              const filename = sourcePath.split("/").pop() ?? sourcePath;
              if (tab?.artifactUrl) {
                await downloadFileFromUrl(tab.artifactUrl, filename, {
                  headers: buildAuthHeaders(),
                  errorMessage: t("files.downloadFailed"),
                });
                return;
              }
              if (target.source === "workspace") {
                await downloadFileFromUrl(
                  workspaceApi.getFileDownloadUrl(sourcePath, target.root),
                  filename,
                  {
                    headers: {
                      ...buildAuthHeaders(),
                      ...(chatId ? { "X-Chat-Id": chatId } : {}),
                      ...(!chatId && projectDirOverride
                        ? {
                            "X-Session-Project-Dir": projectDirOverride,
                          }
                        : {}),
                    },
                    errorMessage: t("files.downloadFailed"),
                  },
                );
                return;
              }
              const blob = new Blob([tab?.content ?? ""], {
                type: "text/plain;charset=utf-8",
              });
              const url = URL.createObjectURL(blob);
              const anchor = document.createElement("a");
              anchor.href = url;
              anchor.download = filename;
              anchor.click();
              URL.revokeObjectURL(url);
            }}
            onSaveFile={async (path, content) => {
              const tab = tabsRef.current.find((item) => item.path === path);
              const target = fileTabTarget(
                tab ?? { path, content, dirty: true },
              );
              if (target.source === "workspace") {
                const saved = await workspaceApi.saveFileContent(
                  target.path,
                  content,
                  tab?.etag,
                  chatId,
                  target.root,
                  projectDirOverride,
                );
                setTabEtag(scopeKey, path, saved.etag);
                return;
              }
              const { source, path: sourcePath } = target;
              if (source === "profile") {
                await workspaceApi.saveFile(sourcePath, content, agentId);
              } else if (source === "daily" || source === "digest") {
                await workspaceApi.saveMemoryFile(sourcePath, content, source);
              } else if (source === "memory") {
                await workspaceApi.saveDailyMemory(sourcePath, content);
              }
            }}
          />
        )}
      </main>
    </div>
  );
}
