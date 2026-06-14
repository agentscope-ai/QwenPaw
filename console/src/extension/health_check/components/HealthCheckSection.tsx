import { useCallback, useEffect, useMemo, useState } from "react";
import { Button, Card, Table, Tag } from "@agentscope-ai/design";
import { Collapse, Modal, Popconfirm, Segmented, Spin, message } from "antd";
import { useTranslation } from "react-i18next";
import api from "@/api";
import type { HealthCheckItem, HealthCheckScanResponse } from "../api/client";
import {
  type SecurityTabKey,
  needsManualAction,
  resolveSecurityTabLink,
} from "../lib/actionLinks";
import {
  ENVIRONMENT_INFO_ITEM_IDS,
  formatDetailSummary,
  formatGuidance,
  isIssueItem,
  isVisibleCheckItem,
  statusTagColor,
} from "../lib/detailMessages";
import { canShowFixAction, isHighRiskFix } from "../lib/fixRisk";
import {
  CAROUSEL_DISPLAY_DURATION_MS,
  TERMINAL_CAROUSEL_KEYS,
  TERMINAL_SCAN_STATES,
  getString,
  type HealthCheckRecord,
} from "../lib/scanUi";
import {
  SESSION_SCAN_STORAGE_KEY,
  summarizeCheckItems,
} from "../lib/scanSummary";
import styles from "@/pages/Settings/Security/index.module.less";

export interface HealthCheckSectionProps {
  onAttentionCountChange?: (count: number) => void;
  onNavigateSecurityTab?: (tabKey: SecurityTabKey) => void;
}

type StoredHealthCheckScan = {
  completedAt: number;
  scan: HealthCheckScanResponse;
};

function loadStoredScan(): {
  scan: HealthCheckScanResponse | null;
  completedAt: number | null;
} {
  try {
    const raw = sessionStorage.getItem(SESSION_SCAN_STORAGE_KEY);
    if (!raw) {
      return { scan: null, completedAt: null };
    }
    const parsed = JSON.parse(raw) as StoredHealthCheckScan | HealthCheckScanResponse;
    if (parsed && typeof parsed === "object" && "scan" in parsed && parsed.scan) {
      return {
        scan: parsed.scan,
        completedAt: typeof parsed.completedAt === "number" ? parsed.completedAt : null,
      };
    }
    if (
      parsed &&
      typeof parsed === "object" &&
      Array.isArray((parsed as HealthCheckScanResponse).check_items)
    ) {
      return { scan: parsed as HealthCheckScanResponse, completedAt: null };
    }
    return { scan: null, completedAt: null };
  } catch {
    return { scan: null, completedAt: null };
  }
}

function storeScan(scan: HealthCheckScanResponse) {
  try {
    const payload: StoredHealthCheckScan = {
      completedAt: Date.now(),
      scan,
    };
    sessionStorage.setItem(SESSION_SCAN_STORAGE_KEY, JSON.stringify(payload));
  } catch {
    // ignore quota / private mode
  }
}

/** All clear → show full checklist; issues → focus on problems first. */
function defaultShowIssuesOnly(scan: HealthCheckScanResponse | null): boolean {
  if (!scan) {
    return true;
  }
  const visible = scan.check_items.filter((item) => isVisibleCheckItem(item));
  return summarizeCheckItems(visible).attention > 0;
}

