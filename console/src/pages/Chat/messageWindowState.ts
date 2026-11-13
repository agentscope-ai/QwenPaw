import { createContext } from "react";

export interface MessageWindowState {
  heights: Map<string, Map<string, number>>;
  expanded: Map<string, boolean>;
}

export const MessageWindowStateContext =
  createContext<MessageWindowState | null>(null);

export function createMessageWindowState(): MessageWindowState {
  return { heights: new Map(), expanded: new Map() };
}
