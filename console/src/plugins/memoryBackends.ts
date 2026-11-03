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
  private registrations = new Map<string, symbol>();
  private availability?: Map<string, boolean>;
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
      available: this.availability
        ? this.availability.get(id) ?? false
        : extension.available ?? true,
    };
    // Availability updates replace entry objects; ownership must survive them.
    const registration = Symbol(id);
    this.registrations.set(id, registration);
    this.entries.set(id, entry);
    this.rebuild();
    return {
      dispose: () => {
        if (this.registrations.get(id) === registration) {
          this.registrations.delete(id);
          this.entries.delete(id);
          this.rebuild();
        }
      },
    };
  }

  syncAvailable(items: MemoryBackendExtension[]): void {
    this.availability = new Map(
      items.map((item) => [
        item.id.trim().toLowerCase(),
        item.available ?? true,
      ]),
    );
    let changed = false;
    for (const [id, entry] of this.entries) {
      if (!entry.source?.startsWith("plugin:")) continue;
      const available = this.availability.get(id) ?? false;
      if (entry.available !== available) {
        this.entries.set(id, { ...entry, available });
        changed = true;
      }
    }
    for (const item of items) {
      const id = item.id.trim().toLowerCase();
      const existing = this.entries.get(id);
      const available = item.available ?? true;
      if (existing) {
        if (existing.available !== available) {
          this.entries.set(id, { ...existing, available });
          changed = true;
        }
      } else {
        this.entries.set(id, {
          ...item,
          id,
          available,
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
        this.registrations.delete(id);
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
