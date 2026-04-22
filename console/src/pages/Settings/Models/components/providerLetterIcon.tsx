import React from "react";

/** Predefined background colors for provider letter-avatar icons. */
const PROVIDER_LETTER_COLORS: Record<string, string> = {
  modelscope: "#6236FF",
  "aliyun-codingplan": "#FF6A00",
  "aliyun-codingplan-intl": "#FF6A00",
  deepseek: "#4D6BFE",
  gemini: "#4285F4",
  "azure-openai": "#0078D4",
  "kimi-cn": "#000000",
  "kimi-intl": "#000000",
  anthropic: "#D97757",
  ollama: "#1A1A1A",
  "minimax-cn": "#1A1A2E",
  minimax: "#1A1A2E",
  openai: "#10A37F",
  dashscope: "#6236FF",
  lmstudio: "#6C5CE7",
  "siliconflow-cn": "#5B5FC7",
  "siliconflow-intl": "#5B5FC7",
  "qwenpaw-local": "#FF7F16",
  "zhipu-cn": "#3366FF",
  "zhipu-intl": "#3366FF",
  "zhipu-cn-codingplan": "#3366FF",
  "zhipu-intl-codingplan": "#3366FF",
  openrouter: "#6366F1",
  opencode: "#2563EB",
};

/** A palette of fallback colors for providers without a predefined color. */
const FALLBACK_COLORS = [
  "#FF6B6B",
  "#4ECDC4",
  "#45B7D1",
  "#96CEB4",
  "#FFEAA7",
  "#DDA0DD",
  "#98D8C8",
  "#F7DC6F",
  "#BB8FCE",
  "#85C1E9",
  "#F0B27A",
  "#82E0AA",
];

/** Get the background color for a provider's letter-avatar icon. */
export function getProviderLetterColor(providerId: string): string {
  if (PROVIDER_LETTER_COLORS[providerId]) {
    return PROVIDER_LETTER_COLORS[providerId];
  }
  let hash = 0;
  for (let i = 0; i < providerId.length; i++) {
    hash = ((hash << 5) - hash + providerId.charCodeAt(i)) | 0;
  }
  return FALLBACK_COLORS[Math.abs(hash) % FALLBACK_COLORS.length];
}

/** Get the display letter for a provider's letter-avatar icon. */
export function getProviderLetter(providerId: string): string {
  return providerId.charAt(0).toUpperCase();
}

interface ProviderIconProps {
  providerId: string;
  size?: number;
}

/**
 * Renders a provider icon as an uppercase first-letter avatar
 * with a colored background.
 */
export const ProviderIcon: React.FC<ProviderIconProps> = ({
  providerId,
  size = 32,
}) => {
  const backgroundColor = getProviderLetterColor(providerId);
  const letter = getProviderLetter(providerId);
  const fontSize = size * 0.45;
  const borderRadius = size * 0.25;

  return (
    <div
      style={{
        width: size,
        height: size,
        borderRadius,
        backgroundColor,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        color: "#fff",
        fontSize,
        fontWeight: 600,
        fontFamily: "Inter, sans-serif",
        userSelect: "none",
        flexShrink: 0,
      }}
      title={providerId}
    >
      {letter}
    </div>
  );
};
