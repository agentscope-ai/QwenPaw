import { Dropdown } from "antd";
import { FileCode2, FolderTree, GitCompareArrows, Plus, X } from "lucide-react";
import { lazy, Suspense, useCallback, useLayoutEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  type EditorTab,
  useActiveTabPathForScope,
  useCodingTabsStore,
  useDiffsForScope,
  useTabsForScope,
} from "../../stores/codingTabsStore";
import { useCodingMode } from "../../stores/codingModeStore";
import type { FilesWorkspaceScope } from "../files-workspace/filesWorkspaceScope";
import { filesWorkspaceScopeKey } from "../files-workspace/filesWorkspaceScope";
import type { FileTarget } from "../files-workspace/types";
import {
  getWorkbenchCapability,
  WORKBENCH_CAPABILITIES,
} from "./workbenchCapabilities";
import {
  isWorkbenchFileTabId,
  readStoredWorkbenchLayout,
  storeWorkbenchLayout,
  type WorkbenchCapabilityId,
  type WorkbenchLayout,
  workbenchFilePath,
  workbenchFileTabId,
  workbenchLayoutStorageKey,
} from "./workbenchPreferences";
import styles from "./WorkbenchShell.module.less";

const FilesWorkspace = lazy(() => import("../files-workspace/FilesWorkspace"));
const GitPanel = lazy(() => import("../../pages/Coding/GitPanel"));

interface WorkbenchShellProps {
  initialTarget?: FileTarget;
  scope: Extract<FilesWorkspaceScope, { kind: "session" }>;
  onClose: () => void;
}

function fileLabel(tab: EditorTab): string {
  const path = (tab.displayPath ?? tab.path).replace(/\\/g, "/");
  return path.split("/").filter(Boolean).pop() ?? path;
}

function withFilesTarget(
  layout: WorkbenchLayout,
  target?: FileTarget,
): WorkbenchLayout {
  if (!target) return layout;
  return {
    ...layout,
    openTabs: layout.openTabs.includes("files")
      ? layout.openTabs
      : [...layout.openTabs, "files"],
    activeTab: "files",
  };
}

