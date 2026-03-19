import { Card, Button, Modal, Tooltip } from "@agentscope-ai/design";
import { DeleteOutlined } from "@ant-design/icons";
import { Server } from "lucide-react";
import type { MCPClientInfo } from "../../../../api/types";
import { useTranslation } from "react-i18next";
import { useState } from "react";
import styles from "../index.module.less";

interface MCPClientCardProps {
  client: MCPClientInfo;
  onToggle: (client: MCPClientInfo, e: React.MouseEvent) => void;
  onDelete: (client: MCPClientInfo, e?: React.MouseEvent) => void;
  onUpdate: (key: string, updates: Record<string, unknown>) => Promise<boolean>;
  runtimeStateOverride?: "queued" | "checking";
  isHovered: boolean;
  onMouseEnter: () => void;
  onMouseLeave: () => void;
}

export function MCPClientCard({
  client,
  onToggle,
  onDelete,
  onUpdate,
  runtimeStateOverride,
  isHovered,
  onMouseEnter,
  onMouseLeave,
}: MCPClientCardProps) {
  const { t } = useTranslation();
  const [jsonModalOpen, setJsonModalOpen] = useState(false);
  const [deleteModalOpen, setDeleteModalOpen] = useState(false);
  const [editedJson, setEditedJson] = useState("");
  const [isEditing, setIsEditing] = useState(false);

  // Determine if MCP client is remote or local based on command
  const isRemote =
    client.transport === "streamable_http" || client.transport === "sse";
  const clientType = isRemote ? "Remote" : "Local";
  const runtimeStatusKey =
    runtimeStateOverride === "checking"
      ? "mcp.runtimeChecking"
      : runtimeStateOverride === "queued"
      ? "mcp.runtimeQueued"
      : !client.enabled
      ? "mcp.runtimeDisabled"
      : client.active === undefined
      ? "mcp.runtimeUnknown"
      : client.active
      ? "mcp.runtimeActive"
      : "mcp.runtimeUnavailable";
  const runtimeStatusClass =
    runtimeStateOverride === "checking"
      ? styles.runtimeChecking
      : runtimeStateOverride === "queued"
      ? styles.runtimeQueued
      : !client.enabled
      ? styles.runtimeDisabled
      : client.active === undefined
      ? styles.runtimeUnknown
      : client.active
      ? styles.runtimeActive
      : styles.runtimeUnavailable;

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
    onDelete(client);
  };

  const handleCardClick = () => {
    const jsonStr = JSON.stringify(client, null, 2);
    setEditedJson(jsonStr);
    setIsEditing(false);
    setJsonModalOpen(true);
  };

  const handleSaveJson = async () => {
    try {
      const parsed = JSON.parse(editedJson) as Record<string, unknown>;
      const updates = { ...parsed };
      delete updates.key;
      delete updates.active;

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

  const clientJson = JSON.stringify(client, null, 2);

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
          <div className={styles.titleRow}>
            <div className={styles.titleMain}>
              <span className={styles.fileIcon}>
                <Server style={{ color: "#1890ff", fontSize: 20 }} />
              </span>
              <Tooltip title={client.name}>
                <h3 className={styles.mcpTitle}>{client.name}</h3>
              </Tooltip>
            </div>
            <span
              className={`${styles.typeBadge} ${
                isRemote ? styles.remote : styles.local
              }`}
            >
              {clientType}
            </span>
          </div>
          <div className={styles.statusContainer}>
            <div className={styles.statusRight}>
              <span
                className={`${styles.statusBadge} ${
                  client.enabled ? styles.enabled : styles.disabled
                }`}
              >
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
              </span>
              <span className={`${styles.statusBadge} ${runtimeStatusClass}`}>
                <span className={`${styles.statusDot} ${runtimeStatusClass}`} />
                <span className={`${styles.statusText} ${runtimeStatusClass}`}>
                  {t(runtimeStatusKey)}
                </span>
              </span>
            </div>
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
