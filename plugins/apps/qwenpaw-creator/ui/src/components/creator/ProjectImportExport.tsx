import { useCallback, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import i18n from "@/i18n";
import { Modal, Progress, message } from "antd";
import { X } from "lucide-react";
import {
  creatorApiUrl,
  creatorFetch,
  creatorHeaders,
  newClientId,
} from "@/api/creator";

interface ProjectImportResponse {
  projectId: string;
}

function importProject(
  file: File,
  onProgress?: (uploadedBytes: number, totalBytes: number) => void,
): Promise<ProjectImportResponse> {
  const form = new FormData();
  const requestId = newClientId("import-project");
  form.append("clientRequestId", requestId);
  form.append("file", file, file.name);

  // fetch() has no upload-progress events, so use XMLHttpRequest to report
  // the uploaded byte count to the UI while the request is in flight.
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", creatorApiUrl("/projects/import"));
    const headers = creatorHeaders({ "Idempotency-Key": requestId });
    headers.forEach((value, key) => xhr.setRequestHeader(key, value));

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) {
        onProgress?.(event.loaded, event.total);
      }
    };

    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText) as ProjectImportResponse);
        } catch {
          reject(new Error(i18n.t("lib.importFailedParse")));
        }
        return;
      }
      let msg = i18n.t("lib.importFailedHttp", { status: xhr.status });
      try {
        const body = JSON.parse(xhr.responseText);
        if (body?.message) msg = body.message;
      } catch {
        /* keep default message */
      }
      reject(new Error(msg));
    };
    xhr.onerror = () => reject(new Error(i18n.t("lib.importFailedNetwork")));
    xhr.onabort = () => reject(new Error(i18n.t("lib.importFailedCancelled")));

    xhr.send(form);
  });
}

interface ProjectImporterProps {
  open: boolean;
  onClose: () => void;
  onImported?: () => void;
}

/**
 * Import dialog from the design draft: a 64px title bar, then either a
 * dashed drop target or, once a zip is picked, the file name over an upload
 * progress bar. Upload starts as soon as a file is chosen.
 */
export function ProjectImporter({
  open,
  onClose,
  onImported,
}: ProjectImporterProps) {
  const { t } = useTranslation();
  const [uploading, setUploading] = useState(false);
  const [fileName, setFileName] = useState<string | null>(null);
  const [percent, setPercent] = useState(0);
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const reset = useCallback(() => {
    setUploading(false);
    setFileName(null);
    setPercent(0);
    setDragOver(false);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }, []);

  const handleClose = useCallback(() => {
    if (uploading) return;
    reset();
    onClose();
  }, [uploading, reset, onClose]);

  const upload = useCallback(
    async (file: File) => {
      if (file.name.split(".").pop()?.toUpperCase() !== "ZIP") {
        message.error(t("importExport.zipOnly"));
        return;
      }
      setFileName(file.name);
      setPercent(0);
      setUploading(true);
      try {
        const response = await importProject(file, (loaded, total) => {
          setPercent(total > 0 ? Math.round((loaded / total) * 100) : 0);
        });
        message.success(
          t("importExport.importSuccess", { projectId: response.projectId }),
          10,
        );
        reset();
        onClose();
        onImported?.();
      } catch (error) {
        message.error(
          error instanceof Error
            ? error.message
            : t("importExport.importFailed"),
          10,
        );
        reset();
      }
    },
    [reset, onClose, onImported],
  );

  return (
    <Modal
      open={open}
      onCancel={handleClose}
      footer={null}
      width={680}
      centered
      closable={false}
      destroyOnHidden
      title={null}
      styles={{ container: { padding: 0, overflow: "hidden" } }}
    >
      <div className="flex h-16 items-center justify-between border-b border-[#EAE9E7] pl-5 pr-3">
        <span className="text-base font-medium leading-7 text-[var(--color-text-primary)]">
          {t("importExport.importTitle")}
        </span>
        <button
          type="button"
          onClick={handleClose}
          disabled={uploading}
          aria-label={t("common.close")}
          className="flex h-10 w-10 cursor-pointer items-center justify-center rounded-lg text-[var(--color-text-secondary)] transition-colors hover:bg-[rgba(43,27,0,0.04)] disabled:cursor-not-allowed disabled:opacity-50"
        >
          <X className="h-5 w-5" />
        </button>
      </div>

      <div className="p-5">
        {fileName ? (
          <div className="flex h-[134px] flex-col items-center justify-center gap-4 rounded-md bg-white px-4">
            <span className="max-w-full truncate text-base font-medium leading-7 text-[var(--color-text-primary)]">
              {fileName}
            </span>
            <div className="w-[400px] max-w-full">
              <Progress
                percent={percent}
                status={uploading ? "active" : undefined}
                strokeColor="var(--color-accent)"
              />
            </div>
          </div>
        ) : (
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            onDragOver={(e) => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragOver(false);
              const file = e.dataTransfer.files?.[0];
              if (file) void upload(file);
            }}
            className={`flex h-[134px] w-full cursor-pointer flex-col items-center justify-center gap-2.5 rounded-md border-2 border-dashed bg-white transition-colors ${
              dragOver
                ? "border-[var(--color-accent)] bg-[var(--color-accent-soft)]"
                : "border-[#EAE9E7] hover:border-[var(--color-accent)]"
            }`}
          >
            <span className="text-base font-medium leading-7 text-[var(--color-text-primary)]">
              {t("importExport.dropzone")}
            </span>
            <span className="text-sm leading-6 text-[rgba(26,26,29,0.45)]">
              {t("importExport.dropzoneDesc")}
            </span>
          </button>
        )}
        <input
          ref={fileInputRef}
          type="file"
          accept=".zip"
          hidden
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) void upload(file);
            e.target.value = "";
          }}
        />
      </div>
    </Modal>
  );
}

