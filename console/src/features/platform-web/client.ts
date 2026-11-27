import { create } from "zustand";
import { hostRequest } from "./context";
import { consoleHostOrigin } from "./hostBridge";

export const isPlatformWebApp = consoleHostOrigin() !== undefined;
export interface WebAccount {
  id: string;
  display_name: string;
}
export interface WebTarget {
  kind: "cloud" | "bound";
  id: string;
  name: string;
  online: boolean;
}
export const useWebWorkspace = create<{
  account: WebAccount | null;
  target: WebTarget | null;
  targets: WebTarget[];
  update: (() => void) | null;
}>(() => ({ account: null, target: null, targets: [], update: null }));

export const targetKey = (target: WebTarget) => `${target.kind}:${target.id}`;
export function webRequest<T>(path: string, body?: unknown): Promise<T> {
  return hostRequest(path, body) as Promise<T>;
}
