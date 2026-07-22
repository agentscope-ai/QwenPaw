/**
 * DesktopOS.tsx — Plan B PoC entry point: a full-screen desktop shell that
 * reuses the existing routeRegistry components inside draggable windows.
 *
 * Zero changes to page components: each window renders the same Component the
 * router would mount, wrapped in Suspense + ChunkErrorBoundary. Windows are
 * one-per-app (route id) so global page stores don't clash across instances.
 *
 * Reachable at /os (registered in App.tsx) — isolated from MainLayout so the
 * classic sidebar layout is untouched.
 */
import { Suspense, useMemo, useEffect, useState, useRef } from "react";
import { useTranslation } from "react-i18next";
import { App, Dropdown, Spin } from "antd";
import { Command, Trash2, Image as ImageIcon } from "lucide-react";
import { useRoutes } from "../plugins/registry/hooks";
import { uninstallPlugin } from "../api/modules/plugin";
import { ChunkErrorBoundary } from "../components/ChunkErrorBoundary";
import { useIsMobile } from "../hooks/useIsMobile";
import { useAgentStore } from "../stores/agentStore";
import { useOsWindows } from "./osWindowStore";
import { useOsPlugins } from "./osPluginStore";
import {
  OS_APPS,
  findAppDef,
  STORE_APP,
  SETTINGS_APP,
  type OsAppDef,
} from "./osApps";
import { useOsStyles, MENUBAR_H } from "./useOsStyles";
import { usePluginApps } from "./usePluginApps";
import { useOsNotifyPoller } from "./useOsNotifyPoller";
import WindowFrame from "./WindowFrame";
import WindowRouter from "./WindowRouter";
import { baseFromRoutePath } from "./osRouteMap";
import MenuBar from "./MenuBar";
import Dock from "./Dock";
import SpacesPanel from "./SpacesPanel";
import { useEdgeReveal } from "./useEdgeReveal";
import { useOsIcons, defaultIconPos } from "./osIconStore";
import Launcher from "./Launcher";
import AppStore from "./AppStore";
import SettingsApp from "./SettingsApp";
import MissionControl from "./MissionControl";
import NotificationCenter from "./NotificationCenter";
import BootScreen from "./BootScreen";
import ConsolePollService from "../components/ConsolePollService";
import WallpaperPicker from "./WallpaperPicker";
import { useOsWallpaper } from "./osWallpaperStore";
import { wallpaperBackground } from "./wallpapers";

/** Session flag so the boot splash plays once per browser session. */
const BOOT_FLAG_KEY = "qwenpaw.os.booted";

function shouldPlayBoot(): boolean {
  try {
    return window.sessionStorage.getItem(BOOT_FLAG_KEY) !== "1";
  } catch {
    return true;
  }
}

