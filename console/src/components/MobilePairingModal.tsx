import { Button, Modal } from "@agentscope-ai/design";
import { Alert, Segmented, Spin } from "antd";
import {
  Cloud,
  ExternalLink,
  RefreshCw,
  ShieldCheck,
  Smartphone,
  Wifi,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { buildAuthHeaders } from "../api/authHeaders";
import { getApiUrl } from "../api/config";
import { openExternalLink } from "../utils/openExternalLink";
import styles from "./MobilePairingModal.module.less";

interface PairingResponse {
  qrcode_img: string;
  expires_at: number;
}

interface RelayStatus {
  status: "not_connected" | "authorization_pending" | "connected";
  verification_uri?: string | null;
  user_code?: string | null;
  interval?: number | null;
}

type PairingMode = "direct" | "relay";

interface MobilePairingModalProps {
  open: boolean;
  onClose: () => void;
}

export function MobilePairingModal({ open, onClose }: MobilePairingModalProps) {
  const { t } = useTranslation();
  const [mode, setMode] = useState<PairingMode>("direct");
  const [direct, setDirect] = useState<PairingResponse | null>(null);
  const [relay, setRelay] = useState<PairingResponse | null>(null);
  const [relayStatus, setRelayStatus] = useState<RelayStatus | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [remaining, setRemaining] = useState(0);

  const requestJson = useCallback(
    async <T,>(path: string, init: RequestInit = {}): Promise<T> => {
      const response = await fetch(getApiUrl(path), {
        ...init,
        headers: {
          ...(init.body ? { "Content-Type": "application/json" } : {}),
          ...buildAuthHeaders(),
          ...init.headers,
        },
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        const detail = body.detail;
        const message = typeof detail === "string" ? detail : detail?.message;
        throw new Error(message || t("mobilePairing.errors.request"));
      }
      return response.json() as Promise<T>;
    },
    [t],
  );

  const createDirectPairing = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setDirect(
        await requestJson<PairingResponse>("/auth/pairing", {
          method: "POST",
          body: JSON.stringify({ base_url: window.location.origin }),
        }),
      );
    } catch (caught) {
      setDirect(null);
      setError(errorMessage(caught, t("mobilePairing.errors.direct")));
    } finally {
      setLoading(false);
    }
  }, [requestJson, t]);

  const createRelayPairing = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setRelay(
        await requestJson<PairingResponse>("/remote-access/platform/pairing", {
          method: "POST",
        }),
      );
    } catch (caught) {
      setRelay(null);
      setError(errorMessage(caught, t("mobilePairing.errors.relay")));
    } finally {
      setLoading(false);
    }
  }, [requestJson, t]);

  const loadRelayStatus = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const status = await requestJson<RelayStatus>("/remote-access/platform");
      setRelayStatus(status);
      if (status.status === "connected") await createRelayPairing();
    } catch (caught) {
      setError(errorMessage(caught, t("mobilePairing.errors.status")));
    } finally {
      setLoading(false);
    }
  }, [createRelayPairing, requestJson, t]);

  const startRelayAuthorization = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const status = await requestJson<RelayStatus>(
        "/remote-access/platform/authorize",
        {
          method: "POST",
          body: JSON.stringify({
            name: `QwenPaw · ${window.location.hostname || "Local"}`,
          }),
        },
      );
      setRelayStatus(status);
      if (status.verification_uri) openExternalLink(status.verification_uri);
    } catch (caught) {
      setError(errorMessage(caught, t("mobilePairing.errors.authorize")));
    } finally {
      setLoading(false);
    }
  }, [requestJson, t]);

  const completeRelayAuthorization = useCallback(async () => {
    try {
      const status = await requestJson<RelayStatus>(
        "/remote-access/platform/complete",
        { method: "POST" },
      );
      setRelayStatus(status);
      if (status.status === "connected") await createRelayPairing();
    } catch (caught) {
      const message = errorMessage(caught, "");
      if (!/pending|等待|slow_down/i.test(message)) setError(message);
    }
  }, [createRelayPairing, requestJson]);

  useEffect(() => {
    if (!open) {
      setDirect(null);
      setRelay(null);
      setRelayStatus(null);
      setError("");
      setMode("direct");
      return;
    }
    if (mode === "direct") void createDirectPairing();
    else void loadRelayStatus();
  }, [createDirectPairing, loadRelayStatus, mode, open]);

  useEffect(() => {
    if (!open || relayStatus?.status !== "authorization_pending") return;
    const delay = Math.max(3, relayStatus.interval ?? 5) * 1000;
    const timer = window.setInterval(
      () => void completeRelayAuthorization(),
      delay,
    );
    return () => window.clearInterval(timer);
  }, [completeRelayAuthorization, open, relayStatus]);

  const activePairing = mode === "direct" ? direct : relay;
  useEffect(() => {
    if (!activePairing) {
      setRemaining(0);
      return;
    }
    const update = () =>
      setRemaining(
        Math.max(0, activePairing.expires_at - Math.floor(Date.now() / 1000)),
      );
    update();
    const timer = window.setInterval(update, 1000);
    return () => window.clearInterval(timer);
  }, [activePairing]);

  const refresh = mode === "direct" ? createDirectPairing : createRelayPairing;
  const awaitingAuthorization =
    mode === "relay" && relayStatus?.status === "authorization_pending";
  const needsAuthorization =
    mode === "relay" && relayStatus?.status === "not_connected";

  return (
    <Modal
      centered
      footer={null}
      onCancel={onClose}
      open={open}
      title={null}
      width={440}
    >
      <div className={styles.root}>
        <div className={styles.icon} aria-hidden="true">
          <Smartphone size={24} />
        </div>
        <h2 className={styles.title}>{t("mobilePairing.title")}</h2>
        <p className={styles.subtitle}>{t("mobilePairing.subtitle")}</p>

        <Segmented<PairingMode>
          block
          className={styles.segmented}
          onChange={setMode}
          options={[
            {
              label: t("mobilePairing.direct"),
              value: "direct",
              icon: <Wifi size={15} />,
            },
            {
              label: t("mobilePairing.relay"),
              value: "relay",
              icon: <Cloud size={15} />,
            },
          ]}
          value={mode}
        />

        <div className={styles.content} aria-live="polite">
          {loading ? <Spin /> : null}
          {!loading && activePairing && remaining > 0 ? (
            <img
              alt={t("mobilePairing.qrAlt")}
              className={styles.qr}
              src={`data:image/png;base64,${activePairing.qrcode_img}`}
            />
          ) : null}
          {!loading && activePairing && remaining === 0 ? (
            <Button icon={<RefreshCw size={16} />} onClick={refresh}>
              {t("mobilePairing.newCode")}
            </Button>
          ) : null}
          {!loading && needsAuthorization ? (
            <div className={styles.authorization}>
              <Cloud size={25} aria-hidden="true" />
              <strong>{t("mobilePairing.enableRelay")}</strong>
              <span>{t("mobilePairing.enableRelayHint")}</span>
              <Button type="primary" onClick={startRelayAuthorization}>
                {t("mobilePairing.authorize")}
              </Button>
            </div>
          ) : null}
          {!loading && awaitingAuthorization ? (
            <div className={styles.authorization}>
              <ShieldCheck size={25} aria-hidden="true" />
              <strong>{t("mobilePairing.waitingApproval")}</strong>
              <span>{t("mobilePairing.userCode")}</span>
              <code className={styles.userCode}>{relayStatus.user_code}</code>
              <Button
                icon={<ExternalLink size={16} />}
                onClick={() =>
                  relayStatus.verification_uri &&
                  openExternalLink(relayStatus.verification_uri)
                }
              >
                {t("mobilePairing.openPlatform")}
              </Button>
            </div>
          ) : null}
        </div>

        {error ? <Alert message={error} showIcon type="error" /> : null}
        {activePairing && remaining > 0 ? (
          <div className={styles.expiry}>
            <ShieldCheck size={15} aria-hidden="true" />
            {t("mobilePairing.expires", { seconds: remaining })}
          </div>
        ) : null}
        <p className={styles.privacy}>
          {mode === "direct"
            ? t("mobilePairing.directHint")
            : t("mobilePairing.relayHint")}
        </p>
      </div>
    </Modal>
  );
}

function errorMessage(value: unknown, fallback: string): string {
  return value instanceof Error && value.message ? value.message : fallback;
}
