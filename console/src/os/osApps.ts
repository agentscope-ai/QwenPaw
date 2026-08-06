/**
 * osApps.ts — Curated application manifest for the Desktop OS PoC.
 *
 * Maps route ids from the existing routeRegistry to desktop metadata:
 * icon (Lucide), display name (i18n key + fallback), accent colour, and
 * default window geometry. Adding more apps is a 1-line entry.
 */
import {
  MessageSquare,
  Files,
  Sparkles,
  Clock,
  Plug,
  Wrench,
  HeartPulse,
  Wifi,
  Inbox,
  Code,
  Store,
  Settings,
  Puzzle,
  History,
  FolderOpen,
  Network,
  Bot,
  BarChart3,
  type LucideIcon,
} from "lucide-react";
import type { MenuItem } from "../plugins/registry/types";

export interface OsAppDef {
  /** Must match a route id in routeRegistry (e.g. "core.skills"). */
  routeId: string;
  /** i18n key (fallback label follows after "|"). */
  labelKey: string;
  /** Fallback English name. */
  fallback: string;
  /** Lucide icon component. */
  Icon: LucideIcon;
  /** Accent colour (CSS value). */
  accent: string;
  /** Default window width. */
  defaultW: number;
  /** Default window height. */
  defaultH: number;
  /** Minimum window width (defaults to the global window minimum). */
  minW?: number;
  /** Minimum window height (defaults to the global window minimum). */
  minH?: number;
  /**
   * Plugin id (source) for plugin-derived apps (PawApps). Undefined for
   * built-in catalog apps and system apps. Used to route uninstall to the
   * backend (DELETE /plugins/{source}) vs. the local osPluginStore.
   */
  source?: string;
}

/**
 * The PoC features these 6 (+ Chat & Coding) apps to demonstrate the desktop
 * shell. Each entry references a route already registered in builtinRoutes.
 */
export const OS_APPS: OsAppDef[] = [
  {
    routeId: "core.chat",
    labelKey: "nav.chat",
    fallback: "Chat",
    Icon: MessageSquare,
    accent: "#3b82f6",
    defaultW: 880,
    defaultH: 640,
  },
  {
    routeId: "core.files",
    labelKey: "nav.files",
    fallback: "Files",
    Icon: Files,
    accent: "#f36b21",
    defaultW: 1180,
    defaultH: 720,
    minW: 760,
    minH: 480,
  },
  {
    routeId: "core.coding",
    labelKey: "nav.coding",
    fallback: "Coding IDE",
    Icon: Code,
    accent: "#64748b",
    defaultW: 1020,
    defaultH: 700,
  },
  {
    routeId: "core.skills",
    labelKey: "nav.skills",
    fallback: "Skills",
    Icon: Sparkles,
    accent: "#8b5cf6",
    defaultW: 780,
    defaultH: 560,
  },
  {
    routeId: "core.cron-jobs",
    labelKey: "nav.cronJobs",
    fallback: "Cron Jobs",
    Icon: Clock,
    accent: "#f97316",
    defaultW: 720,
    defaultH: 520,
  },
  {
    routeId: "core.mcp",
    labelKey: "nav.mcp",
    fallback: "MCP",
    Icon: Plug,
    accent: "#06b6d4",
    defaultW: 760,
    defaultH: 540,
  },
  {
    routeId: "core.tools",
    labelKey: "nav.tools",
    fallback: "Tools",
    Icon: Wrench,
    accent: "#10b981",
    defaultW: 720,
    defaultH: 500,
  },
  {
    routeId: "core.heartbeat",
    labelKey: "nav.heartbeat",
    fallback: "Heartbeat",
    Icon: HeartPulse,
    accent: "#ef4444",
    defaultW: 560,
    defaultH: 440,
  },
  {
    routeId: "core.channels",
    labelKey: "nav.channels",
    fallback: "Channels",
    Icon: Wifi,
    accent: "#22c55e",
    defaultW: 680,
    defaultH: 500,
  },
  {
    routeId: "core.inbox",
    labelKey: "nav.inbox",
    fallback: "Inbox",
    Icon: Inbox,
    accent: "#eab308",
    defaultW: 640,
    defaultH: 500,
  },
  {
    routeId: "core.sessions",
    labelKey: "nav.sessions",
    fallback: "Sessions",
    Icon: History,
    accent: "#0ea5e9",
    defaultW: 820,
    defaultH: 600,
    minW: 780,
    minH: 480,
  },
  {
    routeId: "core.workspace",
    labelKey: "nav.workspace",
    fallback: "Workspace",
    Icon: FolderOpen,
    accent: "#f59e0b",
    defaultW: 900,
    defaultH: 640,
  },
  {
    routeId: "core.acp",
    labelKey: "nav.acp",
    fallback: "ACP",
    Icon: Network,
    accent: "#14b8a6",
    defaultW: 780,
    defaultH: 560,
  },
  {
    routeId: "core.agent-config",
    labelKey: "nav.agentConfig",
    fallback: "Agent Config",
    Icon: Bot,
    accent: "#7c3aed",
    defaultW: 1020,
    defaultH: 640,
    minW: 900,
    minH: 520,
  },
  {
    routeId: "core.agent-stats",
    labelKey: "nav.agentStats",
    fallback: "Agent Stats",
    Icon: BarChart3,
    accent: "#ec4899",
    defaultW: 820,
    defaultH: 600,
    minW: 900,
    minH: 520,
  },
];