export default function DesktopOS() {
  const { styles } = useOsStyles();
  const { t } = useTranslation();
  const { message } = App.useApp();
  const isMobile = useIsMobile();
  const routes = useRoutes();
  const {
    windows,
    order,
    open,
    launcherOpen,
    setLauncher,
    spaceId,
    switchSpace,
    missionControlOpen,
    setMissionControl,
  } = useOsWindows();
  const { installed, uninstall } = useOsPlugins();
  const { selectedAgent, refreshAgents } = useAgentStore();
  const pluginApps = usePluginApps();
  const { wallpaperId } = useOsWallpaper();

  // Desktop right-click menu and wallpaper picker overlay.
  const [wpOpen, setWpOpen] = useState(false);
  const [ctxMenu, setCtxMenu] = useState<{ x: number; y: number } | null>(null);

  // Power-on splash: overlays the desktop, fades out, then unmounts. Played
  // once per browser session (survives OS <-> classic layout switches).
  const [booting, setBooting] = useState(shouldPlayBoot);
  const handleBootDone = () => {
    setBooting(false);
    try {
      window.sessionStorage.setItem(BOOT_FLAG_KEY, "1");
    } catch {
      /* storage unavailable — splash will just replay next mount */
    }
  };

  // Poll approvals + unread inbox events → macOS-style notifications.
  useOsNotifyPoller();

  // Load agents once so Mission Control can list them as spaces.
  useEffect(() => {
    refreshAgents().catch(() => {
      /* backend offline in PoC — current agent still shows as a space */
    });
  }, [refreshAgents]);

  // Keep the active space aligned with the selected agent (full-screen-app
  // switch semantics). Runs when the agent changes outside Mission Control.
  useEffect(() => {
    if (selectedAgent && selectedAgent !== spaceId) {
      switchSpace(selectedAgent);
    }
  }, [selectedAgent, spaceId, switchSpace]);

  // F3 toggles Mission Control, Escape closes it, Ctrl+←/→ switch Spaces —
  // mirrors macOS full-screen-app navigation.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "F3") {
        e.preventDefault();
        setMissionControl(!useOsWindows.getState().missionControlOpen);
      } else if (e.key === "Escape") {
        setMissionControl(false);
      } else if (
        e.ctrlKey &&
        (e.key === "ArrowLeft" || e.key === "ArrowRight")
      ) {
        e.preventDefault();
        const agentState = useAgentStore.getState();
        const ids = agentState.agents.map((a) => a.id);
        const current = agentState.selectedAgent;
        if (!ids.includes(current)) ids.unshift(current);
        if (ids.length < 2) return;
        const idx = ids.indexOf(current);
        const nextIdx =
          e.key === "ArrowLeft"
            ? (idx - 1 + ids.length) % ids.length
            : (idx + 1) % ids.length;
        const nextId = ids[nextIdx];
        agentState.setSelectedAgent(nextId);
        useOsWindows.getState().switchSpace(nextId);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [setMissionControl]);

  // Map route id -> Component for O(1) lookup when rendering window content.
  const componentById = useMemo(() => {
    const map = new Map<string, React.ComponentType>();
    for (const r of routes) map.set(r.id, r.Component);
    return map;
  }, [routes]);

  // Map route id -> registry path so each window can seed its own router base.
  const routePathById = useMemo(() => {
    const map = new Map<string, string>();
    for (const r of routes) map.set(r.id, r.path);
    return map;
  }, [routes]);

  const availableIds = useMemo(
    () => new Set(routes.map((r) => r.id)),
    [routes],
  );

  // Visible apps = App Store (system, always present) + installed catalog
  // apps whose route actually resolves + installed plugin apps (PawApps,
  // derived live from the registry) + System Settings. Driven by
  // osPluginStore + the plugin registry, so installs update the desktop.
  const visibleApps = useMemo(() => {
    const installedSet = new Set(installed);
    const catalog = OS_APPS.filter(
      (a) => availableIds.has(a.routeId) && installedSet.has(a.routeId),
    );
    return [STORE_APP, ...catalog, ...pluginApps, SETTINGS_APP];
  }, [availableIds, installed, pluginApps]);

  // Resolve a window's app def (title/icon/accent) across every source:
  // system apps, catalog apps and dynamic plugin apps.
  const appDefById = useMemo(() => {
    const map = new Map<string, OsAppDef>();
    for (const a of visibleApps) map.set(a.routeId, a);
    return map;
  }, [visibleApps]);

  const openWindows = order
    .map((id) => windows[id])
    .filter((w): w is NonNullable<typeof w> => Boolean(w));

  // Auto-hide chrome: menu bar hides only while a window is maximized; the
  // Spaces panel reveals on top-edge hover. The Dock stays visible by default.
  const anyMaximized = isMobile || openWindows.some((w) => w.maximized);
  const { topHot } = useEdgeReveal();

  // Persisted desktop icon positions + a transient drag handle.
  const { positions: iconPositions, setPosition } = useOsIcons();
  const iconDrag = useRef<{
    id: string;
    dx: number;
    dy: number;
    moved: boolean;
  } | null>(null);

  // Uninstall an app. Plugin apps (PawApps, carrying `source`) are removed on
  // the backend (then reload to refresh the registry); built-in catalog apps
  // are toggled off locally via osPluginStore. System apps aren't uninstallable.
  const handleUninstall = async (a: OsAppDef) => {
    const name = t(a.labelKey, a.fallback);
    if (a.source) {
      try {
        await uninstallPlugin(a.source);
        message.success(
          t("os.uninstalledApp", { name, defaultValue: "Uninstalled" }),
        );
        setTimeout(() => window.location.reload(), 600);
      } catch (err) {
        message.error(
          err instanceof Error
            ? err.message
            : t("os.uninstallFailed", "Uninstall failed"),
        );
      }
      return;
    }
    uninstall(a.routeId);
    message.info(t("os.uninstalledApp", { name, defaultValue: "Uninstalled" }));
  };

  // Renders a single desktop icon (double-click opens; right-click uninstalls
  // when applicable). Positioning is handled by the caller.
  const renderIcon = (a: OsAppDef) => {
    const Icon = a.Icon;
    const uninstallable =
      Boolean(a.source) || OS_APPS.some((o) => o.routeId === a.routeId);
    const iconEl = (
      <div
        className={styles.desktopIcon}
        onDoubleClick={() => open(a.routeId, { w: a.defaultW, h: a.defaultH })}
        onClick={() =>
          isMobile && open(a.routeId, { w: a.defaultW, h: a.defaultH })
        }
      >
        <div className={styles.iconTile} style={{ background: a.accent }}>
          <Icon size={26} />
        </div>
        <span>{t(a.labelKey, a.fallback)}</span>
      </div>
    );
    if (!uninstallable) return iconEl;
    return (
      <Dropdown
        trigger={["contextMenu"]}
        menu={{
          items: [
            {
              key: "uninstall",
              danger: true,
              icon: <Trash2 size={14} />,
              label: t("os.uninstall", "Uninstall"),
              onClick: () => void handleUninstall(a),
            },
          ],
        }}
      >
        {iconEl}
      </Dropdown>
    );
  };

  return (
    <div
      className={styles.desktop}
      style={{ background: wallpaperBackground(wallpaperId) }}
      onPointerDown={() => {
        if (launcherOpen) setLauncher(false);
        if (ctxMenu) setCtxMenu(null);
      }}
      onContextMenu={(e) => {
        // Only the empty desktop background opens the wallpaper menu; icons,
        // Dock and menu bar keep their own context behaviour.
        if (e.target !== e.currentTarget) return;
        e.preventDefault();
        setLauncher(false);
        setCtxMenu({ x: e.clientX, y: e.clientY });
      }}
    >
      {/* Desktop icons. Mobile keeps the fixed grid; desktop uses persisted,
          free-drag positions. */}
      {isMobile ? (
        <div className={styles.iconsGrid}>
          {visibleApps.map((a) => (
            <div key={a.routeId}>{renderIcon(a)}</div>
          ))}
        </div>
      ) : (
        <div className={styles.iconsLayer}>
          {visibleApps.map((a, i) => {
            const pos =
              iconPositions[a.routeId] ?? defaultIconPos(i, window.innerHeight);
            return (
              <div
                key={a.routeId}
                className={styles.iconAbsolute}
                style={{ left: pos.x, top: pos.y }}
                onPointerDown={(e) => {
                  if ((e.target as HTMLElement).closest("button")) return;
                  iconDrag.current = {
                    id: a.routeId,
                    dx: e.clientX - pos.x,
                    dy: e.clientY - pos.y,
                    moved: false,
                  };
                  (e.currentTarget as HTMLElement).setPointerCapture(
                    e.pointerId,
                  );
                }}
                onPointerMove={(e) => {
                  const d = iconDrag.current;
                  if (!d || d.id !== a.routeId) return;
                  const nx = Math.max(0, e.clientX - d.dx);
                  const ny = Math.max(MENUBAR_H, e.clientY - d.dy);
                  if (
                    Math.abs(e.clientX - (d.dx + pos.x)) > 3 ||
                    Math.abs(e.clientY - (d.dy + pos.y)) > 3
                  ) {
                    d.moved = true;
                  }
                  setPosition(a.routeId, nx, ny);
                }}
                onPointerUp={(e) => {
                  iconDrag.current = null;
                  try {
                    (e.currentTarget as HTMLElement).releasePointerCapture(
                      e.pointerId,
                    );
                  } catch {
                    /* noop */
                  }
                }}
              >
                {renderIcon(a)}
              </div>
            );
          })}
        </div>
      )}

      {/* Persistent background watermark — QwenPaw OS brand mark. Sits at the
          lowest layer and never intercepts pointer events, so it reads as a
          backdrop behind icons and app windows rather than a card. */}
      <div className={styles.emptyHint}>
        <Command size={72} strokeWidth={1.4} />
        <div className={styles.emptyBrandName}>QwenPaw OS</div>
      </div>

      {/* Windows layer */}
      <div className={styles.windowsLayer}>
        {openWindows.map((win) => {
          const def =
            appDefById.get(win.id) ?? findAppDef(win.id) ?? OS_APPS[0];
          const isStore = win.id === STORE_APP.routeId;
          const isSettings = win.id === SETTINGS_APP.routeId;
          const Component = componentById.get(win.id);
          if (!isStore && !isSettings && !Component) return null;
          return (
            <WindowFrame
              key={win.id}
              win={win}
              title={t(def.labelKey, def.fallback)}
              Icon={def.Icon}
              accent={def.accent}
              isMobile={isMobile}
            >
              <ChunkErrorBoundary resetKey={win.id}>
                <Suspense
                  fallback={
                    <div className={styles.loading}>
                      <Spin tip={t("common.loading")} />
                    </div>
                  }
                >
                  {isStore ? (
                    <AppStore />
                  ) : isSettings ? (
                    <SettingsApp />
                  ) : Component ? (
                    <WindowRouter
                      routeId={win.id}
                      base={baseFromRoutePath(routePathById.get(win.id))}
                      element={<Component />}
                    />
                  ) : null}
                </Suspense>
              </ChunkErrorBoundary>
            </WindowFrame>
          );
        })}
      </div>

      {launcherOpen && <Launcher apps={visibleApps} />}

      {missionControlOpen && <MissionControl />}

      <NotificationCenter />

      {/* Global approval/message feed (same as MainLayout). Populates the
          shared ApprovalContext so the Inbox + Chat windows show pending
          tool approvals inside the OS, matching the browser layout. */}
      <ConsolePollService />

      <SpacesPanel visible={topHot} />
      <MenuBar hidden={anyMaximized} />
      <Dock />

      {ctxMenu && (
        <div
          className={styles.desktopMenu}
          style={{ left: ctxMenu.x, top: ctxMenu.y }}
          onPointerDown={(e) => e.stopPropagation()}
        >
          <div
            className={styles.desktopMenuItem}
            onClick={() => {
              setWpOpen(true);
              setCtxMenu(null);
            }}
          >
            <ImageIcon size={15} />
            {t("os.changeWallpaper", "Change wallpaper")}
          </div>
        </div>
      )}

      {wpOpen && <WallpaperPicker onClose={() => setWpOpen(false)} />}

      {booting && <BootScreen onDone={handleBootDone} />}
    </div>
  );
}
