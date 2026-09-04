import {
  Suspense,
  useMemo,
  useState,
  type ComponentType,
  type ReactNode,
} from "react";
import { Button, Input, Spin } from "antd";
import {
  Archive,
  ArrowLeft,
  Bot,
  Bug,
  Cpu,
  Gauge,
  Globe,
  HeartPulse,
  Mic,
  PanelLeft,
  Plug,
  Radio,
  ScanLine,
  Search,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { ChunkErrorBoundary } from "@/components/ChunkErrorBoundary";
import { useTheme } from "@/contexts/ThemeContext";
import { useMenuItems, useRoutes } from "@/plugins/registry/hooks";
import { usePlugins } from "@/plugins/PluginContext";
import { findMenuItem, flattenMenu } from "@/layouts/registry/adapter";
import GeneralSettings from "./GeneralSettings";
import NavigationSettings from "./NavigationSettings";
import SettingsAgentSelector from "./SettingsAgentSelector";
import styles from "./index.module.less";

interface SettingsPageDefinition {
  key: string;
  labelKey?: string;
  label?: ReactNode;
  fallback: string;
  descriptionKey: string;
  descriptionFallback: string;
  routeId?: string;
  Component?: ComponentType;
  Icon?: LucideIcon;
  icon?: ReactNode;
  legacyPath?: string;
  href?: string;
}

interface SettingsGroupDefinition {
  key: string;
  labelKey: string;
  fallback: string;
  pages: SettingsPageDefinition[];
}

const SETTINGS_GROUPS: SettingsGroupDefinition[] = [
  {
    key: "application",
    labelKey: "settingsCenter.groups.application",
    fallback: "Application",
    pages: [
      {
        key: "general",
        labelKey: "settingsCenter.pages.general",
        fallback: "General",
        descriptionKey: "settingsCenter.descriptions.general",
        descriptionFallback: "Language, theme and application behavior",
        Component: GeneralSettings,
        Icon: Wrench,
      },
      {
        key: "navigation",
        labelKey: "settingsCenter.pages.navigation",
        fallback: "Sidebar",
        descriptionKey: "settingsCenter.descriptions.navigation",
        descriptionFallback: "Choose which shortcuts appear in the sidebar",
        Component: NavigationSettings,
        Icon: PanelLeft,
      },
    ],
  },
  {
    key: "agent-configuration",
    labelKey: "settingsCenter.groups.agentConfiguration",
    fallback: "Agent configuration",
    pages: [
      {
        key: "channels",
        labelKey: "nav.channels",
        fallback: "Channels",
        descriptionKey: "settingsCenter.descriptions.channels",
        descriptionFallback: "Connect IM and message channels",
        routeId: "core.channels",
        Icon: Radio,
      },
      {
        key: "heartbeat",
        labelKey: "nav.heartbeat",
        fallback: "Heartbeat",
        descriptionKey: "settingsCenter.descriptions.heartbeat",
        descriptionFallback: "Agent availability and periodic wake-up",
        routeId: "core.heartbeat",
        Icon: HeartPulse,
      },
      {
        key: "agent-skills",
        labelKey: "nav.skills",
        fallback: "Skills",
        descriptionKey: "settingsCenter.descriptions.skills",
        descriptionFallback: "Manage agent skills",
        routeId: "core.skills",
        Icon: Sparkles,
      },
      {
        key: "tools",
        labelKey: "nav.tools",
        fallback: "Tools",
        descriptionKey: "settingsCenter.descriptions.tools",
        descriptionFallback: "Configure available tools",
        routeId: "core.tools",
        Icon: Wrench,
      },
      {
        key: "mcp",
        labelKey: "nav.mcp",
        fallback: "MCP",
        descriptionKey: "settingsCenter.descriptions.mcp",
        descriptionFallback: "Configure MCP services",
        routeId: "core.mcp",
        Icon: Plug,
      },
      {
        key: "acp",
        labelKey: "nav.acp",
        fallback: "ACP",
        descriptionKey: "settingsCenter.descriptions.acp",
        descriptionFallback: "Configure ACP agents",
        routeId: "core.acp",
        Icon: ScanLine,
      },
      {
        key: "agent-config",
        labelKey: "nav.agentConfig",
        fallback: "Configuration",
        descriptionKey: "settingsCenter.descriptions.agentConfig",
        descriptionFallback: "Configure agent runtime behavior",
        routeId: "core.agent-config",
        Icon: SlidersHorizontal,
      },
    ],
  },
  {
    key: "global",
    labelKey: "settingsCenter.groups.global",
    fallback: "Global settings",
    pages: [
      {
        key: "agents",
        labelKey: "nav.agents",
        fallback: "Agents",
        descriptionKey: "settingsCenter.descriptions.agents",
        descriptionFallback: "QwenPaw, Codex and Qoder profiles",
        routeId: "core.agents",
        Icon: Bot,
      },
      {
        key: "models",
        labelKey: "nav.models",
        fallback: "Models",
        descriptionKey: "settingsCenter.descriptions.models",
        descriptionFallback: "Providers, credentials and model catalog",
        routeId: "core.models",
        Icon: Cpu,
      },
      {
        key: "skill-pool",
        labelKey: "nav.skillPool",
        fallback: "Skill Pool",
        descriptionKey: "settingsCenter.descriptions.skillPool",
        descriptionFallback: "Reusable skills and extensions",
        routeId: "core.skill-pool",
        Icon: Sparkles,
      },
      {
        key: "environments",
        labelKey: "nav.environments",
        fallback: "Environment variables",
        descriptionKey: "settingsCenter.descriptions.environments",
        descriptionFallback: "Runtime variables and secrets",
        routeId: "core.environments",
        Icon: Globe,
      },
      {
        key: "security",
        labelKey: "nav.security",
        fallback: "Security",
        descriptionKey: "settingsCenter.descriptions.security",
        descriptionFallback: "Execution policies and protection rules",
        routeId: "core.security",
        Icon: ShieldCheck,
      },
      {
        key: "offload-policy",
        labelKey: "nav.offloadPolicy",
        fallback: "Tool offload",
        descriptionKey: "settingsCenter.descriptions.offloadPolicy",
        descriptionFallback: "Background execution policy",
        routeId: "core.offload-policy",
        Icon: Wrench,
      },
      {
        key: "token-usage",
        labelKey: "nav.tokenUsage",
        fallback: "Token usage",
        descriptionKey: "settingsCenter.descriptions.tokenUsage",
        descriptionFallback: "Usage statistics and trends",
        routeId: "core.token-usage",
        Icon: Gauge,
      },
      {
        key: "backups",
        labelKey: "nav.backups",
        fallback: "Backups",
        descriptionKey: "settingsCenter.descriptions.backups",
        descriptionFallback: "Export, restore and migrate data",
        routeId: "core.backups",
        Icon: Archive,
      },
      {
        key: "debug",
        labelKey: "nav.debug",
        fallback: "Debug",
        descriptionKey: "settingsCenter.descriptions.debug",
        descriptionFallback: "Logs and diagnostics",
        routeId: "core.debug",
        Icon: Bug,
      },
      {
        key: "voice",
        labelKey: "nav.voiceTranscription",
        fallback: "Voice",
        descriptionKey: "settingsCenter.descriptions.voice",
        descriptionFallback: "Speech input and transcription",
        routeId: "core.voice-transcription",
        Icon: Mic,
      },
    ],
  },
];

function pageKeyFromPath(pathname: string) {
  const key = pathname.match(/\/settings\/([^/]+)/)?.[1];
  return key || "general";
}

export default function SettingsCenter() {
  const { t } = useTranslation();
  const { isDark } = useTheme();
  const location = useLocation();
  const navigate = useNavigate();
  const routes = useRoutes();
  const { loading: pluginsLoading } = usePlugins();
  const rawSettingsMenu = useMenuItems("primary.settings");
  const [query, setQuery] = useState("");

  const componentByRouteId = useMemo(() => {
    const result = new Map<string, ComponentType>();
    for (const route of routes) result.set(route.id, route.Component);
    return result;
  }, [routes]);

  const availableGroups = useMemo(() => {
    const coreGroups = SETTINGS_GROUPS.map((group) => ({
      ...group,
      pages: group.pages.filter(
        (page) => !page.routeId || componentByRouteId.has(page.routeId),
      ),
    })).filter((group) => group.pages.length > 0);
    const representedRoutes = new Set(
      coreGroups.flatMap((group) =>
        group.pages.flatMap((page) => (page.routeId ? [page.routeId] : [])),
      ),
    );
    const extensionPages = flattenMenu(rawSettingsMenu, routes, 16).flatMap(
      (entry): SettingsPageDefinition[] => {
        const item = findMenuItem(rawSettingsMenu, entry.key);
        if (item?.route && representedRoutes.has(item.route)) return [];
        if (!entry.path && !entry.href) return [];
        return [
          {
            key: `extension-${encodeURIComponent(entry.key)}`,
            label: entry.label,
            fallback: typeof entry.label === "string" ? entry.label : entry.key,
            descriptionKey: "settingsCenter.descriptions.extension",
            descriptionFallback: "Extension settings",
            icon: entry.icon,
            legacyPath: entry.path || undefined,
            href: entry.href,
          },
        ];
      },
    );
    return extensionPages.length > 0
      ? [
          ...coreGroups,
          {
            key: "extensions",
            labelKey: "settingsCenter.groups.extensions",
            fallback: "Extensions",
            pages: extensionPages,
          },
        ]
      : coreGroups;
  }, [componentByRouteId, rawSettingsMenu, routes]);

  const activeKey = pageKeyFromPath(location.pathname);
  const allPages = availableGroups.flatMap((group) => group.pages);
  const matchedActivePage = allPages.find((page) => page.key === activeKey);
  const activePage = matchedActivePage ?? allPages[0];
  const ActiveComponent = activePage?.Component
    ? activePage.Component
    : activePage?.routeId
    ? componentByRouteId.get(activePage.routeId)
    : undefined;

  const pageLabel = (page: SettingsPageDefinition): ReactNode =>
    page.label ?? t(page.labelKey ?? page.key, page.fallback);
  const searchablePageLabel = (page: SettingsPageDefinition): string => {
    const label = pageLabel(page);
    return typeof label === "string" || typeof label === "number"
      ? String(label)
      : page.fallback;
  };

  const normalizedQuery = query.trim().toLocaleLowerCase();
  const visibleGroups = normalizedQuery
    ? availableGroups
        .map((group) => ({
          ...group,
          pages: group.pages.filter((page) =>
            `${searchablePageLabel(page)} ${t(
              page.descriptionKey,
              page.descriptionFallback,
            )}`
              .toLocaleLowerCase()
              .includes(normalizedQuery),
          ),
        }))
        .filter((group) => group.pages.length > 0)
    : availableGroups;

  const returnTo =
    (location.state as { settingsReturnTo?: string } | null)
      ?.settingsReturnTo || "/chat";

  if (pluginsLoading && !matchedActivePage && activeKey !== "general") {
    return (
      <div
        className={`${styles.root} ${isDark ? styles.rootDark : ""}`}
        data-theme={isDark ? "dark" : "light"}
      >
        <div className={styles.loading}>
          <Spin tip={t("common.loading")} />
        </div>
      </div>
    );
  }

  if (!pluginsLoading && !matchedActivePage && activeKey !== "general") {
    return (
      <Navigate
        to="/settings/general"
        replace
        state={{ settingsReturnTo: returnTo }}
      />
    );
  }

  const openPage = (page: SettingsPageDefinition) => {
    if (page.href) {
      window.open(page.href, "_blank", "noopener,noreferrer");
      return;
    }
    if (page.legacyPath) {
      navigate(page.legacyPath);
      return;
    }
    navigate(`/settings/${page.key}`, {
      state: { settingsReturnTo: returnTo },
    });
  };

  return (
    <div
      className={`${styles.root} ${isDark ? styles.rootDark : ""}`}
      data-theme={isDark ? "dark" : "light"}
    >
      <div className={styles.body}>
        <aside className={styles.sidebar}>
          <Button
            type="text"
            className={styles.backButton}
            icon={<ArrowLeft size={18} />}
            onClick={() => navigate(returnTo)}
          >
            {t("settingsCenter.backToApp", "Back to app")}
          </Button>
          <Input
            className={styles.searchInput}
            allowClear
            value={query}
            prefix={<Search size={15} />}
            placeholder={t(
              "settingsCenter.searchPlaceholder",
              "Search settings",
            )}
            onChange={(event) => setQuery(event.target.value)}
          />
          <nav className={styles.navigation}>
            {visibleGroups.map((group) => (
              <section key={group.key} className={styles.navGroup}>
                <h2>{t(group.labelKey, group.fallback)}</h2>
                {group.key === "agent-configuration" && (
                  <SettingsAgentSelector />
                )}
                {group.pages.map((page) => {
                  const Icon = page.Icon;
                  return (
                    <button
                      key={page.key}
                      type="button"
                      className={`${styles.navItem} ${
                        activePage?.key === page.key ? styles.navItemActive : ""
                      }`}
                      onClick={() => openPage(page)}
                    >
                      {page.icon ?? (Icon ? <Icon size={16} /> : null)}
                      <strong>{pageLabel(page)}</strong>
                    </button>
                  );
                })}
              </section>
            ))}
            {visibleGroups.length === 0 && (
              <div className={styles.noResults}>
                {t("settingsCenter.noResults", "No matching settings")}
              </div>
            )}
          </nav>
        </aside>

        <main className={styles.content}>
          {ActiveComponent ? (
            <ChunkErrorBoundary resetKey={activePage?.key ?? "settings"}>
              <Suspense
                fallback={
                  <div className={styles.loading}>
                    <Spin tip={t("common.loading")} />
                  </div>
                }
              >
                <ActiveComponent />
              </Suspense>
            </ChunkErrorBoundary>
          ) : null}
        </main>
      </div>
    </div>
  );
}
