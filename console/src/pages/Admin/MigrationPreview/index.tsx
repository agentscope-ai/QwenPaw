import { Alert, Button, Card, Spin, Table, Tag, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import { Fingerprint, RefreshCw, ScanSearch, ShieldCheck } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  migrationApi,
  type MigrationDomain,
  type MigrationDomainStatus,
  type MigrationPreview,
} from "@/api/modules/migration";
import { PageHeader } from "@/components/PageHeader";

import styles from "./index.module.less";

const { Text, Title } = Typography;

const STATUS_COLOR: Record<MigrationDomainStatus, string> = {
  ready: "green",
  empty: "default",
  rejected: "red",
  unavailable: "gold",
};

function MigrationPreviewPage() {
  const { t } = useTranslation();
  const [preview, setPreview] = useState<MigrationPreview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadPreview = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setPreview(await migrationApi.getPreview());
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadPreview();
  }, [loadPreview]);

  const columns = useMemo<ColumnsType<MigrationDomain>>(
    () => [
      {
        title: t("migrationPreview.columns.domain", "Domain"),
        dataIndex: "label",
        width: 150,
        render: (label: string, row) => (
          <div>
            <strong>{label}</strong>
            <div className={styles.muted}>{row.key}</div>
          </div>
        ),
      },
      {
        title: t("migrationPreview.columns.status", "Status"),
        dataIndex: "status",
        width: 110,
        render: (status: MigrationDomainStatus) => (
          <Tag color={STATUS_COLOR[status]}>{status}</Tag>
        ),
      },
      {
        title: t("migrationPreview.columns.count", "Records"),
        dataIndex: "count",
        width: 100,
      },
      {
        title: t("migrationPreview.columns.mapping", "Mapping"),
        dataIndex: "mapping",
        render: (mapping: Record<string, string>) =>
          Object.entries(mapping).map(([source, target]) => (
            <div key={source} className={styles.mapping}>
              {source} → {target}
            </div>
          )),
      },
      {
        title: t("migrationPreview.columns.hash", "Source hash"),
        dataIndex: "source_hash",
        render: (hash: string) => <code className={styles.hash}>{hash}</code>,
      },
      {
        title: t("migrationPreview.columns.issues", "Issues"),
        width: 190,
        render: (_, row) => {
          const issues = [...row.conflicts, ...row.rejected];
          return issues.length ? (
            <div className={styles.issueList}>
              {issues.map((issue, index) => (
                <Text type="danger" key={`${issue.code}-${index}`}>
                  {issue.detail}
                </Text>
              ))}
            </div>
          ) : (
            "—"
          );
        },
      },
    ],
    [t],
  );

  return (
    <div className={styles.page}>
      <PageHeader
        parent={t("nav.settings", "Settings")}
        current={t("migrationPreview.title", "Migration Preview")}
        extra={
          <Button
            icon={<RefreshCw size={15} />}
            loading={loading && preview !== null}
            onClick={() => void loadPreview()}
          >
            {t("migrationPreview.scanAgain", "Scan again")}
          </Button>
        }
      />

      <main className={styles.content}>
        {loading && preview === null ? (
          <div className={styles.centerState}>
            <Spin size="large" />
            <Text type="secondary">
              {t("migrationPreview.loading", "Scanning legacy sources…")}
            </Text>
          </div>
        ) : error ? (
          <Alert
            type="error"
            showIcon
            message={t(
              "migrationPreview.error",
              "Unable to scan legacy sources",
            )}
            description={error}
            action={
              <Button size="small" onClick={() => void loadPreview()}>
                {t("common.retry", "Retry")}
              </Button>
            }
          />
        ) : preview ? (
          <>
            <section className={styles.hero}>
              <div className={styles.heroIcon}>
                <ScanSearch size={24} />
              </div>
              <div>
                <Title level={2} className={styles.heroTitle}>
                  {t("migrationPreview.hero", "Read-only migration preview")}
                </Title>
                <Text type="secondary">
                  {t(
                    "migrationPreview.description",
                    "This scan only reads legacy sources. It does not write target data or start a migration.",
                  )}
                </Text>
              </div>
              <Tag color="blue">READ ONLY</Tag>
            </section>

            <section className={styles.summaryGrid}>
              <SummaryCard
                label={t("migrationPreview.summary.domains", "Domains")}
                value={preview.summary.domain_count}
              />
              <SummaryCard
                label={t("migrationPreview.summary.records", "Records")}
                value={preview.summary.item_count}
              />
              <SummaryCard
                label={t("migrationPreview.summary.conflicts", "Conflicts")}
                value={preview.summary.conflict_count}
              />
              <SummaryCard
                label={t("migrationPreview.summary.rejected", "Rejected")}
                value={preview.summary.rejected_count}
              />
              <SummaryCard
                label={t(
                  "migrationPreview.summary.secrets",
                  "Secret references",
                )}
                value={preview.summary.secret_reference_count}
              />
            </section>

            <Alert
              className={styles.integrity}
              type={preview.integrity.unchanged ? "success" : "error"}
              showIcon
              message={
                preview.integrity.unchanged
                  ? t("migrationPreview.unchanged", "Source data unchanged")
                  : t(
                      "migrationPreview.changed",
                      "Source data changed during scan",
                    )
              }
              description={
                <code className={styles.hash}>
                  {preview.integrity.after_hash}
                </code>
              }
            />

            <Card
              className={styles.section}
              title={t("migrationPreview.domains", "Migration domains")}
            >
              <Table
                rowKey="key"
                columns={columns}
                dataSource={preview.domains}
                pagination={false}
                scroll={{ x: 980 }}
              />
            </Card>

            <Card
              className={styles.section}
              title={
                <span className={styles.cardTitle}>
                  <ShieldCheck size={17} />
                  {t("migrationPreview.secretRefs", "Secret references")}
                </span>
              }
            >
              {preview.secret_references.length ? (
                <div className={styles.secretList}>
                  {preview.secret_references.map((secret) => (
                    <div key={secret.reference} className={styles.secretRow}>
                      <Fingerprint size={16} />
                      <code>{secret.reference}</code>
                      <Tag
                        color={
                          secret.version === "plaintext" ? "orange" : "green"
                        }
                      >
                        {secret.version}
                      </Tag>
                    </div>
                  ))}
                </div>
              ) : (
                <Text type="secondary">
                  {t(
                    "migrationPreview.noSecrets",
                    "No secret references found",
                  )}
                </Text>
              )}
            </Card>
          </>
        ) : null}
      </main>
    </div>
  );
}

function SummaryCard({ label, value }: { label: string; value: number }) {
  return (
    <Card className={styles.summaryCard} variant="borderless">
      <div className={styles.summaryValue}>{value}</div>
      <Text type="secondary">{label}</Text>
    </Card>
  );
}

export default MigrationPreviewPage;
