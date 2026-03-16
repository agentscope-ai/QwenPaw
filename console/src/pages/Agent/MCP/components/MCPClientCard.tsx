import { Card, Button, Modal, Tooltip, message } from "@agentscope-ai/design";
import { DeleteOutlined, KeyOutlined, DisconnectOutlined } from "@ant-design/icons";
import { Server } from "lucide-react";
import type { MCPClientInfo } from "../../../../api/types";
import { useTranslation } from "react-i18next";
import { useState, useEffect, useCallback } from "react";
import styles from "../index.module.less";
import api from "../../../../api";

interface MCPClientCardProps {
  client: MCPClientInfo;
  onToggle: (client: MCPClientInfo, e: React.MouseEvent) => void;
  onDelete: (client: MCPClientInfo, e: React.MouseEvent) => void;
  onUpdate: (key: string, updates: any) => Promise<boolean>;
  onRefresh?: () => void;
  isHovered: boolean;
  onMouseEnter: () => void;
  onMouseLeave: () => void;
}

export function MCPClientCard({
  client,
  onToggle,
  onDelete,
  onUpdate,
  onRefresh,
  isHovered,
  onMouseEnter,
  onMouseLeave,
}: MCPClientCardProps) {
  const { t } = useTranslation();
  const [jsonModalOpen, setJsonModalOpen] = useState(false);
  const [deleteModalOpen, setDeleteModalOpen] = useState(false);
  const [editedJson, setEditedJson] = useState("");
  const [isEditing, setIsEditing] = useState(false);
  // Initialize from backend-provided value
  const [oauthAuthorized, setOauthAuthorized] = useState(
    client.oauth_authorized ?? false
  );
  const [oauthLoading, setOauthLoading] = useState(false);

  // Check OAuth status on mount and when client changes
  const checkOAuthStatus = useCallback(async () => {
    // Only check for HTTP-based transports
    if (client.transport === "stdio") return;
    try {
      const status = await api.getMCPOAuthStatus(client.key);
      setOauthAuthorized(status.authorized);
    } catch (error) {
      // Silently ignore - OAuth status check is optional
    }
  }, [client.key, client.transport]);

  useEffect(() => {
    checkOAuthStatus();
  }, [checkOAuthStatus]);

  // Listen for OAuth callback messages
  useEffect(() => {
    const handleMessage = (event: MessageEvent) => {
      // Validate origin to prevent cross-site message spoofing
      if (event.origin !== window.location.origin) {
        return;
      }
      if (event.data?.type === "mcp-oauth-callback") {
        checkOAuthStatus();
        onRefresh?.();
      }
    };
    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, [checkOAuthStatus, onRefresh]);

  // Show OAuth controls for HTTP transports that require auth or are authorized
  const showOAuthControls =
    client.transport !== "stdio" && (client.requires_auth || oauthAuthorized);

  // Determine if MCP client is remote or local based on command
  const isRemote =
    client.transport === "streamable_http" || client.transport === "sse";
  const clientType = isRemote ? "Remote" : "Local";

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
    onDelete(client, null as any);
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
      const { key, ...updates } = parsed;

      // Send all updates directly to backend, let backend handle env masking check
      const success = await onUpdate(client.key, updates);
      if (success) {
        setJsonModalOpen(false);
        setIsEditing(false);
      }
    } catch (error) {
      alert("Invalid JSON format");
    }
  };

  const clientJson = JSON.stringify(client, null, 2);

  // OAuth handlers
  const handleStartOAuth = async (e: React.MouseEvent) => {
    e.stopPropagation();

    setOauthLoading(true);
    try {
      const response = await api.startMCPOAuth(client.key);
      // Open authorization URL in new window
      window.open(response.auth_url, "mcp-oauth", "width=600,height=700");
    } catch (error: any) {
      message.error(error?.message || t("mcp.oauthStartError"));
    } finally {
      setOauthLoading(false);
    }
  };

  const handleRevokeOAuth = async (e: React.MouseEvent) => {
    e.stopPropagation();
    setOauthLoading(true);
    try {
      await api.revokeMCPOAuth(client.key);
      setOauthAuthorized(false);
      message.success(t("mcp.oauthRevoked"));
      onRefresh?.();
    } catch (error: any) {
      message.error(error?.message || t("mcp.oauthRevokeError"));
    } finally {
      setOauthLoading(false);
    }
  };

  return (
    <>
      <Card
        hoverable
        onClick={handleCardClick}
        onMouseEnter={onMouseEnter}
        onMouseLeave={onMouseLeave}
        className={`${styles.mcpCard} ${
          client.enabled ? styles.enabledCard : ""
        } ${isHovered ? styles.hover : styles.normal}`}
      >
        <div className={styles.cardHeader}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span className={styles.fileIcon}>
              <Server style={{ color: "#1890ff", fontSize: 20 }} />
            </span>
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
          </div>
          <div className={styles.statusContainer}>
            <span
              className={`${styles.statusDot} ${
                client.enabled ? styles.enabled : styles.disabled
              }`}
            />
            <span
              className={`${styles.statusText} ${
                client.enabled ? styles.enabled : styles.disabled
              }`}
            >
              {client.enabled ? t("common.enabled") : t("common.disabled")}
            </span>
          </div>
        </div>

        <div className={styles.description}>
          {client.description || "\u00A0"}
        </div>

        <div className={styles.cardFooter}>
          <Button
            type="link"
            size="small"
            onClick={handleToggleClick}
            className={styles.actionButton}
          >
            {client.enabled ? t("common.disable") : t("common.enable")}
          </Button>

          {showOAuthControls && (
            oauthAuthorized ? (
              <Tooltip title={t("mcp.oauthRevoke")}>
                <Button
                  type="text"
                  size="small"
                  icon={<DisconnectOutlined />}
                  onClick={handleRevokeOAuth}
                  loading={oauthLoading}
                  className={styles.oauthAuthorizedButton}
                />
              </Tooltip>
            ) : (
              <Tooltip title={t("mcp.oauthAuthorize")}>
                <Button
                  type="text"
                  size="small"
                  icon={<KeyOutlined />}
                  onClick={handleStartOAuth}
                  loading={oauthLoading}
                  className={styles.oauthPendingButton}
                />
              </Tooltip>
            )
          )}

          <Button
            type="text"
            size="small"
            danger
            icon={<DeleteOutlined />}
            className={styles.deleteButton}
            onClick={handleDeleteClick}
            disabled={client.enabled}
          />
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
        {isEditing ? (
          <textarea
            value={editedJson}
            onChange={(e) => setEditedJson(e.target.value)}
            className={styles.editJsonTextArea}
          />
        ) : (
          <pre className={styles.preformattedText}>{clientJson}</pre>
        )}
      </Modal>
    </>
  );
}
