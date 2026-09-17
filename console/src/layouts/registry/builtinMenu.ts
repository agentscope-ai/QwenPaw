/**
 * builtinMenu.ts — host's built-in sidebar menu entries as data.
 *
 * Importing this module self-registers all builtins into menuRegistry, so the
 * Sidebar's `useMenuItems()` snapshot returns them on first render. Plugins
 * register via `QwenPaw.menu.add(...)` which lands in the same registry, so
 * Sidebar treats core + plugin items uniformly.
 *
 * ── Naming convention ──────────────────────────────────────────────────────
 *  Group ids: `core.<name>-group` (e.g. core.control-group)
 *  Item ids:  `core.<key>`        (e.g. core.workspace)
 *  Plugin items use their own prefix (e.g. cloudpaw.a2a) — no clash possible.
 *
 * ── Sticky chat button carve-out ───────────────────────────────────────────
 *  `core.chat` is NOT in this data. The sticky chat button lives outside the
 *  antd <Menu> (rendered next to AgentSelector with bespoke styling); see
 *  Sidebar.tsx. We don't model it as menu data because it has zero antd-Menu
 *  semantics in common with the rest of the sidebar entries.
 *
 * ── Order convention ───────────────────────────────────────────────────────
 *  Within each group, items use order = 10/20/30/… in their natural sequence
 *  so plugins can insert with order 15/25 without colliding.
 */
import {
  SparkAgentLine,
  SparkBarChartLine,
  SparkBrowseLine,
  SparkDataLine,
  SparkDateLine,
  SparkDebugLine,
  SparkEmailLine,
  SparkInternetLine,
  SparkMagicWandLine,
  SparkMcpMcpLine,
  SparkMicLine,
  SparkModePlazaLine,
  SparkModifyLine,
  SparkMyApplicationLine,
  SparkOtherLine,
  SparkPluginLine,
  SparkSaveLine,
  SparkToolLine,
  SparkUserGroupLine,
  SparkVoiceChat01Line,
  SparkWifiLine,
} from "@agentscope-ai/icons";
import { Database, Files, GitBranch, ScanSearch } from "lucide-react";
import i18next from "i18next";
import { menuRegistry } from "../../plugins/registry/store";
import type { MenuItem } from "../../plugins/registry/types";
import { Capability } from "../../access/capabilities";

/** Translate a nav key. Falls back to defaultValue when i18n hasn't loaded. */
const navLabel = (key: string, defaultValue?: string) => (): string =>
  i18next.t(key, defaultValue ?? key);

