import { useEffect, useMemo, useState } from "react";
import { Card, Empty, Button } from "@agentscope-ai/design";
import { Spin, Tooltip } from "antd";
import { DatePicker } from "antd";
import type { Dayjs } from "dayjs";
import dayjs from "dayjs";
import { useTranslation } from "react-i18next";
import { Column, Pie } from "@ant-design/plots";
import api from "../../../api";
import type { AgentStatsSummary } from "../../../api/types/agentStats";
import { PageHeader } from "@/components/PageHeader";
import { useAppMessage } from "../../../hooks/useAppMessage";
import { formatCompact } from "../../../utils/formatNumber";
import { formatPercent } from "../../../utils/cacheUsage";
import { useTheme } from "../../../contexts/ThemeContext";
import { useAgentStore } from "../../../stores/agentStore";
import { getAgentDisplayName } from "../../../utils/agentDisplayName";
import { SummaryCard } from "./SummaryCard";
import styles from "./index.module.less";

type ChartDataItem = {
  date: string;
  chats: number;
  activeSessions: number;
  userMessages: number;
  assistantMessages: number;
  toolCalls: number;
  agentPromptTokens: number;
  agentCompletionTokens: number;
  agentCacheReadTokens: number;
  agentLlmCalls: number;
};

interface ColumnSeries {
  key: keyof ChartDataItem;
  label: string;
}

function formatDateLabel(dateStr: string, crossesYear: boolean): string {
  const date = dayjs(dateStr);
  return crossesYear ? date.format("YY/MM-DD") : date.format("MM-DD");
}

function getColumnConfig(
  chartData: ChartDataItem[],
  series: ColumnSeries[],
  colors: string[],
  isDarkMode: boolean,
  crossesYear: boolean,
  options?: {
    yAxisFormatter?: (v: number) => string;
    tooltipFormatter?: (v: number) => string;
  },
) {
  const config: Record<string, unknown> = {
    data: chartData.flatMap((d) =>
      series.map((s) => ({
        date: d.date,
        value: d[s.key],
        category: s.label,
      })),
    ),
    xField: "date",
    yField: "value",
    seriesField: "category",
    colorField: "category",
    isGroup: true,
    height: 150,
    autoFit: true,
    theme: isDarkMode ? "dark" : "light",
    legend: { position: "bottom" as const },
    meta: {
      color: { range: colors },
    },
    axis: {
      x: {
        labelFormatter: (d: string) => formatDateLabel(d, crossesYear),
      },
      ...(options?.yAxisFormatter
        ? { y: { labelFormatter: options.yAxisFormatter } }
        : {}),
    },
    tooltip: {
      title: "date",
      items: [
        (datum: { date: string; value: number; category: string }) => ({
          name: datum.category,
          value: options?.tooltipFormatter
            ? options.tooltipFormatter(datum.value)
            : datum.value?.toLocaleString(),
        }),
      ],
    },
  };

  return config;
}

