import React, { useState } from "react";
import {
  getChannelIconUrl,
  getChannelLetterColor,
  getChannelLetter,
} from "./channelIcons";

interface ChannelIconProps {
  channelKey: string;
  size?: number;
}

/**
 * Renders a channel icon: tries to load the CDN image first,
 * falls back to an uppercase first-letter avatar on error.
 */
export const ChannelIcon: React.FC<ChannelIconProps> = ({
  channelKey,
  size = 32,
}) => {
  const imageUrl = getChannelIconUrl(channelKey);
  const [imageFailed, setImageFailed] = useState(false);

  const borderRadius = size * 0.25;

  if (imageUrl && !imageFailed) {
    return (
      <img
        src={imageUrl}
        alt={channelKey}
        width={size}
        height={size}
        style={{ borderRadius, objectFit: "cover", flexShrink: 0 }}
        onError={() => setImageFailed(true)}
      />
    );
  }

  const backgroundColor = getChannelLetterColor(channelKey);
  const letter = getChannelLetter(channelKey);
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
      title={channelKey}
    >
      {letter}
    </div>
  );
};
