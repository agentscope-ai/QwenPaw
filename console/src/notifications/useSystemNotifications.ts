import { useCallback, useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { listen } from "@tauri-apps/api/event";
import { isDesktopApp } from "../tauri/backendRuntime";
import { configureDesktopSystemNotifications } from "../tauri/consoleNotifications";
import { useNotificationPreferences } from "./preferences";
import { BrowserEventNotifier } from "./browserEvents";
import {
  notificationEventPath,
  type SystemNotificationEvent,
} from "./notificationEvents";

export function useSystemNotifications(openPath: (path: string) => void) {
  const { t } = useTranslation();
  const preferences = useNotificationPreferences();
  const latest = useRef({ t, openPath });
  latest.current = { t, openPath };
  const notifier = useRef<BrowserEventNotifier>();

  useEffect(() => {
    const browser = new BrowserEventNotifier(
      () => latest.current.t("systemNotifications.conversationComplete"),
      (event) => latest.current.openPath(notificationEventPath(event)),
    );
    notifier.current = browser;
    return () => browser.dispose();
  }, []);

  useEffect(() => {
    if (!preferences.enabled) notifier.current?.closeAll();
    if (!isDesktopApp()) return;
    void configureDesktopSystemNotifications(
      preferences,
      t("systemNotifications.conversationComplete"),
    ).catch((error: unknown) =>
      console.warn("Could not configure system notifications", error),
    );
  }, [preferences, t]);

  useEffect(() => {
    if (!isDesktopApp()) return;
    let disposed = false;
    let unlisten: (() => void) | undefined;
    void listen<SystemNotificationEvent>(
      "qwenpaw:open-notification",
      ({ payload }) => {
        latest.current.openPath(notificationEventPath(payload));
      },
    )
      .then((cleanup) => {
        if (disposed) cleanup();
        else unlisten = cleanup;
      })
      .catch(console.warn);
    return () => {
      disposed = true;
      unlisten?.();
    };
  }, []);

  return useCallback((events: SystemNotificationEvent[]) => {
    if (!isDesktopApp()) notifier.current?.update(events);
  }, []);
}