export default function WorkbenchShell({
  initialTarget,
  scope,
  onClose,
}: WorkbenchShellProps) {
  const { t } = useTranslation();
  const { codingMode } = useCodingMode();
  const scopeKey = filesWorkspaceScopeKey(scope);
  const fileTabs = useTabsForScope(scopeKey);
  const activeFilePath = useActiveTabPathForScope(scopeKey);
  const pendingDiffs = useDiffsForScope(scopeKey);
  const { closeTab, setActiveTab: setActiveFile } = useCodingTabsStore();
  const storageKey = workbenchLayoutStorageKey(scope.agentId, scope.sessionId);
  const changesAvailable =
    codingMode && Boolean(scope.chatId || !scope.projectDirOverride);
  const [layout, setLayout] = useState<WorkbenchLayout>(() =>
    withFilesTarget(readStoredWorkbenchLayout(storageKey), initialTarget),
  );

  const persistLayout = useCallback(
    (next: WorkbenchLayout) => {
      setLayout(next);
      storeWorkbenchLayout(storageKey, next);
    },
    [storageKey],
  );

  useLayoutEffect(() => {
    const stored = readStoredWorkbenchLayout(storageKey);
    const availableTabs = stored.openTabs.filter(
      (id) => id !== "changes" || changesAvailable,
    );
    if (fileTabs.length > 0 && !availableTabs.includes("files")) {
      availableTabs.push("files");
    }

    const storedFilePath = isWorkbenchFileTabId(stored.activeTab)
      ? workbenchFilePath(stored.activeTab)
      : null;
    const storedFileAvailable =
      storedFilePath !== null &&
      fileTabs.some((tab) => tab.path === storedFilePath);
    const fallbackFilePath =
      fileTabs.find((tab) => tab.path === activeFilePath)?.path ??
      fileTabs[0]?.path;
    const fallbackCapability =
      availableTabs.find((id) => id !== "files") ??
      (availableTabs.includes("files") ? "files" : null);
    const activeTab = storedFileAvailable
      ? stored.activeTab
      : stored.activeTab &&
        !isWorkbenchFileTabId(stored.activeTab) &&
        availableTabs.includes(stored.activeTab)
      ? stored.activeTab
      : fallbackFilePath
      ? workbenchFileTabId(fallbackFilePath)
      : fallbackCapability;
    if (isWorkbenchFileTabId(activeTab)) {
      setActiveFile(scopeKey, workbenchFilePath(activeTab));
    }

    const sanitized = withFilesTarget(
      {
        openTabs: availableTabs,
        activeTab,
        fileTreeOpen: stored.fileTreeOpen,
      },
      initialTarget,
    );
    setLayout(sanitized);
    if (JSON.stringify(sanitized) !== JSON.stringify(stored)) {
      storeWorkbenchLayout(storageKey, sanitized);
    }
  }, [
    activeFilePath,
    changesAvailable,
    fileTabs,
    initialTarget,
    scopeKey,
    setActiveFile,
    storageKey,
  ]);

  const openCapability = useCallback(
    (id: WorkbenchCapabilityId) => {
      if (id === "changes" && !changesAvailable) return;
      const openTabs = layout.openTabs.includes(id)
        ? layout.openTabs
        : [...layout.openTabs, id];
      if (id === "files") {
        const path =
          fileTabs.find((tab) => tab.path === activeFilePath)?.path ??
          fileTabs[0]?.path;
        persistLayout({
          openTabs,
          activeTab: path ? workbenchFileTabId(path) : "files",
          fileTreeOpen: true,
        });
        if (path) setActiveFile(scopeKey, path);
        return;
      }
      persistLayout({ ...layout, openTabs, activeTab: id });
    },
    [
      activeFilePath,
      changesAvailable,
      fileTabs,
      layout,
      persistLayout,
      scopeKey,
      setActiveFile,
    ],
  );

  const closeCapability = useCallback(
    (id: WorkbenchCapabilityId) => {
      const index = layout.openTabs.indexOf(id);
      const openTabs = layout.openTabs.filter((tab) => tab !== id);
      const activeTab =
        layout.activeTab === id
          ? openTabs[Math.min(index, openTabs.length - 1)] ?? null
          : layout.activeTab;
      persistLayout({ ...layout, openTabs, activeTab });
    },
    [layout, persistLayout],
  );

  const activateFile = useCallback(
    (path: string) => {
      setActiveFile(scopeKey, path);
      persistLayout({
        ...layout,
        openTabs: layout.openTabs.includes("files")
          ? layout.openTabs
          : [...layout.openTabs, "files"],
        activeTab: workbenchFileTabId(path),
      });
    },
    [layout, persistLayout, scopeKey, setActiveFile],
  );

  const closeFile = useCallback(
    (path: string) => {
      const index = fileTabs.findIndex((tab) => tab.path === path);
      const remaining = fileTabs.filter((tab) => tab.path !== path);
      closeTab(scopeKey, path);
      if (layout.activeTab !== workbenchFileTabId(path)) return;
      const nextPath =
        remaining[Math.min(index, remaining.length - 1)]?.path ?? null;
      const nextCapability =
        layout.openTabs.find((id) => id !== "files") ?? "files";
      if (nextPath) setActiveFile(scopeKey, nextPath);
      persistLayout({
        ...layout,
        activeTab: nextPath ? workbenchFileTabId(nextPath) : nextCapability,
      });
    },
    [closeTab, fileTabs, layout, persistLayout, scopeKey, setActiveFile],
  );

  const toggleFileTree = useCallback(() => {
    const visible =
      layout.fileTreeOpen &&
      (layout.activeTab === "files" || isWorkbenchFileTabId(layout.activeTab));
    if (visible) {
      persistLayout({ ...layout, fileTreeOpen: false });
      return;
    }
    const path =
      fileTabs.find((tab) => tab.path === activeFilePath)?.path ??
      fileTabs[0]?.path;
    if (path) setActiveFile(scopeKey, path);
    persistLayout({
      ...layout,
      openTabs: layout.openTabs.includes("files")
        ? layout.openTabs
        : [...layout.openTabs, "files"],
      activeTab: path ? workbenchFileTabId(path) : "files",
      fileTreeOpen: true,
    });
  }, [
    activeFilePath,
    fileTabs,
    layout,
    persistLayout,
    scopeKey,
    setActiveFile,
  ]);

  const menuItems = WORKBENCH_CAPABILITIES.map((capability) => {
    const Icon = capability.icon;
    const disabled = capability.id === "changes" && !changesAvailable;
    return {
      key: capability.id,
      icon: <Icon size={16} />,
      label: t(capability.labelKey),
      disabled,
      title: disabled
        ? codingMode
          ? t("workbench.sessionRequired")
          : t("workbench.codingModeRequired")
        : undefined,
    };
  });

  const addMenu = {
    items: menuItems,
    onClick: ({ key }: { key: string }) =>
      openCapability(key as WorkbenchCapabilityId),
  };
  const fileResourceActive = isWorkbenchFileTabId(layout.activeTab);
  const filesSurfaceActive = fileResourceActive || layout.activeTab === "files";

  return (
    <div className={styles.shell}>
      <header className={styles.header}>
        <nav className={styles.tabs} aria-label={t("workbench.navigation")}>
          {layout.openTabs.map((id) => {
            if (id === "files") {
              return fileTabs.map((tab) => {
                const resourceId = workbenchFileTabId(tab.path);
                const active = layout.activeTab === resourceId;
                const hasDiff = Boolean(pendingDiffs[tab.path]);
                const label = fileLabel(tab);
                return (
                  <div
                    key={resourceId}
                    className={`${styles.tab} ${styles.fileTab} ${
                      active ? styles.activeTab : ""
                    }`}
                    title={tab.displayPath ?? tab.path}
                  >
                    <button
                      type="button"
                      className={styles.tabSelect}
                      aria-current={active ? "page" : undefined}
                      onClick={() => activateFile(tab.path)}
                    >
                      {hasDiff ? (
                        <GitCompareArrows size={14} />
                      ) : (
                        <FileCode2 size={14} />
                      )}
                      <span>{label}</span>
                      {tab.dirty && <i className={styles.dirtyDot} />}
                    </button>
                    <button
                      type="button"
                      className={styles.tabClose}
                      aria-label={`${t("files.closeTab")}: ${label}`}
                      onClick={() => closeFile(tab.path)}
                    >
                      <X size={13} />
                    </button>
                  </div>
                );
              });
            }
            const capability = getWorkbenchCapability(id);
            const Icon = capability.icon;
            const label = t(capability.labelKey);
            return (
              <div
                key={id}
                className={`${styles.tab} ${
                  layout.activeTab === id ? styles.activeTab : ""
                }`}
              >
                <button
                  type="button"
                  className={styles.tabSelect}
                  aria-current={layout.activeTab === id ? "page" : undefined}
                  onClick={() => openCapability(id)}
                >
                  <Icon size={15} />
                  <span>{label}</span>
                </button>
                <button
                  type="button"
                  className={styles.tabClose}
                  aria-label={t("workbench.closePanel", { name: label })}
                  onClick={() => closeCapability(id)}
                >
                  <X size={13} />
                </button>
              </div>
            );
          })}
          <Dropdown menu={addMenu} trigger={["click"]} placement="bottomLeft">
            <button
              type="button"
              className={styles.addButton}
              aria-label={t("workbench.addPanel")}
            >
              <Plus size={18} />
            </button>
          </Dropdown>
        </nav>
        {!filesSurfaceActive && (
          <button
            type="button"
            className={styles.headerFileTreeButton}
            aria-label={t("files.navigator")}
            aria-pressed={false}
            onClick={toggleFileTree}
          >
            <FolderTree size={17} />
          </button>
        )}
        <button
          type="button"
          className={styles.closeButton}
          aria-label={t("common.close")}
          onClick={onClose}
        >
          <X size={17} />
        </button>
      </header>

      <main className={styles.content}>
        {layout.activeTab ? (
          <Suspense
            fallback={<div className={styles.empty}>{t("common.loading")}</div>}
          >
            {filesSurfaceActive ? (
              <FilesWorkspace
                initialTarget={initialTarget}
                scope={scope}
                embedded
                navigatorOpen={layout.fileTreeOpen}
                navigatorPosition="right"
                onFileActivated={activateFile}
                showBreadcrumbs
                showEditorTabs={false}
                toolbarTrailing={
                  <button
                    type="button"
                    className={`${styles.fileTreeButton} ${
                      layout.fileTreeOpen ? styles.fileTreeButtonActive : ""
                    }`}
                    aria-label={t("files.navigator")}
                    aria-pressed={layout.fileTreeOpen}
                    onClick={toggleFileTree}
                  >
                    <FolderTree size={15} />
                  </button>
                }
                workspaceOnly
              />
            ) : layout.activeTab === "changes" ? (
              <GitPanel chatId={scope.chatId} />
            ) : (
              <div className={styles.empty}>
                {t("workbench.phasePlaceholder")}
              </div>
            )}
          </Suspense>
        ) : (
          <div className={styles.emptyState}>
            <span>{t("workbench.emptyDescription")}</span>
            <Dropdown menu={addMenu} trigger={["click"]} placement="bottom">
              <button type="button" className={styles.emptyAddButton}>
                <Plus size={16} />
                {t("workbench.addPanel")}
              </button>
            </Dropdown>
          </div>
        )}
      </main>
    </div>
  );
}
