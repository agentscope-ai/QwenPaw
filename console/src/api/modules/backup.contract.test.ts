/**
 * Contract tests for api/modules/backup.ts - the surface that the existing
 * `backup.test.ts` deliberately leaves out.
 *
 * That file states up front that it tests behaviour rather than transport, and
 * that "thin wrappers that simply forward to request() ... are not tested here".
 * This file is the complement: it pins the endpoint/verb/body contract of those
 * wrappers (so a rename or a dropped `method: "POST"` cannot slip through
 * unnoticed) and covers `streamBackupJob`, which the existing file does not
 * exercise at all.
 *
 * It also covers the three `text().catch(() => "")` fallbacks. Note that the
 * arrow body is only reached when `text()` itself rejects - a Response whose
 * `text()` resolves to an empty string takes the `text ||` arm instead, so both
 * shapes are asserted separately below.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

const mocks = vi.hoisted(() => ({
  request: vi.fn(),
  getApiUrl: vi.fn((p: string) => `http://test${p}`),
  buildAuthHeaders: vi.fn(() => ({ Authorization: "Bearer tok" })),
  downloadFileFromUrl: vi.fn(),
}));

vi.mock("../request", () => ({ request: mocks.request }));
vi.mock("../config", () => ({ getApiUrl: mocks.getApiUrl }));
vi.mock("../authHeaders", () => ({ buildAuthHeaders: mocks.buildAuthHeaders }));
vi.mock("../../utils/downloadFileFromUrl", () => {
  class DownloadCancelledError extends Error {
    constructor() {
      super("Download cancelled");
      this.name = "DownloadCancelledError";
    }
  }
  return {
    DownloadCancelledError,
    downloadFileFromUrl: mocks.downloadFileFromUrl,
  };
});

import { backupApi, RESTORE_BACKUP_TIMEOUT_MS } from "./backup";
import { downloadFileFromUrl } from "../../utils/downloadFileFromUrl";

/** Build a Response double from the pieces the module actually reads. */
function res(opts: {
  ok?: boolean;
  status?: number;
  json?: unknown;
  text?: string;
  body?: ReadableStream<Uint8Array> | null;
}): Response {
  const status = opts.status ?? 200;
  return {
    ok: opts.ok ?? (status >= 200 && status < 300),
    status,
    json: async () => opts.json,
    text: async () => opts.text ?? "",
    body: opts.body === undefined ? undefined : opts.body,
  } as unknown as Response;
}

/** A Response whose text() rejects - the only way to reach `catch(() => "")`. */
function resTextRejects(status: number): Response {
  return {
    ok: false,
    status,
    text: async () => {
      throw new TypeError("body stream already read");
    },
  } as unknown as Response;
}

function sse(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const c of chunks) controller.enqueue(encoder.encode(c));
      controller.close();
    },
  });
}

interface FetchInit {
  method?: string;
  headers?: Record<string, string>;
  body?: FormData | string;
  signal?: AbortSignal;
}

function lastInit(): FetchInit {
  const calls = (global.fetch as unknown as { mock: { calls: unknown[][] } })
    .mock.calls;
  return (calls[calls.length - 1][1] ?? {}) as FetchInit;
}

/**
 * Run a promise expected to reject and hand back the thrown value typed.
 * Using a helper (rather than `.catch((e) => e as T)`) keeps the assertion
 * honest: if the call unexpectedly resolves, this throws instead of letting a
 * non-error value flow into the expectations below.
 */
async function mustReject<T>(run: () => Promise<unknown>): Promise<T> {
  try {
    await run();
  } catch (e) {
    return e as T;
  }
  throw new Error("expected the call to reject, but it resolved");
}

const createReq = {
  name: "nightly",
  scope: {
    include_agents: true,
    include_global_config: false,
    include_secrets: false,
    include_skill_pool: false,
  },
  agents: ["a1"],
};

