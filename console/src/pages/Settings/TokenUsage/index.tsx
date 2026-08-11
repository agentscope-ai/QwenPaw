import { useCallback, useEffect, useMemo, useState } from "react";
import { DatePicker } from "antd";
import { useTranslation } from "react-i18next";
import dayjs, { type Dayjs } from "dayjs";
import { useTheme } from "../../../contexts/ThemeContext";
import api from "../../../api";
import type { TokenUsageRecord } from "../../../api/types/tokenUsage";
import { useAppMessage } from "../../../hooks/useAppMessage";
import { PageHeader } from "@/components/PageHeader";
import { useAgentStore } from "../../../stores/agentStore";
import {
  LoadingState,
  SummaryCards,
  ModelTrendChart,
  TokenTypeChart,
  LlmToolTrendChart,
  DataTables,
  EmptyState,
} from "./components";
import { useDataAggregation } from "./hooks/useDataAggregation";
import { useModelTrendConfig } from "./hooks/useModelTrendConfig";
import { useTokenTypeConfig } from "./hooks/useTokenTypeConfig";
import { useLlmToolTrendConfig } from "./hooks/useLlmToolTrendConfig";
import styles from "./index.module.less";

function TokenUsagePage() {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const { isDark } = useTheme();
  const { agents } = useAgentStore();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [records, setRecords] = useState<TokenUsageRecord[]>([]);
  const [dailyToolCalls, setDailyToolCalls] = useState<Record<string, number>>(
    {},
  );
  const [toolCallsLoadFailed, setToolCallsLoadFailed] = useState(false);
  const [startDate, setStartDate] = useState<Dayjs>(
    dayjs().subtract(30, "day"),
  );
  const [endDate, setEndDate] = useState<Dayjs>(dayjs());

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(false);
    setToolCallsLoadFailed(false);
    const params = {
      start_date: startDate.format("YYYY-MM-DD"),
      end_date: endDate.format("YYYY-MM-DD"),
    };
    try {
      const [detailsData, toolCallsResult] = await Promise.all([
        api.getTokenUsageDetails(params),
        api.getDailyToolCalls(params).then(
          (data) => ({ ok: true as const, data }),
          (err) => {
            console.error("Failed to load daily tool calls:", err);
            return { ok: false as const, data: {} as Record<string, number> };
          },
        ),
      ]);
      setRecords(detailsData);
      setDailyToolCalls(toolCallsResult.data);
      if (!toolCallsResult.ok) {
        setToolCallsLoadFailed(true);
        message.warning(t("tokenUsage.toolCallsLoadFailed"));
      }
    } catch (err) {
      console.error("Failed to load token usage:", err);
      message.error(t("tokenUsage.loadFailed"));
      setRecords([]);
      setDailyToolCalls({});
      setToolCallsLoadFailed(false);
      setError(true);
    } finally {
      setLoading(false);
    }
  }, [startDate, endDate, message, t]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleDateChange = (dates: [Dayjs | null, Dayjs | null] | null) => {
    if (!dates || !dates[0] || !dates[1]) return;
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

  const llmToolTrendConfig = useLlmToolTrendConfig({
    byDate: aggregatedData?.by_date ?? null,
    dailyToolCalls,
    startDate,
    endDate,
    isDark,
    toolCallsUnavailable: toolCallsLoadFailed,
  });

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

  const byAgentData = useMemo(() => {
    if (!aggregatedData?.by_agent) return [];
    const nameById = new Map(agents.map((a) => [a.id, a.name]));
    return Object.entries(aggregatedData.by_agent).map(([key, stats]) => ({
      key,
      agent:
        nameById.get(stats.agent_id) ||
        stats.agent_id ||
        t("tokenUsage.unknownAgent"),
      prompt_tokens: stats.prompt_tokens,
      completion_tokens: stats.completion_tokens,
      call_count: stats.call_count,
    }));
  }, [aggregatedData?.by_agent, agents, t]);

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

  if (error && records.length === 0) {
    return (
      <div className={styles.container}>
        {pageHeader}
        <LoadingState
          message={t("tokenUsage.loadFailed")}
          error
          onRetry={fetchData}
        />
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
              current && current.isAfter(dayjs(), "day")
            }
          />
        </div>

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

        {llmToolTrendConfig && (
          <LlmToolTrendChart chartConfig={llmToolTrendConfig} />
        )}

        {byModelData.length === 0 &&
        byDateData.length === 0 &&
        byAgentData.length === 0 &&
        !llmToolTrendConfig ? (
          <EmptyState message={t("tokenUsage.noData")} />
        ) : (
          <DataTables
            byModelData={byModelData}
            byDateData={byDateData}
            byAgentData={byAgentData}
          />
        )}
      </div>
    </div>
  );
}

export default TokenUsagePage;
