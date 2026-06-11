import { useTranslation } from "react-i18next";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from "recharts";
import type { ModelTrendChartData } from "../hooks/useModelTrendConfig";
import { CHART_COLORS } from "../hooks/useModelTrendConfig";
import { formatCompact } from "../../../../utils/formatNumber";
import styles from "../index.module.less";

interface ModelTrendChartProps {
  chartConfig: ModelTrendChartData | null;
}

const yTickFormatter = (v: number) => {
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000) return `${(v / 1_000).toFixed(0)}K`;
  return v.toString();
};

export function ModelTrendChart({ chartConfig }: ModelTrendChartProps) {
  const { t } = useTranslation();

  if (!chartConfig) return null;

  const { chartData, modelKeys, dateFormatter } = chartConfig;

  return (
    <div className={`${styles.chartCard} border rounded-lg p-4`}>
      <div className={styles.chartTitle}>{t("tokenUsage.modelTrend")}</div>
      <ResponsiveContainer width="100%" height={300}>
        <LineChart
          data={chartData}
          margin={{ top: 8, right: 16, left: 0, bottom: 0 }}
        >
          <CartesianGrid
            strokeDasharray="3 3"
            stroke="rgba(128,128,128,0.15)"
          />
          <XAxis
            dataKey="date"
            tickFormatter={dateFormatter}
            tick={{ fontSize: 11 }}
          />
          <YAxis
            tickFormatter={yTickFormatter}
            tick={{ fontSize: 11 }}
            width={48}
          />
          <Tooltip
            formatter={(value: number, name: string) => [
              formatCompact(value),
              name,
            ]}
            labelFormatter={(label: string) => label}
          />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          {modelKeys.map((mk, idx) => (
            <Line
              key={mk}
              type="monotone"
              dataKey={mk}
              stroke={CHART_COLORS[idx % CHART_COLORS.length]}
              strokeWidth={2}
              dot={false}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
