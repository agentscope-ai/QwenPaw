import { Files, GitBranch, SquareTerminal, Wrench, X } from "lucide-react";
import { lazy, Suspense, useCallback, useLayoutEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useCodingMode } from "../../stores/codingModeStore";
import type { FilesWorkspaceScope } from "../files-workspace/filesWorkspaceScope";
import type { FileTarget } from "../files-workspace/types";
import styles from "./WorkbenchShell.module.less";
import {
  readStoredWorkbenchTab,
  type WorkbenchTab,
  workbenchTabStorageKey,
} from "./workbenchPreferences";

const FilesWorkspace = lazy(() => import("../files-workspace/FilesWorkspace"));
const GitPanel = lazy(() => import("../../pages/Coding/GitPanel"));

interface WorkbenchShellProps {
  initialTarget?: FileTarget;
  scope: Extract<FilesWorkspaceScope, { kind: "session" }>;
  onClose: () => void;
}

export default function WorkbenchShell({
  initialTarget,
  scope,
  onClose,
}: WorkbenchShellProps) {
  const { t } = useTranslation();
  const { codingMode } = useCodingMode();
  const storageKey = workbenchTabStorageKey(scope.agentId, scope.sessionId);
  const changesAvailable =
    codingMode && Boolean(scope.chatId || !scope.projectDirOverride);
  const [activeTab, setActiveTab] = useState<WorkbenchTab>(() => {
    const stored = readStoredWorkbenchTab(storageKey);
    return initialTarget || (!changesAvailable && stored === "changes")
      ? "files"
      : stored;
  });

  useLayoutEffect(() => {
    const stored = readStoredWorkbenchTab(storageKey);
    if (!changesAvailable && stored === "changes") {
      localStorage.setItem(storageKey, "files");
    }
    setActiveTab(
      initialTarget || (!changesAvailable && stored === "changes")
        ? "files"
        : stored,
    );
  }, [changesAvailable, initialTarget, storageKey]);

  const selectTab = useCallback(
    (tab: WorkbenchTab) => {
      setActiveTab(tab);
      localStorage.setItem(storageKey, tab);
    },
    [storageKey],
  );

  const tabs = [
    { id: "files" as const, label: t("workbench.files"), icon: Files },
    {
      id: "changes" as const,
      label: t("workbench.changes"),
      icon: GitBranch,
      disabled: !changesAvailable,
    },
    {
      id: "terminal" as const,
      label: t("workbench.terminal"),
      icon: SquareTerminal,
    },
    { id: "tools" as const, label: t("workbench.tools"), icon: Wrench },
  ];

  return (
    <div className={styles.shell}>
      <header className={styles.header}>
        <nav className={styles.tabs} aria-label={t("workbench.navigation")}>
          {tabs.map((tab) => {
            const Icon = tab.icon;
            return (
              <button
                key={tab.id}
                type="button"
                className={activeTab === tab.id ? styles.activeTab : ""}
                aria-current={activeTab === tab.id ? "page" : undefined}
                disabled={tab.disabled}
                title={
                  tab.disabled
                    ? codingMode
                      ? t("workbench.sessionRequired")
                      : t("workbench.codingModeRequired")
                    : tab.label
                }
                onClick={() => selectTab(tab.id)}
              >
                <Icon size={16} />
                <span>{tab.label}</span>
              </button>
            );
          })}
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
        <Suspense
          fallback={<div className={styles.empty}>{t("common.loading")}</div>}
        >
          {activeTab === "files" ? (
            <FilesWorkspace
              initialTarget={initialTarget}
              scope={scope}
              embedded
            />
          ) : activeTab === "changes" ? (
            <GitPanel chatId={scope.chatId} />
          ) : (
            <div className={styles.empty}>
              {t("workbench.phasePlaceholder")}
            </div>
          )}
        </Suspense>
      </main>
    </div>
  );
}
