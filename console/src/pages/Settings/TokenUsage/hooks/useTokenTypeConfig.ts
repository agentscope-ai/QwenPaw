import { useMemo } from "react";
import dayjs, { type Dayjs } from "dayjs";

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

export const TYPE_COLORS: Record<string, string> = {
  "Prompt Tokens": "#1677ff",
  "Completion Tokens": "#52c41a",
  "Total Tokens": "#fa8c16",
};

const TOKEN_TYPE_KEYS = [
  "Prompt Tokens",
  "Completion Tokens",
  "Total Tokens",
] as const;

export interface TokenTypeChartData {
  /** Pivoted rows: { date, "Prompt Tokens": n, "Completion Tokens": n, "Total Tokens": n } */
  chartData: Array<Record<string, string | number>>;
  typeKeys: string[];
  dateFormatter: (d: string) => string;
}

export function useTokenTypeConfig({
  byDate,
  startDate,
  endDate,
}: UseTokenTypeConfigProps): TokenTypeChartData | null {
  return useMemo(() => {
    if (!byDate || Object.keys(byDate).length === 0) return null;

    const allDates: string[] = [];
    let current = startDate.clone();
    while (current.isBefore(endDate) || current.isSame(endDate, "day")) {
      allDates.push(current.format("YYYY-MM-DD"));
      current = current.add(1, "day");
    }

    const chartData = allDates.map((date) => {
      const d = byDate[date] ?? {
        prompt_tokens: 0,
        completion_tokens: 0,
        call_count: 0,
      };
      return {
        date,
        "Prompt Tokens": d.prompt_tokens,
        "Completion Tokens": d.completion_tokens,
        "Total Tokens": d.prompt_tokens + d.completion_tokens,
      } as Record<string, string | number>;
    });

    const crossesYear = startDate.year() !== endDate.year();
    const dateFormatter = (d: string) => {
      const parsed = dayjs(d);
      return crossesYear ? parsed.format("YY/MM-DD") : parsed.format("MM-DD");
    };

    return { chartData, typeKeys: [...TOKEN_TYPE_KEYS], dateFormatter };
  }, [byDate, startDate, endDate]);
}
