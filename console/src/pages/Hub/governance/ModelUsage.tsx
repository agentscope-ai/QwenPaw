import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Button, DatePicker, Select, Tabs, Progress, Tooltip } from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs, { type Dayjs } from "dayjs";
import { RefreshCw, CircleHelp } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  governanceRequest as request,
  type UsageDetails,
} from "../../../api/modules/hubGovernance";
import { useTheme } from "../../../contexts/ThemeContext";
import { UsageSummaryCards } from "../../Settings/TokenUsage/components/SummaryCards";
import { UsageTable } from "../../Settings/TokenUsage/components/DataTables";
import {
  ModelTrendChart,
  LoadingState,
  EmptyState,
} from "../../Settings/TokenUsage/components";
import { lineChartChrome } from "../../Settings/TokenUsage/hooks/lineChartChrome";
import { formatTokens } from "./budgetUtils";
import { groupUsage, type UsageGroup } from "./usageAnalytics";
import styles from "./ModelUsage.module.less";

export default function ModelUsage() {
  const { t, i18n } = useTranslation();
  const { isDark } = useTheme();
  const [range, setRange] = useState<[Dayjs, Dayjs]>([
    dayjs().startOf("month"),
    dayjs(),
  ]);
  const [report, setReport] = useState<UsageDetails>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [model, setModel] = useState<string>();
  const [member, setMember] = useState<string>();
  const [dimension, setDimension] = useState<"user_id" | "model_id" | "date">(
    "user_id",
  );
  const sequence = useRef(0);
  const start = range[0].format("YYYY-MM-DD");
  const end = range[1].format("YYYY-MM-DD");
  const load = useCallback(async () => {
    const id = ++sequence.current;
    setLoading(true);
    setError(false);
    try {
      const value = await request<UsageDetails>(
        `admin/usage/details?start_date=${start}&end_date=${end}`,
      );
      if (id === sequence.current) setReport(value);
    } catch {
      if (id === sequence.current) setError(true);
    } finally {
      if (id === sequence.current) setLoading(false);
    }
  }, [start, end]);
  useEffect(() => {
    const pending = sequence;
    void load();
    return () => {
      pending.current++;
    };
  }, [load]);
  const rows = useMemo(
    () =>
      (report?.rows ?? []).filter(
        (row) =>
          (!model || row.model_id === model) &&
          (!member || row.user_id === member),
      ),
    [report, model, member],
  );
  const groups = useMemo(() => groupUsage(rows, dimension), [rows, dimension]);
  const modelGroups = useMemo(() => groupUsage(rows, "model_id"), [rows]);
  const totals = rows.reduce(
    (acc, row) => ({
      charged: acc.charged + row.charged,
      requests: acc.requests + row.requests,
      failures: acc.failures + row.failures,
    }),
    { charged: 0, requests: 0, failures: 0 },
  );
  const chart = useMemo(() => {
    const daily = new Map<string, number>();
    for (const row of rows) {
      const key = `${row.date}:${row.model_id}`;
      daily.set(key, (daily.get(key) ?? 0) + row.charged);
    }
    const days = Array.from(
      { length: dayjs(end).diff(dayjs(start), "day") + 1 },
      (_, i) => dayjs(start).add(i, "day").format("YYYY-MM-DD"),
    );
    return {
      ...lineChartChrome({
        isDark,
        tickCount: Math.min(10, days.length),
        startDate: dayjs(start),
        endDate: dayjs(end),
        seriesField: "model",
      }),
      smooth: false,
      data: days.flatMap((date) =>
        modelGroups.map((m) => ({
          date,
          model: modelGroups.some(
            (other) => other.key !== m.key && other.label === m.label,
          )
            ? `${m.label} · ${m.key}`
            : m.label,
          value: daily.get(`${date}:${m.key}`) ?? 0,
        })),
      ),
    };
  }, [rows, modelGroups, start, end, isDark]);
  const n = (value: number) => value.toLocaleString(i18n.language);
  const labels = {
    user_id: t("hub.governance.analytics.memberRanking"),
    model_id: t("tokenUsage.byModel"),
    date: t("tokenUsage.byDate"),
  };
  const columns: ColumnsType<UsageGroup> = [
    ...(dimension === "user_id"
      ? [
          {
            title: t("hub.governance.analytics.rank"),
            key: "rank",
            width: 60,
            render: (_: unknown, row: UsageGroup) => groups.indexOf(row) + 1,
          },
        ]
      : []),
    {
      title:
        dimension === "user_id"
          ? t("hub.governance.users.member")
          : dimension === "model_id"
          ? t("tokenUsage.model")
          : t("tokenUsage.date"),
      dataIndex: "label",
      key: "label",
      sorter: (a, b) => a.label.localeCompare(b.label),
      render: (value, row) =>
        dimension === "user_id" ? (
          <Button
            type="link"
            size="small"
            onClick={() => {
              setMember(row.key);
              setDimension("model_id");
            }}
          >
            {value}
          </Button>
        ) : (
          value
        ),
    },
    {
      title: (
        <Tooltip title={t("hub.governance.analytics.chargedHint")}>
          <span>
            {t("hub.governance.analytics.charged")} <CircleHelp size={12} />
          </span>
        </Tooltip>
      ),
      dataIndex: "charged",
      key: "charged",
      render: n,
      sorter: (a, b) => a.charged - b.charged,
    },
    {
      title: t("hub.governance.analytics.share"),
      key: "share",
      width: 140,
      render: (_, row) => (
        <Progress
          percent={
            totals.charged
              ? Math.round((row.charged / totals.charged) * 1000) / 10
              : 0
          }
          size="small"
          status="normal"
          strokeColor="var(--app-accent)"
        />
      ),
    },
    ...(
      ["requests", "failures", "actual", "conservative", "reserved"] as const
    ).map((key) => ({
      title: t(`hub.governance.analytics.${key}`),
      dataIndex: key,
      key,
      render: n,
      sorter: (a: UsageGroup, b: UsageGroup) => a[key] - b[key],
    })),
    {
      title: t(
        dimension === "user_id" ? "tokenUsage.model" : "hub.navigation.users",
      ),
      dataIndex: dimension === "user_id" ? "models" : "members",
      key: "count",
      render: n,
    },
  ];
  return (
    <div className={styles.usage}>
      <div className={styles.toolbar}>
        <DatePicker.RangePicker
          value={range}
          allowClear={false}
          onChange={(dates) => {
            if (dates?.[0] && dates[1]) {
              setRange([dates[0], dates[1]]);
              setMember(undefined);
              setModel(undefined);
            }
          }}
          disabledDate={(date, info) =>
            date.isAfter(dayjs(), "day") ||
            !!(info.from && Math.abs(date.diff(info.from, "day")) >= 365)
          }
        />
        <Select
          allowClear
          showSearch
          optionFilterProp="label"
          aria-label={t("tokenUsage.model")}
          placeholder={t("tokenUsage.model")}
          value={model}
          onChange={setModel}
          options={groupUsage(report?.rows ?? [], "model_id").map((m) => ({
            value: m.key,
            label: m.label,
          }))}
        />
        <Select
          allowClear
          showSearch
          optionFilterProp="label"
          aria-label={t("hub.governance.users.member")}
          placeholder={t("hub.governance.users.member")}
          value={member}
          onChange={setMember}
          options={groupUsage(report?.rows ?? [], "user_id").map((m) => ({
            value: m.key,
            label: m.label,
          }))}
        />
        <Button
          icon={<RefreshCw size={14} />}
          loading={loading}
          onClick={load}
          aria-label={t("common.refresh")}
        />
        <span className={styles.timezone}>{report?.timezone}</span>
      </div>
      {loading ? (
        <LoadingState message={t("common.loading")} />
      ) : error ? (
        <LoadingState
          message={t("tokenUsage.loadFailed")}
          error
          onRetry={load}
        />
      ) : (
        <>
          <UsageSummaryCards
            items={[
              {
                label: t("hub.governance.analytics.charged"),
                value: formatTokens(totals.charged, i18n.language),
              },
              { label: t("tokenUsage.totalCalls"), value: n(totals.requests) },
              {
                label: t("hub.governance.analytics.activeMembers"),
                value: n(groupUsage(rows, "user_id").length),
              },
              {
                label: t("hub.governance.analytics.failures"),
                value: n(totals.failures),
              },
            ]}
          />
          {rows.length ? (
            <ModelTrendChart chartConfig={chart} />
          ) : (
            <EmptyState message={t("tokenUsage.noData")} />
          )}
          {rows.length > 0 && (
            <UsageTable
              title={
                <Tabs
                  activeKey={dimension}
                  onChange={(key) => setDimension(key as typeof dimension)}
                  items={Object.entries(labels).map(([key, label]) => ({
                    key,
                    label,
                  }))}
                />
              }
              rows={
                dimension === "date"
                  ? [...groups].sort((a, b) => b.key.localeCompare(a.key))
                  : groups
              }
              columns={columns}
            />
          )}
        </>
      )}
    </div>
  );
}
