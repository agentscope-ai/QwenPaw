import { FormEvent, useState } from "react";
import { MessageSquare, PanelLeft, Send, Settings } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useMessageQueueStore } from "../stores/messageQueueStore";
import styles from "./DesktopStartupShell.module.css";

const STARTUP_QUEUE_ID = "new";

export default function DesktopStartupShell() {
  const { t } = useTranslation();
  const [message, setMessage] = useState("");
  const [queued, setQueued] = useState(
    () => useMessageQueueStore.getState().getQueue(STARTUP_QUEUE_ID).length > 0,
  );

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const text = message.trim();
    if (!text || queued) return;

    useMessageQueueStore.getState().enqueue(STARTUP_QUEUE_ID, { text });
    setMessage("");
    setQueued(true);
  };

  return (
    <div className={styles.shell}>
      <aside
        className={styles.sidebar}
        aria-label={t("common.navigation", "Navigation")}
      >
        <div className={styles.brand}>
          <img src="/qwenpaw.png" alt="QwenPaw" />
          <span>QwenPaw</span>
        </div>
        <nav className={styles.navigation}>
          <div className={styles.activeItem} aria-current="page">
            <MessageSquare size={17} aria-hidden="true" />
            <span>{t("menu.chat", "Chat")}</span>
          </div>
          <div className={styles.navItem}>
            <PanelLeft size={17} aria-hidden="true" />
            <span>{t("menu.workspace", "Workspace")}</span>
          </div>
          <div className={styles.navItem}>
            <Settings size={17} aria-hidden="true" />
            <span>{t("menu.settings", "Settings")}</span>
          </div>
        </nav>
      </aside>

      <main className={styles.main}>
        <header className={styles.header}>
          <div>
            <p className={styles.eyebrow}>QwenPaw</p>
            <h1>{t("chat.newConversation", "New conversation")}</h1>
          </div>
          <span className={styles.status} role="status">
            {queued
              ? t("startup.messageQueued", "Message queued")
              : t("startup.preparing", "Preparing assistant")}
          </span>
        </header>

        <section className={styles.workspace}>
          <div className={styles.intro}>
            <h2>{t("startup.beginNow", "What would you like to do?")}</h2>
            <p>
              {t(
                "startup.beginNowHint",
                "You can begin now. Your first message will be sent as soon as the assistant is ready.",
              )}
            </p>
          </div>

          <form className={styles.composer} onSubmit={submit}>
            <label htmlFor="desktop-startup-message">
              {t("startup.firstMessage", "First message")}
            </label>
            <div className={styles.inputRow}>
              <textarea
                id="desktop-startup-message"
                value={message}
                onChange={(event) => setMessage(event.target.value)}
                placeholder={t("chat.inputPlaceholder", "Ask QwenPaw anything")}
                rows={2}
                disabled={queued}
                autoFocus
              />
              <button
                type="submit"
                disabled={queued || message.trim().length === 0}
                aria-label={t("chat.send", "Send message")}
              >
                <Send size={18} aria-hidden="true" />
              </button>
            </div>
            <p className={styles.helper} aria-live="polite">
              {queued
                ? t(
                    "startup.messageQueuedHint",
                    "Your message is safe and will send automatically.",
                  )
                : t(
                    "startup.backgroundHint",
                    "Optional capabilities continue preparing in the background.",
                  )}
            </p>
          </form>
        </section>
      </main>
    </div>
  );
}
