import { createContext, useContext, type ReactNode } from "react";

import { UI_FONT_SIZE_DEFAULT } from "@/utils/uiFontSizePreference";

/**
 * Provides the effective console font size. The value is already OS-route
 * aware (the desktop shell falls back to the default), so host-rendered
 * Markdown and other consumers read this instead of the raw preference and
 * therefore honour the same fallback that the Ant Design token and the root
 * font-size use.
 */
const FontSizeContext = createContext<number>(UI_FONT_SIZE_DEFAULT);

export function FontSizeProvider({
  value,
  children,
}: {
  value: number;
  children: ReactNode;
}) {
  return (
    <FontSizeContext.Provider value={value}>
      {children}
    </FontSizeContext.Provider>
  );
}

export function useEffectiveFontSize(): number {
  return useContext(FontSizeContext);
}
