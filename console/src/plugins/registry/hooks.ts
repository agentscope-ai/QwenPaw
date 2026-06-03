/**
 * registry/hooks.ts — React subscriptions for Menu / Route / Slot registries.
 *
 * All hooks use useSyncExternalStore against the shared notify bus, so any
 * registration triggers a single render pass for the affected consumers.
 */
import { useSyncExternalStore } from "react";
import { menuRegistry, routeRegistry, slotRegistry, subscribe } from "./store";
import type { MenuItem, MenuLocation, SlotName } from "./types";

export function useMenuItems(location: MenuLocation): MenuItem[] {
  return useSyncExternalStore(subscribe, () => menuRegistry.snapshot(location));
}

export function useAllMenuItems(): MenuItem[] {
  return useSyncExternalStore(subscribe, () => menuRegistry.snapshot());
}

export function useRoutes(): ReturnType<typeof routeRegistry.snapshot> {
  return useSyncExternalStore(subscribe, () => routeRegistry.snapshot());
}

export function useSlotEntries(name: SlotName) {
  return useSyncExternalStore(subscribe, () => slotRegistry.snapshot(name));
}
