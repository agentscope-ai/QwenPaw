/**
 * provider.ts - request contract layer for the model/provider REST surface.
 *
 * Sibling coverage note: ./provider.test.ts already pins listProviders and
 * getActiveModels query building on their *cold* path, plus setActiveLlm,
 * configureProvider, addModel and removeModel. This file covers what it leaves
 * out:
 *   - the two singleflight cache-hit arms (`if (listProvidersPromise) return`
 *     and `if (cached) return`), which the cold-path calls can never reach, and
 *     the release of both caches once the in-flight promise settles.
 *   - custom-provider CRUD, model visibility/config, local-model config,
 *     the two test-connection endpoints, discoverModels (the only method that
 *     builds its path through URL + searchParams), probeMultimodal, the three
 *     OpenRouter endpoints and the two OAuth endpoints.
 *
 * The singleflight state lives in module-level bindings, so every test here
 * re-imports the module after vi.resetModules() to get an unpolluted instance
 * rather than relying on the previous test having drained its cache.
 *
 * Assertions are on path / method / body - the frontend contract - never on
 * backend behaviour.
 */
import { describe, it, expect, vi, afterEach } from "vitest";

type ProviderModule = typeof import("./provider");

vi.mock("../request", () => ({ request: vi.fn() }));

const { request } = await import("../request");
const mockedRequest = vi.mocked(request);

