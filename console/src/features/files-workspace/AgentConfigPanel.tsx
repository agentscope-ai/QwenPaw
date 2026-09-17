import type { AgentRequestContext } from "../../api/modules/agentRequestContext";
import FilesWorkspace from "./FilesWorkspace";

interface AgentConfigPanelProps {
  agentId: string;
  requestContext: AgentRequestContext;
}

export default function AgentConfigPanel({ agentId, requestContext }: AgentConfigPanelProps) {
  return <FilesWorkspace scope={{ kind: "agent", agentId }} requestContext={requestContext} profileOnly />;
}
