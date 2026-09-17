/**
 * NotificationCenter.tsx — macOS-style notifications for the Desktop OS.
 *
 * Renders two things:
 *   1. Transient banners (toasts) that slide in at the top-right and auto
 *      dismiss. Clicking one opens the Inbox window on the matching tab.
 *   2. A slide-in Notification Center panel (toggled from the menu-bar bell)
 *      listing the full notification history with a clear-all action.
 */
import { useEffect, useState, type MouseEvent } from "react";
import { useTranslation } from "react-i18next";
import { App } from "antd";
import { ShieldAlert, Inbox, Bell, X, Trash2 } from "lucide-react";
import { useOsWindows } from "./osWindowStore";
import { STORE_APP } from "./osApps";
import { commandsApi } from "../api/modules/commands";
import {
  useOsNotify,
  type OsNotifyItem,
  type NotifyKind,
} from "./osNotifyStore";
import { useOsStyles, ACCENT } from "./useOsStyles";
import { buttonRoleProps } from "./a11y";

const INBOX_ROUTE = "core.inbox";
const INBOX_TAB_KEY = "qwenpaw.inbox.activeTab";
const TOAST_TTL_MS = 6000;

function KindIcon({ kind, size = 18 }: { kind: NotifyKind; size?: number }) {
  return kind === "approval" ? (
    <ShieldAlert size={size} color={ACCENT} />
  ) : (
    <Inbox size={size} color="#eab308" />
  );
}

