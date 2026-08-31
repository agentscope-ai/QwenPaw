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
import { PageHeader } from "@/components/PageHeader";
import {
  LoadingState,
  SummaryCards,
  ModelTrendChart,
  TokenTypeChart,
  DataTables,
  EmptyState,
} from "./components";
import { useAgentStore } from "../../../stores/agentStore";
import { getAgentDisplayName } from "../../../utils/agentDisplayName";
import { useDataAggregation } from "./hooks/useDataAggregation";
import { lineChartChrome } from "./hooks/lineChartChrome";
import { useModelTrendConfig } from "./hooks/useModelTrendConfig";
import { useTokenTypeConfig } from "./hooks/useTokenTypeConfig";
import { buildByDateRows } from "./tokenUsageRows";
import styles from "./index.module.less";

function TokenUsagePage() {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const { isDark } = useTheme();
  const agents = useAgentStore((state) => state.agents);
  const agentsById = useMemo(
    () => new Map(agents.map((agent) => [agent.id, agent])),
    [agents],
  );
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
  const detailsFetchIdRef = useRef(0);
  const trendFetchIdRef = useRef(0);
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
        if (fetchId !== trendFetchIdRef.current) return;
        setLlmToolDays(data);
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") {
          return;
        }
        console.error("Failed to load llm/tool trend:", err);
        if (fetchId !== trendFetchIdRef.current) return;
        setLlmToolDays(null);
        setTrendError(true);
      } finally {
        if (fetchId === trendFetchIdRef.current) {
          setTrendLoading(false);
        }
      }
    },
    [dateRange],
  );

  const fetchData = useCallback(async () => {
    const detailsId = ++detailsFetchIdRef.current;
    const trendId = ++trendFetchIdRef.current;
    setLoading(true);
    setError(false);
    void fetchTrend(trendId);
    try {
      const detailsData = await api.getTokenUsageDetails(dateRange);
      if (detailsId !== detailsFetchIdRef.current) return;
      setRecords(detailsData);
    } catch (err) {
      console.error("Failed to load token usage:", err);
      if (detailsId !== detailsFetchIdRef.current) return;
      message.error(t("tokenUsage.loadFailed"));
      setRecords([]);
      setError(true);
    } finally {
      if (detailsId === detailsFetchIdRef.current) {
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
      ...lineChartChrome({
        isDark,
        tickCount: Math.min(10, Math.max(3, days.length)),
        startDate,
        endDate,
        seriesField: "type",
        colors: ["#722ed1", "#13c2c2"],
      }),
    };
  }, [llmToolDays, startDate, endDate, isDark, t]);

  const byModelData = useMemo(() => {
    if (!aggregatedData?.by_model) return [];
    return Object.entries(aggregatedData.by_model).map(([key, stats]) => ({
      key,
      model: key,
      prompt_tokens: stats.prompt_tokens,
      completion_tokens: stats.completion_tokens,
      cache_read_tokens: stats.cache_read_tokens,
      cache_eligible_input_tokens: stats.cache_eligible_input_tokens,
      call_count: stats.call_count,
    }));
  }, [aggregatedData?.by_model]);

  const byDateData = useMemo(
    () => buildByDateRows(aggregatedData?.by_date),
    [aggregatedData?.by_date],
  );

  const byAgentData = useMemo(() => {
    if (!aggregatedData?.by_agent) return [];
    return Object.entries(aggregatedData.by_agent)
      .map(([key, stats]) => {
        const agentId = stats.agent_id;
        let agent: string;
        if (!agentId) {
          agent = t("tokenUsage.unattributed");
        } else {
          const profile = agentsById.get(agentId);
          agent = profile ? getAgentDisplayName(profile, t) : agentId;
        }
        return {
          key,
          agent,
          prompt_tokens: stats.prompt_tokens,
          completion_tokens: stats.completion_tokens,
          cache_read_tokens: stats.cache_read_tokens,
          cache_eligible_input_tokens: stats.cache_eligible_input_tokens,
          call_count: stats.call_count,
        };
      })
      .sort(
        (a, b) =>
          b.prompt_tokens +
          b.completion_tokens -
          (a.prompt_tokens + a.completion_tokens),
      );
  }, [aggregatedData?.by_agent, agentsById, t]);

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
            disabledDate={(current: Dayjs, info?: { from?: Dayjs }) => {
              if (!current || current.isAfter(dayjs(), "day")) return true;
              if (info?.from) {
                return Math.abs(current.diff(info.from, "day")) >= 365;
              }
              return false;
            }}
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
                totalCacheReadTokens={aggregatedData.total_cache_read_tokens}
                totalCacheEligibleInputTokens={
                  aggregatedData.total_cache_eligible_input_tokens
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
                void fetchTrend(++trendFetchIdRef.current);
              }}
            />
          ) : (llmToolDays ?? []).every(
              (d) => d.agent_llm_calls === 0 && d.tool_calls === 0,
            ) ? (
            <EmptyState message={t("tokenUsage.noData")} />
          ) : (
            <Line {...llmToolConfig} />
          )}
        </Card>

        {!error &&
          (tablesEmpty ? (
            <EmptyState message={t("tokenUsage.noData")} />
          ) : (
            <DataTables
              byModelData={byModelData}
              byDateData={byDateData}
              byAgentData={byAgentData}
            />
          ))}
      </div>
    </div>
  );
}

export default TokenUsagePage;
