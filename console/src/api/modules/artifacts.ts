import { request } from "../request";
import { buildAuthHeaders } from "../authHeaders";
import { ensureAccessSessionFresh } from "../authSession";
import { downloadFileFromUrl } from "../../utils/downloadFileFromUrl";
import { withAgentRequestContext, type AgentRequestContext } from "./agentRequestContext";

export interface AgentArtifact {
  id: string;
  relative_path: string;
  original_name: string;
  media_type: string;
  size: number;
  source_tool: string;
  conversation_id: string | null;
  status: "active" | "deleted";
  created_at: string;
}

export const artifactsApi = {
  download: async (artifactId: string, filename: string, context?: AgentRequestContext) => {
    if (!(await ensureAccessSessionFresh())) throw new Error("Not authenticated");
    const headers = withAgentRequestContext(
      { headers: buildAuthHeaders() },
      context,
    )?.headers as Record<string, string> | undefined;
    return downloadFileFromUrl(`/api/console/artifacts/${encodeURIComponent(artifactId)}/download`, filename, {headers, preferResponseFilename: true});
  },
  list: (context?: AgentRequestContext) => {
    const options = withAgentRequestContext(undefined, context);
    return options
      ? request<AgentArtifact[]>("/console/artifacts", options)
      : request<AgentArtifact[]>("/console/artifacts");
  },
  collect: (context?: AgentRequestContext) => request<{collected: number; failures: Array<{path: string; error: string}>}>("/console/artifacts/collect", withAgentRequestContext({method: "POST"}, context)),
  remove: (artifactId: string, context?: AgentRequestContext) => request<AgentArtifact>(`/console/artifacts/${encodeURIComponent(artifactId)}`, withAgentRequestContext({ method: "DELETE" }, context)),
  downloadUrl: (artifactId: string) => `/api/console/artifacts/${encodeURIComponent(artifactId)}/download`,
};
