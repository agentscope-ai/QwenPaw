/**
 * Tiny signal channel between the API client and the backend-health store.
 *
 * The client is imported by the store, so it must not import the store back
 * (circular ESM). This module carries the only fact the client reports: a
 * response proved the Creator backend is (not) reachable.
 */

type Listener = (available: boolean) => void;

let available = true;
const listeners = new Set<Listener>();

export function reportBackendAvailable(): void {
  if (available) return;
  available = true;
  listeners.forEach((listener) => listener(true));
}

export function reportBackendUnavailable(): void {
  if (!available) return;
  available = false;
  listeners.forEach((listener) => listener(false));
}

export function backendAvailable(): boolean {
  return available;
}

export function subscribeBackendHealth(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
