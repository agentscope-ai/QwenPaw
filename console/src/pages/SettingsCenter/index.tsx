import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type ComponentType,
  type ReactNode,
} from "react";
import { Alert, Button, Input, Select, Spin } from "antd";
import { LayoutGroup, motion, useReducedMotion } from "motion/react";
import {
  Archive,
  Blocks,
  CalendarDays,
  ArrowLeft,
  Bot,
  Bug,
  Cpu,
  Download,
  Gauge,
  Globe,
  HeartPulse,
  Mic,
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
import { ChunkRecoverySuspense } from "@/components/ChunkRecoverySuspense";
import { useTheme } from "@/contexts/ThemeContext";
import { channelApi } from "@/api/modules/channel";
import { request } from "@/api/request";
import type { AgentsRunningConfig } from "@/api/types";
import { useMenuItems, useRoutes } from "@/plugins/registry/hooks";
import { usePlugins } from "@/plugins/PluginContext";
import {
  usePluginSettingsSearch,
  type SettingsSearchTarget,
} from "@/plugins/settingsSearch";
import { resolveLocalized } from "@/plugins/registry/types";
import {
  findMenuItem,
  flattenMenu,
  renderIcon,
} from "@/layouts/registry/adapter";
import { useAgentStore } from "@/stores/agentStore";
import { supportsPortabilityImport } from "@/utils/agentBackend";
import GeneralSettings from "./GeneralSettings";
import SettingsAgentSelector from "./SettingsAgentSelector";
import styles from "./index.module.less";
import {
  matchesSettingsSearch,
  searchSettingsItems,
  settingsSearchPath,
  settingsSearchTarget,
  searchChannelNames,
  searchToolNames,
  settingsSearchLabel,
  settingsSearchUnavailableReason,
  type SettingsSearchAvailability,
} from "./settingsSearch";
import { useSettingsSearchTarget } from "./useSettingsSearchTarget";
import { SettingsSearchRequest } from "./SettingsSearchRequest";

interface SearchResult {
  id: string;
  label: string;
  path: string;
  target: SettingsSearchTarget;
  disabled?: boolean;
  reason?: string;
}

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
    ],
  },
  {
    key: "agent-configuration",
    labelKey: "settingsCenter.groups.agentConfiguration",
    fallback: "Agent configuration",
    pages: [
      {
        key: "cron-jobs",
        labelKey: "nav.cronJobs",
        fallback: "Scheduled tasks",
        descriptionKey: "nav.cronJobs",
        descriptionFallback: "Scheduled tasks",
        routeId: "core.cron-jobs",
        Icon: CalendarDays,
      },
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
        key: "import",
        labelKey: "nav.import",
        fallback: "Import",
        descriptionKey: "portabilityImport.description",
        descriptionFallback:
          "Bring conversations and tool settings from other AI applications into QwenPaw.",
        routeId: "core.import",
        Icon: Download,
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
        key: "marketplace",
        labelKey: "nav.marketplace",
        fallback: "Extensions",
        descriptionKey: "nav.marketplace",
        descriptionFallback: "Extensions",
        routeId: "core.marketplace",
        Icon: Blocks,
      },
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
  const reducedMotion = useReducedMotion();
  const { t, i18n } = useTranslation();
  const { isDark } = useTheme();
  const location = useLocation();
  const navigate = useNavigate();
  const routes = useRoutes();
  const pluginSearch = usePluginSettingsSearch();
  const selectedAgent = useAgentStore((state) => state.selectedAgent);
  const selectedBackend = useAgentStore(
    (state) =>
      state.agents.find((agent) => agent.id === state.selectedAgent)?.backend,
  );
  const { loading: pluginsLoading } = usePlugins();
  const rawAgentMenu = useMenuItems("primary.agentScoped");
  const rawSettingsMenu = useMenuItems("primary.settings");
  const canImport = useAgentStore(({ selectedAgent, agents }) =>
    supportsPortabilityImport(
      agents.find((agent) => agent.id === selectedAgent),
    ),
  );
  const [query, setQuery] = useState("");
  const [runtimeAvailability, setRuntimeAvailability] = useState<{
    agentId: string | null;
    context: SettingsSearchAvailability;
  } | null>(null);
  const hasRuntime = routes.some((route) => route.id === "core.agent-config");
  useEffect(() => {
    if (!hasRuntime || (selectedBackend && selectedBackend !== "qwenpaw"))
      return;
    const controller = new AbortController();
    void request<AgentsRunningConfig>("/workspace/running-config", {
      headers: { "X-Agent-Id": selectedAgent || "default" },
      signal: controller.signal,
    })
      .then((config) => {
        if (!controller.signal.aborted)
          setRuntimeAvailability({
            agentId: selectedAgent,
            context: {
              strategy: config.light_context_config?.strategy ?? "scroll",
              memoryBackend: config.memory_manager_backend ?? "remelight",
            },
          });
      })
      .catch(() => {});
    return () => controller.abort();
  }, [hasRuntime, selectedAgent, selectedBackend]);
  const [channelNames, setChannelNames] = useState<{
    agentId: string | null;
    labels: Record<string, string>;
  } | null>(null);
  const hasChannels = routes.some((route) => route.id === "core.channels");
  useEffect(() => {
    if (!hasChannels) return;
    const controller = new AbortController();
    void channelApi
      .listChannelSchemas({
        agentId: selectedAgent || "default",
        signal: controller.signal,
      })
      .then((schemas) => {
        if (controller.signal.aborted) return;
        setChannelNames({
          agentId: selectedAgent,
          labels: Object.fromEntries(
            Object.entries(schemas ?? {}).map(([key, schema]) => [
              key,
              schema.label,
            ]),
          ),
        });
      })
      .catch(() => {});
    return () => controller.abort();
  }, [hasChannels, selectedAgent]);

  const componentByRouteId = useMemo(() => {
    const result = new Map<string, ComponentType>();
    for (const route of routes) result.set(route.id, route.Component);
    return result;
  }, [routes]);

  const availableGroups = useMemo(() => {
    const registeredMenu = [...rawAgentMenu, ...rawSettingsMenu];
    const coreGroups = SETTINGS_GROUPS.map((group) => ({
      ...group,
      pages: group.pages
        .filter((page) => !page.routeId || componentByRouteId.has(page.routeId))
        .map((page) => {
          const menuIcon = page.routeId
            ? findMenuItem(registeredMenu, page.routeId)?.icon
            : undefined;
          return menuIcon ? { ...page, icon: renderIcon(menuIcon, 18) } : page;
        }),
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
            routeId: item?.route,
            legacyPath: entry.path || undefined,
            href: entry.href,
          },
        ];
      },
    );
    const extensionRouteIds = new Set(
      extensionPages.map((page) => page.routeId),
    );
    for (const { pluginId, item } of pluginSearch) {
      const route = routes.find((route) => route.id === item.routeId);
      if (
        !route ||
        representedRoutes.has(item.routeId) ||
        extensionRouteIds.has(item.routeId)
      )
        continue;
      extensionRouteIds.add(item.routeId);
      extensionPages.push({
        key: `extension-${encodeURIComponent(item.routeId)}`,
        label: resolveLocalized(item.groupPath, i18n.language)?.[0] ?? pluginId,
        fallback: pluginId,
        descriptionKey: "settingsCenter.descriptions.extension",
        descriptionFallback: "Extension settings",
        routeId: item.routeId,
        legacyPath: route.path,
      });
    }
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
  }, [
    componentByRouteId,
    rawAgentMenu,
    rawSettingsMenu,
    routes,
    pluginSearch,
    i18n.language,
  ]);

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

  const contentRef = useRef<HTMLElement>(null);
  const [searchTarget, setSearchTarget] = useState<SettingsSearchTarget | null>(
    null,
  );
  const activeSearchTarget =
    searchTarget?.agentId === selectedAgent ? searchTarget : null;
  useSettingsSearchTarget(contentRef, activeSearchTarget, activePage?.key);
  const matchingItems = new Map<string, SearchResult[]>(
    allPages.map((page) => {
      const pageContext = `${searchablePageLabel(page)} ${page.fallback}`;
      const items: SearchResult[] = searchSettingsItems(
        page.key,
        query,
        t,
        pageContext,
      ).map((key) => {
        const target = settingsSearchTarget(page.key, key, t);
        const unavailable =
          page.key === "agent-config" &&
          (target.targetId?.startsWith("models.") ||
            target.targetId?.startsWith("modelSelector.")) &&
          selectedBackend &&
          selectedBackend !== "qwenpaw";
        const unavailableReason = settingsSearchUnavailableReason(
          page.key,
          key,
          runtimeAvailability?.agentId === selectedAgent
            ? runtimeAvailability.context
            : undefined,
          t,
        );
        return {
          id: key,
          label: settingsSearchLabel(key, t),
          path: settingsSearchPath(key, t, undefined, page.key).join(" → "),
          target,
          disabled: Boolean(unavailable || unavailableReason),
          reason: unavailable
            ? t(
                "settingsCenter.searchUnsupportedBackend",
                "Model routing is available for QwenPaw agents.",
              )
            : unavailableReason ?? target.hint,
        };
      });
      if (page.key === "channels")
        items.push(
          ...searchChannelNames(
            query,
            t,
            pageContext,
            channelNames?.agentId === selectedAgent ? channelNames.labels : {},
          ),
        );
      if (page.key === "tools") {
        items.push(...searchToolNames(query, t, pageContext));
      }
      if (query.trim())
        for (const { pluginId, item } of pluginSearch) {
          if (item.routeId !== page.routeId) continue;
          const label = resolveLocalized(item.label, i18n.language) ?? item.id;
          const path = resolveLocalized(item.groupPath, i18n.language) ?? [];
          const keywords = resolveLocalized(item.keywords, i18n.language) ?? [];
          const english = [
            resolveLocalized(item.label, "en"),
            ...(resolveLocalized(item.keywords, "en") ?? []),
          ];
          if (
            !matchesSettingsSearch(
              query,
              [
                pageContext,
                label,
                ...path,
                ...keywords,
                ...english,
                resolveLocalized(item.description, i18n.language),
              ].join(" "),
            )
          )
            continue;
          const availability = resolveLocalized(
            item.availability,
            i18n.language,
          );
          items.push({
            id: JSON.stringify([pluginId, item.id]),
            label,
            path: path.join(" → "),
            target: { ...item.target, page: page.key, label },
            disabled: availability?.available === false,
            reason: availability?.reason,
          });
        }
      return [page.key, items];
    }),
  );

  const normalizedQuery = query.trim().toLocaleLowerCase();
  const filterNavigation = normalizedQuery !== "" || !canImport;
  const visibleGroups = filterNavigation
    ? availableGroups
        .map((group) => ({
          ...group,
          pages: group.pages.filter(
            (page) =>
              (page.routeId !== "core.import" || canImport) &&
              (!normalizedQuery ||
                matchesSettingsSearch(
                  normalizedQuery,
                  `${searchablePageLabel(page)} ${t(
                    page.descriptionKey,
                    page.descriptionFallback,
                  )} ${page.fallback}`,
                ) ||
                (matchingItems.get(page.key)?.length ?? 0) > 0),
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

  const openPage = (
    page: SettingsPageDefinition,
    target?: SettingsSearchTarget,
  ) => {
    const destination = target?.page
      ? allPages.find((candidate) => candidate.key === target.page) ?? page
      : page;
    const withQuery = (path: string) => {
      if (!target?.query) return path;
      const [pathname, search = ""] = path.split("?");
      const params = new URLSearchParams(search);
      for (const [key, value] of Object.entries(target.query))
        params.set(key, value);
      return `${pathname}?${params}`;
    };
    if (destination.href) {
      window.open(destination.href, "_blank", "noopener,noreferrer");
      return;
    }
    if (destination.legacyPath) {
      navigate(withQuery(destination.legacyPath), {
        state: { settingsSearchTarget: target, settingsReturnTo: returnTo },
      });
      return;
    }
    navigate(withQuery(`/settings/${destination.key}`), {
      state: { settingsReturnTo: returnTo, settingsSearchTarget: target },
    });
  };
  const openResult = (page: SettingsPageDefinition, item: SearchResult) => {
    const target = { ...item.target, agentId: selectedAgent };
    setSearchTarget(target);
    openPage(page, target);
  };
  const searchHint =
    activeSearchTarget?.hint ??
    (activeSearchTarget?.surface === "cron-job"
      ? t(
          "settingsCenter.searchSelectTask",
          "Choose a task to edit, or create one, to locate this setting.",
        )
      : activeSearchTarget?.surface === "channel"
      ? t(
          "settingsCenter.searchSelectChannel",
          "Choose a channel to locate this setting.",
        )
      : undefined);

  return (
    <div
      className={`${styles.root} ${isDark ? styles.rootDark : ""}`}
      data-theme={isDark ? "dark" : "light"}
    >
      <div className={styles.body}>
        <div className={styles.mobileNavigation}>
          <Button
            type="text"
            icon={<ArrowLeft size={18} />}
            aria-label={t("settingsCenter.backToApp", "Back to app")}
            onClick={() => navigate(returnTo)}
          />
          <Select
            aria-label={t("nav.settings")}
            value={activePage?.key}
            showSearch
            filterOption={false}
            onSearch={setQuery}
            onChange={(value) => {
              const [pageKey, encodedItem] = value.split("::");
              const page = allPages.find((item) => item.key === pageKey);
              if (page) {
                const item = encodedItem
                  ? matchingItems
                      .get(pageKey)
                      ?.find(
                        (item) => item.id === decodeURIComponent(encodedItem),
                      )
                  : undefined;
                if (item) openResult(page, item);
                else {
                  setSearchTarget(null);
                  openPage(page);
                }
              }
              setQuery("");
            }}
            options={visibleGroups.map((group) => ({
              label: t(group.labelKey, group.fallback),
              options: group.pages.flatMap((page) => [
                { value: page.key, label: pageLabel(page) },
                ...(matchingItems.get(page.key) ?? []).map((item) => ({
                  value: `${page.key}::${encodeURIComponent(item.id)}`,
                  label: [
                    searchablePageLabel(page),
                    item.path,
                    item.label,
                    item.reason,
                  ]
                    .filter(Boolean)
                    .join(" · "),
                  disabled: item.disabled,
                })),
              ]),
            }))}
          />
          {activePage?.routeId &&
            SETTINGS_GROUPS[1].pages.some(
              (page) => page.key === activePage.key,
            ) && <SettingsAgentSelector />}
        </div>
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
            aria-label={t("settingsCenter.searchPlaceholder")}
            placeholder={t(
              "settingsCenter.searchPlaceholder",
              "Search settings",
            )}
            onChange={(event) => {
              setQuery(event.target.value);
              setSearchTarget(null);
            }}
          />
          <nav className={styles.navigation} aria-label={t("nav.settings")}>
            <LayoutGroup id="settings-navigation">
              {visibleGroups.map((group) => (
                <section key={group.key} className={styles.navGroup}>
                  <h2>{t(group.labelKey, group.fallback)}</h2>
                  {group.key === "agent-configuration" && (
                    <SettingsAgentSelector />
                  )}
                  {group.pages.map((page) => {
                    const Icon = page.Icon;
                    return (
                      <div key={page.key}>
                        <button
                          type="button"
                          aria-current={
                            activePage?.key === page.key ? "page" : undefined
                          }
                          data-press
                          className={`${styles.navItem} ${
                            activePage?.key === page.key
                              ? styles.navItemActive
                              : ""
                          }`}
                          onClick={() => {
                            setSearchTarget(null);
                            openPage(page);
                          }}
                        >
                          {activePage?.key === page.key && (
                            <motion.span
                              className={styles.navSelection}
                              layoutId="selection"
                              aria-hidden
                              transition={
                                reducedMotion
                                  ? { duration: 0 }
                                  : {
                                      type: "spring",
                                      stiffness: 420,
                                      damping: 40,
                                    }
                              }
                            />
                          )}
                          {page.icon ??
                            (Icon ? (
                              <Icon size={18} strokeWidth={1.75} />
                            ) : null)}
                          <span className={styles.navItemLabel}>
                            {pageLabel(page)}
                          </span>
                        </button>
                        {(matchingItems.get(page.key) ?? []).map((item) => (
                          <button
                            key={item.id}
                            type="button"
                            className={styles.searchResult}
                            disabled={item.disabled}
                            title={item.reason}
                            onClick={() => openResult(page, item)}
                          >
                            <span>{item.label}</span>
                            {item.path && (
                              <small className={styles.searchPath}>
                                {item.path}
                              </small>
                            )}
                            {item.reason && (
                              <small className={styles.searchPath}>
                                {item.reason}
                              </small>
                            )}
                          </button>
                        ))}
                      </div>
                    );
                  })}
                </section>
              ))}
              {visibleGroups.length === 0 && (
                <div className={styles.noResults}>
                  {t("settingsCenter.noResults", "No matching settings")}
                </div>
              )}
            </LayoutGroup>
          </nav>
        </aside>

        <main
          ref={contentRef}
          className={styles.content}
          data-core-settings={
            activePage?.key !== "models" &&
            !activePage?.key.startsWith("extension-")
          }
        >
          <SettingsSearchRequest.Provider value={activeSearchTarget}>
            {searchHint && (
              <Alert
                type="info"
                message={searchHint}
                closable
                onClose={() => setSearchTarget(null)}
              />
            )}
            {ActiveComponent ? (
              <ChunkErrorBoundary resetKey={activePage?.key ?? "settings"}>
                <ChunkRecoverySuspense
                  fallback={
                    <div className={styles.loading}>
                      <Spin tip={t("common.loading")} />
                    </div>
                  }
                >
                  <ActiveComponent />
                </ChunkRecoverySuspense>
              </ChunkErrorBoundary>
            ) : null}
          </SettingsSearchRequest.Provider>
        </main>
      </div>
    </div>
  );
}
