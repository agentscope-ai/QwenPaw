/**
 * Unit tests for the cross-runtime download helper.
 *
 * What this file pins:
 * - Runtime selection order: the legacy pywebview bridge wins over Tauri, and
 *   Tauri wins over the browser fetch path. A wrong order silently changes how
 *   every desktop user receives files, and no render level test would notice.
 * - Input validation: an empty URL and a non HTTP URL both reject with a
 *   message, never reach the network, and honour the caller errorMessage.
 * - Filename normalisation for native save dialogs, covering the reserved
 *   characters, trailing dot and space trimming, and the empty result that
 *   falls back to the literal name download.
 * - The browser path: caller headers forwarded, the blob anchored link clicked,
 *   the object URL revoked only after the deferred timer, and the
 *   Content-Disposition filename preferred solely when the caller asks for it
 *   (including its UTF-8'' extended form and its undecodable variant).
 * - Cancellation semantics: neither an empty Tauri save path nor a falsy
 *   pywebview result is an error. Both surface DownloadCancelledError, which
 *   MediaDownload distinguishes from a real failure by type.
 * - Failure wrapping: a Tauri invoke rejection is rethrown as the caller
 *   errorMessage with the original error kept on `cause`, and rethrown as is
 *   when no errorMessage was supplied.
 *
 * Harness notes (all stubs live in this file; no shared stub was edited):
 * - `@tauri-apps/api/core` and `@tauri-apps/plugin-dialog` are aliased by
 *   console/vite.config.ts to one and the same file (src/test/tauri-mock.ts),
 *   whose exports are already vi.fn() instances. Calling vi.mock twice on those
 *   two ids makes them fight over a single module id, so this file drives the
 *   stub exports directly instead of re-mocking them.
 * - ./openExternalLink is mocked so resolveExternalUrl and isHttpExternalUrl
 *   return fixed verdicts per test instead of depending on jsdom location.
 * - jsdom has no URL.createObjectURL or revokeObjectURL, so both are installed
 *   per test and restored afterwards (same approach as
 *   plugins/usePluginLoader.test.ts).
 * - The anchor click is observed through a prototype spy so jsdom never tries
 *   to navigate, and fake timers make the deferred revoke deterministic.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { invoke as tauriInvoke } from "@tauri-apps/api/core";
import { save as tauriSave } from "@tauri-apps/plugin-dialog";

const h = vi.hoisted(() => {
  const isDesktopTauriRuntime = vi.fn<() => boolean>();
  const resolveExternalUrl = vi.fn<(url: string) => string | null>();
  const isHttpExternalUrl = vi.fn<(url: string) => boolean>();
  const saveFile =
    vi.fn<
      (
        url: string,
        filename: string,
        headers?: Record<string, string>,
      ) => Promise<boolean>
    >();
  const getPyWebViewApi =
    vi.fn<() => { save_file: typeof saveFile } | undefined>();
  return {
    isDesktopTauriRuntime,
    resolveExternalUrl,
    isHttpExternalUrl,
    saveFile,
    getPyWebViewApi,
    anchors: [] as Array<{ href: string; download: string; clicked: number }>,
    createObjectURL: vi.fn<(blob: Blob) => string>(),
    revokeObjectURL: vi.fn<(url: string) => void>(),
    fetchMock: vi.fn<
      (
        url: string,
        init?: RequestInit,
      ) => Promise<{
        ok: boolean;
        status: number;
        headers: { get: (name: string) => string | null };
        blob: () => Promise<Blob>;
      }>
    >(),
  };
});

vi.mock("./openExternalLink", () => ({
  isDesktopTauriRuntime: h.isDesktopTauriRuntime,
  resolveExternalUrl: h.resolveExternalUrl,
  isHttpExternalUrl: h.isHttpExternalUrl,
}));
vi.mock("./pywebview", () => ({ getPyWebViewApi: h.getPyWebViewApi }));

import {
  DownloadCancelledError,
  downloadFileFromUrl,
} from "./downloadFileFromUrl";

// Type-only cast: at runtime these ARE the vi.fn() instances exported by the
// shared tauri stub that vite.config.ts aliases both ids to.
const invokeMock = vi.mocked(tauriInvoke);
const saveMock = vi.mocked(tauriSave);

const URL_OK = "https://host.example/files/report.bin";
const OBJECT_URL = "blob:stub-object-url";

/** Install a fetch stub answering with the given status and headers. */
function stubFetch(options: {
  ok: boolean;
  status?: number;
  disposition?: string | null;
  body?: string;
}): void {
  h.fetchMock.mockReset().mockResolvedValue({
    ok: options.ok,
    status: options.status ?? 200,
    headers: {
      get: (name: string) =>
        name.toLowerCase() === "content-disposition"
          ? options.disposition ?? null
          : null,
    },
    blob: async () => new Blob([options.body ?? "payload"]),
  });
}

