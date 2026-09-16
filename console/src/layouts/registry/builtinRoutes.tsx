/**
 * builtinRoutes.ts — host's built-in routes as data.
 *
 * Importing self-registers all builtins into routeRegistry. MainLayout's
 * `useRoutes()` snapshot returns them. Plugin routes are registered via
 * `QwenPaw.route.add(...)` into the same registry and treated uniformly.
 *
 * Lazy components use `lazyImportWithRetry` inline; the eager Chat page is
 * passed as ComponentType directly. The `/` redirect is a
 * named route with a tiny DefaultRedirect component so routeRegistry has a
 * single uniform shape.
 *
 * Naming convention mirrors builtinMenu: `core.<key>`.
 */
import { Suspense } from "react";
import { Navigate } from "react-router-dom";
import { lazyImportWithRetry } from "../../utils/lazyWithRetry";
import { routeRegistry } from "../../plugins/registry/store";
import type { Route } from "../../plugins/registry/types";
import { Capability } from "../../access/capabilities";

// Eager pages
import Chat from "../../pages/Chat";

// Lazy pages
const ChannelsPage = lazyImportWithRetry("../../pages/Control/Channels");
const SessionsPage = lazyImportWithRetry("../../pages/Control/Sessions");
const InboxPage = lazyImportWithRetry("../../pages/Inbox");
const CronJobsPage = lazyImportWithRetry("../../pages/Control/CronJobs");
const HeartbeatPage = lazyImportWithRetry("../../pages/Control/Heartbeat");
const AgentConfigPage = lazyImportWithRetry("../../pages/Agent/Config");
const SkillsPage = lazyImportWithRetry("../../pages/Agent/Skills");
const SkillPoolPage = lazyImportWithRetry("../../pages/Settings/SkillPool");
const ToolsPage = lazyImportWithRetry("../../pages/Agent/Tools");
const CheckpointsPage = lazyImportWithRetry("../../pages/Agent/Checkpoints");
const MCPPage = lazyImportWithRetry("../../pages/Agent/MCP");
const ModelsPage = lazyImportWithRetry("../../pages/Settings/Models");
const AdminUsersPage = lazyImportWithRetry("../../pages/Admin/Users");
const AdminPublicationsPage = lazyImportWithRetry(
  "../../pages/Admin/Publications",
);
const EnvironmentsPage = lazyImportWithRetry(
  "../../pages/Settings/Environments",
);
const OffloadPolicyPage = lazyImportWithRetry(
  "../../pages/Settings/OffloadPolicy",
);
const SecurityPage = lazyImportWithRetry("../../pages/Settings/Security");
const SystemStatusPage = lazyImportWithRetry("../../pages/Admin/SystemStatus");
const MigrationPreviewPage = lazyImportWithRetry(
  "../../pages/Admin/MigrationPreview",
);
const TokenUsagePage = lazyImportWithRetry("../../pages/Settings/TokenUsage");
const AgentStatsPage = lazyImportWithRetry("../../pages/Settings/AgentStats");
const VoiceTranscriptionPage = lazyImportWithRetry(
  "../../pages/Settings/VoiceTranscription",
);
const AgentsPage = lazyImportWithRetry("../../pages/Settings/Agents");
const DebugPage = lazyImportWithRetry("../../pages/Settings/Debug");
const BackupsPage = lazyImportWithRetry("../../pages/Settings/Backups");
const PluginManagerPage = lazyImportWithRetry(
  "../../pages/Settings/PluginManager",
);
const AppCenterPage = lazyImportWithRetry("../../pages/AppCenter");
const FilesPage = lazyImportWithRetry("../../pages/Files");

/**
 * "/" always lands on the canonical Chat workspace.
 */
function DefaultRedirect() {
  return <Navigate to="/chat" replace />;
}

export const BUILTIN_ROUTES: Route[] = [
  { id: "core.root", path: "/", component: DefaultRedirect },
  { id: "core.chat", path: "/chat/*", component: Chat },
  { id: "core.files", path: "/files", component: FilesPage },
  { id: "core.channels", path: "/channels", component: ChannelsPage },
  { id: "core.sessions", path: "/sessions", component: SessionsPage },
  { id: "core.inbox", path: "/inbox", component: InboxPage },
  { id: "core.cron-jobs", path: "/cron-jobs", component: CronJobsPage },
  { id: "core.heartbeat", path: "/heartbeat", component: HeartbeatPage },
  { id: "core.skills", path: "/skills", component: SkillsPage },
  {
    id: "core.skill-pool",
    path: "/skill-pool",
    component: SkillPoolPage,
    capability: Capability.PlatformSettingsManage,
  },
  { id: "core.tools", path: "/tools", component: ToolsPage },
  { id: "core.mcp", path: "/mcp", component: MCPPage },
  { id: "core.checkpoints", path: "/checkpoints", component: CheckpointsPage },
  { id: "core.agents", path: "/agents", component: AgentsPage },
  {
    id: "core.models",
    path: "/models",
    component: ModelsPage,
    capability: Capability.PlatformSettingsManage,
  },
  {
    id: "core.admin-users",
    path: "/admin/users",
    component: AdminUsersPage,
    capability: Capability.UsersManage,
  },
  {
    id: "core.admin-publications",
    path: "/admin/publications",
    component: AdminPublicationsPage,
    capability: Capability.PublicationsReview,
  },
  {
    id: "core.environments",
    path: "/environments",
    component: EnvironmentsPage,
    capability: Capability.PlatformSettingsManage,
  },
  {
    id: "core.offload-policy",
    path: "/offload-policy",
    component: OffloadPolicyPage,
    capability: Capability.PlatformSettingsManage,
  },
  {
    id: "core.agent-config",
    path: "/agent-config",
    component: AgentConfigPage,
  },
  {
    id: "core.security",
    path: "/security",
    component: SecurityPage,
    capability: Capability.PlatformSettingsManage,
  },
  {
    id: "core.system-status",
    path: "/system-status",
    component: SystemStatusPage,
    capability: Capability.PlatformSettingsManage,
  },
  {
    id: "core.migration-preview",
    path: "/migration-preview",
    component: MigrationPreviewPage,
    capability: Capability.PlatformSettingsManage,
  },
  { id: "core.token-usage", path: "/token-usage", component: TokenUsagePage },
  { id: "core.agent-stats", path: "/agent-stats", component: AgentStatsPage },
  {
    id: "core.voice-transcription",
    path: "/voice-transcription",
    component: VoiceTranscriptionPage,
    capability: Capability.PlatformSettingsManage,
  },
  {
    id: "core.debug",
    path: "/debug",
    component: DebugPage,
    capability: Capability.PlatformSettingsManage,
  },
  {
    id: "core.backups",
    path: "/backups",
    component: BackupsPage,
    capability: Capability.PlatformSettingsManage,
  },
  {
    id: "core.plugin-manager",
    path: "/plugin-manager",
    component: PluginManagerPage,
    capability: Capability.PlatformSettingsManage,
  },
  { id: "core.app-center", path: "/apps", component: AppCenterPage },
  // Deep-link / refresh target: `/apps/<id>` also lands on the App Center,
  // which opens the app inline (with the “← App Center” bar) from the URL.
  {
    id: "core.app-center.embed",
    path: "/apps/:appId",
    component: AppCenterPage,
  },
];

routeRegistry.addBuiltin(BUILTIN_ROUTES);

// Suspense imported above is used by lazyImportWithRetry consumers; ref keeps
// TS from tree-shaking the import in older bundler configs.
void Suspense;
