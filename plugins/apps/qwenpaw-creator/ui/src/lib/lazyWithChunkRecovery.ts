const CHUNK_RELOAD_KEY = "qwenpaw-creator:chunk-reload-attempted";

const CHUNK_LOAD_ERROR =
  /(?:failed to fetch dynamically imported module|error loading dynamically imported module|importing a module script failed)/i;

type StorageLike = Pick<Storage, "getItem" | "setItem" | "removeItem">;

export interface ChunkRecoveryOptions {
  storage?: StorageLike | null;
  reload?: () => void;
}

export function isChunkLoadError(error: unknown): boolean {
  return error instanceof Error && CHUNK_LOAD_ERROR.test(error.message);
}

function browserStorage(): StorageLike | null {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

function reloadCreatorDocument(): void {
  const url = new URL(window.location.href);
  url.searchParams.set("__creator_reload", Date.now().toString(36));
  window.location.replace(url.toString());
}

export async function loadWithChunkRecovery<T>(
  loader: () => Promise<T>,
  options: ChunkRecoveryOptions = {},
): Promise<T> {
  const storage =
    options.storage === undefined ? browserStorage() : options.storage;
  try {
    const loaded = await loader();
    try {
      storage?.removeItem(CHUNK_RELOAD_KEY);
    } catch {
      // Storage policy must not turn a successful module import into a failure.
    }
    return loaded;
  } catch (error) {
    if (!isChunkLoadError(error) || storage === null) throw error;
    try {
      if (storage.getItem(CHUNK_RELOAD_KEY) !== "1") {
        storage.setItem(CHUNK_RELOAD_KEY, "1");
        (options.reload ?? reloadCreatorDocument)();
      }
    } catch {
      // Without a durable one-shot guard, reloading could loop forever.
    }
    throw error;
  }
}
