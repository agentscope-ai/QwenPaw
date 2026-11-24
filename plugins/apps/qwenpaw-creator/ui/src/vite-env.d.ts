/// <reference types="vite/client" />

/**
 * Creator plugin version, injected from plugin.json by vite.config.ts.
 * Guarded at the use site so a bare test runner that skips the config still
 * renders instead of throwing a ReferenceError.
 */
declare const __CREATOR_VERSION__: string;
