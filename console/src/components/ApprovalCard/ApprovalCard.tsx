import { useState, useEffect, useCallback } from "react";
import { Button, Card, Tag, Typography, Space } from "antd";
import { Shield, Check, X, Clock, Copy } from "lucide-react";
import { useTranslation } from "react-i18next";
import styles from "./ApprovalCard.module.less";

const { Text } = Typography;

export interface ApprovalCardProps {
  requestId: string;
  toolName: string;
  severity: string;
  findingsCount: number;
  findingsSummary: string;
  toolParams: Record<string, unknown>;
  createdAt: number;
  timeoutSeconds: number;
  sessionId?: string;
  rootSessionId?: string;
  onApprove: (requestId: string) => Promise<void>;
  onDeny: (requestId: string) => Promise<void>;
  onCancel?: () => void;
}

export function ApprovalCard({
  requestId,
  toolName,
  severity,
  findingsCount,
  findingsSummary,
  toolParams,
  createdAt,
  timeoutSeconds,
  sessionId,
  rootSessionId,
  onApprove,
  onDeny,
  onCancel,
}: ApprovalCardProps) {
  const { t } = useTranslation();
  const [loading, setLoading] = useState<"approve" | "deny" | null>(null);
  const [remaining, setRemaining] = useState<number>(timeoutSeconds);
  const [copiedField, setCopiedField] = useState<string | null>(null);

  const handleCopy = useCallback(async (text: string, field: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedField(field);
      setTimeout(() => setCopiedField(null), 1500);
    } catch {
      /* clipboard not available */
    }
  }, []);

  // Check if this is a cross-session approval
  const isCrossSession =
    sessionId && rootSessionId && sessionId !== rootSessionId;

  useEffect(() => {
    const elapsed = Date.now() / 1000 - createdAt;
    const initialRemaining = Math.max(0, Math.floor(timeoutSeconds - elapsed));
    setRemaining(initialRemaining);

    const timer = setInterval(() => {
      const newElapsed = Date.now() / 1000 - createdAt;
      const newRemaining = Math.max(0, Math.floor(timeoutSeconds - newElapsed));
      setRemaining(newRemaining);

      if (newRemaining <= 0) {
        clearInterval(timer);
      }
    }, 1000);

    return () => clearInterval(timer);
  }, [createdAt, timeoutSeconds]);

  const handleApprove = async () => {
    console.log("[ApprovalCard] Approve button clicked:", requestId);
    setLoading("approve");
    try {
      await onApprove(requestId);
      console.log("[ApprovalCard] onApprove completed");
    } catch (err) {
      console.error("[ApprovalCard] onApprove failed:", err);
    } finally {
      setLoading(null);
    }
  };

  const handleDeny = async () => {
    setLoading("deny");
    try {
      await onDeny(requestId);
    } finally {
      setLoading(null);
    }
  };

  const getSeverityColor = (sev: string) => {
    const s = sev.toLowerCase();
    if (s === "critical" || s === "high") return "error";
    if (s === "medium") return "warning";
    return "default";
  };

  return (
    <Card className={styles.approvalCard} bordered={false}>
      <div className={styles.header}>
        <Space size={8} align="center" className={styles.titleRow}>
          <Shield size={16} className={styles.icon} />
          <Text className={styles.title}>
            {t("approval.title", "Security Approval Required")}
          </Text>
        </Space>
        <Space size={6} align="center" className={styles.timer}>
          <Clock size={14} className={styles.timerIcon} />
          <Text className={styles.timerText}>
            {Math.floor(remaining / 60)}:
            {String(remaining % 60).padStart(2, "0")}
          </Text>
        </Space>
      </div>

      <div className={styles.content}>
        <div className={styles.infoRow}>
          <Text className={styles.label}>{t("approval.tool", "Tool")}:</Text>
          <Text className={styles.value} code>
            {toolName}
          </Text>
        </div>

        <div className={styles.infoRow}>
          <Text className={styles.label}>
            {t("approval.severity", "Severity")}:
          </Text>
          <Tag
            color={getSeverityColor(severity)}
            className={styles.severityTag}
          >
            {severity.toUpperCase()}
          </Tag>
        </div>

        <div className={styles.infoRow}>
          <Text className={styles.label}>
            {t("approval.findings", "Findings")}:
          </Text>
          <Text className={styles.value}>{findingsCount}</Text>
        </div>

        {isCrossSession && (
          <div className={styles.infoRow}>
            <Text className={styles.label}>
              {t("approval.source", "Source")}:
            </Text>
            <Tag color="blue" className={styles.crossSessionTag}>
              {t("approval.subSession", "Sub-Agent")} ({sessionId?.slice(0, 8)})
            </Tag>
          </div>
        )}

        {findingsSummary && (
          <div className={styles.summaryBox}>
            <Text className={styles.summaryText}>{findingsSummary}</Text>
            <button
              className={`${styles.copyButton} ${copiedField === "summary" ? styles.copied : ""
                }`}
              onClick={() => handleCopy(findingsSummary, "summary")}
              title={t("common.copy", "Copy")}
            >
              <Copy size={12} />
            </button>
          </div>
        )}

        {toolParams && Object.keys(toolParams).length > 0 && (
          <details className={styles.paramsDetails}>
            <summary className={styles.paramsSummary}>
              {t("approval.parameters", "Parameters")}
            </summary>
            <div className={styles.paramsCodeWrapper}>
              <pre className={styles.paramsCode}>
                {JSON.stringify(toolParams, null, 2)}
              </pre>
              <button
                className={`${styles.copyButton} ${copiedField === "params" ? styles.copied : ""
                  }`}
                onClick={() =>
                  handleCopy(JSON.stringify(toolParams, null, 2), "params")
                }
                title={t("common.copy", "Copy")}
              >
                <Copy size={12} />
              </button>
            </div>
          </details>
        )}
      </div>

      <div className={styles.actions}>
        {onCancel && (
          <Button
            type="default"
            onClick={() => {
              console.log("[ApprovalCard] Cancel task button clicked");
              onCancel();
            }}
            disabled={loading !== null}
          >
            {t("approval.cancelTask", "Cancel Task")}
          </Button>
        )}
        <Button
          danger
          icon={<X size={14} />}
          onClick={handleDeny}
          loading={loading === "deny"}
          disabled={loading !== null}
        >
          {t("approval.deny", "Deny")}
        </Button>
        <Button
          type="primary"
          icon={<Check size={14} />}
          onClick={handleApprove}
          loading={loading === "approve"}
          disabled={loading !== null}
        >
          {t("approval.approve", "Approve")}
        </Button>
      </div>
    </Card>
  );
}
