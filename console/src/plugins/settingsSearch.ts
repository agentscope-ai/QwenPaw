import { useSyncExternalStore } from "react";
import type { Disposable, Localized } from "./registry/types";

export interface SettingsSearchTarget {
  page: string;
  label: string;
  tab?: string;
  targetId?: string;
  tabId?: string;
  surface?: string;
  query?: Record<string, string>;
  hint?: string;
  channelKey?: string;
  agentId?: string | null;
}

export interface SettingsSearchItem {
  id: string;
  routeId: string;
  label: Localized<string>;
  groupPath?: Localized<string[]>;
  keywords?: Localized<string[]>;
  description?: Localized<string>;
  target: Omit<SettingsSearchTarget, "page" | "label" | "agentId"> & {
    targetId: string;
  };
  availability?: Localized<{ available: boolean; reason?: string }>;
}

export interface SettingsSearchNamespace {
  register(pluginId: string, items: SettingsSearchItem[]): Disposable;
}

interface Registration {
  pluginId: string;
  item: SettingsSearchItem;
  token: symbol;
}

class SettingsSearchRegistry implements SettingsSearchNamespace {
  private entries = new Map<string, Registration>();
  private snapshot: Registration[] = [];
  private listeners = new Set<() => void>();

  private notify() {
    this.snapshot = [...this.entries.values()];
    this.listeners.forEach((listener) => listener());
  }

  register(pluginId: string, items: SettingsSearchItem[]): Disposable {
    const token = Symbol(pluginId);
    for (const item of items) {
      const key = JSON.stringify([pluginId, item.id]);
      this.entries.set(key, { pluginId, item, token });
    }
    this.notify();
    return {
      dispose: () => {
        let changed = false;
        for (const [key, entry] of this.entries) {
          if (entry.token !== token) continue;
          this.entries.delete(key);
          changed = true;
        }
        if (changed) this.notify();
      },
    };
  }

  removeBySource(pluginId: string) {
    let changed = false;
    for (const [key, entry] of this.entries) {
      if (entry.pluginId !== pluginId) continue;
      this.entries.delete(key);
      changed = true;
    }
    if (changed) this.notify();
  }

  getSnapshot = () => this.snapshot;
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };
}

export const settingsSearchRegistry = new SettingsSearchRegistry();
export const settingsSearchNamespace: SettingsSearchNamespace = {
  register: (pluginId, items) =>
    settingsSearchRegistry.register(pluginId, items),
};

export function usePluginSettingsSearch() {
  return useSyncExternalStore(
    settingsSearchRegistry.subscribe,
    settingsSearchRegistry.getSnapshot,
  );
}