function AgentStatsPage() {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const { isDark: isDarkMode } = useTheme();
  const { selectedAgent, agents } = useAgentStore();
  const selectedAgentInfo = agents.find((a) => a.id === selectedAgent);
  const agentName = selectedAgentInfo
    ? getAgentDisplayName(selectedAgentInfo, t)
    : selectedAgent;
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<AgentStatsSummary | null>(null);
  const [startDate, setStartDate] = useState<Dayjs>(dayjs().subtract(7, "day"));
  const [endDate, setEndDate] = useState<Dayjs>(dayjs());

  const fetchData = async (start: Dayjs, end: Dayjs) => {
    setLoading(true);
    setError(null);
    try {
      const summary = await api.getAgentStats({
        start_date: start.format("YYYY-MM-DD"),
        end_date: end.format("YYYY-MM-DD"),
      });
      setData(summary);
    } catch (e) {
      console.error("Failed to load agent statistics:", e);
      const msg = t("agentStats.loadFailed");
      message.error(msg);
      setError(msg);
      setData(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData(startDate, endDate);
  }, [selectedAgent]);

  const handleDateChange = (dates: [Dayjs | null, Dayjs | null] | null) => {
    const newStart = dates?.[0] || startDate;
    const newEnd = dates?.[1] || endDate;
    if (dates?.[0]) setStartDate(newStart);
    if (dates?.[1]) setEndDate(newEnd);
    if (dates?.[0] && dates?.[1]) {
      fetchData(newStart, newEnd);
    }
  };

  const crossesYear = useMemo(
    () => startDate.year() !== endDate.year(),
    [startDate, endDate],
  );

  const chartData = useMemo(() => {
    if (!data?.by_date) return [];
    return data.by_date.map((d) => ({
      date: d.date,
      chats: d.chats,
      activeSessions: d.active_sessions,
      userMessages: d.user_messages,
      assistantMessages: d.assistant_messages,
      toolCalls: d.tool_calls,
      agentPromptTokens: d.agent_prompt_tokens ?? 0,
      agentCompletionTokens: d.agent_completion_tokens ?? 0,
      agentCacheReadTokens: d.agent_cache_read_tokens,
      agentLlmCalls: d.agent_llm_calls ?? 0,
    }));
  }, [data?.by_date]);

  const hasData =
    data &&
    ((data.total_active_sessions ?? 0) > 0 ||
      (data.total_messages ?? 0) > 0 ||
      (data.total_tool_calls ?? 0) > 0 ||
      (data.agent_llm_calls ?? 0) > 0);

  const messageColumnConfig = useMemo(
    () =>
      getColumnConfig(
        chartData,
        [
          { key: "userMessages", label: t("agentStats.userMessages") },
          {
            key: "assistantMessages",
            label: t("agentStats.assistantMessages"),
          },
        ],
        ["#3b82f6", "#f97316"],
        isDarkMode,
        crossesYear,
      ),
    [chartData, t, isDarkMode, crossesYear],
  );

  const chatColumnConfig = useMemo(
    () =>
      getColumnConfig(
        chartData,
        [
          { key: "chats", label: t("agentStats.newSessions") },
          { key: "activeSessions", label: t("agentStats.activeSessions") },
        ],
        ["#ff7f16", "#3b82f6"],
        isDarkMode,
        crossesYear,
      ),
    [chartData, t, isDarkMode, crossesYear],
  );

  const agentTokenColumnConfig = useMemo(() => {
    const inputLabel = t("agentStats.totalInputTokens");
    const outputLabel = t("agentStats.completionTokens");
    const cacheHitLabel = t("tokenUsage.cacheRead");
    const tokenData = chartData.flatMap((day) => {
      const cacheHit = Math.min(
        Math.max(day.agentCacheReadTokens, 0),
        day.agentPromptTokens,
      );
      return [
        {
          date: day.date,
          value: cacheHit,
          displayValue: cacheHit,
          barType: inputLabel,
          segment: cacheHitLabel,
        },
        {
          date: day.date,
          value: Math.max(day.agentPromptTokens - cacheHit, 0),
          displayValue: day.agentPromptTokens,
          barType: inputLabel,
          segment: inputLabel,
        },
        {
          date: day.date,
          value: day.agentCompletionTokens,
          displayValue: day.agentCompletionTokens,
          barType: outputLabel,
          segment: outputLabel,
        },
      ];
    });

    return {
      data: tokenData,
      xField: "date",
      yField: "value",
      seriesField: "barType",
      colorField: "segment",
      stack: {
        groupBy: ["x", "series"],
        series: false,
      },
      height: 150,
      autoFit: true,
      theme: isDarkMode ? "dark" : "light",
      legend: { position: "bottom" as const },
      scale: {
        color: {
          domain: [inputLabel, cacheHitLabel, outputLabel],
          range: ["#b8b2c2", "#0f9f8f", "#64748b"],
        },
      },
      axis: {
        x: {
          labelFormatter: (date: string) => formatDateLabel(date, crossesYear),
        },
        y: { labelFormatter: formatCompact },
      },
      tooltip: {
        title: "date",
        items: [
          (datum: { displayValue: number; segment: string }) => ({
            name: datum.segment,
            value: formatCompact(datum.displayValue),
          }),
        ],
      },
    };
  }, [chartData, t, isDarkMode, crossesYear]);

  const llmToolColumnConfig = useMemo(
    () =>
      getColumnConfig(
        chartData,
        [
          {
            key: "agentLlmCalls",
            label: t("agentStats.currentAgentLlmCalls"),
          },
          { key: "toolCalls", label: t("agentStats.toolCalls") },
        ],
        ["#ec4899", "#14b8a6"],
        isDarkMode,
        crossesYear,
      ),
    [chartData, t, isDarkMode, crossesYear],
  );

  const pieCommon = useMemo(
    () => ({
      height: 280,
      autoFit: true,
      angleField: "value" as const,
      colorField: "channel" as const,
      color: ["#1890ff", "#52c41a", "#faad14", "#f5222d"],
      padding: 40,
      label: {
        text: (d: { channel: string; value: number }) =>
          `${d.channel}: ${d.value}`,
        position: "spider" as const,
        connector: true,
        transform: [{ type: "overlapDodgeY" }, { type: "exceedAdjust" }],
      },
      legend: { position: "bottom" as const },
      theme: isDarkMode ? "dark" : "light",
    }),
    [isDarkMode],
  );

  const chatPieConfig = useMemo(() => {
    if (!data?.channel_stats?.length) return null;
    return {
      ...pieCommon,
      data: data.channel_stats.map((item) => ({
        channel: item.channel,
        value: Number(item.session_count),
      })),
    };
  }, [data?.channel_stats, pieCommon]);

  const messagePieConfig = useMemo(() => {
    if (!data?.channel_stats?.length) return null;
    return {
      ...pieCommon,
      data: data.channel_stats.map((item) => ({
        channel: item.channel,
        value: Number(item.total_messages),
      })),
    };
  }, [data?.channel_stats, pieCommon]);

  return (
    <div className={styles.page}>
      <PageHeader parent={t("nav.settings")} current={t("agentStats.title")} />
      <div className={styles.content}>
        {error && !data ? (
          <div className={styles.error}>
            <p>{error}</p>
            <Button
              type="primary"
              onClick={() => fetchData(startDate, endDate)}
            >
              {t("agentStats.retry")}
            </Button>
          </div>
        ) : loading && !data ? (
          <div className={styles.loading}>
            <Spin size="large" />
            <p>{t("common.loading")}</p>
          </div>
        ) : (
          <>
            <div className={styles.filters}>
              <DatePicker.RangePicker
                value={[startDate, endDate]}
                onChange={handleDateChange}
                className={styles.datePicker}
                disabled={loading}
                disabledDate={(current) =>
                  current && current.isAfter(dayjs(), "day")
                }
              />
              {loading && <Spin size="small" />}
            </div>

            {hasData ? (
              <>
                <div className={styles.currentAgentSectionTitle}>
                  {agentName}
                </div>
                <div className={styles.summaryCards}>
                  <SummaryCard
                    value={data.total_active_sessions}
                    label={t("agentStats.totalSessions")}
                    tooltip={t("agentStats.totalSessionsTooltip")}
                  />
                  <SummaryCard
                    value={data.total_messages}
                    label={t("agentStats.totalMessages")}
                    tooltip={t("agentStats.totalMessagesTooltip")}
                  />
                  <SummaryCard
                    value={data.agent_prompt_tokens ?? 0}
                    label={t("agentStats.promptTokens")}
                    tooltip={t("agentStats.currentAgentPromptTokensTooltip")}
                  />
                  <SummaryCard
                    value={data.agent_cache_hit_rate}
                    label={t("tokenUsage.cacheHitRate")}
                    tooltip={t("agentStats.currentAgentCacheHitRateTooltip")}
                    formatValue={(value) => formatPercent(value ?? null)}
                  />
                  <SummaryCard
                    value={data.agent_completion_tokens ?? 0}
                    label={t("agentStats.completionTokens")}
                    tooltip={t(
                      "agentStats.currentAgentCompletionTokensTooltip",
                    )}
                  />
                  <SummaryCard
                    value={data.agent_llm_calls ?? 0}
                    label={t("agentStats.currentAgentLlmCalls")}
                    tooltip={t("agentStats.currentAgentLlmCallsTooltip")}
                  />
                  <SummaryCard
                    value={data.total_tool_calls}
                    label={t("agentStats.toolCalls")}
                    tooltip={t("agentStats.toolCallsTooltip")}
                  />
                </div>

                <div className={styles.trendRow}>
                  <Card
                    className={styles.chartCard}
                    title={
                      <Tooltip
                        title={t("agentStats.messageTrendTooltip")}
                        placement="bottom"
                      >
                        <span className={styles.chartTitle}>
                          {t("agentStats.messageTrend")}
                        </span>
                      </Tooltip>
                    }
                  >
                    <div className={styles.chartContainerShort}>
                      <Column {...messageColumnConfig} />
                    </div>
                  </Card>

                  <Card
                    className={styles.chartCard}
                    title={
                      <Tooltip
                        title={t("agentStats.sessionTrendTooltip")}
                        placement="bottom"
                      >
                        <span className={styles.chartTitle}>
                          {t("agentStats.sessionTrend")}
                        </span>
                      </Tooltip>
                    }
                  >
                    <div className={styles.chartContainerShort}>
                      <Column {...chatColumnConfig} />
                    </div>
                  </Card>

                  <Card
                    className={styles.chartCard}
                    title={
                      <Tooltip
                        title={t("agentStats.currentAgentTokenTrendTooltip")}
                        placement="bottom"
                      >
                        <span className={styles.chartTitle}>
                          {t("agentStats.tokenTrend")}
                        </span>
                      </Tooltip>
                    }
                  >
                    <div className={styles.chartContainerShort}>
                      <Column {...agentTokenColumnConfig} />
                    </div>
                  </Card>

                  <Card
                    className={styles.chartCard}
                    title={
                      <Tooltip
                        title={t("agentStats.llmAndToolTrendTooltip")}
                        placement="bottom"
                      >
                        <span className={styles.chartTitle}>
                          {t("agentStats.llmAndToolTrend")}
                        </span>
                      </Tooltip>
                    }
                  >
                    <div className={styles.chartContainerShort}>
                      <Column {...llmToolColumnConfig} />
                    </div>
                  </Card>
                </div>

                {(chatPieConfig || messagePieConfig) && (
                  <div className={styles.pieChartsRow}>
                    {chatPieConfig && (
                      <Card
                        className={styles.chartCard}
                        title={
                          <Tooltip
                            title={t("agentStats.sessionsByChannelTooltip")}
                            placement="bottom"
                          >
                            <span className={styles.chartTitle}>
                              {t("agentStats.sessionsByChannel")}
                            </span>
                          </Tooltip>
                        }
                      >
                        <div className={styles.pieChartContainer}>
                          <Pie {...chatPieConfig} />
                        </div>
                      </Card>
                    )}

                    {messagePieConfig && (
                      <Card
                        className={styles.chartCard}
                        title={
                          <Tooltip
                            title={t("agentStats.messagesByChannelTooltip")}
                            placement="bottom"
                          >
                            <span className={styles.chartTitle}>
                              {t("agentStats.messagesByChannel")}
                            </span>
                          </Tooltip>
                        }
                      >
                        <div className={styles.pieChartContainer}>
                          <Pie {...messagePieConfig} />
                        </div>
                      </Card>
                    )}
                  </div>
                )}
              </>
            ) : (
              <Empty
                description={t("agentStats.noData")}
                style={{ marginTop: 48 }}
              />
            )}
          </>
        )}
      </div>
    </div>
  );
}

export default AgentStatsPage;
