import {
  Card,
  Button,
  Modal,
  Tooltip,
  Input,
  Empty,
  Tag,
} from "@agentscope-ai/design";
import { Spin } from "antd";
import type { MCPClientInfo, MCPToolInfo } from "../../../../api/types";
import { useTranslation } from "react-i18next";
import React, { useEffect, useRef, useState, useCallback } from "react";
import { useTheme } from "../../../../contexts/ThemeContext";
import {
  EyeOutlined,
  EyeInvisibleOutlined,
  ToolOutlined,
  LoginOutlined,
} from "@ant-design/icons";
import { ShieldCheck, ShieldAlert, ShieldX } from "lucide-react";
import api from "../../../../api";
import { useAppMessage } from "../../../../hooks/useAppMessage";
import styles from "../index.module.less";

interface MCPClientUpdate {
  name?: string;
  description?: string;
  command?: string;
  enabled?: boolean;
  transport?: "stdio" | "streamable_http" | "sse";
  url?: string;
  headers?: Record<string, string>;
  args?: string[];
  env?: Record<string, string>;
  cwd?: string;
}

interface MCPClientCardProps {
  client: MCPClientInfo;
  onToggle: (client: MCPClientInfo, e: React.MouseEvent) => void;
  onDelete: (client: MCPClientInfo, e: React.MouseEvent) => void;
  onUpdate: (key: string, updates: MCPClientUpdate) => Promise<boolean>;
  onReload?: () => Promise<void> | void;
}

