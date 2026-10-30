import { useCallback, useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { listen } from "@tauri-apps/api/event";
import type { PendingApproval } from "../api/modules/console";
import { isDesktopApp } from "../tauri/backendRuntime";
import { configureDesktopApprovalNotifications } from "../tauri/consoleNotifications";
import { BrowserApprovalNotifier } from "./browserApprovals";
import { useApprovalNotificationsEnabled } from "./preferences";
import type { ApprovalNotificationTarget } from "./approvalNavigation";

export function useApprovalNotifications(
  openApproval: (target?: ApprovalNotificationTarget) => void,
) {
  const enabled = useApprovalNotificationsEnabled();
  const { t } = useTranslation();
  const latest = useRef({ t, openApproval });
  latest.current = { t, openApproval };
  const notifier = useRef<BrowserApprovalNotifier>();

  useEffect(() => {
    const browser = new BrowserApprovalNotifier(
      () => ({
        title: latest.current.t("approvalNotifications.title"),
        body: (tool) =>
          latest.current.t("approvalNotifications.body", { tool }),
      }),
      (approval) =>
        latest.current.openApproval({
          requestId: approval.request_id,
          rootSessionId: approval.root_session_id,
          agentId: approval.owner_agent_id || approval.agent_id,
        }),
    );
    notifier.current = browser;
    return () => browser.dispose();
  }, []);

  useEffect(() => {
    if (!enabled) notifier.current?.closeAll();
    if (!isDesktopApp()) return;
    void configureDesktopApprovalNotifications(
      enabled,
      t("approvalNotifications.title"),
      t("approvalNotifications.body", { tool: "{tool}" }),
    ).catch((error: unknown) => {
      console.warn("Could not configure desktop approval notifications", error);
    });
    return () => {
      void configureDesktopApprovalNotifications(false, "", "").catch(
        console.warn,
      );
    };
  }, [enabled, t]);

  useEffect(() => {
    if (!isDesktopApp()) return;
    let disposed = false;
    let unlisten: (() => void) | undefined;
    void listen("qwenpaw:open-approvals", () => latest.current.openApproval())
      .then((cleanup) => {
        if (disposed) cleanup();
        else unlisten = cleanup;
      })
      .catch(console.warn);
    let approvalUnlisten: (() => void) | undefined;
    void listen<ApprovalNotificationTarget>("qwenpaw:open-approval", (event) =>
      latest.current.openApproval(event.payload),
    )
      .then((cleanup) => {
        if (disposed) cleanup();
        else approvalUnlisten = cleanup;
      })
      .catch(console.warn);
    return () => {
      disposed = true;
      unlisten?.();
      approvalUnlisten?.();
    };
  }, []);

  return useCallback((approvals: PendingApproval[]) => {
    if (!isDesktopApp()) notifier.current?.update(approvals);
  }, []);
}
