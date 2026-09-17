import { Card } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import { Line } from "@ant-design/plots";
import styles from "../index.module.less";

interface TokenTypeChartProps {
  chartConfig: any;
}

export function TokenTypeChart({ chartConfig }: TokenTypeChartProps) {
  const { t } = useTranslation();

  if (!chartConfig) return null;

  return (
    <Card
      className={styles.chartCard}
      title={
        <span className={styles.chartTitle}>
          {t("tokenUsage.tokenTypeChart", "Token Type Trend")}
        </span>
      }
    >
      <Line {...chartConfig} />
    </Card>
  );
}
