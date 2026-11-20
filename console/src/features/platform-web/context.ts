import type { WebAccount, WebTarget } from "./client";

export const CONSOLE_HOST_PROTOCOL = 1;
export interface ConsoleHostContext {
  protocol: number;
  apiBase: string;
  basename: string;
  route: string;
  account: WebAccount;
  target: WebTarget;
  targets: WebTarget[];
  updateAvailable: boolean;
}

export let consoleHost: ConsoleHostContext | null = null;
export let hostRequest: (
  path: string,
  body?: unknown,
) => Promise<unknown> = () =>
  Promise.reject(new Error("Console host is unavailable"));

export function setConsoleHost(
  context: ConsoleHostContext,
  request: typeof hostRequest,
) {
  consoleHost = context;
  hostRequest = request;
}
