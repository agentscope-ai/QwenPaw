import { useMemo } from "react";
import dayjs, { type Dayjs } from "dayjs";
import { useTranslation } from "react-i18next";

interface UseLlmToolTrendConfigProps {
  byDate: Record<
    string,
    {
      prompt_tokens: number;
      completion_tokens: number;
      call_count: number;
    }
  > | null;
  dailyToolCalls: Record<string, number>;
  startDate: Dayjs;
  endDate: Dayjs;
  isDark: boolean;
  /** When true, omit the tool series (API load failed). */
  toolCallsUnavailable?: boolean;
}

export function useLlmToolTrendConfig({
  byDate,
  dailyToolCalls,
  startDate,
  endDate,
  isDark,
  toolCallsUnavailable = false,
}: UseLlmToolTrendConfigProps) {
  const { t } = useTranslation();

  return useMemo(() => {
    const hasLlm =
      !!byDate && Object.values(byDate).some((d) => (d.call_count ?? 0) > 0);
    const hasTool =
      !toolCallsUnavailable &&
      Object.values(dailyToolCalls).some((v) => v > 0);
    if (!hasLlm && !hasTool) return null;

    const allDates: string[] = [];
    let current = startDate.clone();
    while (current.isBefore(endDate) || current.isSame(endDate, "day")) {
      allDates.push(current.format("YYYY-MM-DD"));
      current = current.add(1, "day");
    }

    const llmLabel = t("tokenUsage.llmCalls");
    const toolLabel = t("tokenUsage.toolCalls");
    const crossesYear = startDate.year() !== endDate.year();

    const chartData = allDates.flatMap((date) => {
      const rows: { date: string; value: number; category: string }[] = [];
      if (hasLlm) {
        rows.push({
          date,
          value: byDate?.[date]?.call_count ?? 0,
          category: llmLabel,
        });
      }
      if (hasTool) {
        rows.push({
          date,
          value: dailyToolCalls[date] ?? 0,
          category: toolLabel,
        });
      }
      return rows;
    });

    return {
      data: chartData,
      xField: "date",
      yField: "value",
      seriesField: "category",
      colorField: "category",
      isGroup: true,
      height: 300,
      autoFit: true,
      theme: isDark ? "dark" : "light",
      legend: { position: "bottom" as const },
      meta: {
        color: { range: ["#ec4899", "#14b8a6"] },
      },
      axis: {
        x: {
          labelFormatter: (d: string) => {
            const date = dayjs(d);
            return crossesYear
              ? date.format("YY/MM-DD")
              : date.format("MM-DD");
          },
        },
      },
      tooltip: {
        title: "date",
        items: [
          (datum: { date: string; value: number; category: string }) => ({
            name: datum.category,
            value: datum.value?.toLocaleString(),
          }),
        ],
      },
    };
  }, [
    byDate,
    dailyToolCalls,
    startDate,
    endDate,
    isDark,
    toolCallsUnavailable,
    t,
  ]);
}
