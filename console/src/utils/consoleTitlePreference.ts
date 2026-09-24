import { useSyncExternalStore } from "react";

export const DEFAULT_CONSOLE_TITLE = "QwenPaw Console";
const STORAGE_KEY = "qwenpaw_console_title";
const CHANGE_EVENT = "qwenpaw:console-title-change";

function getConsoleTitlePreference(): string {
  try {
    return localStorage.getItem(STORAGE_KEY) ?? "";
  } catch {
    return "";
  }
}

export function setConsoleTitlePreference(title: string): void {
  // Let the caller report a failed write instead of showing an unsaved value.
  if (title) localStorage.setItem(STORAGE_KEY, title);
  else localStorage.removeItem(STORAGE_KEY);
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

function subscribe(onChange: () => void): () => void {
  const onStorage = (event: StorageEvent) => {
    if (
      event.storageArea === localStorage &&
      (event.key === STORAGE_KEY || event.key === null)
    ) {
      onChange();
    }
  };
  window.addEventListener(CHANGE_EVENT, onChange);
  window.addEventListener("storage", onStorage);
  return () => {
    window.removeEventListener(CHANGE_EVENT, onChange);
    window.removeEventListener("storage", onStorage);
  };
}

export function useConsoleTitlePreference(): string {
  return useSyncExternalStore(subscribe, getConsoleTitlePreference, () => "");
}
