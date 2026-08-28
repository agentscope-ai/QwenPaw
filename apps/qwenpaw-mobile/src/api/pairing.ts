export interface PairingPayload {
  version: 1;
  baseUrl: string;
  ticket: string;
}

export function normalizeBaseUrl(value: string): string {
  const trimmed = value.trim().replace(/\/+$/, "");
  const parsed = new URL(trimmed);
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new Error("QwenPaw address must use HTTP or HTTPS.");
  }
  if (parsed.username || parsed.password || parsed.search || parsed.hash) {
    throw new Error("QwenPaw address must not contain credentials or queries.");
  }
  return parsed.toString().replace(/\/$/, "");
}

export function parsePairingUri(value: string): PairingPayload {
  const uri = new URL(value);
  if (uri.protocol !== "qwenpaw:" || uri.hostname !== "pair") {
    throw new Error("This is not a QwenPaw pairing code.");
  }
  const version = Number(uri.searchParams.get("v"));
  const baseUrl = uri.searchParams.get("base_url") ?? "";
  const ticket = uri.searchParams.get("ticket") ?? "";
  if (version !== 1 || ticket.length < 32) {
    throw new Error("This QwenPaw pairing code is invalid or outdated.");
  }
  return { version: 1, baseUrl: normalizeBaseUrl(baseUrl), ticket };
}
