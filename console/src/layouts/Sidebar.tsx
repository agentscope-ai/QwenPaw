import { NotificationBell } from "@/components/interaction/NotificationBell";
import {
  Layout,
  Button,
  Modal,
  Input,
  Form,
  Tooltip,
  Popover,
  Popconfirm,
  Divider,
} from "antd";
import { useState, useEffect, useMemo, useCallback, useRef } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  Check,
  Grid2X2,
  SlidersHorizontal,
  Puzzle,
  History,
  RotateCw,
  Settings,
  ShieldCheck,
} from "lucide-react";
import { useAppMessage } from "../hooks/useAppMessage";
import AgentSelector from "../components/AgentSelector";
import {
  Bot as SparkAgentLine,
  SquarePen as SparkNewChatLine,
  ChevronLeft as SparkOperateLeftLine,
  ChevronRight as SparkOperateRightLine,
} from "lucide-react";
import SidebarSessionList from "./SidebarSessionList";
import DockableSidebar from "./DockableSidebar";
import skin from "./sidebarA.module.less";
import SidebarUsage from "./SidebarUsage";
import { DEFAULT_AVATAR, useLocalAvatar } from "../stores/localAvatarStore";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { InteractiveCard } from "../components/interaction/InteractiveCard";
import { RunningGlow } from "../components/interaction/RunningGlow";
import SidebarSettingsPanel from "./SidebarSettingsPanel";
import { clearAuthToken, getApiToken } from "../api/config";
import { authApi } from "../api/modules/auth";
import api from "../api";
import {
  syncSessionsGlobal,
  type ExtendedSession,
} from "../stores/sessionListStore";
import { useSidebarStore } from "../stores/sidebarStore";
import { buildChatPath } from "../utils/sessionRoute";
import { getOsRootHref } from "../utils/navigationMode";
import { openExternalLink } from "../utils/openExternalLink";
import {
  getSidebarCollapsedPreference,
  setSidebarCollapsedPreference,
} from "../utils/sidebarCollapsedPreference";
import { useAgentStore } from "../stores/agentStore";
import sessionApi from "../pages/Chat/sessionApi";
import { useInboxWobble } from "../hooks/useInboxWobble";
import styles from "./index.module.less";
import { useTheme } from "../contexts/ThemeContext";
import { useMenuItems, useRoutes } from "../plugins/registry/hooks";
import { Slot } from "../plugins/registry/Slot";
import { flattenMenu } from "./registry/adapter";
import type { FlatMenuEntry } from "./registry/adapter";
import { filterMenuForAgentCapabilities } from "./registry/capabilities";
import {
  filterSidebarMenuItems,
  orderSidebarEntries,
} from "./registry/sidebarEntries";
import { hubApi } from "../api/modules/hub";
import AppBrand from "./AppBrand";
import { AgentStatusIndicator } from "../components/AgentStatusIndicator";
import { getAgentDisplayName } from "../utils/agentDisplayName";
import { isAgentAvailableInChat } from "../utils/agentVisibility";

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
const TOOLS_MODE_KEY = "qwenpaw_sidebar_tools_mode";
function readToolsMode(): number {
  try {
    const value = Number(localStorage.getItem(TOOLS_MODE_KEY));
    return [0, 1, 2].includes(value) ? value : 0;
  } catch {
    return 0;
  }
}
const INBOX_BADGE_POLLING_MS = 6000;
// ── Types ─────────────────────────────────────────────────────────────────

interface SidebarProps {
  /** Route id of the currently active page (e.g. "core.workspace"). */
  selectedKey: string;
  hubMode?: boolean;
}

// ── Sidebar ───────────────────────────────────────────────────────────────

