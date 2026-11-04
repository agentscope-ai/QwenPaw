import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";

/** Subscribe before consuming activations queued while the console was loading. */
export async function subscribeNativeActivation<T>(
  kind: "approval" | "event",
  eventName: string,
  onTarget: (target: T) => void,
): Promise<() => void> {
  let active = true;
  const consume = () => {
    void invoke<{ target: T } | null>("take_notification_target", { kind })
      .then((pending) => {
        if (active && pending) onTarget(pending.target);
      })
      .catch(console.warn);
  };
  const unlisten = await listen(eventName, consume);
  consume();
  return () => {
    active = false;
    unlisten();
  };
}
