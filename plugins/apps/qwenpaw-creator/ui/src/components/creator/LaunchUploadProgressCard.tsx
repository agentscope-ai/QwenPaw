import { useTranslation } from "react-i18next";
import { UploadCloud, X } from "lucide-react";
import { useParams } from "@/routing/navigation";
import { useLaunchUploadStore } from "@/store/launchUploadStore";

/**
 * Floating launch-upload progress card (bottom-left, mirroring the export
 * progress card): the composer navigates to the project page immediately,
 * so this card is how the user sees their attachments still uploading and
 * the first Agent message being prepared.
 */
export default function LaunchUploadProgressCard() {
  const { t } = useTranslation();
  const { id = "" } = useParams();
  const projectId = useLaunchUploadStore((state) => state.projectId);
  const phase = useLaunchUploadStore((state) => state.phase);
  const total = useLaunchUploadStore((state) => state.total);
  const done = useLaunchUploadStore((state) => state.done);
  const failed = useLaunchUploadStore((state) => state.failed);
  const reset = useLaunchUploadStore((state) => state.reset);
  if (!projectId || id !== projectId) return null;
  if (phase === "done") return null;
  const percent =
    phase === "messaging"
      ? 100
      : total > 0
      ? Math.min(99, Math.floor((done / total) * 100))
      : 0;
  const label =
    phase === "error"
      ? t("launchUpload.failed")
      : phase === "messaging"
      ? t("launchUpload.messaging")
      : t("launchUpload.uploading", { done, total });
  return (
    <div
      data-launch-upload-progress
      className="fixed bottom-5 left-5 z-50 w-[300px] rounded-lg border border-[#EAE9E7] bg-white px-4 py-3 shadow-[0_8px_24px_rgba(0,0,0,0.12)]"
    >
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-2 text-sm font-medium text-[var(--color-text-primary)]">
          <UploadCloud className="h-4 w-4 text-[var(--color-accent)]" />
          {label}
        </span>
        {phase === "error" ? (
          <button
            type="button"
            onClick={reset}
            aria-label={t("launchUpload.dismiss")}
            className="flex h-6 w-6 shrink-0 cursor-pointer items-center justify-center rounded text-[var(--color-text-secondary)] transition-colors hover:bg-[rgba(43,27,0,0.04)]"
          >
            <X className="h-4 w-4" />
          </button>
        ) : (
          <span className="text-xs font-semibold text-[var(--color-accent)]">
            {percent}%
          </span>
        )}
      </div>
      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-[rgba(43,27,0,0.06)]">
        <div
          className="h-full rounded-full bg-[var(--color-accent)] transition-[width] duration-300"
          style={{ width: `${percent}%` }}
        />
      </div>
      {failed > 0 && phase !== "error" ? (
        <p className="mt-1 text-xs text-[var(--color-text-tertiary)]">
          {t("launchUpload.partialFailed", { failed })}
        </p>
      ) : null}
    </div>
  );
}
