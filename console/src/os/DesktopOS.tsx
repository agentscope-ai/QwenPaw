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
import { Suspense, useMemo, useEffect, useState, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { App, Dropdown, Spin, type MenuProps } from "antd";
import { Grid2X2, Image as ImageIcon, Trash2 } from "lucide-react";
import { useRoutes } from "../plugins/registry/hooks";
import { uninstallPlugin } from "../api/modules/plugin";
import { ChunkErrorBoundary } from "../components/ChunkErrorBoundary";
import { useIsMobile } from "../hooks/useIsMobile";
import { useAgentStore } from "../stores/agentStore";
import { useSyncCodingMode } from "../stores/useSyncCodingMode";
import { useShallow } from "zustand/react/shallow";
import { useOsWindows } from "./osWindowStore";
import { useOsPlugins } from "./osPluginStore";
import { OS_APPS, STORE_APP, SETTINGS_APP, type OsAppDef } from "./osApps";
import { useOsApps, resolveAppDef } from "./osAppRegistry";
import { useOsStyles, MENUBAR_H } from "./useOsStyles";
import { useOsNotifyPoller } from "./useOsNotifyPoller";
import { isAgentAvailableInChat } from "../utils/agentVisibility";
import { purgeAppState, removePluginAppState } from "./osCleanup";
import WindowFrame from "./WindowFrame";
import WindowRouter from "./WindowRouter";
import { baseFromRoutePath } from "./osRouteMap";
import MenuBar from "./MenuBar";
import Dock from "./Dock";
import SpacesPanel from "./SpacesPanel";
import { useEdgeReveal } from "./useEdgeReveal";
import { useOsIcons, defaultIconPos } from "./osIconStore";
import { useOsDock } from "./osDockStore";
import { useIconDrag } from "./useIconDrag";
import { arrangeApps } from "./iconArrangement";
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
import { buttonRoleProps } from "./a11y";
import { useOsAppLauncher } from "./useOsAppLauncher";
import {
  getPawAppIdFromPath,
  setActivePawAppId,
} from "../plugins/pawapp-sdk/context";
import { getOsRootHref } from "../utils/navigationMode";
import "./osWindowBody.css";

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
  const { styles, cx } = useOsStyles();
  const { t, i18n } = useTranslation();
  const { message } = App.useApp();
  const launchApp = useOsAppLauncher();
  const isMobile = useIsMobile();
  const routes = useRoutes();
  // Narrow subscription: only the fields the desktop shell renders from.
  // Actions are referentially stable; geometry churn stays inside frames.
  const {
    windows,
    order,
    activeId,
    launcherOpen,
    setLauncher,
    spaceId,
    switchSpace,
    missionControlOpen,
    setMissionControl,
  } = useOsWindows(
    useShallow((s) => ({
      windows: s.windows,
      order: s.order,
      activeId: s.activeId,
      launcherOpen: s.launcherOpen,
      setLauncher: s.setLauncher,
      spaceId: s.spaceId,
      switchSpace: s.switchSpace,
      missionControlOpen: s.missionControlOpen,
      setMissionControl: s.setMissionControl,
    })),
  );
  const { uninstall } = useOsPlugins();
  const { selectedAgent, refreshAgents } = useAgentStore();
  useSyncCodingMode();
  // Single app registry: desktop icons, window chrome and the launcher all
  // read from the same source (catalog + system + dynamic plugin apps).
  const { apps: visibleApps, appById } = useOsApps();
  const { wallpaperId } = useOsWallpaper();

  // Desktop right-click menu and wallpaper picker overlay.
  const [wpOpen, setWpOpen] = useState(false);
  const [ctxMenu, setCtxMenu] = useState<{ x: number; y: number } | null>(null);
  const [selectedIconId, setSelectedIconId] = useState<string | null>(null);

  // Power-on splash: overlays the desktop, fades out, then unmounts. Played
  // once per browser session (survives OS <-> classic layout switches).
  // Stable identity so BootScreen's timer effect doesn't restart on every
  // parent re-render.
  const [booting, setBooting] = useState(shouldPlayBoot);
  const handleBootDone = useCallback(() => {
    setBooting(false);
    try {
      window.sessionStorage.setItem(BOOT_FLAG_KEY, "1");
    } catch {
      /* storage unavailable — splash will just replay next mount */
    }
  }, []);

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
        const ids = agentState.agents
          .filter(isAgentAvailableInChat)
          .map((a) => a.id);
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
  const routeById = useMemo(() => {
    const map = new Map<string, (typeof routes)[number]>();
    for (const route of routes) map.set(route.id, route);
    return map;
  }, [routes]);

  // The desktop has one browser entry point: /os. Window navigation stays in
  // each app's MemoryRouter and never becomes a browser deep link.
  useEffect(() => {
    const activeRoute = activeId ? routeById.get(activeId) : undefined;
    const pawAppId =
      activeRoute?.source !== "core" && activeRoute?.path.startsWith("/apps/")
        ? getPawAppIdFromPath(activeRoute.path)
        : "";
    setActivePawAppId(pawAppId || null);
    const browserPath = getOsRootHref(window.location.pathname);
    if (
      `${window.location.pathname}${window.location.search}` !== browserPath
    ) {
      window.history.replaceState(
        { ...window.history.state, osApp: activeId },
        "",
        browserPath,
      );
    }
  }, [activeId, routeById]);

  const openWindows = order
    .map((id) => windows[id])
    .filter((w): w is NonNullable<typeof w> => Boolean(w));

  // Desktop keeps the menu bar visible above maximized windows. Mobile uses
  // full-screen windows and keeps the menu bar hidden.
  const { topHot } = useEdgeReveal();

  // Persisted desktop icon positions + transient drag handlers. While a
  // drag is in flight the position lives in the DOM only (rAF-coalesced);
  // the persisted store is written once when the gesture ends.
  const {
    positions: iconPositions,
    layout: iconLayout,
    setPosition,
    setLayout: setIconLayout,
    arrange: arrangeIcons,
  } = useOsIcons();
  const pinDock = useOsDock((s) => s.pin);
  const iconDragHandlers = useIconDrag(
    setPosition,
    MENUBAR_H,
    (id, event, moved) => {
      if (!moved) return false;
      const overDock = document
        .elementFromPoint?.(event.clientX, event.clientY)
        ?.closest("[data-os-dock-dropzone]");
      if (!overDock) return false;
      pinDock(id);
      return true;
    },
  );

  const displayedApps = useMemo(
    () =>
      iconLayout === "free"
        ? visibleApps
        : arrangeApps(visibleApps, iconLayout, t, i18n.resolvedLanguage),
    [i18n.resolvedLanguage, iconLayout, t, visibleApps],
  );
  const visibleAppIds = useMemo(
    () => displayedApps.map((app) => app.routeId),
    [displayedApps],
  );

  // Viewport changed (browser zoom, resize, DPI/monitor switch): pull
  // persisted windows into view and reflow desktop icons so newly available
  // vertical space is used immediately. Mobile uses its own scrollable grid
  // and must not rewrite the saved desktop layout.
  useEffect(() => {
    const onResize = () => {
      useOsWindows.getState().clampToViewport();
      if (window.innerWidth > 768) {
        useOsIcons
          .getState()
          .reflowToViewport(visibleAppIds, window.innerHeight);
      }
    };
    onResize();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [visibleAppIds]);

  const closeDesktopMenu = () => setCtxMenu(null);
  const handleArrangeIcons = () => {
    arrangeIcons(
      displayedApps.map((app) => app.routeId),
      window.innerHeight,
    );
    setIconLayout("free");
    closeDesktopMenu();
  };
  const desktopMenuItems: MenuProps["items"] = [
    {
      key: "arrange",
      icon: <Grid2X2 size={15} />,
      label: t("os.arrangeDesktop", "Clean up"),
      onClick: handleArrangeIcons,
    },
    { type: "divider" },
    {
      key: "wallpaper",
      icon: <ImageIcon size={15} />,
      label: t("os.changeWallpaper", "Change wallpaper"),
      onClick: () => {
        setWpOpen(true);
        closeDesktopMenu();
      },
    },
  ];

  // Plugin apps are removed from the backend and live frontend state. Built-in
  // catalog apps are toggled locally; system apps are not uninstallable.
  const handleUninstall = async (a: OsAppDef) => {
    const name = t(a.labelKey, a.fallback);
    if (a.source) {
      const source = a.source;
      try {
        await uninstallPlugin(source);
        removePluginAppState(source);
        message.success(
          t("os.uninstalledApp", { name, defaultValue: "Uninstalled" }),
        );
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
    purgeAppState([a.routeId]);
    message.info(t("os.uninstalledApp", { name, defaultValue: "Uninstalled" }));
  };

  // Renders a single desktop icon (double-click opens; right-click uninstalls
  // when applicable). Positioning is handled by the caller.
  const renderIcon = (a: OsAppDef) => {
    const Icon = a.Icon;
    const uninstallable =
      Boolean(a.source) || OS_APPS.some((o) => o.routeId === a.routeId);
    const activate = () => void launchApp(a.routeId);
    const iconEl = (
      <div
        className={cx(
          styles.desktopIcon,
          selectedIconId === a.routeId && styles.desktopIconSelected,
        )}
        onDoubleClick={activate}
        onClick={(event) => {
          event.stopPropagation();
          setSelectedIconId(a.routeId);
          if (isMobile) activate();
        }}
        onFocus={() => setSelectedIconId(a.routeId)}
        title={t(a.labelKey, a.fallback)}
        {...buttonRoleProps(activate, t(a.labelKey, a.fallback))}
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
        setSelectedIconId(null);
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
          {displayedApps.map((a) => (
            <div key={a.routeId}>{renderIcon(a)}</div>
          ))}
        </div>
      ) : (
        <div className={styles.iconsLayer}>
          {displayedApps.map((a, i) => {
            const pos =
              iconLayout === "free"
                ? iconPositions[a.routeId] ??
                  defaultIconPos(i, window.innerHeight)
                : defaultIconPos(i, window.innerHeight);
            return (
              <div
                key={a.routeId}
                className={styles.iconAbsolute}
                style={{ left: pos.x, top: pos.y }}
                {...(iconLayout === "free"
                  ? iconDragHandlers(a.routeId, pos)
                  : {})}
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
        <img src="/qwenpaw.png" alt="" />
        <div className={styles.emptyBrandName}>QwenPaw OS</div>
      </div>

      {/* Windows layer */}
      <div className={styles.windowsLayer}>
        {openWindows.map((win) => {
          const def =
            appById.get(win.id) ?? resolveAppDef(win.id) ?? OS_APPS[0];
          const isStore = win.id === STORE_APP.routeId;
          const isSettings = win.id === SETTINGS_APP.routeId;
          const Component = componentById.get(win.id);
          if (!isStore && !isSettings && !Component) {
            return null;
          }
          return (
            <WindowFrame
              key={win.id}
              win={win}
              title={t(def.labelKey, def.fallback)}
              Icon={def.Icon}
              accent={def.accent}
              isMobile={isMobile}
              themedSurface={!isStore && !isSettings}
              minW={def.minW}
              minH={def.minH}
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
                      base={baseFromRoutePath(routeById.get(win.id)?.path)}
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
      <MenuBar hidden={isMobile} />
      <Dock />

      {ctxMenu && (
        <Dropdown
          open
          trigger={[]}
          placement="bottomLeft"
          overlayClassName={styles.desktopContextMenu}
          menu={{ items: desktopMenuItems }}
          popupRender={(menu) => (
            <div
              onPointerDown={(event) => event.stopPropagation()}
              onContextMenu={(event) => event.stopPropagation()}
            >
              {menu}
            </div>
          )}
          onOpenChange={(open) => {
            if (!open) closeDesktopMenu();
          }}
        >
          <span
            className={styles.desktopMenuAnchor}
            style={{ left: ctxMenu.x, top: ctxMenu.y }}
            onPointerDown={(event) => event.stopPropagation()}
          />
        </Dropdown>
      )}

      {wpOpen && <WallpaperPicker onClose={() => setWpOpen(false)} />}

      {booting && <BootScreen onDone={handleBootDone} />}
    </div>
  );
}
