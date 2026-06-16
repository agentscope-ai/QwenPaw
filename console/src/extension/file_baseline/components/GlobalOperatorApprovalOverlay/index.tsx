import { useCallback, useMemo } from "react";
import { Modal } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import { ApprovalCard } from "../../../../components/ApprovalCard/ApprovalCard";
import { commandsApi } from "../../../../api/modules/commands";
import { useApprovalContext } from "../../../../contexts/ApprovalContext";
import { useAppMessage } from "../../../../hooks/useAppMessage";
import { filterOperatorConsoleApprovals } from "../../lib/operatorConsoleApproval";

/**
 * Modal approval for Console operator writes (file baseline protected paths).
 * Agent chat approvals stay on Chat / Inbox only.
 */
export default function GlobalOperatorApprovalOverlay() {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const { approvals, setApprovals } = useApprovalContext();

  const queue = useMemo(
    () => filterOperatorConsoleApprovals(approvals),
    [approvals],
  );
  const active = queue[0] ?? null;
  const open = active !== null;

  const resolveSessionId = useCallback(
    () => active?.root_session_id || active?.session_id || "",
    [active],
  );

  const handleApprove = useCallback(
    async (requestId: string) => {
      const sessionId = resolveSessionId();
      if (!sessionId) {
        message.error(t("approval.approveFailed"));
        return;
      }
      try {
        await commandsApi.sendApprovalCommand("approve", requestId, sessionId);
        setApprovals((prev) =>
          prev.filter((item) => item.request_id !== requestId),
        );
        message.success(t("approval.approved"));
      } catch (error) {
        message.error(t("approval.approveFailed"));
        console.error("[GlobalOperatorApprovalOverlay] approve failed:", error);
      }
    },
    [message, resolveSessionId, setApprovals, t],
  );

  const handleDeny = useCallback(
    async (requestId: string) => {
      const sessionId = resolveSessionId();
      if (!sessionId) {
        message.error(t("approval.denyFailed"));
        return;
      }
      try {
        await commandsApi.sendApprovalCommand("deny", requestId, sessionId);
        setApprovals((prev) =>
          prev.filter((item) => item.request_id !== requestId),
        );
        message.success(t("approval.denied"));
      } catch (error) {
        message.error(t("approval.denyFailed"));
        console.error("[GlobalOperatorApprovalOverlay] deny failed:", error);
      }
    },
    [message, resolveSessionId, setApprovals, t],
  );

  if (!active) {
    return null;
  }

  return (
    <Modal
      open={open}
      title={t("approval.operatorConsoleSaveTitle", "Approve protected file save")}
      footer={null}
      closable={false}
      maskClosable={false}
      width={720}
      destroyOnClose
      zIndex={1200}
    >
      <ApprovalCard
        requestId={active.request_id}
        agentId={active.agent_id}
        ownerAgentId={active.owner_agent_id}
        toolName={active.tool_name}
        severity={active.severity}
        findingsCount={active.findings_count}
        findingsSummary={active.findings_summary}
        toolParams={active.tool_params}
        createdAt={active.created_at}
        timeoutSeconds={active.timeout_seconds}
        sessionId={active.session_id}
        rootSessionId={active.root_session_id}
        fileBaselineWrite={active.file_baseline_write}
        onApprove={handleApprove}
        onDeny={handleDeny}
      />
    </Modal>
  );
}
