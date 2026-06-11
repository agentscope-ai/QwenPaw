import { useState, useEffect, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { useAppMessage } from "../hooks/useAppMessage";
import AgentSelector from "../components/AgentSelector";
import {
  MessageSquare,
  Minimize2,
  UserSearch,
  PanelLeftOpen,
  PanelLeftClose,
  Mail,
} from "lucide-react";
import { clearAuthToken } from "../api/config";
import { authApi } from "../api/modules/auth";
import api from "../api";
import { useCodingMode } from "../stores/codingModeStore";
import { useMenuItems, useRoutes } from "../plugins/registry/hooks";
import { Slot } from "../plugins/registry/Slot";
import {
  deriveOpenKeys,
  flattenMenu,
  renderIcon,
  routeIdToPath,
} from "./registry/adapter";
import type { FlatMenuEntry } from "./registry/adapter";
import type { MenuItem } from "../plugins/registry/types";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { ScrollArea } from "@/components/ui/scroll-area";

// ── Constants ─────────────────────────────────────────────────────────────

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
}

// ── Account form state ────────────────────────────────────────────────────

interface AccountFormValues {
  currentPassword: string;
  newUsername: string;
  newPassword: string;
  confirmPassword: string;
}

function emptyAccount(): AccountFormValues {
  return {
    currentPassword: "",
    newUsername: "",
    newPassword: "",
    confirmPassword: "",
  };
}

// ── NavItem (leaf menu item) ──────────────────────────────────────────────

// ── ExpandedMenu (renders group label + children) ─────────────────────────

interface ExpandedMenuProps {
  items: MenuItem[];
  selectedKey: string;
  onItemClick: (item: MenuItem) => void;
}

