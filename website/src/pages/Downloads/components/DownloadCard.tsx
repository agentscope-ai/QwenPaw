import { useState } from "react";
import { Download, Monitor, type LucideIcon } from "lucide-react";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";
import { ClampedDescription } from "./ClampedDescription";
import { CDN_BASE } from "../constants";
import type { FileMetadata } from "../types";
import { isPreviewVersion, pickLocalizedField } from "../utils";

interface DownloadCardProps {
  versions: FileMetadata[];
  latestStableFileId: string | null;
  icon?: LucideIcon;
  isRecommended?: boolean;
  kindLabel?: string;
  downloadLabelKey?: "downloads.download" | "downloads.downloadZip";
}

export function DownloadCard({
  versions,
  latestStableFileId,
  icon: Icon = Monitor,
  isRecommended = false,
  kindLabel,
  downloadLabelKey = "downloads.download",
}: DownloadCardProps) {
  const { t, i18n } = useTranslation();
  const language = i18n.resolvedLanguage;
  const [selectedFileId, setSelectedFileId] = useState(versions[0]?.id ?? "");

  const selected =
    versions.find((item) => item.id === selectedFileId) ?? versions[0];

  if (!selected) {
    return null;
  }

  const name = pickLocalizedField(selected.name, language);
  const description = pickLocalizedField(selected.description, language);
  const updatedDate = new Date(selected.updated_at).toLocaleDateString(
    language?.startsWith("zh") ? "zh-CN" : "en-US",
  );
  const downloadUrl = `${CDN_BASE}${selected.url}`;
  const stableVersions = versions.filter(
    (item) => !isPreviewVersion(item.version),
  );
  const previewVersions = versions.filter((item) =>
    isPreviewVersion(item.version),
  );

  return (
    <div
      className={cn(
        "relative z-0 rounded-lg border p-5",
        "shadow-[0_1px_2px_rgba(28,28,28,0.04)]",
        "transition-all duration-300 ease-out",
        "hover:z-20 hover:-translate-y-0.5 hover:bg-[#FEFAF8] hover:shadow-[0_4px_12px_rgba(0,0,0,0.06)]",
        "hover:border-(--color-primary)",
        isRecommended
          ? "border-2 border-(--color-primary) bg-[#FEFAF8]"
          : "border border-border bg-surface",
      )}
    >
      <div className="mb-3 flex items-start gap-3">
        <div className="flex size-11 shrink-0 items-center justify-center rounded-lg bg-site-text text-white">
          <Icon size={22} strokeWidth={2} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="mb-1 flex flex-wrap items-center gap-2">
            <h4 className="text-base font-bold text-site-text">{name}</h4>
            <span className="text-sm font-normal text-site-text-muted">
              v{selected.version}
            </span>
            {selected.author && (
              <span className="text-sm font-normal text-site-text-muted">
                · {selected.author}
              </span>
            )}
            {isRecommended && (
              <span className="inline-flex items-center rounded-sm bg-[rgba(255,106,0,0.1)] px-2 py-1 text-xs font-medium text-[#FF6A00]">
                {t("downloads.recommended")}
              </span>
            )}
            {kindLabel && (
              <span className="inline-flex items-center rounded border border-border bg-site-bg px-1.5 py-0.5 text-[12px] font-medium text-site-text-muted">
                {kindLabel}
              </span>
            )}
          </div>
          <div className="min-h-12 text-sm text-site-text-muted">
            {description ? <ClampedDescription text={description} /> : null}
          </div>
        </div>
      </div>

      {versions.length > 1 && (
        <label className="mb-4 block">
          <span className="mb-1.5 block text-sm font-medium text-site-text">
            {t("downloads.selectVersion")}
          </span>
          <select
            className="w-full cursor-pointer appearance-none rounded-md border border-border bg-surface py-2.5 pr-10 pl-3 text-sm text-site-text transition-colors hover:border-(--color-primary) focus:outline-none focus-visible:border-(--color-primary) focus-visible:ring-2 focus-visible:ring-(--color-primary)/15"
            style={{
              backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='%236b6b6b' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolyline points='6 9 12 15 18 9'%3E%3C/polyline%3E%3C/svg%3E")`,
              backgroundRepeat: "no-repeat",
              backgroundPosition: "right 1rem center",
              backgroundSize: "16px",
            }}
            value={selectedFileId}
            onChange={(e) => {
              setSelectedFileId(e.target.value);
              e.currentTarget.blur();
            }}
          >
            {stableVersions.length > 0 &&
              stableVersions.map((versionItem) => (
                <option key={versionItem.id} value={versionItem.id}>
                  v{versionItem.version}
                  {latestStableFileId === versionItem.id
                    ? ` (${t("downloads.latest")})`
                    : ""}
                </option>
              ))}
            {previewVersions.length > 0 && (
              <optgroup label="Preview">
                {previewVersions.map((versionItem) => (
                  <option key={versionItem.id} value={versionItem.id}>
                    v{versionItem.version}
                  </option>
                ))}
              </optgroup>
            )}
          </select>
        </label>
      )}

      <a
        href={downloadUrl}
        download
        className="mb-4 flex w-full items-center justify-center gap-2 rounded-md bg-site-text px-4 py-2.5 text-sm font-medium text-white no-underline transition-colors hover:bg-site-text/90"
      >
        <Download size={16} strokeWidth={2.5} />
        {t(downloadLabelKey)}
      </a>

      <div className="rounded-md bg-[rgba(245,245,245,0.38)] p-4 text-sm">
        <dl className="m-0 space-y-4">
          <DetailRow label={t("downloads.version")} value={selected.version} />
          <DetailRow label={t("downloads.size")} value={selected.size} />
          <DetailRow label={t("downloads.updated")} value={updatedDate} />
          <div>
            <div className="my-3 border-t border-border" />
            <dt className="mb-1 font-medium text-site-text-muted">SHA256:</dt>
            <dd className="m-0 font-mono text-xs leading-relaxed break-all text-site-text-muted">
              {selected.sha256}
            </dd>
          </div>
        </dl>
      </div>
    </div>
  );
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-4">
      <dt className="shrink-0 font-medium text-site-text-muted">{label}:</dt>
      <dd className="m-0 min-w-0 text-right text-site-text">{value}</dd>
    </div>
  );
}
