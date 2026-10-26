import { useEffect, useRef, useState } from "react";
import { Form, Button, Dropdown, Space, Tooltip } from "antd";
import {
  ArrowUpRight,
  CircleHelp,
  CircleCheck,
  LogIn,
  LogOut,
  MoreHorizontal,
  UserRoundPen,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import type { ProviderInfo } from "@/api/types";
import { request } from "@/api/request";
import { getApiUrl } from "@/api/config";
import { getPyWebViewApi } from "@/utils/pywebview";
import {
  isDesktopTauriRuntime,
  openExternalLink,
} from "@/utils/openExternalLink";
import { IconButton } from "@/components/interaction/IconButton";
import styles from "./ChatGPTAccountPanel.module.less";

export interface ChatGPTSession {
  active: string | null;
  connected: boolean;
  sharing: boolean;
  accounts: { id: string; email: string }[];
}

const endpoint = "/providers/chatgpt";

export function ChatGPTAccountPanel({
  provider,
  onSaved,
}: {
  provider: Pick<ProviderInfo, "meta">;
  onSaved: () => void | Promise<void>;
}) {
  const { t } = useTranslation();
  const [session, setSession] = useState<ChatGPTSession | undefined>(
    provider.meta?.chatgpt_session as ChatGPTSession | undefined,
  );
  const [busy, setBusy] = useState("");
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [warning, setWarning] = useState("");
  const alive = useRef(true);
  const locked = useRef(false);
  const attempt = useRef<string | null>(null);
  const popupRef = useRef<Window | null>(null);
  const saved = useRef(onSaved);
  saved.current = onSaved;
  const hosts = ["localhost", "127.0.0.1", "::1", "[::1]"];
  const local =
    hosts.includes(window.location.hostname) &&
    hosts.includes(new URL(getApiUrl(endpoint), window.location.href).hostname);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      popupRef.current?.close();
      popupRef.current = null;
      if (attempt.current) {
        void request(`${endpoint}/cancel/${attempt.current}`, {
          method: "POST",
        }).catch(() => undefined);
      }
    };
  }, []);

  useEffect(() => {
    if (!pending) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const deadline = Date.now() + 310_000;
    const poll = async () => {
      try {
        const result = await request<{ status: string }>(
          `${endpoint}/status/${pending}`,
        );
        if (stopped) return;
        if (result.status === "ready") {
          const current = await request<ChatGPTSession>(`${endpoint}/session`);
          if (stopped) return;
          attempt.current = null;
          popupRef.current?.close();
          popupRef.current = null;
          setSession(current);
          setPending(null);
          void saved.current();
          return;
        }
        if (
          ["failed", "cancelled"].includes(result.status) ||
          Date.now() > deadline
        ) {
          throw new Error(t("models.chatgpt.failed"));
        }
        timer = setTimeout(poll, 1500);
      } catch (err) {
        if (stopped) return;
        setError(err instanceof Error ? err.message : String(err));
        void request(`${endpoint}/cancel/${pending}`, { method: "POST" }).catch(
          () => undefined,
        );
        void request<ChatGPTSession>(`${endpoint}/session`)
          .then((current) => {
            if (alive.current) setSession(current);
          })
          .catch(() => undefined);
        attempt.current = null;
        popupRef.current?.close();
        popupRef.current = null;
        setPending(null);
        void saved.current();
      }
    };
    timer = setTimeout(poll, 1000);
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [pending, t]);

  const cancelPending = async () => {
    const state = attempt.current;
    attempt.current = null;
    popupRef.current?.close();
    popupRef.current = null;
    setPending(null);
    if (state) await request(`${endpoint}/cancel/${state}`, { method: "POST" });
  };

  const action = async (path: string, body?: object) => {
    if (locked.current) return;
    locked.current = true;
    setBusy(path);
    setError("");
    setWarning("");
    try {
      if (attempt.current && !path.startsWith("cancel/")) await cancelPending();
      const result = await request<{ revoked?: boolean }>(
        `${endpoint}/${path}`,
        {
          method: "POST",
          body: JSON.stringify(body ?? {}),
          timeout: 60_000,
        },
      );
      if (!alive.current) return;
      if (path.startsWith("cancel/")) {
        attempt.current = null;
        popupRef.current?.close();
        popupRef.current = null;
        setPending(null);
      }
      if (result.revoked === false)
        setWarning(t("models.chatgpt.revokeWarning"));
      const current = await request<ChatGPTSession>(`${endpoint}/session`);
      if (!alive.current) return;
      setSession(current);
      void saved.current();
    } catch (err) {
      if (alive.current) {
        setError(err instanceof Error ? err.message : String(err));
        const current = await request<ChatGPTSession>(
          `${endpoint}/session`,
        ).catch(() => undefined);
        if (alive.current && current) {
          setSession(current);
          void saved.current();
        }
      }
    } finally {
      if (path.startsWith("cancel/")) {
        attempt.current = null;
        popupRef.current?.close();
        popupRef.current = null;
        if (alive.current) setPending(null);
      }
      locked.current = false;
      if (alive.current) setBusy("");
    }
  };

  const signIn = async (accountId?: string) => {
    if (locked.current) return;
    locked.current = true;
    setBusy("sign-in");
    setError("");
    const popup =
      !isDesktopTauriRuntime() && !getPyWebViewApi()?.open_external_link
        ? window.open("about:blank", "_blank")
        : null;
    if (popup) popup.opener = null;
    try {
      await cancelPending();
      popupRef.current = popup;
      const result = await request<{ authorize_url: string; state: string }>(
        `${endpoint}/start`,
        {
          method: "POST",
          body: JSON.stringify({ account_id: accountId }),
        },
      );
      if (!alive.current || popup?.closed) {
        popup?.close();
        popupRef.current = null;
        await request(`${endpoint}/cancel/${result.state}`, { method: "POST" });
        return;
      }
      attempt.current = result.state;
      setPending(result.state);
      if (popup) popup.location.replace(result.authorize_url);
      else openExternalLink(result.authorize_url);
    } catch (err) {
      popup?.close();
      popupRef.current = null;
      if (alive.current)
        setError(err instanceof Error ? err.message : String(err));
    } finally {
      locked.current = false;
      if (alive.current) setBusy("");
    }
  };

  // OAuth windows may sever their opener; waiting must not lock account edits.
  const disabled = !!busy || !local;
  return (
    <>
      <Form.Item
        label={
          <Tooltip
            title={t("models.chatgpt.localHelp")}
            trigger={["hover", "focus"]}
          >
            <span tabIndex={0} className={styles.summaryLabel}>
              {t("models.chatgpt.account")}
              <CircleHelp size={14} aria-hidden />
            </span>
          </Tooltip>
        }
      >
        {session?.connected ? (
          <div className={styles.accountSummary}>
            <div className={styles.accountDetails}>
              <div className={styles.accountHeading}>
                <span className={styles.accountName}>
                  {t("models.providerVariants.chatgpt")}
                </span>
                <span
                  role="status"
                  className={
                    session.sharing ? styles.connected : styles.warning
                  }
                >
                  {session.sharing && <CircleCheck size={14} aria-hidden />}
                  {t(
                    session.sharing
                      ? "models.chatgpt.connectedShort"
                      : "models.chatgpt.permissionMissing",
                  )}
                </span>
              </div>
              <div className={styles.accountEmail}>
                {session.accounts.find(
                  (account) => account.id === session.active,
                )?.email || "ChatGPT"}
              </div>
            </div>
            <div className={styles.accountActions}>
              <Button
                size="small"
                onClick={() =>
                  openExternalLink("https://chatgpt.com/settings/usage")
                }
              >
                {t("models.chatgpt.usage")}
                <ArrowUpRight size={14} aria-hidden />
              </Button>
              <Dropdown
                trigger={["click"]}
                menu={{
                  items: [
                    ...session.accounts
                      .filter((account) => account.id !== session.active)
                      .map((account) => ({
                        key: account.id,
                        label: account.email || "ChatGPT",
                        onClick: () =>
                          void action("select", { account_id: account.id }),
                      })),
                    {
                      key: "change",
                      label: t("models.chatgpt.changeAccount"),
                      icon: <UserRoundPen size={16} />,
                      onClick: () => void signIn(),
                    },
                    ...(!session.sharing
                      ? [
                          {
                            key: "reconnect",
                            label: t("models.chatgpt.reconnect"),
                            icon: <LogIn size={16} />,
                            onClick: () =>
                              void signIn(session.active ?? undefined),
                          },
                        ]
                      : []),
                    { type: "divider" },
                    {
                      key: "disconnect",
                      label: t("models.chatgpt.signOut"),
                      icon: <LogOut size={16} />,
                      danger: true,
                      onClick: () => void action("sign-out"),
                    },
                  ],
                }}
              >
                <IconButton
                  type="text"
                  icon={MoreHorizontal}
                  label={t("models.chatgpt.accountActions")}
                  onClick={(event) => event.stopPropagation()}
                  disabled={disabled}
                  loading={!!busy}
                />
              </Dropdown>
            </div>
          </div>
        ) : (
          <Button
            type="primary"
            icon={<LogIn size={16} />}
            loading={busy === "sign-in"}
            disabled={!local || !!busy}
            onClick={() => void signIn(session?.active ?? undefined)}
          >
            Continue with ChatGPT
          </Button>
        )}
      </Form.Item>
      {error && (
        <p role="alert" className={styles.error}>
          {error}
        </p>
      )}
      {warning && (
        <p role="status" className={styles.warning}>
          {warning}
        </p>
      )}
      {pending && (
        <Form.Item>
          <Space wrap>
            <span role="status">{t("models.chatgpt.waiting")}</span>
            <Button
              loading={busy.startsWith("cancel/")}
              onClick={() => void action(`cancel/${pending}`)}
            >
              {t("common.cancel")}
            </Button>
          </Space>
        </Form.Item>
      )}
    </>
  );
}
