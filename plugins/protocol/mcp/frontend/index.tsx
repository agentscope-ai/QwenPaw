import { getHost, type Disposable } from "@qwenpaw/plugin-sdk";

const sdk = getHost();
const React = sdk.host.React;
const { useEffect, useState } = React;
const pluginId = "qwenpaw-mcp";
// Startup loading and an explicit page retry can overlap. Own one wrapper.
sdk.modules ??= {};
const ownModule = (sdk.modules[pluginId] ??= {});
(ownModule.management as Disposable | undefined)?.dispose();

const registration = sdk.route.wrap(pluginId, "core.mcp", (Inner) => {
  function MCPManagement() {
    const agent = sdk.host.useSelectedAgent();
    const chinese = sdk.host.useLocale().startsWith("zh");
    const [admitted, setAdmitted] = useState("");
    const [error, setError] = useState("");
    const [revision, setRevision] = useState(0);
    const [busy, setBusy] = useState(false);
    const requests = React.useRef<AbortController | null>(null);

    useEffect(() => {
      const controller = new AbortController();
      requests.current = controller;
      setAdmitted("");
      setError("");
      setBusy(false);
      sdk.host
        .fetch(
          `/qwenpaw-mcp/management?agent_id=${encodeURIComponent(agent.id)}`,
          { signal: controller.signal },
        )
        .then(async (response) => {
          if (!response.ok)
            throw new Error(`MCP management (${response.status})`);
          const result = await response.json();
          if (
            result.workspace_id !== agent.id ||
            result.plugin_id !== pluginId
          ) {
            throw new Error("MCP workspace changed");
          }
          if (!controller.signal.aborted) setAdmitted(agent.id);
        })
        .catch((failure: unknown) => {
          if (!controller.signal.aborted) setError(String(failure));
        });
      return () => controller.abort();
    }, [agent.id, revision]);

    async function remove(uninstall: boolean) {
      const controller = requests.current;
      if (!controller || controller.signal.aborted) return;
      setBusy(true);
      setError("");
      try {
        const response = await sdk.host.fetch(
          uninstall ? `/plugins/${pluginId}` : `/plugins/${pluginId}/enabled`,
          {
            method: uninstall ? "DELETE" : "POST",
            headers: { "Content-Type": "application/json" },
            body: uninstall ? undefined : JSON.stringify({ enabled: false }),
            signal: controller.signal,
          },
        );
        if (!response.ok) throw new Error(await response.text());
        if (controller.signal.aborted) return;
        registration.dispose();
        window.dispatchEvent(new Event("qwenpaw:mcp-plugin-changed"));
      } catch (failure) {
        if (!controller.signal.aborted) setError(String(failure));
      } finally {
        if (!controller.signal.aborted) setBusy(false);
      }
    }

    return (
      <>
        <div
          role="region"
          aria-label={chinese ? "MCP 插件管理" : "MCP plugin management"}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 12,
            padding: "12px 24px",
          }}
        >
          <span>{chinese ? "MCP 插件" : "MCP plugin"}</span>
          <button disabled={busy} onClick={() => void remove(false)}>
            {chinese ? "禁用" : "Disable"}
          </button>
          <button disabled={busy} onClick={() => void remove(true)}>
            {chinese ? "卸载" : "Uninstall"}
          </button>
          {error && (
            <>
              <span role="alert">{error}</span>
              <button onClick={() => setRevision((value) => value + 1)}>
                {chinese ? "重试" : "Retry"}
              </button>
            </>
          )}
        </div>
        <Inner managementMounted managementAvailable={admitted === agent.id} />
      </>
    );
  }
  return MCPManagement;
});
ownModule.management = registration;
