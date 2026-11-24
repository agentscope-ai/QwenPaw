/**
 * Contract tests for api/modules/agent.ts - the transcription surface and the
 * read-only workspace endpoints that `agent.test.ts` does not exercise.
 *
 * Scope:
 *   - `TranscriptionError` shape (name / status / code / composed message)
 *   - `transcribeAudio` error mapping: object detail (with and without its own
 *     message), string detail, non-JSON body, missing detail, and the success arm
 *   - FormData multipart contract (the field name the backend expects)
 *   - the GET wrappers for language / audio mode / transcription provider type /
 *     providers / memory backends / shutdownSimple
 *
 * Assertions target the request contract and the error surface shown to users,
 * not transport internals.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

const mocks = vi.hoisted(() => ({
  request: vi.fn(),
  getApiUrl: vi.fn((p: string) => `/api${p}`),
  buildAuthHeaders: vi.fn(() => ({ Authorization: "Bearer tok" })),
}));

vi.mock("../request", () => ({ request: mocks.request }));
vi.mock("../config", () => ({ getApiUrl: mocks.getApiUrl }));
vi.mock("../authHeaders", () => ({ buildAuthHeaders: mocks.buildAuthHeaders }));

import { agentApi, TranscriptionError } from "./agent";

/** Minimal Response double: only the fields the module reads. */
function stubResponse(opts: {
  ok?: boolean;
  status?: number;
  statusText?: string;
  json?: unknown;
}): Response {
  const status = opts.status ?? 200;
  return {
    ok: opts.ok ?? (status >= 200 && status < 300),
    status,
    statusText: opts.statusText ?? "",
    json: async () => opts.json,
  } as unknown as Response;
}

/** A Response whose body cannot be parsed as JSON at all. */
function nonJsonResponse(status: number, statusText: string): Response {
  return {
    ok: false,
    status,
    statusText,
    json: async () => {
      throw new SyntaxError("Unexpected token < in JSON at position 0");
    },
  } as unknown as Response;
}

