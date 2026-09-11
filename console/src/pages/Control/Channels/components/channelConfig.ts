import type { ChannelKey } from "./constants";

export function keepConsoleEnabled(
  channelKey: ChannelKey,
  config: Record<string, unknown>,
): Record<string, unknown> {
  if (channelKey !== "console") return config;
  return { ...config, enabled: true };
}
