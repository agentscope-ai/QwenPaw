import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../../../api";

interface ChannelQrcodeConfig {
  /** Channel name used in the API path, e.g. "weixin" or "wecom" */
  channel: string;
  /** Status value that indicates successful authorization */
  successStatus: string;
  /** Key in `credentials` to check for a truthy value on success */
  successCredentialKey: string;
  /** Polling interval in milliseconds (default: 2000) */
  pollInterval?: number;
  /** Called when authorization succeeds with the credentials map */
  onSuccess: (credentials: Record<string, string>) => void;
  /** Called when the QR code expires (optional) */
  onExpired?: () => void;
  /** Called when QR code fetch or polling fails */
  onError: (type: "fetch" | "expired") => void;
}

interface ChannelQrcodeState {
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
 * Works for any channel registered in the backend `QRCODE_PROVIDERS`.
 */
export function useChannelQrcode(
  config: ChannelQrcodeConfig,
): ChannelQrcodeState {
  const {
    channel,
    successStatus,
    successCredentialKey,
    pollInterval = 2000,
    onSuccess,
    onExpired,
    onError,
  } = config;

  const [qrcodeImg, setQrcodeImg] = useState("");
  const [loading, setLoading] = useState(false);
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const confirmedRef = useRef(false);

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
  }, [stopPoll]);

  const fetchQrcode = useCallback(async () => {
    reset();
    setLoading(true);
    try {
      const data = await api.getChannelQrcode(channel);
      if (!data.qrcode_img) {
        onError("fetch");
        return;
      }
      setQrcodeImg(data.qrcode_img);

      // Use recursive setTimeout to avoid overlapping requests
      const schedulePoll = () => {
        pollRef.current = setTimeout(async () => {
          try {
            const result = await api.getChannelQrcodeStatus(
              channel,
              data.poll_token,
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
              onExpired?.();
              onError("expired");
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
    onSuccess,
    onExpired,
    onError,
    reset,
    stopPoll,
  ]);

  // Cleanup on unmount
  useEffect(() => stopPoll, [stopPoll]);

  return { qrcodeImg, loading, fetchQrcode, stopPoll, reset };
}