interface FetchInit {
  method?: string;
  headers?: Record<string, string>;
  body?: FormData;
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

const audio = new File(["\u0000audio"], "voice.webm", { type: "audio/webm" });

beforeEach(() => {
  mocks.request.mockReset();
  mocks.request.mockResolvedValue(undefined);
  mocks.getApiUrl.mockClear();
  mocks.buildAuthHeaders.mockClear();
});

afterEach(() => {
  vi.clearAllMocks();
  vi.restoreAllMocks();
});

describe("TranscriptionError", () => {
  it("composes its message from the HTTP status and the server text", () => {
    const err = new TranscriptionError(413, "Payload Too Large");

    expect(err).toBeInstanceOf(Error);
    expect(err.message).toBe("Transcription failed: 413 Payload Too Large");
  });

  it("is identifiable by name so callers can branch on it", () => {
    expect(new TranscriptionError(500, "boom").name).toBe("TranscriptionError");
  });

  it("carries the status for UI-level branching", () => {
    expect(new TranscriptionError(415, "Unsupported").status).toBe(415);
  });

  it("leaves the machine code undefined when the server sent none", () => {
    expect(new TranscriptionError(500, "boom").code).toBeUndefined();
  });

  it("keeps the machine code when the server classified the failure", () => {
    const err = new TranscriptionError(400, "nope", "TRANSCRIPTION_DISABLED");

    expect(err.code).toBe("TRANSCRIPTION_DISABLED");
    expect(err.status).toBe(400);
  });

  it("accepts every documented code value", () => {
    const codes = [
      "TRANSCRIPTION_DISABLED",
      "FILE_TOO_LARGE",
      "UNSUPPORTED_FILE_TYPE",
    ] as const;

    for (const code of codes) {
      expect(new TranscriptionError(400, "m", code).code).toBe(code);
    }
  });
});

describe("agentApi.transcribeAudio success", () => {
  it("posts the file to the transcribe endpoint and returns the parsed text", async () => {
    global.fetch = vi
      .fn()
      .mockResolvedValue(stubResponse({ json: { text: "hello world" } }));

    const result = await agentApi.transcribeAudio(audio);

    expect(result).toEqual({ text: "hello world" });
    expect(mocks.getApiUrl).toHaveBeenCalledWith("/workspace/transcribe");
  });

  it("sends POST with the auth headers and a multipart body", async () => {
    global.fetch = vi
      .fn()
      .mockResolvedValue(stubResponse({ json: { text: "ok" } }));

    await agentApi.transcribeAudio(audio);

    const init = lastInit();
    expect(init.method).toBe("POST");
    expect(init.headers).toEqual({ Authorization: "Bearer tok" });
    expect(init.body).toBeInstanceOf(FormData);
  });

  it("appends the file under the field name the backend reads", async () => {
    global.fetch = vi
      .fn()
      .mockResolvedValue(stubResponse({ json: { text: "ok" } }));

    await agentApi.transcribeAudio(audio);

    const form = lastInit().body as FormData;
    expect(form.get("file")).toBeInstanceOf(File);
    expect((form.get("file") as File).name).toBe("voice.webm");
  });

  it("accepts a bare Blob as well as a File", async () => {
    global.fetch = vi
      .fn()
      .mockResolvedValue(stubResponse({ json: { text: "blob" } }));
    const blob = new Blob(["\u0000raw"], { type: "audio/wav" });

    await expect(agentApi.transcribeAudio(blob)).resolves.toEqual({
      text: "blob",
    });
    expect((lastInit().body as FormData).get("file")).toBeInstanceOf(Blob);
  });

  it("does not set a Content-Type so the browser supplies the multipart boundary", async () => {
    global.fetch = vi
      .fn()
      .mockResolvedValue(stubResponse({ json: { text: "ok" } }));

    await agentApi.transcribeAudio(audio);

    expect(Object.keys(lastInit().headers ?? {})).not.toContain("Content-Type");
  });
});

describe("agentApi.transcribeAudio failure mapping", () => {
  it("maps an object detail onto the machine code and the server message", async () => {
    global.fetch = vi.fn().mockResolvedValue(
      stubResponse({
        ok: false,
        status: 400,
        statusText: "Bad Request",
        json: {
          detail: { code: "FILE_TOO_LARGE", message: "audio over 25 MB" },
        },
      }),
    );

    const err = await mustReject<TranscriptionError>(() =>
      agentApi.transcribeAudio(audio),
    );

    expect(err).toBeInstanceOf(TranscriptionError);
    expect(err.status).toBe(400);
    expect(err.code).toBe("FILE_TOO_LARGE");
    expect(err.message).toBe("Transcription failed: 400 audio over 25 MB");
  });

  it("keeps the HTTP status text when an object detail carries no message", async () => {
    global.fetch = vi.fn().mockResolvedValue(
      stubResponse({
        ok: false,
        status: 415,
        statusText: "Unsupported Media Type",
        json: { detail: { code: "UNSUPPORTED_FILE_TYPE" } },
      }),
    );

    const err = await mustReject<TranscriptionError>(() =>
      agentApi.transcribeAudio(audio),
    );

    expect(err.code).toBe("UNSUPPORTED_FILE_TYPE");
    expect(err.message).toBe(
      "Transcription failed: 415 Unsupported Media Type",
    );
  });

  it("keeps the HTTP status text when an object detail sends an empty message", async () => {
    global.fetch = vi.fn().mockResolvedValue(
      stubResponse({
        ok: false,
        status: 500,
        statusText: "Server Error",
        json: { detail: { code: "TRANSCRIPTION_DISABLED", message: "" } },
      }),
    );

    const err = await mustReject<TranscriptionError>(() =>
      agentApi.transcribeAudio(audio),
    );

    expect(err.message).toBe("Transcription failed: 500 Server Error");
    expect(err.code).toBe("TRANSCRIPTION_DISABLED");
  });

  it("uses a plain-string detail as the user-facing message", async () => {
    global.fetch = vi.fn().mockResolvedValue(
      stubResponse({
        ok: false,
        status: 403,
        statusText: "Forbidden",
        json: { detail: "transcription is disabled for this workspace" },
      }),
    );

    const err = await mustReject<TranscriptionError>(() =>
      agentApi.transcribeAudio(audio),
    );

    expect(err.message).toBe(
      "Transcription failed: 403 transcription is disabled for this workspace",
    );
    expect(err.code).toBeUndefined();
  });

  it("leaves the code undefined for a string detail even when it looks like a code", async () => {
    global.fetch = vi.fn().mockResolvedValue(
      stubResponse({
        ok: false,
        status: 400,
        statusText: "Bad Request",
        json: { detail: "FILE_TOO_LARGE" },
      }),
    );

    const err = await mustReject<TranscriptionError>(() =>
      agentApi.transcribeAudio(audio),
    );

    expect(err.code).toBeUndefined();
    expect(err.message).toContain("FILE_TOO_LARGE");
  });

  it("falls back to the status text when the body has no detail field", async () => {
    global.fetch = vi.fn().mockResolvedValue(
      stubResponse({
        ok: false,
        status: 502,
        statusText: "Bad Gateway",
        json: { message: "ignored" },
      }),
    );

    const err = await mustReject<TranscriptionError>(() =>
      agentApi.transcribeAudio(audio),
    );

    expect(err.message).toBe("Transcription failed: 502 Bad Gateway");
    expect(err.code).toBeUndefined();
  });

  it("treats a null detail as absent rather than as an object", async () => {
    global.fetch = vi.fn().mockResolvedValue(
      stubResponse({
        ok: false,
        status: 500,
        statusText: "Oops",
        json: { detail: null },
      }),
    );

    const err = await mustReject<TranscriptionError>(() =>
      agentApi.transcribeAudio(audio),
    );

    expect(err.message).toBe("Transcription failed: 500 Oops");
    expect(err.code).toBeUndefined();
  });

  it("survives a body that is not JSON and reports the status text", async () => {
    global.fetch = vi
      .fn()
      .mockResolvedValue(nonJsonResponse(500, "Internal Server Error"));

    const err = await mustReject<TranscriptionError>(() =>
      agentApi.transcribeAudio(audio),
    );

    expect(err).toBeInstanceOf(TranscriptionError);
    expect(err.status).toBe(500);
    expect(err.message).toBe("Transcription failed: 500 Internal Server Error");
  });

  it("survives an empty body with no status text at all", async () => {
    global.fetch = vi
      .fn()
      .mockResolvedValue(
        stubResponse({ ok: false, status: 504, statusText: "" }),
      );

    const err = await mustReject<TranscriptionError>(() =>
      agentApi.transcribeAudio(audio),
    );

    expect(err.status).toBe(504);
    expect(err.message).toBe("Transcription failed: 504 ");
    expect(err.code).toBeUndefined();
  });

  it("propagates a network rejection instead of wrapping it", async () => {
    global.fetch = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));

    await expect(agentApi.transcribeAudio(audio)).rejects.toThrow(
      "Failed to fetch",
    );
    await expect(agentApi.transcribeAudio(audio)).rejects.not.toBeInstanceOf(
      TranscriptionError,
    );
  });
});

