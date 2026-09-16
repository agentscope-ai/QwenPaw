import { useTranslation } from "react-i18next";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Button, Skeleton } from "antd";
import { motion, useReducedMotion } from "motion/react";
import { ArrowUpRight } from "lucide-react";
import {
  governanceRequest as request,
  type UsageReport,
} from "../../../api/modules/hubGovernance";
import type { HubOverview } from "../../../api/modules/hub";
import type { Section } from "../pageUtils";
import { governanceErrorMessage } from "./errors";
import styles from "./UsageDashboard.module.less";

export default function UsageDashboard({
  overview,
  onNavigate,
  children,
}: {
  children?: ReactNode;
  overview: HubOverview;
  onNavigate: (section: Section, target?: string) => void;
}) {
  const { t, i18n } = useTranslation();
  const reduceMotion = useReducedMotion();
  const [report, setReport] = useState<UsageReport>();
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    try {
      setReport(await request<UsageReport>("admin/usage"));
      setError("");
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);
  return (
    <div className={styles.dashboard}>
      <div className={styles.metrics}>
        {[
          {
            label: t("hub.governance.dashboard.requests"),
            value: report?.organization.requests.toLocaleString(i18n.language),
            section: "models" as Section,
            target: "usage",
          },
          {
            label: t("hub.navigation.users"),
            value: overview.total_users.toLocaleString(i18n.language),
            section: "users" as Section,
          },
          {
            label: t("hub.governance.dashboard.running"),
            value: `${overview.runtime_counts.running || 0} / ${
              overview.total_runtimes
            }`,
            section: "runtimes" as Section,
          },
        ].map((m) => (
          <motion.button
            className={styles.metricCard}
            key={m.label}
            whileTap={reduceMotion ? undefined : { scale: 0.98 }}
            onClick={() => onNavigate(m.section, m.target)}
          >
            <span>
              {m.label}
              <ArrowUpRight size={14} />
            </span>
            {m.value === undefined ? (
              <Skeleton.Button active size="small" />
            ) : (
              <strong>{m.value}</strong>
            )}
          </motion.button>
        ))}
      </div>
      {error && (
        <div role="alert">
          {governanceErrorMessage(error, t)}
          <Button onClick={load}>{t("common.retry")}</Button>
        </div>
      )}
      <div className={styles.secondaryGrid}>{children}</div>
    </div>
  );
}
