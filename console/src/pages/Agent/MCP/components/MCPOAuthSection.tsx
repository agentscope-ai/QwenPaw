import React, { useState, useCallback, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import {
  ShieldCheck,
  ShieldX,
  ShieldAlert,
  KeyRound,
  Unlink,
  ExternalLink,
  Info,
  Loader2,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import api from "../../../../api";
import type { MCPClientOAuthStatus } from "../../../../api/types";
import { openExternalLink } from "../../../../utils/openExternalLink";

interface MCPOAuthSectionProps {
  url: string;
  clientKey?: string;
  onAuthChanged?: () => void;
  isNewClient?: boolean;
  currentOAuthStatus?: MCPClientOAuthStatus | null;
  oauthEnabled?: boolean;
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

  useEffect(() => {
    if (phase !== "waiting" || !clientKey) return;
    const timer = setInterval(async () => {
      try {
        const st = await api.getOAuthStatus(clientKey);
        if (st.authorized) {
          setPhase("success");
          onAuthChanged?.();
        }
      } catch {
        // ignore
      }
    }, 2000);
    return () => clearInterval(timer);
  }, [phase, clientKey, onAuthChanged]);

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

  const isRevoking = phase === "revoking";

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

    try {
      const resp = await api.startOAuth(clientKey, {
        url,
        scope,
        client_id: clientId,
        auth_endpoint: authEndpoint,
        token_endpoint: tokenEndpoint,
      });

      setPhase("waiting");
      openExternalLink(resp.auth_url, "_blank", "popup,width=600,height=700");
    } catch (err: unknown) {
      const msg =
        err instanceof Error ? err.message : t("mcp.oauth.startFailed");
      setPhase("error");
      setErrorMsg(msg);
    }
  }, [url, clientKey, scope, clientId, authEndpoint, tokenEndpoint, t]);

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
    <div className="rounded-md border bg-muted/30 p-3 space-y-3">
      <div className="flex items-center justify-between gap-2">
        <OAuthBadge
          isExpired={Boolean(isExpired)}
          isAuthorized={isAuthorized}
          phase={phase}
          t={t}
        />

        <div className="flex items-center gap-2">
          {(isAuthorized || isExpired) && clientKey && (
            <Button
              size="sm"
              variant="outline"
              onClick={handleRevoke}
              disabled={isRevoking}
            >
              {isRevoking && (
                <Loader2 size={12} className="animate-spin mr-1" />
              )}
              <Unlink size={12} className="mr-1" />
              {t("mcp.oauth.revoke")}
            </Button>
          )}
          <Button
            size="sm"
            variant={isAuthorized && !isExpired ? "outline" : "default"}
            onClick={handleStartOAuth}
            disabled={
              !url.trim() || phase === "starting" || phase === "waiting"
            }
          >
            {(phase === "starting" || phase === "waiting") && (
              <Loader2 size={12} className="animate-spin mr-1" />
            )}
            <ExternalLink size={12} className="mr-1" />
            {isAuthorized && !isExpired
              ? t("mcp.oauth.reauthorize")
              : t("mcp.oauth.authorize")}
          </Button>
        </div>
      </div>

      {errorMsg && <p className="text-xs text-destructive">{errorMsg}</p>}

      <div
        className="flex items-center gap-1 text-xs text-muted-foreground cursor-pointer"
        onClick={() => setShowAdvanced((v) => !v)}
      >
        <Info size={11} />
        {showAdvanced
          ? t("mcp.oauth.hideAdvanced")
          : t("mcp.oauth.showAdvanced")}
      </div>

      {showAdvanced && (
        <div className="space-y-2 rounded border bg-background p-3">
          <div>
            <label className="text-xs text-muted-foreground">
              {t("mcp.oauth.clientId")}
            </label>
            <Input
              size={undefined}
              className="h-7 text-xs mt-1"
              placeholder={t("mcp.oauth.clientIdPlaceholder")}
              value={clientId}
              onChange={(e) => onClientIdChange?.(e.target.value)}
            />
          </div>
          <div>
            <label className="text-xs text-muted-foreground">
              {t("mcp.oauth.scope")}
            </label>
            <Input
              className="h-7 text-xs mt-1"
              placeholder={t("mcp.oauth.scopePlaceholder")}
              value={scope}
              onChange={(e) => onScopeChange?.(e.target.value)}
            />
          </div>
          <div>
            <label
              className="text-xs text-muted-foreground"
              title={t("mcp.oauth.endpointHint")}
            >
              {t("mcp.oauth.authEndpoint")}
            </label>
            <Input
              className="h-7 text-xs mt-1"
              placeholder="https://auth.example.com/authorize"
              value={authEndpoint}
              onChange={(e) => onAuthEndpointChange?.(e.target.value)}
            />
          </div>
          <div>
            <label className="text-xs text-muted-foreground">
              {t("mcp.oauth.tokenEndpoint")}
            </label>
            <Input
              className="h-7 text-xs mt-1"
              placeholder="https://auth.example.com/token"
              value={tokenEndpoint}
              onChange={(e) => onTokenEndpointChange?.(e.target.value)}
            />
          </div>
        </div>
      )}
    </div>
  );
};

interface OAuthBadgeProps {
  isExpired: boolean;
  isAuthorized: boolean;
  phase: string;
  t: (key: string) => string;
}

function OAuthBadge({ isExpired, isAuthorized, phase, t }: OAuthBadgeProps) {
  if (isExpired) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full border border-orange-300 bg-white px-2 py-0.5 text-xs text-orange-500">
        <ShieldAlert size={12} />
        {t("mcp.oauth.expired")}
      </span>
    );
  }
  if (isAuthorized) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full border border-green-300 bg-white px-2 py-0.5 text-xs text-green-600">
        <ShieldCheck size={12} />
        {t("mcp.oauth.authorized")}
      </span>
    );
  }
  if (phase === "waiting") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full border border-blue-300 bg-white px-2 py-0.5 text-xs text-blue-600">
        <KeyRound size={12} />
        {t("mcp.oauth.waiting")}
      </span>
    );
  }
  if (phase === "error") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full border border-destructive bg-white px-2 py-0.5 text-xs text-destructive">
        <ShieldX size={12} />
        {t("mcp.oauth.failed")}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-full border border-muted-foreground/30 bg-white px-2 py-0.5 text-xs text-muted-foreground">
      <ShieldX size={12} />
      {t("mcp.oauth.notAuthorized")}
    </span>
  );
}

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
    <div className="flex items-center py-1.5">
      <KeyRound size={14} className="text-muted-foreground" />
      <span className="ml-1.5 text-sm text-muted-foreground">
        {label ?? t("mcp.oauth.enableOAuth")}
      </span>
      <Switch
        checked={enabled}
        onCheckedChange={onChange}
        className="ml-auto"
      />
    </div>
  );
};
