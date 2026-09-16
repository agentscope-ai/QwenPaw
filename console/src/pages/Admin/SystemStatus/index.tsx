import { Alert, Button, Card, Spin, Tag, Typography } from "antd";
import {
  Database,
  HardDrive,
  Layers3,
  LockKeyhole,
  RefreshCw,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  systemStatusApi,
  type StorageStatus,
} from "@/api/modules/systemStatus";
import { PageHeader } from "@/components/PageHeader";

import styles from "./index.module.less";

const { Text, Title } = Typography;

function SystemStatusPage() {
  const { t } = useTranslation();
  const [status, setStatus] = useState<StorageStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadStatus = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setStatus(await systemStatusApi.getStorageStatus());
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadStatus();
  }, [loadStatus]);

  const lockLabel = status
    ? {
        not_applicable: t("systemStatus.lock.notApplicable", "Not applicable"),
        not_configured: t("systemStatus.lock.notConfigured", "Not configured"),
        locked: t("systemStatus.lock.locked", "Legacy writes frozen"),
        unknown: t("systemStatus.lock.unknown", "Unknown"),
      }[status.migration_lock_state]
    : "—";

  const legacyActive = status?.active_repository === "legacy";
  const mixedActive = status?.active_repository === "mixed";
  const databaseLabel = status?.connected
    ? t("systemStatus.database.connected", "Database connected")
    : status?.storage_mode === "legacy"
    ? t("systemStatus.database.notRequired", "Not required in Legacy mode")
    : t("systemStatus.database.disconnected", "Database disconnected");

  return (
    <div className={styles.page}>
      <PageHeader
        parent={t("nav.settings", "Settings")}
        current={t("systemStatus.title", "System Status")}
        extra={
          <Button
            icon={<RefreshCw size={15} />}
            loading={loading && status !== null}
            onClick={() => void loadStatus()}
          >
            {t("systemStatus.refresh", "Refresh")}
          </Button>
        }
      />

      <main className={styles.content}>
        {loading && status === null ? (
          <div className={styles.centerState}>
            <Spin size="large" />
            <Text type="secondary">
              {t("systemStatus.loading", "Loading storage status…")}
            </Text>
          </div>
        ) : error ? (
          <Alert
            type="error"
            showIcon
            message={t(
              "systemStatus.error.title",
              "Unable to load storage status",
            )}
            description={
              <div className={styles.errorDescription}>
                <span>{error}</span>
                <Button size="small" onClick={() => void loadStatus()}>
                  {t("systemStatus.retry", "Retry")}
                </Button>
              </div>
            }
          />
        ) : status ? (
          <>
            <section className={styles.hero}>
              <div>
                <div className={styles.eyebrow}>
                  {t("systemStatus.overview", "Storage overview")}
                </div>
                <Title level={2} className={styles.heroTitle}>
                  {legacyActive
                    ? t("systemStatus.hero.legacy", "Legacy storage is active")
                    : mixedActive
                    ? t("systemStatus.hero.mixed", "Domain cutover is in progress")
                    : t(
                        "systemStatus.hero.postgres",
                        "PostgreSQL storage is active",
                      )}
                </Title>
                <Text className={styles.heroDescription}>
                  {legacyActive
                    ? t(
                        "systemStatus.hero.legacyDescription",
                        "Business repositories still use the original file storage path.",
                      )
                    : mixedActive
                    ? t(
                        "systemStatus.hero.mixedDescription",
                        "Repositories are split by the explicit domain cutover policy.",
                      )
                    : t(
                        "systemStatus.hero.postgresDescription",
                        "Business repositories are using the configured PostgreSQL path.",
                      )}
                </Text>
              </div>
              <Tag color={legacyActive ? "gold" : mixedActive ? "blue" : "green"}>
                {status.active_repository.toUpperCase()}
              </Tag>
            </section>

            <section
              className={styles.grid}
              aria-label="Storage status details"
            >
              <StatusCard
                icon={<Database size={20} />}
                title={t("systemStatus.database.title", "Database")}
                value={databaseLabel}
                detail={status.error_code ?? t("systemStatus.normal", "Normal")}
                tone={
                  status.connected || status.storage_mode === "legacy"
                    ? "ok"
                    : "error"
                }
              />
              <StatusCard
                icon={<HardDrive size={20} />}
                title={t("systemStatus.repository.title", "Active repository")}
                value={
                  status.active_repository === "legacy"
                    ? t("systemStatus.repository.legacy", "Legacy file storage")
                    : status.active_repository === "mixed"
                    ? t("systemStatus.repository.mixed", "Mixed by domain")
                    : "PostgreSQL"
                }
                detail={`${t(
                  "systemStatus.repository.configured",
                  "Configured mode",
                )}: ${status.storage_mode}`}
                tone={
                  status.active_repository === status.storage_mode
                    ? "ok"
                    : "warning"
                }
              />
              <StatusCard
                icon={<Layers3 size={20} />}
                title={t("systemStatus.schema.title", "Schema version")}
                value={status.schema_version ?? "—"}
                detail={`${t("systemStatus.schema.expected", "Expected")}: ${
                  status.expected_schema_version
                }`}
                tone={status.schema_ready ? "ok" : "neutral"}
              />
              <StatusCard
                icon={<LockKeyhole size={20} />}
                title={t("systemStatus.lock.title", "Migration lock")}
                value={lockLabel}
                detail={t(
                  "systemStatus.lock.description",
                  "This phase does not acquire or modify migration locks.",
                )}
                tone="neutral"
              />
            </section>

            {status.domains.length > 0 ? (
              <section className={styles.domainSection} aria-label="Domain cutover status">
                <Title level={4}>
                  {t("systemStatus.domains.title", "Domain cutover")}
                </Title>
                <div className={styles.domainGrid}>
                  {status.domains.map((domain) => (
                    <Card key={domain.domain} size="small" className={styles.domainCard}>
                      <div className={styles.domainHeader}>
                        <Text strong>{domain.domain}</Text>
                        <Tag color={domain.read_repository === "postgres" ? "green" : "gold"}>
                          {domain.read_repository.toUpperCase()}
                        </Tag>
                      </div>
                      <Text type="secondary">
                        {domain.migration_validated &&
                        domain.legacy_writes_frozen &&
                        domain.postgres_writes_open
                          ? t("systemStatus.domains.complete", "Validated · Legacy writes frozen · PostgreSQL writes open")
                          : t("systemStatus.domains.pending", "Cutover gate incomplete")}
                      </Text>
                    </Card>
                  ))}
                </div>
              </section>
            ) : null}

            <Alert
              className={styles.safetyNote}
              type="info"
              showIcon
              message={t(
                "systemStatus.readOnly.title",
                "Read-only diagnostics",
              )}
              description={t(
                "systemStatus.readOnly.description",
                "This page exposes sanitized health information only. It cannot migrate, rebuild, delete, or switch storage.",
              )}
            />
          </>
        ) : null}
      </main>
    </div>
  );
}

function StatusCard({
  icon,
  title,
  value,
  detail,
  tone,
}: {
  icon: React.ReactNode;
  title: string;
  value: React.ReactNode;
  detail: React.ReactNode;
  tone: "ok" | "warning" | "error" | "neutral";
}) {
  return (
    <Card
      className={`${styles.statusCard} ${styles[tone]}`}
      variant="borderless"
    >
      <div className={styles.cardHeader}>
        <span className={styles.cardIcon}>{icon}</span>
        <Text type="secondary">{title}</Text>
      </div>
      <div className={styles.cardValue}>{value}</div>
      <Text type="secondary" className={styles.cardDetail}>
        {detail}
      </Text>
    </Card>
  );
}

export default SystemStatusPage;
