import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import dayjs, { type Dayjs } from "dayjs";
import api from "../../../api";
import type { TokenUsageRecord } from "../../../api/types/tokenUsage";
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
import { useDataAggregation } from "./hooks/useDataAggregation";
import { useModelTrendConfig } from "./hooks/useModelTrendConfig";
import { useTokenTypeConfig } from "./hooks/useTokenTypeConfig";
import styles from "./index.module.less";

function TokenUsagePage() {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [records, setRecords] = useState<TokenUsageRecord[]>([]);
  const [startDate, setStartDate] = useState<Dayjs>(
    dayjs().subtract(30, "day"),
  );
  const [endDate, setEndDate] = useState<Dayjs>(dayjs());

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      const detailsData = await api.getTokenUsageDetails({
        start_date: startDate.format("YYYY-MM-DD"),
        end_date: endDate.format("YYYY-MM-DD"),
      });
      setRecords(detailsData);
    } catch (err) {
      console.error("Failed to load token usage:", err);
      message.error(t("tokenUsage.loadFailed"));
      setRecords([]);
      setError(true);
    } finally {
      setLoading(false);
    }
  }, [startDate, endDate, message, t]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleStartDateChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const d = dayjs(e.target.value);
    if (d.isValid() && !d.isAfter(endDate, "day")) setStartDate(d);
  };

  const handleEndDateChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const d = dayjs(e.target.value);
    const today = dayjs();
    if (
      d.isValid() &&
      !d.isAfter(today, "day") &&
      !d.isBefore(startDate, "day")
    ) {
      setEndDate(d);
    }
  };

  const aggregatedData = useDataAggregation(records);

  const modelTrendConfig = useModelTrendConfig({
    byDateModel: aggregatedData?.by_date_model ?? null,
    startDate,
    endDate,
    isDark: false,
  });

  const tokenTypeConfig = useTokenTypeConfig({
    byDate: aggregatedData?.by_date ?? null,
    startDate,
    endDate,
    isDark: false,
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
        <div className={`${styles.toolbar} flex items-center gap-2`}>
          <input
            type="date"
            value={startDate.format("YYYY-MM-DD")}
            max={endDate.format("YYYY-MM-DD")}
            onChange={handleStartDateChange}
            className="h-8 rounded-md border px-2 text-sm bg-background"
          />
          <span className="text-sm text-muted-foreground">—</span>
          <input
            type="date"
            value={endDate.format("YYYY-MM-DD")}
            min={startDate.format("YYYY-MM-DD")}
            max={dayjs().format("YYYY-MM-DD")}
            onChange={handleEndDateChange}
            className="h-8 rounded-md border px-2 text-sm bg-background"
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

        {byModelData.length === 0 && byDateData.length === 0 ? (
          <EmptyState message={t("tokenUsage.noData")} />
        ) : (
          <DataTables byModelData={byModelData} byDateData={byDateData} />
        )}
      </div>
    </div>
  );
}

export default TokenUsagePage;