export async function saveExportFile(
  projectId: string,
  onProgress?: (receivedBytes: number, totalBytes: number | null) => void,
) {
  const response = await creatorFetch(
    `/projects/${encodeURIComponent(projectId)}/export`,
    {
      method: "GET",
      headers: { "Idempotency-Key": newClientId("export-project") },
    },
  );
  if (!response.ok) {
    throw new Error(
      i18n.t("lib.exportFailedHttp", { status: response.status }),
    );
  }
  if (!response.body) {
    throw new Error(i18n.t("lib.exportFailedNoData"));
  }

  let filename = `${projectId}.zip`;
  const disposition = response.headers.get("Content-Disposition");
  if (disposition) {
    const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(disposition);
    if (match?.[1]) {
      filename = decodeURIComponent(match[1]);
    }
  }

  // The backend advertises the archive size; without it the UI can still
  // report the downloaded byte count.
  const lengthHeader = Number(response.headers.get("Content-Length"));
  const totalBytes =
    Number.isFinite(lengthHeader) && lengthHeader > 0 ? lengthHeader : null;

  const reader = response.body.getReader();
  const chunks: BlobPart[] = [];
  let receivedBytes = 0;
  onProgress?.(0, totalBytes);

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value as BlobPart);
    receivedBytes += value.byteLength;
    onProgress?.(receivedBytes, totalBytes);
  }

  const blob = new Blob(chunks);

  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export interface ExportProgressState {
  receivedBytes: number;
  totalBytes: number | null;
  status: "running" | "done";
}

export function formatBytes(bytes: number): string {
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = Math.max(0, bytes);
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index += 1;
  }
  return `${index === 0 ? Math.round(value) : value.toFixed(1)} ${
    units[index]
  }`;
}

interface ExportProgressCardProps {
  projectName: string;
  progress: ExportProgressState;
  onDismiss: () => void;
}

/**
 * Floating card reporting export percent and byte size while the archive
 * streams down. Pinned bottom-left so it never fights the AgentDock capsule.
 */
export function ExportProgressCard({
  projectName,
  progress,
  onDismiss,
}: ExportProgressCardProps) {
  const { t } = useTranslation();
  const done = progress.status === "done";
  const percent = done
    ? 100
    : progress.totalBytes
    ? Math.min(
        99,
        Math.floor((progress.receivedBytes / progress.totalBytes) * 100),
      )
    : null;
  const sizeText = progress.totalBytes
    ? `${formatBytes(progress.receivedBytes)} / ${formatBytes(
        progress.totalBytes,
      )}`
    : formatBytes(progress.receivedBytes);
  return (
    <div
      data-export-progress
      className="fixed bottom-5 left-5 z-50 w-[300px] rounded-lg border border-[#EAE9E7] bg-white px-4 py-3 shadow-[0_8px_24px_rgba(0,0,0,0.12)]"
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-medium text-[var(--color-text-primary)]">
          {done ? t("importExport.exportDone") : t("importExport.exporting")}
        </span>
        <button
          type="button"
          onClick={onDismiss}
          aria-label={t("importExport.closeExportProgress")}
          className="flex h-6 w-6 shrink-0 cursor-pointer items-center justify-center rounded text-[var(--color-text-secondary)] transition-colors hover:bg-[rgba(43,27,0,0.04)]"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
      <p className="mt-0.5 truncate text-xs text-[var(--color-text-tertiary)]">
        {projectName}
      </p>
      <Progress
        percent={percent ?? 100}
        status={done ? "success" : "active"}
        showInfo={percent !== null}
        strokeColor="var(--color-accent)"
      />
      <div
        data-export-progress-size
        className="text-xs text-[var(--color-text-secondary)]"
      >
        {sizeText}
      </div>
    </div>
  );
}
