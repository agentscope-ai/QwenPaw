import { useTranslation } from "react-i18next";
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
import { governanceErrorMessage } from "./errors";
import styles from "./governance.module.less";

import { formatTokens } from "./budgetUtils";
export default function UsageDashboard({
  overview,
  onNavigate,
}: {
  overview: HubOverview;
  onNavigate: (section: Section, target?: string) => void;
}) {
  const { t, i18n } = useTranslation();
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
        {governanceErrorMessage(error, t)}
        <Button onClick={load}>{t("common.retry")}</Button>
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
            label: t("hub.navigation.users"),
            value: overview.total_users,
            icon: Users,
            detail: t("hub.governance.dashboard.manageAccounts"),
            section: "users" as Section,
          },
          {
            label: t("hub.governance.dashboard.running"),
            value: overview.runtime_counts.running || 0,
            icon: Box,
            detail: t("hub.governance.dashboard.instanceCount", {
              count: overview.total_runtimes,
            }),
            section: "runtimes" as Section,
          },
          {
            label: t("hub.governance.dashboard.monthlyTokens"),
            value: formatTokens(org.charged, i18n.language),
            icon: Coins,
            detail: t("hub.governance.dashboard.requestCount", {
              count: org.requests,
            }),
            section: "models" as Section,
          },
          {
            label: t("hub.governance.dashboard.remaining"),
            value:
              org.remaining === null
                ? t("hub.governance.budget.unlimited")
                : formatTokens(org.remaining, i18n.language),
            icon: Wallet,
            detail:
              org.remaining === 0
                ? t("hub.governance.dashboard.paused")
                : t("hub.governance.dashboard.manageOrganization"),
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
              ? t("hub.governance.dashboard.exhausted")
              : !models.some((m) => m.enabled)
              ? t("hub.governance.dashboard.noModels")
              : t("hub.governance.dashboard.runtimeWarning")}
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
            {t("common.view")}
          </Button>
        </div>
      )}
      <div className={styles.chartGrid}>
        <article className={styles.card}>
          <div className={styles.heading}>
            <h3>{t("hub.governance.dashboard.tokenUsage")}</h3>
            <small>
              {org.period} · {report.timezone}
            </small>
          </div>
          {org.requests === 0 ? (
            <div className={styles.empty}>
              <ChartNoAxesCombined size={28} />
              <strong>{t("hub.governance.dashboard.emptyTitle")}</strong>
              <p>{t("hub.governance.dashboard.emptyHint")}</p>
            </div>
          ) : (
            <>
              <div
                className={styles.chart}
                role="img"
                aria-label={t("hub.governance.dashboard.chartLabel")}
              >
                {days.map((d) => (
                  <div
                    key={d.date}
                    className={styles.barColumn}
                    title={`${new Date(`${d.date}T00:00:00`).toLocaleDateString(
                      i18n.language,
                    )}: ${d.tokens.toLocaleString(i18n.language)} Token`}
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
                <span>{t("hub.governance.dashboard.dailyTokens")}</span>
                <span>
                  {t("hub.governance.dashboard.peak")}{" "}
                  {formatTokens(
                    peak === 1 && org.charged === 0 ? 0 : peak,
                    i18n.language,
                  )}
                </span>
              </div>
            </>
          )}
        </article>
        <article className={styles.card}>
          <h3>{t("hub.governance.dashboard.monthlyBudget")}</h3>
          <div className={styles.metric}>
            {formatTokens(org.charged, i18n.language)} <small>Token</small>
          </div>
          <p>
            {org.token_limit === null
              ? t("hub.governance.dashboard.noLimit")
              : t("hub.governance.dashboard.totalBudget", {
                  amount: formatTokens(org.token_limit, i18n.language),
                })}
          </p>
          {org.token_limit !== null && (
            <Progress
              percent={Math.round(percent)}
              status={org.remaining === 0 ? "exception" : undefined}
              strokeColor="var(--app-accent)"
            />
          )}
          <div className={styles.detailRow}>
            <span>{t("hub.governance.dashboard.reserved")}</span>
            <strong>{formatTokens(org.reserved, i18n.language)}</strong>
          </div>
          <div className={styles.detailRow}>
            <span>{t("hub.governance.dashboard.nextReset")}</span>
            <strong>
              {new Date(year, month, 1).toLocaleDateString(i18n.language)}
            </strong>
          </div>
          <Button onClick={() => onNavigate("settings", "budget")}>
            {t("hub.governance.dashboard.manageBudget")}
          </Button>
        </article>
      </div>
      <div className={styles.settingsColumns}>
        <article className={styles.card}>
          <div className={styles.heading}>
            <h3>{t("hub.governance.dashboard.byModel")}</h3>
            <Button
              type="text"
              onClick={() => onNavigate("models")}
              icon={<ArrowUpRight size={15} />}
              aria-label={t("hub.governance.dashboard.manageModels")}
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
                    <strong>{formatTokens(m.charged, i18n.language)}</strong>
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
              {t("hub.governance.dashboard.noRequests")}
            </p>
          )}
        </article>
        <article className={styles.card}>
          <div className={styles.heading}>
            <h3>{t("hub.governance.dashboard.byMember")}</h3>
            <Button
              type="text"
              onClick={() => onNavigate("users")}
              icon={<ArrowUpRight size={15} />}
              aria-label={t("hub.governance.dashboard.manageUsers")}
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
                  {formatTokens(m.charged, i18n.language)} <small>Token</small>
                </strong>
                <ArrowUpRight size={13} />
              </button>
            ))
          ) : (
            <p className={styles.emptyCompact}>
              {t("hub.governance.dashboard.noMemberUsage")}
            </p>
          )}
        </article>
      </div>
    </div>
  );
}
