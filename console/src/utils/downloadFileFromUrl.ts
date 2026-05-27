import { save } from "@tauri-apps/plugin-dialog";
import { writeFile } from "@tauri-apps/plugin-fs";
import { getApiUrl } from "../api/config";
import {
  isBackendHostedConsole,
  isTauriRuntime,
} from "../tauri/backendRuntime";
import { isHttpExternalUrl, resolveExternalUrl } from "./openExternalLink";

export interface DownloadFileOptions {
  headers?: Record<string, string>;
  errorMessage?: string;
  preferResponseFilename?: boolean;
}

type PyWebViewApi = NonNullable<Window["pywebview"]>["api"];
type DownloadDiagnosticStep =
  | "save-start"
  | "save-cancel"
  | "save-success"
  | "save-error"
  | "fetch-start"
  | "fetch-success"
  | "fetch-error"
  | "write-start"
  | "write-success"
  | "write-error";

interface DownloadDiagnosticPayload {
  step: DownloadDiagnosticStep;
  url?: string;
  filename?: string;
  status?: number;
  bytes?: number;
  has_save_path?: boolean;
  error?: { name: string; message: string };
}

function getPyWebViewApi(): PyWebViewApi | undefined {
  return window.pywebview?.api;
}

function filenameFromContentDisposition(value: string | null): string {
  if (!value) return "";

  const utf8Match = value.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8Match?.[1]) {
    try {
      return decodeURIComponent(utf8Match[1]);
    } catch {
      return utf8Match[1];
    }
  }

  const quotedMatch = value.match(/filename="([^"]+)"/i);
  if (quotedMatch?.[1]) {
    return quotedMatch[1];
  }

  const bareMatch = value.match(/filename=([^;]+)/i);
  return bareMatch?.[1]?.trim() ?? "";
}

function triggerBrowserDownload(blob: Blob, filename: string): void {
  const a = document.createElement("a");
  const objectUrl = URL.createObjectURL(blob);
  a.href = objectUrl;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => URL.revokeObjectURL(objectUrl), 0);
  document.body.removeChild(a);
}

function sanitizeSaveFilename(filename: string): string {
  const sanitized = filename
    .replace(/[<>:"/\\|?*]/g, "_")
    .trim()
    .replace(/[. ]+$/g, "");
  return sanitized || "download";
}

function downloadUrlForLog(url: string): string {
  try {
    const parsedUrl = new URL(url);
    return `${parsedUrl.protocol}//${parsedUrl.host}${parsedUrl.pathname}`;
  } catch {
    return "<unparseable>";
  }
}

function errorForDiagnostic(error: unknown): { name: string; message: string } {
  if (error instanceof Error) {
    return { name: error.name, message: error.message };
  }
  return { name: typeof error, message: String(error) };
}

function statusFromError(error: unknown): number | undefined {
  if (
    error &&
    typeof error === "object" &&
    "status" in error &&
    typeof error.status === "number"
  ) {
    return error.status;
  }
  return undefined;
}

async function logTauriDownloadDiagnostic(
  options: DownloadFileOptions,
  payload: DownloadDiagnosticPayload,
): Promise<void> {
  if (!isBackendHostedConsole()) return;

  try {
    await fetch(getApiUrl("/desktop/diagnostics"), {
      method: "POST",
      headers: {
        ...options.headers,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        source: "download-file",
        page_url: downloadUrlForLog(window.location.href),
        ...payload,
      }),
    });
  } catch (error) {
    console.warn("[download] failed to write desktop diagnostic", error);
  }
}

async function fetchDownloadBlob(
  url: string,
  options: DownloadFileOptions,
): Promise<{ blob: Blob; filename: string }> {
  const res = await fetch(url, { headers: options.headers });
  if (!res.ok) {
    const error = new Error(
      options.errorMessage || `Download failed: ${res.status}`,
    ) as Error & { status?: number };
    error.status = res.status;
    throw error;
  }

  const filename = options.preferResponseFilename
    ? filenameFromContentDisposition(res.headers.get("Content-Disposition"))
    : "";
  return { blob: await res.blob(), filename };
}

export async function downloadFileFromUrl(
  url: string,
  filename: string,
  options: DownloadFileOptions = {},
): Promise<boolean> {
  if (!url) return false;

  const requestUrl = resolveExternalUrl(url);
  if (!requestUrl) return false;

  const safeFilename = sanitizeSaveFilename(filename);
  const pywebviewApi = getPyWebViewApi();
  if (pywebviewApi?.save_file && isHttpExternalUrl(requestUrl)) {
    return pywebviewApi.save_file(requestUrl, safeFilename);
  }

  if (isTauriRuntime()) {
    const urlForLog = downloadUrlForLog(requestUrl);
    await logTauriDownloadDiagnostic(options, {
      step: "save-start",
      filename: safeFilename,
      url: urlForLog,
    });

    let savePath: string | null;
    try {
      savePath = await save({
        defaultPath: safeFilename,
      });
    } catch (error) {
      await logTauriDownloadDiagnostic(options, {
        step: "save-error",
        filename: safeFilename,
        url: urlForLog,
        error: errorForDiagnostic(error),
      });
      throw error;
    }

    // False means the user cancelled the native save dialog; it is not an error.
    if (!savePath) {
      await logTauriDownloadDiagnostic(options, {
        step: "save-cancel",
        filename: safeFilename,
        url: urlForLog,
        has_save_path: false,
      });
      return false;
    }

    await logTauriDownloadDiagnostic(options, {
      step: "save-success",
      filename: safeFilename,
      url: urlForLog,
      has_save_path: true,
    });

    let blob: Blob;
    try {
      await logTauriDownloadDiagnostic(options, {
        step: "fetch-start",
        filename: safeFilename,
        url: urlForLog,
      });
      ({ blob } = await fetchDownloadBlob(requestUrl, options));
      await logTauriDownloadDiagnostic(options, {
        step: "fetch-success",
        filename: safeFilename,
        url: urlForLog,
        bytes: blob.size,
      });
    } catch (error) {
      await logTauriDownloadDiagnostic(options, {
        step: "fetch-error",
        filename: safeFilename,
        url: urlForLog,
        status: statusFromError(error),
        error: errorForDiagnostic(error),
      });
      throw error;
    }

    try {
      await logTauriDownloadDiagnostic(options, {
        step: "write-start",
        filename: safeFilename,
        url: urlForLog,
        bytes: blob.size,
      });
      await writeFile(savePath, new Uint8Array(await blob.arrayBuffer()));
      await logTauriDownloadDiagnostic(options, {
        step: "write-success",
        filename: safeFilename,
        url: urlForLog,
        bytes: blob.size,
      });
    } catch (error) {
      await logTauriDownloadDiagnostic(options, {
        step: "write-error",
        filename: safeFilename,
        url: urlForLog,
        bytes: blob.size,
        error: errorForDiagnostic(error),
      });
      throw error;
    }

    return true;
  }

  const { blob, filename: responseFilename } = await fetchDownloadBlob(
    requestUrl,
    options,
  );
  triggerBrowserDownload(blob, responseFilename || filename);
  return true;
}
