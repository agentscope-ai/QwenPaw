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
import type { TokenTypeChartData } from "../hooks/useTokenTypeConfig";
import { TYPE_COLORS } from "../hooks/useTokenTypeConfig";
import { formatCompact } from "../../../../utils/formatNumber";
import styles from "../index.module.less";

interface TokenTypeChartProps {
  chartConfig: TokenTypeChartData | null;
}

const yTickFormatter = (v: number) => {
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000) return `${(v / 1_000).toFixed(0)}K`;
  return v.toString();
};

export function TokenTypeChart({ chartConfig }: TokenTypeChartProps) {
  const { t } = useTranslation();

  if (!chartConfig) return null;

  const { chartData, typeKeys, dateFormatter } = chartConfig;

  return (
    <div className={`${styles.chartCard} border rounded-lg p-4`}>
      <div className={styles.chartTitle}>
        {t("tokenUsage.tokenTypeChart", "Token Type Trend")}
      </div>
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
          {typeKeys.map((tk) => (
            <Line
              key={tk}
              type="monotone"
              dataKey={tk}
              stroke={TYPE_COLORS[tk] ?? "#8884d8"}
              strokeWidth={2}
              dot={false}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
