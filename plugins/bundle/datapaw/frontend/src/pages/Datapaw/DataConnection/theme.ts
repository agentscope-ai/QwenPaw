/** DataPaw data-connection pages brand primary (light + dark base). */
export const DATA_CONNECTION_PRIMARY = "#4c4bdb";

export const DATA_CONNECTION_THEME_TOKENS = {
  light: {
    colorPrimary: DATA_CONNECTION_PRIMARY,
    colorLink: DATA_CONNECTION_PRIMARY,
    colorPrimaryHover: "#5e5ee8",
    colorPrimaryActive: "#3a3ab0",
    colorTextLightSolid: "#ffffff",
    colorText: "rgba(0, 0, 0, 0.88)",
    colorTextSecondary: "rgba(0, 0, 0, 0.65)",
  },
  dark: {
    colorPrimary: DATA_CONNECTION_PRIMARY,
    colorLink: DATA_CONNECTION_PRIMARY,
    colorPrimaryHover: "#6d6cf0",
    colorPrimaryActive: "#4342c8",
    colorTextLightSolid: "#ffffff",
    colorText: "rgba(255, 255, 255, 0.85)",
    colorTextSecondary: "rgba(255, 255, 255, 0.65)",
  },
} as const;
