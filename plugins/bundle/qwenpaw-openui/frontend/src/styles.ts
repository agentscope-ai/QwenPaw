import { PLUGIN_ID } from "./host";
import { useInsertionEffect } from "react";
import componentStyles from "openui:styles";

let users = 0;
let style: HTMLStyleElement | undefined;

/** Release styles when the last UI unmounts, including plugin disposal. */
export function useOpenUIStyles() {
  useInsertionEffect(() => {
    if (users++ === 0) {
      style = document.createElement("style");
      style.dataset.qwenpawPlugin = PLUGIN_ID;
      style.textContent = componentStyles;
      document.head.appendChild(style);
    }
    return () => {
      if (--users === 0) {
        style?.remove();
        style = undefined;
      }
    };
  }, []);
}
