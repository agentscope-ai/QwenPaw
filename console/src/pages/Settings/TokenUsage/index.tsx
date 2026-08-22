import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { DatePicker, Tooltip } from "antd";
import { Card } from "@agentscope-ai/design";
import { Line } from "@ant-design/plots";
import { useTranslation } from "react-i18next";
import dayjs, { type Dayjs } from "dayjs";
import { useTheme } from "../../../contexts/ThemeContext";
import api from "../../../api";
import type { TokenUsageRecord } from "../../../api/types/tokenUsage";
import type { LlmToolDaily } from "../../../api/modules/agentStats";
import { useAppMessage } from "../../../hooks/useAppMessage";
import { formatCompact } from "../../../utils/formatNumber";
import { PageHeader } from "@/components/PageHeader";
import {
  LoadingState,
  SummaryCards,
  ModelTrendChart,
  TokenTypeChart,
  DataTables,
  EmptyState,
} from "./components";
import { useDataAggregation } from "./hooks/useDataAggregation";
import { useModelTrendConfig } from "./hooks/useModelTrendConfig";
import { useTokenTypeConfig } from "./hooks/useTokenTypeConfig";
import styles from "./index.module.less";

function lineChartChrome(
  isDark: boolean,
  tickCount: number,
  colors: string[],
  startDate: Dayjs,
  endDate: Dayjs,
) {
  const ymd = startDate.year() !== endDate.year();
  return {
    xField: "date",
    yField: "value",
    seriesField: "type",
    colorField: "type",
    smooth: true,
    autoFit: true,
    height: 300,
    theme: isDark ? "dark" : "light",
    style: { lineWidth: 3, fillOpacity: 0 },
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
    legend: { position: "top" as const, itemMarker: "circle" },
    color: colors,
  };
}

