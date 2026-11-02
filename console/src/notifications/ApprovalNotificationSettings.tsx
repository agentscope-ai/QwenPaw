import { useEffect, useRef, useState } from "react";
import { message, Switch } from "antd";
import { BellRing } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  getDesktopNotificationPermission,
  requestDesktopNotificationPermission,
} from "../tauri/consoleNotifications";
import { isDesktopApp } from "../tauri/backendRuntime";
import {
  getNotificationPermission,
  setNotificationsEnabled,
  useApprovalNotificationsEnabled,
} from "./preferences";
import styles from "./ApprovalNotificationSettings.module.less";

export default function ApprovalNotificationSettings() {
  const { t } = useTranslation();
  const enabled = useApprovalNotificationsEnabled();
  const desktop = isDesktopApp();
  const [permission, setPermission] = useState(getNotificationPermission);
  const [busy, setBusy] = useState(false);
  const requesting = useRef(false);
  const permissionRevision = useRef(0);
  const available = permission === "granted" || permission === "native";
  const unsupported = [
    "unsupported",
    "insecure",
    "checking",
    "unavailable",
  ].includes(permission);
  const permissionLabel =
    desktop && ["default", "granted", "denied"].includes(permission)
      ? `native${permission[0].toUpperCase()}${permission.slice(1)}`
      : permission;

  useEffect(() => {
    let disposed = false;
    const refresh = async () => {
      if (requesting.current) return;
      const revision = ++permissionRevision.current;
      try {
        const result = desktop
          ? await getDesktopNotificationPermission()
          : getNotificationPermission();
        if (!disposed && revision === permissionRevision.current)
          setPermission(result);
      } catch {
        if (!disposed && revision === permissionRevision.current)
          setPermission("unavailable");
      }
    };
    const onFocus = () => void refresh();
    onFocus();
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onFocus);
    return () => {
      disposed = true;
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onFocus);
    };
  }, [desktop]);

  const toggle = async (checked: boolean) => {
    if (!checked) {
      setNotificationsEnabled(false);
      return;
    }
    setBusy(true);
    requesting.current = true;
    ++permissionRevision.current;
    try {
      const result = desktop
        ? await requestDesktopNotificationPermission()
        : permission === "default"
        ? await Notification.requestPermission()
        : getNotificationPermission();
      setPermission(result);
      setNotificationsEnabled(result === "granted" || result === "native");
    } catch {
      message.error(t("approvalNotifications.failed"));
    } finally {
      requesting.current = false;
      setBusy(false);
    }
  };

  return (
    <section
      className={styles.setting}
      aria-label={t("approvalNotifications.settingTitle")}
    >
      <div className={styles.icon} aria-hidden="true">
        <BellRing size={20} strokeWidth={1.5} />
      </div>
      <div className={styles.copy}>
        <div className={styles.heading}>
          <span>{t("approvalNotifications.settingTitle")}</span>
          <span className={styles.status} aria-live="polite">
            {t(`approvalNotifications.permission.${permissionLabel}`)}
          </span>
        </div>
        <p>{t("approvalNotifications.description")}</p>
      </div>
      <div className={styles.actions}>
        <Switch
          checked={enabled && available}
          loading={busy || permission === "checking"}
          disabled={unsupported || permission === "denied"}
          aria-label={t("approvalNotifications.settingTitle")}
          onChange={(checked) => void toggle(checked)}
        />
      </div>
    </section>
  );
}
