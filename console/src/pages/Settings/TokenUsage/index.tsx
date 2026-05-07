import { useEffect, useMemo, useState } from "react";
import { Button, DatePicker } from "antd";
import { useTranslation } from "react-i18next";
import dayjs, { Dayjs } from "dayjs";
import { useTheme } from "../../../contexts/ThemeContext";
import api from "../../../api";
import type { TokenUsageRecord } from "../../../api/types/tokenUsage";
import { useAppMessage } from "../../../hooks/useAppMessage";
import { PageHeader } from "@/components/PageHeader";
import {
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
  const { isDark } = useTheme();
  const [loading, setLoading] = useState(true);
  const [records, setRecords] = useState<TokenUsageRecord[]>([]);
  const [startDate, setStartDate] = useState<Dayjs>(
    dayjs().subtract(30, "day"),
  );
  const [endDate, setEndDate] = useState<Dayjs>(dayjs());
  const [selectedModels, setSelectedModels] = useState<string[]>([]);
  const [selectedTokenTypes, setSelectedTokenTypes] = useState<string[]>([]);

  const fetchData = async () => {
    setLoading(true);
    try {
      const detailsData = await api.getTokenUsageDetails({
        start_date: startDate.format("YYYY-MM-DD"),
        end_date: endDate.format("YYYY-MM-DD"),
      });

      setRecords(detailsData);
    } catch (e) {
      console.error("Failed to load token usage:", e);
      const msg = t("tokenUsage.loadFailed");
      message.error(msg);
      setRecords([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  const handleDateChange = (dates: [Dayjs | null, Dayjs | null] | null) => {
    if (!dates || !dates[0] || !dates[1]) return;
    setStartDate(dates[0]);
    setEndDate(dates[1]);
  };

  const handleRefresh = async () => {
    await fetchData();
  };

  // Use hooks for data aggregation and chart configs
  const aggregatedData = useDataAggregation(records);
  const modelTrendConfig = useModelTrendConfig({
    byDateModel: aggregatedData?.by_date_model || null,
    startDate,
    endDate,
    selectedModels,
    isDark,
  });
  const tokenTypeConfig = useTokenTypeConfig({
    byDate: aggregatedData?.by_date || null,
    startDate,
    endDate,
    selectedTokenTypes,
    isDark,
  });

  // Initialize with all models and types selected when data loads
  useEffect(() => {
    if (aggregatedData) {
      const allModels = Object.keys(aggregatedData.by_model || {});
      const allTypes = ["Prompt Tokens", "Completion Tokens", "Total Tokens"];

      // Use functional updates to avoid dependency issues
      setSelectedModels((prev) =>
        prev.length === 0 || prev.length !== allModels.length
          ? allModels
          : prev,
      );
      setSelectedTokenTypes((prev) =>
        prev.length === 0 || prev.length !== allTypes.length ? allTypes : prev,
      );
    }
  }, [aggregatedData]);

  // Prepare table data
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
    const data = Object.entries(aggregatedData.by_date).map(
      ([date, stats]) => ({
        key: date,
        date,
        prompt_tokens: stats.prompt_tokens,
        completion_tokens: stats.completion_tokens,
        call_count: stats.call_count,
      }),
    );
    return data.sort((a, b) => b.date.localeCompare(a.date));
  }, [aggregatedData?.by_date]);

  if (loading) {
    return (
      <div className={styles.container}>
        <PageHeader
          parent={t("nav.settings")}
          current={t("tokenUsage.title")}
        />
        <div className={styles.loading}>Loading...</div>
      </div>
    );
  }

  return (
    <div className={styles.container}>
      <PageHeader parent={t("nav.settings")} current={t("tokenUsage.title")} />

      <div className={styles.content}>
        {/* Date Range Picker and Refresh Button */}
        <div className={styles.toolbar}>
          <DatePicker.RangePicker
            value={[startDate, endDate]}
            onChange={handleDateChange}
          />
          <Button onClick={handleRefresh}>
            {t("tokenUsage.refresh", "Refresh")}
          </Button>
        </div>

        {/* Summary Cards */}
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

        {/* Charts */}
        <div className={styles.trendRow}>
          <ModelTrendChart
            chartConfig={modelTrendConfig}
            selectedModels={selectedModels}
            allModels={Object.keys(aggregatedData?.by_model || {})}
            onModelChange={setSelectedModels}
          />
          <TokenTypeChart
            chartConfig={tokenTypeConfig}
            selectedTokenTypes={selectedTokenTypes}
            onTokenTypeChange={setSelectedTokenTypes}
          />
        </div>

        {/* Tables */}
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
