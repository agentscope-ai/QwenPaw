import React, { useEffect, useSyncExternalStore } from "react";
import type { ComponentType } from "react";
import { Form } from "@agentscope-ai/design";
import type { ToolConfigField } from "../api/modules/tools";
import { ConfigFields } from "../components/ConfigFields";
import type { Disposable } from "./registry/types";
import { getApiToken, getApiUrl } from "../api/config";

export interface HarnessSettingsProps {
  backendId: string;
  value: Record<string, unknown>;
  onChange(value: Record<string, unknown>): void;
  open: boolean;
}

export interface HarnessFrontendExtension {
  backendId: string;
  SettingsComponent?: ComponentType<HarnessSettingsProps>;
}

export interface HarnessBackendDescriptor {
  id: string;
  label: string;
  plugin_id: string | null;
  status: "available" | "disabled" | "failed";
  capabilities: Record<string, unknown>;
  config_fields: ToolConfigField[];
}

interface Registration {
  pluginId: string;
  extension: HarnessFrontendExtension;
  token: symbol;
}

class HarnessRegistry {
  private entries = new Map<string, Registration>();
  private catalog = new Map<string, HarnessBackendDescriptor>();
  private listeners = new Set<() => void>();
  private snapshot: HarnessBackendDescriptor[] = [];
  private catalogValid = false;
  private catalogRevision = 0;

  register(pluginId: string, extension: HarnessFrontendExtension): Disposable {
    const id = extension.backendId;
    if (id === "qwenpaw" || !/^[a-z][a-z0-9_-]*$/.test(id)) {
      throw new Error("Harness backendId is invalid or reserved");
    }
    const owner = this.catalogValid
      ? this.catalog.get(id)?.plugin_id
      : undefined;
    if (owner && owner !== pluginId)
      throw new Error(`Harness '${id}' belongs to '${owner}'`);
    const occupied = this.entries.get(id);
    if (occupied)
      throw new Error(
        `Harness '${id}' is registered by '${occupied.pluginId}'`,
      );
    const registration = {
      pluginId,
      extension: { ...extension },
      token: Symbol(id),
    };
    this.entries.set(id, registration);
    this.rebuild();
    return {
      dispose: () => {
        if (this.entries.get(id)?.token === registration.token) {
          this.entries.delete(id);
          this.rebuild();
        }
      },
    };
  }

  disposeAll(pluginId: string): void {
    for (const [id, entry] of this.entries)
      if (entry.pluginId === pluginId) this.entries.delete(id);
    this.rebuild();
  }

  syncCatalog(rows: HarnessBackendDescriptor[]): void {
    this.catalogRevision += 1;
    this.catalog = new Map(rows.map((row) => [row.id, row]));
    this.catalogValid = true;
    for (const [id, entry] of this.entries) {
      if (this.catalog.get(id)?.plugin_id !== entry.pluginId)
        this.entries.delete(id);
    }
    this.rebuild();
  }

  getSettings(backendId: string): HarnessFrontendExtension | undefined {
    if (!this.catalogValid) return undefined;
    const row = this.catalog.get(backendId);
    const entry = this.entries.get(backendId);
    return row?.status === "available" && row.plugin_id === entry?.pluginId
      ? entry.extension
      : undefined;
  }

  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };
  getSnapshot = () => this.snapshot;
  invalidateCatalog(): void {
    this.catalogRevision += 1;
    this.catalogValid = false;
    this.rebuild();
  }
  async refreshCatalog(): Promise<void> {
    const revision = ++this.catalogRevision;
    try {
      const token = getApiToken();
      const response = await fetch(getApiUrl("/agents/backends"), {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!response.ok)
        throw new Error(`Failed to load backend catalog (${response.status})`);
      const body = (await response.json()) as {
        backends: HarnessBackendDescriptor[];
      };
      if (revision === this.catalogRevision) this.syncCatalog(body.backends);
    } catch (error) {
      if (revision === this.catalogRevision) this.invalidateCatalog();
      throw error;
    }
  }
  private rebuild(): void {
    this.snapshot = this.catalogValid ? Array.from(this.catalog.values()) : [];
    this.listeners.forEach((listener) => listener());
  }
}

export const harnessRegistry = new HarnessRegistry();
export const harnessNamespace = {
  register: (
    pluginId: string,
    extension: HarnessFrontendExtension,
  ): Disposable => harnessRegistry.register(pluginId, extension),
};

export async function refreshHarnessCatalog(): Promise<void> {
  await harnessRegistry.refreshCatalog();
}

function SchemaSettings({
  value,
  onChange,
  configFields,
}: HarnessSettingsProps & { configFields: ToolConfigField[] }) {
  const [form] = Form.useForm();
  useEffect(() => form.setFieldsValue(value), [form, value]);
  return React.createElement(
    Form,
    {
      form,
      layout: "vertical",
      initialValues: value,
      onValuesChange: (changed: Record<string, unknown>) =>
        onChange({ ...value, ...changed }),
    },
    React.createElement(ConfigFields, { fields: configFields }),
  );
}

export function HarnessSettings({
  backendId,
  value,
  onChange,
  open,
  configFields,
}: HarnessSettingsProps & { configFields?: ToolConfigField[] }) {
  const rows = useSyncExternalStore(
    harnessRegistry.subscribe,
    harnessRegistry.getSnapshot,
    harnessRegistry.getSnapshot,
  );
  const descriptor = rows.find((row) => row.id === backendId);
  if (descriptor?.status !== "available") return null;
  const extension = harnessRegistry.getSettings(backendId);
  const props = { backendId, value, onChange, open };
  return extension?.SettingsComponent
    ? React.createElement(extension.SettingsComponent, {
        ...props,
        key: backendId,
      })
    : React.createElement(SchemaSettings, {
        ...props,
        key: backendId,
        configFields: configFields ?? descriptor.config_fields,
      });
}
