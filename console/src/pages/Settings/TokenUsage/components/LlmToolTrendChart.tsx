import { Card } from "@agentscope-ai/design";
import { Tooltip } from "antd";
import { useTranslation } from "react-i18next";
import { Column } from "@ant-design/plots";
import styles from "../index.module.less";

interface LlmToolTrendChartProps {
  chartConfig: Record<string, unknown> | null;
}

export function LlmToolTrendChart({ chartConfig }: LlmToolTrendChartProps) {
  const { t } = useTranslation();

  if (!chartConfig) return null;

  return (
    <Card
      className={styles.chartCard}
      title={
        <Tooltip title={t("tokenUsage.llmAndToolTrendTooltip")} placement="bottom">
          <span className={styles.chartTitle}>
            {t("tokenUsage.llmAndToolTrend")}
          </span>
        </Tooltip>
      }
    >
      <Column {...chartConfig} />
    </Card>
  );
}
