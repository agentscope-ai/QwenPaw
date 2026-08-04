/**
 * Launcher.tsx — Start-menu overlay listing all registered apps in a grid
 * with a search filter. Selecting an app opens its window and closes the
 * launcher. Only apps whose route id resolves in the registry are shown.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Search } from "lucide-react";
import { useOsWindows } from "./osWindowStore";
import type { OsAppDef } from "./osApps";
import { buttonRoleProps } from "./a11y";
import { useOsStyles } from "./useOsStyles";
import { useOsAppLauncher } from "./useOsAppLauncher";

interface LauncherProps {
  /** Apps to show (already filtered to installed + available). */
  apps: OsAppDef[];
}

export default function Launcher({ apps: source }: LauncherProps) {
  const { styles } = useOsStyles();
  const { t } = useTranslation();
  // Actions only (referentially stable) — window updates never re-render
  // the launcher grid.
  const setLauncher = useOsWindows((s) => s.setLauncher);
  const launchApp = useOsAppLauncher();
  const [query, setQuery] = useState("");

  const apps = useMemo(
    () =>
      source.filter((a) => {
        const label = t(a.labelKey, a.fallback).toLowerCase();
        return label.includes(query.toLowerCase());
      }),
    [source, query, t],
  );

  const launch = useCallback(
    async (app: OsAppDef) => {
      if (await launchApp(app.routeId)) {
        setLauncher(false);
      }
    },
    [launchApp, setLauncher],
  );

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setLauncher(false);
      } else if (
        event.key === "Enter" &&
        event.target instanceof HTMLInputElement &&
        !event.isComposing &&
        apps[0]
      ) {
        void launch(apps[0]);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [apps, launch, setLauncher]);

  return (
    <div
      className={styles.launcher}
      role="dialog"
      aria-modal="true"
      aria-label={t("os.launchpad", "Launchpad")}
      onPointerDown={() => setLauncher(false)}
    >
      <div
        className={styles.launcherSurface}
        onPointerDown={(event) => event.stopPropagation()}
      >
        <div className={styles.launcherSearch}>
          <Search size={17} aria-hidden />
          <input
            autoFocus
            aria-label={t("common.search", "Search apps...")}
            placeholder={t("common.search", "Search apps...")}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>
        <div className={styles.launcherGrid}>
          {apps.map((a) => {
            const Icon = a.Icon;
            const activate = () => void launch(a);
            return (
              <div
                key={a.routeId}
                className={styles.launcherItem}
                onClick={activate}
                {...buttonRoleProps(activate, t(a.labelKey, a.fallback))}
              >
                <div
                  className={styles.launcherIcon}
                  style={{ background: a.accent }}
                >
                  <Icon size={27} />
                </div>
                <span>{t(a.labelKey, a.fallback)}</span>
              </div>
            );
          })}
          {apps.length === 0 && (
            <div className={styles.launcherEmpty}>
              {t("common.noData", "No apps")}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
