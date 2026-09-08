import type { ComponentType } from "react";
import { useEffect, useSyncExternalStore } from "react";
import api from "../api";

export interface MemoryBackendExtension {
  id: string;
  label: string;
  configPath?: string[];
  tabKey?: string;
  ConfigComponent?: ComponentType;
  source?: string;
  available?: boolean;
}

export interface MemoryBackendNamespace {
  register(
    pluginId: string,
    extension: MemoryBackendExtension,
  ): { dispose(): void };
}

class MemoryBackendRegistry {
  private entries = new Map<string, MemoryBackendExtension>();
  private listeners = new Set<() => void>();
  private snapshot: MemoryBackendExtension[] = [];

  constructor() {
    this.entries.set("remelight", {
      id: "remelight",
      label: "ReMe Light",
      configPath: ["reme_light_memory_config"],
      tabKey: "remeLightMemory",
      source: "core",
      available: true,
    });
    this.entries.set("none", {
      id: "none",
      label: "none (disabled)",
      source: "core",
      available: true,
    });
    this.rebuild();
  }

  register(pluginId: string, extension: MemoryBackendExtension) {
    const id = extension.id.trim().toLowerCase();
    const existing = this.entries.get(id);
    if (existing?.source && existing.source !== `plugin:${pluginId}`) {
      throw new Error(
        `Memory backend '${id}' is already registered by ${existing.source}`,
      );
    }
    const entry = {
      ...extension,
      id,
      source: `plugin:${pluginId}`,
      available: extension.available ?? true,
    };
    this.entries.set(id, entry);
    this.rebuild();
    return {
      dispose: () => {
        if (this.entries.get(id) === entry) {
          this.entries.delete(id);
          this.rebuild();
        }
      },
    };
  }

  syncAvailable(items: MemoryBackendExtension[]): void {
    const availableIds = new Set(
      items.map((item) => item.id.trim().toLowerCase()),
    );
    let changed = false;
    for (const [id, entry] of this.entries) {
      if (!entry.source?.startsWith("plugin:")) continue;
      const available = availableIds.has(id);
      if (entry.available !== available) {
        this.entries.set(id, { ...entry, available });
        changed = true;
      }
    }
    for (const item of items) {
      const id = item.id.trim().toLowerCase();
      const existing = this.entries.get(id);
      if (existing) {
        if (existing.available !== item.available) {
          this.entries.set(id, { ...existing, available: item.available });
          changed = true;
        }
      } else {
        this.entries.set(id, {
          ...item,
          id,
          available: item.available ?? true,
        });
        changed = true;
      }
    }
    if (changed) this.rebuild();
  }

  removeBySource(pluginId: string): void {
    let changed = false;
    for (const [id, entry] of this.entries) {
      if (entry.source === `plugin:${pluginId}`) {
        this.entries.delete(id);
        changed = true;
      }
    }
    if (changed) this.rebuild();
  }

  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  getSnapshot = () => this.snapshot;

  private rebuild(): void {
    this.snapshot = Array.from(this.entries.values());
    this.listeners.forEach((listener) => listener());
  }
}

export const memoryBackendRegistry = new MemoryBackendRegistry();

export const memoryBackendNamespace: MemoryBackendNamespace = {
  register: (pluginId, extension) =>
    memoryBackendRegistry.register(pluginId, extension),
};

export function useMemoryBackends(): MemoryBackendExtension[] {
  const entries = useSyncExternalStore(
    memoryBackendRegistry.subscribe,
    memoryBackendRegistry.getSnapshot,
    memoryBackendRegistry.getSnapshot,
  );
  useEffect(() => {
    api
      .listMemoryBackends()
      .then((items) => memoryBackendRegistry.syncAvailable(items))
      .catch(() => {});
  }, []);
  return entries;
}
