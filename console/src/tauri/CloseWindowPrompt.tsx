import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { CircleAlert, X } from "lucide-react";
import {
  setRememberedCloseAction,
  type CloseAction,
} from "./closeWindowPreference";
import styles from "./DesktopClient.module.less";

/** Native dialog semantics keep close controls independent of console chunks. */
export default function CloseWindowPrompt() {
  const { t, i18n } = useTranslation();
  const dialog = useRef<HTMLDialogElement>(null);
  const backgroundAction = useRef<HTMLButtonElement>(null);
  const [remember, setRemember] = useState(false);
  const pending = useRef(false);
  const [submitting, setSubmitting] = useState<CloseAction | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let disposed = false;
    let unlisten: (() => void) | undefined;
    void listen("qwenpaw-close-requested", () => {
      void invoke("ack_close").catch(console.error);
      if (pending.current) return;
      setRemember(false);
      setError("");
      dialog.current?.showModal();
      backgroundAction.current?.focus({ preventScroll: true });
    })
      .then((cleanup) => {
        if (disposed) cleanup();
        else unlisten = cleanup;
      })
      .catch(console.error);
    return () => {
      disposed = true;
      unlisten?.();
    };
  }, []);

  useEffect(() => {
    const syncTrayLabels = (language: string) => {
      const translate = i18n.getFixedT(language);
      void invoke("set_tray_labels", {
        showWindow: translate("desktop.closeWindow.showWindow"),
        quit: translate("desktop.closeWindow.quitApp"),
        stopBlocked: translate("desktop.closeWindow.stopBlocked"),
      }).catch(console.error);
    };
    syncTrayLabels(i18n.resolvedLanguage || i18n.language || "en");
    i18n.on("languageChanged", syncTrayLabels);
    return () => {
      i18n.off("languageChanged", syncTrayLabels);
    };
  }, [i18n]);

  async function choose(action: CloseAction) {
    if (pending.current) return;
    pending.current = true;
    setSubmitting(action);
    setError("");
    try {
      if (action === "stop-service") await invoke("stop_service");
      if (remember) await setRememberedCloseAction(action);
      await invoke(
        action === "minimize-to-tray" ? "minimize_to_tray" : "quit_app",
      );
      dialog.current?.close();
    } catch (reason) {
      setError(String(reason));
    } finally {
      pending.current = false;
      setSubmitting(null);
    }
  }

  return (
    <dialog
      ref={dialog}
      className={styles.closeDialog}
      aria-labelledby="desktop-close-title"
      aria-describedby="desktop-close-description"
      aria-busy={submitting !== null}
      onCancel={(event) => {
        if (submitting) event.preventDefault();
      }}
    >
      <header className={styles.closeHeader}>
        <h2 id="desktop-close-title">{t("desktop.closeWindow.title")}</h2>
        <button
          className={styles.dismissClose}
          aria-label={t("common.cancel")}
          disabled={submitting !== null}
          onClick={() => dialog.current?.close()}
        >
          <X size={18} aria-hidden="true" />
        </button>
      </header>
      <p id="desktop-close-description">
        {t("desktop.closeWindow.description")}
      </p>
      <label>
        <input
          type="checkbox"
          checked={remember}
          disabled={submitting !== null}
          onChange={(event) => setRemember(event.target.checked)}
        />
        {t("desktop.closeWindow.remember")}
      </label>
      {error && (
        <div className={styles.closeError} role="alert">
          <CircleAlert size={18} aria-hidden="true" />
          <span>{error}</span>
        </div>
      )}
      <footer>
        <button
          ref={backgroundAction}
          data-press
          className={styles.keepRunning}
          disabled={submitting !== null}
          onClick={() => void choose("quit")}
        >
          {t(
            submitting === "quit"
              ? "desktop.closeWindow.quitting"
              : "desktop.closeWindow.keepRunning",
          )}
        </button>
        <button
          data-press
          className={styles.quitCompletely}
          disabled={submitting !== null}
          onClick={() => void choose("stop-service")}
        >
          {t(
            submitting === "stop-service"
              ? "desktop.closeWindow.quitting"
              : "desktop.closeWindow.stopService",
          )}
        </button>
      </footer>
    </dialog>
  );
}
