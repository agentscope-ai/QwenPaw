import { useMemo } from "react";
import dayjs, { type Dayjs } from "dayjs";
import { formatCompact } from "../../../../utils/formatNumber";

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
  selectedTokenTypes: string[];
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
  selectedTokenTypes,
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

    const allTypes = ["Prompt Tokens", "Completion Tokens", "Total Tokens"];
    const filteredTypes =
      selectedTokenTypes.length > 0
        ? allTypes.filter((type) => selectedTokenTypes.includes(type))
        : allTypes;

    // If no types selected, show all types
    const displayTypes =
      selectedTokenTypes.length === 0 ? allTypes : filteredTypes;

    const colors = displayTypes
      .map((type) => TYPE_COLORS[type])
      .filter(Boolean);

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

      displayTypes.forEach((type) => {
        chartData.push({
          date,
          type,
          value: typeValues[type] || 0,
        });
      });
    });

    const tickCount = Math.min(10, Math.max(3, allDates.length));

    return {
      data: chartData,
      xField: "date",
      yField: "value",
      seriesField: "type",
      colorField: "type",
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
          (datum: { date: string; value: number; type: string }) => ({
            name: datum.type,
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
      color: colors,
    };
  }, [byDate, startDate, endDate, selectedTokenTypes, isDark]);
}
