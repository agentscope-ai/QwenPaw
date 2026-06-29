/**
 * Tests for api/modules/backup.ts
 *
 * Design principle: test **behaviour**, not transport.
 * We verify return values, error shapes, and state transitions — not the
 * exact URL, HTTP method, or request body that the implementation happens
 * to send.  This keeps the tests resilient when the API client internals
 * change (e.g. switching from `request()` to direct `fetch`, renaming query
 * params, or adjusting Content-Type headers).
 *
 * Only functions with non-trivial control-flow (SSE streaming, conflict
 * handling, cancel-suppression) get dedicated tests.  Thin wrappers that
 * simply forward to `request()` or `downloadFileFromUrl()` are not tested
 * here — their contract is already covered by the shared `request` module.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// ---------------------------------------------------------------------------
// Module stubs — keep them minimal; only provide what the code-under-test
// actually needs so we don't over-couple to irrelevant internals.
// ---------------------------------------------------------------------------
vi.mock("../request", () => ({
  request: vi.fn(),
}));
vi.mock("../config", () => ({
  getApiUrl: vi.fn((p: string) => `http://test${p}`),
}));
vi.mock("../authHeaders", () => ({
  buildAuthHeaders: vi.fn(() => ({})),
}));
vi.mock("../../utils/downloadFileFromUrl", () => {
  class DownloadCancelledError extends Error {
    constructor() {
      super("Download cancelled");
      this.name = "DownloadCancelledError";
    }
  }
  return {
    DownloadCancelledError,
    downloadFileFromUrl: vi.fn(),
  };
});

import { backupApi } from "./backup";
import {
  downloadFileFromUrl,
  DownloadCancelledError,
} from "../../utils/downloadFileFromUrl";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

interface MockResponseOptions {
  ok?: boolean;
  status: number;
  json?: unknown;
  text?: string;
  body?: ReadableStream<Uint8Array>;
}

function mockResponse({
  ok,
  status,
  json,
  text,
  body,
}: MockResponseOptions): Response {
  return {
    ok: ok ?? (status >= 200 && status < 300),
    status,
    json: async () => json,
    text: async () => text ?? "",
    body,
  } as unknown as Response;
}

/** Build a fake Response whose body yields the given SSE chunks. */
function makeSseResponse(chunks: string[]): Response {
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const c of chunks) controller.enqueue(encoder.encode(c));
      controller.close();
    },
  });
  return mockResponse({ ok: true, status: 200, body: stream });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("backupApi", () => {
  beforeEach(() => {
    vi.mocked(downloadFileFromUrl).mockReset();
    vi.mocked(downloadFileFromUrl).mockResolvedValue(undefined);
  });

  afterEach(() => {
    vi.clearAllMocks();
    vi.restoreAllMocks();
  });

  // =========================================================================
  // createBackupStream — SSE parsing + event-driven progress
  // =========================================================================
  // This is the most complex function: it manually reads an SSE stream,
  // parses `data:` lines, calls onEvent for each, and returns the `meta`
  // from the "done" event.  Several branches need guarding:
  //   - normal happy path (events → done event → return meta)
  //   - error event → throws with the event's message
  //   - stream ends without a done event → throws
  // =========================================================================

  describe("createBackupStream", () => {
    it("calls onEvent for each SSE event and returns the done-event meta", async () => {
      const agentEvent = {
        type: "agent",
        agent_id: "a1",
        index: 0,
        total: 1,
        percent: 50,
      } as const;
      const doneEvent = {
        type: "done",
        meta: { id: "b1", name: "n" },
        percent: 100,
      } as const;
      global.fetch = vi
        .fn()
        .mockResolvedValue(
          makeSseResponse([
            `data: ${JSON.stringify(agentEvent)}\n\n`,
            `data: ${JSON.stringify(doneEvent)}\n\n`,
          ]),
        );

      const onEvent = vi.fn();
      const meta = await backupApi.createBackupStream(
        {
          name: "n",
          scope: {
            include_agents: true,
            include_global_config: false,
            include_secrets: false,
            include_skill_pool: false,
          },
          agents: ["a1"],
        },
        onEvent,
      );

      // The onEvent callback must be invoked once per SSE event
      expect(onEvent).toHaveBeenCalledTimes(2);
      expect(onEvent).toHaveBeenNthCalledWith(1, agentEvent);
      expect(onEvent).toHaveBeenNthCalledWith(2, doneEvent);
      // The returned meta must come from the "done" event
      expect(meta).toEqual({ id: "b1", name: "n" });
    });

    it("throws the error-event message when the server sends an error event", async () => {
      const errorEvent = { type: "error", message: "disk full" };
      global.fetch = vi
        .fn()
        .mockResolvedValue(
          makeSseResponse([`data: ${JSON.stringify(errorEvent)}\n\n`]),
        );

      await expect(
        backupApi.createBackupStream(
          {
            name: "n",
            scope: {
              include_agents: false,
              include_global_config: false,
              include_secrets: false,
              include_skill_pool: false,
            },
            agents: [],
          },
          () => {},
        ),
      ).rejects.toThrow("disk full");
    });

    it("throws when the stream ends without ever sending a done event", async () => {
      // An agent event arrives but the server drops the connection before "done"
      const agentEvent = {
        type: "agent",
        agent_id: "a1",
        index: 0,
        total: 1,
        percent: 50,
      };
      global.fetch = vi
        .fn()
        .mockResolvedValue(
          makeSseResponse([`data: ${JSON.stringify(agentEvent)}\n\n`]),
        );

      await expect(
        backupApi.createBackupStream(
          {
            name: "n",
            scope: {
              include_agents: false,
              include_global_config: false,
              include_secrets: false,
              include_skill_pool: false,
            },
            agents: [],
          },
          () => {},
        ),
      ).rejects.toThrow("No completion event received");
    });

    it("ignores non-data SSE lines (skips chunks without 'data: ' prefix)", async () => {
      const doneEvent = {
        type: "done",
        meta: { id: "b1", name: "n" },
        percent: 100,
      };
      global.fetch = vi.fn().mockResolvedValue(
        makeSseResponse([
          `: this is a comment\n\n`, // SSE comment — should be ignored
          `event: agent\n\n`, // event field without data — ignored
          `data: ${JSON.stringify(doneEvent)}\n\n`,
        ]),
      );

      const onEvent = vi.fn();
      const meta = await backupApi.createBackupStream(
        {
          name: "n",
          scope: {
            include_agents: false,
            include_global_config: false,
            include_secrets: false,
            include_skill_pool: false,
          },
          agents: [],
        },
        onEvent,
      );

      // Only the data-prefixed line should trigger onEvent
      expect(onEvent).toHaveBeenCalledTimes(1);
      expect(meta).toEqual({ id: "b1", name: "n" });
    });
  });

  // =========================================================================
  // importBackup — conflict handling (HTTP 409)
  // =========================================================================
  // This is the one error path in the module that has **structured data**
  // attached to the thrown error.  If the 409 branch breaks, the UI cannot
  // present the conflict-resolution dialog, so this is a high-value guard.
  // =========================================================================

  describe("importBackup", () => {
    it("on HTTP 409, throws Error('backup_conflict') with .conflict carrying the server body", async () => {
      const conflictBody = {
        detail: "backup_conflict" as const,
        existing: { id: "b0", name: "old" },
        pending_token: "tok-123",
      };
      global.fetch = vi
        .fn()
        .mockResolvedValue(
          mockResponse({ ok: false, status: 409, json: conflictBody }),
        );

      try {
        await backupApi.importBackup(new File(["data"], "backup.zip"));
        expect.unreachable("should have thrown");
      } catch (e) {
        expect(e).toBeInstanceOf(Error);
        expect((e as Error).message).toBe("backup_conflict");
        // The .conflict property is what the UI reads to show the dialog
        expect((e as Error & { conflict: unknown }).conflict).toEqual(
          conflictBody,
        );
      }
    });

    it("on non-409 failure, throws an error containing the response text", async () => {
      global.fetch = vi
        .fn()
        .mockResolvedValue(
          mockResponse({ ok: false, status: 400, text: "Bad file" }),
        );

      await expect(
        backupApi.importBackup(new File(["data"], "backup.zip")),
      ).rejects.toThrow("Bad file");
    });

    it("returns parsed BackupMeta on success", async () => {
      const meta = { id: "b1", name: "n" };
      global.fetch = vi
        .fn()
        .mockResolvedValue(mockResponse({ ok: true, status: 200, json: meta }));

      const result = await backupApi.importBackup(
        new File(["data"], "backup.zip"),
      );
      expect(result).toEqual(meta);
    });
  });

  // =========================================================================
  // resolveImportConflict — error path
  // =========================================================================
  // Only the error branch needs guarding; the happy path is a thin fetch+json.

  describe("resolveImportConflict", () => {
    it("on non-ok response, throws an error containing the response text", async () => {
      global.fetch = vi
        .fn()
        .mockResolvedValue(
          mockResponse({ ok: false, status: 500, text: "server error" }),
        );

      await expect(backupApi.resolveImportConflict("tok-123")).rejects.toThrow(
        "server error",
      );
    });
  });

  // =========================================================================
  // exportBackup — cancel-suppression logic
  // =========================================================================
  // exportBackup delegates to downloadFileFromUrl, but crucially it **swallows**
  // DownloadCancelledError so the caller sees a clean void return when the user
  // cancels the save dialog.  This is a behavioural contract, not a transport
  // detail — if it regresses, the UI will show a spurious error on cancel.
  // =========================================================================

  describe("exportBackup", () => {
    it("returns undefined (does not rethrow) when download is cancelled", async () => {
      vi.mocked(downloadFileFromUrl).mockRejectedValueOnce(
        new DownloadCancelledError(),
      );

      await expect(
        backupApi.exportBackup("b1", "my-backup"),
      ).resolves.toBeUndefined();
    });

    it("re-throws non-cancelled errors so the UI can display them", async () => {
      vi.mocked(downloadFileFromUrl).mockRejectedValueOnce(
        new Error("Network failure"),
      );

      await expect(backupApi.exportBackup("b1", "n")).rejects.toThrow(
        "Network failure",
      );
    });
  });
});