let originalCreate: typeof URL.createObjectURL;
let originalRevoke: typeof URL.revokeObjectURL;
let clickSpy: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  // Every stub is reset here, including the fetch one: a leftover call record
  // from the previous test would otherwise satisfy or break the
  // not.toHaveBeenCalled assertions below.
  invokeMock.mockReset().mockResolvedValue(undefined);
  saveMock.mockReset().mockResolvedValue("/tmp/chosen.bin");
  h.fetchMock.mockReset();
  h.isDesktopTauriRuntime.mockReset().mockReturnValue(false);
  h.resolveExternalUrl.mockReset().mockImplementation((url: string) => url);
  h.isHttpExternalUrl.mockReset().mockReturnValue(true);
  h.getPyWebViewApi.mockReset().mockReturnValue(undefined);
  h.saveFile.mockReset().mockResolvedValue(true);
  h.anchors.length = 0;
  h.createObjectURL.mockReset().mockReturnValue(OBJECT_URL);
  h.revokeObjectURL.mockReset();

  originalCreate = URL.createObjectURL;
  originalRevoke = URL.revokeObjectURL;
  URL.createObjectURL =
    h.createObjectURL as unknown as typeof URL.createObjectURL;
  URL.revokeObjectURL =
    h.revokeObjectURL as unknown as typeof URL.revokeObjectURL;

  clickSpy = vi
    .spyOn(HTMLAnchorElement.prototype, "click")
    .mockImplementation(function (this: HTMLAnchorElement) {
      h.anchors.push({ href: this.href, download: this.download, clicked: 1 });
    });
  vi.stubGlobal("fetch", h.fetchMock);
});

