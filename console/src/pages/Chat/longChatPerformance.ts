/**
 * Keep user-message navigation available in long chats while using the
 * lighter navigator variant. Unlike the minimap, navigator mode does not
 * calculate and observe a position for every rendered bubble.
 */
export const LONG_CHAT_USER_MESSAGE_ANCHORS = {
  enabled: true,
  variant: "navigator",
} as const;
