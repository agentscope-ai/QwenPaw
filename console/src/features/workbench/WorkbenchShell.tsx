import { Dropdown } from "antd";
import { lazy, Suspense, useCallback, useLayoutEffect, useState } from "react";
import { Plus, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useCodingMode } from "../../stores/codingModeStore";
import type { FilesWorkspaceScope } from "../files-workspace/filesWorkspaceScope";
import type { FileTarget } from "../files-workspace/types";
import {
  getWorkbenchCapability,
  WORKBENCH_CAPABILITIES,
} from "./workbenchCapabilities";
import {
  readStoredWorkbenchLayout,
  storeWorkbenchLayout,
  type WorkbenchCapabilityId,
  type WorkbenchLayout,
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

function withFilesTarget(
  layout: WorkbenchLayout,
  target?: FileTarget,
): WorkbenchLayout {
  if (!target) return layout;
  return {
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
    const sanitized = {
      openTabs: availableTabs,
      activeTab:
        stored.activeTab && availableTabs.includes(stored.activeTab)
          ? stored.activeTab
          : availableTabs[0] ?? null,
    } satisfies WorkbenchLayout;
    const next = withFilesTarget(sanitized, initialTarget);
    setLayout(next);
    if (
      next.activeTab !== stored.activeTab ||
      next.openTabs.length !== stored.openTabs.length ||
      next.openTabs.some((id, index) => id !== stored.openTabs[index])
    ) {
      storeWorkbenchLayout(storageKey, next);
    }
  }, [changesAvailable, initialTarget, storageKey]);

  const openCapability = useCallback(
    (id: WorkbenchCapabilityId) => {
      if (id === "changes" && !changesAvailable) return;
      persistLayout({
        openTabs: layout.openTabs.includes(id)
          ? layout.openTabs
          : [...layout.openTabs, id],
        activeTab: id,
      });
    },
    [changesAvailable, layout.openTabs, persistLayout],
  );

  const closeCapability = useCallback(
    (id: WorkbenchCapabilityId) => {
      const index = layout.openTabs.indexOf(id);
      const openTabs = layout.openTabs.filter((tab) => tab !== id);
      const activeTab =
        layout.activeTab === id
          ? openTabs[Math.min(index, openTabs.length - 1)] ?? null
          : layout.activeTab;
      persistLayout({ openTabs, activeTab });
    },
    [layout, persistLayout],
  );

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

  return (
    <div className={styles.shell}>
      <header className={styles.header}>
        <nav className={styles.tabs} aria-label={t("workbench.navigation")}>
          {layout.openTabs.map((id) => {
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
            {layout.activeTab === "files" ? (
              <FilesWorkspace
                initialTarget={initialTarget}
                scope={scope}
                embedded
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
