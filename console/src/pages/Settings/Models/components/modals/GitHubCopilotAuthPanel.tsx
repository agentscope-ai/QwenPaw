import { useCallback, useEffect, useRef, useState } from "react";
import { Button, Modal } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import {
  CheckCircleFilled,
  CloseCircleFilled,
  CopyOutlined,
  ExportOutlined,
  GithubOutlined,
  LoadingOutlined,
} from "@ant-design/icons";
import api from "../../../../../api";
import { useAppMessage } from "../../../../../hooks/useAppMessage";
import type {
  DeviceCodeStart,
  OAuthStatus,
} from "../../../../../api/types/provider";

interface GitHubCopilotAuthPanelProps {
  providerId: string;
  initialStatus?: {
    is_authenticated?: boolean;
    oauth_user_login?: string;
  };
  onAuthChanged: () => void;
}

const POLL_INTERVAL_MS = 3000;

export function GitHubCopilotAuthPanel({
  providerId,
  initialStatus,
  onAuthChanged,
}: GitHubCopilotAuthPanelProps) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [status, setStatus] = useState<OAuthStatus>(() => ({
    status: initialStatus?.is_authenticated ? "authorized" : "not_started",
    message: "",
    is_authenticated: Boolean(initialStatus?.is_authenticated),
    login: initialStatus?.oauth_user_login ?? "",
  }));
  const [device, setDevice] = useState<DeviceCodeStart | null>(null);
  const [starting, setStarting] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const mountedRef = useRef(true);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const refreshStatus = useCallback(async () => {
    try {
      const next = await api.getProviderOAuthStatus(providerId);
      if (!mountedRef.current) return next;
      setStatus(next);
      if (next.status === "authorized") {
        stopPolling();
        setDevice(null);
        onAuthChanged();
      } else if (next.status === "error") {
        stopPolling();
        setDevice(null);
      }
      return next;
    } catch (err) {
      // Silent: polling errors are transient.
      return null;
    }
  }, [providerId, onAuthChanged, stopPolling]);

  useEffect(() => {
    mountedRef.current = true;
    void refreshStatus();
    return () => {
      mountedRef.current = false;
      stopPolling();
    };
  }, [refreshStatus, stopPolling]);

  const handleSignIn = async () => {
    setStarting(true);
    try {
      const start = await api.startProviderOAuth(providerId);
      setDevice(start);
      setStatus((prev) => ({
        ...prev,
        status: "pending",
        message: t("models.copilotPolling"),
      }));
      stopPolling();
      pollRef.current = setInterval(() => {
        void refreshStatus();
      }, POLL_INTERVAL_MS);
    } catch (err) {
      const errMsg =
        err instanceof Error ? err.message : t("models.copilotSignInFailed");
      message.error(errMsg);
    } finally {
      setStarting(false);
    }
  };

  const handleSignOut = () => {
    Modal.confirm({
      title: t("models.copilotSignOut"),
      content: t("models.copilotSignOutConfirm"),
      okText: t("models.copilotSignOut"),
      okButtonProps: { danger: true },
      cancelText: t("models.cancel"),
      onOk: async () => {
        setSigningOut(true);
        try {
          const next = await api.logoutProviderOAuth(providerId);
          stopPolling();
          setDevice(null);
          setStatus(next);
          message.success(t("models.copilotSignOutSuccess"));
          onAuthChanged();
        } catch (err) {
          const errMsg =
            err instanceof Error ? err.message : t("models.failedToRevoke");
          message.error(errMsg);
        } finally {
          setSigningOut(false);
        }
      },
    });
  };

  const handleCopy = async () => {
    if (!device?.user_code) return;
    try {
      await navigator.clipboard.writeText(device.user_code);
      message.success(t("models.copilotCodeCopied"));
    } catch {
      // ignore
    }
  };

  const renderStatusBadge = () => {
    if (status.status === "authorized") {
      return (
        <span style={{ color: "#52c41a", display: "inline-flex", gap: 6 }}>
          <CheckCircleFilled />
          {t("models.copilotStatusAuthorized", {
            login: status.login || "",
          })}
        </span>
      );
    }
    if (status.status === "pending") {
      return (
        <span style={{ color: "#faad14", display: "inline-flex", gap: 6 }}>
          <LoadingOutlined />
          {t("models.copilotStatusPending")}
        </span>
      );
    }
    if (status.status === "error") {
      return (
        <span style={{ color: "#ff4d4f", display: "inline-flex", gap: 6 }}>
          <CloseCircleFilled />
          {t("models.copilotStatusError")}
          {status.message ? `: ${status.message}` : ""}
        </span>
      );
    }
    return (
      <span style={{ color: "rgba(0,0,0,0.55)" }}>
        {t("models.copilotStatusNotStarted")}
      </span>
    );
  };

  return (
    <div
      style={{
        border: "1px solid rgba(0,0,0,0.08)",
        borderRadius: 8,
        padding: 16,
        marginBottom: 16,
        background: "rgba(0,0,0,0.02)",
      }}
    >
      <div
        style={{
          fontWeight: 600,
          marginBottom: 8,
          display: "flex",
          alignItems: "center",
          gap: 8,
        }}
      >
        <GithubOutlined />
        {t("models.copilotAuthTitle")}
      </div>
      <div
        style={{
          fontSize: 13,
          color: "rgba(0,0,0,0.65)",
          marginBottom: 12,
          lineHeight: 1.6,
        }}
      >
        {t("models.copilotAuthDescription")}
      </div>

      <div style={{ marginBottom: 12 }}>
        <span style={{ color: "rgba(0,0,0,0.55)", marginRight: 8 }}>
          {t("models.copilotStatusLabel")}:
        </span>
        {renderStatusBadge()}
      </div>

      {device && status.status === "pending" && (
        <div
          style={{
            background: "#fff",
            border: "1px dashed rgba(0,0,0,0.15)",
            borderRadius: 8,
            padding: 12,
            marginBottom: 12,
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 12,
              marginBottom: 10,
            }}
          >
            <span
              style={{ color: "rgba(0,0,0,0.55)", minWidth: 96, fontSize: 13 }}
            >
              {t("models.copilotUserCode")}:
            </span>
            <code
              style={{
                fontSize: 18,
                fontWeight: 600,
                letterSpacing: 2,
                background: "rgba(0,0,0,0.05)",
                padding: "4px 10px",
                borderRadius: 4,
              }}
            >
              {device.user_code}
            </code>
            <Button size="small" icon={<CopyOutlined />} onClick={handleCopy}>
              {t("models.copilotCopyCode")}
            </Button>
          </div>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 12,
              marginBottom: 10,
            }}
          >
            <span
              style={{ color: "rgba(0,0,0,0.55)", minWidth: 96, fontSize: 13 }}
            >
              {t("models.copilotVerificationUrl")}:
            </span>
            <a
              href={device.verification_uri}
              target="_blank"
              rel="noopener noreferrer"
              style={{ wordBreak: "break-all" }}
            >
              {device.verification_uri}
            </a>
            <Button
              size="small"
              icon={<ExportOutlined />}
              onClick={() =>
                window.open(
                  device.verification_uri,
                  "_blank",
                  "noopener,noreferrer",
                )
              }
            >
              {t("models.copilotOpenVerification")}
            </Button>
          </div>
          <div style={{ fontSize: 12, color: "rgba(0,0,0,0.55)" }}>
            {t("models.copilotInstructions")}
          </div>
        </div>
      )}

      <div style={{ display: "flex", gap: 8 }}>
        {status.is_authenticated ? (
          <Button danger loading={signingOut} onClick={handleSignOut}>
            {t("models.copilotSignOut")}
          </Button>
        ) : (
          <Button
            type="primary"
            icon={<GithubOutlined />}
            loading={starting || status.status === "pending"}
            onClick={handleSignIn}
          >
            {t("models.copilotSignIn")}
          </Button>
        )}
      </div>
    </div>
  );
}
