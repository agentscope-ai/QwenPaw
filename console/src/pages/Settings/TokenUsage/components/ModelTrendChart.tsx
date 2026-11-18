import type { LineConfig } from "@ant-design/plots";
import { Card } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import { SnapTrend } from "@/components/interaction/SnapTrend";
import styles from "../index.module.less";

interface ModelTrendChartProps {
  chartConfig: LineConfig | null;
}

export function ModelTrendChart({ chartConfig }: ModelTrendChartProps) {
  const { t } = useTranslation();

  if (!chartConfig) return null;

  return (
    <Card
      className={styles.chartCard}
      title={
        <span className={styles.chartTitle}>{t("tokenUsage.modelTrend")}</span>
      }
    >
      <SnapTrend config={chartConfig} label={t("tokenUsage.date")} />
    </Card>
  );
}
