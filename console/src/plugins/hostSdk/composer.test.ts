import { afterEach, describe, expect, it } from "vitest";
import { bindChatComposer, composer } from "./composer";
import { setTextareaValue } from "../../pages/Chat/utils";
import { rotatePendingComposer } from "../../pages/Chat/chatInputDraft";
import type {
  ComposerSnapshot,
  Disposable,
  ModelSelection,
} from "../types/qwenpaw";

const bindings: Disposable[] = [];
afterEach(() => {
  bindings.splice(0).forEach((binding) => binding.dispose());
  document.body.replaceChildren();
  sessionStorage.clear();
});

function setup(
  model = async (): Promise<ModelSelection | null> => ({
    provider_id: "p",
    model_id: "m",
  }),
) {
  const element = document.createElement("textarea");
  document.body.append(element);
  const state = { agentId: "a", sessionId: "s", chatId: "c", ready: true };
  const binding = bindChatComposer({
    element: () => element,
    scope: () =>
      state.ready
        ? {
            agentId: state.agentId,
            sessionId: state.sessionId,
            chatId: state.chatId,
          }
        : null,
    write: (text) => setTextareaValue(element, text),
    model,
  });
  bindings.push(binding);
  setTextareaValue(element, "original");
  return { element, state, binding };
}

function read(): ComposerSnapshot {
  const result = composer.read();
  if (!result) throw new Error("Expected the active composer");
  return result;
}

describe("host-owned composer snapshots", () => {
  it.each(["", "new"])(
    "invalidates a rotated blank session (%s) even when scope and text match",
    (sessionId) => {
      const { element, state } = setup();
      state.sessionId = sessionId;
      state.chatId = "";
      const previous = read();
      rotatePendingComposer("another-agent");
      expect(read().revision).toBe(previous.revision);
      rotatePendingComposer(state.agentId);
      expect(composer.replace(previous, "old async result")).toBe(false);
      expect(element.value).toBe("original");
      expect(composer.replace(read(), "current result")).toBe(true);
      expect(element.value).toBe("current result");
    },
  );

  it("discards a model lookup when the pending composer rotates", async () => {
    let resolve!: (model: ModelSelection) => void;
    const { state } = setup(() => new Promise((done) => (resolve = done)));
    state.sessionId = state.chatId = "";
    const pending = composer.model();
    rotatePendingComposer(state.agentId);
    resolve({ provider_id: "p", model_id: "old" });
    expect(await pending).toBeNull();
  });

  it("replaces once, updates the real input and refuses forged or reused snapshots", () => {
    const { element } = setup();
    const snapshot = read();
    expect(Object.isFrozen(snapshot)).toBe(true);
    expect(composer.replace({ ...snapshot }, "forged")).toBe(false);
    expect(composer.replace(snapshot, "improved")).toBe(true);
    expect(element.value).toBe("improved");
    expect(composer.replace(snapshot, "stale")).toBe(false);
    expect(element.value).toBe("improved");
  });

  it("rejects results after typing, undoing, scope changes and disabled input", () => {
    const { element, state } = setup();
    const snapshot = read();
    setTextareaValue(element, "new");
    setTextareaValue(element, "original");
    expect(composer.replace(snapshot, "old result")).toBe(false);
    const current = read();
    state.sessionId = "other";
    expect(composer.replace(current, "wrong session")).toBe(false);
    state.sessionId = "s";
    expect(composer.replace(current, "returned session")).toBe(false);
    state.ready = false;
    expect(composer.read()).toBeNull();
    expect(composer.replace(current, "disabled")).toBe(false);
    expect(element.value).toBe("original");
  });

  it("invalidates old bindings and does not let their cleanup remove a newer one", () => {
    const first = setup();
    const snapshot = read();
    const second = setup();
    first.binding.dispose();
    expect(composer.replace(snapshot, "old result")).toBe(false);
    expect(composer.replace(read(), "second result")).toBe(true);
    expect(second.element.value).toBe("second result");
    second.binding.dispose();
    expect(composer.read()).toBeNull();
  });

  it("uses the selected model but discards a lookup if the model or draft changes", async () => {
    let resolve!: (model: ModelSelection) => void;
    setup(
      () =>
        new Promise((done) => {
          resolve = done;
        }),
    );
    const pending = composer.model();
    window.dispatchEvent(new Event("session-model-changed"));
    resolve({ provider_id: "p", model_id: "old" });
    expect(await pending).toBeNull();
    const ready = composer.model();
    resolve({ provider_id: "p", model_id: "selected" });
    expect(await ready).toEqual({ provider_id: "p", model_id: "selected" });
  });
});