afterEach(() => {
  clickSpy.mockRestore();
  URL.createObjectURL = originalCreate;
  URL.revokeObjectURL = originalRevoke;
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("downloadFileFromUrl - input validation", () => {
  it("rejects an empty URL with the default message and never resolves it", async () => {
    await expect(downloadFileFromUrl("", "name.bin")).rejects.toThrow(
      "Download URL is empty",
    );
    expect(h.resolveExternalUrl).not.toHaveBeenCalled();
    expect(h.fetchMock).not.toHaveBeenCalled();
    expect(tauriInvoke).not.toHaveBeenCalled();
  });

  it("honours the caller errorMessage for an empty URL", async () => {
    await expect(
      downloadFileFromUrl("", "name.bin", { errorMessage: "no file" }),
    ).rejects.toThrow("no file");
  });

  it("rejects when resolveExternalUrl cannot resolve the URL", async () => {
    h.resolveExternalUrl.mockReturnValue(null);
    await expect(
      downloadFileFromUrl("/relative/path", "name.bin"),
    ).rejects.toThrow("Download URL is invalid");
    expect(h.fetchMock).not.toHaveBeenCalled();
    expect(tauriInvoke).not.toHaveBeenCalled();
  });

  it("rejects a non HTTP external URL such as mailto", async () => {
    h.isHttpExternalUrl.mockReturnValue(false);
    await expect(
      downloadFileFromUrl("mailto:a@b.example", "name.bin", {
        errorMessage: "unsupported link",
      }),
    ).rejects.toThrow("unsupported link");
    expect(h.fetchMock).not.toHaveBeenCalled();
  });

  it("passes the resolved URL, not the raw one, to the chosen runtime", async () => {
    h.resolveExternalUrl.mockReturnValue(URL_OK);
    stubFetch({ ok: true });
    await downloadFileFromUrl("/local/report.bin", "report.bin");
    expect(h.fetchMock).toHaveBeenCalledWith(URL_OK, { headers: undefined });
  });
});

describe("downloadFileFromUrl - pywebview bridge", () => {
  beforeEach(() => {
    h.getPyWebViewApi.mockReturnValue({ save_file: h.saveFile });
  });

  it("prefers pywebview over Tauri even when both runtimes are present", async () => {
    h.isDesktopTauriRuntime.mockReturnValue(true);
    stubFetch({ ok: true });
    await downloadFileFromUrl(URL_OK, "report.bin");
    expect(h.saveFile).toHaveBeenCalledTimes(1);
    expect(tauriInvoke).not.toHaveBeenCalled();
    expect(tauriSave).not.toHaveBeenCalled();
    expect(h.fetchMock).not.toHaveBeenCalled();
  });

  it("calls save_file with two arguments when there are no headers", async () => {
    await downloadFileFromUrl(URL_OK, "report.bin");
    expect(h.saveFile).toHaveBeenCalledWith(URL_OK, "report.bin");
    expect(h.saveFile.mock.calls[0]).toHaveLength(2);
  });

  it("forwards headers as the third argument when they are present", async () => {
    await downloadFileFromUrl(URL_OK, "report.bin", {
      headers: { Authorization: "Bearer token" },
    });
    expect(h.saveFile).toHaveBeenCalledWith(URL_OK, "report.bin", {
      Authorization: "Bearer token",
    });
    expect(h.saveFile.mock.calls[0]).toHaveLength(3);
  });

  it("does not pass a third argument for an empty headers object", async () => {
    await downloadFileFromUrl(URL_OK, "report.bin", { headers: {} });
    expect(h.saveFile).toHaveBeenCalledWith(URL_OK, "report.bin");
    expect(h.saveFile.mock.calls[0]).toHaveLength(2);
  });

  it("throws DownloadCancelledError when the bridge reports a falsy save", async () => {
    h.saveFile.mockResolvedValue(false);
    await expect(
      downloadFileFromUrl(URL_OK, "report.bin"),
    ).rejects.toBeInstanceOf(DownloadCancelledError);
  });
});

describe("downloadFileFromUrl - Tauri runtime", () => {
  beforeEach(() => {
    h.isDesktopTauriRuntime.mockReturnValue(true);
  });

  it("asks the native dialog for the sanitised default path", async () => {
    // Runtime value of the literal below is:  bad<>:"/\|?*name.bin
    // Nine reserved characters each become one underscore (verified with node
    // against the product regex, not guessed).
    await downloadFileFromUrl(URL_OK, 'bad<>:"/\\|?*name.bin');
    expect(tauriSave).toHaveBeenCalledWith({
      defaultPath: "bad_________name.bin",
    });
    expect(tauriInvoke).toHaveBeenCalledTimes(1);
  });

  it("streams through the Rust command with the chosen path and headers", async () => {
    await downloadFileFromUrl(URL_OK, "report.bin", {
      headers: { "X-Key": "v" },
    });
    expect(tauriInvoke).toHaveBeenCalledWith("download_backend_file", {
      request: {
        url: URL_OK,
        filePath: "/tmp/chosen.bin",
        headers: { "X-Key": "v" },
      },
    });
    expect(h.fetchMock).not.toHaveBeenCalled();
  });

  it("treats a null save path as a cancellation, not a failure", async () => {
    saveMock.mockResolvedValue(null);
    await expect(
      downloadFileFromUrl(URL_OK, "report.bin"),
    ).rejects.toBeInstanceOf(DownloadCancelledError);
    expect(tauriInvoke).not.toHaveBeenCalled();
  });

  it("keeps the empty string save path as a cancellation too", async () => {
    saveMock.mockResolvedValue("");
    await expect(
      downloadFileFromUrl(URL_OK, "report.bin"),
    ).rejects.toBeInstanceOf(DownloadCancelledError);
    expect(tauriInvoke).not.toHaveBeenCalled();
  });

  it("wraps an invoke rejection in errorMessage and keeps the cause", async () => {
    const boom = new Error("rust io failure");
    invokeMock.mockRejectedValue(boom);
    await expect(
      downloadFileFromUrl(URL_OK, "report.bin", {
        errorMessage: "save failed",
      }),
    ).rejects.toMatchObject({ message: "save failed", cause: boom });
  });

  it("rethrows the original error when no errorMessage was supplied", async () => {
    const boom = new Error("rust io failure");
    invokeMock.mockRejectedValue(boom);
    await expect(downloadFileFromUrl(URL_OK, "report.bin")).rejects.toBe(boom);
  });
});

describe("downloadFileFromUrl - filename normalisation", () => {
  beforeEach(() => {
    h.isDesktopTauriRuntime.mockReturnValue(true);
  });

  it("replaces reserved characters and trims trailing dots and spaces", async () => {
    // Runtime value: two leading spaces, nine reserved characters, then a
    // trailing ". . " that the product regex strips. Expected value verified
    // with node against the product regex.
    await downloadFileFromUrl(URL_OK, '  a<b>c:d"e/f\\g|h?i*j. . ');
    expect(tauriSave).toHaveBeenCalledWith({
      defaultPath: "a_b_c_d_e_f_g_h_i_j",
    });
  });

  it("falls back to the literal name download for a dots only filename", async () => {
    await downloadFileFromUrl(URL_OK, "...");
    expect(tauriSave).toHaveBeenCalledWith({ defaultPath: "download" });
  });

  it("falls back to the literal name download for a spaces only filename", async () => {
    await downloadFileFromUrl(URL_OK, "   ");
    expect(tauriSave).toHaveBeenCalledWith({ defaultPath: "download" });
  });

  it("replaces but does not drop a name made only of reserved characters", async () => {
    // <> is not trimmed by the trailing dot and space rule, so the underscores
    // survive and the download fallback does not apply.
    await downloadFileFromUrl(URL_OK, "<>");
    expect(tauriSave).toHaveBeenCalledWith({ defaultPath: "__" });
  });

  it("leaves an already safe filename untouched", async () => {
    await downloadFileFromUrl(URL_OK, "report.v2-final_2026.bin");
    expect(tauriSave).toHaveBeenCalledWith({
      defaultPath: "report.v2-final_2026.bin",
    });
  });

  it("trims a single trailing dot and space", async () => {
    await downloadFileFromUrl(URL_OK, "trailing. ");
    expect(tauriSave).toHaveBeenCalledWith({ defaultPath: "trailing" });
  });

  it("sanitises the browser path filename as well", async () => {
    h.isDesktopTauriRuntime.mockReturnValue(false);
    stubFetch({ ok: true });
    await downloadFileFromUrl(URL_OK, "weird<>name.bin");
    expect(h.anchors).toHaveLength(1);
    expect(h.anchors[0].download).toBe("weird__name.bin");
    expect(tauriSave).not.toHaveBeenCalled();
  });
});

describe("downloadFileFromUrl - browser path", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  it("fetches with the caller headers, clicks the anchor and revokes later", async () => {
    stubFetch({ ok: true });
    await downloadFileFromUrl(URL_OK, "report.bin", {
      headers: { Authorization: "Bearer t" },
    });
    expect(h.fetchMock).toHaveBeenCalledWith(URL_OK, {
      headers: { Authorization: "Bearer t" },
    });
    expect(h.createObjectURL).toHaveBeenCalledTimes(1);
    expect(h.anchors).toHaveLength(1);
    expect(h.anchors[0]).toEqual({
      href: OBJECT_URL,
      download: "report.bin",
      clicked: 1,
    });
    // Cleanup is deferred with setTimeout(..., 0), so it has not run yet.
    expect(h.revokeObjectURL).not.toHaveBeenCalled();
    vi.runAllTimers();
    expect(h.revokeObjectURL).toHaveBeenCalledWith(OBJECT_URL);
  });

  it("throws with the status in the message when the response is not ok", async () => {
    stubFetch({ ok: false, status: 503 });
    await expect(downloadFileFromUrl(URL_OK, "report.bin")).rejects.toThrow(
      "Download failed: 503",
    );
    expect(h.createObjectURL).not.toHaveBeenCalled();
    expect(h.anchors).toHaveLength(0);
  });

  it("prefers the caller errorMessage over the status message", async () => {
    stubFetch({ ok: false, status: 404 });
    await expect(
      downloadFileFromUrl(URL_OK, "report.bin", {
        errorMessage: "file gone",
      }),
    ).rejects.toMatchObject({ message: "file gone", status: 404 });
  });

  it("keeps the suggested filename when preferResponseFilename is off", async () => {
    stubFetch({ ok: true, disposition: 'attachment; filename="server.bin"' });
    await downloadFileFromUrl(URL_OK, "local.bin");
    expect(h.anchors[0].download).toBe("local.bin");
  });

  it("uses the quoted Content-Disposition filename when asked for it", async () => {
    stubFetch({ ok: true, disposition: 'attachment; filename="server.bin"' });
    await downloadFileFromUrl(URL_OK, "local.bin", {
      preferResponseFilename: true,
    });
    expect(h.anchors[0].download).toBe("server.bin");
  });

  it("decodes the UTF-8 extended form of Content-Disposition", async () => {
    stubFetch({
      ok: true,
      disposition: "attachment; filename*=UTF-8''%E6%8A%A5%E5%91%8A.bin",
    });
    await downloadFileFromUrl(URL_OK, "local.bin", {
      preferResponseFilename: true,
    });
    // decodeURIComponent of that payload is the CJK word for report, which the
    // reserved character rule leaves untouched.
    expect(h.anchors[0].download).toBe("\u62a5\u544a.bin");
  });

  it("keeps the raw payload when it is not decodable", async () => {
    // %E0%A4%A is a truncated UTF-8 escape, so decodeURIComponent throws and
    // the product code falls back to the raw matched value.
    stubFetch({
      ok: true,
      disposition: "attachment; filename*=UTF-8''%E0%A4%A",
    });
    await downloadFileFromUrl(URL_OK, "local.bin", {
      preferResponseFilename: true,
    });
    expect(h.anchors[0].download).toBe("%E0%A4%A");
  });

  it("accepts a bare unquoted filename and stops at the next parameter", async () => {
    stubFetch({
      ok: true,
      disposition: "attachment; filename=plain.bin ; x=1",
    });
    await downloadFileFromUrl(URL_OK, "local.bin", {
      preferResponseFilename: true,
    });
    expect(h.anchors[0].download).toBe("plain.bin");
  });

  it("falls back to the local name when the header is absent", async () => {
    stubFetch({ ok: true, disposition: null });
    await downloadFileFromUrl(URL_OK, "local.bin", {
      preferResponseFilename: true,
    });
    expect(h.anchors[0].download).toBe("local.bin");
  });

  it("sanitises a server supplied filename before using it", async () => {
    stubFetch({
      ok: true,
      disposition: 'attachment; filename="../evil<name>.bin"',
    });
    await downloadFileFromUrl(URL_OK, "local.bin", {
      preferResponseFilename: true,
    });
    expect(h.anchors[0].download).toBe(".._evil_name_.bin");
  });

  it("falls back to the local name when the header carries no filename at all", async () => {
    // A bare `attachment` disposition matches none of the three filename
    // patterns, so the bareMatch arm reaches its nullish default and the empty
    // result hands the decision back to the suggested filename.
    stubFetch({ ok: true, disposition: "attachment" });
    await downloadFileFromUrl(URL_OK, "local.bin", {
      preferResponseFilename: true,
    });
    expect(h.anchors[0].download).toBe("local.bin");
  });

  it("falls back to the local name when the server name sanitises away", async () => {
    // <> becomes two underscores, which is a non empty name, so the product
    // keeps it instead of falling back. Pinning that exact boundary.
    stubFetch({ ok: true, disposition: 'attachment; filename="<>"' });
    await downloadFileFromUrl(URL_OK, "local.bin", {
      preferResponseFilename: true,
    });
    expect(h.anchors[0].download).toBe("__");
  });
});

describe("downloadFileFromUrl - error identity", () => {
  it("exposes a DownloadCancelledError named for the cancel contract", () => {
    const error = new DownloadCancelledError();
    expect(error).toBeInstanceOf(Error);
    expect(error.name).toBe("DownloadCancelledError");
    expect(error.message).toBe("Download cancelled");
  });

  it("does not report a browser failure as a cancellation", async () => {
    stubFetch({ ok: false, status: 500 });
    await expect(
      downloadFileFromUrl(URL_OK, "report.bin"),
    ).rejects.not.toBeInstanceOf(DownloadCancelledError);
  });
});
