// Compatibility exports; cross-feature code imports from @/utils/channel.
export {
  CHANNEL_LABELS,
  getChannelLabel,
  type ChannelKey,
} from "../../../../utils/channel";

const LOOPBACK_HOSTNAMES = new Set(["localhost"]);
const IPV4_LOOPBACK_RE = /^127(\.\d{1,3}){3}$/;
const IPV6_LOOPBACK_RE = /^(?:0*:)+0*1$/;

/**
 * Whether a listen address only accepts connections from the local machine.
 *
 * Mirrors `is_loopback_host` in `src/qwenpaw/utils/http.py`, which stays
 * authoritative; this copy only drives form validation. Unspecified
 * addresses such as `0.0.0.0`, `::` and the empty string bind every
 * interface and are therefore not loopback.
 */
export function isLoopbackHost(host: string): boolean {
  const candidate = (host ?? "")
    .trim()
    .replace(/^\[|\]$/g, "")
    .toLowerCase()
    .replace(/\.$/, "");
  if (!candidate) return false;
  if (LOOPBACK_HOSTNAMES.has(candidate)) return true;
  if (IPV4_LOOPBACK_RE.test(candidate)) return true;
  return IPV6_LOOPBACK_RE.test(candidate);
}
