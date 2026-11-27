import { useEffect } from "react";
import { Alert, Button, Modal } from "antd";
import { useTranslation } from "react-i18next";
import type { BackupMeta } from "@/api/types/backup";
import { useBackupRunner } from "../shared/useBackupRunner";
import { buildPreRestoreScope } from "../shared/scope";
import BackupProgress from "./BackupProgress";

interface Props {
  /** The backup being restored. When non-null the modal opens and auto-starts. */
  target: BackupMeta | null;
  /** All currently known agent IDs; passed explicitly to buildPreRestoreScope. */
  agentIds: string[];
  onClose: () => void;
  onSuccess: () => void;
}

/**
 * Automatic pre-restore snapshot modal.
 * Opens when target is set, immediately starts a full backup, shows only a
 * progress bar and a Cancel button. No user form input required.
 */
export default function SilentBackupModal({
  target,
  agentIds,
  onClose,
  onSuccess,
}: Props) {
  const { t } = useTranslation();
  const runner = useBackupRunner({
    onSuccess,
    onClose,
    resumeActiveOnStartFailure: false,
  });

  useEffect(() => {
    if (!target) return;
    const { name, description, scope, agents } = buildPreRestoreScope(agentIds);
    runner.start({
      name,
      description: t(description),
      scope,
      agents,
    });
    // Start one snapshot for the selected restore target.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target]);

  return (
    <Modal
      title={t(
        runner.failed
          ? "backup.preRestoreBackupFailed"
          : "backup.creatingPreRestoreBackup",
      )}
      open={target !== null}
      onCancel={runner.loading ? runner.cancel : onClose}
      footer={
        runner.loading ? (
          <Button danger loading={runner.cancelling} onClick={runner.cancel}>
            {t(
              runner.cancelling
                ? "confirmation.cancellingBackup"
                : "confirmation.cancelBackup",
            )}
          </Button>
        ) : (
          <Button onClick={onClose}>{t("common.close")}</Button>
        )
      }
      destroyOnHidden
      centered
      closable={false}
      maskClosable={false}
    >
      {runner.failed ? (
        <Alert type="error" message={t("backup.preRestoreBackupFailedHint")} />
      ) : (
        <BackupProgress
          progress={runner.progress}
          progressMsg={runner.progressMsg}
        />
      )}
    </Modal>
  );
}
