import type {
  ComposerSnapshot,
  ModelSelection,
  Disposable,
} from "../types/qwenpaw";

type Scope = Omit<ComposerSnapshot, "text" | "revision">;
interface Binding {
  element(): HTMLTextAreaElement | null;
  scope(): Scope | null;
  write(text: string): void;
  model(): Promise<ModelSelection | null>;
}
let active: Binding | undefined;
let revision = 0;
let last = "";
const issued = new WeakMap<
  ComposerSnapshot,
  { binding: Binding; element: HTMLTextAreaElement }
>();

/** Only the visible host composer binds; old cleanup cannot remove a new one. */
export function bindChatComposer(binding: Binding): Disposable {
  active = binding;
  revision++;
  const changed = (event: Event) => {
    if (
      active === binding &&
      (event.type !== "input" || event.target === binding.element())
    )
      revision++;
  };
  const rotated = (event: Event) => {
    const scope = binding.scope();
    const agentId = (event as CustomEvent<{ agentId?: string }>).detail
      ?.agentId;
    if (active === binding && (!scope || scope.agentId === (agentId ?? "")))
      revision++;
  };
  document.addEventListener("input", changed, true);
  window.addEventListener("qwenpaw:pending-composer-rotated", rotated);
  window.addEventListener("session-model-changed", changed);
  window.addEventListener("model-switched", changed);
  return {
    dispose() {
      document.removeEventListener("input", changed, true);
      window.removeEventListener("qwenpaw:pending-composer-rotated", rotated);
      window.removeEventListener("session-model-changed", changed);
      window.removeEventListener("model-switched", changed);
      if (active === binding) {
        active = undefined;
        revision++;
      }
    },
  };
}

function read(): ComposerSnapshot | null {
  const binding = active;
  const scope = binding?.scope();
  const element = binding?.element();
  if (!binding || !scope || !element || !element.isConnected) return null;
  const text = element.value;
  const value = JSON.stringify([
    scope.agentId,
    scope.sessionId,
    scope.chatId,
    text,
  ]);
  if (value !== last) {
    last = value;
    revision++;
  }
  const snapshot = Object.freeze({ ...scope, text, revision });
  issued.set(snapshot, { binding, element });
  return snapshot;
}

function matches(snapshot: ComposerSnapshot): boolean {
  const owner = issued.get(snapshot);
  const current = read();
  return (
    !!owner &&
    owner.binding === active &&
    owner.element === active?.element() &&
    current?.revision === snapshot.revision
  );
}

export const composer = {
  read,
  replace(snapshot: ComposerSnapshot, text: string): boolean {
    if (typeof text !== "string" || !matches(snapshot)) return false;
    revision++; // One successful replacement consumes every older snapshot.
    active!.write(text);
    return true;
  },
  async model(): Promise<ModelSelection | null> {
    const snapshot = read();
    if (!snapshot) return null;
    const model = await active!.model();
    return matches(snapshot) ? model : null;
  },
};
