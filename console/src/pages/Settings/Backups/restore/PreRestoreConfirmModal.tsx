/**
 * First step in the restore flow: asks the user whether they want to create
 * an automatic snapshot before overwriting data.
 */
import { useTranslation } from "react-i18next";
import type { BackupMeta } from "@/api/types/backup";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";

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
    <Dialog open={!!target} onOpenChange={(open) => !open && onCancel()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("backup.preRestoreBackupTitle")}</DialogTitle>
        </DialogHeader>
        <p className="text-sm leading-relaxed">
          {t("backup.preRestoreBackupContent")}
        </p>
        <DialogFooter>
          <Button variant="outline" onClick={onCancel}>
            {t("common.cancel")}
          </Button>
          <Button
            variant="outline"
            onClick={() => target && onNoBackup(target)}
          >
            {t("backup.preRestoreBackupNo")}
          </Button>
          <Button onClick={() => target && onYesBackup(target)}>
            {t("backup.preRestoreBackupYes")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
