import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { invoke } from "@tauri-apps/api/core";
import { isDesktopApp } from "./backendRuntime";

/** Keep native labels in sync after lazy locale resources have loaded. */
export function useDesktopTrayLabels() {
  const { i18n } = useTranslation();

  useEffect(() => {
    if (!isDesktopApp()) return;
    let revision = 0;
    let disposed = false;
    const sync = async (language: string) => {
      const current = ++revision;
      try {
        await i18n.loadLanguages(language);
        if (disposed || current !== revision) return;
        const translate = i18n.getFixedT(language);
        await invoke("set_tray_labels", {
          showWindow: translate("desktop.closeWindow.showWindow"),
          quit: translate("desktop.closeWindow.quitApp"),
          stopBlocked: translate("desktop.closeWindow.stopBlocked"),
          viewApprovals: translate("approvalNotifications.openApprovals"),
        });
      } catch (error) {
        console.error("Could not update desktop tray labels", error);
      }
    };
    const onLanguage = (language: string) => void sync(language);
    onLanguage(i18n.language || i18n.resolvedLanguage || "en");
    i18n.on("languageChanged", onLanguage);
    return () => {
      disposed = true;
      i18n.off("languageChanged", onLanguage);
    };
  }, [i18n]);
}
