/** External product presentation. Internal protocol names remain unchanged. */
export const PRODUCT_NAME = "WeldonAgent" as const;
export const DOCUMENT_TITLE = PRODUCT_NAME;
export const ASSISTANT_NAME = PRODUCT_NAME;

/** Public builds do not expose upstream maintenance or version entry points. */
export const PUBLIC_MAINTENANCE_LINKS_ENABLED = false as const;
export const VERSION_BADGE_ENABLED = false as const;
export const DESKTOP_UPDATE_CHECK_ENABLED = false as const;
