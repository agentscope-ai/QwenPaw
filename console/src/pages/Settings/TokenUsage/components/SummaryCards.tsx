import { Card } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import { formatCompact } from "../../../../utils/formatNumber";
import { cacheHitRate, formatPercent } from "../../../../utils/cacheUsage";
import styles from "../index.module.less";

interface SummaryCardsProps {
  totalCalls: number;
  totalPromptTokens: number;
  totalCompletionTokens: number;
  totalCacheReadTokens: number;
  totalCacheEligibleInputTokens: number;
}

export function SummaryCards({
  totalCalls,
  totalPromptTokens,
  totalCompletionTokens,
  totalCacheReadTokens,
  totalCacheEligibleInputTokens,
}: SummaryCardsProps) {
  const { t } = useTranslation();
  const hitRate = cacheHitRate(
    totalCacheReadTokens,
    totalCacheEligibleInputTokens,
  );

  return (
    <div className={styles.summaryCards}>
      <Card className={styles.card}>
        <div className={styles.cardValue}>{formatCompact(totalCalls)}</div>
        <div className={styles.cardLabel}>{t("tokenUsage.totalCalls")}</div>
      </Card>
      <Card className={styles.card}>
        <div className={styles.cardValue}>
          {formatCompact(totalPromptTokens)}
        </div>
        <div className={styles.cardLabel}>{t("tokenUsage.promptTokens")}</div>
      </Card>
      <Card className={styles.card}>
        <div className={styles.cardValue}>
          {formatCompact(totalCacheReadTokens)}
        </div>
        <div className={styles.cardLabel}>{t("tokenUsage.cacheRead")}</div>
      </Card>
      <Card className={styles.card}>
        <div className={styles.cardValue}>{formatPercent(hitRate)}</div>
        <div className={styles.cardLabel}>{t("tokenUsage.cacheHitRate")}</div>
      </Card>
      <Card className={styles.card}>
        <div className={styles.cardValue}>
          {formatCompact(totalCompletionTokens)}
        </div>
        <div className={styles.cardLabel}>
          {t("tokenUsage.completionTokens")}
        </div>
      </Card>
    </div>
  );
}
