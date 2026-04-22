import React from "react";
import { getChannelLetterColor, getChannelLetter } from "./channelIcons";

interface ChannelIconProps {
  channelKey: string;
  size?: number;
}

/**
 * Renders a channel icon as an uppercase first-letter avatar
 * with a colored background.
 */
export const ChannelIcon: React.FC<ChannelIconProps> = ({
  channelKey,
  size = 32,
}) => {
  const backgroundColor = getChannelLetterColor(channelKey);
  const letter = getChannelLetter(channelKey);
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
      title={channelKey}
    >
      {letter}
    </div>
  );
};
