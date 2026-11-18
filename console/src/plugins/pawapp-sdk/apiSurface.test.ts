import { afterEach, describe, expect, it, vi } from "vitest";

import { hostFetch } from "../hostSdk/fetch";
import { apiNamespace, createApiNamespace, PawApiError } from "./api";
import { setActivePawAppId } from "./context";

vi.mock("../hostSdk/fetch", () => ({
  hostFetch: vi.fn(),
}));

const mockedFetch = vi.mocked(hostFetch);
const encoder = new TextEncoder();

function jsonResponse(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function textResponse(text: string, status = 200) {
  return new Response(text, { status });
}

function errorResponse(
  status: number,
  text: string,
  contentType: string | null = "application/json",
) {
  const headers = new Headers();
  if (contentType !== null) headers.set("content-type", contentType);
  return {
    ok: false,
    status,
    statusText: "StatusText",
    headers,
    text: () => Promise.resolve(text),
    json: () => Promise.reject(new Error("not json")),
  } as unknown as Response;
}

function streamResponse(chunks: string[], contentType = "text/event-stream") {
  let index = 0;
  // Mirrors real ReadableStream semantics: once cancelled, every pending and
  // later read settles as done instead of delivering buffered chunks.
  let cancelled = false;
  const reader = {
    read: vi.fn(async () => {
      if (cancelled || index >= chunks.length) {
        return { done: true, value: undefined };
      }
      const chunk = chunks[index];
      index += 1;
      return { done: false, value: encoder.encode(chunk) };
    }),
    cancel: vi.fn(() => {
      cancelled = true;
      return Promise.resolve();
    }),
    releaseLock: vi.fn(),
  };
  const headers = new Headers();
  headers.set("content-type", contentType);
  return {
    reader,
    response: {
      ok: true,
      status: 200,
      statusText: "OK",
      headers,
      body: { getReader: () => reader },
    } as unknown as Response,
  };
}

async function collect<T>(source: AsyncGenerator<T>): Promise<T[]> {
  const out: T[] = [];
  for await (const item of source) out.push(item);
  return out;
}

afterEach(() => {
  mockedFetch.mockReset();
  setActivePawAppId(null);
});

describe("PawApp api namespace download", () => {
  it("returns the response blob for a successful download", async () => {
    const api = createApiNamespace(() => "datapaw");
    mockedFetch.mockResolvedValue(
      new Response("file-bytes", { headers: { "content-type": "text/plain" } }),
    );

    const blob = await api.download("/files/report.csv");

    expect(await blob.text()).toBe("file-bytes");
    const [url, init] = mockedFetch.mock.calls[0] as unknown as [
      string,
      RequestInit,
    ];
    expect(url).toBe("/datapaw/files/report.csv");
    expect(init.method).toBe("GET");
  });

  it("appends query parameters to the download url", async () => {
    const api = createApiNamespace(() => "datapaw");
    mockedFetch.mockResolvedValue(new Response("x"));

    await api.download("/files/report.csv", {
      query: { version: 2, skip: undefined, dropped: null },
    });

    const [url] = mockedFetch.mock.calls[0] as unknown as [string];
    expect(url).toBe("/datapaw/files/report.csv?version=2");
  });

  it("raises a PawApiError when the download response is not ok", async () => {
    const api = createApiNamespace(() => "datapaw");
    mockedFetch.mockResolvedValue(
      errorResponse(404, JSON.stringify({ detail: "missing file" })),
    );

    await expect(api.download("/files/gone")).rejects.toBeInstanceOf(
      PawApiError,
    );
  });

  it("forwards the abort signal and custom headers of a download", async () => {
    const api = createApiNamespace(() => "datapaw");
    mockedFetch.mockResolvedValue(new Response("x"));
    const controller = new AbortController();

    await api.download("/files/a", {
      headers: { "X-Trace": "abc" },
      signal: controller.signal,
    });

    const [, init] = mockedFetch.mock.calls[0] as unknown as [
      string,
      RequestInit,
    ];
    expect(init.headers).toEqual({ "X-Trace": "abc" });
    expect(init.signal).toBe(controller.signal);
  });
});

describe("PawApp api response parsing", () => {
  it("returns undefined for a 204 response", async () => {
    const api = createApiNamespace(() => "datapaw");
    mockedFetch.mockResolvedValue(
      new Response(null, {
        status: 204,
        headers: { "content-type": "application/json" },
      }),
    );

    await expect(api.get("/records")).resolves.toBeUndefined();
  });

  it("returns the raw text when the content type is not json", async () => {
    const api = createApiNamespace(() => "datapaw");
    mockedFetch.mockResolvedValue(textResponse("plain-body"));

    await expect(api.get("/records")).resolves.toBe("plain-body");
  });

  it("treats a missing content type header as non-json", async () => {
    const api = createApiNamespace(() => "datapaw");
    mockedFetch.mockResolvedValue({
      ok: true,
      status: 200,
      headers: { get: () => null },
      text: () => Promise.resolve("headerless"),
    } as unknown as Response);

    await expect(api.get("/records")).resolves.toBe("headerless");
  });

  it("defaults the request method to GET when none is given", async () => {
    const api = createApiNamespace(() => "datapaw");
    mockedFetch.mockResolvedValue(jsonResponse({ ok: true }));

    await api.request("/records");

    const [, init] = mockedFetch.mock.calls[0] as unknown as [
      string,
      RequestInit,
    ];
    expect(init.method).toBe("GET");
    expect(init.body).toBeUndefined();
  });

  it("uses the structured message as the error detail", async () => {
    const api = createApiNamespace(() => "datapaw");
    mockedFetch.mockResolvedValue(
      errorResponse(
        422,
        JSON.stringify({
          detail: { code: "BAD_INPUT", message: "field wrong" },
        }),
      ),
    );

    const error = await api
      .get("/records")
      .then(() => null)
      .catch((e: PawApiError) => e);

    expect(error).toBeInstanceOf(PawApiError);
    expect(error?.message).toBe("PawApp API error 422: field wrong");
    expect(error?.code).toBe("BAD_INPUT");
    expect(error?.detail).toEqual({
      code: "BAD_INPUT",
      message: "field wrong",
    });
  });

  it("serialises a structured detail without a message field", async () => {
    const api = createApiNamespace(() => "datapaw");
    mockedFetch.mockResolvedValue(
      errorResponse(409, JSON.stringify({ detail: { field: "name" } })),
    );

    const error = await api
      .get("/records")
      .then(() => null)
      .catch((e: PawApiError) => e);

    expect(error?.message).toBe('PawApp API error 409: {"field":"name"}');
    expect(error?.code).toBeUndefined();
  });

  it("keeps a non-string code out of the error and falls back to statusText", async () => {
    const api = createApiNamespace(() => "datapaw");
    mockedFetch.mockResolvedValue(
      errorResponse(500, JSON.stringify({ detail: { code: 42, message: 7 } })),
    );

    const error = await api
      .get("/records")
      .then(() => null)
      .catch((e: PawApiError) => e);

    expect(error?.code).toBeUndefined();
    expect(error?.message).toBe(
      'PawApp API error 500: {"code":42,"message":7}',
    );
  });

  it("reads a top level message when detail is absent", async () => {
    const api = createApiNamespace(() => "datapaw");
    mockedFetch.mockResolvedValue(
      errorResponse(403, JSON.stringify({ message: "forbidden" })),
    );

    const error = await api
      .get("/records")
      .then(() => null)
      .catch((e: PawApiError) => e);

    expect(error?.message).toBe("PawApp API error 403: forbidden");
  });

  it("reads a top level string code when the payload is not an object detail", async () => {
    const api = createApiNamespace(() => "datapaw");
    mockedFetch.mockResolvedValue(
      errorResponse(
        400,
        JSON.stringify({ detail: "bad request", code: "E_BAD" }),
      ),
    );

    const error = await api
      .get("/records")
      .then(() => null)
      .catch((e: PawApiError) => e);

    expect(error?.message).toBe("PawApp API error 400: bad request");
    // The detail here is a plain string, so parseResponse takes its non-object
    // branch, which is the only place that reads the top level code field.
    expect(error?.code).toBe("E_BAD");
    expect(error?.detail).toBe("bad request");
  });

  it("serialises a non-string top level detail", async () => {
    const api = createApiNamespace(() => "datapaw");
    mockedFetch.mockResolvedValue(
      errorResponse(400, JSON.stringify({ detail: 7, code: "E_NUM" })),
    );

    const error = await api
      .get("/records")
      .then(() => null)
      .catch((e: PawApiError) => e);

    expect(error?.message).toBe("PawApp API error 400: 7");
    expect(error?.code).toBe("E_NUM");
  });

  it("preserves a non-json error body as the detail text", async () => {
    const api = createApiNamespace(() => "datapaw");
    mockedFetch.mockResolvedValue(errorResponse(502, "<html>gateway</html>"));

    const error = await api
      .get("/records")
      .then(() => null)
      .catch((e: PawApiError) => e);

    expect(error?.message).toBe("PawApp API error 502: <html>gateway</html>");
    expect(error?.detail).toBe("<html>gateway</html>");
  });

  it("falls back to statusText when the error body is empty", async () => {
    const api = createApiNamespace(() => "datapaw");
    mockedFetch.mockResolvedValue(errorResponse(503, ""));

    const error = await api
      .get("/records")
      .then(() => null)
      .catch((e: PawApiError) => e);

    expect(error?.message).toBe("PawApp API error 503: StatusText");
  });

  it("tolerates a failing text() on the error response", async () => {
    const api = createApiNamespace(() => "datapaw");
    mockedFetch.mockResolvedValue({
      ok: false,
      status: 500,
      statusText: "Boom",
      text: () => Promise.reject(new Error("body unreadable")),
    } as unknown as Response);

    const error = await api
      .get("/records")
      .then(() => null)
      .catch((e: PawApiError) => e);

    expect(error?.message).toBe("PawApp API error 500: Boom");
  });

  it("rejects a request carrying both body and rawBody", async () => {
    const api = createApiNamespace(() => "datapaw");

    await expect(
      api.request("/records", {
        method: "POST",
        body: { a: 1 },
        rawBody: "raw",
      }),
    ).rejects.toThrow("cannot set both body and rawBody");
    expect(mockedFetch).not.toHaveBeenCalled();
  });

  it("sends a native rawBody without a json content type", async () => {
    const api = createApiNamespace(() => "datapaw");
    mockedFetch.mockResolvedValue(jsonResponse({ ok: true }));

    await api.request("/upload", { method: "POST", rawBody: "text-payload" });

    const [, init] = mockedFetch.mock.calls[0] as unknown as [
      string,
      RequestInit,
    ];
    expect(init.body).toBe("text-payload");
    expect(init.headers).toEqual({});
  });

  it("omits a query string when every query value is null or undefined", async () => {
    const api = createApiNamespace(() => "datapaw");
    mockedFetch.mockResolvedValue(jsonResponse({ ok: true }));

    await api.get("/records", { query: { a: undefined, b: null } });

    const [url] = mockedFetch.mock.calls[0] as unknown as [string];
    expect(url).toBe("/datapaw/records");
  });

  it("joins an appended query with an ampersand when the path already has one", async () => {
    setActivePawAppId("legacyapp");
    mockedFetch.mockResolvedValue(jsonResponse({ ok: true }));

    await apiNamespace.get("/records?revision=4", { query: { extra: "yes" } });

    const [url] = mockedFetch.mock.calls[0] as unknown as [string];
    expect(url).toBe("/legacyapp/records?revision=4&extra=yes");
  });
});

describe("PawApp api legacy scoping", () => {
  it("prefixes a leading slash for the non-strict namespace", async () => {
    setActivePawAppId("legacyapp");
    mockedFetch.mockResolvedValue(jsonResponse({ ok: true }));

    await apiNamespace.get("records");

    const [url] = mockedFetch.mock.calls[0] as unknown as [string];
    expect(url).toBe("/legacyapp/records");
  });

  it("keeps an already rooted path untouched for the non-strict namespace", async () => {
    setActivePawAppId("legacyapp");
    mockedFetch.mockResolvedValue(jsonResponse({ ok: true }));

    await apiNamespace.get("/records");

    const [url] = mockedFetch.mock.calls[0] as unknown as [string];
    expect(url).toBe("/legacyapp/records");
  });

  it("rejects an invalid app id in the strict namespace", async () => {
    const api = createApiNamespace(() => "Bad App");
    mockedFetch.mockResolvedValue(jsonResponse({ ok: true }));

    await expect(api.get("/records")).rejects.toThrow("Invalid PawApp id");
  });

  it("builds a legacy path-derived task handle through the non-strict factory", () => {
    setActivePawAppId("legacyapp");
    // createPawTaskWithScope performs two fetches: the create POST and then the
    // SSE stream connection, so each call needs its own response object.
    mockedFetch
      .mockResolvedValueOnce(jsonResponse({ task_id: "t-1" }))
      .mockResolvedValueOnce(streamResponse([]).response);

    const handle = apiNamespace.task("/generate", { script: "x" });

    expect(typeof handle.cancel).toBe("function");
    expect(typeof handle.on).toBe("function");
    const [url] = mockedFetch.mock.calls[0] as unknown as [string];
    expect(url).toBe("/legacyapp/generate");
  });

  it("builds a scope-validated task handle through the strict factory", () => {
    const api = createApiNamespace(() => "datapaw");
    mockedFetch
      .mockResolvedValueOnce(jsonResponse({ task_id: "t-2" }))
      .mockResolvedValueOnce(streamResponse([]).response);

    const handle = api.task("/generate");

    expect(typeof handle.cancel).toBe("function");
    const [url] = mockedFetch.mock.calls[0] as unknown as [string];
    expect(url).toBe("/datapaw/generate");
  });
});

describe("PawApp api event stream parsing", () => {
  it("parses event names, ids and multiline data", async () => {
    const api = createApiNamespace(() => "datapaw");
    const { response } = streamResponse([
      "event: progress\ndata: line1\ndata: line2\nid: ev-1\n\n",
    ]);
    mockedFetch.mockResolvedValue(response);

    const events = await collect(api.events("/events", { method: "GET" }));

    expect(events).toEqual([
      { event: "progress", data: "line1\nline2", id: "ev-1" },
    ]);
  });

  it("defaults the stream method to POST and sends a json body", async () => {
    const api = createApiNamespace(() => "datapaw");
    const { response } = streamResponse(["data: done\n\n"]);
    mockedFetch.mockResolvedValue(response);

    await collect(api.events("/events", { body: { q: 1 } }));

    const [, init] = mockedFetch.mock.calls[0] as unknown as [
      string,
      RequestInit,
    ];
    expect(init.method).toBe("POST");
    expect(init.body).toBe(JSON.stringify({ q: 1 }));
    expect(init.headers).toMatchObject({
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    });
  });

  it("exposes the data-only stream view of the same events", async () => {
    const api = createApiNamespace(() => "datapaw");
    const { response } = streamResponse([
      "event: chunk\ndata: alpha\n\n",
      "data: beta\n\n",
    ]);
    mockedFetch.mockResolvedValue(response);

    const chunks = await collect(api.stream("/events", { q: 1 }));

    expect(chunks).toEqual(["alpha", "beta"]);
  });

  it("carries the retry hint and ignores comment and fieldless lines", async () => {
    const api = createApiNamespace(() => "datapaw");
    const { response } = streamResponse([
      ": keep-alive\n",
      "retry: 2500\n",
      "heartbeat\n",
      "data: payload\n\n",
    ]);
    mockedFetch.mockResolvedValue(response);

    const events = await collect(api.events("/events", { method: "GET" }));

    expect(events).toEqual([
      { event: "message", data: "payload", retry: 2500 },
    ]);
  });

  it("falls back to the message name for an empty event field", async () => {
    const api = createApiNamespace(() => "datapaw");
    const { response } = streamResponse(["event:\ndata: x\n\n"]);
    mockedFetch.mockResolvedValue(response);

    const events = await collect(api.events("/events", { method: "GET" }));

    expect(events).toEqual([{ event: "message", data: "x" }]);
  });

  it("ignores an id field containing a null byte and a non numeric retry", async () => {
    const api = createApiNamespace(() => "datapaw");
    const { response } = streamResponse([
      "id: bad\u0000id\nretry: soon\nretry:\ndata: y\n\n",
    ]);
    mockedFetch.mockResolvedValue(response);

    const events = await collect(api.events("/events", { method: "GET" }));

    expect(events).toEqual([{ event: "message", data: "y" }]);
  });

  it("resets event metadata after a flush that carried no data", async () => {
    const api = createApiNamespace(() => "datapaw");
    const { response } = streamResponse([
      "event: first\nid: 9\nretry: 100\n\n",
      "data: after\n\n",
    ]);
    mockedFetch.mockResolvedValue(response);

    const events = await collect(api.events("/events", { method: "GET" }));

    expect(events).toEqual([{ event: "message", data: "after" }]);
  });

  it("strips a single leading space from a field value", async () => {
    const api = createApiNamespace(() => "datapaw");
    const { response } = streamResponse(["data:  padded\n\n"]);
    mockedFetch.mockResolvedValue(response);

    const events = await collect(api.events("/events", { method: "GET" }));

    expect(events).toEqual([{ event: "message", data: " padded" }]);
  });

  it("strips carriage returns from CRLF framed events", async () => {
    const api = createApiNamespace(() => "datapaw");
    const { response } = streamResponse(["event: tick\r\ndata: crlf\r\n\r\n"]);
    mockedFetch.mockResolvedValue(response);

    const events = await collect(api.events("/events", { method: "GET" }));

    expect(events).toEqual([{ event: "tick", data: "crlf" }]);
  });

  it("reassembles an event split across two chunks", async () => {
    const api = createApiNamespace(() => "datapaw");
    const { response } = streamResponse([
      "data: part",
      "-one\n\ndata: two\n\n",
    ]);
    mockedFetch.mockResolvedValue(response);

    const events = await collect(api.events("/events", { method: "GET" }));

    expect(events).toEqual([
      { event: "message", data: "part-one" },
      { event: "message", data: "two" },
    ]);
  });

  it("flushes a trailing event that never received a blank line", async () => {
    const api = createApiNamespace(() => "datapaw");
    const { response } = streamResponse(["event: tail\ndata: unterminated\n"]);
    mockedFetch.mockResolvedValue(response);

    const events = await collect(api.events("/events", { method: "GET" }));

    expect(events).toEqual([{ event: "tail", data: "unterminated" }]);
  });

  it("releases the reader lock once the stream completes", async () => {
    const api = createApiNamespace(() => "datapaw");
    const { response, reader } = streamResponse(["data: a\n\n"]);
    mockedFetch.mockResolvedValue(response);

    await collect(api.events("/events", { method: "GET" }));

    expect(reader.cancel).toHaveBeenCalledOnce();
    expect(reader.releaseLock).toHaveBeenCalledOnce();
  });

  it("removes the abort listener after the generator finishes", async () => {
    const api = createApiNamespace(() => "datapaw");
    const { response } = streamResponse(["data: a\n\n"]);
    mockedFetch.mockResolvedValue(response);
    const controller = new AbortController();
    const removeSpy = vi.spyOn(controller.signal, "removeEventListener");

    await collect(
      api.events("/events", { method: "GET", signal: controller.signal }),
    );

    expect(removeSpy).toHaveBeenCalledWith("abort", expect.any(Function));
    removeSpy.mockRestore();
  });

  it("rejects a GET event stream that carries a body", async () => {
    const api = createApiNamespace(() => "datapaw");
    const iterator = api.events("/events", { method: "GET", body: { q: 1 } });

    await expect(collect(iterator)).rejects.toThrow(
      "GET SSE request cannot include a body",
    );
    expect(mockedFetch).not.toHaveBeenCalled();
  });

  it("rejects a GET event stream that carries a rawBody", async () => {
    const api = createApiNamespace(() => "datapaw");
    const iterator = api.events("/events", {
      method: "GET",
      rawBody: "raw",
    });

    await expect(collect(iterator)).rejects.toThrow(
      "GET SSE request cannot include a body",
    );
  });

  it("rejects an event stream that carries both body and rawBody", async () => {
    const api = createApiNamespace(() => "datapaw");
    const iterator = api.events("/events", {
      body: { q: 1 },
      rawBody: "raw",
    });

    await expect(collect(iterator)).rejects.toThrow(
      "cannot set both body and rawBody",
    );
  });

  it("treats an explicitly null rawBody as absent", async () => {
    const api = createApiNamespace(() => "datapaw");
    const { response } = streamResponse(["data: a\n\n"]);
    mockedFetch.mockResolvedValue(response);

    await collect(api.events("/events", { method: "GET", rawBody: null }));

    const [, init] = mockedFetch.mock.calls[0] as unknown as [
      string,
      RequestInit,
    ];
    expect(init.body).toBeUndefined();
  });

  it("sends a raw event body without json encoding it", async () => {
    const api = createApiNamespace(() => "datapaw");
    const { response } = streamResponse(["data: a\n\n"]);
    mockedFetch.mockResolvedValue(response);

    await collect(api.events("/events", { rawBody: "native-payload" }));

    const [, init] = mockedFetch.mock.calls[0] as unknown as [
      string,
      RequestInit,
    ];
    expect(init.body).toBe("native-payload");
    expect(init.headers).not.toHaveProperty("Content-Type");
  });

  it("surfaces a PawApiError for a failed event stream response", async () => {
    const api = createApiNamespace(() => "datapaw");
    mockedFetch.mockResolvedValue(
      errorResponse(401, JSON.stringify({ detail: "unauthorised" })),
    );

    await expect(
      collect(api.events("/events", { method: "GET" })),
    ).rejects.toThrow("PawApp API error 401: unauthorised");
  });

  it("fails when the event response carries no readable body", async () => {
    const api = createApiNamespace(() => "datapaw");
    mockedFetch.mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers(),
      body: undefined,
    } as unknown as Response);

    await expect(
      collect(api.events("/events", { method: "GET" })),
    ).rejects.toThrow("No response body for stream");
  });

  it("stops immediately when the signal is already aborted", async () => {
    const api = createApiNamespace(() => "datapaw");
    const { response, reader } = streamResponse(["data: never\n\n"]);
    mockedFetch.mockResolvedValue(response);
    const controller = new AbortController();
    controller.abort();

    const events = await collect(
      api.events("/events", { method: "GET", signal: controller.signal }),
    );

    expect(events).toEqual([]);
    expect(reader.cancel).toHaveBeenCalledOnce();
  });
});
