import { useCallback, useEffect, useRef, useState } from "react";
import { Button, Form, Input } from "antd";
import {
  Blocks,
  Check,
  CircleAlert,
  Clock3,
  ExternalLink,
  LogOut,
  PawPrint,
  SquareTerminal,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { harnessApi, type HarnessProvider } from "@/api/modules/harness";
import type { AgentBackend } from "@/api/types/agents";
import { useAppMessage } from "@/hooks/useAppMessage";
import styles from "./AgentBackendFields.module.less";

const POLL_INTERVAL_MS = 2_000;

interface AgentBackendFieldsProps {
  form: ReturnType<typeof Form.useForm>[0];
  open: boolean;
}

export function AgentBackendFields({ form, open }: AgentBackendFieldsProps) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const backend =
    (Form.useWatch("backend", form) as AgentBackend | undefined) ?? "qwenpaw";
  const [codex, setCodex] = useState<HarnessProvider | null>(null);
  const [connecting, setConnecting] = useState(false);
  const pollTimer = useRef<number | undefined>(undefined);
  const pollTimeout = useRef<number | undefined>(undefined);

  const stopPolling = useCallback(() => {
    if (pollTimer.current) window.clearInterval(pollTimer.current);
    if (pollTimeout.current) window.clearTimeout(pollTimeout.current);
    pollTimer.current = undefined;
    pollTimeout.current = undefined;
  }, []);

  const loadStatus = useCallback(async () => {
    const result = await harnessApi.list();
    const provider = result.providers.find((item) => item.id === "codex");
    setCodex(provider ?? null);
    return provider;
  }, []);

  useEffect(() => {
    if (!open) return stopPolling;
    void loadStatus().catch(() => setCodex(null));
    return stopPolling;
  }, [loadStatus, open, stopPolling]);

  const connect = useCallback(async () => {
    const popup = window.open("about:blank", "_blank");
    if (popup) popup.opener = null;
    setConnecting(true);
    try {
      const login = await harnessApi.login("codex");
      if (!login.authUrl) throw new Error("Codex did not return a login URL");
      if (popup) popup.location.href = login.authUrl;
      else window.open(login.authUrl, "_blank", "noopener,noreferrer");
      stopPolling();
      pollTimer.current = window.setInterval(async () => {
        try {
          const provider = await loadStatus();
          if (provider?.authenticated) {
            stopPolling();
            setConnecting(false);
            message.success(t("harnesses.connected"));
          }
        } catch {
          return;
        }
      }, POLL_INTERVAL_MS);
      pollTimeout.current = window.setTimeout(() => {
        stopPolling();
        setConnecting(false);
      }, 120_000);
    } catch (error) {
      popup?.close();
      setConnecting(false);
      message.error(error instanceof Error ? error.message : String(error));
    }
  }, [loadStatus, message, stopPolling, t]);

  const disconnect = useCallback(async () => {
    try {
      await harnessApi.logout("codex");
      await loadStatus();
      message.success(t("harnesses.disconnected"));
    } catch (error) {
      message.error(error instanceof Error ? error.message : String(error));
    }
  }, [loadStatus, message, t]);

  const selectBackend = useCallback(
    (next: AgentBackend) => {
      form.setFieldsValue({
        backend: next,
        ...(next === "qwenpaw" ? { backend_settings: {} } : {}),
      });
    },
    [form],
  );

  return (
    <section className={styles.section}>
      <Form.Item name="backend" hidden>
        <Input />
      </Form.Item>

      <div className={styles.sectionHeading}>
        <span className={styles.eyebrow}>{t("agent.backend.eyebrow")}</span>
        <h3>{t("agent.backend.typeTitle")}</h3>
        <p>{t("agent.backend.typeDescription")}</p>
      </div>

      <div className={styles.typeGrid}>
        <button
          type="button"
          className={`${styles.typeCard} ${
            backend === "qwenpaw" ? styles.selected : ""
          }`}
          onClick={() => selectBackend("qwenpaw")}
        >
          <span className={styles.typeIcon}>
            <PawPrint size={20} />
          </span>
          <span className={styles.typeCopy}>
            <strong>{t("agent.backend.nativeTitle")}</strong>
            <small>{t("agent.backend.nativeDescription")}</small>
          </span>
          <span className={styles.radioMark} aria-hidden="true" />
        </button>
        <button
          type="button"
          className={`${styles.typeCard} ${
            backend !== "qwenpaw" ? styles.selected : ""
          }`}
          onClick={() => selectBackend("codex")}
        >
          <span className={styles.typeIcon}>
            <Blocks size={20} />
          </span>
          <span className={styles.typeCopy}>
            <strong>{t("agent.backend.thirdPartyTitle")}</strong>
            <small>{t("agent.backend.thirdPartyDescription")}</small>
          </span>
          <span className={styles.radioMark} aria-hidden="true" />
        </button>
      </div>

      {backend === "codex" && (
        <div className={styles.thirdPartyPanel}>
          <div className={styles.panelHeading}>
            <h4>{t("agent.backend.providerTitle")}</h4>
            <p>{t("agent.backend.providerDescription")}</p>
          </div>

          <div className={styles.providerGrid}>
            <button type="button" className={styles.providerCardSelected}>
              <span className={styles.providerIcon}>
                <SquareTerminal size={18} />
              </span>
              <span className={styles.providerCopy}>
                <strong>Codex</strong>
                <small>{t("agent.backend.codexHint")}</small>
              </span>
              <Check size={15} className={styles.providerCheck} />
            </button>
            <div className={styles.providerCardDisabled}>
              <span className={styles.providerIcon}>
                <Blocks size={18} />
              </span>
              <span className={styles.providerCopy}>
                <strong>Claude Code</strong>
                <small>{t("harnesses.comingSoon")}</small>
              </span>
              <Clock3 size={14} />
            </div>
            <div className={styles.providerCardDisabled}>
              <span className={styles.providerIcon}>
                <Blocks size={18} />
              </span>
              <span className={styles.providerCopy}>
                <strong>Qoder</strong>
                <small>{t("harnesses.comingSoon")}</small>
              </span>
              <Clock3 size={14} />
            </div>
          </div>

          <div className={styles.codexConfig}>
            <div className={styles.accountRow}>
              <div className={styles.accountState}>
                <span className={styles.accountLabel}>
                  {t("agent.backend.account")}
                </span>
                {codex?.authenticated ? (
                  <span className={styles.connectedState}>
                    <Check size={14} /> {t("harnesses.connected")}
                    {codex.account?.email ? ` · ${codex.account.email}` : ""}
                  </span>
                ) : (
                  <span className={styles.disconnectedState}>
                    <CircleAlert size={14} />
                    {codex?.installed
                      ? t("harnesses.notConnected")
                      : t("agent.backend.codexNotFound")}
                  </span>
                )}
              </div>
              <div className={styles.accountAction}>
                {!codex?.authenticated && (
                  <Button
                    icon={<ExternalLink size={14} />}
                    loading={connecting}
                    disabled={codex ? !codex.installed : true}
                    onClick={() => void connect()}
                  >
                    {t("harnesses.connect")}
                  </Button>
                )}
                {codex?.authenticated && (
                  <Button
                    icon={<LogOut size={14} />}
                    onClick={() => void disconnect()}
                  >
                    {t("harnesses.disconnect")}
                  </Button>
                )}
              </div>
            </div>
            {codex?.authenticated && (
              <p className={styles.chatSettingsHint}>
                {t("agent.backend.chatSettingsHint")}
              </p>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
