import { Card } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import { Line } from "@ant-design/plots";
import { ChartFilterSelect } from "./ChartFilterSelect";
import styles from "../index.module.less";

interface ModelTrendChartProps {
  chartConfig: any;
  selectedModels: string[];
  allModels: string[];
  onModelChange: (models: string[]) => void;
}

export function ModelTrendChart({
  chartConfig,
  selectedModels,
  allModels,
  onModelChange,
}: ModelTrendChartProps) {
  const { t } = useTranslation();

  if (!chartConfig) return null;

  return (
    <Card
      className={styles.chartCard}
      title={
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            gap: "12px",
            flexWrap: "wrap",
          }}
        >
          <span className={styles.chartTitle}>
            {t("tokenUsage.modelTrend")}
          </span>
          <ChartFilterSelect
            value={selectedModels}
            onChange={onModelChange}
            options={allModels}
            placeholder={t("tokenUsage.selectModels")}
            style={{ minWidth: 200, maxWidth: 400 }}
          />
        </div>
      }
    >
      <Line {...chartConfig} />
    </Card>
  );
}
