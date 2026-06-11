import { useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { Loader2, PackageOpen } from "lucide-react";
import type { Dayjs } from "dayjs";
import dayjs from "dayjs";
import { useTranslation } from "react-i18next";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip as RechartTooltip,
  Legend,
  PieChart,
  Pie,
  Cell,
} from "recharts";
import api from "../../../api";
import type { AgentStatsSummary } from "../../../api/types/agentStats";
import { PageHeader } from "@/components/PageHeader";
import { useAppMessage } from "../../../hooks/useAppMessage";
import { formatCompact } from "../../../utils/formatNumber";
import { useAgentStore } from "../../../stores/agentStore";
import { SummaryCard } from "./SummaryCard";
import styles from "./index.module.less";

type ChartDataItem = {
  date: string;
  displayDate: string;
  chats: number;
  activeSessions: number;
  userMessages: number;
  assistantMessages: number;
  totalMessages: number;
  promptTokens: number;
  completionTokens: number;
  llmCalls: number;
  toolCalls: number;
};

interface BarSeriesConfig {
  dataKey: keyof ChartDataItem;
  label: string;
  color: string;
}

function formatDateLabel(dateStr: string, crossesYear: boolean): string {
  const date = dayjs(dateStr);
  return crossesYear ? date.format("YY/MM-DD") : date.format("MM-DD");
}

const PIE_COLORS = ["#1890ff", "#52c41a", "#faad14", "#f5222d"];

interface TrendCardProps {
  title: string;
  tooltip: string;
  data: ChartDataItem[];
  series: BarSeriesConfig[];
  crossesYear: boolean;
  yFormatter?: (v: number) => string;
}

