import { useTranslation } from "react-i18next";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";

/**
 * Shared confirmation for backups that do not verify with the local signing key.
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
    <Dialog open={open} onOpenChange={(o) => !o && onCancel()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>
            {isLegacy
              ? t("backup.trustLegacyTitle", {
                  defaultValue: "Trust legacy backup?",
                })
              : t("backup.trustForeignTitle", {
                  defaultValue: "Trust this backup?",
                })}
          </DialogTitle>
        </DialogHeader>
        <div className="rounded-md border border-yellow-200 bg-yellow-50 px-3 py-2 text-sm dark-mode:border-yellow-800 dark-mode:bg-yellow-950">
          <div className="font-medium text-yellow-800 dark-mode:text-yellow-200">
            {backupName ||
              t("backup.unknownBackupName", { defaultValue: "Backup archive" })}
          </div>
          <div className="mt-1 text-yellow-700 dark-mode:text-yellow-300">
            {isLegacy
              ? t("backup.trustLegacyDesc", {
                  defaultValue:
                    "This older backup has no local signature. Only continue if you trust where it came from; this instance will sign it before restore.",
                })
              : t("backup.trustForeignDesc", {
                  defaultValue:
                    "This backup was not signed by this instance. Only continue if you trust the source; local security and MCP settings will be preserved by default when restored.",
                })}
          </div>
        </div>
        <DialogFooter>
          <Button
            variant="outline"
            onClick={onCancel}
            disabled={confirmLoading}
          >
            {t("common.cancel")}
          </Button>
          <Button
            variant="destructive"
            onClick={onConfirm}
            disabled={confirmLoading}
          >
            {t("common.confirm")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
