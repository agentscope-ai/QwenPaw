import React, { useState } from "react";
import { providerIcon } from "./providerIcon";
import {
  getProviderLetterColor,
  getProviderLetter,
} from "./providerLetterIcon";

/** The default fallback URL returned by providerIcon() for unknown providers. */
const DEFAULT_FALLBACK_URL =
  "https://gw.alicdn.com/imgextra/i4/O1CN01IWnlOw1lebfpiFrIL_!!6000000004844-0-tps-100-100.jpg";

interface ProviderIconProps {
  providerId: string;
  size?: number;
}

/**
 * Renders a provider icon: tries to load the CDN image first,
 * falls back to an uppercase first-letter avatar on error or for unknown providers.
 */
export const ProviderIcon: React.FC<ProviderIconProps> = ({
  providerId,
  size = 32,
}) => {
  const rawUrl = providerIcon(providerId);
  const imageUrl = rawUrl === DEFAULT_FALLBACK_URL ? undefined : rawUrl;
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
