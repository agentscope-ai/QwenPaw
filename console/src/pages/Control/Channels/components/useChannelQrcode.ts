import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../../../api";

export interface ChannelQrcodeConfig {
  /** Channel name used in the API path, e.g. "wechat" or "wecom" */
  channel: string;
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
  onSuccess: (credentials: Record<string, string>) => void;
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
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const confirmedRef = useRef(false);
  const pollCountRef = useRef(0);
  const startTimeRef = useRef(0);

  const stopPoll = useCallback(() => {
    if (pollRef.current) {
      clearTimeout(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const reset = useCallback(() => {
    stopPoll();
    setQrcodeImg("");
    confirmedRef.current = false;
    pollCountRef.current = 0;
    startTimeRef.current = 0;
  }, [stopPoll]);

  const fetchQrcode = useCallback(async () => {
    reset();
    setLoading(true);
    try {
      const data = await api.getChannelQrcode(channel, params);
      if (!data.qrcode_img) {
        onError("fetch");
        return;
      }
      setQrcodeImg(data.qrcode_img);

      pollCountRef.current = 0;
      startTimeRef.current = Date.now();

      // Use recursive setTimeout to avoid overlapping requests
      const schedulePoll = () => {
        pollRef.current = setTimeout(async () => {
          // Check wall-clock timeout first
          if (pollTimeout && Date.now() - startTimeRef.current >= pollTimeout) {
            setQrcodeImg("");
            onError("expired");
            return;
          }
          // Check max poll count (failsafe)
          if (maxPollCount && pollCountRef.current >= maxPollCount) {
            setQrcodeImg("");
            onError("expired");
            return;
          }
          pollCountRef.current++;

          try {
            const result = await api.getChannelQrcodeStatus(
              channel,
              data.poll_token,
              params,
            );
            if (
              result.status === successStatus &&
              result.credentials[successCredentialKey]
            ) {
              if (confirmedRef.current) return;
              confirmedRef.current = true;
              setQrcodeImg("");
              onSuccess(result.credentials);
              return;
            } else if (result.status === "expired") {
              setQrcodeImg("");
              onError("expired");
              return;
            } else if (result.status === "fail") {
              setQrcodeImg("");
              onError("fail");
              return;
            }
          } catch {
            // ignore individual poll errors
          }
          // Schedule next poll only after current one completes
          schedulePoll();
        }, pollInterval);
      };
      schedulePoll();
    } catch {
      onError("fetch");
    } finally {
      setLoading(false);
    }
  }, [
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
    stopPoll,
  ]);

  // Cleanup on unmount
  useEffect(() => stopPoll, [stopPoll]);

  return { qrcodeImg, loading, fetchQrcode, stopPoll, reset };
}