describe("agentApi read-only workspace endpoints", () => {
  it("reads the agent language", async () => {
    mocks.request.mockResolvedValue({ language: "zh" });

    await expect(agentApi.getAgentLanguage()).resolves.toEqual({
      language: "zh",
    });
    expect(mocks.request).toHaveBeenCalledWith("/workspace/language");
  });

  it("reads the audio mode", async () => {
    mocks.request.mockResolvedValue({ audio_mode: "push_to_talk" });

    await expect(agentApi.getAudioMode()).resolves.toEqual({
      audio_mode: "push_to_talk",
    });
    expect(mocks.request).toHaveBeenCalledWith("/workspace/audio-mode");
  });

  it("reads the transcription provider type", async () => {
    mocks.request.mockResolvedValue({
      transcription_provider_type: "local_whisper",
    });

    await expect(agentApi.getTranscriptionProviderType()).resolves.toEqual({
      transcription_provider_type: "local_whisper",
    });
    expect(mocks.request).toHaveBeenCalledWith(
      "/workspace/transcription-provider-type",
    );
  });

  it("reads the provider catalogue together with the configured id", async () => {
    const payload = {
      providers: [
        { id: "openai", name: "OpenAI", available: true },
        { id: "local_whisper", name: "Local Whisper", available: false },
      ],
      configured_provider_id: "openai",
    };
    mocks.request.mockResolvedValue(payload);

    await expect(agentApi.getTranscriptionProviders()).resolves.toEqual(
      payload,
    );
    expect(mocks.request).toHaveBeenCalledWith(
      "/workspace/transcription-providers",
    );
  });

  it("keeps an unavailable provider in the catalogue", async () => {
    mocks.request.mockResolvedValue({
      providers: [{ id: "x", name: "X", available: false }],
      configured_provider_id: "",
    });

    const result = await agentApi.getTranscriptionProviders();

    expect(result.providers).toHaveLength(1);
    expect(result.providers[0].available).toBe(false);
  });

  it("reads the memory backend descriptors", async () => {
    const backends = [
      { id: "local", label: "Local", source: "builtin", available: true },
      {
        id: "graph",
        label: "Graph",
        source: "plugin",
        available: false,
        metadata: { reason: "off" },
      },
    ];
    mocks.request.mockResolvedValue(backends);

    await expect(agentApi.listMemoryBackends()).resolves.toEqual(backends);
    expect(mocks.request).toHaveBeenCalledWith("/agents/memory/backends");
  });

  it("passes through an empty memory backend list", async () => {
    mocks.request.mockResolvedValue([]);

    await expect(agentApi.listMemoryBackends()).resolves.toEqual([]);
  });

  it("posts the simple shutdown without a body", async () => {
    await agentApi.shutdownSimple();

    expect(mocks.request).toHaveBeenCalledWith("/agent/shutdown", {
      method: "POST",
    });
  });

  it("keeps the simple and admin shutdown paths distinct", async () => {
    await agentApi.shutdownSimple();
    await agentApi.shutdown();

    expect(mocks.request).toHaveBeenNthCalledWith(1, "/agent/shutdown", {
      method: "POST",
    });
    expect(mocks.request).toHaveBeenNthCalledWith(2, "/agent/admin/shutdown", {
      method: "POST",
    });
  });

  it("writes the transcription provider type", async () => {
    mocks.request.mockResolvedValue({ transcription_provider_type: "openai" });

    await agentApi.updateTranscriptionProviderType("openai");

    expect(mocks.request).toHaveBeenCalledWith(
      "/workspace/transcription-provider-type",
      {
        method: "PUT",
        body: JSON.stringify({ transcription_provider_type: "openai" }),
      },
    );
  });
});

describe("agentApi.testEmbedding timeout policy", () => {
  it("derives the timeout from the configured health-check timeout", async () => {
    await agentApi.testEmbedding({ health_check_timeout: 60 } as never);

    expect(mocks.request).toHaveBeenCalledWith(
      "/workspace/embedding/test",
      expect.objectContaining({ timeout: 125 * 1000 }),
    );
  });

  it("assumes 15s when the config omits the health-check timeout", async () => {
    await agentApi.testEmbedding({} as never);

    expect(mocks.request).toHaveBeenCalledWith(
      "/workspace/embedding/test",
      expect.objectContaining({ timeout: 35 * 1000 }),
    );
  });

  it("never goes below the 30s floor even for a tiny health-check timeout", async () => {
    await agentApi.testEmbedding({ health_check_timeout: 1 } as never);

    expect(mocks.request).toHaveBeenCalledWith(
      "/workspace/embedding/test",
      expect.objectContaining({ timeout: 30 * 1000 }),
    );
  });
});
