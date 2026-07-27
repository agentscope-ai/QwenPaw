import { isReplayTruncatedPayload } from "./utils";

export function sdkHeartbeatPayload() {
  return {
    object: "message",
    type: "heartbeat",
  };
}

export function filterReplayPayload(
  payload: Record<string, unknown>,
  streamTruncated: boolean,
): {
  payload: Record<string, unknown>;
  streamTruncated: boolean;
} {
  if (isReplayTruncatedPayload(payload)) {
    return {
      payload: sdkHeartbeatPayload(),
      streamTruncated: true,
    };
  }

  const completesResponse =
    payload.object === "response" && payload.status === "completed";
  if (streamTruncated && !completesResponse) {
    if (payload.type !== "rate_limited" && !payload.error) {
      return {
        payload: sdkHeartbeatPayload(),
        streamTruncated: true,
      };
    }
    return { payload, streamTruncated: false };
  }

  return {
    payload,
    streamTruncated: completesResponse ? false : streamTruncated,
  };
}
