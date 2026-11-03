import { beforeEach, describe, expect, it, vi } from "vitest";
import { request } from "../request";
import { portabilityImportApi } from "./import";

vi.mock("../request", () => ({ request: vi.fn() }));
vi.mock("../config", () => ({
  getApiUrl: (path: string) => `/api${path}`,
}));
vi.mock("../authHeaders", () => ({ buildAuthHeaders: () => ({}) }));

describe("portabilityImportApi", () => {
  beforeEach(() => {
    vi.mocked(request).mockReset();
    vi.restoreAllMocks();
  });

  it("pins every JSON request to the explicit agent", async () => {
    vi.mocked(request).mockResolvedValue({});
    const selection = { sessions: true, skills: ["skill-1"] };

    await portabilityImportApi.sources("agent one");
    await portabilityImportApi.create("agent one", ["codex", "qoder"]);
    await portabilityImportApi.snapshot("agent one", "import-1");
    await portabilityImportApi.current("agent one");
    await portabilityImportApi.start(
      "agent one",
      "import-1",
      {
        codex: selection,
      },
      true,
    );
    await portabilityImportApi.retry("agent one", "import-1", {
      codex: { sessions: false, skills: ["skill-1"] },
    });
    await portabilityImportApi.cancel("agent one", "import-1");

    const base = "/agents/agent%20one/portability/imports";
    expect(request).toHaveBeenNthCalledWith(1, `${base}/sources`);
    expect(request).toHaveBeenNthCalledWith(
      2,
      `${base}/jobs`,
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ sources: ["codex", "qoder"] }),
      }),
    );
    expect(request).toHaveBeenNthCalledWith(3, `${base}/jobs/import-1`);
    expect(request).toHaveBeenNthCalledWith(4, `${base}/jobs/current`);
    expect(request).toHaveBeenNthCalledWith(
      5,
      `${base}/jobs/import-1/start`,
      expect.objectContaining({
        body: JSON.stringify({
          selections: { codex: selection },
          allow_plugin_execution: true,
        }),
      }),
    );
    expect(request).toHaveBeenNthCalledWith(
      6,
      `${base}/jobs/import-1/retry`,
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          selections: { codex: { sessions: false, skills: ["skill-1"] } },
        }),
      }),
    );
    expect(request).toHaveBeenNthCalledWith(7, `${base}/jobs/import-1/cancel`, {
      method: "POST",
    });
  });

  it("parses reconnectable SSE snapshots", async () => {
    const encoder = new TextEncoder();
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(
          encoder.encode(
            'data: {"seq":3,"snapshot":{"job_id":"j","agent_id":"a","state":"completed","phase":"done","seq":3,"providers":[],"logs":[]}}\n\n',
          ),
        );
        controller.close();
      },
    });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(stream, { status: 200 })),
    );
    const events: number[] = [];
    const onOpen = vi.fn();

    await portabilityImportApi.streamEvents(
      "agent one",
      "import-1",
      2,
      (event) => events.push(event.seq),
      new AbortController().signal,
      onOpen,
    );

    expect(fetch).toHaveBeenCalledWith(
      "/api/agents/agent%20one/portability/imports/jobs/import-1/events?after=2",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(events).toEqual([3]);
    expect(onOpen).toHaveBeenCalledOnce();
  });
});
