import React, { useState, useCallback, useEffect } from "react";
import { Button, Input, Tooltip } from "@agentscope-ai/design";
import { Switch } from "antd";
import {
  ShieldCheck,
  ShieldX,
  ShieldAlert,
  KeyRound,
  Unlink,
  ExternalLink,
  Info,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import api from "../../../../api";
import type { MCPClientOAuthStatus } from "../../../../api/types";
import { openExternalPopup } from "../../../../utils/openExternalLink";

interface MCPOAuthSectionProps {
  /** MCP server URL — used for OAuth discovery */
  url: string;
  /** Client key (must already exist for re-auth; leave blank for new client) */
  clientKey?: string;
  /** Called when OAuth auth state changes (authorized or revoked) */
  onAuthChanged?: () => void;
  /** Whether this section is inside the "create" modal (no clientKey yet) */
  isNewClient?: boolean;
  /** Current OAuth status from the server (for existing clients) */
  currentOAuthStatus?: MCPClientOAuthStatus | null;
  /** Whether OAuth is toggled on */
  oauthEnabled?: boolean;
  /** External OAuth params controlled by parent */
  clientId?: string;
  scope?: string;
  authEndpoint?: string;
  tokenEndpoint?: string;
  onClientIdChange?: (v: string) => void;
  onScopeChange?: (v: string) => void;
  onAuthEndpointChange?: (v: string) => void;
  onTokenEndpointChange?: (v: string) => void;
}

type OAuthPhase =
  | "idle"
  | "starting"
  | "waiting"
  | "success"
  | "error"
  | "revoking";

const OAUTH_MESSAGE_TYPE = "mcp-oauth";
const OAUTH_STORAGE_KEY = "mcp_oauth_result";

function openOAuthAuthorizationUrl(authUrl: string): Window | null | undefined {
  return openExternalPopup(
    authUrl,
    "mcp-oauth-popup",
    "width=520,height=680,menubar=no,toolbar=no,location=yes,status=no",
  );
}

export const MCPOAuthSection: React.FC<MCPOAuthSectionProps> = ({
  url,
  clientKey,
  onAuthChanged,
  isNewClient = false,
  currentOAuthStatus,
  oauthEnabled = false,
  clientId = "",
  scope = "",
  authEndpoint = "",
  tokenEndpoint = "",
  onClientIdChange,
  onScopeChange,
  onAuthEndpointChange,
  onTokenEndpointChange,
}) => {
  const { t } = useTranslation();

  const [phase, setPhase] = useState<OAuthPhase>("idle");
  const [errorMsg, setErrorMsg] = useState("");
  const [showAdvanced, setShowAdvanced] = useState(false);

  const cleanupRef = React.useRef<(() => void) | null>(null);

  // Poll backend every 2s when waiting, for existing clients
  useEffect(() => {
    if (phase !== "waiting" || !clientKey) return;
    const timer = setInterval(async () => {
      try {
        const st = await api.getOAuthStatus(clientKey);
        if (st.authorized) {
          cleanupRef.current?.();
          localStorage.removeItem(OAUTH_STORAGE_KEY);
          setPhase("success");
          onAuthChanged?.();
        }
      } catch {
        // ignore
      }
    }, 2000);
    return () => clearInterval(timer);
  }, [phase, clientKey, onAuthChanged]);

  // Determine combined authorized state
  const isAuthorized =
    phase === "success" ||
    (!isNewClient &&
      phase === "idle" &&
      currentOAuthStatus?.authorized === true);

  const isExpired =
    !isNewClient &&
    phase === "idle" &&
    currentOAuthStatus?.authorized &&
    currentOAuthStatus.expires_at > 0 &&
    currentOAuthStatus.expires_at < Date.now() / 1000;

  // Capture before any type narrowing caused by isAuthorized/isExpired guards
  const isRevoking = phase === "revoking";

  useEffect(() => {
    return () => {
      cleanupRef.current?.();
    };
  }, []);

  const handleStartOAuth = useCallback(async () => {
    if (!url.trim()) {
      setErrorMsg(t("mcp.oauth.noUrl"));
      return;
    }
    if (!clientKey) {
      setErrorMsg(t("mcp.oauth.noClientKey"));
      return;
    }

    setPhase("starting");
    setErrorMsg("");
    cleanupRef.current?.();

    // Clear any stale result from a previous attempt
    localStorage.removeItem(OAUTH_STORAGE_KEY);

    try {
      const resp = await api.startOAuth(clientKey, {
        url,
        scope,
        client_id: clientId,
        auth_endpoint: authEndpoint,
        token_endpoint: tokenEndpoint,
      });

      setPhase("waiting");

      const popup = openOAuthAuthorizationUrl(resp.auth_url);
      if (popup === undefined) {
        setPhase("error");
        setErrorMsg(t("mcp.oauth.popupBlocked"));
        return;
      }

      let pollInterval: ReturnType<typeof setInterval> | null = null;
      let didFinish = false;
      let checkingClosedPopup = false;
      // eslint-disable-next-line prefer-const
      let cleanupFn = () => {};

      const finishSuccess = () => {
        if (didFinish) return;
        didFinish = true;
        cleanupFn();
        localStorage.removeItem(OAUTH_STORAGE_KEY);
        setPhase("success");
        onAuthChanged?.();
      };

      const finishError = (message: string) => {
        if (didFinish) return;
        didFinish = true;
        cleanupFn();
        localStorage.removeItem(OAUTH_STORAGE_KEY);
        setPhase("error");
        setErrorMsg(message);
      };

      const onResult = (status: string, errText?: string) => {
        if (status === "success") {
          finishSuccess();
        } else {
          finishError(errText || t("mcp.oauth.authFailed"));
        }
      };

      const syncOAuthStatus = async (): Promise<boolean> => {
        try {
          const st = await api.getOAuthStatus(clientKey);
          if (st.authorized) {
            finishSuccess();
            return true;
          }
        } catch {
          // ignore
        }
        return false;
      };

      // Primary: postMessage (works when window.opener is available)
      // Restrict to same origin to prevent malicious pages from faking success.
      const handleMessage = (event: MessageEvent) => {
        if (event.origin !== window.location.origin) return;
        if (event.data?.type !== OAUTH_MESSAGE_TYPE) return;
        onResult(event.data.status, event.data.error);
      };

      // Secondary: localStorage storage event (works cross-origin, same host)
      const handleStorage = (event: StorageEvent) => {
        if (event.key !== OAUTH_STORAGE_KEY || !event.newValue) return;
        try {
          const data = JSON.parse(event.newValue);
          if (data?.type !== OAUTH_MESSAGE_TYPE) return;
          onResult(data.status, data.error);
        } catch {
          // ignore malformed value
        }
      };

      // Popup windows can report closure; external browsers cannot, so Tauri
      // completion is handled by the phase-level backend polling above.
      if (popup) {
        pollInterval = setInterval(async () => {
          if (!popup.closed || checkingClosedPopup || didFinish) return;
          checkingClosedPopup = true;

          const authorized = await syncOAuthStatus();
          if (!authorized) {
            finishError(t("mcp.oauth.windowClosed"));
          }
        }, 800);
      }

      cleanupFn = () => {
        window.removeEventListener("message", handleMessage);
        window.removeEventListener("storage", handleStorage);
        if (pollInterval) clearInterval(pollInterval);
        cleanupRef.current = null;
      };

      window.addEventListener("message", handleMessage);
      window.addEventListener("storage", handleStorage);
      cleanupRef.current = cleanupFn;
    } catch (err: unknown) {
      const msg =
        err instanceof Error ? err.message : t("mcp.oauth.startFailed");
      setPhase("error");
      setErrorMsg(msg);
    }
  }, [
    url,
    clientKey,
    scope,
    clientId,
    authEndpoint,
    tokenEndpoint,
    onAuthChanged,
    t,
  ]);

  const handleCancelOAuth = useCallback(() => {
    cleanupRef.current?.();
    localStorage.removeItem(OAUTH_STORAGE_KEY);
    setPhase("idle");
    setErrorMsg("");
  }, []);

  const handleRevoke = useCallback(async () => {
    if (!clientKey) return;
    setPhase("revoking");
    try {
      await api.revokeOAuth(clientKey);
      setPhase("idle");
      onAuthChanged?.();
    } catch {
      setPhase("idle");
    }
  }, [clientKey, onAuthChanged]);

  if (!oauthEnabled) {
    return null;
  }

  return (
    <div style={sectionStyle}>
      {/* Status badge */}
      <div style={statusRowStyle}>
        {isExpired ? (
          <OAuthBadge
            icon={<ShieldAlert size={14} />}
            label={t("mcp.oauth.expired")}
            color="#e67e22"
          />
        ) : isAuthorized ? (
          <OAuthBadge
            icon={<ShieldCheck size={14} />}
            label={t("mcp.oauth.authorized")}
            color="#27ae60"
          />
        ) : phase === "waiting" ? (
          <OAuthBadge
            icon={<KeyRound size={14} />}
            label={t("mcp.oauth.waiting")}
            color="#2980b9"
          />
        ) : phase === "error" ? (
          <OAuthBadge
            icon={<ShieldX size={14} />}
            label={t("mcp.oauth.failed")}
            color="#c0392b"
          />
        ) : (
          <OAuthBadge
            icon={<ShieldX size={14} />}
            label={t("mcp.oauth.notAuthorized")}
            color="#7f8c8d"
          />
        )}

        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {(isAuthorized || isExpired) && clientKey && (
            <Button size="small" onClick={handleRevoke} loading={isRevoking}>
              <span
                style={{ display: "inline-flex", alignItems: "center", gap: 4 }}
              >
                <Unlink size={12} />
                {t("mcp.oauth.revoke")}
              </span>
            </Button>
          )}
          {phase === "waiting" && (
            <Button size="small" onClick={handleCancelOAuth}>
              {t("common.cancel")}
            </Button>
          )}
          <Button
            size="small"
            type={isAuthorized && !isExpired ? "default" : "primary"}
            onClick={handleStartOAuth}
            loading={phase === "starting" || phase === "waiting"}
            disabled={!url.trim()}
          >
            <span
              style={{ display: "inline-flex", alignItems: "center", gap: 4 }}
            >
              <ExternalLink size={12} />
              {isAuthorized && !isExpired
                ? t("mcp.oauth.reauthorize")
                : t("mcp.oauth.authorize")}
            </span>
          </Button>
        </div>
      </div>

      {errorMsg && <p style={errorStyle}>{errorMsg}</p>}

      {/* Advanced fields (client_id, scope, manual endpoints) */}
      <div
        style={{ marginTop: 8, cursor: "pointer", color: "#888", fontSize: 12 }}
        onClick={() => setShowAdvanced((v) => !v)}
      >
        <Info size={11} style={{ verticalAlign: "middle", marginRight: 4 }} />
        {showAdvanced
          ? t("mcp.oauth.hideAdvanced")
          : t("mcp.oauth.showAdvanced")}
      </div>

      {showAdvanced && (
        <div style={advancedStyle}>
          <label style={labelStyle}>{t("mcp.oauth.clientId")}</label>
          <Input
            size="small"
            placeholder={t("mcp.oauth.clientIdPlaceholder")}
            value={clientId}
            onChange={(e) => onClientIdChange?.(e.target.value)}
          />

          <label style={{ ...labelStyle, marginTop: 8 }}>
            {t("mcp.oauth.scope")}
          </label>
          <Input
            size="small"
            placeholder={t("mcp.oauth.scopePlaceholder")}
            value={scope}
            onChange={(e) => onScopeChange?.(e.target.value)}
          />

          <Tooltip title={t("mcp.oauth.endpointHint")}>
            <label style={{ ...labelStyle, marginTop: 8 }}>
              {t("mcp.oauth.authEndpoint")}
            </label>
          </Tooltip>
          <Input
            size="small"
            placeholder="https://auth.example.com/authorize"
            value={authEndpoint}
            onChange={(e) => onAuthEndpointChange?.(e.target.value)}
          />

          <label style={{ ...labelStyle, marginTop: 8 }}>
            {t("mcp.oauth.tokenEndpoint")}
          </label>
          <Input
            size="small"
            placeholder="https://auth.example.com/token"
            value={tokenEndpoint}
            onChange={(e) => onTokenEndpointChange?.(e.target.value)}
          />
        </div>
      )}
    </div>
  );
};

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

interface OAuthBadgeProps {
  icon: React.ReactNode;
  label: string;
  color: string;
}

const OAuthBadge: React.FC<OAuthBadgeProps> = ({ icon, label, color }) => (
  <span style={{ ...badgeStyle, color, borderColor: color }}>
    {icon}
    <span style={{ marginLeft: 4 }}>{label}</span>
  </span>
);

// Toggle row shown in the parent form to enable/disable OAuth
interface OAuthToggleRowProps {
  enabled: boolean;
  onChange: (v: boolean) => void;
  label?: string;
}

export const OAuthToggleRow: React.FC<OAuthToggleRowProps> = ({
  enabled,
  onChange,
  label,
}) => {
  const { t } = useTranslation();
  return (
    <div style={toggleRowStyle}>
      <KeyRound size={14} style={{ color: "#888" }} />
      <span style={{ marginLeft: 6, fontSize: 13, color: "#555" }}>
        {label ?? t("mcp.oauth.enableOAuth")}
      </span>
      <Switch
        size="small"
        checked={enabled}
        onChange={onChange}
        style={{ marginLeft: "auto" }}
      />
    </div>
  );
};

// ---------------------------------------------------------------------------
// Inline styles (keeps JSX concise, avoids extra CSS module entries)
// ---------------------------------------------------------------------------

const sectionStyle: React.CSSProperties = {
  background: "#f8f9fa",
  border: "1px solid #e9ecef",
  borderRadius: 8,
  padding: "12px 14px",
  marginTop: 8,
};

const statusRowStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 8,
};

const badgeStyle: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  fontSize: 12,
  padding: "2px 8px",
  borderRadius: 12,
  border: "1px solid",
  background: "white",
};

const errorStyle: React.CSSProperties = {
  color: "#c0392b",
  fontSize: 12,
  marginTop: 6,
  marginBottom: 0,
};

const advancedStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 4,
  marginTop: 10,
  padding: "10px 12px",
  background: "white",
  borderRadius: 6,
  border: "1px solid #e9ecef",
};

const labelStyle: React.CSSProperties = {
  fontSize: 11,
  color: "#888",
  marginBottom: 2,
};

const toggleRowStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  padding: "6px 0",
};
