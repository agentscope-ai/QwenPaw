/**
 * The vendor navigator scans all messages and measures rendered bubbles on
 * every streaming update. Disable it until anchors can update independently
 * from the response stream.
 */
export const LONG_CHAT_USER_MESSAGE_ANCHORS = {
  enabled: false,
  variant: "navigator",
} as const;
