import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useApprovalContext } from "../../../contexts/ApprovalContext";
import { commandsApi } from "../../../api/modules/commands";
import { chatApi } from "../../../api/modules/chat";
import { useAppMessage } from "../../../hooks/useAppMessage";
import { useSessionStore } from "../stores/sessionStore";

export interface ApprovalMessageData {
  requestId: string;
  sessionId: string;
  rootSessionId?: string;
  agentId: string;
  toolName: string;
  severity: string;
  findingsCount: number;
  findingsSummary: string;
  toolParams: Record<string, unknown>;
  createdAt: number;
  timeoutSeconds: number;
}

/**
 * Build the set of all known IDs for the current session so that
 * approval filtering works regardless of which ID format the backend
 * stored as root_session_id (UUID, timestamp, or "console:default").
 */
function buildKnownSessionIds(
  chatId: string | undefined,
  activeSessionId: string | null,
  sessions: Array<{ id: string; sessionId?: string }>,
): Set<string> {
  const ids = new Set<string>();
  if (activeSessionId) ids.add(activeSessionId);
  if (chatId) ids.add(chatId);

  // The backend root_session_id is typically the "channel:user" format
  // (e.g. "console:default") resolved by the channel's resolve_session_id.
  // Look up the matching session and add its sessionId so filtering works.
  const target = activeSessionId || chatId;
  if (target) {
    const session = sessions.find((s) => s.id === target);
    if (session?.sessionId) ids.add(session.sessionId);
  }

  return ids;
}

export function useApprovals(
  chatId: string | undefined,
  activeSessionId: string | null,
) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const { approvals, setApprovals } = useApprovalContext();
  const sessions = useSessionStore((s) => s.sessions);
  const [approvalRequests, setApprovalRequests] = useState<
    Map<string, ApprovalMessageData>
  >(new Map());
  const prevApprovalKeyRef = useRef("");

  // Filter approvals for current session
  useEffect(() => {
    const knownIds = buildKnownSessionIds(chatId, activeSessionId, sessions);

    // When no session ID is available yet, use the first approval's
    // root_session_id as a hint (handles the race where approval arrives
    // before the session ID is propagated).
    if (knownIds.size === 0 && approvals.length > 0) {
      knownIds.add(approvals[0].root_session_id);
    }

    const sessionApprovals =
      knownIds.size > 0
        ? approvals.filter((approval) => knownIds.has(approval.root_session_id))
        : approvals;

    const approvalKey = sessionApprovals
      .map((a) => a.request_id)
      .sort()
      .join(",");

    if (approvalKey === prevApprovalKeyRef.current) return;
    prevApprovalKeyRef.current = approvalKey;

    const newMap = new Map<string, ApprovalMessageData>();
    for (const approval of sessionApprovals) {
      newMap.set(approval.request_id, {
        requestId: approval.request_id,
        sessionId: approval.session_id,
        rootSessionId: approval.root_session_id,
        agentId: approval.agent_id,
        toolName: approval.tool_name,
        severity: approval.severity,
        findingsCount: approval.findings_count,
        findingsSummary: approval.findings_summary,
        toolParams: approval.tool_params,
        createdAt: approval.created_at,
        timeoutSeconds: approval.timeout_seconds,
      });
    }

    setApprovalRequests(newMap);
  }, [approvals, chatId, activeSessionId, sessions]);

  const handleApprove = useCallback(
    async (requestId: string) => {
      // Use the approval record's own rootSessionId — it matches what the
      // backend stored and avoids 403 "root session mismatch" errors.
      const request = approvalRequests.get(requestId);
      const rootSessionId =
        request?.rootSessionId || activeSessionId || chatId || "";

      try {
        const cardElement = document.querySelector(
          `[data-approval-id="${requestId}"]`,
        );
        if (cardElement) {
          cardElement.classList.add("approvalCardExit");
        }

        await commandsApi.sendApprovalCommand(
          "approve",
          requestId,
          rootSessionId,
        );
        setApprovals((prev) =>
          prev.filter((item) => item.request_id !== requestId),
        );
        message.success(t("approval.approved"));

        setTimeout(() => {
          setApprovalRequests((prev) => {
            const next = new Map(prev);
            next.delete(requestId);
            return next;
          });
        }, 300);
      } catch (error) {
        message.error(t("approval.approveFailed"));
        console.error("Failed to approve:", error);
      }
    },
    [approvalRequests, activeSessionId, chatId, t, message, setApprovals],
  );

  const handleDeny = useCallback(
    async (requestId: string) => {
      const request = approvalRequests.get(requestId);
      const rootSessionId =
        request?.rootSessionId || activeSessionId || chatId || "";

      try {
        const cardElement = document.querySelector(
          `[data-approval-id="${requestId}"]`,
        );
        if (cardElement) {
          cardElement.classList.add("approvalCardExit");
        }

        await commandsApi.sendApprovalCommand("deny", requestId, rootSessionId);
        setApprovals((prev) =>
          prev.filter((item) => item.request_id !== requestId),
        );
        message.success(t("approval.denied"));

        setTimeout(() => {
          setApprovalRequests((prev) => {
            const next = new Map(prev);
            next.delete(requestId);
            return next;
          });
        }, 300);
      } catch (error) {
        message.error(t("approval.denyFailed"));
        console.error("Failed to deny:", error);
      }
    },
    [approvalRequests, activeSessionId, chatId, t, message, setApprovals],
  );

  const handleCancel = useCallback(
    (rootSessionId: string | undefined) => {
      const resolvedChatId = activeSessionId || chatId || "";
      if (!resolvedChatId) {
        console.warn("[Chat] No chat_id resolved, cannot cancel task");
        return;
      }

      chatApi
        .stopChat(resolvedChatId)
        .then(() => {
          setApprovals((prev) =>
            prev.filter((item) => item.root_session_id !== rootSessionId),
          );
        })
        .catch((err) => {
          console.error("[Chat] stopChat failed:", err);
        });
    },
    [activeSessionId, chatId, setApprovals],
  );

  return {
    approvalRequests,
    handleApprove,
    handleDeny,
    handleCancel,
  };
}
