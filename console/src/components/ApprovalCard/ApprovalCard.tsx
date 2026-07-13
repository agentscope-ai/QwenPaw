import { useState, useEffect, useCallback, useMemo } from "react";
import { Button, Card, Tag, Typography, Space, Tooltip } from "antd";
import { Shield, Check, X, Clock, Copy, Info, AlertCircle } from "lucide-react";
import type { ToolExecutionLevel } from "../../utils/approval";
import { useTranslation } from "react-i18next";
import { useAgentStore } from "../../stores/agentStore";
import { getAgentDisplayName } from "../../utils/agentDisplayName";
import styles from "./ApprovalCard.module.less";

const { Text } = Typography;

export interface ApprovalCardProps {
  requestId: string;
  toolName: string;
  toolSource?: string;
  severity: string;
  findingsCount: number;
  findingsSummary: string;
  toolParams: Record<string, unknown>;
  createdAt: number;
  timeoutSeconds: number;
  agentId: string;
  ownerAgentId?: string;
  showInboxAgentContext?: boolean;
  sessionId?: string;
  rootSessionId?: string;
  // Approval-scope choice (console-only). When true the card renders
  // Approve Pattern + Approve Exact; when false, a single Approve button.
  isGeneralized?: boolean;
  exactTarget?: string;
  similarTarget?: string;
  executionLevel?: ToolExecutionLevel;
  onApprove: (requestId: string, scope?: "exact" | "similar") => Promise<void>;
  onDeny: (requestId: string) => Promise<void>;
  onCancel?: () => void;
  onAcknowledge?: (requestId: string) => Promise<void>;
}

