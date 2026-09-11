import { useMemo } from "react";
import { type Dayjs } from "dayjs";
import { lineChartChrome } from "./lineChartChrome";

interface UseTokenTypeConfigProps {
  byDate: Record<
    string,
    {
      prompt_tokens: number;
      completion_tokens: number;
      call_count: number;
    }
  > | null;
  startDate: Dayjs;
  endDate: Dayjs;
  isDark: boolean;
}

const TYPE_COLORS: Record<string, string> = {
  "Prompt Tokens": "#1677ff",
  "Completion Tokens": "#52c41a",
  "Total Tokens": "#fa8c16",
};

export function useTokenTypeConfig({
  byDate,
  startDate,
  endDate,
  isDark,
}: UseTokenTypeConfigProps) {
  return useMemo(() => {
    if (!byDate || Object.keys(byDate).length === 0) return null;

    const isDarkMode = isDark;

    const allDates: string[] = [];
    let current = startDate.clone();
    while (current.isBefore(endDate) || current.isSame(endDate, "day")) {
      allDates.push(current.format("YYYY-MM-DD"));
      current = current.add(1, "day");
    }

    const allTypes = [
      "Prompt Tokens",
      "Completion Tokens",
      "Total Tokens",
    ] as const;
    const colors = allTypes.map((type) => TYPE_COLORS[type]);

    const chartData: Array<{
      date: string;
      type: string;
      value: number;
    }> = [];

    allDates.forEach((date) => {
      const dayStats = byDate[date] || {
        prompt_tokens: 0,
        completion_tokens: 0,
        call_count: 0,
      };

      const typeValues: Record<string, number> = {
        "Prompt Tokens": dayStats.prompt_tokens,
        "Completion Tokens": dayStats.completion_tokens,
        "Total Tokens": dayStats.prompt_tokens + dayStats.completion_tokens,
      };

      allTypes.forEach((type) => {
        chartData.push({
          date,
          type,
          value: typeValues[type] || 0,
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
        seriesField: "type",
        colors,
        legend: {
          itemName: {
            style: {
              fill: isDarkMode ? "rgba(255, 255, 255, 0.85)" : "#333",
              fontSize: 12,
            },
          },
        },
      }),
    };
  }, [byDate, startDate, endDate, isDark]);
}
