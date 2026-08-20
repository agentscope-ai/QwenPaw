import { FileWarning, Files, GitBranch } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { buildAuthHeaders } from "../../api/authHeaders";
import { chatProjectDirectoryApi } from "../../api/modules/chatProjectDirectory";
import { projectDirectoryApi } from "../../api/modules/projectDirectory";
import { getPendingProjectDirectory } from "../project-directory/pendingProjectDirectory";
import { listenForProjectDirectoryChanges } from "../project-directory/projectDirectoryChangeEvent";
import { workspaceApi } from "../../api/modules/workspace";
import GitPanel from "../../pages/Coding/GitPanel";
import TabbedEditor from "../../pages/Coding/TabbedEditor";
import {
  useCodingTabsStore,
  useActiveTabPathForScope,
  useTabsForScope,
} from "../../stores/codingTabsStore";
import { useCodingMode } from "../../stores/codingModeStore";
import { downloadFileFromUrl } from "../../utils/downloadFileFromUrl";
import FilesNavigator from "./FilesNavigator";
import MemoryGraphView from "./MemoryGraphView";
import { directoriesMatch } from "./directorySources";
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
  scope,
}: FilesWorkspaceProps) {
  const { t } = useTranslation();
  const { codingMode } = useCodingMode();
  const scopeKey = filesWorkspaceScopeKey(scope);
  const chatId = scope.kind === "session" ? scope.chatId : undefined;
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
  const {
    clearProjectTabs,
    closeTab,
    openTab,
    setActiveTab,
    setTabContent,
    setTabDirty,
    setTabEtag,
  } = useCodingTabsStore();
  const hydratedTabs = useRef(new Set<string>());
  const tabsRef = useRef(tabs);
  tabsRef.current = tabs;
  const targetsByTab = useRef(new Map<string, FileTarget>());
  const navigationSequence = useRef(0);
  const [loadError, setLoadError] = useState("");
  const [memoryGraphRoot, setMemoryGraphRoot] =
    useState<MemoryGraphRoot | null>(null);
  const [activity, setActivity] = useState<"files" | "git">("files");
  const [directoryRevision, setDirectoryRevision] = useState(0);
  const [editorNavigation, setEditorNavigation] = useState<{
    path: string;
    line: number;
    endLine: number;
    column?: number;
    sequence: number;
  } | null>(null);

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
        const projectDirectory = chatId
          ? (await chatProjectDirectoryApi.get(chatId)).project_dir
          : agentInfo.path;
        const workspaceDirectory = agentInfo.workspace_dir ?? agentInfo.path;
        const directPath = toProjectRelativePath(target.path);
        const sameDirectory = directoriesMatch(
          projectDirectory,
          workspaceDirectory,
        );
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

        if (sameDirectory) {
          addCandidate(
            directPath ??
              toProjectRelativePath(target.path, workspaceDirectory),
            "workspace",
          );
        } else {
          addCandidate(
            directPath ?? toProjectRelativePath(target.path, projectDirectory),
            "project",
          );
          addCandidate(
            directPath ??
              toProjectRelativePath(target.path, workspaceDirectory),
            "workspace",
          );
        }

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
            // Try the other visible directory root.
          }
        }
      } catch {
        // Keep historical attachments read-only when directory lookup fails.
      }
      return target;
    },
    [chatId, projectDirOverride],
  );

  const loadTarget = useCallback(
    async (target: FileTarget) => {
      if (target.source === "profile") {
        return {
          content: (await workspaceApi.loadFile(target.path)).content,
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
    [chatId, projectDirOverride],
  );

  const loadTabContent = useCallback(
    async (tabPath: string) => {
      const tab = tabsRef.current.find((item) => item.path === tabPath);
      const separator = tabPath.indexOf("::");
      const target =
        targetsByTab.current.get(tabPath) ??
        ({
          source:
            tab?.source ??
            (separator < 0
              ? "workspace"
              : (tabPath.slice(0, separator) as FileTarget["source"])),
          path: separator < 0 ? tabPath : tabPath.slice(separator + 2),
          root: tab?.workspaceRoot,
          artifactUrl: tab?.artifactUrl,
        } satisfies FileTarget);
      const loaded = await loadTarget(target);
      setTabEtag(scopeKey, tabPath, loaded.etag);
      return loaded.content;
    },
    [loadTarget, scopeKey, setTabEtag],
  );

  const openTarget = useCallback(
    async (target: FileTarget) => {
      const resolvedTarget = await resolveEditableTarget(target);
      const tabPath =
        resolvedTarget.source === "workspace"
          ? resolvedTarget.root === "workspace"
            ? `workspace-root::${resolvedTarget.path}`
            : resolvedTarget.path
          : `${resolvedTarget.source}::${resolvedTarget.path}`;
      targetsByTab.current.set(tabPath, resolvedTarget);
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
      const existing = tabsRef.current.find((tab) => tab.path === tabPath);
      if (existing) {
        setLoadError("");
        setActiveTab(scopeKey, tabPath);
        return;
      }
      try {
        const loaded = await loadTarget(resolvedTarget);
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
        setActiveTab(scopeKey, tabPath);
      } catch {
        setLoadError(t("files.loadFailed"));
      }
    },
    [loadTarget, openTab, resolveEditableTarget, scopeKey, setActiveTab, t],
  );

  useEffect(() => {
    hydratedTabs.current.clear();
  }, [scopeKey]);

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
      void loadTabContent(tab.path)
        .then((content) => setTabContent(scopeKey, tab.path, content))
        .catch(() => {
          closeTab(scopeKey, tab.path);
          setLoadError(t("files.loadFailed"));
        });
    });
  }, [closeTab, loadTabContent, scopeKey, setTabContent, t, tabs]);

  useEffect(() => {
    if (initialTarget) void openTarget(initialTarget);
  }, [initialTarget, openTarget]);

  const handleClose = (path: string) => {
    const index = tabs.findIndex((tab) => tab.path === path);
    closeTab(scopeKey, path);
    if (activeTabPath === path) {
      setActiveTab(
        scopeKey,
        tabs[index + 1]?.path ?? tabs[index - 1]?.path ?? "",
      );
    }
  };

  const handleCloseOthers = (path: string) => {
    tabs.forEach((tab) => {
      if (tab.path !== path) closeTab(scopeKey, tab.path);
    });
    setActiveTab(scopeKey, path);
  };

  return (
    <div
      className={`${styles.workspace} ${
        tabs.length === 0 && !memoryGraphRoot ? styles.workspaceEmpty : ""
      }`}
    >
      {codingMode && (
        <nav className={styles.activityRail} aria-label={t("files.workspace")}>
          <button
            type="button"
            className={activity === "files" ? styles.activityActive : ""}
            aria-label={t("files.navigator")}
            onClick={() => setActivity("files")}
          >
            <Files size={18} />
          </button>
          {chatId || !projectDirOverride ? (
            <button
              type="button"
              className={activity === "git" ? styles.activityActive : ""}
              aria-label={t("files.sourceControl")}
              onClick={() => setActivity("git")}
            >
              <GitBranch size={18} />
            </button>
          ) : null}
        </nav>
      )}
      {activity === "files" || !codingMode ? (
        <FilesNavigator
          key={`${scopeKey}:${projectDirOverride ?? ""}:${directoryRevision}`}
          scope={effectiveScope}
          selectedPath={
            tabs.find((tab) => tab.path === activeTabPath)?.displayPath ??
            activeTabPath
          }
          onSelect={(target) => {
            setMemoryGraphRoot(null);
            void openTarget(target);
          }}
          activeMemoryGraphRoot={memoryGraphRoot}
          onShowMemoryGraph={(root) => setMemoryGraphRoot(root)}
          onShowFiles={() => setMemoryGraphRoot(null)}
        />
      ) : (
        <aside className={styles.sourcePanel}>
          <header>
            <GitBranch size={15} />
            <span>{t("files.sourceControl")}</span>
          </header>
          <GitPanel chatId={chatId} />
        </aside>
      )}
      <main className={styles.documentSurface}>
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
            onTabSelect={(path) => setActiveTab(scopeKey, path)}
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
            onDownloadFile={async (path) => {
              const tab = tabsRef.current.find((item) => item.path === path);
              const separator = path.indexOf("::");
              const sourcePath =
                tab?.displayPath ??
                (separator < 0 ? path : path.slice(separator + 2));
              const filename = sourcePath.split("/").pop() ?? sourcePath;
              if (tab?.artifactUrl) {
                await downloadFileFromUrl(tab.artifactUrl, filename, {
                  headers: buildAuthHeaders(),
                  errorMessage: t("files.downloadFailed"),
                });
                return;
              }
              if ((tab?.source ?? "workspace") === "workspace") {
                await downloadFileFromUrl(
                  workspaceApi.getFileDownloadUrl(
                    sourcePath,
                    tab?.workspaceRoot,
                  ),
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
              const separator = path.indexOf("::");
              if ((tab?.source ?? "workspace") === "workspace") {
                const saved = await workspaceApi.saveFileContent(
                  tab?.displayPath ?? path,
                  content,
                  tab?.etag,
                  chatId,
                  tab?.workspaceRoot,
                  projectDirOverride,
                );
                setTabEtag(scopeKey, path, saved.etag);
                return;
              }
              const source = path.slice(0, separator);
              const sourcePath = path.slice(separator + 2);
              if (source === "profile") {
                await workspaceApi.saveFile(sourcePath, content);
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
