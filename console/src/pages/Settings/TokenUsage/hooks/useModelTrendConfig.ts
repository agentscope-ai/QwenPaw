import { useMemo } from "react";
import { type Dayjs } from "dayjs";
import { lineChartChrome } from "./lineChartChrome";

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

    return {
      data: chartData,
      ...lineChartChrome({
        isDark: isDarkMode,
        tickCount: Math.min(10, Math.max(3, allDates.length)),
        startDate,
        endDate,
        seriesField: "model",
        legend: {
          maxRows: 2,
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
      }),
    };
  }, [byDateModel, startDate, endDate, isDark]);
}
