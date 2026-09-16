import { useTranslation } from "react-i18next";
import type { AgentRunningConfigSummary } from "../../../api/modules/agent";
import styles from "./index.module.less";

type Props = {
  summary: AgentRunningConfigSummary;
};

export function ReadOnlyConfigSummary({ summary }: Props) {
  const { t } = useTranslation();
  const model = summary.active_model;

  return (
    <section
      className={styles.readOnlySummary}
      aria-label={t("agentConfig.readOnlyTitle")}
    >
      <div className={styles.readOnlySummaryHeader}>
        <div>
          <span className={styles.readOnlyEyebrow}>
            {t("agentConfig.readOnlyEyebrow")}
          </span>
          <h2>{summary.name}</h2>
          <p>{t("agentConfig.readOnlyDescription")}</p>
        </div>
        <span className={styles.readOnlyBadge}>
          {t("agentConfig.readOnlyBadge")}
        </span>
      </div>

      <div className={styles.readOnlyGrid}>
        <div>
          <span>{t("agentConfig.language")}</span>
          <strong>{summary.language}</strong>
        </div>
        <div>
          <span>{t("agentConfig.timezone")}</span>
          <strong>{summary.timezone}</strong>
        </div>
        <div>
          <span>{t("agentConfig.activeModel")}</span>
          <strong>{model?.model || t("agentConfig.notConfigured")}</strong>
          {model?.provider_id && <small>{model.provider_id}</small>}
        </div>
        <div>
          <span>{t("agentConfig.modelSwitching")}</span>
          <strong>
            {summary.model_switchable
              ? t("agentConfig.availableInChat")
              : t("agentConfig.fixedModel")}
          </strong>
        </div>
      </div>

      <p className={styles.readOnlyNotice}>
        {summary.read_only_reason || t("agentConfig.readOnlyDescription")}
      </p>
    </section>
  );
}