function ExpandedMenu({ items, selectedKey, onItemClick }: ExpandedMenuProps) {
  const visibleItems = items.filter((i) => i.visible?.() !== false);

  return (
    <div className="flex flex-col gap-0.5">
      {visibleItems.map((rawItem) => {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const item = rawItem as any;
        const children: MenuItem[] = item.__children ?? [];
        const isGroup = item.isGroup || children.length > 0;

        if (isGroup) {
          const visibleChildren = children.filter(
            (c: MenuItem) => c.visible?.() !== false,
          );
          return (
            <div key={item.id} className="mb-1">
              {/* Group label */}
              <div className="px-2 py-1 text-[11px] font-medium text-foreground/25 tracking-wide uppercase leading-8">
                {typeof item.label === "function" ? item.label() : item.label}
              </div>
              {/* Group children */}
              <div className="flex flex-col gap-0.5">
                {visibleChildren.map((child: MenuItem) => {
                  const isActive = selectedKey === child.id;
                  return (
                    <button
                      key={child.id}
                      className={cn(
                        "flex items-center gap-2.5 w-full h-10 px-2 rounded-lg border-none bg-transparent text-sm cursor-pointer transition-colors text-left",
                        "text-foreground/70 hover:bg-accent",
                        isActive && "!bg-accent !text-foreground",
                      )}
                      onClick={() => onItemClick(child)}
                    >
                      {renderIcon(child.icon, 16)}
                      <span className="truncate">
                        {typeof child.label === "function"
                          ? child.label()
                          : child.label}
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>
          );
        }

        // Leaf
        const isActive = selectedKey === item.id;
        return (
          <button
            key={item.id}
            className={cn(
              "flex items-center gap-2.5 w-full h-10 px-2 rounded-lg border-none bg-transparent text-sm cursor-pointer transition-colors text-left",
              "text-foreground/70 hover:bg-accent",
              isActive && "!bg-accent !text-foreground",
            )}
            onClick={() => onItemClick(item)}
          >
            {renderIcon(item.icon, 16)}
            <span className="truncate">
              {typeof item.label === "function" ? item.label() : item.label}
            </span>
          </button>
        );
      })}
    </div>
  );
}

// ── Sidebar ───────────────────────────────────────────────────────────────

export default function Sidebar({ selectedKey }: SidebarProps) {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const { codingMode } = useCodingMode();
  const chatPath = codingMode ? "/coding" : "/chat";
  const [authEnabled, setAuthEnabled] = useState(false);
  const [accountModalOpen, setAccountModalOpen] = useState(false);
  const [accountLoading, setAccountLoading] = useState(false);
  const [accountForm, setAccountForm] =
    useState<AccountFormValues>(emptyAccount);
  const [accountErrors, setAccountErrors] = useState<
    Partial<AccountFormValues>
  >({});
  const [collapsed, setCollapsed] = useState(false);
  const [isMobile, setIsMobile] = useState(isMobileSidebarViewport);
  const [hasInboxUnread, setHasInboxUnread] = useState(false);

  // Menu + route snapshots from registry (builtin + plugin registrations merged).
  const agentMenu = useMenuItems("primary.agentScoped");
  const settingsMenu = useMenuItems("primary.settings");
  const routes = useRoutes();

  // ── Effects ──────────────────────────────────────────────────────────────

  useEffect(() => {
    authApi
      .getStatus()
      .then((res) => setAuthEnabled(res.enabled))
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
      if (mediaQuery.matches) {
        setCollapsed(true);
      }
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
        const hasPendingApprovals =
          (pushRes?.pending_approvals?.length || 0) > 0;
        setHasInboxUnread(hasUnreadEvents || hasPendingApprovals);
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

  // ── Handlers ──────────────────────────────────────────────────────────────

  const handleMenuItemClick = (item: MenuItem) => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const cast = item as any;
    if (cast.href) {
      window.open(cast.href, "_blank", "noopener,noreferrer");
      return;
    }
    const path = routeIdToPath(item.route, routes);
    if (path) navigate(path);
  };

  const handleUpdateProfile = async () => {
    const trimmedUsername = accountForm.newUsername?.trim() || undefined;
    const trimmedPassword = accountForm.newPassword?.trim() || undefined;
    const errors: Partial<AccountFormValues> = {};

    if (!accountForm.currentPassword) {
      errors.currentPassword = t("account.currentPasswordRequired");
    }
    if (accountForm.newPassword && !trimmedPassword) {
      errors.newPassword = t("account.passwordEmpty");
    }
    if (accountForm.newUsername && !trimmedUsername) {
      errors.newUsername = t("account.usernameEmpty");
    }
    if (
      accountForm.newPassword &&
      accountForm.confirmPassword !== accountForm.newPassword
    ) {
      errors.confirmPassword = t("account.passwordMismatch");
    }

    setAccountErrors(errors);
    if (Object.keys(errors).length > 0) return;

    if (!trimmedUsername && !trimmedPassword) {
      message.warning(t("account.nothingToUpdate"));
      return;
    }

    setAccountLoading(true);
    try {
      await authApi.updateProfile(
        accountForm.currentPassword,
        trimmedUsername,
        trimmedPassword,
      );
      toast.success(t("account.updateSuccess"));
      setAccountModalOpen(false);
      setAccountForm(emptyAccount());
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
      toast.error(msg);
    } finally {
      setAccountLoading(false);
    }
  };

  // ── Collapsed nav items ──────────────────────────────────────────────────

  const collapsedNavItems = useMemo(() => {
    const stickyChat: FlatMenuEntry = {
      key: "core.chat",
      icon: <MessageSquare size={18} />,
      path: chatPath,
      label: t("nav.chat"),
    };

    const flat = [
      stickyChat,
      ...flattenMenu(agentMenu, routes, 18),
      ...flattenMenu(settingsMenu, routes, 18),
    ];

    return flat.map((entry) => {
      if (entry.key !== "core.inbox") return entry;
      return {
        ...entry,
        icon: (
          <span className="relative inline-flex">
            {entry.icon ?? <Mail size={18} />}
            {hasInboxUnread && (
              <span className="absolute -top-0.5 -right-0.5 w-1.5 h-1.5 rounded-full bg-primary" />
            )}
          </span>
        ),
      };
    });
  }, [agentMenu, settingsMenu, routes, chatPath, t, hasInboxUnread]);

  // ── Sizes ────────────────────────────────────────────────────────────────

  const siderWidth = collapsed ? (isMobile ? 56 : 72) : 240;
  const isChatActive =
    selectedKey === "core.chat" || selectedKey === "core.coding";

  // `renderIcon` retained for tree-shaking awareness.
  void renderIcon;
  // deriveOpenKeys retained for future use.
  void deriveOpenKeys;

  return (
    <aside
      style={{ width: siderWidth }}
      className={cn(
        "flex flex-col shrink-0 h-full transition-[width] duration-200 border-r border-border",
        "bg-sidebar border-sidebar-border",
        collapsed ? "px-2" : "px-4",
      )}
    >
      {collapsed ? (
        /* ── COLLAPSED (icon-only) ── */
        <ScrollArea className="flex-1">
          <nav className="flex flex-col items-center gap-1 py-1">
            {collapsedNavItems.map((item) => {
              const isActive =
                item.key === "core.chat"
                  ? isChatActive
                  : selectedKey === item.key;
              return (
                <Tooltip key={item.key}>
                  <TooltipTrigger asChild>
                    <button
                      className={cn(
                        "w-10 h-10 flex items-center justify-center rounded-[10px] border-none bg-transparent cursor-pointer transition-all",
                        "text-foreground/55 hover:bg-accent hover:text-foreground/88",
                        isActive && "!bg-accent !text-foreground/88",
                        isMobile && "w-9 h-9 rounded-lg",
                      )}
                      onClick={() =>
                        item.href
                          ? window.open(
                              item.href,
                              "_blank",
                              "noopener,noreferrer",
                            )
                          : navigate(item.path)
                      }
                    >
                      {item.icon}
                    </button>
                  </TooltipTrigger>
                  <TooltipContent side="right">{item.label}</TooltipContent>
                </Tooltip>
              );
            })}
          </nav>
        </ScrollArea>
      ) : (
        /* ── EXPANDED ── */
        <ScrollArea className="flex-1">
          <div className="flex flex-col gap-1 py-2">
            {/* Agent-scoped section */}
            <div className="bg-muted/50 border border-border rounded-xl p-1 mb-1">
              {/* Sticky agent selector + chat button */}
              <div className="sticky top-0 z-10 bg-muted rounded-[12px_12px_0_0] mb-1">
                <AgentSelector collapsed={collapsed} />
                {/* Sticky Chat button */}
                <button
                  className={cn(
                    "flex items-center gap-2.5 w-full h-10 px-3 rounded-lg border-none bg-transparent text-sm cursor-pointer transition-colors text-left",
                    "text-foreground/88 hover:bg-accent",
                    isChatActive && "!bg-accent !text-foreground",
                  )}
                  onClick={() => navigate(chatPath)}
                >
                  <MessageSquare size={16} />
                  <span>{t("nav.chat")}</span>
                  {hasInboxUnread && (
                    <span
                      className="ml-1 w-1.5 h-1.5 rounded-full bg-primary"
                      style={{ marginTop: 1 }}
                    />
                  )}
                </button>
              </div>

              <Slot name="sider.top" kind="fill" />

              {/* Agent-scoped menu */}
              <ExpandedMenu
                items={agentMenu}
                selectedKey={selectedKey}
                onItemClick={handleMenuItemClick}
              />
            </div>

            {/* Settings menu */}
            <ExpandedMenu
              items={settingsMenu}
              selectedKey={selectedKey}
              onItemClick={handleMenuItemClick}
            />

            <Slot name="sider.bottom" kind="fill" />
          </div>
        </ScrollArea>
      )}

      {/* Auth actions (account + logout) */}
      {authEnabled && !collapsed && (
        <div className="px-4 py-3 border-t border-border flex flex-col gap-1">
          <button
            className={cn(
              "flex items-center gap-2 w-full px-2 py-1.5 rounded-lg text-sm text-foreground/65 bg-transparent border-none cursor-pointer text-left transition-colors",
              "hover:text-foreground/88 hover:bg-accent",
            )}
            onClick={() => {
              setAccountForm(emptyAccount());
              setAccountErrors({});
              setAccountModalOpen(true);
            }}
          >
            <UserSearch size={16} />
            {t("account.title")}
          </button>
          <button
            className={cn(
              "flex items-center gap-2 w-full px-2 py-1.5 rounded-lg text-sm text-foreground/65 bg-transparent border-none cursor-pointer text-left transition-colors",
              "hover:text-foreground/88 hover:bg-accent",
            )}
            onClick={() => {
              clearAuthToken();
              window.location.href = "/login";
            }}
          >
            <Minimize2 size={16} />
            {t("login.logout")}
          </button>
        </div>
      )}

      {/* Collapse toggle */}
      <div
        className={cn(
          "shrink-0 z-10 flex items-center py-2 border-t border-border",
          collapsed ? "justify-center" : "justify-end",
        )}
      >
        <button
          className={cn(
            "p-1.5 rounded-lg text-foreground/45 bg-transparent border-none cursor-pointer transition-all",
            "hover:bg-accent hover:text-foreground",
          )}
          onClick={() => setCollapsed(!collapsed)}
        >
          {collapsed ? (
            <PanelLeftOpen size={20} />
          ) : (
            <PanelLeftClose size={20} />
          )}
        </button>
      </div>

      {/* Account modal */}
      <Dialog
        open={accountModalOpen}
        onOpenChange={(open) => {
          setAccountModalOpen(open);
          if (!open) setAccountErrors({});
        }}
      >
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{t("account.title")}</DialogTitle>
            <DialogDescription className="sr-only">
              {t("account.description", "Update your username or password.")}
            </DialogDescription>
          </DialogHeader>
          <form
            className="flex flex-col gap-4 pt-2"
            onSubmit={(e) => {
              e.preventDefault();
              void handleUpdateProfile();
            }}
          >
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="currentPassword">
                {t("account.currentPassword")}
                <span className="text-destructive ml-0.5">*</span>
              </Label>
              <Input
                id="currentPassword"
                type="password"
                value={accountForm.currentPassword}
                onChange={(e) =>
                  setAccountForm((f) => ({
                    ...f,
                    currentPassword: e.target.value,
                  }))
                }
              />
              {accountErrors.currentPassword && (
                <p className="text-[12px] text-destructive">
                  {accountErrors.currentPassword}
                </p>
              )}
            </div>

            <div className="flex flex-col gap-1.5">
              <Label htmlFor="newUsername">{t("account.newUsername")}</Label>
              <Input
                id="newUsername"
                type="text"
                placeholder={t("account.newUsernamePlaceholder")}
                value={accountForm.newUsername}
                onChange={(e) =>
                  setAccountForm((f) => ({ ...f, newUsername: e.target.value }))
                }
              />
              {accountErrors.newUsername && (
                <p className="text-[12px] text-destructive">
                  {accountErrors.newUsername}
                </p>
              )}
            </div>

            <div className="flex flex-col gap-1.5">
              <Label htmlFor="newPassword">{t("account.newPassword")}</Label>
              <Input
                id="newPassword"
                type="password"
                placeholder={t("account.newPasswordPlaceholder")}
                value={accountForm.newPassword}
                onChange={(e) =>
                  setAccountForm((f) => ({ ...f, newPassword: e.target.value }))
                }
              />
              {accountErrors.newPassword && (
                <p className="text-[12px] text-destructive">
                  {accountErrors.newPassword}
                </p>
              )}
            </div>

            <div className="flex flex-col gap-1.5">
              <Label htmlFor="confirmPassword">
                {t("account.confirmPassword")}
              </Label>
              <Input
                id="confirmPassword"
                type="password"
                placeholder={t("account.confirmPasswordPlaceholder")}
                value={accountForm.confirmPassword}
                onChange={(e) =>
                  setAccountForm((f) => ({
                    ...f,
                    confirmPassword: e.target.value,
                  }))
                }
              />
              {accountErrors.confirmPassword && (
                <p className="text-[12px] text-destructive">
                  {accountErrors.confirmPassword}
                </p>
              )}
            </div>

            <Button
              type="submit"
              className="w-full bg-primary text-primary-foreground hover:bg-primary/90"
              disabled={accountLoading}
            >
              {accountLoading ? (
                <span className="flex items-center gap-2">
                  <span className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
                  {t("account.save")}
                </span>
              ) : (
                t("account.save")
              )}
            </Button>
          </form>
        </DialogContent>
      </Dialog>
    </aside>
  );
}
