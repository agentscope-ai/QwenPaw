export interface ApprovalScopeIdentity {
  agentId: string;
  ownerAgentId?: string;
  rootSessionId: string;
}

export const isApprovalInCurrentScope = (
  approval: ApprovalScopeIdentity,
  selectedAgent: string,
  rootSessionId: string,
  isAgentSwitchTransition: boolean,
): boolean => {
  if (isAgentSwitchTransition || !rootSessionId) return false;

  const ownerAgentId = approval.ownerAgentId || approval.agentId;
  return (
    ownerAgentId === selectedAgent && approval.rootSessionId === rootSessionId
  );
};
