/**
 * registry/slotKeys.ts — single source of truth for chat slot field names.
 *
 * All string literals used as keys into chatExtensions (setScalar / addToList /
 * snapshot / audit) live here. The `ChatScalarField` / `ChatListField` union
 * types are derived from these objects, so adding a new slot is one entry.
 *
 * ── How to add a new slot ────────────────────────────────────────────────────
 * 1. Add the entry to `ChatScalar` or `ChatList` below.
 * 2. Add the corresponding value-type to `ChatScalarValues` in types.ts.
 * 3. Add the snapshot entry to `ChatScalarSnapshot` (scalar) or
 *    `ChatListSnapshot` (list) in chatExtensions.ts. TypeScript will flag
 *    mismatches in chatExtensions.ts at compile time.
 * 4. Expose via the plugin API in hostSdk/install.ts.
 * 5. Read & merge in pages/Chat/index.tsx options useMemo.
 *
 * Field strings follow `domain.field` dotted naming so they read naturally
 * in audit logs and developer tools (e.g. `welcome.greeting`, not `wg`).
 * ─────────────────────────────────────────────────────────────────────────────
 */

/** Scalar (last-writer-wins) slot keys. */
export const ChatScalar = {
  welcomeGreeting: "welcome.greeting",
  welcomeDescription: "welcome.description",
  welcomeAvatar: "welcome.avatar",
  welcomeNick: "welcome.nick",
  welcomePrompts: "welcome.prompts",
  welcomeRender: "welcome.render",
  headerLeftTitle: "header.leftTitle",
  headerLeftLogo: "header.leftLogo",
  headerLeftHeaderRender: "header.leftHeader.render",
  themeColorPrimary: "theme.colorPrimary",
  senderPlaceholder: "sender.placeholder",
  senderDisclaimer: "sender.disclaimer",
  requestRender: "request.render",
  responseRender: "response.render",
} as const;

export type ChatScalarField = (typeof ChatScalar)[keyof typeof ChatScalar];

/** Additive list slot keys. */
export const ChatList = {
  rightHeader: "header.rightHeader",
  senderPrefix: "sender.prefix",
  senderSuggestions: "sender.suggestions",
  actions: "actions",
  requestActions: "requestActions",
  cards: "cards",
  customToolRender: "customToolRender",
  requestPrepend: "request.prepend",
  requestAppend: "request.append",
  responsePrepend: "response.prepend",
  responseAppend: "response.append",
} as const;

export type ChatListField = (typeof ChatList)[keyof typeof ChatList];
