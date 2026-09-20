import { migratePendingModel, withPendingModel } from "./sessionModel";
import {
  migratePendingProjectDirectory,
  withPendingProjectDirectory,
} from "../project-directory/pendingProjectDirectory";
import {
  migratePendingThinking,
  withPendingThinking,
} from "../thinking/sessionThinkingApi";

export function migratePendingSessionSettings(
  agentId: string,
  from: string,
  to: string,
) {
  migratePendingProjectDirectory(agentId, from, to);
  migratePendingThinking(agentId, from, to);
  migratePendingModel(agentId, from, to);
}

export function withPendingSessionSettings(
  body: Record<string, unknown>,
  agentId: string,
  sessionId: string,
) {
  const project = withPendingProjectDirectory(body, agentId, sessionId);
  return {
    ...project,
    requestBody: withPendingModel(
      withPendingThinking(project.requestBody, agentId, sessionId),
      agentId,
      sessionId,
    ),
  };
}
