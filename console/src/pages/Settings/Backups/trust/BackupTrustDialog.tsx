import { Alert, Modal } from "antd";
import { useTranslation } from "react-i18next";

/**
 * Shared confirmation for backups that do not verify with the local signing
 * key. Import and restore both use this dialog so the trust decision is
 * explicit before the backend accepts or signs a foreign/legacy archive.
 */
interface Props {
  open: boolean;
  mode: "foreign" | "legacy";
  backupName?: string;
  confirmLoading?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export default function BackupTrustDialog({
  open,
  mode,
  backupName,
  confirmLoading,
  onConfirm,
  onCancel,
}: Props) {
  const { t } = useTranslation();
  const isLegacy = mode === "legacy";

  return (
    <Modal
      title={
        isLegacy
          ? t("backup.trustLegacyTitle", {
              defaultValue: "Trust legacy backup?",
            })
          : t("backup.trustForeignTitle", {
              defaultValue: "Trust this backup?",
            })
      }
      open={open}
      onOk={onConfirm}
      onCancel={onCancel}
      confirmLoading={confirmLoading}
      okButtonProps={{ danger: true }}
      okText={t("common.confirm")}
      cancelText={t("common.cancel")}
      centered
    >
      <Alert
        type="warning"
        showIcon
        message={
          backupName ||
          t("backup.unknownBackupName", { defaultValue: "Backup archive" })
        }
        description={
          isLegacy
            ? t("backup.trustLegacyDesc", {
                defaultValue:
                  "This older backup has no local signature. Only continue if you trust where it came from; this instance will sign it before restore.",
              })
            : t("backup.trustForeignDesc", {
                defaultValue:
                  "This backup was not signed by this instance. Only continue if you trust the source; local security and MCP settings will be preserved by default when restored.",
              })
        }
      />
    </Modal>
  );
}
