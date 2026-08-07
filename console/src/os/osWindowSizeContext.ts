/**
 * osWindowSizeContext.ts — Live content width of the enclosing OS window.
 *
 * WindowFrame publishes its content area width here so width-aware hooks
 * (useIsMobile) can respond to the window size instead of the viewport.
 * Outside the OS (classic layout) there is no provider and consumers fall
 * back to viewport-based behaviour.
 */
import { createContext } from "react";

/** Content width in px, or null when unknown / not inside an OS window. */
export const OsWindowSizeContext = createContext<number | null>(null);