function formatTime(ms: number): string {
  return new Date(ms).toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Open the Inbox window on the tab that matches the notification kind. */
function useOpenInbox() {
  const open = useOsWindows((s) => s.open);
  return (kind: NotifyKind) => {
    try {
      window.localStorage.setItem(
        INBOX_TAB_KEY,
        kind === "approval" ? "approvals" : "messages",
      );
    } catch {
      /* storage unavailable — Inbox falls back to its default tab */
    }
    if (INBOX_ROUTE === STORE_APP.routeId) return; // guard (never true)
    // Geometry comes from the app registry manifest, like every entry point.
    open(INBOX_ROUTE);
  };
}

/** Quick approve/deny buttons shown on approval notifications so the user
 *  can act without opening the Inbox. Full detail stays in the Inbox tab. */
function ApprovalActions({ item }: { item: OsNotifyItem }) {
  const { styles } = useOsStyles();
  const { t } = useTranslation();
  const { message } = App.useApp();
  const dismissItem = useOsNotify((s) => s.dismissItem);
  const [busy, setBusy] = useState(false);

  const act = async (action: "approve" | "deny", e: MouseEvent) => {
    e.stopPropagation();
    if (busy || !item.requestId) return;
    setBusy(true);
    try {
      await commandsApi.sendApprovalCommand(
        action,
        item.requestId,
        item.rootSessionId || "",
      );
      // Only drop the notification once the backend accepted the command —
      // the approval is still pending otherwise and must stay actionable.
      dismissItem(item.id);
    } catch (err) {
      message.error(
        err instanceof Error
          ? err.message
          : t("os.approvalActionFailed", "Action failed, please retry"),
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={styles.notifyActions} onClick={(e) => e.stopPropagation()}>
      <button
        className={styles.notifyDenyBtn}
        disabled={busy}
        onClick={(e) => act("deny", e)}
      >
        {t("approval.deny", "Deny")}
      </button>
      <button
        className={styles.notifyApproveBtn}
        disabled={busy}
        onClick={(e) => act("approve", e)}
      >
        {t("approval.approve", "Approve")}
      </button>
    </div>
  );
}

function Toast({ item }: { item: OsNotifyItem }) {
  const { styles, cx } = useOsStyles();
  const { t } = useTranslation();
  const dismiss = useOsNotify((s) => s.dismissToast);
  const openInbox = useOpenInbox();

  useEffect(() => {
    // Approval banners persist until acted on (or resolved elsewhere and
    // pruned by the store); informational banners auto-dismiss.
    if (item.kind === "approval") return;
    const timer = window.setTimeout(() => dismiss(item.id), TOAST_TTL_MS);
    return () => window.clearTimeout(timer);
  }, [item.id, item.kind, dismiss]);

  return (
    <div
      className={cx(styles.toast, styles.toastEnter)}
      role="status"
      aria-live="polite"
      onClick={() => {
        openInbox(item.kind);
        dismiss(item.id);
      }}
    >
      <div className={styles.toastIcon}>
        <KindIcon kind={item.kind} />
      </div>
      <div className={styles.toastBody}>
        <div className={styles.toastTitle}>{item.title}</div>
        <div className={styles.toastText}>{item.body}</div>
        <div className={styles.toastMeta}>
          {item.kind === "approval"
            ? t("os.notifyApproval", "Approval")
            : t("os.notifyInbox", "Inbox")}
          {" · "}
          {formatTime(item.createdAt)}
        </div>
        {item.kind === "approval" && item.requestId && (
          <ApprovalActions item={item} />
        )}
      </div>
      <button
        className={styles.toastClose}
        title={t("common.close", "Close")}
        aria-label={t("common.close", "Close")}
        onClick={(e) => {
          e.stopPropagation();
          dismiss(item.id);
        }}
      >
        <X size={14} />
      </button>
    </div>
  );
}

export default function NotificationCenter() {
  const { styles } = useOsStyles();
  const { t } = useTranslation();
  const { toasts, history, centerOpen, setCenter, clearHistory } =
    useOsNotify();
  const openInbox = useOpenInbox();

  return (
    <>
      {/* Transient banners */}
      <div className={styles.toastStack}>
        {toasts.map((item) => (
          <Toast key={item.id} item={item} />
        ))}
      </div>

      {/* Notification Center panel */}
      {centerOpen && (
        <div
          className={styles.ncPanel}
          role="dialog"
          aria-modal="false"
          aria-label={t("os.notifications", "Notifications")}
        >
          <div className={styles.ncHeader}>
            <span className={styles.ncTitle}>
              <Bell size={15} />
              {t("os.notifications", "Notifications")}
            </span>
            <span style={{ display: "flex", gap: 6 }}>
              <button
                className={styles.ncIconBtn}
                title={t("os.clearAll", "Clear all")}
                aria-label={t("os.clearAll", "Clear all")}
                onClick={clearHistory}
              >
                <Trash2 size={15} />
              </button>
              <button
                className={styles.ncIconBtn}
                title={t("common.close", "Close")}
                aria-label={t("common.close", "Close")}
                onClick={() => setCenter(false)}
              >
                <X size={16} />
              </button>
            </span>
          </div>

          <div className={styles.ncList}>
            {history.length === 0 ? (
              <div className={styles.ncEmpty}>
                <Bell size={30} strokeWidth={1.4} />
                <div>{t("os.noNotifications", "No notifications")}</div>
              </div>
            ) : (
              history.map((item) => (
                <div
                  key={item.id}
                  className={styles.ncItem}
                  onClick={() => {
                    openInbox(item.kind);
                    setCenter(false);
                  }}
                  {...buttonRoleProps(() => {
                    openInbox(item.kind);
                    setCenter(false);
                  }, item.title)}
                >
                  <div className={styles.ncItemIcon}>
                    <KindIcon kind={item.kind} size={16} />
                  </div>
                  <div className={styles.ncItemBody}>
                    <div className={styles.ncItemTitle}>{item.title}</div>
                    <div className={styles.ncItemText}>{item.body}</div>
                    {item.kind === "approval" && item.requestId && (
                      <ApprovalActions item={item} />
                    )}
                  </div>
                  <span className={styles.ncItemTime}>
                    {formatTime(item.createdAt)}
                  </span>
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </>
  );
}
