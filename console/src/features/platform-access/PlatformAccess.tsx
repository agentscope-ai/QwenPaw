import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, Button, Popconfirm, QRCode, Tooltip } from "antd";
import { Check, LogIn, RefreshCw, Smartphone, UserRound } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useAppMessage } from "../../hooks/useAppMessage";
import { SharedModal } from "../../components/interaction/SharedModal";
import {
  platformAccessApi,
  type MobileLogin,
  type MobileLoginStatus,
} from "./api";
import { usePlatformAccess } from "./store";
import styles from "./platformAccess.module.less";
import { isPlatformWebApp } from "../platform-web/client";
import { WorkspaceSwitcher } from "../platform-web/WorkspaceSwitcher";

function failure(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export function PlatformAccount({
  className,
  onSelect,
}: {
  className: string;
  onSelect: () => void;
}) {
  const { t } = useTranslation();
  const { connection, open } = usePlatformAccess();
  if (isPlatformWebApp) return <WorkspaceSwitcher className={className} />;
  const label = connection?.logged_in
    ? connection.account_name
    : t("platformAccess.signIn");
  return (
    <button
      id="platform-account"
      type="button"
      className={className}
      aria-label={t("platformAccess.account")}
      onClick={() => {
        onSelect();
        open("account");
      }}
    >
      {connection?.logged_in ? <UserRound size={18} /> : <LogIn size={18} />}
      <span>{label}</span>
    </button>
  );
}

export function PlatformMobileButton() {
  const { t } = useTranslation();
  const open = usePlatformAccess((state) => state.open);
  if (isPlatformWebApp) return <WorkspaceSwitcher />;
  return (
    <>
      <Tooltip title={t("platformAccess.addToPhone")}>
        <Button
          type="text"
          icon={<Smartphone size={18} />}
          aria-label={t("platformAccess.addToPhone")}
          className={styles.mobileButton}
          onClick={() => open("mobile")}
        />
      </Tooltip>
      <PlatformAccessDialog />
    </>
  );
}

function PlatformAccessDialog() {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const { panel, open, connection, refresh, localAccount } =
    usePlatformAccess();
  const ready = !!connection?.logged_in && !!connection.node_id;
  const [ticket, setTicket] = useState<MobileLogin | null>(null);
  const [status, setStatus] = useState<MobileLoginStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [expired, setExpired] = useState(false);
  const generation = useRef(0);
  const acting = useRef(false);
  const action = async (operation: () => Promise<unknown>) => {
    if (acting.current) return;
    acting.current = true;
    setBusy(true);
    setError("");
    try {
      await operation();
    } catch (error) {
      setError(failure(error));
    } finally {
      acting.current = false;
      setBusy(false);
      await refresh().catch(() => {});
    }
  };
  const generate = useCallback(async () => {
    const current = ++generation.current;
    const latest = await refresh();
    if (!latest.logged_in || !latest.node_id) return;
    const next = await platformAccessApi.mobile();
    if (current !== generation.current) {
      void platformAccessApi.cancel(next.request_id).catch(() => {});
      return;
    }
    setStatus(null);
    setExpired(false);
    setTicket(next);
  }, [refresh]);
  useEffect(() => {
    if (!panel) return;
    let cancelled = false;
    setError("");
    setTicket(null);
    setStatus(null);
    setExpired(false);
    setBusy(true);
    const load = panel === "mobile" && ready ? generate() : refresh();
    void load
      .catch((error) => {
        if (!cancelled) {
          setError(failure(error));
          void refresh().catch(() => {});
        }
      })
      .finally(() => {
        if (!cancelled) setBusy(false);
      });
    return () => {
      cancelled = true;
      generation.current += 1;
    };
  }, [panel, ready, generate, refresh]);
  useEffect(() => {
    if (!panel || connection?.status !== "authorization_pending") return;
    const timer = window.setInterval(() => {
      void refresh().catch(() => {});
    }, 2000);
    return () => window.clearInterval(timer);
  }, [panel, connection?.status, refresh]);
  useEffect(() => {
    if (!ticket || panel !== "mobile") return;
    let active = true;
    let finished = false;
    let exchanged = false;
    let polling = false;
    const timer = window.setInterval(() => {
      if (polling || finished) return;
      polling = true;
      void platformAccessApi
        .mobileStatus(ticket.request_id)
        .then((value) => {
          if (!active) return;
          setStatus(value);
          exchanged = value.status === "exchanged";
          finished = exchanged;
        })
        .catch((error) => {
          if (active) {
            setError(failure(error));
            void refresh().catch(() => {});
            finished = true;
          }
        })
        .finally(() => {
          polling = false;
        });
    }, 1500);
    const expiry = window.setTimeout(
      () => {
        if (!finished && active) {
          finished = true;
          setExpired(true);
        }
      },
      Math.max(0, ticket.expires_at * 1000 - Date.now()),
    );
    return () => {
      active = false;
      window.clearInterval(timer);
      window.clearTimeout(expiry);
      if (!exchanged)
        void platformAccessApi.cancel(ticket.request_id).catch(() => {});
    };
  }, [ticket, panel, refresh]);

  const login = () =>
    action(async () => {
      const popup = window.open(
        "about:blank",
        "qwenpaw-platform",
        "popup,width=760,height=760",
      );
      if (popup) popup.opener = null;
      try {
        const value = await platformAccessApi.login(
          localAccount
            ? `${window.location.hostname} · ${localAccount}`
            : window.location.hostname,
        );
        if (value.authorization_url) {
          if (popup) popup.location.href = value.authorization_url;
          else throw new Error(t("platformAccess.popupBlocked"));
        }
        await refresh();
      } catch (error) {
        popup?.close();
        throw error;
      }
    });

  const complete = status?.status === "exchanged";
  return (
    <SharedModal
      open={panel !== null}
      onCancel={() => open(null)}
      footer={null}
      title={t(
        panel === "account"
          ? "platformAccess.account"
          : "platformAccess.addToPhone",
      )}
      width={400}
    >
      <div className={styles.content}>
        {error && <Alert type="error" message={error} />}
        {connection?.transport_status === "authorization_required" && (
          <Alert type="warning" message={t("platformAccess.bindingExpired")} />
        )}
        {panel === "account" || !ready ? (
          <>
            {localAccount && (
              <div className={styles.identity}>
                <span>{t("platformAccess.localIdentity")}</span>
                <strong>{localAccount}</strong>
              </div>
            )}
            <div className={styles.identity}>
              <span>{t("platformAccess.cloudIdentity")}</span>
              <strong>
                {connection?.account_name || t("platformAccess.notSignedIn")}
              </strong>
            </div>
            {connection?.node_id && (
              <div className={styles.identity}>
                <span>{t("platformAccess.connection")}</span>
                <strong>
                  {t(
                    connection.transport_status === "online"
                      ? "platformAccess.online"
                      : "platformAccess.offline",
                  )}
                </strong>
              </div>
            )}
            {!connection?.logged_in ? (
              <Button type="primary" loading={busy} onClick={login} block>
                {t("platformAccess.signIn")}
              </Button>
            ) : connection.node_id ? (
              <Button type="primary" onClick={() => open("mobile")} block>
                {t("platformAccess.addToPhone")}
              </Button>
            ) : (
              <Button
                type="primary"
                loading={busy}
                onClick={() => action(platformAccessApi.bind)}
                block
              >
                {t("platformAccess.retryBind")}
              </Button>
            )}
            {(connection?.logged_in || connection?.node_id) && (
              <div className={styles.accountActions}>
                {connection.logged_in && (
                  <Button
                    type="text"
                    loading={busy}
                    onClick={() => action(platformAccessApi.logout)}
                  >
                    {t("platformAccess.signOut")}
                  </Button>
                )}
                {connection.node_id && (
                  <Popconfirm
                    title={t("platformAccess.disconnectConfirm")}
                    onConfirm={() =>
                      action(async () => {
                        const result = await platformAccessApi.disconnect();
                        if (!result.remote_cleanup_confirmed)
                          message.warning(
                            t("platformAccess.remoteCleanupUnconfirmed"),
                          );
                      })
                    }
                  >
                    <Button type="text" danger loading={busy}>
                      {t("platformAccess.disconnect")}
                    </Button>
                  </Popconfirm>
                )}
              </div>
            )}
            {connection?.status === "authorization_pending" && (
              <p role="status">{t("platformAccess.waitingLogin")}</p>
            )}
          </>
        ) : complete ? (
          <div className={styles.completed} role="status">
            <Check size={32} />
            <strong>{t("platformAccess.phoneConnected")}</strong>
            <p>{t("platformAccess.installOnPhone")}</p>
          </div>
        ) : (
          <>
            <div className={styles.qr} aria-busy={busy}>
              {ticket && !expired && !status?.verification_code ? (
                <QRCode
                  value={ticket.url}
                  size={224}
                  bordered={false}
                  errorLevel="M"
                />
              ) : status?.verification_code && !expired ? (
                <div className={styles.verification}>
                  <Smartphone size={28} />
                  <strong>{status.verification_code}</strong>
                  <span>{status.device_name}</span>
                </div>
              ) : (
                <Smartphone size={40} />
              )}
            </div>
            <strong className={styles.accountName}>
              {connection?.account_name}
            </strong>
            <p className={styles.hint}>
              {t(
                expired
                  ? "platformAccess.expired"
                  : status?.verification_code
                  ? "platformAccess.verifyPhone"
                  : "platformAccess.qrConsent",
              )}
            </p>
            {connection?.transport_status !== "online" && (
              <p className={styles.hint}>{t("platformAccess.offlineHint")}</p>
            )}
            {status?.status === "claimed" && ticket && (
              <Button
                type="primary"
                loading={busy}
                onClick={() =>
                  action(() =>
                    platformAccessApi.approve(
                      ticket.request_id,
                      status.verification_code!,
                    ),
                  )
                }
                block
              >
                {t("platformAccess.confirmPhone")}
              </Button>
            )}
            {(expired || error || !ticket) && (
              <Button
                icon={<RefreshCw size={16} />}
                loading={busy}
                onClick={() => action(generate)}
                block
              >
                {t("platformAccess.refreshQr")}
              </Button>
            )}
          </>
        )}
      </div>
    </SharedModal>
  );
}
