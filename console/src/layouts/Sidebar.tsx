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
  History,
  RotateCw,
  Settings,
  ShieldCheck,
  SquarePen,
} from "lucide-react";
import { useAppMessage } from "../hooks/useAppMessage";
import AgentSelector from "../components/AgentSelector";
import {
  SparkExitFullscreenLine,
  SparkSearchUserLine,
  SparkMenuExpandLine,
  SparkMenuFoldLine,
  SparkEmailLine,
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
import { buildChatPath } from "../utils/sessionRoute";
import { getOsRootHref } from "../utils/navigationMode";
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
import type { ReactNode } from "react";
import { hubApi } from "../api/modules/hub";

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
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const { isDark } = useTheme();
  const [authEnabled, setAuthEnabled] = useState(false);
  const [hubAdmin, setHubAdmin] = useState(false);
  const [hubUsername, setHubUsername] = useState("");
  const [accountModalOpen, setAccountModalOpen] = useState(false);
  const [accountLoading, setAccountLoading] = useState(false);
  const [runtimeRestarting, setRuntimeRestarting] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [version, setVersion] = useState("");
  const [accountForm] = Form.useForm();
  // Start collapsed on mobile so the first paint does not overlay/obscure
  // the main content on narrow viewports.
  const [collapsed, setCollapsed] = useState(isMobileSidebarViewport);
  const [isMobile, setIsMobile] = useState(isMobileSidebarViewport);
  const navScrollRef = useRef<HTMLDivElement>(null);
  const [hasUnreadMessages, setHasUnreadMessages] = useState(false);
  const [hasPendingApprovals, setHasPendingApprovals] = useState(false);
  const [shakeInbox, setShakeInbox] = useState(false);
  const [wobbleEnabled] = useInboxWobble();
  const currentApprovalIdsRef = useRef<Set<string>>(new Set());
  const seenApprovalIdsRef = useRef<Set<string>>(new Set());

  // The legacy store name is retained for persisted-data compatibility. The
  // user-facing UI now exposes one sidebar with configurable visibility.
  const { focusItemIds, hiddenPluginItemIds } = useSidebarModeStore();
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
  }, [agentMenu, focusItemIds, routes, selectedSettingsMenu]);
  const simpleInboxEntry = selectedFlatNav.find(
    (entry) => entry.key === "core.inbox",
  );
  const simpleMarketplaceEntry = selectedFlatNav.find(
    (entry) => entry.key === "core.marketplace",
  );
  const visibleSidebarNav = useMemo(
    () =>
      selectedFlatNav.filter(
        (entry) =>
          entry.key !== "core.inbox" && entry.key !== "core.marketplace",
      ),
    [selectedFlatNav],
  );
  // ── Effects ──────────────────────────────────────────────────────────────

  useEffect(() => {
    const activeEntry = navScrollRef.current?.querySelector<HTMLElement>(
      '[aria-current="page"]',
    );
    activeEntry?.scrollIntoView?.({ block: "nearest" });
  }, [selectedKey, visibleSidebarNav]);

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

  const collapsedNavItems = useMemo(() => {
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
    const scrollableEntries = [
      ...flattenMenu(agentMenu, routes, 18),
      ...flattenMenu(selectedSettingsMenu, routes, 18),
    ];
    const inboxEntry = scrollableEntries.find(
      (entry) => entry.key === "core.inbox",
    );
    const marketplaceEntry = scrollableEntries.find(
      (entry) => entry.key === "core.marketplace",
    );
    const orderedEntries = orderSidebarEntries(
      scrollableEntries.filter(
        (entry) =>
          entry.key !== "core.inbox" && entry.key !== "core.marketplace",
      ),
      focusItemIds,
    );
    const flat = [
      ...(inboxEntry ? [inboxEntry] : []),
      ...(marketplaceEntry ? [marketplaceEntry] : []),
      ...orderedEntries,
    ];
    return flat.map((entry) =>
      entry.key === "core.inbox"
        ? { ...entry, icon: decorateInboxIcon(entry.icon) }
        : entry,
    );
  }, [
    agentMenu,
    focusItemIds,
    selectedSettingsMenu,
    routes,
    hasInboxUnread,
    inboxDotColor,
  ]);

  // ── Handlers ──────────────────────────────────────────────────────────────

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
          type="button"
          aria-label={typeof item.label === "string" ? item.label : undefined}
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
  };

  const renderSimpleNavItem = (entry: FlatMenuEntry) => {
    const isActive = selectedKey === entry.key;
    return (
      <button
        key={entry.key}
        type="button"
        aria-current={isActive ? "page" : undefined}
        className={`${styles.simpleNavItem} ${
          isActive ? styles.simpleNavItemActive : ""
        }`}
        onClick={() => {
          if (entry.href) {
            window.open(entry.href, "_blank", "noopener,noreferrer");
          } else {
            navigate(entry.path);
          }
        }}
      >
        {entry.icon}
        <span>{entry.label}</span>
      </button>
    );
  };

  // The expanded sidebar uses the same content on desktop and mobile.
  const siderWidth = collapsed ? (isMobile ? 56 : 72) : 280;

  return (
    <Sider
      width={siderWidth}
      className={`${styles.sider}${
        collapsed ? ` ${styles.siderCollapsed}` : ""
      }${isDark ? ` ${styles.siderDark}` : ""}${
        !collapsed ? ` ${styles.siderSimple}` : ""
      }`}
    >
      {collapsed ? (
        <nav className={styles.collapsedNav}>
          <div className={styles.collapsedNavPinned}>
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
                <SquarePen size={18} />
              </button>
            </Tooltip>
            <Tooltip
              title={t("chat.chatHistoryTooltip")}
              placement="right"
              mouseEnterDelay={0.5}
            >
              <button
                type="button"
                className={styles.collapsedNavItem}
                aria-label={t("chat.chatHistoryTooltip")}
                onClick={() => setCollapsed(false)}
              >
                <History size={18} />
              </button>
            </Tooltip>
          </div>
          <div className={styles.collapsedNavScroll}>
            {collapsedNavItems.map(renderCollapsedNavItem)}
          </div>
        </nav>
      ) : (
        <>
          {/* Unified sidebar: selected shortcuts and sessions. */}
          <div
            className={`${styles.agentScopedSection} ${styles.simpleAgentPanel}`}
          >
            <div className={styles.agentSelectorContainer}>
              <AgentSelector collapsed={collapsed} />
            </div>
            <Slot name="sider.top" kind="fill" />
            <button
              type="button"
              className={styles.simpleNewTask}
              onClick={handleNewChat}
            >
              <SquarePen size={16} />
              <span>{t("chat.newTask", "New task")}</span>
            </button>
            <div
              ref={navScrollRef}
              className={`${styles.simpleNavItems} ${styles.simpleNavScroll}`}
            >
              {simpleInboxEntry && (
                <button
                  type="button"
                  aria-current={
                    selectedKey === simpleInboxEntry.key ? "page" : undefined
                  }
                  className={`${styles.simpleNavItem} ${
                    styles.simpleInboxItem
                  } ${
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
              {simpleMarketplaceEntry &&
                renderSimpleNavItem(simpleMarketplaceEntry)}
              {visibleSidebarNav.map(renderSimpleNavItem)}
            </div>
            <button
              type="button"
              className={styles.simpleMoreSettings}
              onClick={handleOpenSettings}
            >
              <Settings size={16} />
              <span>{t("nav.moreSettings", "More settings")}</span>
            </button>
          </div>

          {/* Session list — fills the primary space. */}
          <div className={styles.simpleSessionArea}>
            <SidebarSessionList
              onNewChat={handleNewChat}
              onSessionClick={handleSidebarSessionClick}
            />
          </div>
          <Slot name="sider.bottom" kind="fill" />
        </>
      )}

      {authEnabled && !collapsed && (
        <div className={styles.authActions}>
          {hubAdmin && (
            <Button
              type="text"
              icon={<ShieldCheck size={16} />}
              onClick={() => navigate("/hub/admin")}
              block
              className={styles.authBtn}
            >
              {t("hub.brand.title")}
            </Button>
          )}
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
            />
          }
        >
          <Button
            type="text"
            title={t("nav.moreSettings", "More settings")}
            aria-label={t("nav.moreSettings", "More settings")}
            icon={<Settings size={18} />}
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
  );
}
