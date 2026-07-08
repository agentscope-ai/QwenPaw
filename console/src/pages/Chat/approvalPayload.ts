import type { ToolExecutionLevel } from "./components/ApprovalLevelToggle";

export function applyApprovalLevelToRequestBody(
  requestBody: Record<string, unknown>,
  sessionLevel: ToolExecutionLevel | null,
  runningConfigApprovalLevel: ToolExecutionLevel,
): void {
  const approvalLevel = sessionLevel ?? runningConfigApprovalLevel;
  const existing = requestBody.request_context;
  const requestContext =
    existing && typeof existing === "object" && !Array.isArray(existing)
      ? { ...(existing as Record<string, unknown>) }
      : {};

  requestContext.approval_level = approvalLevel;
  requestBody.request_context = requestContext;
}
