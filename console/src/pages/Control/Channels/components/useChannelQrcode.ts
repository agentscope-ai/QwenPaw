import { useCallback, useLayoutEffect, useRef, useState } from "react";
import { api } from "../../../../api";
import type { ChannelAuthProvenance } from "../../../../api/modules/channel";
import { useAgentStore } from "../../../../stores/agentStore";

export interface ChannelQrcodeCustody {
  /** Atomically transfer cancellation ownership to a validated save job. */
  take: () => boolean;
  /** Discard an authorization that has not been taken by a save job. */
  cancel: () => void;
}

export interface ChannelQrcodeConfig {
  /** Channel name used in the API path, e.g. "wechat" or "wecom" */
  channel: string;
  agentId: string;
  /** Status value that indicates successful authorization */
  successStatus: string;
  /** Key in `credentials` to check for a truthy value on success */
  successCredentialKey: string;
  /** Polling interval in milliseconds (default: 2000) */
  pollInterval?: number;
  /** Maximum total polling time in milliseconds (wall-clock). Default: Infinity */
  pollTimeout?: number;
  /** Maximum number of poll attempts (failsafe). Default: Infinity */
  maxPollCount?: number;
  /** Extra query parameters to pass to the QR code API (e.g. domain) */
  params?: Record<string, string>;
  /** Called when authorization succeeds with the credentials map */
  onSuccess: (
    credentials: Record<string, string>,
    provenance: ChannelAuthProvenance,
    custody: ChannelQrcodeCustody,
  ) => void;
  /** Called when QR code fetch fails, polling detects expiry, or backend reports failure */
  onError: (type: "fetch" | "expired" | "fail") => void;
}

export interface ChannelQrcodeState {
  qrcodeImg: string;
  loading: boolean;
  fetchQrcode: () => Promise<void>;
  stopPoll: () => void;
  reset: () => void;
}

/**
 * Generic hook for channel QR-code-based authorization.
 *
 * Handles: fetch QR code → display → poll status → auto-fill credentials.
 * Works for any channel registered in the backend `QRCODE_AUTH_HANDLERS`.
 */
export function useChannelQrcode(
  config: ChannelQrcodeConfig,
): ChannelQrcodeState {
  const {
    channel,
    agentId,
    successStatus,
    successCredentialKey,
    pollInterval = 2000,
    pollTimeout,
    maxPollCount,
    params,
    onSuccess,
    onError,
  } = config;
  const [qrcodeImg, setQrcodeImg] = useState("");
  const [loading, setLoading] = useState(false);
  const generation = useRef(0);
  const pollRef = useRef<ReturnType<typeof setTimeout>>();
  const flight = useRef<{
    controller: AbortController;
    agentId: string;
    channel: string;
    token?: string;
    custodyTaken: boolean;
  }>();

  const revoke = (channel: string, token: string, agentId: string) => {
    // Cancellation has its own request signal; the poll signal is already aborted.
    void api.cancelChannelQrcode(channel, token, { agentId }).catch(() => {
      console.warn("Unable to cancel QR authorization");
    });
  };

  const stopPoll = useCallback(() => {
    generation.current += 1;
    clearTimeout(pollRef.current);
    const previous = flight.current;
    flight.current = undefined;
    previous?.controller.abort();
    if (previous?.token && !previous.custodyTaken) {
      revoke(previous.channel, previous.token, previous.agentId);
    }
  }, []);

  const reset = useCallback(() => {
    stopPoll();
    setQrcodeImg("");
    setLoading(false);
  }, [stopPoll]);

  // A layout cleanup fences promises before a changed scope can paint, including ABA.
  const paramsKey = JSON.stringify(params ?? {});
  useLayoutEffect(() => {
    reset();
    return stopPoll;
  }, [agentId, channel, paramsKey, reset, stopPoll]);
  useLayoutEffect(
    () =>
      useAgentStore.subscribe((next, previous) => {
        if (next.selectedAgent !== previous.selectedAgent) reset();
      }),
    [reset],
  );

  const fetchQrcode = useCallback(async () => {
    reset();
    const currentGeneration = generation.current;
    const current = {
      controller: new AbortController(),
      agentId,
      channel,
      token: undefined as string | undefined,
      custodyTaken: false,
    };
    flight.current = current;
    const active = () =>
      generation.current === currentGeneration && flight.current === current;
    const scope = { agentId, signal: current.controller.signal };
    const capturedParams = params ? { ...params } : undefined;
    const fail = (reason: "fetch" | "expired" | "fail") => {
      if (!active()) return;
      reset();
      onError(reason);
    };
    setLoading(true);
    try {
      const data = await api.getChannelQrcode(channel, capturedParams, scope);
      if (!active()) {
        if (data.poll_token) revoke(channel, data.poll_token, agentId);
        return;
      }
      current.token = data.poll_token;
      if (!data.qrcode_img || !data.poll_token) {
        fail("fetch");
        return;
      }
      setQrcodeImg(data.qrcode_img);
      let pollCount = 0;
      const started = Date.now();
      const schedulePoll = () => {
        if (!active()) return;
        pollRef.current = setTimeout(async () => {
          if (!active()) return;
          if (
            (pollTimeout && Date.now() - started >= pollTimeout) ||
            (maxPollCount && pollCount >= maxPollCount)
          ) {
            fail("expired");
            return;
          }
          pollCount += 1;
          try {
            const result = await api.getChannelQrcodeStatus(
              channel,
              data.poll_token,
              capturedParams,
              scope,
            );
            if (!active()) return;
            if (
              result.status === successStatus &&
              result.credentials[successCredentialKey]
            ) {
              // Confirmation alone does not transfer cancellation ownership.
              // The consumer must synchronously take it when a valid job exists.
              setQrcodeImg("");
              onSuccess(
                { ...result.credentials },
                { agentId, channel, token: data.poll_token },
                {
                  take: () => {
                    if (current.custodyTaken) return true;
                    if (!active()) return false;
                    current.custodyTaken = true;
                    return true;
                  },
                  cancel: () => {
                    if (active() && !current.custodyTaken) reset();
                  },
                },
              );
              return;
            }
            if (result.status === "expired" || result.status === "fail") {
              fail(result.status);
              return;
            }
          } catch {
            if (!active()) return;
          }
          schedulePoll();
        }, pollInterval);
      };
      schedulePoll();
    } catch {
      fail("fetch");
    } finally {
      if (active()) setLoading(false);
    }
  }, [
    agentId,
    channel,
    successStatus,
    successCredentialKey,
    pollInterval,
    pollTimeout,
    maxPollCount,
    params,
    onSuccess,
    onError,
    reset,
  ]);

  return { qrcodeImg, loading, fetchQrcode, stopPoll, reset };
}
