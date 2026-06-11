import { useState, useEffect, useCallback, useMemo } from "react";
import { Shield, Check, X, Clock, Copy, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { useAgentStore } from "../../stores/agentStore";
import { getAgentDisplayName } from "../../utils/agentDisplayName";

export interface ApprovalCardProps {
  requestId: string;
  toolName: string;
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
  onApprove: (requestId: string) => Promise<void>;
  onDeny: (requestId: string) => Promise<void>;
  onCancel?: () => void;
  onAcknowledge?: (requestId: string) => Promise<void>;
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
  agentId,
  ownerAgentId,
  showInboxAgentContext = false,
  sessionId,
  rootSessionId,
  onApprove,
  onDeny,
  onCancel,
  onAcknowledge,
}: ApprovalCardProps) {
  const { t } = useTranslation();
  const agents = useAgentStore((state) => state.agents);
  const agentsById = useMemo(
    () => new Map(agents.map((agent) => [agent.id, agent])),
    [agents],
  );
  const [loading, setLoading] = useState<
    "approve" | "deny" | "acknowledge" | null
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

  useEffect(() => {
    const elapsed = Date.now() / 1000 - createdAt;
    const initialRemaining = Math.max(0, Math.floor(timeoutSeconds - elapsed));
    setRemaining(initialRemaining);

    const timer = setInterval(() => {
      const newElapsed = Date.now() / 1000 - createdAt;
      const newRemaining = Math.max(0, Math.floor(timeoutSeconds - newElapsed));
      setRemaining(newRemaining);
      if (newRemaining <= 0) clearInterval(timer);
    }, 1000);

    return () => clearInterval(timer);
  }, [createdAt, timeoutSeconds]);

  const handleApprove = async () => {
    setLoading("approve");
    try {
      await onApprove(requestId);
    } catch (err) {
      toast.error(
        err instanceof Error
          ? err.message
          : t("common.operationFailed", "Operation failed"),
      );
    } finally {
      setLoading(null);
    }
  };

  const handleDeny = async () => {
    setLoading("deny");
    try {
      await onDeny(requestId);
    } catch (err) {
      toast.error(
        err instanceof Error
          ? err.message
          : t("common.operationFailed", "Operation failed"),
      );
    } finally {
      setLoading(null);
    }
  };

  const handleAcknowledge = async () => {
    if (!onAcknowledge) return;
    setLoading("acknowledge");
    try {
      await onAcknowledge(requestId);
    } catch (err) {
      toast.error(
        err instanceof Error
          ? err.message
          : t("common.operationFailed", "Operation failed"),
      );
    } finally {
      setLoading(null);
    }
  };

  const getSeverityVariant = (
    sev: string,
  ): "destructive" | "secondary" | "outline" => {
    const s = sev.toLowerCase();
    if (s === "critical" || s === "high") return "destructive";
    if (s === "medium") return "secondary";
    return "outline";
  };

  return (
    <Card className="border border-border bg-card shadow-sm animate-in fade-in slide-in-from-bottom-4 duration-300 hover:shadow-md transition-shadow">
      <CardContent className="p-4 flex flex-col gap-0">
        {/* Header */}
        <div className="flex items-center justify-between pb-3 mb-3 border-b border-border">
          <div className="flex items-center gap-2">
            <Shield size={16} className="text-orange-500 shrink-0" />
            <span className="text-sm font-semibold text-foreground">
              {t("approval.title", "Security Approval Required")}
            </span>
          </div>
          <div className="flex items-center gap-1 bg-muted rounded-full px-2.5 py-0.5">
            <Clock size={13} className="text-muted-foreground" />
            <span className="text-xs font-mono font-medium text-muted-foreground">
              {Math.floor(remaining / 60)}:
              {String(remaining % 60).padStart(2, "0")}
            </span>
          </div>
        </div>

        {/* Content */}
        <div className="flex flex-col gap-2 mb-3">
          {showInboxAgentContext && (
            <>
              <div className="flex items-center gap-2">
                <span className="text-xs text-muted-foreground min-w-14 shrink-0">
                  {t("approval.ownerAgent", "Owner Agent")}:
                </span>
                <Badge
                  variant="secondary"
                  className="text-[11px] font-medium bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400 border-0"
                >
                  {ownerAgentDisplayName}
                </Badge>
              </div>
              {shouldShowExecutionAgent && (
                <div className="flex items-center gap-2">
                  <span className="text-xs text-muted-foreground min-w-14 shrink-0">
                    {t("approval.executingAgent", "Executing Agent")}:
                  </span>
                  <Badge
                    variant="secondary"
                    className="text-[11px] font-medium bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400 border-0"
                  >
                    {executionAgentDisplayName}
                  </Badge>
                </div>
              )}
            </>
          )}

          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground min-w-14 shrink-0">
              {t("approval.tool", "Tool")}:
            </span>
            <code className="text-xs bg-muted px-2 py-0.5 rounded border border-border font-mono text-foreground">
              {toolName}
            </code>
          </div>

          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground min-w-14 shrink-0">
              {t("approval.severity", "Severity")}:
            </span>
            <Badge
              variant={getSeverityVariant(severity)}
              className="text-[11px] font-semibold tracking-wide border-0"
            >
              {severity.toUpperCase()}
            </Badge>
          </div>

          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground min-w-14 shrink-0">
              {t("approval.findings", "Findings")}:
            </span>
            <span className="text-sm font-medium text-foreground">
              {findingsCount}
            </span>
          </div>

          {isCrossSession && !showInboxAgentContext && (
            <div className="flex items-center gap-2">
              <span className="text-xs text-muted-foreground min-w-14 shrink-0">
                {t("approval.source", "Source")}:
              </span>
              <Badge
                variant="secondary"
                className="text-[11px] font-medium bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400 border-0"
              >
                {t("approval.subSession", "Sub-Agent")} (
                {sessionId?.slice(0, 8)})
              </Badge>
            </div>
          )}

          {findingsSummary && (
            <div className="relative bg-muted/50 border-l-2 border-border pl-3 pr-8 py-2.5 rounded-r-md mt-1">
              <p className="text-xs text-muted-foreground leading-relaxed whitespace-pre-wrap break-words">
                {findingsSummary}
              </p>
              <button
                type="button"
                className={cn(
                  "absolute top-2 right-2 w-6 h-6 flex items-center justify-center rounded",
                  "text-muted-foreground hover:bg-accent hover:text-foreground transition-colors",
                  copiedField === "summary" && "text-green-500",
                )}
                onClick={() => void handleCopy(findingsSummary, "summary")}
                title={t("common.copy", "Copy")}
              >
                <Copy size={12} />
              </button>
            </div>
          )}

          {toolParams && Object.keys(toolParams).length > 0 && (
            <details className="bg-muted/50 border border-border rounded-md px-3 py-2.5 mt-1 cursor-pointer group">
              <summary className="text-xs font-medium text-muted-foreground list-none flex items-center gap-1.5 select-none outline-none hover:text-foreground transition-colors [&::-webkit-details-marker]:hidden">
                <span className="text-[8px] text-muted-foreground transition-transform group-open:rotate-90 inline-block">
                  ▶
                </span>
                {t("approval.parameters", "Parameters")}
              </summary>
              <div className="relative mt-2 pt-2 border-t border-border">
                <pre className="text-[11px] font-mono text-muted-foreground leading-relaxed overflow-x-auto max-h-[200px] overflow-y-auto whitespace-pre pr-8 scrollbar-thin">
                  {JSON.stringify(toolParams, null, 2)}
                </pre>
                <button
                  type="button"
                  className={cn(
                    "absolute top-2 right-0 w-6 h-6 flex items-center justify-center rounded",
                    "text-muted-foreground hover:bg-accent hover:text-foreground transition-colors",
                    copiedField === "params" && "text-green-500",
                  )}
                  onClick={() =>
                    void handleCopy(
                      JSON.stringify(toolParams, null, 2),
                      "params",
                    )
                  }
                  title={t("common.copy", "Copy")}
                >
                  <Copy size={12} />
                </button>
              </div>
            </details>
          )}
        </div>

        {/* Actions */}
        <div className="flex items-center justify-end gap-2 pt-3 border-t border-border">
          {isTimedOut ? (
            <>
              <span className="text-xs text-destructive font-medium mr-auto">
                {t("approval.timeoutAutoDenied", "Timed out, auto denied")}
              </span>
              {onAcknowledge && (
                <Button
                  size="sm"
                  onClick={() => void handleAcknowledge()}
                  disabled={loading !== null}
                >
                  {loading === "acknowledge" && (
                    <Loader2 size={14} className="animate-spin" />
                  )}
                  {t("approval.acknowledge", "Got It")}
                </Button>
              )}
            </>
          ) : (
            <>
              {onCancel && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => onCancel()}
                  disabled={loading !== null}
                >
                  {t("approval.cancelTask", "Cancel Task")}
                </Button>
              )}
              <Button
                variant="outline"
                size="sm"
                className="text-destructive border-destructive/40 hover:bg-destructive/10 hover:text-destructive"
                onClick={() => void handleDeny()}
                disabled={loading !== null}
              >
                {loading === "deny" ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  <X size={14} />
                )}
                {t("approval.deny", "Deny")}
              </Button>
              <Button
                size="sm"
                className="bg-orange-500 hover:bg-orange-600 text-white border-0 shadow-sm"
                onClick={() => void handleApprove()}
                disabled={loading !== null}
              >
                {loading === "approve" ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  <Check size={14} />
                )}
                {t("approval.approve", "Approve")}
              </Button>
            </>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
