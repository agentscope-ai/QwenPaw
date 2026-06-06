import React from "react";
import { ApprovalCard } from "../../ApprovalCard/ApprovalCard";
import type { ApprovalMessageData } from "../hooks/useApprovals";

export interface ApprovalOverlayProps {
  approvalRequests: Map<string, ApprovalMessageData>;
  onApprove: (requestId: string) => Promise<void>;
  onDeny: (requestId: string) => Promise<void>;
  onCancel: (rootSessionId: string | undefined) => void;
}

const ApprovalOverlay: React.FC<ApprovalOverlayProps> = ({
  approvalRequests,
  onApprove,
  onDeny,
  onCancel,
}) => {
  if (approvalRequests.size === 0) return null;

  return (
    <>
      {Array.from(approvalRequests.values()).map((request) => (
        <div
          key={request.requestId}
          data-approval-id={request.requestId}
          style={{
            position: "fixed",
            bottom: 80,
            right: 24,
            zIndex: 1000,
            maxWidth: 480,
            width: "calc(100vw - 48px)",
          }}
        >
          <ApprovalCard
            requestId={request.requestId}
            agentId={request.agentId}
            toolName={request.toolName}
            severity={request.severity}
            findingsCount={request.findingsCount}
            findingsSummary={request.findingsSummary}
            toolParams={request.toolParams}
            createdAt={request.createdAt}
            timeoutSeconds={request.timeoutSeconds}
            sessionId={request.sessionId}
            rootSessionId={request.rootSessionId}
            onApprove={onApprove}
            onDeny={onDeny}
            onCancel={() => onCancel(request.rootSessionId)}
          />
        </div>
      ))}
    </>
  );
};

export default ApprovalOverlay;
