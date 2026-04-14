/**
 * First step in the restore flow: asks the user whether they want to create
 * an automatic snapshot before overwriting data. Three outcomes:
 *   - Cancel     → abort entirely
 *   - No backup  → proceed straight to RestoreBackupModal
 *   - Yes backup → open SilentBackupModal first, then RestoreBackupModal
 */
import { Button, Modal } from "antd";
import { useTranslation } from "react-i18next";
import type { BackupMeta } from "@/api/types/backup";

interface Props {
  target: BackupMeta | null;
  onCancel: () => void;
  onNoBackup: (target: BackupMeta) => void;
  onYesBackup: (target: BackupMeta) => void;
}

export default function PreRestoreConfirmModal({
  target,
  onCancel,
  onNoBackup,
  onYesBackup,
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
        <Button key="no" onClick={() => target && onNoBackup(target)}>
          {t("backup.preRestoreBackupNo")}
        </Button>,
        <Button
          key="yes"
          type="primary"
          onClick={() => target && onYesBackup(target)}
        >
          {t("backup.preRestoreBackupYes")}
        </Button>,
      ]}
    >
      <p style={{ lineHeight: 1.6 }}>{t("backup.preRestoreBackupContent")}</p>
    </Modal>
  );
}
