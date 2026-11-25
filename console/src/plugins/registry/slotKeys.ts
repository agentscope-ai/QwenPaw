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
  codeBlocks: "response.codeBlocks",
  approvalRenderers: "approval.renderers",
  requestPrepend: "request.prepend",
  requestAppend: "request.append",
  requestPayloadTransforms: "request.payloadTransforms",
  responsePrepend: "response.prepend",
  responseAppend: "response.append",
} as const;

export type ChatListField = (typeof ChatList)[keyof typeof ChatList];

/**
 * Theme token override keys, split by the SDK version that introduced them.
 *
 * Semantic roles from `styles/tokens.css`, WITHOUT the `--app-` prefix, so a
 * plugin writes `{ surface: { light, dark } }` instead of reaching into the
 * raw custom-property namespace. The set stays closed on purpose: only the
 * roles listed here may be overridden, so the remaining `--app-*` names stay
 * an implementation detail.
 *
 * `CORE` shipped with the first slice and needs no declaration. `EXTENDED`
 * arrived later, so a plugin that uses one has to declare the `themeTokens`
 * SDK capability (`src/qwenpaw/plugins/sdk_version.py`), which requires
 * `sdk.version >= 1.2.0`.
 */
export const CORE_THEME_TOKENS = {
  bg: "bg",
  surface: "surface",
  surfaceRaised: "surface-raised",
  border: "border",
  text: "text",
  textSecondary: "text-secondary",
} as const;

export const EXTENDED_THEME_TOKENS = {
  surfaceSubtle: "surface-subtle",
  surfaceSunken: "surface-sunken",
  shellBg: "shell-bg",
  textTertiary: "text-tertiary",
  textQuaternary: "text-quaternary",
  borderSubtle: "border-subtle",
  borderStrong: "border-strong",
  accent: "accent",
  accentHover: "accent-hover",
  accentActive: "accent-active",
  accentSoft: "accent-soft",
  accentSoftHover: "accent-soft-hover",
  accentFaint: "accent-faint",
  accentRing: "accent-ring",
  accentBorder: "accent-border",
  accentText: "accent-text",
  success: "success",
  successBg: "success-bg",
  successBorder: "success-border",
  successText: "success-text",
  warning: "warning",
  warningBg: "warning-bg",
  warningBorder: "warning-border",
  warningText: "warning-text",
  error: "error",
  errorBg: "error-bg",
  errorBorder: "error-border",
  errorText: "error-text",
  infoBg: "info-bg",
  infoBorder: "info-border",
  infoText: "info-text",
} as const;

export const ThemeTokens = {
  ...CORE_THEME_TOKENS,
  ...EXTENDED_THEME_TOKENS,
} as const;

export type ThemeTokenKey = (typeof ThemeTokens)[keyof typeof ThemeTokens];
