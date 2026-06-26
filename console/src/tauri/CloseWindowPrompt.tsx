import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { Button, Checkbox, Modal, Typography } from "antd";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { isTauriRuntime } from "./backendRuntime";
import {
  getRememberedCloseAction,
  setRememberedCloseAction,
  type CloseAction,
} from "./closeWindowPreference";

const CLOSE_REQUESTED_EVENT = "qwenpaw-close-requested";

async function runCloseAction(action: CloseAction): Promise<void> {
  const command = action === "quit" ? "quit_app" : "minimize_to_tray";
  await invoke<void>(command);
}

export default function CloseWindowPrompt() {
  const { t, i18n } = useTranslation();
  const [open, setOpen] = useState(false);
  const [remember, setRemember] = useState(false);
  const [submitting, setSubmitting] = useState<CloseAction | null>(null);

  const handleCloseRequested = useCallback(() => {
    // Tell Rust a listener is alive so its minimize-to-tray fallback stands
    // down; we now own the prompt / remembered-choice flow.
    void invoke("ack_close").catch((err) => {
      console.error("Failed to ack close request:", err);
    });

    const rememberedAction = getRememberedCloseAction();
    if (rememberedAction) {
      void runCloseAction(rememberedAction).catch((err) => {
        console.error("Failed to run remembered close action:", err);
      });
      return;
    }

    setRemember(false);
    setOpen(true);
  }, []);

  const handleAction = useCallback(
    async (action: CloseAction) => {
      setSubmitting(action);
      try {
        if (remember) {
          setRememberedCloseAction(action);
        }
        await runCloseAction(action);
        if (action === "minimize-to-tray") {
          setOpen(false);
        }
      } catch (err) {
        console.error("Failed to run close action:", err);
      } finally {
        setSubmitting(null);
      }
    },
    [remember],
  );

  useEffect(() => {
    if (!isTauriRuntime()) return undefined;

    let disposed = false;
    let unlisten: (() => void) | undefined;

    void listen(CLOSE_REQUESTED_EVENT, () => handleCloseRequested())
      .then((cleanup) => {
        if (disposed) {
          cleanup();
          return;
        }
        unlisten = cleanup;
      })
      .catch((err) => {
        console.error("Failed to listen for close requests:", err);
      });

    return () => {
      disposed = true;
      unlisten?.();
    };
  }, [handleCloseRequested]);

  useEffect(() => {
    if (!isTauriRuntime()) return undefined;

    const syncTrayLabels = (language: string) => {
      const translate = i18n.getFixedT(language);
      void invoke("set_tray_labels", {
        showWindow: translate("desktop.closeWindow.showWindow", "Show Window"),
        quit: translate("desktop.closeWindow.quitApp", "Quit App"),
      }).catch((err) => {
        console.error("Failed to update tray labels:", err);
      });
    };

    syncTrayLabels(i18n.resolvedLanguage || i18n.language || "en");
    i18n.on("languageChanged", syncTrayLabels);

    return () => {
      i18n.off("languageChanged", syncTrayLabels);
    };
  }, [i18n]);

  if (!isTauriRuntime()) {
    return null;
  }

  return (
    <Modal
      open={open}
      title={t("desktop.closeWindow.title", "Close Window")}
      closable={false}
      maskClosable={false}
      keyboard={false}
      footer={[
        <Button
          key="minimize"
          loading={submitting === "minimize-to-tray"}
          disabled={submitting === "quit"}
          onClick={() => void handleAction("minimize-to-tray")}
        >
          {t("desktop.closeWindow.minimizeToTray", "Minimize to Tray")}
        </Button>,
        <Button
          key="quit"
          type="primary"
          danger
          loading={submitting === "quit"}
          disabled={submitting === "minimize-to-tray"}
          onClick={() => void handleAction("quit")}
        >
          {t("desktop.closeWindow.quitApp", "Quit App")}
        </Button>,
      ]}
    >
      <Typography.Paragraph type="secondary">
        {t(
          "desktop.closeWindow.description",
          "What would you like to do when closing the window? Quitting the app stops all running tasks and scheduled jobs.",
        )}
      </Typography.Paragraph>
      <Checkbox
        checked={remember}
        onChange={(event) => setRemember(event.target.checked)}
      >
        {t("desktop.closeWindow.remember", "Remember my choice")}
      </Checkbox>
    </Modal>
  );
}
