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
    <UsageSummaryCards
      items={[
        { label: t("tokenUsage.totalCalls"), value: formatCompact(totalCalls) },
        {
          label: t("tokenUsage.promptTokens"),
          value: formatCompact(totalPromptTokens),
        },
        {
          label: t("tokenUsage.cacheRead"),
          value: formatCompact(totalCacheReadTokens),
        },
        { label: t("tokenUsage.cacheHitRate"), value: formatPercent(hitRate) },
        {
          label: t("tokenUsage.completionTokens"),
          value: formatCompact(totalCompletionTokens),
        },
      ]}
    />
  );
}

export function UsageSummaryCards({
  items,
}: {
  items: { label: string; value: string }[];
}) {
  return (
    <div className={styles.summaryCards}>
      {items.map((item) => (
        <Card className={styles.card} key={item.label}>
          <div className={styles.cardValue}>{item.value}</div>
          <div className={styles.cardLabel}>{item.label}</div>
        </Card>
      ))}
    </div>
  );
}
