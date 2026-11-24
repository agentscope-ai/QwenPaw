import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { App, Button, Popover, Select, Switch } from "antd";
import {
  Bell,
  CheckCheck,
  ShieldCheck,
  Inbox,
  Info,
  ChevronDown,
  Square,
  SquareCheck,
  ArrowUpRight,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { isDesktopApp } from "../tauri/backendRuntime";
import {
  getDesktopNotificationPermission,
  requestDesktopNotificationPermission,
  openSystemNotificationSettings,
} from "../tauri/consoleNotifications";
import {
  getNotificationPermission,
  updateNotificationPreferences,
  useNotificationPreferences,
  type ConversationNotificationMode,
} from "./preferences";
import styles from "./NotificationSettings.module.less";

function SettingRow({
  icon,
  title,
  description,
  children,
}: {
  icon: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className={styles.row}>
      <span className={styles.icon} aria-hidden="true">
        {icon}
      </span>
      <div className={styles.copy}>
        <strong>{title}</strong>
        {description && <div className={styles.description}>{description}</div>}
      </div>
      <div className={styles.control}>{children}</div>
    </div>
  );
}

export default function NotificationSettings() {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const preferences = useNotificationPreferences();
  const permissionId = useId();
  const [helpOpen, setHelpOpen] = useState(false);
  const desktop = isDesktopApp();
  const [permission, setPermission] = useState(getNotificationPermission);
  const [busy, setBusy] = useState(false);
  const requesting = useRef(false);
  const revision = useRef(0);
  const mounted = useRef(true);
  const unavailable = [
    "unsupported",
    "insecure",
    "checking",
    "unavailable",
  ].includes(permission);
  const authorized = permission === "granted" || permission === "native";
  const categoriesDisabled = !preferences.enabled || !authorized;

  useEffect(() => {
    mounted.current = true;
    const refresh = async () => {
      if (requesting.current) return;
      const current = ++revision.current;
      try {
        const result = desktop
          ? await getDesktopNotificationPermission()
          : getNotificationPermission();
        if (mounted.current && current === revision.current)
          setPermission(result);
      } catch {
        if (mounted.current && current === revision.current)
          setPermission("unavailable");
      }
    };
    const onFocus = () => void refresh();
    onFocus();
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onFocus);
    return () => {
      mounted.current = false;
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onFocus);
    };
  }, [desktop]);

  const toggle = async (checked: boolean) => {
    if (!checked) {
      updateNotificationPreferences({ enabled: false });
      return;
    }
    requesting.current = true;
    ++revision.current;
    setBusy(true);
    try {
      const result = desktop
        ? await requestDesktopNotificationPermission()
        : permission === "default"
        ? await Notification.requestPermission()
        : getNotificationPermission();
      if (!mounted.current) return;
      setPermission(result);
      updateNotificationPreferences({
        enabled: result === "granted" || result === "native",
      });
    } catch {
      message.error(t("approvalNotifications.failed"));
    } finally {
      requesting.current = false;
      if (mounted.current) setBusy(false);
    }
  };

  const sources = ["cron", "heartbeat", "mail"] as const;
  const selectedSources = sources.filter((source) => preferences[source]);
  const backgroundSummary =
    selectedSources.length === sources.length
      ? t("systemNotifications.allEnabled")
      : t("systemNotifications.selectedCount", {
          count: selectedSources.length,
        });
  const modeOptions = ["off", "background", "always"].map((value) => ({
    value,
    label: t(`systemNotifications.mode.${value}`),
  }));
  let permissionMessage: string | undefined;
  if (permission === "denied") {
    permissionMessage = t(
      desktop
        ? "systemNotifications.systemBlocked"
        : "systemNotifications.browserBlocked",
    );
  } else if (unavailable && permission !== "checking") {
    permissionMessage = t(`approvalNotifications.permission.${permission}`);
  } else if (permission === "default" && preferences.enabled) {
    permissionMessage = t("systemNotifications.permissionRequired");
  }
  const permissionDescription = permissionMessage ? permissionId : undefined;
  const openSettings = () => {
    void openSystemNotificationSettings().catch(() =>
      message.error(t("systemNotifications.openFailed")),
    );
  };

  return (
    <section
      id="notifications"
      className={styles.section}
      aria-label={t("systemNotifications.heading")}
    >
      <h3>{t("systemNotifications.heading")}</h3>
      <div className={styles.card}>
        <SettingRow
          icon={<Bell size={20} />}
          title={
            <span className={styles.title}>
              {t("systemNotifications.enabled")}
              <Popover
                trigger="click"
                placement="bottom"
                open={helpOpen}
                onOpenChange={setHelpOpen}
                content={
                  <div className={styles.helpContent}>
                    <p>
                      {t(
                        desktop
                          ? "systemNotifications.systemSettingsDescription"
                          : "systemNotifications.browserHelp",
                      )}
                    </p>
                    {desktop && (
                      <Button
                        type="link"
                        icon={<ArrowUpRight size={15} />}
                        iconPosition="end"
                        onClick={openSettings}
                      >
                        {t("systemNotifications.openSettings")}
                      </Button>
                    )}
                  </div>
                }
              >
                <Button
                  type="text"
                  className={styles.helpButton}
                  aria-label={t("systemNotifications.help")}
                  aria-expanded={helpOpen}
                  icon={<Info size={16} />}
                  onKeyDown={(event) => {
                    if (event.key === "Escape") setHelpOpen(false);
                  }}
                />
              </Popover>
            </span>
          }
        >
          <Switch
            aria-label={t("systemNotifications.enabled")}
            aria-describedby={permissionDescription}
            checked={preferences.enabled}
            loading={busy || permission === "checking"}
            disabled={
              !preferences.enabled && (unavailable || permission === "denied")
            }
            onChange={(checked) => void toggle(checked)}
          />
        </SettingRow>
        {permissionMessage && (
          <div className={styles.permission}>
            <span role="status" id={permissionId}>
              {permissionMessage}
            </span>
            {permission === "denied" && (
              <Button
                type="link"
                onClick={desktop ? openSettings : () => setHelpOpen(true)}
              >
                {t(
                  desktop
                    ? "systemNotifications.allowInSettings"
                    : "systemNotifications.showBrowserHelp",
                )}
              </Button>
            )}
            {permission === "default" && (
              <Button
                type="link"
                loading={busy}
                onClick={() => void toggle(true)}
              >
                {t("systemNotifications.authorize")}
              </Button>
            )}
          </div>
        )}
        <div
          className={styles.categories}
          role="group"
          aria-label={t("systemNotifications.categories")}
          aria-describedby={permissionDescription}
          aria-disabled={categoriesDisabled}
        >
          <SettingRow
            icon={<ShieldCheck size={20} />}
            title={t("systemNotifications.approval")}
            description={t("systemNotifications.approvalDescription")}
          >
            <Select<ConversationNotificationMode>
              aria-label={t("systemNotifications.approval")}
              aria-describedby={permissionDescription}
              value={preferences.approval ? preferences.approvalTiming : "off"}
              disabled={categoriesDisabled}
              className={styles.mode}
              onChange={(mode) =>
                updateNotificationPreferences(
                  mode === "off"
                    ? { approval: false }
                    : { approval: true, approvalTiming: mode },
                )
              }
              options={modeOptions}
            />
          </SettingRow>
          <SettingRow
            icon={<CheckCheck size={20} />}
            title={t("systemNotifications.conversation")}
            description={t("systemNotifications.conversationDescription")}
          >
            <Select<ConversationNotificationMode>
              aria-label={t("systemNotifications.conversation")}
              aria-describedby={permissionDescription}
              value={preferences.conversation}
              disabled={categoriesDisabled}
              className={styles.mode}
              onChange={(conversation) =>
                updateNotificationPreferences({ conversation })
              }
              options={modeOptions}
            />
          </SettingRow>
          <SettingRow
            icon={<Inbox size={20} />}
            title={t("systemNotifications.background")}
            description={t("systemNotifications.backgroundDescription")}
          >
            <Select
              mode="multiple"
              aria-label={t("systemNotifications.background")}
              aria-describedby={permissionDescription}
              value={selectedSources}
              disabled={categoriesDisabled}
              className={`${styles.mode} ${styles.sources}`}
              showSearch={false}
              suffixIcon={<ChevronDown size={16} />}
              maxTagCount={0}
              maxTagPlaceholder={() => backgroundSummary}
              placeholder={t("systemNotifications.mode.off")}
              menuItemSelectedIcon={null}
              onChange={(values) =>
                updateNotificationPreferences({
                  cron: values.includes("cron"),
                  heartbeat: values.includes("heartbeat"),
                  mail: values.includes("mail"),
                })
              }
              options={sources.map((source) => ({
                value: source,
                label: t(`systemNotifications.${source}`),
              }))}
              optionRender={({ value, label }) => {
                const checked = selectedSources.includes(
                  value as (typeof sources)[number],
                );
                const Icon = checked ? SquareCheck : Square;
                return (
                  <span className={styles.sourceOption}>
                    <Icon
                      size={16}
                      aria-hidden="true"
                      data-selected={checked}
                    />
                    {label}
                  </span>
                );
              }}
            />
          </SettingRow>
        </div>
      </div>
    </section>
  );
}