beforeEach(() => {
  mocks.request.mockReset();
  mocks.request.mockResolvedValue(undefined);
  mocks.getApiUrl.mockClear();
  mocks.buildAuthHeaders.mockClear();
  mocks.downloadFileFromUrl.mockReset();
  mocks.downloadFileFromUrl.mockResolvedValue(undefined);
});

afterEach(() => {
  vi.clearAllMocks();
  vi.restoreAllMocks();
});

describe("backupApi read endpoints", () => {
  it("lists backups from the collection endpoint", async () => {
    const list = [{ id: "b1", name: "n1" }];
    mocks.request.mockResolvedValue(list);

    await expect(backupApi.listBackups()).resolves.toEqual(list);
    expect(mocks.request).toHaveBeenCalledWith("/backups");
  });

  it("returns an empty backup list unchanged", async () => {
    mocks.request.mockResolvedValue([]);

    await expect(backupApi.listBackups()).resolves.toEqual([]);
  });

  it("reads a single backup by id", async () => {
    const detail = { id: "b7", name: "n7", agents: [] };
    mocks.request.mockResolvedValue(detail);

    await expect(backupApi.getBackup("b7")).resolves.toEqual(detail);
    expect(mocks.request).toHaveBeenCalledWith("/backups/b7");
  });

  it("does not URL-encode the backup id in the detail path", async () => {
    await backupApi.getBackup("a/b");

    expect(mocks.request).toHaveBeenCalledWith("/backups/a/b");
  });
});

describe("backupApi job endpoints", () => {
  it("starts a job with the create payload serialised as the body", async () => {
    const snapshot = { job_id: "j1", state: "running" };
    mocks.request.mockResolvedValue(snapshot);

    await expect(backupApi.startBackupJob(createReq as never)).resolves.toEqual(
      snapshot,
    );
    expect(mocks.request).toHaveBeenCalledWith("/backups/jobs", {
      method: "POST",
      body: JSON.stringify(createReq),
    });
  });

  it("reads the active job from a fixed path", async () => {
    mocks.request.mockResolvedValue({ job_id: "j2", state: "running" });

    await backupApi.getActiveBackupJob();

    expect(mocks.request).toHaveBeenCalledWith("/backups/jobs/active");
  });

  it("reports null when there is no active job", async () => {
    mocks.request.mockResolvedValue(null);

    await expect(backupApi.getActiveBackupJob()).resolves.toBeNull();
  });

  it("reads a specific job by id", async () => {
    mocks.request.mockResolvedValue({ job_id: "j3", state: "done" });

    await backupApi.getBackupJob("j3");

    expect(mocks.request).toHaveBeenCalledWith("/backups/jobs/j3");
  });

  it("cancels a job with POST and no body", async () => {
    mocks.request.mockResolvedValue({ job_id: "j4", state: "cancelled" });

    await expect(backupApi.cancelBackupJob("j4")).resolves.toEqual({
      job_id: "j4",
      state: "cancelled",
    });
    expect(mocks.request).toHaveBeenCalledWith("/backups/jobs/j4/cancel", {
      method: "POST",
    });
  });

  it("posts an id list to the bulk delete endpoint", async () => {
    mocks.request.mockResolvedValue({ deleted: 2 });

    await expect(backupApi.deleteBackups(["b1", "b2"])).resolves.toEqual({
      deleted: 2,
    });
    expect(mocks.request).toHaveBeenCalledWith("/backups/delete", {
      method: "POST",
      body: JSON.stringify({ ids: ["b1", "b2"] }),
    });
  });

  it("sends an empty id list rather than omitting the field", async () => {
    await backupApi.deleteBackups([]);

    expect(mocks.request).toHaveBeenCalledWith("/backups/delete", {
      method: "POST",
      body: JSON.stringify({ ids: [] }),
    });
  });
});

