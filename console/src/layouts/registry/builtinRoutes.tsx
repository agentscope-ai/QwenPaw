/**
 * builtinRoutes.ts — host's built-in routes as data.
 *
 * Importing self-registers all builtins into routeRegistry. MainLayout's
 * `useRoutes()` snapshot returns them. Plugin routes are registered via
 * `QwenPaw.route.add(...)` into the same registry and treated uniformly.
 *
 * Lazy components use `lazyImportWithRetry` inline. The `/` redirect is a
 * named route with a tiny DefaultRedirect component so routeRegistry has a
 * single uniform shape.
 *
 * Naming convention mirrors builtinMenu: `core.<key>`.
 */
import { Suspense } from "react";
import { Navigate, useLocation } from "react-router-dom";
import i18next from "../../i18n";
import { lazyImportWithRetry } from "../../utils/lazyWithRetry";
import { routeRegistry } from "../../plugins/registry/store";
import type {
  Route,
  RouteDomain,
  RouteLayout,
  RouteMeta,
  RouteNavigation,
  RouteScope,
} from "../../plugins/registry/types";

// Lazy pages
const ChatPage = lazyImportWithRetry("../../pages/Chat");
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
const ACPPage = lazyImportWithRetry("../../pages/Agent/ACP");
const ModelsPage = lazyImportWithRetry("../../pages/Settings/Models");
const EnvironmentsPage = lazyImportWithRetry(
  "../../pages/Settings/Environments",
);
const OffloadPolicyPage = lazyImportWithRetry(
  "../../pages/Settings/OffloadPolicy",
);
const SecurityPage = lazyImportWithRetry("../../pages/Settings/Security");
const TokenUsagePage = lazyImportWithRetry("../../pages/Settings/TokenUsage");
const AgentStatsPage = lazyImportWithRetry("../../pages/Settings/AgentStats");
const VoiceTranscriptionPage = lazyImportWithRetry(
  "../../pages/Settings/VoiceTranscription",
);
const AgentsPage = lazyImportWithRetry("../../pages/Settings/Agents");
const DebugPage = lazyImportWithRetry("../../pages/Settings/Debug");
const BackupsPage = lazyImportWithRetry("../../pages/Settings/Backups");
const AppCenterPage = lazyImportWithRetry("../../pages/AppCenter");
const MarketplacePage = lazyImportWithRetry("../../pages/Market");
const FilesPage = lazyImportWithRetry("../../pages/Files");
const ImportPage = lazyImportWithRetry("../../pages/Import");
const SettingsCenterPage = lazyImportWithRetry("../../pages/SettingsCenter");

/**
 * "/" always lands on the canonical Chat workspace.
 */
function DefaultRedirect() {
  return <Navigate to="/chat" replace />;
}

/** Synonym for /acp. Kept for plugins / external links that reference uppercase. */
function ACPRedirect() {
  const location = useLocation();

  return (
    <Navigate
      to={{
        pathname: "/acp",
        search: location.search,
        hash: location.hash,
      }}
      replace
    />
  );
}

function routeMeta(
  titleKey: string,
  fallback: string,
  domain: RouteDomain,
  scope: RouteScope,
  layout: RouteLayout = "standard",
  navigation: RouteNavigation = "context",
): RouteMeta {
  return {
    domain,
    title: (locale) =>
      i18next.t(titleKey, { defaultValue: fallback, lng: locale }),
    scope,
    layout,
    navigation,
  };
}

