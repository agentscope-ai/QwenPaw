import { Card, Button, Modal, Tooltip, Input, Select } from "@agentscope-ai/design";
import type {
  MCPAccessPolicy,
  MCPClientInfo,
  MCPClientUpdateRequest,
} from "../../../../api/types";
import { useTranslation } from "react-i18next";
import React, { useEffect, useState } from "react";
import { useTheme } from "../../../../contexts/ThemeContext";
import {
  EyeOutlined,
  EyeInvisibleOutlined,
  ToolOutlined,
} from "@ant-design/icons";
import { ShieldCheck, ShieldAlert, ShieldX, KeyRound } from "lucide-react";
import { MCPAccessModal } from "./MCPAccessModal";
import { MCPOAuthSection } from "./MCPOAuthSection";
import styles from "../index.module.less";
import {
  buildCredentialUpdates,
  createCredentialDraft,
  type CredentialDraft,
  type CredentialDraftAction,
} from "../credentials";

interface MCPClientCardProps {
  client: MCPClientInfo;
  onToggle: (client: MCPClientInfo, e: React.MouseEvent) => void;
  onDelete: (client: MCPClientInfo, e: React.MouseEvent) => void;
  onUpdate: (key: string, updates: MCPClientUpdateRequest, expectedRevision?: number) => Promise<boolean>;
  onUpdatePolicy: (key: string, policy: MCPAccessPolicy, expectedRevision?: number) => Promise<boolean>;
  onRefresh: () => Promise<void>;
  canEdit: boolean;
}

