import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import type { BackupMeta } from "@/api/types/backup";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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
  const runner = useBackupRunner({ onSuccess, onClose });

  useEffect(() => {
    if (!target) return;
    const { name, description, scope, agents } = buildPreRestoreScope(agentIds);
    runner.start({
      name,
      description: t(description),
      scope,
      agents,
    });
    // runner.start is stable (doesn't change between renders)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target]);

  return (
    <Dialog open={target !== null} onOpenChange={() => runner.cancel()}>
      <DialogContent
        className="max-w-md"
        onInteractOutside={(e) => e.preventDefault()}
        onEscapeKeyDown={(e) => e.preventDefault()}
      >
        <DialogHeader>
          <DialogTitle>{t("backup.creatingPreRestoreBackup")}</DialogTitle>
          <DialogDescription className="sr-only">
            {t("backup.creatingPreRestoreBackup")}
          </DialogDescription>
        </DialogHeader>
        <BackupProgress
          progress={runner.progress}
          progressMsg={runner.progressMsg}
        />
      </DialogContent>
    </Dialog>
  );
}
