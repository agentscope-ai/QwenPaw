export * from "./types";

export { request } from "./request";

export { getApiUrl, getApiToken } from "./config";

import { rootApi } from "./modules/root";
import { channelApi } from "./modules/channel";
import { heartbeatApi } from "./modules/heartbeat";
import { cronJobApi } from "./modules/cronjob";
import { chatApi, sessionApi } from "./modules/chat";
import { envApi } from "./modules/env";
import { providerApi } from "./modules/provider";
import { skillApi } from "./modules/skill";
import { agentApi } from "./modules/agent";
import { agentsApi } from "./modules/agents";
import { workspaceApi } from "./modules/workspace";
import { localModelApi } from "./modules/localModel";
import { mcpApi } from "./modules/mcp";
import { tokenUsageApi } from "./modules/tokenUsage";
import { toolsApi } from "./modules/tools";
import { securityApi } from "./modules/security";
import { userTimezoneApi } from "./modules/userTimezone";
import { languageApi } from "./modules/language";
import { meetingsApi } from "./modules/meetings";
import { agentSACPApi } from "./modules/agent_sacp";

export const api = {
  // Root
  ...rootApi,

  // Channels
  ...channelApi,

  // Heartbeat
  ...heartbeatApi,

  // Cron Jobs
  ...cronJobApi,

  // Chats
  ...chatApi,

  // Sessions（Legacy aliases）
  ...sessionApi,

  // Environment Variables
  ...envApi,

  // Providers
  ...providerApi,

  // Agent
  ...agentApi,

  // Skills
  ...skillApi,

  // Workspace
  ...workspaceApi,

  // Local Models
  ...localModelApi,

  // MCP Clients
  ...mcpApi,

  // Token Usage
  ...tokenUsageApi,
  // Tools
  ...toolsApi,

  // Security
  ...securityApi,

  // User Timezone
  ...userTimezoneApi,

  // Language
  ...languageApi,

  // Meetings
  ...meetingsApi,

  // Agent SACP
  ...agentSACPApi,
};

export default api;

// Export individual APIs for direct access
export { agentsApi };
export { meetingsApi };
export { agentSACPApi };