function TrendCard({
  title,
  tooltip,
  data,
  series,
  crossesYear,
  yFormatter,
}: TrendCardProps) {
  const barData = data.map((d) => {
    const row: Record<string, string | number> = {
      date: formatDateLabel(d.date, crossesYear),
    };
    series.forEach((s) => {
      row[s.label] = d[s.dataKey];
    });
    return row;
  });

  return (
    <div className={`${styles.chartCard} border rounded-lg p-4`}>
      <Tooltip>
        <TooltipTrigger asChild>
          <div
            className={`${styles.chartTitle} cursor-default text-sm font-semibold mb-2`}
          >
            {title}
          </div>
        </TooltipTrigger>
        <TooltipContent side="bottom">{tooltip}</TooltipContent>
      </Tooltip>
      <div className={styles.chartContainerShort}>
        <ResponsiveContainer width="100%" height={150}>
          <BarChart
            data={barData}
            margin={{ top: 4, right: 8, left: 0, bottom: 0 }}
          >
            <CartesianGrid
              strokeDasharray="3 3"
              stroke="rgba(128,128,128,0.15)"
            />
            <XAxis dataKey="date" tick={{ fontSize: 10 }} />
            <YAxis
              tick={{ fontSize: 10 }}
              width={40}
              tickFormatter={yFormatter ?? ((v: number) => v.toString())}
            />
            <RechartTooltip
              formatter={(value: number, name: string) => [
                yFormatter ? yFormatter(value) : value.toLocaleString(),
                name,
              ]}
            />
            <Legend wrapperStyle={{ fontSize: 10 }} />
            {series.map((s) => (
              <Bar key={s.label} dataKey={s.label} fill={s.color} />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

interface PieCardProps {
  title: string;
  tooltip: string;
  data: Array<{ channel: string; value: number }>;
}

function PieCard({ title, tooltip, data }: PieCardProps) {
  return (
    <div className={`${styles.chartCard} border rounded-lg p-4`}>
      <Tooltip>
        <TooltipTrigger asChild>
          <div
            className={`${styles.chartTitle} cursor-default text-sm font-semibold mb-2`}
          >
            {title}
          </div>
        </TooltipTrigger>
        <TooltipContent side="bottom">{tooltip}</TooltipContent>
      </Tooltip>
      <div className={styles.pieChartContainer}>
        <ResponsiveContainer width="100%" height={280}>
          <PieChart>
            <Pie
              data={data}
              dataKey="value"
              nameKey="channel"
              cx="50%"
              cy="50%"
              outerRadius={90}
              label={({ channel, value }: { channel: string; value: number }) =>
                `${channel}: ${value}`
              }
            >
              {data.map((_entry, idx) => (
                <Cell key={idx} fill={PIE_COLORS[idx % PIE_COLORS.length]} />
              ))}
            </Pie>
            <RechartTooltip />
            <Legend />
          </PieChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function AgentStatsPage() {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const { selectedAgent } = useAgentStore();
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

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    fetchData(startDate, endDate);
  }, [selectedAgent]);

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

  const handleApplyDates = () => fetchData(startDate, endDate);

  const crossesYear = useMemo(
    () => startDate.year() !== endDate.year(),
    [startDate, endDate],
  );

  const chartData = useMemo((): ChartDataItem[] => {
    if (!data?.by_date) return [];
    return data.by_date.map((d) => ({
      date: d.date,
      displayDate: dayjs(d.date).format("MM-DD"),
      chats: d.chats,
      activeSessions: d.active_sessions,
      userMessages: d.user_messages,
      assistantMessages: d.assistant_messages,
      totalMessages: d.total_messages,
      promptTokens: d.prompt_tokens,
      completionTokens: d.completion_tokens,
      llmCalls: d.llm_calls,
      toolCalls: d.tool_calls,
    }));
  }, [data?.by_date]);

  const hasData =
    data &&
    ((data.total_active_sessions ?? 0) > 0 ||
      (data.total_messages ?? 0) > 0 ||
      (data.total_llm_calls ?? 0) > 0 ||
      (data.total_tool_calls ?? 0) > 0);

  const chatPieData = useMemo(
    () =>
      data?.channel_stats?.map((item) => ({
        channel: item.channel,
        value: Number(item.session_count),
      })) ?? null,
    [data?.channel_stats],
  );

  const messagePieData = useMemo(
    () =>
      data?.channel_stats?.map((item) => ({
        channel: item.channel,
        value: Number(item.total_messages),
      })) ?? null,
    [data?.channel_stats],
  );

  return (
    <div className={styles.page}>
      <PageHeader parent={t("nav.settings")} current={t("agentStats.title")} />
      <div className={styles.content}>
        {error && !data ? (
          <div className={styles.error}>
            <p>{error}</p>
            <Button onClick={() => fetchData(startDate, endDate)}>
              {t("agentStats.retry")}
            </Button>
          </div>
        ) : loading && !data ? (
          <div className={styles.loading}>
            <Loader2 className="animate-spin" size={32} />
            <p>{t("common.loading")}</p>
          </div>
        ) : (
          <>
            <div className={`${styles.filters} flex items-center gap-2`}>
              <input
                type="date"
                value={startDate.format("YYYY-MM-DD")}
                max={endDate.format("YYYY-MM-DD")}
                onChange={handleStartDateChange}
                disabled={loading}
                className="h-8 rounded-md border px-2 text-sm bg-background disabled:opacity-50"
              />
              <span className="text-sm text-muted-foreground">—</span>
              <input
                type="date"
                value={endDate.format("YYYY-MM-DD")}
                min={startDate.format("YYYY-MM-DD")}
                max={dayjs().format("YYYY-MM-DD")}
                onChange={handleEndDateChange}
                disabled={loading}
                className="h-8 rounded-md border px-2 text-sm bg-background disabled:opacity-50"
              />
              <Button
                variant="outline"
                size="sm"
                onClick={handleApplyDates}
                disabled={loading}
              >
                {loading ? (
                  <Loader2 size={12} className="animate-spin" />
                ) : (
                  t("common.apply", "Apply")
                )}
              </Button>
            </div>

            {hasData ? (
              <>
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
                    value={data.total_prompt_tokens}
                    label={t("agentStats.promptTokens")}
                    tooltip={t("agentStats.promptTokensTooltip")}
                  />
                  <SummaryCard
                    value={data.total_completion_tokens}
                    label={t("agentStats.completionTokens")}
                    tooltip={t("agentStats.completionTokensTooltip")}
                  />
                  <SummaryCard
                    value={data.total_llm_calls}
                    label={t("agentStats.llmCalls")}
                    tooltip={t("agentStats.llmCallsTooltip")}
                  />
                  <SummaryCard
                    value={data.total_tool_calls}
                    label={t("agentStats.toolCalls")}
                    tooltip={t("agentStats.toolCallsTooltip")}
                  />
                </div>

                <div className={styles.trendRow}>
                  <TrendCard
                    title={t("agentStats.messageTrend")}
                    tooltip={t("agentStats.messageTrendTooltip")}
                    data={chartData}
                    series={[
                      {
                        dataKey: "userMessages",
                        label: t("agentStats.userMessages"),
                        color: "#3b82f6",
                      },
                      {
                        dataKey: "assistantMessages",
                        label: t("agentStats.assistantMessages"),
                        color: "#5b4b8a",
                      },
                    ]}
                    crossesYear={crossesYear}
                  />
                  <TrendCard
                    title={t("agentStats.sessionTrend")}
                    tooltip={t("agentStats.sessionTrendTooltip")}
                    data={chartData}
                    series={[
                      {
                        dataKey: "chats",
                        label: t("agentStats.newSessions"),
                        color: "#5b4b8a",
                      },
                      {
                        dataKey: "activeSessions",
                        label: t("agentStats.activeSessions"),
                        color: "#3b82f6",
                      },
                    ]}
                    crossesYear={crossesYear}
                  />
                  <TrendCard
                    title={t("agentStats.tokenTrend")}
                    tooltip={t("agentStats.tokenTrendTooltip")}
                    data={chartData}
                    series={[
                      {
                        dataKey: "promptTokens",
                        label: t("agentStats.promptTokens"),
                        color: "#8b5cf6",
                      },
                      {
                        dataKey: "completionTokens",
                        label: t("agentStats.completionTokens"),
                        color: "#10b981",
                      },
                    ]}
                    crossesYear={crossesYear}
                    yFormatter={formatCompact}
                  />
                  <TrendCard
                    title={t("agentStats.llmAndToolTrend")}
                    tooltip={t("agentStats.llmAndToolTrendTooltip")}
                    data={chartData}
                    series={[
                      {
                        dataKey: "llmCalls",
                        label: t("agentStats.llmCalls"),
                        color: "#ec4899",
                      },
                      {
                        dataKey: "toolCalls",
                        label: t("agentStats.toolCalls"),
                        color: "#14b8a6",
                      },
                    ]}
                    crossesYear={crossesYear}
                  />
                </div>

                {chatPieData?.length || messagePieData?.length ? (
                  <div className={styles.pieChartsRow}>
                    {chatPieData?.length ? (
                      <PieCard
                        title={t("agentStats.sessionsByChannel")}
                        tooltip={t("agentStats.sessionsByChannelTooltip")}
                        data={chatPieData}
                      />
                    ) : null}
                    {messagePieData?.length ? (
                      <PieCard
                        title={t("agentStats.messagesByChannel")}
                        tooltip={t("agentStats.messagesByChannelTooltip")}
                        data={messagePieData}
                      />
                    ) : null}
                  </div>
                ) : null}
              </>
            ) : (
              <div className="flex flex-col items-center justify-center gap-3 mt-12 text-muted-foreground">
                <PackageOpen size={48} strokeWidth={1} />
                <span className="text-sm">{t("agentStats.noData")}</span>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

export default AgentStatsPage;
