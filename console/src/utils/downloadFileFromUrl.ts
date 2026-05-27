import { save } from "@tauri-apps/plugin-dialog";
import { writeFile } from "@tauri-apps/plugin-fs";
import { isTauriRuntime } from "../tauri/backendRuntime";
import { isHttpExternalUrl, resolveExternalUrl } from "./openExternalLink";

export interface DownloadFileOptions {
  headers?: Record<string, string>;
  errorMessage?: string;
  preferResponseFilename?: boolean;
}

type PyWebViewApi = NonNullable<Window["pywebview"]>["api"];

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
    const savePath = await save({
      defaultPath: safeFilename,
    });
    // False means the user cancelled the native save dialog; it is not an error.
    if (!savePath) {
      return false;
    }

    const { blob } = await fetchDownloadBlob(requestUrl, options);
    await writeFile(savePath, new Uint8Array(await blob.arrayBuffer()));
    return true;
  }

  const { blob, filename: responseFilename } = await fetchDownloadBlob(
    requestUrl,
    options,
  );
  triggerBrowserDownload(blob, responseFilename || filename);
  return true;
}
