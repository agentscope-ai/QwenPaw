import { consoleHost, setConsoleHost } from "./context";
import {
  connectConsoleHost,
  consoleHostOrigin,
  consoleHostRoute,
} from "./hostBridge";
import { useWebWorkspace } from "./client";

/** Initialize the shipped Console before any account-scoped stores load. */
export async function initializeConsoleHost(): Promise<void> {
  const origin = consoleHostOrigin();
  if (origin === undefined) return;

  const update = () => request("/host/update");
  const getBridge = async () => {
    const bridge = await connectConsoleHost(origin);
    const { context } = bridge;
    if (consoleHost !== context) {
      bridge.onUpdate = () => useWebWorkspace.setState({ update });
      setConsoleHost(context, request);
      useWebWorkspace.setState({
        account: context.account,
        target: context.target,
        targets: context.targets,
        update: context.updateAvailable ? update : null,
      });
    }
    return bridge;
  };
  async function request(path: string, body?: unknown): Promise<unknown> {
    return (await getBridge()).request(path, body);
  }

  const { context } = await getBridge();
  const route = consoleHostRoute(context);
  window.history.replaceState(null, "", context.basename + route);
  void request("/host/navigation", { route }).catch(() => undefined);
}
