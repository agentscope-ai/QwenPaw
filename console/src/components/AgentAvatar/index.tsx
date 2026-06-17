import { RobotOutlined } from "@ant-design/icons";
import { getApiUrl } from "../../api/config";

interface AgentAvatarProps {
  avatarUrl?: string;
  size?: number;
  opacity?: number;
}

/**
 * Renders an agent avatar image or a fallback robot icon.
 * Automatically wraps avatar_url with the API prefix.
 */
export function AgentAvatar({
  avatarUrl,
  size = 24,
  opacity = 1,
}: AgentAvatarProps) {
  if (avatarUrl) {
    return (
      <img
        src={getApiUrl(avatarUrl)}
        alt=""
        style={{
          width: size,
          height: size,
          borderRadius: "50%",
          objectFit: "cover",
          opacity,
          flexShrink: 0,
        }}
      />
    );
  }

  return (
    <RobotOutlined
      style={{
        fontSize: size * 0.67,
        opacity: opacity * 0.85,
        flexShrink: 0,
      }}
    />
  );
}
