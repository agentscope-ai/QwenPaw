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
  selectedModels: string[];
  isDark: boolean;
}

export function useModelTrendConfig({
  byDateModel,
  startDate,
  endDate,
  selectedModels,
  isDark,
}: UseModelTrendConfigProps) {
  return useMemo(() => {
    if (!byDateModel || Object.keys(byDateModel).length === 0) return null;

    const isDarkMode = isDark;

    const allModelKeys = new Map<string, { provider: string; model: string }>();
    Object.entries(byDateModel).forEach(([, modelMap]) => {
      Object.entries(modelMap).forEach(([key, stats]) => {
        allModelKeys.set(key, {
          provider: stats.provider_id,
          model: stats.model,
        });
      });
    });

    const filteredModelKeys =
      selectedModels.length > 0
        ? new Map(
            Array.from(allModelKeys.entries()).filter(([key]) =>
              selectedModels.includes(key),
            ),
          )
        : allModelKeys;

    // If no models selected, show all models
    const displayModelKeys =
      selectedModels.length === 0 ? allModelKeys : filteredModelKeys;

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
      displayModelKeys.forEach((_, modelKey) => {
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
            return date.format("MMM DD");
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
        itemMarker: "circle",
        itemName: {
          style: {
            fill: isDarkMode ? "rgba(255, 255, 255, 0.85)" : "#333",
            fontSize: 12,
          },
        },
      },
    };
  }, [byDateModel, startDate, endDate, selectedModels, isDark]);
}
