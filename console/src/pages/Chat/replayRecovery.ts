export function shouldInspectReplayPayload(
  raw: string,
  streamTruncated: boolean,
): boolean {
  return (
    streamTruncated ||
    raw.includes('"turn_usage"') ||
    raw.includes('"replay_truncated"')
  );
}

export function shouldForwardReplayPayload(
  payload: Record<string, unknown>,
  streamTruncated: boolean,
): {
  forward: boolean;
  streamTruncated: boolean;
} {
  if (payload.type === "replay_truncated") {
    return {
      forward: false,
      streamTruncated: true,
    };
  }

  const completesResponse =
    payload.object === "response" && payload.status === "completed";
  if (streamTruncated && !completesResponse) {
    const terminalError =
      payload.type === "rate_limited" || Boolean(payload.error);
    return {
      forward: terminalError,
      streamTruncated: !terminalError,
    };
  }

  return {
    forward: payload.type !== "turn_usage",
    streamTruncated: completesResponse ? false : streamTruncated,
  };
}

export function sdkRateLimitErrorPayload(
  payload: Record<string, unknown>,
  fallbackMessage: string,
) {
  const error = payload.error;
  return {
    type: "error",
    code: "rate_limited",
    message:
      typeof error === "string" && error.trim() ? error : fallbackMessage,
  };
}