/** Fresh provider module with an empty singleflight cache. */
async function freshProvider(): Promise<ProviderModule> {
  vi.resetModules();
  return await import("./provider");
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

afterEach(() => {
  vi.clearAllMocks();
  mockedRequest.mockReset();
});

describe("providerApi.listProviders singleflight", () => {
  it("serves concurrent callers from one in-flight request", async () => {
    const { providerApi } = await freshProvider();
    const pending = deferred<unknown[]>();
    mockedRequest.mockReturnValue(pending.promise as never);

    const first = providerApi.listProviders();
    const second = providerApi.listProviders();

    expect(mockedRequest).toHaveBeenCalledTimes(1);
    expect(mockedRequest).toHaveBeenCalledWith("/models");
    expect(second).toBe(first);

    pending.resolve([{ id: "openai" }] as never);
    await expect(first).resolves.toEqual([{ id: "openai" }]);
  });

  it("issues a new request after the previous one settled", async () => {
    const { providerApi } = await freshProvider();
    mockedRequest.mockResolvedValue([{ id: "a" }] as never);

    await providerApi.listProviders();
    await providerApi.listProviders();

    expect(mockedRequest).toHaveBeenCalledTimes(2);
  });

  it("releases the cache after a rejection so a retry is possible", async () => {
    const { providerApi } = await freshProvider();
    mockedRequest.mockRejectedValueOnce(new Error("network down"));

    await expect(providerApi.listProviders()).rejects.toThrow("network down");

    mockedRequest.mockResolvedValue([{ id: "b" }] as never);
    await expect(providerApi.listProviders()).resolves.toEqual([{ id: "b" }]);
    expect(mockedRequest).toHaveBeenCalledTimes(2);
  });

  it("shares the rejected promise with a caller that joined while it was pending", async () => {
    const { providerApi } = await freshProvider();
    const pending = deferred<unknown[]>();
    mockedRequest.mockReturnValue(pending.promise as never);

    const first = providerApi.listProviders();
    const second = providerApi.listProviders();
    pending.reject(new Error("boom"));

    await expect(first).rejects.toThrow("boom");
    await expect(second).rejects.toThrow("boom");
    expect(mockedRequest).toHaveBeenCalledTimes(1);
  });
});

describe("providerApi.getActiveModels singleflight", () => {
  it("keys the cache on the resolved query so identical params share one request", async () => {
    const { providerApi } = await freshProvider();
    const pending = deferred<unknown>();
    mockedRequest.mockReturnValue(pending.promise as never);

    const first = providerApi.getActiveModels({ scope: "effective" });
    const second = providerApi.getActiveModels({ scope: "effective" });

    expect(mockedRequest).toHaveBeenCalledTimes(1);
    expect(mockedRequest).toHaveBeenCalledWith(
      "/models/active?scope=effective",
    );
    expect(second).toBe(first);

    pending.resolve({} as never);
    await first;
  });

  it("does not share the cache across different scopes", async () => {
    const { providerApi } = await freshProvider();
    mockedRequest.mockResolvedValue({} as never);

    const a = providerApi.getActiveModels({ scope: "global" });
    const b = providerApi.getActiveModels({ scope: "agent" });

    expect(a).not.toBe(b);
    expect(mockedRequest).toHaveBeenCalledTimes(2);
    expect(mockedRequest).toHaveBeenNthCalledWith(
      1,
      "/models/active?scope=global",
    );
    expect(mockedRequest).toHaveBeenNthCalledWith(
      2,
      "/models/active?scope=agent",
    );
    await Promise.all([a, b]);
  });

  it("does not share the cache between a parameterised and a bare call", async () => {
    const { providerApi } = await freshProvider();
    mockedRequest.mockResolvedValue({} as never);

    const bare = providerApi.getActiveModels();
    const scoped = providerApi.getActiveModels({ agent_id: "ag-1" });

    expect(bare).not.toBe(scoped);
    expect(mockedRequest).toHaveBeenNthCalledWith(1, "/models/active");
    expect(mockedRequest).toHaveBeenNthCalledWith(
      2,
      "/models/active?agent_id=ag-1",
    );
    await Promise.all([bare, scoped]);
  });

  it("drops the cached entry once settled so a later call re-fetches", async () => {
    const { providerApi } = await freshProvider();
    mockedRequest.mockResolvedValue({ models: [] } as never);

    await providerApi.getActiveModels();
    await providerApi.getActiveModels();

    expect(mockedRequest).toHaveBeenCalledTimes(2);
  });
});

describe("providerApi.setActiveLlm cache invalidation", () => {
  it("PUTs the body and then clears every cached active-model promise", async () => {
    const { providerApi } = await freshProvider();
    mockedRequest.mockResolvedValue({ active: true } as never);
    const body = {
      provider_id: "openai",
      model: "gpt-4",
      scope: "agent" as const,
    };

    await providerApi.getActiveModels({ scope: "agent" });
    mockedRequest.mockClear();

    await expect(providerApi.setActiveLlm(body)).resolves.toEqual({
      active: true,
    });
    expect(mockedRequest).toHaveBeenCalledWith("/models/active", {
      method: "PUT",
      body: JSON.stringify(body),
    });
  });

  it("resolves with the request result unchanged", async () => {
    const { providerApi } = await freshProvider();
    const payload = { llm: { provider_id: "dashscope", model: "qwen-max" } };
    mockedRequest.mockResolvedValue(payload as never);

    await expect(
      providerApi.setActiveLlm({
        provider_id: "dashscope",
        model: "qwen-max",
        scope: "global",
      }),
    ).resolves.toBe(payload);
  });

  it("rejects without swallowing the request error", async () => {
    const { providerApi } = await freshProvider();
    mockedRequest.mockRejectedValue(new Error("409 Conflict"));

    await expect(
      providerApi.setActiveLlm({
        provider_id: "x",
        model: "y",
        scope: "global",
      }),
    ).rejects.toThrow("409 Conflict");
  });
});

describe("providerApi custom provider CRUD", () => {
  it("creates a custom provider by POSTing the body", async () => {
    const { providerApi } = await freshProvider();
    mockedRequest.mockResolvedValue({ id: "custom-1" } as never);
    const body = { name: "My Provider", base_url: "https://api.example.com" };

    await providerApi.createCustomProvider(body as never);

    expect(request).toHaveBeenCalledWith("/models/custom-providers", {
      method: "POST",
      body: JSON.stringify(body),
    });
  });

  it("deletes a custom provider and returns the remaining provider list", async () => {
    const { providerApi } = await freshProvider();
    mockedRequest.mockResolvedValue([] as never);

    await providerApi.deleteCustomProvider("custom/1");

    expect(request).toHaveBeenCalledWith(
      "/models/custom-providers/custom%2F1",
      { method: "DELETE" },
    );
  });
});

describe("providerApi model-level endpoints", () => {
  it("toggles visibility with a boolean body and encodes both ids", async () => {
    const { providerApi } = await freshProvider();
    mockedRequest.mockResolvedValue({ id: "p" } as never);

    await providerApi.setModelVisibility("open/ai", "gpt 4", true);

    expect(request).toHaveBeenCalledWith(
      "/models/open%2Fai/models/gpt%204/visibility",
      { method: "PUT", body: JSON.stringify({ hidden: true }) },
    );
  });

  it("keeps hidden=false as an explicit false rather than dropping the field", async () => {
    const { providerApi } = await freshProvider();
    mockedRequest.mockResolvedValue({ id: "p" } as never);

    await providerApi.setModelVisibility("p", "m", false);

    expect(request).toHaveBeenCalledWith("/models/p/models/m/visibility", {
      method: "PUT",
      body: '{"hidden":false}',
    });
  });

  it("configures a model by PUT with the whole body serialised", async () => {
    const { providerApi } = await freshProvider();
    mockedRequest.mockResolvedValue({ id: "p" } as never);
    const body = { api_key: "sk-1", temperature: 0.2 };

    await providerApi.configureModel("p/1", "m/2", body as never);

    expect(request).toHaveBeenCalledWith("/models/p%2F1/models/m%2F2/config", {
      method: "PUT",
      body: JSON.stringify(body),
    });
  });
});

describe("providerApi local model config", () => {
  it("saves local model settings with a PUT", async () => {
    const { providerApi } = await freshProvider();
    mockedRequest.mockResolvedValue({ ok: true } as never);
    const body = { enabled: true, models: ["qwen3-coder"] };

    await providerApi.configureLocalModelSettings(body as never);

    expect(request).toHaveBeenCalledWith("/local-models/config", {
      method: "PUT",
      body: JSON.stringify(body),
    });
  });

  it("reads the local model config with a bare GET and no options", async () => {
    const { providerApi } = await freshProvider();
    mockedRequest.mockResolvedValue({ enabled: false } as never);

    await expect(providerApi.getLocalModelConfig()).resolves.toEqual({
      enabled: false,
    });
    expect(request).toHaveBeenCalledWith("/local-models/config");
    expect(request).toHaveBeenCalledTimes(1);
  });
});

describe("providerApi test-connection endpoints", () => {
  it("omits the body entirely when no test payload is supplied", async () => {
    const { providerApi } = await freshProvider();
    mockedRequest.mockResolvedValue({ success: true } as never);

    await providerApi.testProviderConnection("openai");

    expect(request).toHaveBeenCalledWith("/models/openai/test", {
      method: "POST",
      body: undefined,
    });
  });

  it("serialises the supplied test payload", async () => {
    const { providerApi } = await freshProvider();
    mockedRequest.mockResolvedValue({ success: true } as never);
    const body = { api_key: "sk-test" };

    await providerApi.testProviderConnection("open/ai", body as never);

    expect(request).toHaveBeenCalledWith("/models/open%2Fai/test", {
      method: "POST",
      body: JSON.stringify(body),
    });
  });

  it("tests a single model through the models/test sub-resource", async () => {
    const { providerApi } = await freshProvider();
    mockedRequest.mockResolvedValue({ success: false, error: "401" } as never);
    const body = { model: "gpt-4o" };

    await expect(
      providerApi.testModelConnection("openai", body as never),
    ).resolves.toEqual({ success: false, error: "401" });
    expect(request).toHaveBeenCalledWith("/models/openai/models/test", {
      method: "POST",
      body: JSON.stringify(body),
    });
  });
});

describe("providerApi.discoverModels - URL/searchParams based path", () => {
  it("defaults save to true and appends it as a query string", async () => {
    const { providerApi } = await freshProvider();
    mockedRequest.mockResolvedValue({ models: [] } as never);

    await providerApi.discoverModels("openai");

    expect(request).toHaveBeenCalledWith("/models/openai/discover?save=true", {
      method: "POST",
      body: undefined,
    });
  });

  it("passes save=false through as a string query value", async () => {
    const { providerApi } = await freshProvider();
    mockedRequest.mockResolvedValue({ models: [] } as never);

    await providerApi.discoverModels("openai", undefined, false);

    expect(request).toHaveBeenCalledWith("/models/openai/discover?save=false", {
      method: "POST",
      body: undefined,
    });
  });

  it("keeps a slash in the provider id percent-encoded inside the path segment", async () => {
    const { providerApi } = await freshProvider();
    mockedRequest.mockResolvedValue({ models: [] } as never);

    await providerApi.discoverModels("open/ai", { api_key: "k" } as never);

    expect(request).toHaveBeenCalledWith(
      "/models/open%2Fai/discover?save=true",
      { method: "POST", body: JSON.stringify({ api_key: "k" }) },
    );
  });

  it("percent-encodes a space in the provider id as %20, not as a plus sign", async () => {
    const { providerApi } = await freshProvider();
    mockedRequest.mockResolvedValue({ models: [] } as never);

    await providerApi.discoverModels("my provider");

    const path = mockedRequest.mock.calls[0][0] as string;
    expect(path).toBe("/models/my%20provider/discover?save=true");
  });

  it("leaves the origin out of the request path", async () => {
    const { providerApi } = await freshProvider();
    mockedRequest.mockResolvedValue({ models: [] } as never);

    await providerApi.discoverModels("openai");

    const path = mockedRequest.mock.calls[0][0] as string;
    expect(path.startsWith("/")).toBe(true);
    expect(path).not.toContain(window.location.origin);
  });
});

describe("providerApi.probeMultimodal", () => {
  it("POSTs to the probe-multimodal sub-resource with no body", async () => {
    const { providerApi } = await freshProvider();
    mockedRequest.mockResolvedValue({ multimodal: true } as never);

    await expect(
      providerApi.probeMultimodal("openai", "gpt-4o"),
    ).resolves.toEqual({ multimodal: true });
    expect(request).toHaveBeenCalledWith(
      "/models/openai/models/gpt-4o/probe-multimodal",
      { method: "POST" },
    );
  });

  it("encodes both ids when they contain reserved characters", async () => {
    const { providerApi } = await freshProvider();
    mockedRequest.mockResolvedValue({} as never);

    await providerApi.probeMultimodal("open/ai", "gpt 4o/mini");

    expect(request).toHaveBeenCalledWith(
      "/models/open%2Fai/models/gpt%204o%2Fmini/probe-multimodal",
      { method: "POST" },
    );
  });
});

describe("providerApi OpenRouter endpoints", () => {
  it("fetches the series catalogue with a bare GET", async () => {
    const { providerApi } = await freshProvider();
    mockedRequest.mockResolvedValue({ series: [] } as never);

    await providerApi.getOpenRouterSeries();

    expect(request).toHaveBeenCalledWith("/models/openrouter/series");
    expect(request).toHaveBeenCalledTimes(1);
  });

  it("omits the body when discovering extended models without a payload", async () => {
    const { providerApi } = await freshProvider();
    mockedRequest.mockResolvedValue({ models: [] } as never);

    await providerApi.discoverOpenRouterExtended();

    expect(request).toHaveBeenCalledWith(
      "/models/openrouter/discover-extended",
      { method: "POST", body: undefined },
    );
  });

  it("serialises the extended discovery payload when supplied", async () => {
    const { providerApi } = await freshProvider();
    mockedRequest.mockResolvedValue({ models: [] } as never);

    await providerApi.discoverOpenRouterExtended({ api_key: "or-1" } as never);

    expect(request).toHaveBeenCalledWith(
      "/models/openrouter/discover-extended",
      { method: "POST", body: JSON.stringify({ api_key: "or-1" }) },
    );
  });

  it("posts the filter criteria to the OpenRouter filter endpoint", async () => {
    const { providerApi } = await freshProvider();
    mockedRequest.mockResolvedValue({ models: [] } as never);
    const body = { query: "code", max_price: 3 };

    await providerApi.filterOpenRouterModels(body as never);

    expect(request).toHaveBeenCalledWith("/models/openrouter/models/filter", {
      method: "POST",
      body: JSON.stringify(body),
    });
  });
});

describe("providerApi OAuth endpoints", () => {
  it("starts the OAuth flow with a POST and no body", async () => {
    const { providerApi } = await freshProvider();
    const payload = {
      authorize_url: "https://x/oauth",
      state: "s1",
      flow_type: "pkce",
    };
    mockedRequest.mockResolvedValue(payload as never);

    await expect(providerApi.startOAuth("open/router")).resolves.toBe(payload);
    expect(request).toHaveBeenCalledWith(
      "/providers/open%2Frouter/oauth/start",
      {
        method: "POST",
      },
    );
  });

  it("queries OAuth status with the state as a percent-encoded query param", async () => {
    const { providerApi } = await freshProvider();
    mockedRequest.mockResolvedValue({ status: "pending" } as never);

    await providerApi.getOAuthStatus("openai", "st ate/1");

    expect(request).toHaveBeenCalledWith(
      "/providers/openai/oauth/status?state=st%20ate%2F1",
    );
  });

  it("reports an OAuth error field verbatim", async () => {
    const { providerApi } = await freshProvider();
    mockedRequest.mockResolvedValue({
      status: "failed",
      error: "access_denied",
    } as never);

    await expect(providerApi.getOAuthStatus("openai", "s")).resolves.toEqual({
      status: "failed",
      error: "access_denied",
    });
  });
});
