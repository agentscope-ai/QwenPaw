import {
  Layout,
  Menu,
  Button,
  Modal,
  Input,
  Form,
  Tooltip,
  Badge,
  Popover,
  Tour,
} from "antd";
import type { TourProps } from "antd";
import { useState, useEffect, useMemo, useCallback, useRef } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { ChevronDown, MessageSquareText } from "lucide-react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useAppMessage } from "../hooks/useAppMessage";
import AgentSelector from "../components/AgentSelector";
import {
  SparkChatTabFill,
  SparkExitFullscreenLine,
  SparkSearchUserLine,
  SparkMenuExpandLine,
  SparkMenuFoldLine,
  SparkEmailLine,
  SparkSettingLine,
} from "@agentscope-ai/icons";
import SidebarSessionList from "./SidebarSessionList";
import SidebarSettingsPanel from "./SidebarSettingsPanel";
import { clearAuthToken } from "../api/config";
import { authApi } from "../api/modules/auth";
import api from "../api";
import {
  syncSessionsGlobal,
  type ExtendedSession,
} from "../stores/sessionListStore";
import { useSidebarModeStore } from "../stores/sidebarModeStore";
import { buildChatPath, getSessionIdFromPath } from "../utils/sessionRoute";
import { useAgentStore } from "../stores/agentStore";
import sessionApi from "../pages/Chat/sessionApi";
import { useInboxWobble } from "../hooks/useInboxWobble";
import styles from "./index.module.less";
import { useTheme } from "../contexts/ThemeContext";
import { useMenuItems, useRoutes } from "../plugins/registry/hooks";
import { Slot } from "../plugins/registry/Slot";
import {
  deriveOpenKeys,
  findMenuItem,
  flattenMenu,
  renderIcon,
  routeIdToPath,
  toAntdItems,
} from "./registry/adapter";
import type { FlatMenuEntry } from "./registry/adapter";
import { filterMenuForAgentCapabilities } from "./registry/capabilities";
import type { MenuItem } from "../plugins/registry/types";
import type { ReactNode } from "react";
import {
  dismissDesktopModeHint,
  shouldShowDesktopModeHint,
} from "../utils/desktopModeHint";

// ── Layout ────────────────────────────────────────────────────────────────

const { Sider } = Layout;
const MOBILE_SIDEBAR_QUERY = "(max-width: 768px)";

function isMobileSidebarViewport() {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia(MOBILE_SIDEBAR_QUERY).matches
  );
}
const INBOX_BADGE_POLLING_MS = 6000;

// ── Simple mode whitelist ─────────────────────────────────────────────────

/** Menu item IDs that remain visible in simple sidebar mode (no groups). */
const SIMPLE_MODE_WHITELIST = new Set([
  "core.files",
  "core.inbox",
  "core.marketplace",
  "core.cron-jobs",
  "core.agent-config",
  "core.models",
]);

/**
 * Flatten a MenuItem tree into a leaf-only list for simple sidebar mode.
 * Groups are eliminated entirely — only whitelisted children survive
 * as top-level items.
 */
function flattenMenuForSimpleMode(items: MenuItem[]): MenuItem[] {
  const result: MenuItem[] = [];
  for (const rawItem of items) {
    const item = rawItem as MenuItem & { __children?: MenuItem[] };
    if (item.__children && item.__children.length > 0) {
      for (const child of item.__children) {
        if (SIMPLE_MODE_WHITELIST.has(child.id)) {
          result.push(child);
        }
      }
    } else if (SIMPLE_MODE_WHITELIST.has(item.id)) {
      result.push(item);
    }
  }
  return result;
}

// ── Types ─────────────────────────────────────────────────────────────────

interface SidebarProps {
  /** Route id of the currently active page (e.g. "core.workspace"). */
  selectedKey: string;
}

// ── Sidebar ───────────────────────────────────────────────────────────────

