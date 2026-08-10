# PawApp SDK app contract proposal

> Implementation status (2026-08-07): the app-scoped frontend handle, native
> page registration, standard host-capability routes, managed sidecar service,
> extension registration, scope validation, and compatibility tests are
> implemented on `dev/datapaw-app` for later owning-team review.

Status: local proposal for review by the PawApp SDK owning team.

This change set does not assume ownership of the PawApp SDK. It records the
small public contract needed by native, full-page applications. Application
and SDK changes should be reviewed and landed as separate commits.

## Problem

An installed app needs to register a native page, call only its own backend,
use host chat and storage, and optionally run a private loopback service. The
current lower-level plugin globals make the app repeat authentication, route
prefixing, lifecycle, and cleanup logic. That encourages apps to combine the
SDK with direct `window.QwenPaw` calls or fixed-port `fetch` calls.

## Proposed frontend surface

```ts
const paw = window.QwenPaw.paw.forApp("example-app");

const page = paw.ui.registerPage({
  label: "Example",
  mount(container) {
    const root = createRoot(container);
    root.render(<ExampleApp paw={paw} />);
    return () => root.unmount();
  },
});

const result = await paw.api.post("/query", { question: "..." });
await paw.storage.set("selected-source", "warehouse");
const reply = await paw.chat("Analyze last week's conversion rate");

for await (const event of paw.api.events("/tasks/session/dag/events", {
  method: "GET",
})) {
  console.log(event.event, event.data);
}
```

Required behavior:

- `forApp(appId)` validates and permanently scopes the returned handle.
- `paw.api` prefixes `/api/{appId}` and uses the host's authenticated request
  path. It supports GET, POST, PUT, PATCH, DELETE, downloads, streams, and
  native request bodies such as `FormData` through `rawBody`.
- Permanent app API and page paths reject absolute URLs, query/hash fragments,
  backslashes, and decoded or double-encoded dot segments. Query values use
  the dedicated `query` option. The legacy dynamic API keeps its prior path
  behavior until a separate deprecation cycle.
- `registerPage` accepts either a host-compatible React component or a mount
  callback for a self-contained UI runtime. Routes must remain under
  `/apps/{appId}` and registration returns a disposable.
- `paw.ui.chat` scopes chat presentation and tool renderers to the app ID.
- `paw.chat(message, { agentId, sessionId, skill })` supports an explicit
  app-owned agent rather than relying on mutable host selection.
- `paw.api.events()` supports authenticated GET and POST SSE, including named
  events, multiline data, IDs, cancellation, and app-scope validation.
- Apps do not need `getApiToken`, `getApiUrl`, `registerRoutes`, or direct
  access to the global route/chat registries.

## Proposed backend surface

```py
app = PawApp("Example", app_id="example-app")
app.enable_standard_capabilities()

service = app.managed_service(
    "context",
    command=(python, "-m", "example_service", "--port", "{port}"),
    health_path="/health",
    external_url_env="EXAMPLE_SERVICE_URL",
    mode_env="EXAMPLE_SERVICE_MODE",
)

app.skill_provider(skills_dir)
app.prompt_section("example-guidance", "...")
app.agent_profile("example", name="Example Agent", persona_dir=persona_dir)
```

Required behavior:

- Apps explicitly opt into standard namespaced chat, storage, toast, and
  notify routes through `enable_standard_capabilities()`. Existing PawApps do
  not receive new routes automatically.
- The SDK aggregates standard and app-defined routers into one registry
  registration because the host owns a single HTTP prefix per plugin.
- `managed_service` allocates a loopback port, starts before app routes are
  used, health-checks, captures bounded diagnostics, and stops during host
  shutdown. An explicit external mode supports production service managers.
- Service URLs, tokens, environment variables, and process IDs are never
  returned by `status()`. Explicit backend diagnostics use `diagnostics()`.
- Skill providers, prompt sections, workspace callbacks, and runtime hooks
  delegate through the existing `PluginApi`; the app never receives or calls
  `PluginApi` directly.
- App-owned agent profiles are provisioned idempotently through the SDK,
  started by the normal workspace manager, and detached without deleting user
  conversations or artifacts.

## Compatibility and rollout

- Existing `paw` imports, embedded path query strings, custom routes, and
  existing plugins continue to work unchanged.
- The new API is additive. `forApp` is the recommended path for native apps.
- Strict app ID and path validation applies to the new permanent `forApp`
  handles. The legacy dynamic API retains its previous path behavior and can
  be deprecated on a separate schedule.
- The SDK-owning team can split the proposal into smaller releases. Consumer
  apps should pin the first QwenPaw version that contains the accepted
  contract.
- Until accepted, SDK-dependent changes stay isolated from consumer app code
  so they can be rebased without rewriting product features.

## Acceptance tests

- Two app handles cannot cross-call each other's backend or register routes
  outside their own path, including encoded traversal attempts.
- A PawApp that does not opt in receives no standard capability routes.
- Page disposal unmounts the standalone UI exactly once.
- All request verbs carry normal host authentication and app route prefixing.
- Managed services receive a dynamically allocated port, pass health checks,
  and are terminated on failed startup and normal shutdown.
- External mode requires an explicit URL and never launches a child process.
- No public status response contains a sidecar URL, token, environment value,
  or PID.
