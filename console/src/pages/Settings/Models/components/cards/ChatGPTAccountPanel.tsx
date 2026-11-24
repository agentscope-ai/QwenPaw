import { useEffect, useRef, useState } from "react";
import { Form, Dropdown } from "antd";
import InlineHelp from "@/components/InlineHelp";
import { Button } from "@agentscope-ai/design";
import {
  ArrowUpRight,
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
import {
  isDesktopTauriRuntime,
  openExternalLink,
} from "@/utils/openExternalLink";
import { OAuthConfirmModal } from "@/pages/Chat/ModelSelector/OAuthConfirmModal";
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
  const [signInAccount, setSignInAccount] = useState<{ id?: string } | null>(
    null,
  );
  const [error, setError] = useState("");
  const [warning, setWarning] = useState("");
  const alive = useRef(true);
  const locked = useRef(false);
  const saved = useRef(onSaved);
  saved.current = onSaved;
  const hosts = ["localhost", "127.0.0.1", "::1", "[::1]"];
  const local =
    (hosts.includes(window.location.hostname) || isDesktopTauriRuntime()) &&
    hosts.includes(new URL(getApiUrl(endpoint), window.location.href).hostname);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const action = async (path: string, body?: object) => {
    if (locked.current) return;
    locked.current = true;
    setBusy(path);
    setError("");
    setWarning("");
    try {
      const result = await request<{ revoked?: boolean }>(
        `${endpoint}/${path}`,
        {
          method: "POST",
          body: JSON.stringify(body ?? {}),
          timeout: 60_000,
        },
      );
      if (!alive.current) return;
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
      locked.current = false;
      if (alive.current) setBusy("");
    }
  };

  const signIn = (id?: string) => {
    setError("");
    setSignInAccount({ id });
  };

  const disabled = !!busy || !local;
  return (
    <>
      <Form.Item
        label={
          <span className={styles.summaryLabel}>
            {t("models.chatgpt.account")}
            <InlineHelp inline subject={t("models.chatgpt.account")}>
              {t("models.chatgpt.localHelp")}
            </InlineHelp>
          </span>
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
            disabled={!local || !!busy}
            onClick={() => void signIn(session?.active ?? undefined)}
          >
            {t("modelSelector.oauthTitle", { provider: "ChatGPT" })}
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
      <OAuthConfirmModal
        open={signInAccount !== null}
        providerId="openai-chatgpt"
        providerName="ChatGPT"
        description={t("models.chatgpt.oauthDescription")}
        flow={{
          start: () =>
            request(`${endpoint}/start`, {
              method: "POST",
              body: JSON.stringify({ account_id: signInAccount?.id }),
            }),
          getStatus: (state) => request(`${endpoint}/status/${state}`),
          cancel: (state) =>
            request(`${endpoint}/cancel/${state}`, { method: "POST" }),
        }}
        onCancel={() => setSignInAccount(null)}
        onSuccess={() => {
          setSignInAccount(null);
          void request<ChatGPTSession>(`${endpoint}/session`)
            .then((current) => {
              if (alive.current) {
                setSession(current);
                void saved.current();
              }
            })
            .catch(() => {
              if (alive.current) setError(t("models.chatgpt.failed"));
            });
        }}
      />
    </>
  );
}