/** Lookup helper (searches catalog + system apps). */
export function findAppDef(routeId: string): OsAppDef | undefined {
  if (routeId === STORE_APP.routeId) return STORE_APP;
  if (routeId === SETTINGS_APP.routeId) return SETTINGS_APP;
  return OS_APPS.find((a) => a.routeId === routeId);
}

/**
 * App Store — a system app rendered by a native component (not route-backed).
 * Always available; simulates plugin management for the other catalog apps.
 */
export const STORE_APP: OsAppDef = {
  routeId: "os.store",
  labelKey: "os.appStore",
  fallback: "App Store",
  Icon: Store,
  accent: "#FF7F16",
  defaultW: 860,
  defaultH: 600,
};

/**
 * System Settings — a system app that aggregates every settings route into a
 * single macOS-style window (left list + right route pane). Route-less; the
 * desktop renders SettingsApp for it.
 */
export const SETTINGS_APP: OsAppDef = {
  routeId: "os.settings",
  labelKey: "os.systemSettings",
  fallback: "System Settings",
  Icon: Settings,
  accent: "#6b7280",
  defaultW: 1200,
  defaultH: 720,
  minW: 960,
  minH: 560,
};

// ───────────────────────────────────────────────────────────────────────────
// Plugin apps (PawApps) — derived dynamically from the route registry.
//
// Installed plugins like agent-office register one or more Routes (pages) plus
// a MenuItem (label + icon). A plugin is treated as a single desktop "app"
// bundle: it may contribute several "/apps/" routes (plus a mirror route), but
// it surfaces as ONE app keyed by its source (plugin id). All plugin apps
// share a unified Puzzle icon with a hash-derived accent so they read as one
// family; the display name comes from a matching menu item's static label,
// falling back to a title derived from the path slug, then the source id.
// ───────────────────────────────────────────────────────────────────────────

/** Route path prefix that marks a plugin as a desktop app (PawApp). */
export const PLUGIN_APP_PREFIX = "/apps/";

const PLUGIN_ACCENTS = [
  "#6366f1",
  "#ec4899",
  "#14b8a6",
  "#f59e0b",
  "#8b5cf6",
  "#0ea5e9",
  "#ef4444",
  "#22c55e",
];

/** Deterministic accent from a seed so an app keeps the same colour. */
function hashAccent(seed: string): string {
  let h = 0;
  for (let i = 0; i < seed.length; i += 1) {
    h = (h * 31 + seed.charCodeAt(i)) >>> 0;
  }
  return PLUGIN_ACCENTS[h % PLUGIN_ACCENTS.length];
}

/** Turn "/apps/agent-office" into "Agent Office" as a name fallback. */
function slugToTitle(path: string): string {
  const slug = path.replace(PLUGIN_APP_PREFIX, "").split("/")[0] || path;
  return slug
    .split(/[-_]/)
    .filter(Boolean)
    .map((s) => s.charAt(0).toUpperCase() + s.slice(1))
    .join(" ");
}

/** Minimal route shape needed here (matches ResolvedRoute). */
interface RouteLike {
  id: string;
  path: string;
  source: string;
}

/**
 * Derive desktop app defs for installed plugin bundles (PawApps) from the live
 * route + menu registries. Each plugin (source) yields at most one app, using
 * its first "/apps/" route as the launch/render target. Pure — safe to call
 * inside useMemo.
 */
export function buildPluginApps(
  routes: RouteLike[],
  menuItems: MenuItem[],
): OsAppDef[] {
  const labelByRoute = new Map<string, string>();
  for (const m of menuItems) {
    if (m.route && typeof m.label === "string") {
      labelByRoute.set(m.route, m.label);
    }
  }
  // Group "/apps/" routes by source so each plugin bundle appears once. The
  // first route wins as the bundle's launch target.
  const bundleRoute = new Map<string, RouteLike>();
  for (const r of routes) {
    if (!r.path.startsWith(PLUGIN_APP_PREFIX) || r.source === "core") continue;
    if (!bundleRoute.has(r.source)) bundleRoute.set(r.source, r);
  }
  return [...bundleRoute.entries()].map(([source, r]) => {
    const name = labelByRoute.get(r.id) ?? slugToTitle(r.path) ?? source;
    return {
      routeId: r.id,
      labelKey: name,
      fallback: name,
      Icon: Puzzle,
      accent: hashAccent(source),
      defaultW: 960,
      defaultH: 680,
      source,
    };
  });
}
