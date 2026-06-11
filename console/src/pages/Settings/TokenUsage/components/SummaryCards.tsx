import { useTranslation } from "react-i18next";
import { formatCompact } from "../../../../utils/formatNumber";
import styles from "../index.module.less";

interface SummaryCardsProps {
  totalCalls: number;
  totalPromptTokens: number;
  totalCompletionTokens: number;
  totalTokens: number;
}

export function SummaryCards({
  totalCalls,
  totalPromptTokens,
  totalCompletionTokens,
  totalTokens,
}: SummaryCardsProps) {
  const { t } = useTranslation();

  return (
    <div className={styles.summaryCards}>
      <div className={`${styles.card} border rounded-lg p-4`}>
        <div className={styles.cardValue}>{formatCompact(totalCalls)}</div>
        <div className={styles.cardLabel}>{t("tokenUsage.totalCalls")}</div>
      </div>
      <div className={`${styles.card} border rounded-lg p-4`}>
        <div className={styles.cardValue}>
          {formatCompact(totalPromptTokens)}
        </div>
        <div className={styles.cardLabel}>{t("tokenUsage.promptTokens")}</div>
      </div>
      <div className={`${styles.card} border rounded-lg p-4`}>
        <div className={styles.cardValue}>
          {formatCompact(totalCompletionTokens)}
        </div>
        <div className={styles.cardLabel}>
          {t("tokenUsage.completionTokens")}
        </div>
      </div>
      <div className={`${styles.card} border rounded-lg p-4`}>
        <div className={styles.cardValue}>{formatCompact(totalTokens)}</div>
        <div className={styles.cardLabel}>{t("tokenUsage.totalTokens")}</div>
      </div>
    </div>
  );
}
