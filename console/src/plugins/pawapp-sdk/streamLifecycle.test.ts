import { afterEach, describe, expect, it, vi } from "vitest";

import { hostFetch } from "../hostSdk/fetch";
import { forApp } from "./index";

vi.mock("../hostSdk/fetch", () => ({
  hostFetch: vi.fn(),
}));

const mockedFetch = vi.mocked(hostFetch);
const encoder = new TextEncoder();

function taskCreatedResponse() {
  return new Response(JSON.stringify({ task_id: "task-1" }), {
    headers: { "content-type": "application/json" },
  });
}

function streamResponse(reader: {
  read: () => Promise<ReadableStreamReadResult<Uint8Array>>;
  cancel: () => Promise<void>;
  releaseLock: () => void;
}) {
  return {
    ok: true,
    status: 200,
    statusText: "OK",
    body: { getReader: () => reader },
  } as unknown as Response;
}

async function settleWithin<T>(promise: Promise<T>): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([
      promise,
      new Promise<never>((_, reject) => {
        timer = setTimeout(
          () => reject(new Error("result did not settle")),
          100,
        );
      }),
    ]);
  } finally {
    if (timer !== undefined) clearTimeout(timer);
  }
}

function failedResponse(status: number, cancel: () => Promise<void>) {
  return {
    ok: false,
    status,
    statusText: "Failed",
    body: { cancel },
  } as unknown as Response;
}

afterEach(() => {
  mockedFetch.mockReset();
});

