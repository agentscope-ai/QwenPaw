import dayjs, { type Dayjs } from "dayjs";
import { formatCompact } from "../../../../utils/formatNumber";

type LineChartChromeOptions = {
  isDark: boolean;
  tickCount: number;
  startDate: Dayjs;
  endDate: Dayjs;
  seriesField: string;
  colors?: string[];
  legend?: Record<string, unknown>;
};

export function lineChartChrome({
  isDark,
  tickCount,
  startDate,
  endDate,
  seriesField,
  colors,
  legend,
}: LineChartChromeOptions) {
  const ymd = startDate.year() !== endDate.year();
  return {
    xField: "date",
    yField: "value",
    seriesField,
    colorField: seriesField,
    smooth: true,
    autoFit: true,
    height: 300,
    theme: isDark ? "dark" : "light",
    style: { lineWidth: 3, fillOpacity: 0 },
    tooltip: {
      title: "date",
      items: [
        (datum: Record<string, unknown>) => ({
          name: String(datum[seriesField] ?? ""),
          value: formatCompact(Number(datum.value) || 0),
        }),
      ],
    },
    axis: {
      x: {
        range: [0, 1] as [number, number],
        nice: true,
        tickCount,
        labelFormatter: (d: string) =>
          dayjs(d).format(ymd ? "YY/MM-DD" : "MM-DD"),
        grid: null,
      },
      y: {
        labelFormatter: (v: number) => {
          if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
          if (v >= 1_000) return `${(v / 1_000).toFixed(0)}K`;
          return String(v);
        },
        grid: {
          line: {
            style: {
              stroke: isDark
                ? "rgba(255, 255, 255, 0.05)"
                : "rgba(0, 0, 0, 0.04)",
            },
          },
        },
      },
    },
    legend: {
      position: "top" as const,
      itemMarker: "circle",
      ...legend,
    },
    ...(colors ? { color: colors } : {}),
  };
}