function TokenUsagePage() {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const { isDark } = useTheme();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [records, setRecords] = useState<TokenUsageRecord[]>([]);
  const [llmToolDays, setLlmToolDays] = useState<LlmToolDaily[] | null>(null);
  const [trendLoading, setTrendLoading] = useState(true);
  const [trendError, setTrendError] = useState(false);
  const [startDate, setStartDate] = useState<Dayjs>(
    dayjs().subtract(30, "day"),
  );
  const [endDate, setEndDate] = useState<Dayjs>(dayjs());
  const fetchIdRef = useRef(0);
  const trendAbortRef = useRef<AbortController | null>(null);

  const dateRange = useMemo(
    () => ({
      start_date: startDate.format("YYYY-MM-DD"),
      end_date: endDate.format("YYYY-MM-DD"),
    }),
    [startDate, endDate],
  );

  const fetchTrend = useCallback(
    async (fetchId: number) => {
      trendAbortRef.current?.abort();
      const controller = new AbortController();
      trendAbortRef.current = controller;
      setTrendLoading(true);
      setTrendError(false);
      try {
        const data = await api.getGlobalLlmToolTrend(dateRange, {
          signal: controller.signal,
        });
        if (fetchId !== fetchIdRef.current) return;
        setLlmToolDays(data);
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") {
          return;
        }
        console.error("Failed to load llm/tool trend:", err);
        if (fetchId !== fetchIdRef.current) return;
        setLlmToolDays(null);
        setTrendError(true);
      } finally {
        if (fetchId === fetchIdRef.current) {
          setTrendLoading(false);
        }
      }
    },
    [dateRange],
  );

  const fetchData = useCallback(async () => {
    const fetchId = ++fetchIdRef.current;
    setLoading(true);
    setError(false);
    void fetchTrend(fetchId);
    try {
      const detailsData = await api.getTokenUsageDetails(dateRange);
      if (fetchId !== fetchIdRef.current) return;
      setRecords(detailsData);
    } catch (err) {
      console.error("Failed to load token usage:", err);
      if (fetchId !== fetchIdRef.current) return;
      message.error(t("tokenUsage.loadFailed"));
      setRecords([]);
      setError(true);
    } finally {
      if (fetchId === fetchIdRef.current) {
        setLoading(false);
      }
    }
  }, [dateRange, fetchTrend, message, t]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleDateChange = (dates: [Dayjs | null, Dayjs | null] | null) => {
    if (!dates || !dates[0] || !dates[1]) {
      return;
    }
    setStartDate(dates[0]);
    setEndDate(dates[1]);
  };

  const aggregatedData = useDataAggregation(records);

  const modelTrendConfig = useModelTrendConfig({
    byDateModel: aggregatedData?.by_date_model ?? null,
    startDate,
    endDate,
    isDark,
  });

  const tokenTypeConfig = useTokenTypeConfig({
    byDate: aggregatedData?.by_date ?? null,
    startDate,
    endDate,
    isDark,
  });

  const llmToolConfig = useMemo(() => {
    const days = llmToolDays ?? [];
    const llmLabel = t("tokenUsage.recordedTurnsAllAgents");
    const toolLabel = t("tokenUsage.toolCalls");
    return {
      data: days.flatMap((row) => [
        { date: row.date, type: llmLabel, value: row.agent_llm_calls },
        { date: row.date, type: toolLabel, value: row.tool_calls },
      ]),
      ...lineChartChrome(
        isDark,
        Math.min(10, Math.max(3, days.length)),
        ["#722ed1", "#13c2c2"],
        startDate,
        endDate,
      ),
    };
  }, [llmToolDays, startDate, endDate, isDark, t]);

  const byModelData = useMemo(() => {
    if (!aggregatedData?.by_model) return [];
    return Object.entries(aggregatedData.by_model).map(([key, stats]) => ({
      key,
      model: key,
      prompt_tokens: stats.prompt_tokens,
      completion_tokens: stats.completion_tokens,
      call_count: stats.call_count,
    }));
  }, [aggregatedData?.by_model]);

  const byDateData = useMemo(() => {
    if (!aggregatedData?.by_date) return [];
    return Object.entries(aggregatedData.by_date)
      .map(([date, stats]) => ({
        key: date,
        date,
        prompt_tokens: stats.prompt_tokens,
        completion_tokens: stats.completion_tokens,
        call_count: stats.call_count,
      }))
      .sort((a, b) => b.date.localeCompare(a.date));
  }, [aggregatedData?.by_date]);

  const tablesEmpty = byModelData.length === 0 && byDateData.length === 0;

  const pageHeader = (
    <PageHeader parent={t("nav.settings")} current={t("tokenUsage.title")} />
  );

  if (loading) {
    return (
      <div className={styles.container}>
        {pageHeader}
        <LoadingState message={t("common.loading", "Loading...")} />
      </div>
    );
  }

  return (
    <div className={styles.container}>
      {pageHeader}

      <div className={styles.content}>
        <div className={styles.toolbar}>
          <DatePicker.RangePicker
            value={[startDate, endDate]}
            onChange={handleDateChange}
            disabledDate={(current) =>
              !current || current.isAfter(dayjs(), "day")
            }
          />
        </div>

        {error ? (
          <LoadingState
            message={t("tokenUsage.loadFailed")}
            error
            onRetry={fetchData}
          />
        ) : (
          <>
            {aggregatedData && (
              <SummaryCards
                totalCalls={aggregatedData.total_calls}
                totalPromptTokens={aggregatedData.total_prompt_tokens}
                totalCompletionTokens={aggregatedData.total_completion_tokens}
                totalTokens={
                  aggregatedData.total_prompt_tokens +
                  aggregatedData.total_completion_tokens
                }
              />
            )}

            <div className={styles.trendRow}>
              <ModelTrendChart chartConfig={modelTrendConfig} />
              <TokenTypeChart chartConfig={tokenTypeConfig} />
            </div>
          </>
        )}

        <Card
          className={styles.chartCard}
          title={
            <Tooltip title={t("tokenUsage.llmAndToolTrendTooltip")}>
              <span className={styles.chartTitle}>
                {t("tokenUsage.llmAndToolTrend")}
              </span>
            </Tooltip>
          }
        >
          {trendLoading ? (
            <LoadingState message={t("common.loading", "Loading...")} />
          ) : trendError ? (
            <LoadingState
              message={t("tokenUsage.llmAndToolTrendLoadFailed")}
              error
              onRetry={() => {
                void fetchTrend(++fetchIdRef.current);
              }}
            />
          ) : (
            <Line {...llmToolConfig} />
          )}
        </Card>

        {!error &&
          (tablesEmpty ? (
            <EmptyState message={t("tokenUsage.noData")} />
          ) : (
            <DataTables byModelData={byModelData} byDateData={byDateData} />
          ))}
      </div>
    </div>
  );
}

export default TokenUsagePage;
