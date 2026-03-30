import { Card, Button, Modal, Tooltip } from "@agentscope-ai/design";
import { DeleteOutlined } from "@ant-design/icons";
import { Bot } from "lucide-react";
import type { ACPHarnessInfo } from "../../../../api/types";
import { useTranslation } from "react-i18next";
import { useState } from "react";
import styles from "../index.module.less";

interface ACPHarnessCardProps {
  harness: ACPHarnessInfo;
  onToggle: (key: string) => void;
  onDelete: (key: string) => void;
  onEdit: (harness: ACPHarnessInfo) => void;
  isHovered: boolean;
  onMouseEnter: () => void;
  onMouseLeave: () => void;
}

export function ACPHarnessCard({
  harness,
  onToggle,
  onDelete,
  onEdit,
  isHovered,
  onMouseEnter,
  onMouseLeave,
}: ACPHarnessCardProps) {
  const { t } = useTranslation();
  const [deleteModalOpen, setDeleteModalOpen] = useState(false);

  const handleToggleClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    onToggle(harness.key);
  };

  const handleDeleteClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    setDeleteModalOpen(true);
  };

  const confirmDelete = () => {
    setDeleteModalOpen(false);
    onDelete(harness.key);
  };

  const handleCardClick = () => {
    onEdit(harness);
  };

  return (
    <>
      <Card
        hoverable
        onClick={handleCardClick}
        onMouseEnter={onMouseEnter}
        onMouseLeave={onMouseLeave}
        className={`${styles.harnessCard} ${
          harness.enabled ? styles.enabledCard : ""
        } ${isHovered ? styles.hover : styles.normal}`}
      >
        <div className={styles.cardHeader}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span className={styles.fileIcon}>
              <Bot style={{ color: "#615ced", fontSize: 20 }} />
            </span>
            <Tooltip title={harness.name}>
              <h3 className={styles.harnessTitle}>{harness.name}</h3>
            </Tooltip>
          </div>
          <div className={styles.statusContainer}>
            <span
              className={`${styles.statusDot} ${
                harness.enabled ? styles.enabled : styles.disabled
              }`}
            />
            <span
              className={`${styles.statusText} ${
                harness.enabled ? styles.enabled : styles.disabled
              }`}
            >
              {harness.enabled ? t("common.enabled") : t("common.disabled")}
            </span>
          </div>
        </div>

        <div className={styles.harnessDetails}>
          <div className={styles.detailRow}>
            <span className={styles.detailLabel}>{t("acp.command")}:</span>
            <span className={styles.detailValue}>{harness.command || "-"}</span>
          </div>
          <div className={styles.detailRow}>
            <span className={styles.detailLabel}>{t("acp.args")}:</span>
            <span className={styles.detailValue}>
              {harness.args?.join(" ") || "-"}
            </span>
          </div>
          <div className={styles.detailRow}>
            <span className={styles.detailLabel}>{t("acp.envVars")}:</span>
            <span className={styles.detailValue}>
              {Object.keys(harness.env || {}).length > 0
                ? `${Object.keys(harness.env).length} ${t("acp.envVarsCount")}`
                : "-"}
            </span>
          </div>
          <div className={styles.detailRow}>
            <span className={styles.detailLabel}>
              {t("acp.keepSessionDefault")}:
            </span>
            <span className={styles.detailValue}>
              {harness.keep_session_default
                ? t("acp.keepSessionDefaultEnabled")
                : t("acp.keepSessionDefaultDisabled")}
            </span>
          </div>
          <div className={styles.detailRow}>
            <span className={styles.detailLabel}>
              {t("acp.permissionBrokerVerified")}:
            </span>
            <span className={styles.detailValue}>
              {harness.permission_broker_verified
                ? t("acp.permissionBrokerVerifiedEnabled")
                : t("acp.permissionBrokerVerifiedDisabled")}
            </span>
          </div>
        </div>

        <div className={styles.cardFooter}>
          <Button
            type="link"
            size="small"
            onClick={handleToggleClick}
            className={styles.actionButton}
          >
            {harness.enabled ? t("common.disable") : t("common.enable")}
          </Button>

          <Button
            type="text"
            size="small"
            danger
            icon={<DeleteOutlined />}
            className={styles.deleteButton}
            onClick={handleDeleteClick}
            disabled={harness.enabled}
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
        <p>{t("acp.deleteConfirm")}</p>
      </Modal>
    </>
  );
}
