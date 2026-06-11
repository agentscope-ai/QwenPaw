/**
 * Shown when importing a zip whose ID already exists in the store (HTTP 409).
 */
import { useTranslation } from "react-i18next";
import dayjs from "dayjs";
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
  conflictMeta: BackupMeta | null;
  onChoice: () => void;
  onCancel: () => void;
}

export default function ImportConflictModal({
  conflictMeta,
  onChoice,
  onCancel,
}: Props) {
  const { t } = useTranslation();

  return (
    <Dialog open={!!conflictMeta} onOpenChange={(open) => !open && onCancel()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{t("backup.importConflictTitle")}</DialogTitle>
        </DialogHeader>
        <p className="text-sm">{t("backup.importConflictDesc")}</p>
        {conflictMeta && (
          <div className="rounded-md bg-muted px-3 py-3 text-sm space-y-1">
            <div>
              <strong>{t("backup.name")}:</strong> {conflictMeta.name}
            </div>
            <div>
              <strong>ID:</strong>{" "}
              <span className="font-mono text-xs">{conflictMeta.id}</span>
            </div>
            <div>
              <strong>{t("backup.createdAt")}:</strong>{" "}
              {dayjs(conflictMeta.created_at).format("YYYY-MM-DD HH:mm:ss")}
            </div>
          </div>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onCancel}>
            {t("common.cancel")}
          </Button>
          <Button variant="destructive" onClick={() => onChoice()}>
            {t("backup.importReplace")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