describe("backupApi.streamBackupJob", () => {
  it("calls onSnapshot for each SSE frame and resolves when the stream ends", async () => {
    const s1 = { job_id: "j1", state: "running", percent: 10 };
    const s2 = { job_id: "j1", state: "done", percent: 100 };
    global.fetch = vi.fn().mockResolvedValue(
      res({
        body: sse([
          `data: ${JSON.stringify(s1)}\n\n`,
          `data: ${JSON.stringify(s2)}\n\n`,
        ]),
      }),
    );

    const onSnapshot = vi.fn();
    await expect(
      backupApi.streamBackupJob("j1", onSnapshot),
    ).resolves.toBeUndefined();

    expect(onSnapshot).toHaveBeenCalledTimes(2);
    expect(onSnapshot).toHaveBeenNthCalledWith(1, s1);
    expect(onSnapshot).toHaveBeenNthCalledWith(2, s2);
  });

  it("requests the per-job event stream with auth headers", async () => {
    global.fetch = vi.fn().mockResolvedValue(res({ body: sse([]) }));

    await backupApi.streamBackupJob("j9", () => {});

    expect(mocks.getApiUrl).toHaveBeenCalledWith("/backups/jobs/j9/events");
    const init = lastInit();
    expect(init.headers).toEqual({ Authorization: "Bearer tok" });
    expect(init.method).toBeUndefined();
  });

  it("forwards the caller abort signal", async () => {
    global.fetch = vi.fn().mockResolvedValue(res({ body: sse([]) }));
    const controller = new AbortController();

    await backupApi.streamBackupJob("j1", () => {}, controller.signal);

    expect(lastInit().signal).toBe(controller.signal);
  });

  it("reassembles a frame split across two network chunks", async () => {
    const snapshot = { job_id: "j1", state: "running", percent: 42 };
    const encoded = `data: ${JSON.stringify(snapshot)}\n\n`;
    const splitAt = 12;
    const enc = new TextEncoder();
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(enc.encode(encoded.slice(0, splitAt)));
        controller.enqueue(enc.encode(encoded.slice(splitAt)));
        controller.close();
      },
    });
    global.fetch = vi.fn().mockResolvedValue(res({ body: stream }));

    const onSnapshot = vi.fn();
    await backupApi.streamBackupJob("j1", onSnapshot);

    expect(onSnapshot).toHaveBeenCalledTimes(1);
    expect(onSnapshot).toHaveBeenCalledWith(snapshot);
  });

  it("ignores SSE frames without the data prefix", async () => {
    const snapshot = { job_id: "j1", state: "done" };
    global.fetch = vi.fn().mockResolvedValue(
      res({
        body: sse([
          ": keep-alive comment\n\n",
          "event: ping\n\n",
          `data: ${JSON.stringify(snapshot)}\n\n`,
        ]),
      }),
    );

    const onSnapshot = vi.fn();
    await backupApi.streamBackupJob("j1", onSnapshot);

    expect(onSnapshot).toHaveBeenCalledTimes(1);
    expect(onSnapshot).toHaveBeenCalledWith(snapshot);
  });

  it("resolves without any callback when the stream is immediately empty", async () => {
    global.fetch = vi.fn().mockResolvedValue(res({ body: sse([]) }));

    const onSnapshot = vi.fn();
    await expect(
      backupApi.streamBackupJob("j1", onSnapshot),
    ).resolves.toBeUndefined();
    expect(onSnapshot).not.toHaveBeenCalled();
  });

  it("throws the response text when the stream request fails", async () => {
    global.fetch = vi
      .fn()
      .mockResolvedValue(
        res({ ok: false, status: 404, text: "job not found" }),
      );

    await expect(backupApi.streamBackupJob("j1", () => {})).rejects.toThrow(
      "job not found",
    );
  });

  it("throws a status-bearing message when a failed stream has an empty body", async () => {
    global.fetch = vi
      .fn()
      .mockResolvedValue(res({ ok: false, status: 500, text: "" }));

    await expect(backupApi.streamBackupJob("j1", () => {})).rejects.toThrow(
      "Request failed: 500",
    );
  });

  it("throws a status-bearing message when reading the failed body itself fails", async () => {
    global.fetch = vi.fn().mockResolvedValue(resTextRejects(502));

    await expect(backupApi.streamBackupJob("j1", () => {})).rejects.toThrow(
      "Request failed: 502",
    );
  });

  it("throws when the server answered ok but sent no body at all", async () => {
    global.fetch = vi
      .fn()
      .mockResolvedValue(res({ ok: true, status: 200, body: null }));

    await expect(backupApi.streamBackupJob("j1", () => {})).rejects.toThrow(
      "No backup event stream received",
    );
  });
});