export const MCPClientCard = React.memo(function MCPClientCard({
  client,
  onToggle,
  onDelete,
  onUpdate,
  onUpdatePolicy,
  onRefresh,
  canEdit,
}: MCPClientCardProps) {
  const { t } = useTranslation();
  const { isDark } = useTheme();
  const [isHovered, setIsHovered] = useState(false);
  const [jsonModalOpen, setJsonModalOpen] = useState(false);
  const [deleteModalOpen, setDeleteModalOpen] = useState(false);
  const [accessModalOpen, setAccessModalOpen] = useState(false);
  const [editedJson, setEditedJson] = useState("");
  const [isEditing, setIsEditing] = useState(false);
  const [oauthModalOpen, setOauthModalOpen] = useState(false);
  const [oauthClientId, setOauthClientId] = useState("");
  const [oauthScope, setOauthScope] = useState(
    client.oauth_status?.scope || "",
  );
  const [oauthAuthEndpoint, setOauthAuthEndpoint] = useState("");
  const [oauthTokenEndpoint, setOauthTokenEndpoint] = useState("");
  const [credentialDraft, setCredentialDraft] = useState<CredentialDraft>(() =>
    createCredentialDraft(client.credential_fields),
  );
  const [openedRevision, setOpenedRevision] = useState<number>();
  const [oauthRefreshRevision, setOauthRefreshRevision] = useState<number>();
  const [oauthRefreshing, setOauthRefreshing] = useState(false);

  useEffect(() => {
    if (
      oauthRefreshRevision !== undefined &&
      client.revision !== oauthRefreshRevision
    ) {
      setOauthRefreshRevision(undefined);
      setOauthRefreshing(false);
    }
  }, [client.revision, oauthRefreshRevision]);

  const refreshAfterOAuthChange = async () => {
    setOauthRefreshing(true);
    try {
      await onRefresh();
    } catch {
      // Keep the old revision blocked; the OAuth action becomes an explicit retry.
    } finally {
      setOauthRefreshing(false);
    }
  };

  // Determine if MCP client is remote or local based on command
  const isRemote =
    client.transport === "streamable_http" || client.transport === "sse";
  const clientType = isRemote ? "Remote" : "Local";

  const oauthStatus = client.oauth_status;
  const now = Date.now() / 1000;
  const isOauthAuthorized =
    !!oauthStatus?.authorized && oauthStatus.expires_at > now;
  const isOauthExpired =
    !!oauthStatus?.authorized && oauthStatus.expires_at <= now;
  const hasOauth = !!oauthStatus;

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
    const {
      key: _key,
      credential_fields: credentialFields,
      revision: _revision,
      runtime_status: _runtimeStatus,
      runtime_error: _runtimeError,
      can_edit: _canEdit,
      access_summary: _accessSummary,
      oauth_status: _oauthStatus,
      tools: _tools,
      headers: _headers,
      env: _env,
      ...editable
    } = client;
    const keep = (names: string[]) =>
      Object.fromEntries(names.map((name) => [name, { action: "keep" }]));
    const jsonStr = JSON.stringify(
      {
        ...editable,
        credential_updates: {
          headers: keep(credentialFields?.headers ?? []),
          env: keep(credentialFields?.env ?? []),
        },
      },
      null,
      2,
    );
    setCredentialDraft(createCredentialDraft(credentialFields));
    setOpenedRevision(client.revision);
    setEditedJson(jsonStr);
    setIsEditing(false);
    setJsonModalOpen(true);
  };

  const handleSaveJson = async () => {
    try {
      const parsed = JSON.parse(editedJson);
      if (
        Object.prototype.hasOwnProperty.call(parsed, "headers") ||
        Object.prototype.hasOwnProperty.call(parsed, "env")
      ) {
        alert(t("mcp.rawCredentialRejected"));
        return;
      }
      const { key: _key, ...updates } = parsed;
      const explicitActions = buildCredentialUpdates(credentialDraft);
      updates.credential_updates = {
        headers: {
          ...updates.credential_updates?.headers,
          ...explicitActions.headers,
        },
        env: {
          ...updates.credential_updates?.env,
          ...explicitActions.env,
        },
      };

      // Send all updates directly to backend, let backend handle env masking check
      const success = await onUpdate(client.key, updates, openedRevision);
      if (success) {
        setJsonModalOpen(false);
        setIsEditing(false);
      }
    } catch {
      alert("Invalid JSON format");
    }
  };

  const clientJson = JSON.stringify(client, null, 2);

  return (
    <>
      <Card
        data-testid={`mcp-client-card-${client.key}`}
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

        {Boolean(
          client.credential_fields?.headers.length ||
            client.credential_fields?.env.length,
        ) && (
          <div className={styles.maskedFieldHint}>
            {t("mcp.credentialConfigured", {
              fields: [
                ...(client.credential_fields?.headers ?? []).map(
                  (name) => `header:${name}`,
                ),
                ...(client.credential_fields?.env ?? []).map(
                  (name) => `env:${name}`,
                ),
              ].join(", "),
            })}
          </div>
        )}
        {client.enabled &&
          client.runtime_status &&
          client.runtime_status !== "active" && (
          <div className={styles.maskedFieldHint}>
            {t("mcp.runtimeInactive", {
              status: client.runtime_status,
              error: client.runtime_error || "",
            })}
          </div>
        )}

        <div className={styles.cardFooter}>
          <Button
            className={styles.toolsButton}
            onClick={(e) => {
              e.stopPropagation();
              setAccessModalOpen(true);
            }}
            icon={<ToolOutlined />}
          >
            {t("mcp.tools")}
          </Button>
          <div
            className={`${styles.cardSecondaryActions} ${
              isRemote
                ? styles.cardSecondaryActionsThree
                : styles.cardSecondaryActionsTwo
            }`}
          >
            {isRemote && canEdit && (
              <Button
                data-testid={`mcp-oauth-manage-${client.key}`}
                className={styles.toggleButton}
                disabled={oauthRefreshing}
                onClick={(e) => {
                  e.stopPropagation();
                  if (oauthRefreshRevision !== undefined) {
                    void refreshAfterOAuthChange();
                    return;
                  }
                  setOpenedRevision(client.revision);
                  setOauthModalOpen(true);
                }}
                style={
                  isOauthAuthorized
                    ? {
                        color: "#27ae60",
                        borderColor: "#27ae60",
                        background: "rgba(39,174,96,0.06)",
                      }
                    : isOauthExpired
                    ? {
                        color: "#e67e22",
                        borderColor: "#e67e22",
                        background: "rgba(230,126,34,0.06)",
                      }
                    : undefined
                }
              >
                <span
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 4,
                  }}
                >
                  {isOauthAuthorized ? (
                    <ShieldCheck size={13} />
                  ) : isOauthExpired ? (
                    <ShieldAlert size={13} />
                  ) : (
                    <KeyRound size={13} />
                  )}
                  {oauthRefreshRevision !== undefined
                    ? t("common.retry")
                    : isOauthAuthorized
                    ? t("mcp.oauth.authorized")
                    : isOauthExpired
                    ? t("mcp.oauth.expired")
                    : t("mcp.oauth.authorize")}
                </span>
              </Button>
            )}
            {canEdit && <Button
              className={styles.toggleButton}
              onClick={(e) => {
                e.stopPropagation();
                handleToggleClick(e);
              }}
              icon={client.enabled ? <EyeInvisibleOutlined /> : <EyeOutlined />}
            >
              {client.enabled ? t("common.disable") : t("common.enable")}
            </Button>}
            {canEdit && <Button
              className={styles.deleteButton}
              danger
              onClick={(e) => {
                e.stopPropagation();
                handleDeleteClick(e);
              }}
            >
              {t("common.delete")}
            </Button>}
          </div>
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
            {canEdit && (isEditing ? (
              <Button data-testid={`mcp-client-save-${client.key}`} type="primary" onClick={handleSaveJson}>
                {t("common.save")}
              </Button>
            ) : (
              <Button data-testid={`mcp-client-edit-${client.key}`} type="primary" onClick={() => setIsEditing(true)}>
                {t("common.edit")}
              </Button>
            ))}
          </div>
        }
        width={700}
      >
        <div className={styles.maskedFieldHint}>{t("mcp.credentialFieldHint")}</div>
        {isEditing && (
          <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 12 }}>
            {(["headers", "env"] as const).flatMap((kind) =>
              Object.entries(credentialDraft[kind]).map(([name, field]) => (
                <div
                  key={`${kind}:${name}`}
                  data-testid={`mcp-credential-row-${kind}-${name}`}
                  style={{ display: "grid", gridTemplateColumns: "1fr 130px 2fr", gap: 8 }}
                >
                  <Input value={`${kind}:${name}`} disabled />
                  <Select
                    data-testid={`mcp-credential-action-${kind}-${name}`}
                    value={field.action}
                    options={[
                      { label: t("mcp.credentialAction.keep"), value: "keep" },
                      { label: t("mcp.credentialAction.replace"), value: "replace" },
                      { label: t("mcp.credentialAction.delete"), value: "delete" },
                    ]}
                    onChange={(action) =>
                      setCredentialDraft((previous) => ({
                        ...previous,
                        [kind]: {
                          ...previous[kind],
                          [name]: {
                            ...previous[kind][name],
                            action: action as CredentialDraftAction,
                          },
                        },
                      }))
                    }
                  />
                  <Input.Password
                    data-testid={`mcp-credential-value-${kind}-${name}`}
                    value={field.value}
                    disabled={field.action !== "replace"}
                    placeholder={field.action === "replace" ? t("mcp.credentialReplacement") : ""}
                    onChange={(event) =>
                      setCredentialDraft((previous) => ({
                        ...previous,
                        [kind]: {
                          ...previous[kind],
                          [name]: { ...previous[kind][name], value: event.target.value },
                        },
                      }))
                    }
                  />
                </div>
              )),
            )}
          </div>
        )}
        {isEditing ? (
          <Input.TextArea
            data-testid={`mcp-client-json-${client.key}`}
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

      <MCPAccessModal
        client={client}
        open={accessModalOpen}
        onClose={() => setAccessModalOpen(false)}
        onSave={(policy, revision) => onUpdatePolicy(client.key, policy, revision)}
        canEdit={canEdit}
      />

      {/* Dedicated OAuth modal — opened only via the Authorize button */}
      <Modal
        title={
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            {isOauthAuthorized ? (
              <ShieldCheck size={16} style={{ color: "#27ae60" }} />
            ) : isOauthExpired ? (
              <ShieldAlert size={16} style={{ color: "#e67e22" }} />
            ) : (
              <ShieldX size={16} style={{ color: "#7f8c8d" }} />
            )}
            {`${client.name} — ${t("mcp.oauth.manage")}`}
          </div>
        }
        open={oauthModalOpen}
        onCancel={() => setOauthModalOpen(false)}
        footer={
          <div style={{ textAlign: "right" }}>
            <Button onClick={() => setOauthModalOpen(false)}>
              {t("common.close")}
            </Button>
          </div>
        }
        width={560}
      >
        {oauthModalOpen && <MCPOAuthSection
          url={client.url}
          clientKey={client.key}
          oauthEnabled
          currentOAuthStatus={oauthStatus}
          revision={openedRevision ?? client.revision}
          clientId={oauthClientId}
          scope={oauthScope}
          authEndpoint={oauthAuthEndpoint}
          tokenEndpoint={oauthTokenEndpoint}
          onClientIdChange={setOauthClientId}
          onScopeChange={setOauthScope}
          onAuthEndpointChange={setOauthAuthEndpoint}
          onTokenEndpointChange={setOauthTokenEndpoint}
          onAuthChanged={() => {
            setOauthModalOpen(false);
            setOauthRefreshRevision(openedRevision ?? client.revision);
            void refreshAfterOAuthChange();
          }}
        />}
      </Modal>
    </>
  );
});
