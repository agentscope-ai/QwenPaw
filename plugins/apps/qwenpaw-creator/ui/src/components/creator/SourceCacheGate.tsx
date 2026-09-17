/** Download-original gate shown for bundled example Projects. */

import { useTranslation } from "react-i18next";
import { Button } from "antd";
import { Download, Loader2 } from "lucide-react";
import type { SourceCacheStatus } from "@/lib/sourceCache";
import { formatBytes } from "@/components/creator/ProjectImportExport";

interface SourceCacheGateProps {
  status: SourceCacheStatus;
  /** Compact banner variant (AgentDock) vs. full card (Assets page). */
  compact?: boolean;
}

export default function SourceCacheGate({
  status,
  compact = false,
}: SourceCacheGateProps) {
  const { t } = useTranslation();
  const pending = status.versions.filter((version) => !version.cached);
  if (pending.length === 0) return null;

  return (
    <div
      className={
        compact
          ? "rounded-lg border border-[#eae9e7] bg-white p-3"
          : "rounded-xl border border-[#eae9e7] bg-white p-5"
      }
    >
      <p className="flex items-center gap-2 text-sm font-medium text-[#474a52]">
        <Download className="h-4 w-4 text-[var(--color-accent)]" />
        {t("sourceCache.title")}
      </p>
      <p className="mt-1 text-xs leading-5 text-[#808080]">
        {t("sourceCache.description")}
      </p>
      <div className="mt-3 flex flex-col gap-2">
        {pending.map((version) => {
          const downloading = version.state === "downloading";
          const failed = version.state === "failed";
          const progress =
            downloading &&
            version.expectedSizeBytes &&
            version.expectedSizeBytes > 0
              ? Math.min(
                  100,
                  Math.round(
                    ((version.receivedBytes ?? 0) / version.expectedSizeBytes) *
                      100,
                  ),
                )
              : null;
          return (
            <div
              key={version.assetVersionId}
              className="flex items-center gap-3 rounded-lg border border-[#f0efed] px-3 py-2"
            >
              <div className="min-w-0 flex-1">
                <p className="truncate text-xs font-medium text-[#474a52]">
                  {version.name}
                </p>
                <p className="text-[11px] text-[#a3a3a3]">
                  {version.expectedSizeBytes
                    ? downloading && version.receivedBytes !== undefined
                      ? `${formatBytes(version.receivedBytes)} / ${formatBytes(
                          version.expectedSizeBytes,
                        )}`
                      : formatBytes(version.expectedSizeBytes)
                    : ""}
                </p>
                {downloading && (
                  <div className="mt-1 h-1 w-full overflow-hidden rounded-full bg-[#eae9e7]">
                    <div
                      className="h-full rounded-full bg-[var(--color-accent)] transition-[width] duration-300"
                      style={{ width: `${progress ?? 5}%` }}
                    />
                  </div>
                )}
                {failed && version.error && (
                  <p className="mt-0.5 text-[11px] text-red-500">
                    {t("sourceCache.failed", { message: version.error })}
                  </p>
                )}
              </div>
              <Button
                size="small"
                type={failed ? "default" : "primary"}
                disabled={downloading || status.triggering}
                onClick={() => void status.download(version.assetVersionId)}
              >
                {downloading ? (
                  <span className="flex items-center gap-1">
                    <Loader2 className="h-3 w-3 animate-spin" />
                    {t("sourceCache.downloading")}
                  </span>
                ) : failed ? (
                  t("sourceCache.retry")
                ) : (
                  t("sourceCache.download")
                )}
              </Button>
            </div>
          );
        })}
      </div>
    </div>
  );
}
