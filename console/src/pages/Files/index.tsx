import { FileText } from "lucide-react";
import { useTranslation } from "react-i18next";
import FilesWorkspace from "../../features/files-workspace/FilesWorkspace";
import { OpenWorkspaceButton } from "../../features/files-workspace/OpenWorkspaceButton";
import { useAgentStore } from "../../stores/agentStore";
import workspaceStyles from "../../features/files-workspace/FilesWorkspace.module.less";
import styles from "./index.module.less";

export default function FilesPage() {
  const { t } = useTranslation();
  const { selectedAgent } = useAgentStore();

  return (
    <section className={styles.page} aria-label={t("files.agentWorkspace")}>
      <header className={workspaceStyles.drawerHeader}>
        <div className={workspaceStyles.fileMark} aria-hidden="true">
          <FileText size={17} />
        </div>
        <div className={workspaceStyles.drawerTitle}>
          <strong>{t("files.title")}</strong>
        </div>
        <OpenWorkspaceButton agentId={selectedAgent || null} />
      </header>
      <div className={styles.workspace}>
        <FilesWorkspace scope={{ kind: "agent", agentId: selectedAgent }} />
      </div>
    </section>
  );
}
