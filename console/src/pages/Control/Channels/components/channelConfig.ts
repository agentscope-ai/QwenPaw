import type { ChannelKey } from "./constants";
import type { ChannelSaveJob } from "../../../../api/modules/channel";

export function captureChannelSaveJob(job: ChannelSaveJob): ChannelSaveJob {
  const copy = structuredClone(job);
  const freeze = (value: unknown) => {
    if (value && typeof value === "object") {
      Object.values(value).forEach(freeze);
      Object.freeze(value);
    }
  };
  freeze(copy);
  return copy;
}

export function keepConsoleEnabled(
  channelKey: ChannelKey,
  config: Record<string, unknown>,
): Record<string, unknown> {
  if (channelKey !== "console") return config;
  return { ...config, enabled: true };
}
