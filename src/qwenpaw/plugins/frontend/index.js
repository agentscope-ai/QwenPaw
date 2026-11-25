export const SDK_VERSION = "1.2.0";
// Library features only. Query capabilities(appId) for the running backend.
export const SDK_CAPABILITIES = Object.freeze(["host", "chat", "routes", "paw", "tasks", "harnesses", "checkpoints"]);
export function getHost() {
  const host = globalThis.window?.QwenPaw;
  if (!host) throw new Error("QwenPaw host is unavailable");
  return host;
}
export function forApp(appId) {
  const factory = getHost().paw;
  if (!factory) throw new Error("PawApp host capabilities are unavailable");
  return factory.forApp(appId);
}
export function tasks(appId) {
  const api = forApp(appId).api;
  async function requireTasks(options) {
    const result = await capabilities(appId, options);
    if (result.status !== "supported" || !result.capabilities.includes("tasks")) {
      throw new Error("This app has not advertised the tasks capability");
    }
  }
  return {
    start: async (request, options) => { await requireTasks(options); return api.post("/tasks", request, options); },
    get: async (runId, options) => { await requireTasks(options); return api.get(`/tasks/${encodeURIComponent(runId)}`, options); },
    stream: async function* (runId, options) {
      await requireTasks(options);
      for await (const event of api.events(`/tasks/${encodeURIComponent(runId)}/stream`, {...options, method: "GET"})) {
        if (event.data) yield JSON.parse(event.data);
      }
    },
    cancel: async (runId, options) => { await requireTasks(options); return api.post(`/tasks/${encodeURIComponent(runId)}/cancel`, {}, options); },
  };
}
export async function capabilities(appId, options) {
  try {
    const result = await forApp(appId).api.get("/.sdk", options);
    if (!result || typeof result.sdk_version !== "string" || !Array.isArray(result.capabilities)) {
      return {status: "unknown", sdk_version: null, app_id: appId, capabilities: []};
    }
    return {...result, status: result.sdk_version.split(".")[0] === "1" ? "supported" : "unsupported"};
  } catch (error) {
    if (options?.signal?.aborted) throw error;
    // Old apps and unreachable backends both lack a verified capability claim.
    return {status: "unknown", sdk_version: null, app_id: appId, capabilities: []};
  }
}

/** SDK 1.2: selected-conversation checkpoints; applying uses host approval. */
export function checkpoints(appId) {
  const api = forApp(appId).api;
  async function request(action, body, options) {
    if (!options?.chatId) throw new Error("Select a saved conversation first");
    if (typeof options.agentId !== "string" || !options.agentId.trim()) {
      throw new Error("Specify the selected conversation's workspace (agentId)");
    }
    const scope = {
      signal: options.signal,
      headers: { ...options.headers, "X-Chat-Id": options.chatId },
      query: { ...options.query, agent_id: options.agentId },
    };
    const advertised = await capabilities(appId, scope);
    if (advertised.status !== "supported" || !advertised.capabilities.includes("checkpoints")) {
      throw new Error("This app has not advertised checkpoint support");
    }
    if (action === "timeline") return api.get("/checkpoints/timeline", { ...scope, query: { ...scope.query, limit: options.limit ?? 20 } });
    return api.post("/checkpoints/" + action, body, scope);
  }
  function restoreBody(target, options) {
    return { target, include_memory: options.include_memory ?? false, include_files: options.include_files ?? false, ...(options.files ? { files: options.files } : {}) };
  }
  return {
    timeline: (options) => request("timeline", undefined, options),
    snapshot: (name, options) => request("snapshot", { name }, options),
    previewRestore: (target, options) => request("restore/preview", restoreBody(target, options), options),
    restore: (target, options) => request("restore", restoreBody(target, options), options),
  };
}