export function ApprovalCard({
  requestId,
  toolName,
  toolSource,
  severity,
  findingsCount,
  findingsSummary,
  toolParams,
  createdAt,
  timeoutSeconds,
  agentId,
  ownerAgentId,
  showInboxAgentContext = false,
  sessionId,
  rootSessionId,
  isGeneralized,
  exactTarget,
  similarTarget,
  executionLevel,
  onApprove,
  onDeny,
  onCancel: _onCancel,
  onAcknowledge,
}: ApprovalCardProps) {
  const { t } = useTranslation();
  const isStrictMode = executionLevel === "STRICT";
  const agents = useAgentStore((state) => state.agents);
  const agentsById = useMemo(
    () => new Map(agents.map((agent) => [agent.id, agent])),
    [agents],
  );
  const [loading, setLoading] = useState<
    "approve-pattern" | "approve-exact" | "deny" | "acknowledge" | null
  >(null);
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
  const isTimedOut = showInboxAgentContext && remaining <= 0;
  const executionAgentDisplayName = useMemo(() => {
    const matched = agentsById.get(agentId);
    if (matched) return getAgentDisplayName(matched, t);
    return agentId || t("common.unknown", "Unknown");
  }, [agentsById, agentId, t]);
  const ownerAgentDisplayName = useMemo(() => {
    const ownerId = ownerAgentId || agentId;
    const matched = agentsById.get(ownerId);
    if (matched) return getAgentDisplayName(matched, t);
    return ownerId || t("common.unknown", "Unknown");
  }, [agentsById, ownerAgentId, agentId, t]);
  const shouldShowExecutionAgent =
    showInboxAgentContext && Boolean(isCrossSession);
  const displayToolSource =
    toolSource && toolSource !== "builtin"
      ? toolSource
      : t("approval.builtinSource", "Built-in");

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

  const handleApprove = async (scope?: "exact" | "similar") => {
    const loadingKey =
      scope === "similar" ? "approve-pattern" : "approve-exact";
    console.log(
      "[ApprovalCard] Approve button clicked:",
      requestId,
      "scope:",
      scope,
    );
    setLoading(loadingKey);
    try {
      await onApprove(requestId, scope);
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

  const handleAcknowledge = async () => {
    if (!onAcknowledge) return;
    setLoading("acknowledge");
    try {
      await onAcknowledge(requestId);
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
        {showInboxAgentContext ? (
          <>
            <div className={styles.infoRow}>
              <Text className={styles.label}>
                {t("approval.ownerAgent", "Owner Agent")}:
              </Text>
              <Tag color="success" className={styles.ownerAgentTag}>
                {ownerAgentDisplayName}
              </Tag>
            </div>
            {shouldShowExecutionAgent ? (
              <div className={styles.infoRow}>
                <Text className={styles.label}>
                  {t("approval.executingAgent", "Executing Agent")}:
                </Text>
                <Tag color="blue" className={styles.crossSessionTag}>
                  {executionAgentDisplayName}
                </Tag>
              </div>
            ) : null}
          </>
        ) : null}

        <div className={styles.infoRow}>
          <Text className={styles.label}>{t("approval.tool", "Tool")}:</Text>
          <Text className={styles.value} code>
            {toolName}
          </Text>
        </div>

        <div className={styles.infoRow}>
          <Text className={styles.label}>
            {t("approval.source", "Source")}:
          </Text>
          <Text className={styles.value} code>
            {displayToolSource}
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

        {isCrossSession && !showInboxAgentContext && (
          <div className={styles.infoRow}>
            <Text className={styles.label}>
              {t("approval.source", "Source")}:
            </Text>
            <Tag color="blue" className={styles.crossSessionTag}>
              {t("approval.subSession", "Sub-Agent")} ({sessionId?.slice(0, 8)})
            </Tag>
          </div>
        )}

        {isGeneralized && (exactTarget || similarTarget) && (
          <div className={styles.scopeSection}>
            <Text className={styles.scopeLabel}>
              {t("approval.approvalScope", "Approval scope")}:
            </Text>
            <div className={styles.scopeItems}>
              <div className={styles.scopeItem}>
                <Text className={styles.scopeItemLabel}>
                  {t("approval.approveExact", "Just Once")}:
                </Text>
                <code className={styles.scopeCode}>{exactTarget}</code>
              </div>
              <div className={styles.scopeItem}>
                <Text className={styles.scopeItemLabel}>
                  {t("approval.approvePattern", "Always Allow")}:
                </Text>
                <code className={styles.scopeCode}>{similarTarget}</code>
                {isStrictMode && (
                  <Tooltip
                    title={t(
                      "approval.strictModeHint",
                      "Always allow is unavailable in strict mode",
                    )}
                  >
                    <AlertCircle
                      size={14}
                      className={styles.strictModeHintIcon}
                    />
                  </Tooltip>
                )}
              </div>
            </div>
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
                className={`${styles.copyButton} ${
                  copiedField === "params" ? styles.copied : ""
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

        {findingsSummary && (
          <details className={styles.detailsSection}>
            <summary className={styles.detailsSummary}>
              <Info size={12} />
              {t("approval.details", "Details")}
            </summary>
            <div className={styles.detailsContent}>
              <pre className={styles.detailsText}>{findingsSummary}</pre>
              <button
                className={`${styles.copyButton} ${
                  copiedField === "details" ? styles.copied : ""
                }`}
                onClick={() => handleCopy(findingsSummary, "details")}
                title={t("common.copy", "Copy")}
              >
                <Copy size={12} />
              </button>
            </div>
          </details>
        )}
      </div>

      <div className={styles.actions}>
        {isTimedOut ? (
          <>
            <Text className={styles.timeoutHint}>
              {t("approval.timeoutAutoDenied", "Timed out, auto denied")}
            </Text>
            {onAcknowledge ? (
              <Button
                type="primary"
                onClick={handleAcknowledge}
                loading={loading === "acknowledge"}
                disabled={loading !== null}
              >
                {t("approval.acknowledge", "Got It")}
              </Button>
            ) : null}
          </>
        ) : (
          <>
            <Button
              danger
              icon={<X size={14} />}
              onClick={handleDeny}
              loading={loading === "deny"}
              disabled={loading !== null}
              className={styles.denyButton}
            >
              {t("approval.deny", "Deny")}
            </Button>
            {isGeneralized ? (
              <>
                <Button
                  onClick={() => handleApprove("exact")}
                  loading={loading === "approve-exact"}
                  disabled={loading !== null}
                  className={styles.approveOnceButton}
                >
                  {t("approval.approveExact", "Just Once")}
                </Button>
                <Tooltip
                  title={
                    isStrictMode
                      ? t(
                          "approval.strictModeHint",
                          "Always allow is unavailable in strict mode",
                        )
                      : undefined
                  }
                >
                  <Button
                    type="primary"
                    icon={<Check size={14} />}
                    onClick={() => handleApprove("similar")}
                    loading={loading === "approve-pattern"}
                    disabled={isStrictMode || loading !== null}
                    className={styles.approveAlwaysButton}
                  >
                    {t("approval.approvePattern", "Always Allow")}
                  </Button>
                </Tooltip>
              </>
            ) : (
              <Button
                type="primary"
                icon={<Check size={14} />}
                onClick={() => handleApprove()}
                loading={
                  loading === "approve-exact" || loading === "approve-pattern"
                }
                disabled={loading !== null}
                className={styles.approveAlwaysButton}
              >
                {t("approval.approve", "Approve")}
              </Button>
            )}
          </>
        )}
      </div>
    </Card>
  );
}