describe("PawApp SDK stream lifecycle", () => {
  it("cancels and releases an SSE reader once when the caller aborts", async () => {
    const reader = {
      read: vi.fn(
        () =>
          new Promise<ReadableStreamReadResult<Uint8Array>>(() => undefined),
      ),
      cancel: vi.fn(() => new Promise<void>(() => undefined)),
      releaseLock: vi.fn(),
    };
    mockedFetch.mockResolvedValue({
      ok: true,
      status: 200,
      statusText: "OK",
      body: { getReader: () => reader },
    } as unknown as Response);

    const controller = new AbortController();
    const iterator = forApp("analysis-app").api.events("/events", {
      method: "GET",
      signal: controller.signal,
    });
    const completed = iterator.next();
    await vi.waitFor(() => expect(reader.read).toHaveBeenCalledOnce());

    controller.abort();

    await expect(completed).resolves.toEqual({ done: true, value: undefined });
    expect(reader.cancel).toHaveBeenCalledOnce();
    expect(reader.releaseLock).not.toHaveBeenCalled();
  });

  it("contains rejected SSE cleanup and releases the reader lock", async () => {
    const reader = {
      read: vi.fn(
        () =>
          new Promise<ReadableStreamReadResult<Uint8Array>>(() => undefined),
      ),
      cancel: vi.fn().mockRejectedValue(new Error("cleanup failed")),
      releaseLock: vi.fn(),
    };
    mockedFetch.mockResolvedValue(streamResponse(reader));
    const controller = new AbortController();
    const completed = forApp("analysis-app")
      .api.events("/events", { method: "GET", signal: controller.signal })
      .next();
    await vi.waitFor(() => expect(reader.read).toHaveBeenCalledOnce());

    controller.abort();

    await expect(completed).resolves.toEqual({ done: true, value: undefined });
    await vi.waitFor(() => expect(reader.releaseLock).toHaveBeenCalledOnce());
    expect(reader.cancel).toHaveBeenCalledOnce();
  });

  it.each([
    {
      name: "done",
      event: 'data: {"type":"done","data":{"ok":true}}\n',
      assertion: "resolve" as const,
    },
    {
      name: "error",
      event: 'data: {"type":"error","message":"failed"}\n',
      assertion: "reject" as const,
    },
  ])("finalizes a task once on $name", async ({ event, assertion }) => {
    const reader = {
      read: vi.fn().mockResolvedValueOnce({
        done: false,
        value: encoder.encode(event),
      }),
      cancel: vi.fn().mockResolvedValue(undefined),
      releaseLock: vi.fn(),
    };
    mockedFetch
      .mockResolvedValueOnce(taskCreatedResponse())
      .mockResolvedValueOnce(streamResponse(reader));
    const onDone = vi.fn();
    const onError = vi.fn();
    const task = forApp("analysis-app")
      .api.task("/jobs", {})
      .on("done", onDone)
      .on("error", onError);

    if (assertion === "resolve") {
      await expect(task.result).resolves.toEqual({ ok: true });
      expect(onDone).toHaveBeenCalledOnce();
      expect(onError).not.toHaveBeenCalled();
    } else {
      await expect(task.result).rejects.toThrow("failed");
      expect(onError).toHaveBeenCalledOnce();
      expect(onDone).not.toHaveBeenCalled();
    }

    task.cancel();
    await vi.waitFor(() => expect(reader.cancel).toHaveBeenCalledOnce());
    expect(reader.releaseLock).toHaveBeenCalledOnce();
  });

  it("settles cancellation immediately and finalizes its reader once", async () => {
    let finishRead: (() => void) | undefined;
    const reader = {
      read: vi.fn(
        () =>
          new Promise<ReadableStreamReadResult<Uint8Array>>((resolve) => {
            finishRead = () => resolve({ done: true, value: undefined });
          }),
      ),
      cancel: vi.fn(async () => {
        finishRead?.();
      }),
      releaseLock: vi.fn(),
    };
    mockedFetch
      .mockResolvedValueOnce(taskCreatedResponse())
      .mockResolvedValueOnce(streamResponse(reader));
    const task = forApp("analysis-app").api.task("/jobs", {});
    await vi.waitFor(() => expect(reader.read).toHaveBeenCalledOnce());

    task.cancel();

    await expect(task.result).rejects.toThrow("Task cancelled");
    await vi.waitFor(() => expect(reader.cancel).toHaveBeenCalledOnce());
    expect(reader.releaseLock).toHaveBeenCalledOnce();
    task.cancel();
    expect(reader.cancel).toHaveBeenCalledOnce();
  });

  it("does not delay a terminal result while reader cleanup is pending", async () => {
    const reader = {
      read: vi.fn().mockResolvedValueOnce({
        done: false,
        value: encoder.encode('data: {"type":"done","data":{"ok":true}}\n'),
      }),
      cancel: vi.fn(() => new Promise<void>(() => undefined)),
      releaseLock: vi.fn(),
    };
    mockedFetch
      .mockResolvedValueOnce(taskCreatedResponse())
      .mockResolvedValueOnce(streamResponse(reader));

    const task = forApp("analysis-app").api.task("/jobs", {});

    await expect(task.result).resolves.toEqual({ ok: true });
    expect(reader.cancel).toHaveBeenCalledOnce();
  });

  it.each(["create", "stream"])(
    "does not delay a %s failure while response cleanup is pending",
    async (stage) => {
      const cancel = vi.fn(() => new Promise<void>(() => undefined));
      if (stage === "create") {
        mockedFetch.mockResolvedValueOnce(failedResponse(500, cancel));
      } else {
        mockedFetch
          .mockResolvedValueOnce(taskCreatedResponse())
          .mockResolvedValueOnce(failedResponse(502, cancel));
      }

      const result = forApp("analysis-app").api.task("/jobs", {}).result;

      await expect(settleWithin(result)).rejects.toThrow(
        stage === "create" ? "Task creation failed" : "SSE connection failed",
      );
      expect(cancel).toHaveBeenCalledOnce();
    },
  );

  it.each(["create", "stream"])(
    "settles cancellation while the %s request is pending",
    async (stage) => {
      const pending = new Promise<Response>(() => undefined);
      if (stage === "create") {
        mockedFetch.mockReturnValueOnce(pending);
      } else {
        mockedFetch
          .mockResolvedValueOnce(taskCreatedResponse())
          .mockReturnValueOnce(pending);
      }
      const task = forApp("analysis-app").api.task("/jobs", {});
      await vi.waitFor(() =>
        expect(mockedFetch).toHaveBeenCalledTimes(stage === "create" ? 1 : 2),
      );

      task.cancel();

      await expect(settleWithin(task.result)).rejects.toThrow("Task cancelled");
    },
  );

  it("does not dispatch later events from a batch after cancellation", async () => {
    const reader = {
      read: vi.fn().mockResolvedValueOnce({
        done: false,
        value: encoder.encode(
          'data: {"type":"progress","data":{"step":1}}\n' +
            'data: {"type":"progress","data":{"step":2}}\n',
        ),
      }),
      cancel: vi.fn().mockResolvedValue(undefined),
      releaseLock: vi.fn(),
    };
    mockedFetch
      .mockResolvedValueOnce(taskCreatedResponse())
      .mockResolvedValueOnce(streamResponse(reader));
    const onProgress = vi.fn();
    const task = forApp("analysis-app").api.task("/jobs", {});
    task.on("progress", (data) => {
      onProgress(data);
      task.cancel();
    });

    await expect(task.result).rejects.toThrow("Task cancelled");
    expect(onProgress).toHaveBeenCalledOnce();
    expect(onProgress).toHaveBeenCalledWith({ step: 1 });
  });
});
