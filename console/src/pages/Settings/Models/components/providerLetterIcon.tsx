import React, { useState } from "react";

/** CDN URLs for provider logos — used as primary icon with letter-avatar fallback. */
const PROVIDER_ICON_URLS: Record<string, string> = {
  modelscope:
    "https://gw.alicdn.com/imgextra/i4/O1CN01exenB61EAwhgY4pmA_!!6000000000312-2-tps-400-400.png",
  "aliyun-codingplan":
    "https://gw.alicdn.com/imgextra/i4/O1CN01nEmGhQ1we71GXW6eo_!!6000000006332-2-tps-400-400.png",
  "aliyun-codingplan-intl":
    "https://gw.alicdn.com/imgextra/i4/O1CN01nEmGhQ1we71GXW6eo_!!6000000006332-2-tps-400-400.png",
  deepseek:
    "https://gw.alicdn.com/imgextra/i4/O1CN01YfmXc81ogO3pR0aW8_!!6000000005254-2-tps-400-400.png",
  gemini:
    "https://gw.alicdn.com/imgextra/i2/O1CN01pDWy7z25caEvmJ3u1_!!6000000007547-2-tps-400-400.png",
  "azure-openai":
    "https://gw.alicdn.com/imgextra/i2/O1CN01R42n1y1hQAjCEiVlB_!!6000000004271-2-tps-400-400.png",
  "kimi-cn":
    "https://gw.alicdn.com/imgextra/i1/O1CN01xCKAr81Yz8Q9pXh1u_!!6000000003129-2-tps-400-400.png",
  "kimi-intl":
    "https://gw.alicdn.com/imgextra/i1/O1CN01xCKAr81Yz8Q9pXh1u_!!6000000003129-2-tps-400-400.png",
  anthropic:
    "https://gw.alicdn.com/imgextra/i2/O1CN014LwvBJ1tNDYvc3FfA_!!6000000005889-2-tps-400-400.png",
  ollama:
    "https://gw.alicdn.com/imgextra/i3/O1CN01xZeNJ01R0Ufb3nqqb_!!6000000002049-2-tps-400-400.png",
  "minimax-cn":
    "https://gw.alicdn.com/imgextra/i1/O1CN01B0FaVn1VzBcO4nF1C_!!6000000002723-2-tps-400-400.png",
  minimax:
    "https://gw.alicdn.com/imgextra/i1/O1CN01B0FaVn1VzBcO4nF1C_!!6000000002723-2-tps-400-400.png",
  openai:
    "https://gw.alicdn.com/imgextra/i3/O1CN01rQSexq1D7S4AYstKh_!!6000000000169-2-tps-400-400.png",
  dashscope:
    "https://gw.alicdn.com/imgextra/i4/O1CN01aDHDeq1mgj7gbRkhi_!!6000000004984-2-tps-400-400.png",
  lmstudio:
    "https://gw.alicdn.com/imgextra/i4/O1CN01Abv67y1jHaXLqikIJ_!!6000000004523-2-tps-200-200.png",
  "siliconflow-cn":
    "https://img.alicdn.com/imgextra/i1/O1CN01TUkzVC1clAoPa2ix8_!!6000000003640-2-tps-520-520.png",
  "siliconflow-intl":
    "https://img.alicdn.com/imgextra/i1/O1CN01TUkzVC1clAoPa2ix8_!!6000000003640-2-tps-520-520.png",
  "qwenpaw-local": "/qwenpaw.png",
  "zhipu-cn":
    "https://img.alicdn.com/imgextra/i2/O1CN01TFZcQz23xX7qacIEv_!!6000000007322-2-tps-640-640.png",
  "zhipu-intl":
    "https://img.alicdn.com/imgextra/i2/O1CN01TFZcQz23xX7qacIEv_!!6000000007322-2-tps-640-640.png",
  "zhipu-cn-codingplan":
    "https://img.alicdn.com/imgextra/i2/O1CN01TFZcQz23xX7qacIEv_!!6000000007322-2-tps-640-640.png",
  "zhipu-intl-codingplan":
    "https://img.alicdn.com/imgextra/i2/O1CN01TFZcQz23xX7qacIEv_!!6000000007322-2-tps-640-640.png",
  openrouter:
    "https://gw.alicdn.com/imgextra/i4/O1CN01oX74jS1ciQR9xBtZ2_!!6000000003634-2-tps-252-252.png",
  opencode:
    "https://gw.alicdn.com/imgextra/i1/O1CN01d3RfoB28G5dbN4i97_!!6000000007904-2-tps-30-30.png",
};

/** Get the CDN icon URL for a provider, or undefined if none exists. */
function getProviderIconUrl(providerId: string): string | undefined {
  return PROVIDER_ICON_URLS[providerId];
}

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
 * Renders a provider icon: tries to load the CDN image first,
 * falls back to an uppercase first-letter avatar on error.
 */
export const ProviderIcon: React.FC<ProviderIconProps> = ({
  providerId,
  size = 32,
}) => {
  const imageUrl = getProviderIconUrl(providerId);
  const [imageFailed, setImageFailed] = useState(false);

  const borderRadius = size * 0.25;

  if (imageUrl && !imageFailed) {
    return (
      <img
        src={imageUrl}
        alt={providerId}
        width={size}
        height={size}
        style={{ borderRadius, objectFit: "cover", flexShrink: 0 }}
        onError={() => setImageFailed(true)}
      />
    );
  }

  const backgroundColor = getProviderLetterColor(providerId);
  const letter = getProviderLetter(providerId);
  const fontSize = size * 0.45;

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
