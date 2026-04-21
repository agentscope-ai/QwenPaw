/**
 * Renders a row of Ant Design Tags summarising what a backup covers:
 * agent count, global config, skill pool, and secrets (highlighted in orange).
 * Used in the BackupTable scope column and potentially elsewhere.
 */
import { Tag } from "antd";
import { useTranslation } from "react-i18next";
import type { BackupMeta } from "@/api/types/backup";
import styles from "./ScopeTags.module.less";

interface Props {
  scope: BackupMeta["scope"];
  agentCount?: number;
}

export default function ScopeTags({ scope, agentCount }: Props) {
  const { t } = useTranslation();
  return (
    <div className={styles.scopeTags}>
      {scope.include_agents && agentCount ? (
        <Tag>{t("backup.agents", { count: agentCount })}</Tag>
      ) : null}
      {scope.include_global_config && <Tag>{t("backup.globalConfig")}</Tag>}
      {scope.include_skill_pool && <Tag>{t("backup.skillPool")}</Tag>}
      {scope.include_secrets && <Tag color="orange">{t("backup.secrets")}</Tag>}
    </div>
  );
}