export const BUILTIN_ROUTES: Route[] = [
  {
    id: "core.root",
    path: "/",
    component: DefaultRedirect,
    meta: routeMeta(
      "nav.chat",
      "Chat",
      "chat",
      "global",
      "standard",
      "search-only",
    ),
  },
  {
    id: "core.chat",
    path: "/chat/*",
    component: ChatPage,
    meta: routeMeta("nav.chat", "Chat", "chat", "session", "workbench", "rail"),
  },
  {
    id: "core.settings-center",
    path: "/settings/*",
    component: SettingsCenterPage,
    meta: routeMeta(
      "nav.settings",
      "Settings",
      "settings",
      "global",
      "standard",
      "settings",
    ),
  },
  {
    id: "core.files",
    path: "/files",
    component: FilesPage,
    meta: routeMeta("nav.files", "Files", "workspace", "agent", "workbench"),
  },
  {
    id: "core.channels",
    path: "/channels",
    component: ChannelsPage,
    meta: routeMeta(
      "nav.channels",
      "Channels",
      "settings",
      "agent",
      "standard",
      "settings",
    ),
  },
  {
    id: "core.sessions",
    path: "/sessions",
    component: SessionsPage,
    meta: routeMeta("nav.sessions", "Sessions", "tasks", "agent"),
  },
  {
    id: "core.inbox",
    path: "/inbox",
    component: InboxPage,
    meta: routeMeta("nav.inbox", "Inbox", "tasks", "agent"),
  },
  {
    id: "core.cron-jobs",
    path: "/cron-jobs",
    component: CronJobsPage,
    meta: routeMeta("nav.cronJobs", "Cron Jobs", "tasks", "agent"),
  },
  {
    id: "core.heartbeat",
    path: "/heartbeat",
    component: HeartbeatPage,
    meta: routeMeta("nav.heartbeat", "Heartbeat", "tasks", "agent"),
  },
  {
    id: "core.skills",
    path: "/skills",
    component: SkillsPage,
    meta: routeMeta("nav.skills", "Skills", "workspace", "agent"),
  },
  {
    id: "core.skill-pool",
    path: "/skill-pool",
    component: SkillPoolPage,
    meta: routeMeta(
      "nav.skillPool",
      "Skill Pool",
      "settings",
      "global",
      "standard",
      "settings",
    ),
  },
  {
    id: "core.tools",
    path: "/tools",
    component: ToolsPage,
    meta: routeMeta("nav.tools", "Tools", "workspace", "agent"),
  },
  {
    id: "core.mcp",
    path: "/mcp",
    component: MCPPage,
    meta: routeMeta("nav.mcp", "MCP", "workspace", "agent"),
  },
  {
    id: "core.acp",
    path: "/acp",
    caseSensitive: true,
    component: ACPPage,
    meta: routeMeta("nav.acp", "ACP", "workspace", "agent"),
  },
  {
    id: "core.acp-alias",
    path: "/ACP",
    component: ACPRedirect,
    meta: routeMeta(
      "nav.acp",
      "ACP",
      "workspace",
      "agent",
      "standard",
      "search-only",
    ),
  },
  {
    id: "core.checkpoints",
    path: "/checkpoints",
    component: CheckpointsPage,
    meta: routeMeta("checkpoints.nav", "Checkpoints", "workspace", "agent"),
  },
  {
    id: "core.agents",
    path: "/agents",
    component: AgentsPage,
    meta: routeMeta(
      "nav.agents",
      "Agent Management",
      "settings",
      "global",
      "standard",
      "settings",
    ),
  },
  {
    id: "core.models",
    path: "/models",
    component: ModelsPage,
    meta: routeMeta(
      "nav.models",
      "Models",
      "settings",
      "global",
      "standard",
      "settings",
    ),
  },
  {
    id: "core.environments",
    path: "/environments",
    component: EnvironmentsPage,
    meta: routeMeta(
      "nav.environments",
      "Environments",
      "settings",
      "global",
      "standard",
      "settings",
    ),
  },
  {
    id: "core.offload-policy",
    path: "/offload-policy",
    component: OffloadPolicyPage,
    meta: routeMeta(
      "nav.offloadPolicy",
      "Tool Offload",
      "settings",
      "global",
      "standard",
      "settings",
    ),
  },
  {
    id: "core.agent-config",
    path: "/agent-config",
    component: AgentConfigPage,
    meta: routeMeta("nav.agentConfig", "Configuration", "workspace", "agent"),
  },
  {
    id: "core.security",
    path: "/security",
    component: SecurityPage,
    meta: routeMeta(
      "nav.security",
      "Security",
      "settings",
      "global",
      "standard",
      "settings",
    ),
  },
  {
    id: "core.token-usage",
    path: "/token-usage",
    component: TokenUsagePage,
    meta: routeMeta(
      "nav.tokenUsage",
      "Token Usage",
      "settings",
      "global",
      "standard",
      "settings",
    ),
  },
  {
    id: "core.agent-stats",
    path: "/agent-stats",
    component: AgentStatsPage,
    meta: routeMeta("nav.agentStats", "Agent Statistics", "workspace", "agent"),
  },
  {
    id: "core.voice-transcription",
    path: "/voice-transcription",
    component: VoiceTranscriptionPage,
    meta: routeMeta(
      "nav.voiceTranscription",
      "Voice Transcription",
      "settings",
      "global",
      "standard",
      "settings",
    ),
  },
  {
    id: "core.debug",
    path: "/debug",
    component: DebugPage,
    meta: routeMeta(
      "nav.debug",
      "Debug",
      "settings",
      "global",
      "standard",
      "settings",
    ),
  },
  {
    id: "core.backups",
    path: "/backups",
    component: BackupsPage,
    meta: routeMeta(
      "nav.backups",
      "Backups",
      "settings",
      "global",
      "standard",
      "settings",
    ),
  },
  {
    id: "core.marketplace",
    path: "/market",
    component: MarketplacePage,
    meta: routeMeta("nav.marketplace", "Extension", "extensions", "global"),
  },
  {
    id: "core.import",
    path: "/imports",
    component: ImportPage,
    meta: routeMeta("nav.import", "Import", "extensions", "global"),
  },
  // Deep-link / refresh target: `/apps/<id>` also lands on the App Center,
  // which opens the app inline (with the “← App Center” bar) from the URL.
  {
    id: "core.app-center.embed",
    path: "/apps/:appId",
    component: AppCenterPage,
    meta: routeMeta(
      "nav.apps",
      "Apps",
      "extensions",
      "global",
      "immersive",
      "search-only",
    ),
  },
];

routeRegistry.addBuiltin(BUILTIN_ROUTES);

// Suspense imported above is used by lazyImportWithRetry consumers; ref keeps
// TS from tree-shaking the import in older bundler configs.
void Suspense;