describe("backupApi.createBackupStream failure fallbacks", () => {
  it("throws the response text when the create request fails", async () => {
    global.fetch = vi
      .fn()
      .mockResolvedValue(
        res({ ok: false, status: 422, text: "invalid scope" }),
      );

    await expect(
      backupApi.createBackupStream(createReq as never, () => {}),
    ).rejects.toThrow("invalid scope");
  });

  it("throws a status-bearing message when the failed create body is empty", async () => {
    global.fetch = vi
      .fn()
      .mockResolvedValue(res({ ok: false, status: 500, text: "" }));

    await expect(
      backupApi.createBackupStream(createReq as never, () => {}),
    ).rejects.toThrow("Request failed: 500");
  });

  it("throws a status-bearing message when reading the failed create body fails", async () => {
    global.fetch = vi.fn().mockResolvedValue(resTextRejects(503));

    await expect(
      backupApi.createBackupStream(createReq as never, () => {}),
    ).rejects.toThrow("Request failed: 503");
  });

  it("sends the create payload with an explicit JSON content type", async () => {
    global.fetch = vi.fn().mockResolvedValue(
      res({
        body: sse([
          `data: ${JSON.stringify({ type: "done", meta: { id: "b1" } })}\n\n`,
        ]),
      }),
    );

    await backupApi.createBackupStream(createReq as never, () => {});

    const init = lastInit();
    expect(init.method).toBe("POST");
    expect((init.headers as Record<string, string>)["Content-Type"]).toBe(
      "application/json",
    );
    expect(JSON.parse(String(init.body))).toEqual(createReq);
  });
});

describe("backupApi.importBackup multipart contract", () => {
  it("sends the file under the expected field name when no trust mode is given", async () => {
    global.fetch = vi.fn().mockResolvedValue(res({ json: { id: "b1" } }));
    const file = new File(["z"], "backup 归档.zip");

    await backupApi.importBackup(file);

    const init = lastInit();
    expect(init.method).toBe("POST");
    expect(init.body).toBeInstanceOf(FormData);
    const sent = (init.body as FormData).get("file") as File;
    expect(sent.name).toBe("backup 归档.zip");
    expect((init.body as FormData).has("trust_mode")).toBe(false);
  });

  it("adds the trust_mode field when the caller chooses a trust mode", async () => {
    global.fetch = vi.fn().mockResolvedValue(res({ json: { id: "b2" } }));

    await backupApi.importBackup(new File(["z"], "b.zip"), {
      trustMode: "overwrite" as never,
    });

    expect((lastInit().body as FormData).get("trust_mode")).toBe("overwrite");
  });

  it("omits trust_mode when the caller passes an empty string", async () => {
    global.fetch = vi.fn().mockResolvedValue(res({ json: { id: "b3" } }));

    await backupApi.importBackup(new File(["z"], "b.zip"), {
      trustMode: "" as never,
    });

    expect((lastInit().body as FormData).has("trust_mode")).toBe(false);
  });

  it("posts to the import endpoint", async () => {
    global.fetch = vi.fn().mockResolvedValue(res({ json: { id: "b4" } }));

    await backupApi.importBackup(new File(["z"], "b.zip"));

    expect(mocks.getApiUrl).toHaveBeenCalledWith("/backups/import");
  });

  it("throws a status-bearing message when the failed import body is unreadable", async () => {
    global.fetch = vi.fn().mockResolvedValue(resTextRejects(413));

    await expect(
      backupApi.importBackup(new File(["z"], "b.zip")),
    ).rejects.toThrow("Import failed: 413");
  });

  it("throws a status-bearing message when the failed import body is empty", async () => {
    global.fetch = vi
      .fn()
      .mockResolvedValue(res({ ok: false, status: 400, text: "" }));

    await expect(
      backupApi.importBackup(new File(["z"], "b.zip")),
    ).rejects.toThrow("Import failed: 400");
  });

  it("checks the conflict status before the generic ok check", async () => {
    global.fetch = vi
      .fn()
      .mockResolvedValue(
        res({ ok: false, status: 409, json: { pending_token: "tok" } }),
      );

    const err = await mustReject<Error & { conflict?: unknown }>(() =>
      backupApi.importBackup(new File(["z"], "b.zip")),
    );

    expect(err.message).toBe("backup_conflict");
    expect(err.conflict).toEqual({ pending_token: "tok" });
  });
});

