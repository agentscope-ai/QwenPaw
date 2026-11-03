const PLUGIN_CHANGE_EVENT = "qwenpaw:plugins-changed";

export function notifyPluginChange(): void {
  window.dispatchEvent(new Event(PLUGIN_CHANGE_EVENT));
}

export function subscribeToPluginChanges(listener: () => void): () => void {
  window.addEventListener(PLUGIN_CHANGE_EVENT, listener);
  return () => window.removeEventListener(PLUGIN_CHANGE_EVENT, listener);
}
