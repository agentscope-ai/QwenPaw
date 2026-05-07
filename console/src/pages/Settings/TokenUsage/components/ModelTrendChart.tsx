import { Card } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import { Line } from "@ant-design/plots";
import styles from "../index.module.less";

interface ModelTrendChartProps {
  chartConfig: any;
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
      <Line {...chartConfig} />
    </Card>
  );
}
