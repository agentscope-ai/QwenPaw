import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import { Button, Card, Tag, Typography, Space } from "antd";
import { Shield, Check, X, Clock, Copy, Info } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useAgentStore } from "../../stores/agentStore";
import { commandsApi } from "../../api/modules/commands";
import { getAgentDisplayName } from "../../utils/agentDisplayName";
import { ApiError } from "../../api/request";
import type { PendingApproval } from "../../api/modules/console";
import { parseErrorDetail } from "../../utils/error";
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
  // One-line rationale the agent emitted before requesting this tool call.
  reasoning?: string;
  sessionId?: string;
  rootSessionId?: string;
  // Approval-scope choice (console-only). When true the card renders
  // Approve Pattern + Approve Exact; when false, a single Approve button.
  isGeneralized?: boolean;
  exactTarget?: string;
  similarTarget?: string;
  approvalBehavior?: PendingApproval["approval_behavior"];
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
  reasoning,
  sessionId,
  rootSessionId,
  isGeneralized,
  exactTarget,
  similarTarget,
  approvalBehavior = "unknown",
  onApprove,
  onDeny,
  onAcknowledge,
}: ApprovalCardProps) {
  const { t } = useTranslation();
  const isSessionRule = approvalBehavior === "session_rule";
  const isSessionApp = approvalBehavior === "session_app";
  const offersPattern =
    isSessionRule && isGeneralized && Boolean(similarTarget);
  const approveLabel = isSessionRule
    ? t("approval.allowTarget", "Allow target for this session")
    : isSessionApp
    ? t("approval.allowApp", "Allow app for this session")
    : approvalBehavior === "once"
    ? t("approval.allowOnce", "Allow this call")
    : t("approval.approve", "Approve call");
  const denyLabel = isSessionApp
    ? t("approval.denyApp", "Deny app for this session")
    : t("approval.deny", "Reject this call");
  const applicationDetails = isSessionApp
    ? ([
        ["applicationId", "Application ID", toolParams?.canonical_app_id],
        ["risk", "Risk", toolParams?.risk],
        ["warning", "Warning", toolParams?.warning],
      ] as const)
    : [];
  const agents = useAgentStore((state) => state.agents);
  const agentsById = useMemo(
    () => new Map(agents.map((agent) => [agent.id, agent])),
    [agents],
  );
  const [loading, setLoading] = useState<
    | "approve-pattern"
    | "approve-exact"
    | "deny"
    | "acknowledge"
    | "check"
    | null
  >(null);
  const [remaining, setRemaining] = useState(() =>
    Math.max(0, Math.ceil(createdAt + timeoutSeconds - Date.now() / 1000)),
  );
  const submitting = useRef(false);
  const [outcome, setOutcome] = useState<
    "approved" | "denied" | "unavailable" | "rejected" | "failed" | null
  >(null);
  const [rejectionReason, setRejectionReason] = useState("");
  const [checkFailed, setCheckFailed] = useState(false);
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
  const isTimedOut = remaining <= 0;
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
  const hasOwnerAgentIdentity = Boolean(ownerAgentId || agentId);
  const displayToolSource =
    toolSource && toolSource !== "builtin"
      ? toolSource
      : t("approval.builtinSource", "Built-in");

  useEffect(() => {
    const elapsed = Date.now() / 1000 - createdAt;
    const initialRemaining = Math.max(0, Math.ceil(timeoutSeconds - elapsed));
    setRemaining(initialRemaining);

    const timer = setInterval(() => {
      const newElapsed = Date.now() / 1000 - createdAt;
      const newRemaining = Math.max(0, Math.ceil(timeoutSeconds - newElapsed));
      setRemaining(newRemaining);

      if (newRemaining <= 0) {
        clearInterval(timer);
      }
    }, 1000);

    return () => clearInterval(timer);
  }, [createdAt, timeoutSeconds]);

  const submitDecision = async (
    decision: "approve" | "deny",
    scope?: "exact" | "similar",
  ) => {
    if (submitting.current || outcome) return;
    if (Date.now() / 1000 >= createdAt + timeoutSeconds) {
      setRemaining(0);
      return;
    }
    submitting.current = true;
    setLoading(
      decision === "deny"
        ? "deny"
        : scope === "similar"
        ? "approve-pattern"
        : "approve-exact",
    );
    try {
      if (decision === "approve") await onApprove(requestId, scope);
      else await onDeny(requestId);
      setOutcome(decision === "approve" ? "approved" : "denied");
    } catch (error) {
      const status = error instanceof ApiError ? error.status : undefined;
      if (status === 404 || status === 409) {
        setOutcome("unavailable");
      } else if (status !== undefined && status < 500) {
        // Other client errors are explicit refusals: the decision was not
        // applied, so show the server's reason instead of an unknown result.
        const detail = parseErrorDetail(error);
        setRejectionReason(
          typeof detail === "string" ? detail : `HTTP ${status}`,
        );
        setOutcome("rejected");
      } else {
        setOutcome("failed");
      }
    } finally {
      submitting.current = false;
      setLoading(null);
    }
  };

  const handleAcknowledge = async () => {
    if (!onAcknowledge || submitting.current) return;
    submitting.current = true;
    setLoading("acknowledge");
    try {
      await onAcknowledge(requestId);
    } catch {
      setOutcome("failed");
    } finally {
      submitting.current = false;
      setLoading(null);
    }
  };

  const recheck = async () => {
    if (submitting.current || isTimedOut) return;
    submitting.current = true;
    setLoading("check");
    setCheckFailed(false);
    try {
      const pending = await commandsApi.isApprovalPending(
        requestId,
        rootSessionId,
      );
      if (Date.now() / 1000 >= createdAt + timeoutSeconds) {
        setRemaining(0);
        setOutcome("unavailable");
      } else {
        setOutcome(pending ? null : "unavailable");
      }
    } catch {
      setCheckFailed(true);
    } finally {
      submitting.current = false;
      setLoading(null);
    }
  };

  const canRecheck =
    !isTimedOut && (outcome === "failed" || outcome === "rejected");

  const statusText =
    loading === "check"
      ? t("approval.checkStatus")
      : loading && loading !== "acknowledge"
      ? t("approval.submitting", "Submitting decision…")
      : outcome === "approved"
      ? t("approval.approved", "Tool call approved")
      : outcome === "denied"
      ? isSessionApp
        ? t("approval.appDenied", "App access denied for this session")
        : t("approval.denied", "Tool call rejected")
      : outcome === "unavailable"
      ? t("approval.unavailable", "Request already handled or expired")
      : isTimedOut
      ? t("approval.expired", "Request expired")
      : checkFailed
      ? t("approval.checkStatusFailed")
      : outcome === "failed"
      ? t(
          "approval.submitUnconfirmed",
          "Could not confirm the decision. Check the request status before trying again.",
        )
      : outcome === "rejected"
      ? t(
          "approval.submitRejected",
          "The server rejected this decision: {{reason}}",
          { reason: rejectionReason },
        )
      : t("approval.waiting", "Waiting for confirmation");

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
            {t("approval.title", "Security Approval Required")} · {toolName}
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
        <p className={styles.scopeHint}>
          {isSessionRule
            ? t(
                "approval.sessionRuleHint",
                "Approval continues this call and attempts to save a rule for this tool and target in the executing agent’s session. Matching targets may be allowed again; other security checks still apply. Closing this page does not revoke the rule.",
              )
            : isSessionApp
            ? t(
                "approval.sessionAppHint",
                "Allow or deny access to this application for the executing session. This does not grant permanent access.",
              )
            : approvalBehavior === "once"
            ? t(
                "approval.onceHint",
                "Approval continues this call only and does not save an authorization rule.",
              )
            : approvalBehavior === "strict"
            ? t(
                "approval.strictHint",
                "Strict mode requires confirmation for each call. Approval may record a session target rule, but it does not bypass strict mode.",
              )
            : t(
                "approval.unknownHint",
                "Approval lets the pending call continue. This source has not provided its authorization lifetime; review the details before deciding.",
              )}
        </p>
        {(isSessionRule || isSessionApp || approvalBehavior === "strict") && (
          <p className={styles.scopeHint}>
            {t("approval.executingAgent", "Executing Agent")}:{" "}
            {executionAgentDisplayName}
            {" · "}
            {t("approval.session", "Session")}: {sessionId}
          </p>
        )}
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
        ) : hasOwnerAgentIdentity ? (
          <div className={styles.infoRow}>
            <Text className={styles.label}>
              {t("approval.agent", "Agent")}:
            </Text>
            <Tag color="success" className={styles.ownerAgentTag}>
              {ownerAgentDisplayName}
            </Tag>
          </div>
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

        {reasoning ? (
          <div className={styles.reasoningRow}>
            <Text className={styles.label}>
              {t("approval.reason", "Reason")}:
            </Text>
            <Text
              className={styles.reasoningText}
            >{`\u201C${reasoning}\u201D`}</Text>
          </div>
        ) : null}

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

        {exactTarget && (
          <div className={styles.scopeSection}>
            <Text className={styles.scopeLabel}>
              {t("approval.target", "Target")}:
            </Text>
            <code className={styles.scopeCode}>{exactTarget}</code>
            {offersPattern && (
              <>
                <Text className={styles.scopeItemLabel}>
                  {t("approval.pattern", "Target pattern")}:
                </Text>
                <code className={styles.scopeCode}>{similarTarget}</code>
              </>
            )}
          </div>
        )}

        {applicationDetails.map(([key, label, value]) =>
          typeof value === "string" && value.trim() ? (
            <div key={key} className={styles.infoRow}>
              <Text className={styles.label}>
                {t(`approval.${key}`, label)}:
              </Text>
              <Text className={styles.value} code={key === "applicationId"}>
                {value}
              </Text>
            </div>
          ) : null,
        )}

        {toolParams && Object.keys(toolParams).length > 0 && (
          <details className={styles.paramsDetails} open={!exactTarget}>
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
          <details className={styles.detailsSection} open>
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

      <p role="status" aria-live="polite" className={styles.scopeHint}>
        {statusText}
      </p>
      <div className={styles.actions} aria-busy={loading !== null}>
        {canRecheck ? (
          <Button
            key="check-status"
            onClick={recheck}
            loading={loading === "check"}
            aria-label={t("approval.checkStatus")}
          >
            {t("approval.checkStatus")}
          </Button>
        ) : outcome || isTimedOut ? (
          onAcknowledge && (isTimedOut || outcome === "unavailable") ? (
            <Button
              onClick={handleAcknowledge}
              loading={loading === "acknowledge"}
              disabled={loading !== null}
            >
              {t("approval.dismiss", "Dismiss notice")}
            </Button>
          ) : null
        ) : (
          <>
            <Button
              icon={<X size={14} />}
              onClick={() => submitDecision("deny")}
              loading={loading === "deny"}
              disabled={loading !== null}
              className={styles.denyButton}
            >
              {denyLabel}
            </Button>
            {offersPattern && (
              <Button
                onClick={() => submitDecision("approve", "similar")}
                loading={loading === "approve-pattern"}
                disabled={loading !== null}
                className={styles.approveAlwaysButton}
              >
                {t("approval.allowPattern", "Allow pattern for this session")}
              </Button>
            )}
            <Button
              type="primary"
              icon={<Check size={14} />}
              onClick={() =>
                submitDecision("approve", isGeneralized ? "exact" : undefined)
              }
              loading={loading === "approve-exact"}
              disabled={loading !== null}
              className={styles.approveOnceButton}
            >
              {approveLabel}
            </Button>
          </>
        )}
      </div>
    </Card>
  );
}
