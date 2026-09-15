import { useCallback, useEffect, useState } from "react";
import { Button, Progress, Skeleton } from "antd";
import {
  ArrowUpRight,
  Users,
  Box,
  Coins,
  Wallet,
  ChartNoAxesCombined,
} from "lucide-react";
import {
  governanceRequest as request,
  type UsageReport,
  type ManagedModel,
} from "../../../api/modules/hubGovernance";
import type { HubOverview } from "../../../api/modules/hub";
import type { Section } from "../pageUtils";
import { useGovernanceText } from "./shared";
import styles from "./governance.module.less";

import { formatTokens } from "./budgetUtils";
export default function UsageDashboard({
  overview,
  onNavigate,
}: {
  overview: HubOverview;
  onNavigate: (section: Section, target?: string) => void;
}) {
  const text = useGovernanceText();
  const [report, setReport] = useState<UsageReport>();
  const [models, setModels] = useState<ManagedModel[]>([]);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    try {
      const [r, m] = await Promise.all([
        request<UsageReport>("admin/usage"),
        request<ManagedModel[]>("admin/models"),
      ]);
      setReport(r);
      setModels(m);
      setError("");
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);
  if (error)
    return (
      <div className={styles.card} role="alert">
        {error}
        <Button onClick={load}>{text("重试", "Retry")}</Button>
      </div>
    );
  if (!report) return <Skeleton active />;
  const org = report.organization;
  const percent = org.token_limit
    ? Math.min(100, ((org.charged + org.reserved) / org.token_limit) * 100)
    : 0;
  const top = [...report.members]
    .filter((m) => m.charged > 0)
    .sort((a, b) => b.charged - a.charged)
    .slice(0, 5);
  const maxModel = Math.max(1, ...report.models.map((m) => m.charged));
  const [year, month] = org.period.split("-").map(Number);
  const days = Array.from(
    { length: new Date(year, month, 0).getDate() },
    (_, i) => {
      const date = `${org.period}-${String(i + 1).padStart(2, "0")}`;
      return {
        date,
        tokens: report.daily.find((d) => d.date === date)?.tokens ?? 0,
      };
    },
  );
  const peak = Math.max(1, ...days.map((d) => d.tokens));
  return (
    <div className={styles.dashboard}>
      <div className={styles.metrics}>
        {[
          {
            label: text("用户", "Users"),
            value: overview.total_users,
            icon: Users,
            detail: text("管理账号与额度", "Manage accounts and limits"),
            section: "users" as Section,
          },
          {
            label: text("运行实例", "Running instances"),
            value: overview.runtime_counts.running || 0,
            icon: Box,
            detail: `${overview.total_runtimes} ${text("个实例", "instances")}`,
            section: "runtimes" as Section,
          },
          {
            label: text("本月 Token", "Monthly tokens"),
            value: formatTokens(org.charged),
            icon: Coins,
            detail: `${org.requests} ${text("次调用", "requests")}`,
            section: "models" as Section,
          },
          {
            label: text("剩余额度", "Budget remaining"),
            value:
              org.remaining === null
                ? text("不限额", "Unlimited")
                : formatTokens(org.remaining),
            icon: Wallet,
            detail:
              org.remaining === 0
                ? text("调用已暂停", "Calls paused")
                : text("查看组织预算", "Manage organization budget"),
            section: "settings" as Section,
          },
        ].map((m) => (
          <button
            className={styles.metricCard}
            key={m.label}
            onClick={() =>
              onNavigate(
                m.section,
                m.section === "settings" ? "budget" : undefined,
              )
            }
          >
            <span>
              <m.icon size={16} />
              {m.label}
            </span>
            <strong>{m.value}</strong>
            <small>
              {m.detail}
              <ArrowUpRight size={13} />
            </small>
          </button>
        ))}
      </div>
      {(org.remaining === 0 ||
        !models.some((m) => m.enabled) ||
        !!overview.runtime_counts.failed) && (
        <div className={styles.notice}>
          <span>
            {org.remaining === 0
              ? text(
                  "组织额度已用完，请调整预算以恢复调用。",
                  "Organization budget exhausted. Adjust the budget to resume calls.",
                )
              : !models.some((m) => m.enabled)
              ? text(
                  "还没有可用模型，添加模型后成员即可开始使用。",
                  "Add an available model to get your members started.",
                )
              : text(
                  "有实例运行异常，请检查实例状态。",
                  "Some instances need attention.",
                )}
          </span>
          <Button
            size="small"
            onClick={() =>
              onNavigate(
                org.remaining === 0
                  ? "settings"
                  : !models.some((m) => m.enabled)
                  ? "models"
                  : "runtimes",
              )
            }
          >
            {text("去处理", "View")}
          </Button>
        </div>
      )}
      <div className={styles.chartGrid}>
        <article className={styles.card}>
          <div className={styles.heading}>
            <h3>{text("用量趋势", "Token usage")}</h3>
            <small>
              {org.period} · {report.timezone}
            </small>
          </div>
          {org.requests === 0 ? (
            <div className={styles.empty}>
              <ChartNoAxesCombined size={28} />
              <strong>
                {text("等待第一次调用", "Awaiting your first request")}
              </strong>
              <p>
                {text(
                  "成员使用托管模型后，这里将展示每天的用量。",
                  "Daily usage appears here when members use managed models.",
                )}
              </p>
            </div>
          ) : (
            <>
              <div
                className={styles.chart}
                role="img"
                aria-label={text(
                  "本月每日 Token 用量",
                  "Daily token usage this month",
                )}
              >
                {days.map((d) => (
                  <div
                    key={d.date}
                    className={styles.barColumn}
                    title={`${d.date}: ${d.tokens.toLocaleString()} Token`}
                  >
                    <div
                      className={styles.bar}
                      style={{
                        height: `${
                          d.tokens ? Math.max(2, (d.tokens / peak) * 100) : 0
                        }%`,
                      }}
                    />
                    <span>{d.date.slice(-2)}</span>
                  </div>
                ))}
              </div>
              <div className={styles.chartLegend}>
                <span>{text("每日 Token", "Tokens per day")}</span>
                <span>
                  {text("单日最高", "Daily peak")}{" "}
                  {formatTokens(peak === 1 && org.charged === 0 ? 0 : peak)}
                </span>
              </div>
            </>
          )}
        </article>
        <article className={styles.card}>
          <h3>{text("本月预算", "Monthly budget")}</h3>
          <div className={styles.metric}>
            {formatTokens(org.charged)} <small>Token</small>
          </div>
          <p>
            {org.token_limit === null
              ? text("组织未设用量上限", "No organization limit configured")
              : `${text("总额度", "Total budget")} ${formatTokens(
                  org.token_limit,
                )}`}
          </p>
          {org.token_limit !== null && (
            <Progress
              percent={Math.round(percent)}
              status={org.remaining === 0 ? "exception" : undefined}
              strokeColor="var(--app-accent)"
            />
          )}
          <div className={styles.detailRow}>
            <span>{text("处理中预留", "Reserved for active calls")}</span>
            <strong>{formatTokens(org.reserved)}</strong>
          </div>
          <div className={styles.detailRow}>
            <span>{text("下次重置", "Next reset")}</span>
            <strong>
              {month === 12 ? year + 1 : year}-
              {String(month === 12 ? 1 : month + 1).padStart(2, "0")}-01
            </strong>
          </div>
          <Button onClick={() => onNavigate("settings", "budget")}>
            {text("管理预算", "Manage budget")}
          </Button>
        </article>
      </div>
      <div className={styles.settingsColumns}>
        <article className={styles.card}>
          <div className={styles.heading}>
            <h3>{text("模型用量", "Usage by model")}</h3>
            <Button
              type="text"
              onClick={() => onNavigate("models")}
              icon={<ArrowUpRight size={15} />}
              aria-label={text("管理模型", "Manage models")}
            />
          </div>
          {report.models.length ? (
            [...report.models]
              .sort((a, b) => b.charged - a.charged)
              .slice(0, 5)
              .map((m) => (
                <button
                  className={styles.modelUsageRow}
                  key={m.model_id}
                  onClick={() => onNavigate("models", m.model_id)}
                >
                  <div className={styles.detailRow}>
                    <span>
                      {models.find((model) => model.id === m.model_id)?.name ??
                        m.model_id}
                    </span>
                    <strong>{formatTokens(m.charged)}</strong>
                  </div>
                  <Progress
                    percent={(m.charged / maxModel) * 100}
                    showInfo={false}
                    strokeColor="var(--app-accent)"
                    size="small"
                  />
                </button>
              ))
          ) : (
            <p className={styles.emptyCompact}>
              {text("暂无模型调用", "No model requests yet")}
            </p>
          )}
        </article>
        <article className={styles.card}>
          <div className={styles.heading}>
            <h3>{text("成员用量", "Member usage")}</h3>
            <Button
              type="text"
              onClick={() => onNavigate("users")}
              icon={<ArrowUpRight size={15} />}
              aria-label={text("管理用户", "Manage users")}
            />
          </div>
          {top.length ? (
            top.map((m, i) => (
              <button
                className={styles.rankRow}
                key={m.user_id}
                onClick={() => onNavigate("users", m.username)}
              >
                <span className={styles.rank}>{i + 1}</span>
                <span>{m.username}</span>
                <strong>
                  {formatTokens(m.charged)} <small>Token</small>
                </strong>
                <ArrowUpRight size={13} />
              </button>
            ))
          ) : (
            <p className={styles.emptyCompact}>
              {text(
                "成员开始使用后，这里将展示用量分布。",
                "Member usage will appear after their first requests.",
              )}
            </p>
          )}
        </article>
      </div>
    </div>
  );
}
