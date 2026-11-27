import { setConsoleHost } from "./context";
import { connectConsoleHost, consoleHostOrigin } from "./hostBridge";
import { useWebWorkspace } from "./client";

/** Initialize the shipped Console before any account-scoped stores load. */
export async function initializeConsoleHost(): Promise<void> {
  const origin = consoleHostOrigin();
  if (origin === undefined) return;

  const bridge = await connectConsoleHost(origin);
  const { context, request } = bridge;
  const update = () => {
    void request("/host/update");
  };
  bridge.onUpdate = () => useWebWorkspace.setState({ update });
  setConsoleHost(context, request);
  useWebWorkspace.setState({
    account: context.account,
    target: context.target,
    targets: context.targets,
    update: context.updateAvailable ? update : null,
  });

  const current = window.location.pathname.slice(context.basename.length);
  const requested =
    current && current !== "/index.html"
      ? current + window.location.search + window.location.hash
      : context.route;
  const route =
    requested.startsWith("/") && !requested.startsWith("//")
      ? requested
      : "/chat";
  window.history.replaceState(null, "", context.basename + route);
  void request("/host/navigation", { route });
}