export default function Sidebar({ selectedKey }: SidebarProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const { isDark } = useTheme();
  const currentSessionId = getSessionIdFromPath(location.pathname);
  const chatPath = buildChatPath(currentSessionId);
  const [authEnabled, setAuthEnabled] = useState(false);
  const [accountModalOpen, setAccountModalOpen] = useState(false);
  const [accountLoading, setAccountLoading] = useState(false);
  const [accountForm] = Form.useForm();
  // Start collapsed on mobile so the first paint does not overlay/obscure
  // the main content on narrow viewports.
  const [collapsed, setCollapsed] = useState(isMobileSidebarViewport);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const settingsButtonRef = useRef<HTMLButtonElement>(null);
  const [desktopModeHintOpen, setDesktopModeHintOpen] = useState(false);
  const [isMobile, setIsMobile] = useState(isMobileSidebarViewport);
  const [simpleAgentFunctionsExpanded, setSimpleAgentFunctionsExpanded] =
    useState(false);
  const prefersReducedMotion = useReducedMotion();
  const [hasUnreadMessages, setHasUnreadMessages] = useState(false);
  const [hasPendingApprovals, setHasPendingApprovals] = useState(false);
  const [shakeInbox, setShakeInbox] = useState(false);
  const [wobbleEnabled] = useInboxWobble();
  const currentApprovalIdsRef = useRef<Set<string>>(new Set());
  const seenApprovalIdsRef = useRef<Set<string>>(new Set());

  // Sidebar mode: "simple" (only core items) or "full" (everything)
  const { mode: sidebarMode } = useSidebarModeStore();
  const { selectedAgent, agents } = useAgentStore();
  const currentAgent = agents.find((agent) => agent.id === selectedAgent);
  const backendCapabilities = useMemo(
    () =>
      currentAgent
        ? {
            ...currentAgent.backend_capabilities,
            workspace_ui:
              currentAgent.backend === "qwenpaw"
                ? currentAgent.backend_capabilities?.workspace_ui ?? true
                : false,
          }
        : undefined,
    [currentAgent],
  );

  // Menu + route snapshots from registry (builtin + plugin registrations merged).
  const rawAgentMenu = useMenuItems("primary.agentScoped");
  const rawSettingsMenu = useMenuItems("primary.settings");
  const routes = useRoutes();

  // Apply simple-mode filtering when enabled
  const agentMenu = useMemo(() => {
    const visibleMenu = filterMenuForAgentCapabilities(
      rawAgentMenu,
      backendCapabilities,
    );
    return sidebarMode === "simple"
      ? flattenMenuForSimpleMode(visibleMenu)
      : visibleMenu;
  }, [backendCapabilities, rawAgentMenu, sidebarMode]);
  const settingsMenu = useMemo(
    () =>
      sidebarMode === "simple"
        ? flattenMenuForSimpleMode(rawSettingsMenu)
        : rawSettingsMenu,
    [rawSettingsMenu, sidebarMode],
  );

  // Flat nav entries for simple mode (icon + label + path)
  const simpleFlatNav = useMemo(() => {
    if (sidebarMode !== "simple") return [];
    return [
      ...flattenMenu(agentMenu, routes, 16),
      ...flattenMenu(settingsMenu, routes, 16),
    ];
  }, [agentMenu, settingsMenu, routes, sidebarMode]);
  const simpleInboxEntry = simpleFlatNav.find(
    (entry) => entry.key === "core.inbox",
  );
  const simpleFoldedNav = simpleFlatNav.filter(
    (entry) => entry.key !== "core.inbox",
  );

  // ── Effects ──────────────────────────────────────────────────────────────

  useEffect(() => {
    authApi
      .getStatus()
      .then((res) => setAuthEnabled(res.enabled))
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!isMobile && shouldShowDesktopModeHint(window.localStorage)) {
      setDesktopModeHintOpen(true);
    }
  }, [isMobile]);

  const dismissDesktopHint = useCallback(() => {
    dismissDesktopModeHint(window.localStorage);
    setDesktopModeHintOpen(false);
  }, []);

  const desktopModeHintSteps = useMemo<TourProps["steps"]>(
    () => [
      {
        title: t("sidebar.desktopModeHint.title", "Try Desktop Mode"),
        description: t(
          "sidebar.desktopModeHint.description",
          "Open quick settings here, then choose Desktop Mode for a window-based workspace.",
        ),
        target: () => settingsButtonRef.current as HTMLButtonElement,
        placement: "rightBottom",
        nextButtonProps: {
          children: t("sidebar.desktopModeHint.gotIt", "Got it"),
        },
      },
    ],
    [t],
  );

  useEffect(() => {
    if (
      typeof window === "undefined" ||
      typeof window.matchMedia !== "function"
    ) {
      return;
    }

    const mediaQuery = window.matchMedia(MOBILE_SIDEBAR_QUERY);
    const syncMobileSidebar = () => {
      setIsMobile(mediaQuery.matches);
      // Collapse on mobile to avoid covering the main content; expand again
      // when the viewport returns to desktop width.
      setCollapsed(mediaQuery.matches);
    };

    syncMobileSidebar();
    mediaQuery.addEventListener("change", syncMobileSidebar);

    return () => {
      mediaQuery.removeEventListener("change", syncMobileSidebar);
    };
  }, []);
  useEffect(() => {
    const loadUnreadState = async () => {
      try {
        const [inboxRes, pushRes] = await Promise.all([
          api.getInboxEvents({
            unread_only: true,
            limit: 1,
          }),
          api.getPushMessages(),
        ]);
        const hasUnreadEvents = (inboxRes?.events?.length || 0) > 0;
        const approvals = pushRes?.pending_approvals || [];
        const currentIds = new Set(
          approvals.map((a: { request_id: string }) => a.request_id),
        );
        currentApprovalIdsRef.current = currentIds;
        const hasNewApprovals =
          currentIds.size > 0 &&
          [...currentIds].some((id) => !seenApprovalIdsRef.current.has(id));
        setShakeInbox(hasNewApprovals);
        setHasUnreadMessages(hasUnreadEvents);
        setHasPendingApprovals(currentIds.size > 0);
      } catch {
        // Keep previous state when polling fails.
      }
    };
    void loadUnreadState();
    const timer = window.setInterval(() => {
      void loadUnreadState();
    }, INBOX_BADGE_POLLING_MS);
    return () => window.clearInterval(timer);
  }, []);

  // ── Pre-fetch sessions on mount ───────────────────────────────────────────
  // On mobile the sidebar starts collapsed so SidebarSessionList is unmounted
  // and never fetches.  When the user expands the sidebar the list mounts fresh
  // but the Zustand store may still be empty (ChatSessionInitializer may not
  // have synced yet).  Proactively fetch sessions into the store so the data
  // is ready the moment the user expands.  Fire on mount regardless of
  // sidebar mode (the default "full" mode also benefits from this).
  // Uses sessionApi.getSessionList() instead of raw api.listChats() to ensure
  // the same data processing pipeline (dedup, realId, generating state) as
  // the desktop ChatSessionDrawer.
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const list = await sessionApi.getSessionList();
        if (!cancelled && list.length > 0) {
          syncSessionsGlobal(list as ExtendedSession[]);
        }
      } catch {
        // Best-effort: let SidebarSessionList retry on its own.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // ── Inbox badge dot & wobble ─────────────────────────────────────────────
  const hasInboxUnread = hasUnreadMessages || hasPendingApprovals;
  const inboxDotColor = hasPendingApprovals
    ? "#e04848"
    : "rgba(255, 157, 77, 1)";
  const effectiveShake = shakeInbox && wobbleEnabled;

  // ── Adapter: convert MenuItem trees to antd, with inbox badge decoration.

  /** Mark current approvals as "seen" so the wobble stops. */
  const handleInboxHover = useCallback(() => {
    seenApprovalIdsRef.current = new Set(currentApprovalIdsRef.current);
    setShakeInbox(false);
  }, []);

  /**
   * Bridge hover events from the antd Menu `<li>` to our handler.
   * addEventListener de-duplicates the same function reference, so re-calling
   * on the same element is harmless; old detached elements are GC'd naturally.
   */
  const inboxLiRefCallback = useCallback(
    (node: HTMLSpanElement | null) => {
      const li = node?.closest("li");
      if (!li) return;
      li.addEventListener("mouseenter", handleInboxHover);
    },
    [handleInboxHover],
  );

  /** Wrap the inbox label with the unread-Badge while keeping all other labels intact. */
  const decorateLabel = (item: MenuItem, label: ReactNode): ReactNode => {
    if (item.id !== "core.inbox" || label == null) return label;
    return (
      <span ref={inboxLiRefCallback}>
        <Badge dot={hasInboxUnread} color={inboxDotColor} offset={[5, 7]}>
          <span>{label}</span>
        </Badge>
      </span>
    );
  };

  const getItemClassName = (item: MenuItem) => {
    if (item.id === "core.inbox" && effectiveShake) {
      return styles.inboxShake;
    }
    return undefined;
  };

  const agentMenuItems = useMemo(
    () =>
      toAntdItems(agentMenu, { collapsed, decorateLabel, getItemClassName }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [
      agentMenu,
      collapsed,
      hasUnreadMessages,
      hasPendingApprovals,
      effectiveShake,
    ],
  );

  const settingsMenuItems = useMemo(
    () => toAntdItems(settingsMenu, { collapsed }),
    [settingsMenu, collapsed],
  );

  const openKeys = useMemo(
    () => [...deriveOpenKeys(agentMenu), ...deriveOpenKeys(settingsMenu)],
    [agentMenu, settingsMenu],
  );

  const collapsedNavItems = useMemo(() => {
    // Sticky chat is its own carve-out (lives outside menu data — see builtinMenu.ts).
    const stickyChat: FlatMenuEntry = {
      key: "core.chat",
      icon: <SparkChatTabFill size={18} />,
      path: chatPath,
      label: t("nav.chat"),
    };
    // Inbox in collapsed mode shows a dot overlay on its icon (kept Sidebar-local
    // for the same reason as decorateLabel: live state isn't menu data).
    const decorateInboxIcon = (icon: ReactNode): ReactNode => (
      <span style={{ position: "relative", display: "inline-flex" }}>
        {icon ?? <SparkEmailLine size={18} />}
        {hasInboxUnread && (
          <span
            style={{
              position: "absolute",
              top: -1,
              right: -3,
              width: 6,
              height: 6,
              borderRadius: "50%",
              background: inboxDotColor,
            }}
          />
        )}
      </span>
    );
    const flat = [
      stickyChat,
      ...flattenMenu(agentMenu, routes, 18),
      ...flattenMenu(settingsMenu, routes, 18),
    ];
    return flat.map((entry) =>
      entry.key === "core.inbox"
        ? { ...entry, icon: decorateInboxIcon(entry.icon) }
        : entry,
    );
  }, [
    agentMenu,
    settingsMenu,
    routes,
    chatPath,
    t,
    hasInboxUnread,
    inboxDotColor,
  ]);

  // ── Handlers ──────────────────────────────────────────────────────────────

  const handleMenuClick = (key: string, allItems: MenuItem[]) => {
    const item = findMenuItem(allItems, key);
    if (item?.href) {
      window.open(item.href, "_blank", "noopener,noreferrer");
      return;
    }
    const path = routeIdToPath(item?.route, routes);
    if (path) navigate(path);
  };

  /**
   * New chat: if we're already on the chat page, dispatch the event so
   * ChatSessionInitializer (which is mounted) creates the session.
   * If we're on another page, navigate to /chat without a session id —
   * the chat page will auto-create a new session on mount.
   */
  const handleNewChat = useCallback(() => {
    const onChatPage = location.pathname.startsWith("/chat");
    if (onChatPage) {
      window.dispatchEvent(new CustomEvent("qwenpaw:sidebar-new-chat"));
    } else {
      sessionStorage.setItem("qwenpaw_pending_new_chat", "1");
      navigate("/chat");
    }
  }, [location.pathname, navigate]);

  /**
   * Session click: navigate directly without relying on ChatSessionInitializer.
   * Resolve realId (backend UUID) to avoid exposing local timestamp in URL.
   */
  const handleSidebarSessionClick = useCallback(
    (sessionId: string) => {
      const effectiveId = sessionApi.getEffectiveSessionId(sessionId);
      const targetPath = buildChatPath(effectiveId);
      navigate(targetPath);
    },
    [navigate],
  );

  const handleUpdateProfile = async (values: {
    currentPassword: string;
    newUsername?: string;
    newPassword?: string;
  }) => {
    const trimmedUsername = values.newUsername?.trim() || undefined;
    const trimmedPassword = values.newPassword?.trim() || undefined;

    if (values.newPassword && !trimmedPassword) {
      message.error(t("account.passwordEmpty"));
      return;
    }

    if (values.newUsername && !trimmedUsername) {
      message.error(t("account.usernameEmpty"));
      return;
    }

    if (!trimmedUsername && !trimmedPassword) {
      message.warning(t("account.nothingToUpdate"));
      return;
    }

    setAccountLoading(true);
    try {
      await authApi.updateProfile(
        values.currentPassword,
        trimmedUsername,
        trimmedPassword,
      );
      message.success(t("account.updateSuccess"));
      setAccountModalOpen(false);
      accountForm.resetFields();
      clearAuthToken();
      window.location.href = "/login";
    } catch (err: unknown) {
      const raw = err instanceof Error ? err.message : "";
      let msg = t("account.updateFailed");
      if (raw.includes("password is incorrect")) {
        msg = t("account.wrongPassword");
      } else if (raw.includes("Nothing to update")) {
        msg = t("account.nothingToUpdate");
      } else if (raw.includes("cannot be empty")) {
        msg = t("account.nothingToUpdate");
      } else if (raw) {
        msg = raw;
      }
      message.error(msg);
    } finally {
      setAccountLoading(false);
    }
  };

  // ── Render ────────────────────────────────────────────────────────────────

  const isChatActive = selectedKey === "core.chat";
  // `renderIcon` retained for tree-shaking awareness.
  void renderIcon;

  // On mobile, the expanded sidebar shows sessions (like simple mode) instead
  // of the full menu — matching the desktop history panel UX.
  const isSimpleExpanded = (sidebarMode === "simple" || isMobile) && !collapsed;
  const siderWidth = collapsed
    ? isMobile
      ? 56
      : 72
    : sidebarMode === "simple" && !isMobile
    ? 280
    : 240;

  return (
    <Sider
      width={siderWidth}
      className={`${styles.sider}${
        collapsed ? ` ${styles.siderCollapsed}` : ""
      }${isDark ? ` ${styles.siderDark}` : ""}${
        isSimpleExpanded ? ` ${styles.siderSimple}` : ""
      }`}
    >
      {collapsed ? (
        <nav className={styles.collapsedNav}>
          {collapsedNavItems.map((item) => {
            const isActive =
              item.key === "core.chat"
                ? isChatActive
                : selectedKey === item.key;
            return (
              <Tooltip
                key={item.key}
                title={item.label}
                placement="right"
                overlayInnerStyle={{
                  background: "rgba(0,0,0,0.75)",
                  color: "#fff",
                }}
              >
                <button
                  className={`${styles.collapsedNavItem} ${
                    isActive ? styles.collapsedNavItemActive : ""
                  }${
                    item.key === "core.inbox" && effectiveShake
                      ? ` ${styles.inboxShake}`
                      : ""
                  }`}
                  onClick={() => {
                    if (item.href) {
                      window.open(item.href, "_blank", "noopener,noreferrer");
                    } else {
                      navigate(item.path);
                    }
                  }}
                  onMouseEnter={
                    item.key === "core.inbox" ? handleInboxHover : undefined
                  }
                >
                  {item.icon}
                </button>
              </Tooltip>
            );
          })}
        </nav>
      ) : isSimpleExpanded ? (
        <>
          {/* Simple mode: agent context and navigation share one panel. */}
          <div
            className={`${styles.agentScopedSection} ${styles.simpleAgentPanel}`}
          >
            <div className={styles.agentSelectorContainer}>
              <AgentSelector collapsed={collapsed} />
            </div>
            <button
              type="button"
              className={`${styles.simpleNavItem} ${styles.simpleChatItem} ${
                isChatActive ? styles.simpleNavItemActive : ""
              }`}
              onClick={() => navigate(chatPath)}
            >
              <MessageSquareText size={16} />
              <span>{t("nav.chat")}</span>
            </button>
            {simpleInboxEntry && (
              <button
                type="button"
                className={`${styles.simpleNavItem} ${styles.simpleInboxItem} ${
                  selectedKey === simpleInboxEntry.key
                    ? styles.simpleNavItemActive
                    : ""
                }${effectiveShake ? ` ${styles.inboxShake}` : ""}`}
                onMouseEnter={handleInboxHover}
                onClick={() => {
                  if (simpleInboxEntry.href) {
                    window.open(
                      simpleInboxEntry.href,
                      "_blank",
                      "noopener,noreferrer",
                    );
                  } else {
                    navigate(simpleInboxEntry.path);
                  }
                }}
              >
                <span className={styles.simpleInboxIcon}>
                  {simpleInboxEntry.icon ?? <SparkEmailLine size={16} />}
                  {hasInboxUnread && (
                    <span
                      className={styles.simpleInboxUnreadDot}
                      style={{ background: inboxDotColor }}
                    />
                  )}
                </span>
                <span>{simpleInboxEntry.label}</span>
              </button>
            )}
            <button
              type="button"
              className={styles.simpleAgentDisclosure}
              aria-expanded={simpleAgentFunctionsExpanded}
              aria-controls="simple-agent-functions"
              aria-label={t(
                "sidebar.toggleAgentNavigation",
                "Expand or collapse agent navigation",
              )}
              onClick={() =>
                setSimpleAgentFunctionsExpanded((expanded) => !expanded)
              }
            >
              <span className={styles.simpleAgentDisclosureLine} />
              <motion.span
                className={styles.simpleAgentDisclosureHandle}
                animate={{ rotate: simpleAgentFunctionsExpanded ? 180 : 0 }}
                transition={
                  prefersReducedMotion
                    ? { duration: 0 }
                    : { duration: 0.22, ease: [0.22, 0.78, 0.24, 1] }
                }
              >
                <ChevronDown size={14} />
              </motion.span>
              <span className={styles.simpleAgentDisclosureLine} />
            </button>
            <AnimatePresence initial={false}>
              {simpleAgentFunctionsExpanded && (
                <motion.div
                  key="simple-agent-functions"
                  id="simple-agent-functions"
                  className={styles.simpleAgentFunctionsMotion}
                  initial={
                    prefersReducedMotion
                      ? false
                      : { height: 0, opacity: 0, y: -4 }
                  }
                  animate={{ height: "auto", opacity: 1, y: 0 }}
                  exit={{ height: 0, opacity: 0, y: -4 }}
                  transition={
                    prefersReducedMotion
                      ? { duration: 0 }
                      : { duration: 0.24, ease: [0.22, 0.78, 0.24, 1] }
                  }
                >
                  <div className={styles.simpleNavItems}>
                    {simpleFoldedNav.map((entry) => {
                      const isActive = selectedKey === entry.key;
                      return (
                        <button
                          key={entry.key}
                          className={`${styles.simpleNavItem} ${
                            isActive ? styles.simpleNavItemActive : ""
                          }`}
                          onClick={() => {
                            if (entry.href) {
                              window.open(
                                entry.href,
                                "_blank",
                                "noopener,noreferrer",
                              );
                            } else {
                              navigate(entry.path);
                            }
                          }}
                        >
                          {entry.icon}
                          <span>{entry.label}</span>
                        </button>
                      );
                    })}
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>

          {/* Session list — fills the primary space. */}
          <SidebarSessionList
            onNewChat={handleNewChat}
            onSessionClick={handleSidebarSessionClick}
          />
        </>
      ) : (
        <>
          {/* Agent-scoped section: selector + Chat + Control + Workspace */}
          <div className={styles.agentScopedSection}>
            <div className={styles.agentSelectorContainer}>
              <AgentSelector collapsed={collapsed} />
              {/* Chat entry — sticky together with agent selector */}
              <button
                className={`${styles.stickyChatButton}${
                  isChatActive ? ` ${styles.stickyChatButtonActive}` : ""
                }`}
                onClick={() => navigate(chatPath)}
              >
                <SparkChatTabFill size={16} />
                <span>{t("nav.chat")}</span>
              </button>
            </div>
            <Slot name="sider.top" kind="fill" />
            <Menu
              mode="inline"
              selectedKeys={[selectedKey]}
              openKeys={openKeys}
              onClick={({ key }) => handleMenuClick(String(key), agentMenu)}
              items={agentMenuItems}
              theme={isDark ? "dark" : "light"}
              className={styles.sideMenu}
            />
          </div>

          {/* Global settings section */}
          <Menu
            mode="inline"
            selectedKeys={[selectedKey]}
            openKeys={openKeys}
            onClick={({ key }) => handleMenuClick(String(key), settingsMenu)}
            items={settingsMenuItems}
            theme={isDark ? "dark" : "light"}
            className={styles.sideMenu}
          />
          <Slot name="sider.bottom" kind="fill" />
        </>
      )}

      {authEnabled && !collapsed && (
        <div className={styles.authActions}>
          <Button
            type="text"
            icon={<SparkSearchUserLine size={16} />}
            onClick={() => {
              accountForm.resetFields();
              setAccountModalOpen(true);
            }}
            block
            className={`${styles.authBtn} ${
              collapsed ? styles.authBtnCollapsed : ""
            }`}
          >
            {!collapsed && t("account.title")}
          </Button>
          <Button
            type="text"
            icon={<SparkExitFullscreenLine size={16} />}
            onClick={() => {
              clearAuthToken();
              window.location.href = "/login";
            }}
            block
            className={`${styles.authBtn} ${
              collapsed ? styles.authBtnCollapsed : ""
            }`}
          >
            {!collapsed && t("login.logout")}
          </Button>
        </div>
      )}

      <div className={styles.collapseToggleContainer}>
        {/* Gear stays visible in collapsed state too — otherwise users
            (especially on mobile, where the sidebar starts collapsed)
            cannot discover how to restore full mode. */}
        <Popover
          open={settingsOpen}
          onOpenChange={setSettingsOpen}
          placement={collapsed ? "rightBottom" : "topRight"}
          trigger="click"
          content={
            <SidebarSettingsPanel onClose={() => setSettingsOpen(false)} />
          }
        >
          <Button
            ref={settingsButtonRef}
            type="text"
            icon={<SparkSettingLine size={18} />}
            className={styles.collapseToggle}
          />
        </Popover>
        <Button
          type="text"
          icon={
            collapsed ? (
              <SparkMenuExpandLine size={20} />
            ) : (
              <SparkMenuFoldLine size={20} />
            )
          }
          onClick={() => setCollapsed(!collapsed)}
          className={styles.collapseToggle}
        />
      </div>

      <Tour
        open={desktopModeHintOpen}
        steps={desktopModeHintSteps}
        onClose={dismissDesktopHint}
        onFinish={dismissDesktopHint}
        mask={{ color: "rgba(9, 9, 11, 0.2)" }}
      />

      <Modal
        open={accountModalOpen}
        onCancel={() => setAccountModalOpen(false)}
        title={t("account.title")}
        footer={null}
        destroyOnHidden
        centered
      >
        <Form
          form={accountForm}
          layout="vertical"
          onFinish={handleUpdateProfile}
        >
          <Form.Item
            name="currentPassword"
            label={t("account.currentPassword")}
            rules={[
              { required: true, message: t("account.currentPasswordRequired") },
            ]}
          >
            <Input.Password />
          </Form.Item>
          <Form.Item name="newUsername" label={t("account.newUsername")}>
            <Input placeholder={t("account.newUsernamePlaceholder")} />
          </Form.Item>
          <Form.Item name="newPassword" label={t("account.newPassword")}>
            <Input.Password placeholder={t("account.newPasswordPlaceholder")} />
          </Form.Item>
          <Form.Item
            name="confirmPassword"
            label={t("account.confirmPassword")}
            dependencies={["newPassword"]}
            rules={[
              ({ getFieldValue }) => ({
                validator(_, value) {
                  if (!value && !getFieldValue("newPassword")) {
                    return Promise.resolve();
                  }
                  if (value === getFieldValue("newPassword")) {
                    return Promise.resolve();
                  }
                  return Promise.reject(
                    new Error(t("account.passwordMismatch")),
                  );
                },
              }),
            ]}
          >
            <Input.Password
              placeholder={t("account.confirmPasswordPlaceholder")}
            />
          </Form.Item>
          <Form.Item>
            <Button
              type="primary"
              htmlType="submit"
              loading={accountLoading}
              block
            >
              {t("account.save")}
            </Button>
          </Form.Item>
        </Form>
      </Modal>
    </Sider>
  );
}