export default function Sidebar({
  selectedKey,
  hubMode = false,
}: SidebarProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const { t, i18n } = useTranslation();
  const localAvatar = useLocalAvatar((state) =>
    state.selected ? state.images[state.selected] : undefined,
  );
  useEffect(() => {
    const reload = () => {
      useLocalAvatar.getState().reset();
      if (getApiToken())
        void useLocalAvatar
          .getState()
          .load()
          .catch(() => {});
    };
    void useLocalAvatar
      .getState()
      .load()
      .catch(() => {});
    window.addEventListener("qwenpaw:auth-changed", reload);
    return () => window.removeEventListener("qwenpaw:auth-changed", reload);
  }, []);
  const language = i18n.resolvedLanguage ?? i18n.language;
  const { message } = useAppMessage();
  const { isDark } = useTheme();
  const [authEnabled, setAuthEnabled] = useState(false);
  const [hubAdmin, setHubAdmin] = useState(false);
  const [hubUsername, setHubUsername] = useState("");
  const [authUsername, setAuthUsername] = useState("");
  const [accountModalOpen, setAccountModalOpen] = useState(false);
  const [accountLoading, setAccountLoading] = useState(false);
  const [runtimeRestarting, setRuntimeRestarting] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [historyPopoverOpen, setHistoryPopoverOpen] = useState(false);
  const [agentPopoverOpen, setAgentPopoverOpen] = useState(false);
  const [version, setVersion] = useState("");
  const [accountForm] = Form.useForm();
  // Start collapsed on mobile so the first paint does not overlay/obscure
  // the main content on narrow viewports. On desktop, restore the persisted
  // preference so a reload keeps the last collapsed/expanded state.
  const [collapsed, setCollapsed] = useState(
    () => isMobileSidebarViewport() || getSidebarCollapsedPreference(),
  );
  const [isMobile, setIsMobile] = useState(isMobileSidebarViewport);
  const navScrollRef = useRef<HTMLDivElement>(null);
  const reducedMotion = useReducedMotion();
  const [toolsMode, setToolsMode] = useState(readToolsMode);
  const toolsOpen = toolsMode !== 0;
  const modeLabel = [
    t("sidebar.toolsCompact", "Compact tools"),
    t("sidebar.toolsDetailed", "Detailed tools"),
    t("sidebar.foldTools", "Collapse tools"),
  ][toolsMode];
  const cycleTools = () => {
    const next = (toolsMode + 1) % 3;
    setToolsMode(next);
    try {
      localStorage.setItem(TOOLS_MODE_KEY, String(next));
    } catch {
      /* Storage can be disabled. */
    }
  };
  const [unreadCount, setUnreadCount] = useState(0);
  const [hasPendingApprovals, setHasPendingApprovals] = useState(false);
  const [shakeInbox, setShakeInbox] = useState(false);
  const [wobbleEnabled] = useInboxWobble();
  const currentApprovalIdsRef = useRef<Set<string>>(new Set());
  const seenApprovalIdsRef = useRef<Set<string>>(new Set());

  const { focusItemIds, hiddenPluginItemIds } = useSidebarStore();
  const { selectedAgent, agents, setSelectedAgent, refreshAgents } =
    useAgentStore();
  const currentAgent = agents.find((agent) => agent.id === selectedAgent);
  const availableAgents = useMemo(
    () =>
      agents.filter((agent) => agent.enabled && isAgentAvailableInChat(agent)),
    [agents],
  );
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

  const visibleAgentMenu = useMemo(
    () => filterMenuForAgentCapabilities(rawAgentMenu, backendCapabilities),
    [backendCapabilities, rawAgentMenu],
  );
  const focusItemIdSet = useMemo(() => new Set(focusItemIds), [focusItemIds]);
  const hiddenPluginItemIdSet = useMemo(
    () => new Set(hiddenPluginItemIds),
    [hiddenPluginItemIds],
  );

  // Selected entries form both the expanded and collapsed navigation surface.
  const agentMenu = useMemo(
    () =>
      filterSidebarMenuItems(
        visibleAgentMenu,
        focusItemIdSet,
        hiddenPluginItemIdSet,
      ),
    [focusItemIdSet, hiddenPluginItemIdSet, visibleAgentMenu],
  );
  const selectedSettingsMenu = useMemo(
    () =>
      filterSidebarMenuItems(
        rawSettingsMenu,
        focusItemIdSet,
        hiddenPluginItemIdSet,
      ),
    [focusItemIdSet, hiddenPluginItemIdSet, rawSettingsMenu],
  );

  const selectedFlatNav = useMemo(() => {
    const entries = [
      ...flattenMenu(agentMenu, routes, 16),
      ...flattenMenu(selectedSettingsMenu, routes, 16),
    ];
    const uniqueEntries = [
      ...new Map(entries.map((entry) => [entry.key, entry])).values(),
    ];
    return orderSidebarEntries(uniqueEntries, focusItemIds);
  }, [agentMenu, focusItemIds, routes, selectedSettingsMenu, language]);
  // ── Effects ──────────────────────────────────────────────────────────────

  useEffect(() => {
    const activeEntry = navScrollRef.current?.querySelector<HTMLElement>(
      '[aria-current="page"]',
    );
    if (toolsOpen && activeEntry && navScrollRef.current) {
      const list = navScrollRef.current;
      const itemTop =
        activeEntry.getBoundingClientRect().top -
        list.getBoundingClientRect().top +
        list.scrollTop;
      if (itemTop < list.scrollTop) list.scrollTop = itemTop;
      else if (
        itemTop + activeEntry.offsetHeight >
        list.scrollTop + list.clientHeight
      )
        list.scrollTop = itemTop + activeEntry.offsetHeight - list.clientHeight;
    }
  }, [selectedKey, selectedFlatNav, toolsOpen]);

  useEffect(() => {
    api
      .getVersion()
      .then((response) => setVersion(response?.version ?? ""))
      .catch(() => {});
  }, []);

  useEffect(() => {
    authApi
      .getStatus()
      .then(async (res) => {
        setAuthEnabled(res.enabled);
        if (res.mode === "hub") {
          const user = await hubApi.me();
          setHubAdmin(user.role === "admin");
          setHubUsername(user.username);
          setAuthUsername(user.username);
        } else if (res.enabled) {
          const user = await authApi.getCurrentUser();
          setAuthUsername(user.username);
        }
      })
      .catch(() => {});
  }, []);

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
      // Collapse on mobile to avoid covering the main content. This is a
      // transient viewport override: it never writes the preference, and
      // returning to desktop width restores what the user last chose.
      setCollapsed(mediaQuery.matches || getSidebarCollapsedPreference());
    };

    syncMobileSidebar();
    mediaQuery.addEventListener("change", syncMobileSidebar);

    return () => {
      mediaQuery.removeEventListener("change", syncMobileSidebar);
    };
  }, []);

  useEffect(() => {
    if (!collapsed) {
      setHistoryPopoverOpen(false);
      setAgentPopoverOpen(false);
    }
  }, [collapsed]);

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
        setUnreadCount(
          inboxRes?.unread_count ??
            inboxRes?.total ??
            (hasUnreadEvents ? 1 : 0),
        );
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
  // sidebar is expanded.
  // Uses sessionApi.getSessionList() instead of raw api.listChats() to ensure
  // the same data processing pipeline (dedup, realId, generating state) as
  // the shared conversation-history list.
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
  const effectiveShake = shakeInbox && wobbleEnabled;

  // ── Adapter: convert MenuItem trees to antd, with inbox badge decoration.

  /** Mark current approvals as "seen" so the wobble stops. */
  const handleInboxHover = useCallback(() => {
    seenApprovalIdsRef.current = new Set(currentApprovalIdsRef.current);
    setShakeInbox(false);
  }, []);

  const collapsedNavItems = useMemo(() => {
    // Inbox in collapsed mode shows a dot overlay on its icon (kept Sidebar-local
    // for the same reason as decorateLabel: live state isn't menu data).
    const scrollableEntries = [
      ...flattenMenu(agentMenu, routes, 18),
      ...flattenMenu(selectedSettingsMenu, routes, 18),
    ];
    const inboxEntry = scrollableEntries.find(
      (entry) => entry.key === "core.inbox",
    );
    const orderedEntries = orderSidebarEntries(
      scrollableEntries.filter((entry) => entry.key !== "core.inbox"),
      focusItemIds,
    );
    const flat = [...(inboxEntry ? [inboxEntry] : []), ...orderedEntries];
    return flat.map((entry) =>
      entry.key === "core.inbox"
        ? {
            ...entry,
            icon: (
              <NotificationBell
                count={unreadCount}
                attention={hasPendingApprovals}
                animate={wobbleEnabled}
                ring={effectiveShake}
              />
            ),
          }
        : entry,
    );
  }, [
    agentMenu,
    focusItemIds,
    selectedSettingsMenu,
    routes,
    unreadCount,
    hasPendingApprovals,
    wobbleEnabled,
    effectiveShake,
    language,
  ]);

  // ── Handlers ──────────────────────────────────────────────────────────────

  /**
   * Explicit user toggle: the only path that persists the collapsed state.
   * Viewport-driven collapsing stays transient so a narrow window does not
   * permanently pin the desktop sidebar.
   */
  const handleSetCollapsed = useCallback((nextCollapsed: boolean) => {
    setCollapsed(nextCollapsed);
    setSidebarCollapsedPreference(nextCollapsed);
  }, []);

  /**
   * New chat: if we're already on the chat page, dispatch the event so
   * ChatSessionInitializer opens a blank composer. From another page,
   * navigate to /chat without a session id. The first send creates the session.
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

  const handleOpenSettings = useCallback(() => {
    navigate("/settings/general", {
      state: {
        settingsReturnTo: `${location.pathname}${location.search}${location.hash}`,
      },
    });
  }, [location.hash, location.pathname, location.search, navigate]);

  const handleOpenDesktopMode = useCallback(() => {
    window.location.assign(getOsRootHref(window.location.pathname));
  }, []);

  const handleOpenAccount = useCallback(() => {
    accountForm.resetFields();
    setAccountModalOpen(true);
  }, [accountForm]);

  const handleLogout = useCallback(() => {
    clearAuthToken();
    window.location.href = "/login";
  }, []);

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
    currentPassword?: string;
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

    if (!hubMode && !trimmedUsername && !trimmedPassword) {
      message.warning(t("account.nothingToUpdate"));
      return;
    }

    setAccountLoading(true);
    try {
      if (hubMode) {
        if (!trimmedPassword) {
          message.warning(t("account.passwordRequired"));
          return;
        }
        await hubApi.changePassword(trimmedPassword);
      } else {
        await authApi.updateProfile(
          values.currentPassword || "",
          trimmedUsername,
          trimmedPassword,
        );
      }
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

  const handleRestartRuntime = async () => {
    setRuntimeRestarting(true);
    try {
      await hubApi.restartOwnRuntime();
      message.success(t("account.runtimeRestartSuccess"));
      window.location.reload();
    } catch (error: unknown) {
      message.error(
        error instanceof Error
          ? error.message
          : t("account.runtimeRestartFailed"),
      );
    } finally {
      setRuntimeRestarting(false);
    }
  };

  // ── Render ────────────────────────────────────────────────────────────────

  const isChatActive = selectedKey === "core.chat";

  const renderCollapsedNavItem = (item: FlatMenuEntry) => {
    const isActive =
      item.key === "core.chat" ? isChatActive : selectedKey === item.key;
    return (
      <Tooltip key={item.key} title={item.label} placement="right">
        <button
          type="button"
          aria-label={typeof item.label === "string" ? item.label : undefined}
          className={`${styles.collapsedNavItem} ${
            isActive ? styles.collapsedNavItemActive : ""
          }`}
          onClick={() => {
            if (item.href) {
              openExternalLink(item.href);
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
  };

  const renderNavItem = (entry: FlatMenuEntry) => {
    const isActive = selectedKey === entry.key;
    const isInbox = entry.key === "core.inbox";
    return (
      <button
        key={entry.key}
        aria-label={typeof entry.label === "string" ? entry.label : undefined}
        type="button"
        aria-current={isActive ? "page" : undefined}
        data-press
        onMouseEnter={isInbox ? handleInboxHover : undefined}
        className={`${styles.navigationItem} ${
          isActive ? styles.navigationItemActive : ""
        }`}
        onClick={() => {
          if (entry.href) {
            openExternalLink(entry.href);
          } else {
            navigate(entry.path);
          }
        }}
      >
        <span className={styles.inboxIcon}>
          {isInbox ? (
            <NotificationBell
              count={unreadCount}
              attention={hasPendingApprovals}
              animate={wobbleEnabled}
              ring={effectiveShake}
            />
          ) : (
            entry.icon ?? <Puzzle size={18} />
          )}
        </span>
        <motion.span
          className={skin.navLabel}
          animate={{ opacity: toolsMode === 2 ? 1 : 0 }}
          transition={{ duration: reducedMotion ? 0 : 0.18 }}
        >
          {entry.label}
        </motion.span>
      </button>
    );
  };

  const siderWidth = collapsed ? (isMobile ? 56 : 72) : isMobile ? 240 : 280;

  return (
    <DockableSidebar
      width={siderWidth}
      mobile={isMobile}
      onMobileDismiss={() => handleSetCollapsed(true)}
    >
      <Sider
        width={siderWidth}
        className={`${styles.sider} ${skin.surface} ${
          collapsed ? skin.compactRail : ""
        }${collapsed ? ` ${styles.siderCollapsed}` : ""}${
          isDark ? ` ${styles.siderDark}` : ""
        }${!collapsed ? ` ${styles.siderExpanded}` : ""}`}
      >
        <AppBrand
          hidden={collapsed}
          version={version}
          action={
            <Button
              type="text"
              icon={<SparkOperateLeftLine size={18} />}
              onClick={() => handleSetCollapsed(true)}
              className={styles.brandCollapseToggle}
              aria-label={t("sidebar.collapse", "Collapse sidebar")}
            />
          }
        />

        {collapsed ? (
          <nav className={styles.collapsedNav}>
            <div className={styles.collapsedNavPinned}>
              <Tooltip
                title={t("sidebar.expand", "Expand sidebar")}
                placement="right"
                mouseEnterDelay={0.5}
              >
                <button
                  type="button"
                  className={styles.collapsedNavItem}
                  aria-label={t("sidebar.expand", "Expand sidebar")}
                  onClick={() => handleSetCollapsed(false)}
                >
                  <SparkOperateRightLine size={18} />
                </button>
              </Tooltip>
              <Popover
                open={agentPopoverOpen}
                onOpenChange={(open) => {
                  setAgentPopoverOpen(open);
                  if (open && agents.length === 0) {
                    void refreshAgents().catch(() => {});
                  }
                }}
                placement="rightTop"
                trigger="click"
                arrow={false}
                overlayClassName={styles.collapsedAgentPopover}
                content={
                  <div className={styles.collapsedAgentPanel}>
                    <div className={styles.collapsedPanelTitle}>
                      {t("agent.selectAgent")}
                    </div>
                    <div className={styles.collapsedAgentList}>
                      {availableAgents.map((agent) => (
                        <button
                          key={agent.id}
                          type="button"
                          className={`${styles.collapsedAgentOption} ${
                            agent.id === selectedAgent
                              ? styles.collapsedAgentOptionActive
                              : ""
                          }`}
                          onClick={() => {
                            setSelectedAgent(agent.id);
                            setAgentPopoverOpen(false);
                            message.success(t("agent.switchSuccess"));
                          }}
                        >
                          <AgentStatusIndicator
                            status={agent.startup_status}
                            enabled={agent.enabled}
                          />
                          <SparkAgentLine size={18} />
                          <span className={styles.collapsedAgentName}>
                            {getAgentDisplayName(agent, t)}
                          </span>
                          {agent.id === selectedAgent && <Check size={16} />}
                        </button>
                      ))}
                    </div>
                  </div>
                }
              >
                <Tooltip
                  title={
                    currentAgent
                      ? getAgentDisplayName(currentAgent, t)
                      : t("agent.selectAgent")
                  }
                  placement="right"
                  mouseEnterDelay={0.5}
                >
                  <button
                    type="button"
                    className={styles.collapsedNavItem}
                    aria-label={t("agent.selectAgent")}
                    aria-expanded={agentPopoverOpen}
                  >
                    <SparkAgentLine size={18} />
                  </button>
                </Tooltip>
              </Popover>
              <Tooltip
                title={t("chat.newTask", "New task")}
                placement="right"
                mouseEnterDelay={0.5}
              >
                <button
                  type="button"
                  className={styles.collapsedNavItem}
                  aria-label={t("chat.newTask", "New task")}
                  onClick={handleNewChat}
                >
                  <SparkNewChatLine size={18} />
                </button>
              </Tooltip>
              <Popover
                open={historyPopoverOpen}
                onOpenChange={setHistoryPopoverOpen}
                placement="rightTop"
                trigger="click"
                arrow={false}
                overlayClassName={styles.collapsedHistoryPopover}
                content={
                  <div className={styles.collapsedHistoryPanel}>
                    <SidebarSessionList
                      onNewChat={() => {
                        setHistoryPopoverOpen(false);
                        handleNewChat();
                      }}
                      onSessionClick={(sessionId) => {
                        setHistoryPopoverOpen(false);
                        handleSidebarSessionClick(sessionId);
                      }}
                    />
                  </div>
                }
              >
                <Tooltip
                  title={t("chat.chatHistoryTooltip")}
                  placement="right"
                  mouseEnterDelay={0.5}
                >
                  <button
                    type="button"
                    className={styles.collapsedNavItem}
                    aria-label={t("chat.chatHistoryTooltip")}
                    aria-expanded={historyPopoverOpen}
                  >
                    <History size={18} />
                  </button>
                </Tooltip>
              </Popover>
            </div>
            <div className={styles.collapsedNavScroll}>
              {collapsedNavItems.map(renderCollapsedNavItem)}
            </div>
          </nav>
        ) : (
          <>
            <InteractiveCard
              as="section"
              tilt={2}
              frameClassName={skin.toolFrame}
              className={`${skin.toolPanel} ${
                toolsOpen ? skin.toolPanelOpen : ""
              }`}
              aria-label={t("sidebar.tools", "Agent and shortcuts")}
            >
              <div className={skin.toolHeader}>
                <button
                  type="button"
                  className={skin.toolHeaderHitArea}
                  aria-hidden="true"
                  tabIndex={-1}
                  title={modeLabel}
                  onClick={cycleTools}
                />
                <div className={skin.agent}>
                  <AgentSelector compact />
                </div>
                <button
                  type="button"
                  className={skin.toolButton}
                  data-press
                  aria-expanded={toolsOpen}
                  title={modeLabel}
                  aria-label={modeLabel}
                  data-mode={toolsMode}
                  onClick={cycleTools}
                >
                  <Grid2X2 size={16} />
                </button>
              </div>
              <RunningGlow active />
              <AnimatePresence initial={false}>
                {toolsOpen && (
                  <motion.div
                    key="tools"
                    layout="size"
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: "auto", opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    transition={
                      reducedMotion
                        ? { duration: 0 }
                        : { type: "spring", stiffness: 420, damping: 40 }
                    }
                    style={{ overflow: "hidden" }}
                  >
                    <motion.div
                      layout
                      transition={
                        reducedMotion
                          ? { duration: 0 }
                          : {
                              type: "spring",
                              stiffness: 420,
                              damping: 40,
                            }
                      }
                      ref={navScrollRef}
                      className={`${skin.navGrid} ${
                        toolsMode === 2 ? skin.navDetailed : ""
                      }`}
                    >
                      {selectedFlatNav.map((entry, index) => (
                        <motion.div
                          key={entry.key}
                          layout="position"
                          initial={reducedMotion ? false : { y: 7, opacity: 0 }}
                          animate={{ y: 0, opacity: 1 }}
                          transition={{
                            type: "spring",
                            stiffness: 420,
                            damping: 30,
                            delay: reducedMotion
                              ? 0
                              : Math.min(index * 0.025, 0.15),
                          }}
                        >
                          {renderNavItem(entry)}
                        </motion.div>
                      ))}

                      <button
                        type="button"
                        className={skin.moreSettings}
                        data-press
                        aria-label={t("nav.moreSettings", "More settings")}
                        onClick={handleOpenSettings}
                      >
                        <Settings size={18} />
                        <span className={skin.navLabel}>
                          {t("nav.moreSettings", "More settings")}
                        </span>
                      </button>
                    </motion.div>
                  </motion.div>
                )}
              </AnimatePresence>
            </InteractiveCard>
            <button
              type="button"
              data-press
              className={skin.newTask}
              onClick={handleNewChat}
            >
              <SparkNewChatLine size={18} />
              <span>{t("chat.newTask", "New task")}</span>
            </button>
            <div className={skin.pluginSlot}>
              <Slot name="sider.top" kind="fill" />
            </div>

            {/* Session list — fills the primary space. */}
            <div className={styles.sessionArea}>
              <SidebarSessionList
                defaultSearchOpen
                hideNewTask
                onNewChat={handleNewChat}
                onSessionClick={handleSidebarSessionClick}
              />
            </div>
            <div className={skin.pluginSlot}>
              <Slot name="sider.bottom" kind="fill" />
            </div>
          </>
        )}

        {authEnabled && hubAdmin && !collapsed && (
          <div className={styles.authActions}>
            <Button
              type="text"
              icon={<ShieldCheck size={16} />}
              onClick={() => navigate("/hub/admin")}
              block
              className={styles.authBtn}
            >
              {t("hub.brand.title")}
            </Button>
          </div>
        )}

        {!collapsed && (
          <SidebarUsage
            mobile={isMobile}
            agentId={selectedAgent ?? undefined}
          />
        )}
        <div className={styles.collapseToggleContainer}>
          <Popover
            open={settingsOpen}
            onOpenChange={setSettingsOpen}
            placement={collapsed ? "rightBottom" : "topRight"}
            trigger="click"
            overlayClassName={styles.quickSettingsPopover}
            destroyOnHidden
            content={
              <SidebarSettingsPanel
                version={version}
                onClose={() => setSettingsOpen(false)}
                onOpenDesktopMode={handleOpenDesktopMode}
                onOpenSettings={handleOpenSettings}
                authEnabled={authEnabled}
                onOpenAccount={handleOpenAccount}
                onLogout={handleLogout}
              />
            }
          >
            <button
              type="button"
              data-press
              title={t("sidebar.quickMenu.settings", "Settings")}
              aria-label={t("sidebar.quickMenu.settings", "Settings")}
              aria-haspopup="menu"
              aria-expanded={settingsOpen}
              className={collapsed ? styles.collapseToggle : skin.identity}
            >
              {collapsed ? (
                <Settings size={18} />
              ) : (
                <>
                  <span className={skin.avatar}>
                    <img src={localAvatar ?? DEFAULT_AVATAR} alt="QwenPaw" />
                  </span>
                  <span className={skin.identityText}>
                    <strong>
                      {authUsername || t("sidebar.localWorkspace")}
                    </strong>
                    <small>
                      {hubUsername
                        ? "QwenPaw Hub"
                        : authEnabled
                        ? t("sidebar.consoleAccount")
                        : t("sidebar.localMode")}
                    </small>
                  </span>
                  <SlidersHorizontal size={17} />
                </>
              )}
            </button>
          </Popover>
        </div>

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
            {hubMode ? (
              <div className={styles.accountIdentity}>
                <span>{t("account.username")}</span>
                <strong>{hubUsername}</strong>
              </div>
            ) : (
              <>
                <Form.Item
                  name="currentPassword"
                  label={t("account.currentPassword")}
                  rules={[
                    {
                      required: true,
                      message: t("account.currentPasswordRequired"),
                    },
                  ]}
                >
                  <Input.Password />
                </Form.Item>
                <Form.Item name="newUsername" label={t("account.newUsername")}>
                  <Input placeholder={t("account.newUsernamePlaceholder")} />
                </Form.Item>
              </>
            )}
            <Form.Item
              name="newPassword"
              label={t("account.newPassword")}
              rules={
                hubMode
                  ? [
                      {
                        required: true,
                        message: t("account.passwordRequired"),
                      },
                      { min: 8, message: t("hub.validation.passwordMin") },
                    ]
                  : undefined
              }
            >
              <Input.Password
                placeholder={t(
                  hubMode
                    ? "account.hubPasswordPlaceholder"
                    : "account.newPasswordPlaceholder",
                )}
              />
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
            {hubMode && (
              <div className={styles.runtimeRecovery}>
                <Divider />
                <strong>{t("account.runtimeTitle")}</strong>
                <p>{t("account.runtimeDescription")}</p>
                <Popconfirm
                  title={t("account.runtimeRestartConfirmTitle")}
                  description={t("account.runtimeRestartConfirmDescription")}
                  onConfirm={handleRestartRuntime}
                  okText={t("account.runtimeRestart")}
                  cancelText={t("common.cancel")}
                >
                  <Button
                    icon={<RotateCw size={16} />}
                    loading={runtimeRestarting}
                    block
                  >
                    {t("account.runtimeRestart")}
                  </Button>
                </Popconfirm>
              </div>
            )}
          </Form>
        </Modal>
      </Sider>
    </DockableSidebar>
  );
}
