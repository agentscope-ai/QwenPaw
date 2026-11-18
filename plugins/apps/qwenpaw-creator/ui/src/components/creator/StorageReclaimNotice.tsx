import { useState } from "react";
import { Modal, message } from "antd";
import { HardDriveDownload } from "lucide-react";
import { useTranslation } from "react-i18next";
import { confirmProjectReclaim, CreatorHttpError } from "@/api/creator";
import { formatBytes } from "@/components/creator/ProjectImportExport";

interface StorageReclaimNoticeProps {
  projectId: string;
  projectName: string;
  pendingBytes: number;
  onConfirmed: () => void;
}

export default function StorageReclaimNotice({
  projectId,
  projectName,
  pendingBytes,
  onConfirmed,
}: StorageReclaimNoticeProps) {
  const { t } = useTranslation();
  const [busy, setBusy] = useState(false);
  const size = formatBytes(pendingBytes);

  const askAndReclaim = () => {
    Modal.confirm({
      title: t("storage.confirmTitle", { name: projectName, size }),
      content: t("storage.confirmBody"),
      okText: t("storage.confirmButton"),
      cancelText: t("common.cancel"),
      okButtonProps: { danger: true },
      onOk: () => {
        setBusy(true);
        confirmProjectReclaim(projectId)
          .then((result) => {
            onConfirmed();
            message.success(
              t("storage.confirmed", {
                size: formatBytes(
                  result.releasedBytes + result.transactionBytes,
                ),
              }),
            );
          })
          .catch((error) => {
            const detail =
              error instanceof CreatorHttpError
                ? error.userMessage
                : String(error);
            message.error(t("storage.failed", { message: detail }));
          })
          .finally(() => setBusy(false));
      },
    });
  };

  return (
    <div
      data-storage-reclaim-notice
      className="flex items-center justify-between gap-2 rounded border border-[var(--color-warning)]/40 bg-[var(--color-warning-soft)]/40 px-2 py-1.5"
    >
      <span className="flex min-w-0 flex-1 items-center gap-1.5 text-[11px] leading-4 text-[var(--color-warning)]">
        <HardDriveDownload className="h-3.5 w-3.5 shrink-0" />
        <span className="truncate">{t("storage.pendingHint", { size })}</span>
      </span>
      <button
        type="button"
        disabled={busy}
        aria-label={t("storage.confirmButton")}
        onClick={(event) => {
          event.stopPropagation();
          askAndReclaim();
        }}
        className="shrink-0 cursor-pointer rounded-full border border-[var(--color-warning)]/40 bg-white/60 px-1.5 py-0.5 text-[10px] font-semibold text-[var(--color-warning)] transition-colors hover:bg-white/90 disabled:cursor-wait dark:bg-white/10"
      >
        {t("storage.confirmButton")}
      </button>
    </div>
  );
}
