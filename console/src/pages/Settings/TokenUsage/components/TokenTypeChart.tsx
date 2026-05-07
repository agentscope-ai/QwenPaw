import { Card } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import { Line } from "@ant-design/plots";
import { ChartFilterSelect } from "./ChartFilterSelect";
import styles from "../index.module.less";

const TOKEN_TYPES = ["Prompt Tokens", "Completion Tokens", "Total Tokens"];

interface TokenTypeChartProps {
  chartConfig: any;
  selectedTokenTypes: string[];
  onTokenTypeChange: (types: string[]) => void;
}

export function TokenTypeChart({
  chartConfig,
  selectedTokenTypes,
  onTokenTypeChange,
}: TokenTypeChartProps) {
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
            {t("tokenUsage.tokenTypeChart", "Token Type Trend")}
          </span>
          <ChartFilterSelect
            value={selectedTokenTypes}
            onChange={onTokenTypeChange}
            options={TOKEN_TYPES as [string, string, string]}
            placeholder={t("tokenUsage.selectTokenTypes")}
            style={{ minWidth: 200 }}
          />
        </div>
      }
    >
      <Line {...chartConfig} />
    </Card>
  );
}