export const MCPClientCard = React.memo(function MCPClientCard({
  client,
  onToggle,
  onDelete,
  onUpdate,
  onReload,
}: MCPClientCardProps) {
  const { t } = useTranslation();
  const { isDark } = useTheme();
  const { message } = useAppMessage();
  const [isHovered, setIsHovered] = useState(false);
  const [jsonModalOpen, setJsonModalOpen] = useState(false);
  const [deleteModalOpen, setDeleteModalOpen] = useState(false);
  const [toolsModalOpen, setToolsModalOpen] = useState(false);
  const [tools, setTools] = useState<MCPToolInfo[]>([]);
  const [toolsLoading, setToolsLoading] = useState(false);
  const [toolsError, setToolsError] = useState<string | null>(null);
  const [editedJson, setEditedJson] = useState("");
  const [isEditing, setIsEditing] = useState(false);

  // ── OAuth modal state ────────────────────────────────────────────────────
  const [authModalOpen, setAuthModalOpen] = useState(false);
  const [authMode, setAuthMode] = useState<"auto" | "paste" | null>(null);
  const [authStarting, setAuthStarting] = useState(false);
  const [authSubmitting, setAuthSubmitting] = useState(false);
  const [authorizeUrl, setAuthorizeUrl] = useState("");
  const [redirectUri, setRedirectUri] = useState("");
  const [pastedCallback, setPastedCallback] = useState("");
  const [authError, setAuthError] = useState<string | null>(null);
  const [authComplete, setAuthComplete] = useState(false);
  const authPollRef = useRef<number | null>(null);
  // Snapshot of ``client.auth_token_expires_at`` taken when the modal opens.
  const authBaselineExpiresAtRef = useRef(0);
  // Public URL editor state (inline in the modal)
  const [showPublicUrlEditor, setShowPublicUrlEditor] = useState(false);
  const [publicUrlInput, setPublicUrlInput] = useState("");
  const [publicUrlSaving, setPublicUrlSaving] = useState(false);

  const stopAuthPoll = useCallback(() => {
    if (authPollRef.current !== null) {
      window.clearInterval(authPollRef.current);
      authPollRef.current = null;
    }
  }, []);

  useEffect(() => stopAuthPoll, [stopAuthPoll]);

  // Listen for the OAuth callback page's postMessage so we can react
  // immediately instead of waiting for the next polling tick.
  useEffect(() => {
    function onMessage(ev: MessageEvent) {
      const data = ev?.data;
      if (
        data &&
        typeof data === "object" &&
        data.type === "qwenpaw:mcp-oauth" &&
        data.status === "success" &&
        data.clientKey === client.key
      ) {
        onReload?.();
      }
    }
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [client.key, onReload]);

  // Determine if MCP client is remote or local based on command
  const isRemote =
    client.transport === "streamable_http" || client.transport === "sse";
  const clientType = isRemote ? "Remote" : "Local";

  const now = Date.now() / 1000;
  const tokenExp = client.auth_token_expires_at || 0;
  const isOauthAuthorized =
    client.auth_state === "oauth_active" && (tokenExp === 0 || tokenExp > now);
  const isOauthExpired =
    client.auth_state === "oauth_expired" ||
    (client.auth_state === "oauth_active" && tokenExp > 0 && tokenExp <= now);
  const hasOauth = isRemote;

  const handleToggleClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    onToggle(client, e);
  };

  const handleDeleteClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    setDeleteModalOpen(true);
  };

  const confirmDelete = () => {
    setDeleteModalOpen(false);
    onDelete(client, null as unknown as React.MouseEvent);
  };

  const handleCardClick = () => {
    const jsonStr = JSON.stringify(client, null, 2);
    setEditedJson(jsonStr);
    setIsEditing(false);
    setJsonModalOpen(true);
  };

  const handleSaveJson = async () => {
    try {
      const parsed = JSON.parse(editedJson);
      const { key: _key, ...updates } = parsed;

      // Send all updates directly to backend, let backend handle env masking check
      const success = await onUpdate(client.key, updates);
      if (success) {
        setJsonModalOpen(false);
        setIsEditing(false);
      }
    } catch {
      alert("Invalid JSON format");
    }
  };

  const handleShowTools = useCallback(
    async (e: React.MouseEvent) => {
      e.stopPropagation();
      setToolsModalOpen(true);
      setToolsLoading(true);
      setToolsError(null);
      setTools([]);
      try {
        const data = await api.listMCPTools(client.key);
        setTools(data);
      } catch (err: any) {
        const msg = err?.message || "";
        if (msg.includes("connecting") || msg.includes("not ready")) {
          setToolsError(t("mcp.toolsConnecting"));
        } else {
          setToolsError(msg || t("mcp.toolsLoadError"));
        }
      } finally {
        setToolsLoading(false);
      }
    },
    [client.key, t],
  );

  const clientJson = JSON.stringify(client, null, 2);

  // ── OAuth helpers ────────────────────────────────────────────────────────
  const openAuthModal = useCallback(
    async (e?: React.MouseEvent) => {
      e?.stopPropagation();
      setAuthError(null);
      setAuthorizeUrl("");
      setRedirectUri("");
      setPastedCallback("");
      setAuthMode(null);
      setAuthComplete(false);
      setShowPublicUrlEditor(false);
      authBaselineExpiresAtRef.current = client.auth_token_expires_at || 0;
      setAuthModalOpen(true);
      setAuthStarting(true);
      try {
        const resp = await api.beginMCPOAuth(client.key);
        setAuthorizeUrl(resp.authorize_url);
        setRedirectUri(resp.redirect_uri);
        setAuthMode(resp.mode);
        // Eagerly open the authorize URL in a new tab. Keep the opener link
        // so the callback page can call window.opener.postMessage and
        // window.close() reliably.
        window.open(resp.authorize_url, "_blank");
        if (resp.mode === "auto") {
          // Poll the MCP client metadata as a fallback; the postMessage from
          // the callback page is the fast path. Either signal closes the
          // modal once auth_state flips to oauth_active.
          stopAuthPoll();
          authPollRef.current = window.setInterval(async () => {
            try {
              await onReload?.();
            } catch {
              /* ignore transient errors */
            }
          }, 1500);
        }
      } catch (err: any) {
        setAuthError(err?.message || String(err));
      } finally {
        setAuthStarting(false);
      }
    },
    [client.key, onReload, stopAuthPoll],
  );

  const savePublicUrlAndRestart = useCallback(async () => {
    const url = publicUrlInput.trim();
    if (!url) return;
    setPublicUrlSaving(true);
    setAuthError(null);
    try {
      await api.setPublicUrl(url);
      // Re-run begin with the updated public URL.
      const resp = await api.beginMCPOAuth(client.key);
      setAuthorizeUrl(resp.authorize_url);
      setRedirectUri(resp.redirect_uri);
      setAuthMode(resp.mode);
      setShowPublicUrlEditor(false);
      message.success(t("mcp.oauth.publicUrlSaved"));
    } catch (err: any) {
      setAuthError(err?.message || String(err));
    } finally {
      setPublicUrlSaving(false);
    }
  }, [publicUrlInput, client.key, message, t]);

  const submitPastedCallback = useCallback(async () => {
    setAuthError(null);
    setAuthSubmitting(true);
    try {
      await api.completeMCPOAuth(client.key, pastedCallback.trim());
      stopAuthPoll();
      setAuthComplete(true);
      await onReload?.();
    } catch (err: any) {
      setAuthError(err?.message || String(err));
    } finally {
      setAuthSubmitting(false);
    }
  }, [client.key, pastedCallback, onReload, stopAuthPoll]);

  const cancelAuthModal = useCallback(() => {
    stopAuthPoll();
    setAuthModalOpen(false);
  }, [stopAuthPoll]);

  // Watch ``client.auth_token_expires_at``: when it advances beyond the
  // baseline we know a new token arrived. Instead of closing the modal
  // immediately (which can be too fast for the user to see), we show
  // a success state inside the modal and let the user dismiss it.
  useEffect(() => {
    if (
      authModalOpen &&
      !authComplete &&
      client.auth_state === "oauth_active" &&
      (client.auth_token_expires_at || 0) > authBaselineExpiresAtRef.current
    ) {
      stopAuthPoll();
      setAuthComplete(true);
    }
  }, [
    authModalOpen,
    authComplete,
    client.auth_state,
    client.auth_token_expires_at,
    stopAuthPoll,
  ]);

  const handleSignOut = useCallback(
    async (e?: React.MouseEvent) => {
      e?.stopPropagation();
      try {
        await api.signOutMCPOAuth(client.key, false);
        message.success(t("mcp.oauth.signOutSuccess"));
        await onReload?.();
      } catch (err: any) {
        message.error(err?.message || t("mcp.oauth.signOutError"));
      }
    },
    [client.key, message, t, onReload],
  );

  // ── Derived UI state ─────────────────────────────────────────────────────
  const showAuthRow = isRemote;
  const authDotClass =
    client.auth_state === "oauth_active"
      ? styles.authActive
      : client.auth_state === "oauth_pending"
      ? styles.authPending
      : client.auth_state === "oauth_expired"
      ? styles.authExpired
      : styles.authNone;

  const authLabel =
    client.auth_state === "oauth_active"
      ? t("mcp.oauth.statusActive")
      : client.auth_state === "oauth_pending"
      ? t("mcp.oauth.statusPending")
      : client.auth_state === "oauth_expired"
      ? t("mcp.oauth.statusExpired")
      : t("mcp.oauth.statusNone");

  return (
    <>
      <Card
        hoverable
        onClick={handleCardClick}
        onMouseEnter={() => setIsHovered(true)}
        onMouseLeave={() => setIsHovered(false)}
        className={`${styles.mcpCard} ${
          client.enabled ? styles.enabledCard : ""
        } ${isHovered ? styles.hover : styles.normal}`}
      >
        <div className={styles.cardHeader}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              minWidth: 0,
            }}
          >
            <Tooltip title={client.name}>
              <h3 className={styles.mcpTitle}>{client.name}</h3>
            </Tooltip>
            <span
              className={`${styles.typeBadge} ${
                isRemote ? styles.remote : styles.local
              }`}
            >
              {clientType}
            </span>
            {hasOauth && isOauthExpired && (
              <Tooltip title={t("mcp.oauth.expired")}>
                <ShieldAlert
                  size={13}
                  style={{ color: "#e67e22", flexShrink: 0 }}
                />
              </Tooltip>
            )}
            {hasOauth && isOauthAuthorized && (
              <Tooltip title={t("mcp.oauth.authorized")}>
                <ShieldCheck
                  size={13}
                  style={{ color: "#27ae60", flexShrink: 0 }}
                />
              </Tooltip>
            )}
            {hasOauth && !isOauthAuthorized && !isOauthExpired && (
              <Tooltip title={t("mcp.oauth.notAuthorized")}>
                <ShieldX
                  size={13}
                  style={{ color: "#7f8c8d", flexShrink: 0 }}
                />
              </Tooltip>
            )}
          </div>
          <div className={styles.statusContainer}>
            <span className={styles.statusDot} />
            <span className={styles.statusText}>
              {client.enabled ? t("common.enabled") : t("common.disabled")}
            </span>
          </div>
        </div>

        <p className={styles.mcpDescription}>{client.description || "-"}</p>

        {showAuthRow && (
          <div className={styles.authRow} onClick={(e) => e.stopPropagation()}>
            <span className={`${styles.authDot} ${authDotClass}`} />
            <span>{authLabel}</span>
            {client.auth_state === "oauth_active" && (
              <button
                type="button"
                className={styles.authInlineButton}
                onClick={handleSignOut}
              >
                {t("mcp.oauth.signOut")}
              </button>
            )}
          </div>
        )}

        <div className={styles.cardFooter}>
          <Button
            className={styles.toolsButton}
            onClick={handleShowTools}
            icon={<ToolOutlined />}
            disabled={!client.enabled || toolsLoading}
            loading={toolsLoading}
          >
            {t("mcp.tools")}
          </Button>
          {showAuthRow && (
            <Button
              className={styles.toggleButton}
              onClick={openAuthModal}
              icon={<LoginOutlined />}
              disabled={authStarting}
            >
              {client.auth_state === "oauth_active"
                ? t("mcp.oauth.reauthenticate")
                : t("mcp.oauth.authenticate")}
            </Button>
          )}
          <Button
            className={styles.toggleButton}
            onClick={(e) => {
              e.stopPropagation();
              handleToggleClick(e);
            }}
            icon={client.enabled ? <EyeInvisibleOutlined /> : <EyeOutlined />}
          >
            {client.enabled ? t("common.disable") : t("common.enable")}
          </Button>
          <Button
            className={styles.deleteButton}
            danger
            onClick={(e) => {
              e.stopPropagation();
              handleDeleteClick(e);
            }}
          >
            {t("common.delete")}
          </Button>
        </div>
      </Card>

      <Modal
        title={t("common.confirm")}
        open={deleteModalOpen}
        onOk={confirmDelete}
        onCancel={() => setDeleteModalOpen(false)}
        okText={t("common.confirm")}
        cancelText={t("common.cancel")}
        okButtonProps={{ danger: true }}
      >
        <p>{t("mcp.deleteConfirm")}</p>
      </Modal>

      <Modal
        title={`${client.name} - ${t("mcp.oauth.title")}`}
        open={authModalOpen}
        onCancel={cancelAuthModal}
        footer={
          authComplete ? (
            <div style={{ textAlign: "right" }}>
              <Button type="primary" onClick={cancelAuthModal}>
                {t("common.close")}
              </Button>
            </div>
          ) : (
            <div style={{ textAlign: "right" }}>
              <Button
                onClick={cancelAuthModal}
                style={{ marginRight: 8 }}
                disabled={authSubmitting}
              >
                {t("common.cancel")}
              </Button>
              <Button
                type="primary"
                onClick={submitPastedCallback}
                loading={authSubmitting}
                disabled={!pastedCallback.trim()}
              >
                {t("mcp.oauth.submit")}
              </Button>
            </div>
          )
        }
        width={620}
      >
        {authStarting ? (
          <div className={styles.toolsLoading}>
            <Spin />
            <div className={styles.oauthModalHint}>
              {t("mcp.oauth.preparing")}
            </div>
          </div>
        ) : authComplete ? (
          <div className={styles.oauthSuccess}>
            <div className={styles.oauthSuccessIcon}>&#10003;</div>
            <div className={styles.oauthSuccessTitle}>
              {t("mcp.oauth.completeSuccess")}
            </div>
            <div className={styles.oauthModalHint}>
              {t("mcp.oauth.completeCloseHint")}
            </div>
          </div>
        ) : (
          <>
            {/* Step 1: Open the authorize URL */}
            <div className={styles.oauthModalSection}>
              <div className={styles.oauthModalLabel}>
                {t("mcp.oauth.pasteStep1Title")}
              </div>
              <div className={styles.oauthModalHint}>
                {authMode === "auto"
                  ? t("mcp.oauth.autoHint")
                  : t("mcp.oauth.pasteStep1Hint")}
              </div>
              {authorizeUrl && (
                <Button
                  type="link"
                  onClick={() => window.open(authorizeUrl, "_blank")}
                  style={{ paddingLeft: 0 }}
                >
                  {t("mcp.oauth.openAuthorize")}
                </Button>
              )}
            </div>

            {/* Callback URL display + public URL editor */}
            {redirectUri && (
              <div className={styles.oauthModalSection}>
                <div className={styles.oauthModalLabel}>
                  {t("mcp.oauth.callbackUrlLabel")}
                </div>
                <div className={styles.oauthModalUrl}>{redirectUri}</div>
                <div style={{ marginTop: 6 }}>
                  <Button
                    type="link"
                    size="small"
                    onClick={async () => {
                      if (!showPublicUrlEditor) {
                        try {
                          const resp = await api.getPublicUrl();
                          setPublicUrlInput(resp.public_url);
                        } catch {
                          setPublicUrlInput("");
                        }
                      }
                      setShowPublicUrlEditor(!showPublicUrlEditor);
                    }}
                    style={{ paddingLeft: 0, fontSize: 12 }}
                  >
                    {showPublicUrlEditor
                      ? t("mcp.oauth.hidePublicUrl")
                      : t("mcp.oauth.changePublicUrl")}
                  </Button>
                </div>
                {showPublicUrlEditor && (
                  <div style={{ marginTop: 8 }}>
                    <div className={styles.oauthModalHint}>
                      {t("mcp.oauth.publicUrlHint")}
                    </div>
                    <div style={{ display: "flex", gap: 8 }}>
                      <Input
                        value={publicUrlInput}
                        onChange={(e) => setPublicUrlInput(e.target.value)}
                        placeholder="https://gateway.example.com/qwenpaw-a"
                        disabled={publicUrlSaving}
                        style={{ flex: 1 }}
                      />
                      <Button
                        type="primary"
                        size="small"
                        onClick={savePublicUrlAndRestart}
                        loading={publicUrlSaving}
                        disabled={!publicUrlInput.trim()}
                      >
                        {t("mcp.oauth.saveAndRestart")}
                      </Button>
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* Auto-mode waiting indicator */}
            {authMode === "auto" && (
              <div className={styles.oauthModalSection}>
                <div className={styles.oauthAutoWaiting}>
                  <Spin size="small" />
                  <span style={{ marginLeft: 8 }}>
                    {t("mcp.oauth.autoTitle")}
                  </span>
                </div>
              </div>
            )}

            {/* Step 2: Paste the callback URL */}
            <div className={styles.oauthModalSection}>
              <div className={styles.oauthModalLabel}>
                {t("mcp.oauth.pasteStep2Title")}
              </div>
              <div className={styles.oauthModalHint}>
                {t("mcp.oauth.pasteStep2Hint")}
              </div>
              <Input.TextArea
                value={pastedCallback}
                onChange={(e) => setPastedCallback(e.target.value)}
                autoSize={{ minRows: 3, maxRows: 6 }}
                placeholder="http://localhost:10112/oauth/callback?code=...&state=..."
                disabled={authSubmitting}
              />
            </div>
          </>
        )}

        {authError && <div className={styles.oauthError}>{authError}</div>}
      </Modal>

      <Modal
        title={`${client.name} - ${t("mcp.tools")}`}
        open={toolsModalOpen}
        onCancel={() => setToolsModalOpen(false)}
        footer={
          <div style={{ textAlign: "right" }}>
            <Button onClick={() => setToolsModalOpen(false)}>
              {t("common.close")}
            </Button>
          </div>
        }
        width={700}
      >
        {toolsLoading ? (
          <div className={styles.toolsLoading}>
            <Spin />
          </div>
        ) : toolsError ? (
          <div className={styles.toolsError}>{toolsError}</div>
        ) : tools.length === 0 ? (
          <Empty description={t("mcp.noTools")} />
        ) : (
          <div className={styles.toolsList}>
            {tools.map((tool) => (
              <div key={tool.name} className={styles.toolItem}>
                <div className={styles.toolHeader}>
                  <Tag color="blue">{tool.name}</Tag>
                </div>
                {tool.description && (
                  <p className={styles.toolDescription}>{tool.description}</p>
                )}
                {tool.input_schema &&
                  Object.keys(tool.input_schema).length > 0 && (
                    <details className={styles.toolSchema}>
                      <summary>{t("mcp.toolSchema")}</summary>
                      <pre className={styles.toolSchemaContent}>
                        {JSON.stringify(tool.input_schema, null, 2)}
                      </pre>
                    </details>
                  )}
              </div>
            ))}
          </div>
        )}
      </Modal>

      <Modal
        title={`${client.name} - Configuration`}
        open={jsonModalOpen}
        onCancel={() => setJsonModalOpen(false)}
        footer={
          <div style={{ textAlign: "right" }}>
            <Button
              onClick={() => setJsonModalOpen(false)}
              style={{ marginRight: 8 }}
            >
              {t("common.cancel")}
            </Button>
            {isEditing ? (
              <Button type="primary" onClick={handleSaveJson}>
                {t("common.save")}
              </Button>
            ) : (
              <Button type="primary" onClick={() => setIsEditing(true)}>
                {t("common.edit")}
              </Button>
            )}
          </div>
        }
        width={700}
      >
        <div className={styles.maskedFieldHint}>{t("mcp.maskedFieldHint")}</div>
        {isEditing ? (
          <Input.TextArea
            value={editedJson}
            onChange={(e) => setEditedJson(e.target.value)}
            autoSize={{ minRows: 15, maxRows: 25 }}
            style={{
              fontFamily: "Monaco, Courier New, monospace",
              fontSize: 13,
            }}
          />
        ) : (
          <pre
            style={{
              backgroundColor: isDark ? "#1f1f1f" : "#f5f5f5",
              color: isDark ? "rgba(255,255,255,0.85)" : "rgba(0,0,0,0.88)",
              padding: 16,
              borderRadius: 8,
              maxHeight: 400,
              overflow: "auto",
            }}
          >
            {clientJson}
          </pre>
        )}
      </Modal>
    </>
  );
});
