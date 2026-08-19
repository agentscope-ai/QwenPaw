/**
 * SettingsApp.tsx — macOS "System Settings"-style aggregate window.
 *
 * A left list of every settings route + a right pane that renders the
 * selected route's existing component (via useRoutes). Page components are
 * reused verbatim — no changes to the settings pages themselves. Items whose
 * route is not currently registered are hidden automatically.
 */
import { Suspense, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Spin } from "antd";
import {
  Bot,
  Cpu,
  Sparkles,
  Globe,
  ShieldCheck,
  BarChart3,
  Archive,
  Mic,
  Bug,
  Package,
  SlidersHorizontal,
  type LucideIcon,
} from "lucide-react";
import { useRoutes } from "../plugins/registry/hooks";
import { ChunkErrorBoundary } from "../components/ChunkErrorBoundary";
import { useOsRoute } from "./osRouteStore";
import { SETTINGS_APP_ID, baseFromRoutePath } from "./osRouteMap";
import WindowRouter from "./WindowRouter";
import { useOsStyles } from "./useOsStyles";

interface SettingsItem {
  routeId: string;
  labelKey: string;
  fallback: string;
  Icon: LucideIcon;
}

/** Mirrors the core.settings-group entries in builtinMenu. */
const SETTINGS_ITEMS: SettingsItem[] = [
  {
    routeId: "core.agents",
    labelKey: "nav.agents",
    fallback: "Agents",
    Icon: Bot,
  },
  {
    routeId: "core.models",
    labelKey: "nav.models",
    fallback: "Models",
    Icon: Cpu,
  },
  {
    routeId: "core.skill-pool",
    labelKey: "nav.skillPool",
    fallback: "Skill Pool",
    Icon: Sparkles,
  },
  {
    routeId: "core.environments",
    labelKey: "nav.environments",
    fallback: "Environments",
    Icon: Globe,
  },
  {
    routeId: "core.security",
    labelKey: "nav.security",
    fallback: "Security",
    Icon: ShieldCheck,
  },
  {
    routeId: "core.token-usage",
    labelKey: "nav.tokenUsage",
    fallback: "Token Usage",
    Icon: BarChart3,
  },
  {
    routeId: "core.backups",
    labelKey: "nav.backups",
    fallback: "Backups",
    Icon: Archive,
  },
  {
    routeId: "core.voice-transcription",
    labelKey: "nav.voiceTranscription",
    fallback: "Voice",
    Icon: Mic,
  },
  {
    routeId: "core.debug",
    labelKey: "nav.debug",
    fallback: "Debug",
    Icon: Bug,
  },
  {
    routeId: "core.plugin-manager",
    labelKey: "nav.pluginManager",
    fallback: "Plugin Manager",
    Icon: Package,
  },
];

export default function SettingsApp() {
  const { styles, cx } = useOsStyles();
  const { t } = useTranslation();
  const routes = useRoutes();

  const componentById = useMemo(() => {
    const map = new Map<string, React.ComponentType>();
    for (const r of routes) map.set(r.id, r.Component);
    return map;
  }, [routes]);

  // Route id -> registry path so each pane can seed its own router base.
  const routePathById = useMemo(() => {
    const map = new Map<string, string>();
    for (const r of routes) map.set(r.id, r.path);
    return map;
  }, [routes]);

  const items = useMemo(
    () => SETTINGS_ITEMS.filter((i) => componentById.has(i.routeId)),
    [componentById],
  );

  const [active, setActive] = useState<string>("");
  const current = active || items[0]?.routeId || "";
  const Active = componentById.get(current);

  // Deep-link IN: a cross-app navigation to a settings route (e.g. Chat ->
  // "/models") posts the target pane's route id here; select it when present.
  const target = useOsRoute((s) => s.targets[SETTINGS_APP_ID]);
  useEffect(() => {
    if (target && componentById.has(target.path)) {
      setActive(target.path);
    }
  }, [target, componentById]);

  return (
    <div className={styles.settingsRoot}>
      <div className={styles.settingsSidebar}>
        {items.map((i) => {
          const Icon = i.Icon;
          return (
            <div
              key={i.routeId}
              className={cx(
                styles.settingsNavItem,
                current === i.routeId && styles.settingsNavActive,
              )}
              onClick={() => setActive(i.routeId)}
            >
              <Icon size={16} />
              <span>{t(i.labelKey, i.fallback)}</span>
            </div>
          );
        })}
      </div>

      <div className={styles.settingsPane}>
        {Active ? (
          <ChunkErrorBoundary resetKey={current}>
            <Suspense
              fallback={
                <div className={styles.loading}>
                  <Spin tip={t("common.loading")} />
                </div>
              }
            >
              <WindowRouter
                key={current}
                routeId={current}
                base={baseFromRoutePath(routePathById.get(current))}
                element={<Active />}
              />
            </Suspense>
          </ChunkErrorBoundary>
        ) : (
          <div className={styles.ncEmpty}>
            <SlidersHorizontal size={30} strokeWidth={1.4} />
            <div>{t("os.noSettings", "No settings available")}</div>
          </div>
        )}
      </div>
    </div>
  );
}