export const BUILTIN_MENU: MenuItem[] = [
  // ── Agent-scoped (Sidebar Menu #1) ───────────────────────────────────────
  {
    id: "core.inbox",
    location: "primary.agentScoped",
    label: navLabel("nav.inbox"),
    icon: SparkEmailLine,
    route: "core.inbox",
    order: 10,
  },

  {
    id: "core.app-center",
    location: "primary.agentScoped",
    label: navLabel("nav.apps", "Apps"),
    icon: SparkMyApplicationLine,
    route: "core.app-center",
    order: 15,
  },

  // control-group
  {
    id: "core.control-group",
    location: "primary.agentScoped",
    label: navLabel("nav.control"),
    isGroup: true,
    order: 20,
  },
  {
    id: "core.channels",
    location: "primary.agentScoped",
    parentId: "core.control-group",
    label: navLabel("nav.channels"),
    icon: SparkWifiLine,
    route: "core.channels",
    order: 10,
  },
  {
    id: "core.sessions",
    location: "primary.agentScoped",
    parentId: "core.control-group",
    label: navLabel("nav.sessions"),
    icon: SparkUserGroupLine,
    route: "core.sessions",
    order: 20,
  },
  {
    id: "core.cron-jobs",
    location: "primary.agentScoped",
    parentId: "core.control-group",
    label: navLabel("nav.cronJobs"),
    icon: SparkDateLine,
    route: "core.cron-jobs",
    order: 30,
  },
  {
    id: "core.heartbeat",
    location: "primary.agentScoped",
    parentId: "core.control-group",
    label: navLabel("nav.heartbeat"),
    icon: SparkVoiceChat01Line,
    route: "core.heartbeat",
    order: 40,
  },

  // workspace-group
  {
    id: "core.workspace-group",
    location: "primary.agentScoped",
    label: navLabel("nav.agent"),
    isGroup: true,
    order: 30,
  },
  {
    id: "core.files",
    location: "primary.agentScoped",
    parentId: "core.workspace-group",
    label: navLabel("nav.files"),
    icon: Files,
    route: "core.files",
    order: 5,
  },
  {
    id: "core.skills",
    location: "primary.agentScoped",
    parentId: "core.workspace-group",
    label: navLabel("nav.skills"),
    icon: SparkMagicWandLine,
    route: "core.skills",
    order: 10,
  },
  {
    id: "core.tools",
    location: "primary.agentScoped",
    parentId: "core.workspace-group",
    label: navLabel("nav.tools"),
    icon: SparkToolLine,
    route: "core.tools",
    order: 20,
  },
  {
    id: "core.mcp",
    location: "primary.agentScoped",
    parentId: "core.workspace-group",
    label: navLabel("nav.mcp"),
    icon: SparkMcpMcpLine,
    route: "core.mcp",
    order: 40,
  },
  {
    id: "core.agent-config",
    location: "primary.agentScoped",
    parentId: "core.workspace-group",
    label: navLabel("nav.agentConfig"),
    icon: SparkModifyLine,
    route: "core.agent-config",
    order: 60,
  },
  {
    id: "core.agent-stats",
    location: "primary.agentScoped",
    parentId: "core.workspace-group",
    label: navLabel("nav.agentStats"),
    icon: SparkBarChartLine,
    route: "core.agent-stats",
    order: 70,
  },
  {
    id: "core.checkpoints",
    location: "primary.agentScoped",
    parentId: "core.agent-group",
    label: navLabel("checkpoints.nav"),
    icon: GitBranch,
    route: "core.checkpoints",
    order: 80,
  },

  // ── Settings (Sidebar Menu #2) ───────────────────────────────────────────
  {
    id: "core.settings-group",
    location: "primary.settings",
    label: navLabel("nav.settings"),
    isGroup: true,
    order: 10,
  },
  {
    id: "core.agents",
    location: "primary.settings",
    parentId: "core.settings-group",
    label: navLabel("nav.agents"),
    icon: SparkAgentLine,
    route: "core.agents",
    order: 10,
  },
  {
    id: "core.models",
    location: "primary.settings",
    parentId: "core.settings-group",
    label: navLabel("nav.models"),
    icon: SparkModePlazaLine,
    route: "core.models",
    capability: Capability.PlatformSettingsManage,
    order: 20,
  },
  {
    id: "core.admin-users",
    location: "primary.settings",
    parentId: "core.settings-group",
    label: navLabel("nav.users", "User Management"),
    icon: SparkUserGroupLine,
    route: "core.admin-users",
    capability: Capability.UsersManage,
    order: 120,
  },
  {
    id: "core.admin-publications",
    location: "primary.settings",
    parentId: "core.settings-group",
    label: navLabel("nav.publications", "发布审核"),
    icon: SparkMyApplicationLine,
    route: "core.admin-publications",
    capability: Capability.PublicationsReview,
    order: 28,
  },
  {
    id: "core.skill-pool",
    location: "primary.settings",
    parentId: "core.settings-group",
    label: navLabel("nav.skillPool", "Skill Pool"),
    icon: SparkOtherLine,
    route: "core.skill-pool",
    capability: Capability.PlatformSettingsManage,
    order: 30,
  },
  {
    id: "core.environments",
    location: "primary.settings",
    parentId: "core.settings-group",
    label: navLabel("nav.environments"),
    icon: SparkInternetLine,
    route: "core.environments",
    capability: Capability.PlatformSettingsManage,
    order: 50,
  },
  {
    id: "core.offload-policy",
    location: "primary.settings",
    parentId: "core.settings-group",
    label: navLabel("nav.offloadPolicy", "Tool Offload"),
    icon: SparkDateLine,
    route: "core.offload-policy",
    capability: Capability.PlatformSettingsManage,
    order: 55,
  },
  {
    id: "core.security",
    location: "primary.settings",
    parentId: "core.settings-group",
    label: navLabel("nav.security"),
    icon: SparkBrowseLine,
    route: "core.security",
    capability: Capability.PlatformSettingsManage,
    order: 60,
  },
  {
    id: "core.system-status",
    location: "primary.settings",
    parentId: "core.settings-group",
    label: navLabel("nav.systemStatus", "System Status"),
    icon: Database,
    route: "core.system-status",
    capability: Capability.PlatformSettingsManage,
    order: 65,
  },
  {
    id: "core.migration-preview",
    location: "primary.settings",
    parentId: "core.settings-group",
    label: navLabel("nav.migrationPreview", "Migration Preview"),
    icon: ScanSearch,
    route: "core.migration-preview",
    capability: Capability.PlatformSettingsManage,
    order: 67,
  },
  {
    id: "core.token-usage",
    location: "primary.settings",
    parentId: "core.settings-group",
    label: navLabel("nav.tokenUsage"),
    icon: SparkDataLine,
    route: "core.token-usage",
    order: 70,
  },
  {
    id: "core.backups",
    location: "primary.settings",
    parentId: "core.settings-group",
    label: navLabel("nav.backups"),
    icon: SparkSaveLine,
    route: "core.backups",
    capability: Capability.PlatformSettingsManage,
    order: 80,
  },
  {
    id: "core.voice-transcription",
    location: "primary.settings",
    parentId: "core.settings-group",
    label: navLabel("nav.voiceTranscription"),
    icon: SparkMicLine,
    route: "core.voice-transcription",
    capability: Capability.PlatformSettingsManage,
    order: 90,
  },
  {
    id: "core.debug",
    location: "primary.settings",
    parentId: "core.settings-group",
    label: navLabel("nav.debug", "Debug"),
    icon: SparkDebugLine,
    route: "core.debug",
    capability: Capability.PlatformSettingsManage,
    order: 100,
  },
  {
    id: "core.plugin-manager",
    location: "primary.settings",
    parentId: "core.settings-group",
    label: navLabel("nav.pluginManager", "Plugin Manager"),
    icon: SparkPluginLine,
    route: "core.plugin-manager",
    capability: Capability.PlatformSettingsManage,
    order: 110,
  },
];

// Self-register at module load. main.tsx imports this file as a side-effect.
menuRegistry.addBuiltin(BUILTIN_MENU);
