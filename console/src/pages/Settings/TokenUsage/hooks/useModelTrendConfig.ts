import { useMemo } from "react";
import dayjs, { type Dayjs } from "dayjs";
import { formatCompact } from "../../../../utils/formatNumber";

interface UseModelTrendConfigProps {
  byDateModel: Record<
    string,
    Record<
      string,
      {
        model: string;
        provider_id: string;
        prompt_tokens: number;
        completion_tokens: number;
        call_count: number;
      }
    >
  > | null;
  startDate: Dayjs;
  endDate: Dayjs;
  isDark: boolean;
}

export function useModelTrendConfig({
  byDateModel,
  startDate,
  endDate,
  isDark,
}: UseModelTrendConfigProps) {
  return useMemo(() => {
    if (!byDateModel || Object.keys(byDateModel).length === 0) return null;

    const isDarkMode = isDark;

    const allModelKeys = new Set<string>();
    Object.values(byDateModel).forEach((modelMap) => {
      Object.keys(modelMap).forEach((key) => allModelKeys.add(key));
    });

    const allDates: string[] = [];
    let current = startDate.clone();
    while (current.isBefore(endDate) || current.isSame(endDate, "day")) {
      allDates.push(current.format("YYYY-MM-DD"));
      current = current.add(1, "day");
    }

    const chartData: Array<{
      date: string;
      model: string;
      value: number;
    }> = [];

    allDates.forEach((date) => {
      const dayData = byDateModel[date] || {};
      allModelKeys.forEach((modelKey) => {
        chartData.push({
          date,
          model: modelKey,
          value: dayData[modelKey]?.prompt_tokens || 0,
        });
      });
    });

    const tickCount = Math.min(10, Math.max(3, allDates.length));

    return {
      data: chartData,
      xField: "date",
      yField: "value",
      seriesField: "model",
      colorField: "model",
      smooth: true,
      autoFit: true,
      height: 300,
      theme: isDarkMode ? "dark" : "light",
      style: {
        lineWidth: 3,
        fillOpacity: 0,
      },
      tooltip: {
        title: "date",
        items: [
          (datum: { date: string; value: number; model: string }) => ({
            name: datum.model,
            value: formatCompact(datum.value),
          }),
        ],
      },
      axis: {
        x: {
          range: [0, 1],
          nice: true,
          tickCount,
          labelFormatter: (d: string) => {
            const date = dayjs(d);
            return date.format("MM-DD");
          },
          grid: null,
        },
        y: {
          labelFormatter: (v: number) => {
            if (v >= 1_000_000) {
              return `${(v / 1_000_000).toFixed(1)}M`;
            } else if (v >= 1_000) {
              return `${(v / 1_000).toFixed(0)}K`;
            }
            return v.toString();
          },
          grid: {
            line: {
              style: {
                stroke: isDarkMode
                  ? "rgba(255, 255, 255, 0.05)"
                  : "rgba(0, 0, 0, 0.04)",
              },
            },
          },
        },
      },
      legend: {
        position: "top" as const,
        maxRows: 2,
        itemMarker: "circle",
        itemMarkerSize: 8,
        itemLabelFontSize: 11,
        itemSpacing: 8,
        itemName: {
          style: {
            fill: isDarkMode ? "rgba(255, 255, 255, 0.85)" : "#333",
            fontSize: 11,
          },
        },
      },
    };
  }, [byDateModel, startDate, endDate, isDark]);
}