export function HealthCheckSection({
  onAttentionCountChange,
  onNavigateSecurityTab,
}: HealthCheckSectionProps) {
  const { t } = useTranslation();
  const initialStored = loadStoredScan();
  const [scan, setScan] = useState<HealthCheckScanResponse | null>(initialStored.scan);
  const [loading, setLoading] = useState(false);
  const [fixingId, setFixingId] = useState<string | null>(null);
  const [highRiskFixId, setHighRiskFixId] = useState<string | null>(null);
  const [scanError, setScanError] = useState<string | null>(null);
  const [currentCheckIndex, setCurrentCheckIndex] = useState(0);
  const [expandedTechnical, setExpandedTechnical] = useState<Record<string, boolean>>({});
  const [showIssuesOnly, setShowIssuesOnly] = useState(() =>
    defaultShowIssuesOnly(initialStored.scan),
  );
  const [lastCompletedAt, setLastCompletedAt] = useState<number | null>(initialStored.completedAt);

  const runScan = useCallback(async () => {
    setLoading(true);
    setScanError(null);
    setCurrentCheckIndex(0);
    setExpandedTechnical({});
    try {
      const result = await api.runIntegrityHealthCheckScan(false);
      setScan(result);
      storeScan(result);
      setLastCompletedAt(Date.now());
      setShowIssuesOnly(defaultShowIssuesOnly(result));
    } catch (error) {
      setScanError(
        error instanceof Error ? error.message : t("security.healthCheck.loadFailed"),
      );
    } finally {
      setLoading(false);
    }
  }, [t]);

  const visibleCheckItems = useMemo(() => {
    return (scan?.check_items ?? []).filter((item) => isVisibleCheckItem(item));
  }, [scan]);

  const summary = useMemo(
    () => summarizeCheckItems(visibleCheckItems),
    [visibleCheckItems],
  );

  useEffect(() => {
    onAttentionCountChange?.(summary.attention);
  }, [onAttentionCountChange, summary.attention]);

  const tablePrimaryItems = useMemo(() => {
    if (showIssuesOnly) {
      return visibleCheckItems.filter((item) => isIssueItem(item));
    }
    if (summary.attention === 0) {
      return visibleCheckItems;
    }
    return visibleCheckItems.filter(
      (item) =>
        !(ENVIRONMENT_INFO_ITEM_IDS.has(item.id) && item.status === "ok"),
    );
  }, [showIssuesOnly, summary.attention, visibleCheckItems]);

  const collapsedEnvironmentItems = useMemo(() => {
    if (showIssuesOnly || summary.attention === 0) {
      return [];
    }
    return visibleCheckItems.filter(
      (item) => ENVIRONMENT_INFO_ITEM_IDS.has(item.id) && item.status === "ok",
    );
  }, [showIssuesOnly, summary.attention, visibleCheckItems]);

  const checkItemIds = useMemo(() => {
    return visibleCheckItems.map((item) => item.id).filter(Boolean);
  }, [visibleCheckItems]);

  const currentCheckId =
    checkItemIds[currentCheckIndex % Math.max(checkItemIds.length, 1)] ?? "";
  const scanStatus = loading ? "running" : scanError ? "failed" : scan ? "completed" : null;
  const isTerminalState =
    scanStatus !== null && TERMINAL_SCAN_STATES.includes(scanStatus);
  const currentCheck = loading
    ? t("security.healthCheck.carousel.runningHint")
    : scanStatus
      ? t(
          TERMINAL_CAROUSEL_KEYS[scanStatus] ??
            "security.healthCheck.carousel.idle",
        )
      : t("security.healthCheck.carousel.idle");

  useEffect(() => {
    if (!loading || checkItemIds.length < 2) {
      return undefined;
    }
    const carousel = window.setInterval(() => {
      setCurrentCheckIndex((index) => (index + 1) % checkItemIds.length);
    }, CAROUSEL_DISPLAY_DURATION_MS);
    return () => {
      window.clearInterval(carousel);
    };
  }, [checkItemIds.length, loading]);

  useEffect(() => {
    if (isTerminalState) {
      setCurrentCheckIndex(0);
    }
  }, [isTerminalState]);

  const executeFix = async (fixId: string) => {
    setFixingId(fixId);
    try {
      const result = await api.runIntegrityHealthCheckFix(fixId);
      if (result.executed && result.exit_code === 0) {
        message.success(t("security.healthCheck.fix.success"));
        await runScan();
      } else {
        message.error(t("security.healthCheck.fix.failed"));
      }
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : t("security.healthCheck.fix.failed"),
      );
    } finally {
      setFixingId(null);
      setHighRiskFixId(null);
    }
  };

  const renderDetailCell = (record: HealthCheckRecord) => {
    const rowId = getString(record, "id");
    const rawDetail = getString(record, "detail");
    const summaryText = formatDetailSummary(record, t);
    const showTechnical = Boolean(rawDetail && rawDetail !== summaryText);
    const expanded = expandedTechnical[rowId] ?? false;

    return (
      <div>
        <div>{summaryText}</div>
        {showTechnical && (
          <Button
            type="link"
            size="small"
            style={{ paddingInline: 0, height: "auto" }}
            onClick={() =>
              setExpandedTechnical((prev) => ({
                ...prev,
                [rowId]: !expanded,
              }))
            }
          >
            {expanded
              ? t("security.healthCheck.details.hideTechnical")
              : t("security.healthCheck.details.showTechnical")}
          </Button>
        )}
        {showTechnical && expanded && (
          <pre className={styles.healthCheckTechnicalDetail}>{rawDetail}</pre>
        )}
      </div>
    );
  };

  const renderActionCell = (record: HealthCheckRecord) => {
    const fixId = getString(record, "fix_id");
    const status = getString(record, "status");

    if (canShowFixAction(fixId || null, status)) {
      const button = (
        <Button
          size="small"
          loading={fixingId === fixId}
          disabled={Boolean(fixingId && fixingId !== fixId)}
          onClick={
            isHighRiskFix(fixId) ? () => setHighRiskFixId(fixId) : undefined
          }
        >
          {t("security.healthCheck.fix.action")}
        </Button>
      );

      if (isHighRiskFix(fixId)) {
        return button;
      }

      return (
        <Popconfirm
          title={t("security.healthCheck.fix.confirmTitle")}
          description={t("security.healthCheck.fix.confirmDescription")}
          okText={t("security.healthCheck.fix.confirmOk")}
          cancelText={t("security.healthCheck.fix.confirmCancel")}
          onConfirm={() => executeFix(fixId)}
        >
          {button}
        </Popconfirm>
      );
    }

    if (!needsManualAction(record)) {
      return "—";
    }

    const tabLink = resolveSecurityTabLink(record);
    if (tabLink && onNavigateSecurityTab) {
      return (
        <Button
          type="link"
          size="small"
          style={{ paddingInline: 0, height: "auto" }}
          onClick={() => onNavigateSecurityTab(tabLink)}
        >
          {t(`security.healthCheck.actions.gotoTab.${tabLink}`)}
        </Button>
      );
    }

    return (
      <span className={styles.healthCheckManualAction}>
        {t("security.healthCheck.actions.manual")}
      </span>
    );
  };

  const tableColumns = [
    {
      title: t("security.healthCheck.columns.group"),
      dataIndex: "group",
      key: "group",
      render: (group: string) => (
        <Tag color="blue">
          {t(`security.healthCheck.groups.${group}`, {
            defaultValue: group,
          })}
        </Tag>
      ),
    },
    {
      title: t("security.healthCheck.columns.check"),
      dataIndex: "label",
      key: "label",
      render: (_label: string, record: HealthCheckRecord) =>
        t(`security.healthCheck.scanItems.${getString(record, "id")}`, {
          defaultValue: getString(record, "label"),
        }),
    },
    {
      title: t("security.healthCheck.columns.status"),
      dataIndex: "status",
      key: "status",
      render: (status: string) => (
        <Tag color={statusTagColor(status)}>
          {t(`security.healthCheck.itemStatus.${status}`, {
            defaultValue: status,
          })}
        </Tag>
      ),
    },
    {
      title: t("security.healthCheck.columns.detail"),
      dataIndex: "detail",
      key: "detail",
      render: (_detail: string, record: HealthCheckRecord) => renderDetailCell(record),
    },
    {
      title: t("security.healthCheck.columns.guidance"),
      dataIndex: "risk",
      key: "guidance",
      render: (_risk: string, record: HealthCheckRecord) => formatGuidance(record, t),
    },
    {
      title: t("security.healthCheck.columns.action"),
      key: "action",
      render: (_value: unknown, record: HealthCheckRecord) => renderActionCell(record),
    },
  ];

  const renderEmptyState = () => {
    if (!scan) {
      return (
        <div className={styles.healthCheckEmptyState}>
          <p>{t("security.healthCheck.emptyState.intro")}</p>
          <ol className={styles.healthCheckSteps}>
            <li>{t("security.healthCheck.emptyState.step1")}</li>
            <li>{t("security.healthCheck.emptyState.step2")}</li>
            <li>{t("security.healthCheck.emptyState.step3")}</li>
          </ol>
        </div>
      );
    }
    if (showIssuesOnly && summary.attention === 0) {
      return (
        <div className={styles.healthCheckEmptyState}>
          <p>{t("security.healthCheck.summary.allClear")}</p>
        </div>
      );
    }
    return t("security.healthCheck.emptyCheckItems");
  };

  const renderEnvironmentCollapse = () => {
    if (collapsedEnvironmentItems.length === 0) {
      return null;
    }
    return (
      <Collapse
        className={styles.healthCheckEnvCollapse}
        items={[
          {
            key: "environment",
            label: t("security.healthCheck.environmentCollapse.title", {
              count: collapsedEnvironmentItems.length,
            }),
            children: (
              <Table
                rowKey={(record: HealthCheckItem) => String(record.id)}
                dataSource={collapsedEnvironmentItems}
                pagination={false}
                size="small"
                showHeader={false}
                columns={[
                  {
                    key: "check",
                    render: (_value, record) =>
                      t(`security.healthCheck.scanItems.${getString(record, "id")}`, {
                        defaultValue: getString(record, "label"),
                      }),
                  },
                  {
                    key: "detail",
                    render: (_value, record) => formatDetailSummary(record, t),
                  },
                ]}
              />
            ),
          },
        ]}
      />
    );
  };

  return (
    <div className={styles.sectionFileGuardContainer}>
      <Card className={styles.formCard}>
        <div className={styles.sectionHeader}>
          <h3 className={styles.sectionTitle}>{t("security.healthCheck.panelTitle")}</h3>
          <Button type="primary" loading={loading} onClick={() => void runScan()}>
            {scan ? t("security.healthCheck.runCheckAgain") : t("security.healthCheck.runCheck")}
          </Button>
        </div>

        {loading && (
          <div className={styles.healthCheckRunning}>
            <Spin size="small" />
            <span>
              {t("security.healthCheck.carousel.currentPrefix", {
                item: currentCheckId
                  ? t(`security.healthCheck.scanItems.${currentCheckId}`)
                  : t("security.healthCheck.carousel.idle"),
              })}
            </span>
          </div>
        )}

        {!loading && (
          <div className={styles.integrityResult} data-terminal={isTerminalState}>
            <Tag color={scanError ? "red" : scan ? "green" : "default"}>
              {scanStatus
                ? t(`security.healthCheck.status.${scanStatus}`)
                : t("security.healthCheck.status.idle")}
            </Tag>
            <span>{currentCheck}</span>
          </div>
        )}

        {scan && !loading && !scanError && (
          <div className={styles.healthCheckSummary}>
            <span>
              {summary.attention === 0
                ? t("security.healthCheck.summary.allClearHeadline", summary)
                : t("security.healthCheck.summary.headline", summary)}
            </span>
            {lastCompletedAt && (
              <span className={styles.healthCheckSummaryMeta}>
                {t("security.healthCheck.summary.lastRun", {
                  time: new Date(lastCompletedAt).toLocaleString(),
                })}
              </span>
            )}
          </div>
        )}

        {scanError && (
          <div className={styles.healthCheckErrorBlock}>
            <p>{t("security.healthCheck.errorHint")}</p>
            <Button size="small" onClick={() => void runScan()}>
              {t("security.healthCheck.retry")}
            </Button>
          </div>
        )}
      </Card>

      <Card className={styles.tableCard}>
        {scan && (
          <div className={styles.healthCheckTableToolbar}>
            <Segmented
              value={showIssuesOnly ? "issues" : "all"}
              onChange={(value) => setShowIssuesOnly(value === "issues")}
              options={[
                {
                  label: t("security.healthCheck.view.issuesOnly"),
                  value: "issues",
                },
                {
                  label: t("security.healthCheck.view.all"),
                  value: "all",
                },
              ]}
            />
          </div>
        )}
        <Table
          rowKey={(record) => String(record.id)}
          dataSource={scan ? tablePrimaryItems : []}
          pagination={false}
          size="small"
          locale={{ emptyText: renderEmptyState() }}
          columns={tableColumns}
        />
        {renderEnvironmentCollapse()}
      </Card>

      <Modal
        open={highRiskFixId !== null}
        title={t("security.healthCheck.fix.highRiskTitle")}
        okText={t("security.healthCheck.fix.confirmOk")}
        cancelText={t("security.healthCheck.fix.confirmCancel")}
        confirmLoading={fixingId !== null}
        onOk={() => {
          if (highRiskFixId) {
            void executeFix(highRiskFixId);
          }
        }}
        onCancel={() => setHighRiskFixId(null)}
      >
        {highRiskFixId
          ? t(`security.healthCheck.fix.highRisk.${highRiskFixId}`, {
              defaultValue: t("security.healthCheck.fix.highRiskDefault"),
            })
          : null}
      </Modal>
    </div>
  );
}
