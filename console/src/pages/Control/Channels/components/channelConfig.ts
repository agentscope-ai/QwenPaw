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

const SIP_LIVEKIT_FIELDS = [
  "livekit_url",
  "livekit_api_key",
  "livekit_api_secret",
  "livekit_sip_trunk_id",
  "livekit_room_name",
  "livekit_output_sample_rate",
] as const;

export function keepConsoleEnabled(
  channelKey: ChannelKey,
  config: Record<string, unknown>,
): Record<string, unknown> {
  if (channelKey !== "console") return config;
  return { ...config, enabled: true };
}

export function normalizeChannelSubmitValues(
  channelKey: ChannelKey | null,
  values: Record<string, unknown>,
): Record<string, unknown> {
  if (channelKey !== "sip" || values.sip_mode === "livekit") return values;

  const normalized = { ...values };
  for (const field of SIP_LIVEKIT_FIELDS) delete normalized[field];
  return normalized;
}
