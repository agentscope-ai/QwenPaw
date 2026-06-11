import { useMemo } from "react";
import dayjs, { type Dayjs } from "dayjs";

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

export interface ModelTrendChartData {
  /** Pivoted rows: { date, [modelKey]: tokenCount, ... } */
  chartData: Array<Record<string, string | number>>;
  modelKeys: string[];
  dateFormatter: (d: string) => string;
}

const CHART_COLORS = [
  "#1677ff",
  "#52c41a",
  "#fa8c16",
  "#eb2f96",
  "#722ed1",
  "#13c2c2",
  "#fadb14",
  "#a0d911",
];

export function useModelTrendConfig({
  byDateModel,
  startDate,
  endDate,
}: UseModelTrendConfigProps): ModelTrendChartData | null {
  return useMemo(() => {
    if (!byDateModel || Object.keys(byDateModel).length === 0) return null;

    const allModelKeys = new Set<string>();
    Object.values(byDateModel).forEach((modelMap) => {
      Object.keys(modelMap).forEach((key) => allModelKeys.add(key));
    });

    const modelKeys = Array.from(allModelKeys);

    const allDates: string[] = [];
    let current = startDate.clone();
    while (current.isBefore(endDate) || current.isSame(endDate, "day")) {
      allDates.push(current.format("YYYY-MM-DD"));
      current = current.add(1, "day");
    }

    const chartData = allDates.map((date) => {
      const dayData = byDateModel[date] || {};
      const row: Record<string, string | number> = { date };
      modelKeys.forEach((mk) => {
        row[mk] = dayData[mk]?.prompt_tokens ?? 0;
      });
      return row;
    });

    const crossesYear = startDate.year() !== endDate.year();
    const dateFormatter = (d: string) => {
      const parsed = dayjs(d);
      return crossesYear ? parsed.format("YY/MM-DD") : parsed.format("MM-DD");
    };

    return { chartData, modelKeys, dateFormatter };
  }, [byDateModel, startDate, endDate]);
}

export { CHART_COLORS };
