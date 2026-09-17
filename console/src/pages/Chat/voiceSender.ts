/** Resolve a voice control within its owning Chat container. */
export function findVoiceSender(
  root: HTMLElement | null,
  anchor: HTMLElement | null,
): HTMLTextAreaElement | null {
  if (!root || !anchor || !root.contains(anchor)) return null;
  const senderRoot = anchor.closest<HTMLElement>("[data-sender-root]");
  if (!senderRoot || !root.contains(senderRoot)) return null;
  return senderRoot.querySelector<HTMLTextAreaElement>("textarea");
}
