/**
 * Launcher.tsx — Start-menu overlay listing all registered apps in a grid
 * with a search filter. Selecting an app opens its window and closes the
 * launcher. Only apps whose route id resolves in the registry are shown.
 */
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Search } from "lucide-react";
import { useOsWindows } from "./osWindowStore";
import type { OsAppDef } from "./osApps";
import { buttonRoleProps } from "./a11y";
import { useOsStyles, ACCENT } from "./useOsStyles";

interface LauncherProps {
  /** Apps to show (already filtered to installed + available). */
  apps: OsAppDef[];
}

export default function Launcher({ apps: source }: LauncherProps) {
  const { styles } = useOsStyles();
  const { t } = useTranslation();
  const { open, setLauncher } = useOsWindows();
  const [query, setQuery] = useState("");

  const apps = useMemo(
    () =>
      source.filter((a) => {
        const label = t(a.labelKey, a.fallback).toLowerCase();
        return label.includes(query.toLowerCase());
      }),
    [source, query, t],
  );

  return (
    <div className={styles.launcher} onPointerDown={(e) => e.stopPropagation()}>
      <div className={styles.launcherSearch}>
        <Search size={16} color="#94a3b8" />
        <input
          autoFocus
          placeholder={t("common.search", "Search apps...")}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>
      <div className={styles.launcherGrid}>
        {apps.map((a) => {
          const Icon = a.Icon;
          const launch = () => {
            open(a.routeId, { w: a.defaultW, h: a.defaultH });
            setLauncher(false);
          };
          return (
            <div
              key={a.routeId}
              className={styles.launcherItem}
              onClick={launch}
              {...buttonRoleProps(launch, t(a.labelKey, a.fallback))}
            >
              <div
                style={{
                  width: 44,
                  height: 44,
                  borderRadius: 12,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  background: `${a.accent}22`,
                  color: a.accent,
                }}
              >
                <Icon size={22} />
              </div>
              <span>{t(a.labelKey, a.fallback)}</span>
            </div>
          );
        })}
        {apps.length === 0 && (
          <div style={{ gridColumn: "1 / -1", color: ACCENT, fontSize: 13 }}>
            {t("common.noData", "No apps")}
          </div>
        )}
      </div>
    </div>
  );
}
