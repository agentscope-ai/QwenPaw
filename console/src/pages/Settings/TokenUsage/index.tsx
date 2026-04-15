import { useEffect, useMemo, useState } from "react";
import { Button, Card, Table } from "@agentscope-ai/design";
import type { ColumnsType } from "antd/es/table";
import { DatePicker } from "antd";
import { useTranslation } from "react-i18next";
import dayjs, { Dayjs } from "dayjs";
import api from "../../../api";
import type {
  TokenUsageSummary,
  TokenUsageStats,
} from "../../../api/types/tokenUsage";
import { formatCompact } from "../../../utils/formatNumber";
import { LoadingState, EmptyState } from "./components";
import { PageHeader } from "@/components/PageHeader";
import { useAppMessage } from "../../../hooks/useAppMessage";
import styles from "./index.module.less";

type ByModelRow = TokenUsageStats & { key: string };
type ByDateRow = TokenUsageStats & { key: string; date: string };

function TokenUsagePage() {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<TokenUsageSummary | null>(null);
  const [startDate, setStartDate] = useState<Dayjs>(
    dayjs().subtract(30, "day"),
  );
  const [endDate, setEndDate] = useState<Dayjs>(dayjs());

  const fetchData = async () => {
    setLoading(true);
    setError(null);
    try {
      const summary = await api.getTokenUsage({
        start_date: startDate.format("YYYY-MM-DD"),
        end_date: endDate.format("YYYY-MM-DD"),
      });
      setData(summary);
    } catch (e) {
      console.error("Failed to load token usage:", e);
      const msg = t("tokenUsage.loadFailed");
      message.error(msg);
      setError(msg);
      setData(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  const handleDateChange = (dates: [Dayjs | null, Dayjs | null] | null) => {
    if (dates?.[0]) setStartDate(dates[0]);
    if (dates?.[1]) setEndDate(dates[1]);
  };

  const byModelDataSource: ByModelRow[] = useMemo(() => {
    if (!data?.by_model) return [];
    return Object.entries(data.by_model).map(([key, stats]) => ({
      ...stats,
      key,
    }));
  }, [data?.by_model]);

  const byDateDataSource: ByDateRow[] = useMemo(() => {
    if (!data?.by_date) return [];
    return Object.entries(data.by_date)
      .map(([dt, stats]) => ({
        ...stats,
        key: dt,
        date: dt,
      }))
      .sort((a, b) => b.date.localeCompare(a.date));
  }, [data?.by_date]);

  const byModelColumns: ColumnsType<ByModelRow> = useMemo(
    () => [
      {
        title: t("tokenUsage.provider"),
        dataIndex: "provider_id",
        key: "provider_id",
        render: (v: string) => v ?? "",
      },
      {
        title: t("tokenUsage.model"),
        dataIndex: "model",
        key: "model",
        render: (v: string, r) => v ?? r.key,
      },
      {
        title: t("tokenUsage.promptTokens"),
        dataIndex: "prompt_tokens",
        key: "prompt_tokens",
        render: (n: number) => formatCompact(n),
      },
      {
        title: t("tokenUsage.completionTokens"),
        dataIndex: "completion_tokens",
        key: "completion_tokens",
        render: (n: number) => formatCompact(n),
      },
      {
        title: t("tokenUsage.totalCalls"),
        dataIndex: "call_count",
        key: "call_count",
        render: (n: number) => formatCompact(n),
      },
    ],
    [t],
  );

  const byDateColumns: ColumnsType<ByDateRow> = useMemo(
    () => [
      { title: t("tokenUsage.date"), dataIndex: "date", key: "date" },
      {
        title: t("tokenUsage.promptTokens"),
        dataIndex: "prompt_tokens",
        key: "prompt_tokens",
        render: (n: number) => formatCompact(n),
      },
      {
        title: t("tokenUsage.completionTokens"),
        dataIndex: "completion_tokens",
        key: "completion_tokens",
        render: (n: number) => formatCompact(n),
      },
      {
        title: t("tokenUsage.totalCalls"),
        dataIndex: "call_count",
        key: "call_count",
        render: (n: number) => formatCompact(n),
      },
    ],
    [t],
  );

  return (
    <div className={styles.tokenUsagePage}>
      <PageHeader parent={t("nav.settings")} current={t("tokenUsage.title")} />
      <div className={styles.content}>
        {loading && !data ? (
          <LoadingState
            message={error ?? t("common.loading")}
            error={!!error}
            onRetry={error ? fetchData : undefined}
          />
        ) : (
          <>
            <div className={styles.filters}>
              <DatePicker.RangePicker
                value={[startDate, endDate]}
                onChange={handleDateChange}
                className={styles.datePicker}
              />
              <Button type="primary" onClick={fetchData} loading={loading}>
                {t("tokenUsage.refresh")}
              </Button>
            </div>

            {data && data.total_calls > 0 ? (
              <>
                <div className={styles.summaryCards}>
                  <Card className={styles.card}>
                    <div className={styles.cardValue}>
                      {formatCompact(data.total_prompt_tokens)}
                    </div>
                    <div className={styles.cardLabel}>
                      {t("tokenUsage.promptTokens")}
                    </div>
                  </Card>
                  <Card className={styles.card}>
                    <div className={styles.cardValue}>
                      {formatCompact(data.total_completion_tokens)}
                    </div>
                    <div className={styles.cardLabel}>
                      {t("tokenUsage.completionTokens")}
                    </div>
                  </Card>
                </div>

                {byModelDataSource.length > 0 && (
                  <Card
                    className={styles.tableCard}
                    title={t("tokenUsage.byModel")}
                    bodyStyle={{ padding: 0 }}
                  >
                    <Table<ByModelRow>
                      columns={byModelColumns}
                      dataSource={byModelDataSource}
                      rowKey="key"
                      pagination={false}
                    />
                  </Card>
                )}

                {byDateDataSource.length > 0 && (
                  <Card
                    className={styles.tableCard}
                    title={t("tokenUsage.byDate")}
                    bodyStyle={{ padding: 0 }}
                  >
                    <Table<ByDateRow>
                      columns={byDateColumns}
                      dataSource={byDateDataSource}
                      rowKey="key"
                      pagination={false}
                    />
                  </Card>
                )}
              </>
            ) : (
              <EmptyState message={t("tokenUsage.noData")} />
            )}
          </>
        )}
      </div>
    </div>
  );
}

export default TokenUsagePage;