describe("backupApi.resolveImportConflict", () => {
  it("posts the pending token as a multipart field", async () => {
    global.fetch = vi.fn().mockResolvedValue(res({ json: { id: "b5" } }));

    await backupApi.resolveImportConflict("tok-xyz");

    const init = lastInit();
    expect(init.method).toBe("POST");
    expect((init.body as FormData).get("pending_token")).toBe("tok-xyz");
  });

  it("returns the parsed backup meta on success", async () => {
    const meta = { id: "b6", name: "resolved" };
    global.fetch = vi.fn().mockResolvedValue(res({ json: meta }));

    await expect(backupApi.resolveImportConflict("tok-xyz")).resolves.toEqual(
      meta,
    );
  });

  it("posts to the same import endpoint as the initial upload", async () => {
    global.fetch = vi.fn().mockResolvedValue(res({ json: { id: "b7" } }));

    await backupApi.resolveImportConflict("tok-xyz");

    expect(mocks.getApiUrl).toHaveBeenCalledWith("/backups/import");
  });

  it("throws a status-bearing message when the failed body is unreadable", async () => {
    global.fetch = vi.fn().mockResolvedValue(resTextRejects(504));

    await expect(backupApi.resolveImportConflict("tok-xyz")).rejects.toThrow(
      "Import failed: 504",
    );
  });

  it("throws a status-bearing message when the failed body is empty", async () => {
    global.fetch = vi
      .fn()
      .mockResolvedValue(res({ ok: false, status: 500, text: "" }));

    await expect(backupApi.resolveImportConflict("tok-xyz")).rejects.toThrow(
      "Import failed: 500",
    );
  });
});

describe("backupApi.exportBackup", () => {
  it("downloads a zip named after the backup and forwards the auth headers", async () => {
    await backupApi.exportBackup("b1", "nightly backup");

    expect(downloadFileFromUrl).toHaveBeenCalledWith(
      "http://test/backups/b1/export",
      "nightly backup.zip",
      {
        headers: { Authorization: "Bearer tok" },
        errorMessage: "Export failed",
      },
    );
  });

  it("resolves cleanly when a cancelled download is reported", async () => {
    const { DownloadCancelledError } = await import(
      "../../utils/downloadFileFromUrl"
    );
    mocks.downloadFileFromUrl.mockRejectedValueOnce(
      new DownloadCancelledError(),
    );

    await expect(backupApi.exportBackup("b1", "n")).resolves.toBeUndefined();
  });

  it("re-throws any other download failure", async () => {
    mocks.downloadFileFromUrl.mockRejectedValueOnce(new Error("disk gone"));

    await expect(backupApi.exportBackup("b1", "n")).rejects.toThrow(
      "disk gone",
    );
  });
});

describe("backupApi.restoreBackup timeout contract", () => {
  it("uses the exported restore timeout constant", async () => {
    await backupApi.restoreBackup("b1", { include_agents: false } as never);

    expect(mocks.request).toHaveBeenCalledWith(
      "/backups/b1/restore",
      expect.objectContaining({ timeout: RESTORE_BACKUP_TIMEOUT_MS }),
    );
  });
});
