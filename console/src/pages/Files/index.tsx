import { FileText } from "lucide-react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useLocation, useSearchParams } from "react-router-dom";
import UnifiedFileCenter from "../../features/files-workspace/UnifiedFileCenter";
import { parseFileCenterLocation } from "../../features/files-workspace/fileLocator";
import { useAgentStore } from "../../stores/agentStore";
import workspaceStyles from "../../features/files-workspace/FilesWorkspace.module.less";
import styles from "./index.module.less";

export default function FilesPage() {
  const { t } = useTranslation();
  const { selectedAgent } = useAgentStore();
  const [searchParams] = useSearchParams();
  const location = useLocation();
  const initialLocator = parseFileCenterLocation(`${location.pathname}${location.search}`);
  const governanceAgentId =
    searchParams.get("governance") === "runtime-config"
      ? searchParams.get("agentId")
      : null;
  const agentId = governanceAgentId || initialLocator?.agentId || selectedAgent;
  const requestContext = useMemo(
    () => ({
      agentId,
      ...(governanceAgentId ? { governance: true as const } : {}),
    }),
    [agentId, governanceAgentId],
  );

  return (
    <section className={styles.page} aria-label={t("files.agentWorkspace")}>
      <header className={workspaceStyles.drawerHeader}>
        <div className={workspaceStyles.fileMark} aria-hidden="true">
          <FileText size={17} />
        </div>
        <div className={workspaceStyles.drawerTitle}>
          <strong>{t("files.title")}</strong>
          {governanceAgentId && (
            <span>
              {t("files.governanceMemoryTitle", {
                name: searchParams.get("agentName") || governanceAgentId,
              })}
            </span>
          )}
        </div>
      </header>
      <div className={styles.workspace}>
        <UnifiedFileCenter
          agentId={agentId}
          requestContext={requestContext}
          initialLocator={initialLocator}
          syncLocation
        />
      </div>
    </section>
  );
}
