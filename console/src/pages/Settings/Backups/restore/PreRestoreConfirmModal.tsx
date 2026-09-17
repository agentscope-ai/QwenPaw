/**
 * First restore warning. The server always creates a signed protection backup
 * after the final impact confirmation and before it writes any data.
 */
import { Button, Modal } from "antd";
import { useTranslation } from "react-i18next";
import type { BackupMeta } from "@/api/types/backup";

interface Props {
  target: BackupMeta | null;
  onCancel: () => void;
  onNoBackup: (target: BackupMeta) => void;
}

export default function PreRestoreConfirmModal({
  target,
  onCancel,
  onNoBackup,
}: Props) {
  const { t } = useTranslation();

  return (
    <Modal
      open={!!target}
      title={t("backup.preRestoreBackupTitle")}
      centered
      width={520}
      onCancel={onCancel}
      footer={[
        <Button key="cancel" onClick={onCancel}>
          {t("common.cancel")}
        </Button>,
        <Button
          key="continue"
          type="primary"
          onClick={() => target && onNoBackup(target)}
        >
          {t("backup.preRestoreBackupNo")}
        </Button>,
      ]}
    >
      <p style={{ lineHeight: 1.6 }}>{t("backup.preRestoreBackupContent")}</p>
    </Modal>
  );
}
