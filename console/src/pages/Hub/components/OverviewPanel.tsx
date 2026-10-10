import NumberFlow from "@number-flow/react";
import { RunningGlow } from "@/components/interaction/RunningGlow";
import { Cascade } from "@/components/interaction/Cascade";
import { useTranslation } from "react-i18next";
import { Button } from "antd";
import {
  ArrowUpRight,
  Boxes,
  BrainCircuit,
  ChartNoAxesCombined,
  ChevronRight,
  HardDrive,
  MemoryStick,
  KeyRound,
  ScrollText,
  ShieldAlert,
  Users,
} from "lucide-react";
import type { HubOverview } from "../../../api/modules/hub";
import { formatDate, type Section } from "../pageUtils";
import styles from "./OverviewPanel.module.less";

type Props = {
  overview: HubOverview;
  onNavigate: (section: Section, target?: string) => void;
};
const states = ["running", "stopped", "failed", "starting", "created"] as const;

export default function OverviewPanel({ overview, onNavigate }: Props) {
  const { t, i18n } = useTranslation();
  const running = overview.runtime_counts.running || 0;
  const failed = overview.runtime_counts.failed || 0;
  const percent = overview.total_runtimes
    ? ((running / overview.total_runtimes) * 100).toFixed(1)
    : null;
  const capacity = (used: number, total: number, available: number) => {
    const format = (bytes: number) =>
      `${(bytes / 1024 ** 3).toLocaleString(i18n.language, {
        maximumFractionDigits: 1,
      })} GiB`;
    return t("hub.overview.capacity", {
      used: format(used),
      total: format(total),
      available: format(available),
    });
  };
  return (
    <section className={styles.overview}>
      <header className={styles.heading}>
        <div>
          <h1>{t("hub.overview.title")}</h1>
          <p>{t("hub.overview.description")}</p>
        </div>
        {failed > 0 && (
          <button
            type="button"
            className={styles.attention}
            onClick={() => onNavigate("runtimes", "failed")}
          >
            <ShieldAlert size={17} />
            <span>{t("hub.overview.failedCount", { count: failed })}</span>
            <ChevronRight size={16} />
          </button>
        )}
      </header>
      <Cascade className={styles.commandCenter}>
        <section
          className={styles.fleet}
          aria-label={t("hub.navigation.runtimes")}
        >
          <RunningGlow active={running > 0} />
          <div className={styles.fleetTop}>
            <span>
              <Boxes size={18} />
              {t("hub.navigation.runtimes")}
            </span>
            <button
              type="button"
              onClick={() => onNavigate("runtimes")}
              aria-label={t("hub.overview.totalRuntimes")}
            >
              <ArrowUpRight size={20} />
            </button>
          </div>
          <div className={styles.fleetBody}>
            <button
              type="button"
              className={styles.availability}
              onClick={() => onNavigate("runtimes")}
            >
              <span>{t("hub.overview.availability")}</span>
              <strong>
                {percent === null ? (
                  "—"
                ) : (
                  <>
                    <NumberFlow
                      value={Number(percent)}
                      respectMotionPreference
                      format={{
                        minimumFractionDigits: 1,
                        maximumFractionDigits: 1,
                      }}
                    />
                    <small>%</small>
                  </>
                )}
              </strong>
              <p>
                {t("hub.overview.availabilityDetail", {
                  running,
                  total: overview.total_runtimes,
                })}
              </p>
            </button>
            <div className={styles.distribution}>
              <div className={styles.distributionBar} aria-hidden="true">
                {states
                  .filter((state) => overview.runtime_counts[state] > 0)
                  .map((state) => (
                    <span
                      key={state}
                      data-state={state}
                      style={{ flex: overview.runtime_counts[state] }}
                    />
                  ))}
              </div>
              <div className={styles.stateList}>
                {states.map((state) => (
                  <button
                    key={state}
                    type="button"
                    data-state={state}
                    onClick={() => onNavigate("runtimes", state)}
                  >
                    <i />
                    <span>{t(`hub.runtimeStates.${state}`)}</span>
                    <strong>
                      <NumberFlow
                        value={overview.runtime_counts[state] || 0}
                        respectMotionPreference
                      />
                    </strong>
                    <ArrowUpRight size={14} />
                  </button>
                ))}
              </div>
            </div>
          </div>
        </section>
        <section
          className={styles.workspace}
          aria-label={t("hub.navigation.workspace")}
        >
          <h2>{t("hub.navigation.workspace")}</h2>
          <button type="button" onClick={() => onNavigate("users")}>
            <Users size={20} />
            <span>
              <strong>{t("hub.overview.totalUsers")}</strong>
              <small>{t("hub.overview.managedLocally")}</small>
            </span>
            <b>
              <NumberFlow
                value={overview.total_users}
                respectMotionPreference
              />
            </b>
            <ChevronRight size={16} />
          </button>
          <button type="button" onClick={() => onNavigate("models")}>
            <BrainCircuit size={20} />
            <span>
              <strong>{t("hub.governance.models.title")}</strong>
              <small>{t("hub.governance.models.organizationTitle")}</small>
            </span>
            <ChevronRight size={16} />
          </button>
          <button type="button" onClick={() => onNavigate("credentials")}>
            <KeyRound size={20} />
            <span>
              <strong>{t("hub.navigation.credentials")}</strong>
              <small>{t("hub.credentials.encrypted")}</small>
            </span>
            <ChevronRight size={16} />
          </button>
        </section>
      </Cascade>
      <section
        className={styles.resources}
        aria-labelledby="hub-resources-title"
      >
        <div className={styles.sectionHeading}>
          <h2 id="hub-resources-title">{t("hub.overview.hostResources")}</h2>
          <span>{t("hub.overview.liveSnapshot")}</span>
        </div>
        <div className={styles.resourceGrid}>
          {[
            {
              label: "CPU",
              value: overview.host.cpu_percent,
              Icon: ChartNoAxesCombined,
            },
            {
              label: t("hub.overview.memory"),
              value: overview.host.memory_percent,
              Icon: MemoryStick,
              detail: capacity(
                overview.host.memory_used,
                overview.host.memory_total,
                overview.host.memory_available,
              ),
            },
            {
              label: t("hub.overview.dataDisk"),
              value: overview.host.disk_percent,
              Icon: HardDrive,
              detail: capacity(
                overview.host.disk_used,
                overview.host.disk_total,
                overview.host.disk_free,
              ),
              path: overview.host.disk_path,
            },
          ].map(({ label, value, Icon, detail, path }) => (
            <div className={styles.resource} key={label}>
              <div>
                <Icon size={19} />
                <span>{label}</span>
                <strong>
                  {value.toFixed(1)}
                  <small>%</small>
                </strong>
              </div>
              <meter
                aria-label={`${label}: ${value.toFixed(1)}%`}
                min={0}
                max={100}
                value={value}
              />
              {detail && (
                <small className={styles.resourceDetail}>{detail}</small>
              )}
              {path && (
                <small className={styles.resourceDetail} title={path}>
                  {path}
                </small>
              )}
            </div>
          ))}
        </div>
      </section>
      <section className={styles.activity}>
        <div className={styles.sectionHeading}>
          <div>
            <h2>{t("hub.overview.recentActivity")}</h2>
            <p>{t("hub.overview.auditBacked")}</p>
          </div>
          <Button type="text" onClick={() => onNavigate("audit")}>
            {t("hub.overview.viewAll")}
            <ArrowUpRight size={15} />
          </Button>
        </div>
        <div className={styles.eventList}>
          {overview.recent_events.slice(0, 5).map((event) => (
            <button
              type="button"
              key={event.event_id}
              className={styles.event}
              onClick={() => onNavigate("audit", event.resource_id)}
            >
              <span className={styles.eventIcon}>
                <ScrollText size={18} />
              </span>
              <span className={styles.eventMain}>
                <strong>{t(`hub.auditActions.${event.action}`)}</strong>
                <small>{event.resource_id}</small>
              </span>
              <span className={styles.actor}>{event.actor_username}</span>
              <time dateTime={event.created_at}>
                {formatDate(event.created_at, i18n.language)}
              </time>
              <ChevronRight size={15} />
            </button>
          ))}
        </div>
        {!overview.recent_events.length && (
          <div className={styles.empty}>
            <ScrollText size={25} />
            <p>{t("hub.audit.empty")}</p>
          </div>
        )}
      </section>
    </section>
  );
}
