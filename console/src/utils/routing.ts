export interface RoutingSlotLike {
  provider_id?: string;
  model?: string;
}

export function hasConfiguredRoutingSlot<T extends RoutingSlotLike>(
  slot?: T | null,
): slot is T & { provider_id: string; model: string } {
  return Boolean(slot?.provider_id && slot?.model);
}

export function isLoopbackBaseUrl(baseUrl?: string): boolean {
  if (!baseUrl) return false;
  try {
    const url = new URL(baseUrl);
    return ["127.0.0.1", "localhost", "::1"].includes(url.hostname);
  } catch {
    return false;
  }
}
