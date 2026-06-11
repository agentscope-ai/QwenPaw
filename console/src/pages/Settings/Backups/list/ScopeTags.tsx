/**
 * Renders a row of badges summarising what a backup covers:
 * agent count, global config, skill pool, and secrets (highlighted in orange).
 * Used in the BackupTable scope column and potentially elsewhere.
 */
import { useTranslation } from "react-i18next";
import type { BackupMeta } from "@/api/types/backup";
import { Badge } from "@/components/ui/badge";
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
        <Badge variant="secondary">
          {t("backup.agents", { count: agentCount })}
        </Badge>
      ) : null}
      {scope.include_global_config && (
        <Badge variant="secondary">{t("backup.globalConfig")}</Badge>
      )}
      {scope.include_skill_pool && (
        <Badge variant="secondary">{t("backup.skillPool")}</Badge>
      )}
      {scope.include_secrets && (
        <Badge className="bg-orange-100 text-orange-700 border-orange-200 dark-mode:bg-orange-950 dark-mode:text-orange-300">
          {t("backup.secrets")}
        </Badge>
      )}
    </div>
  );
}
