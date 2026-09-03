export interface DirectPairingPayload {
  kind: "direct";
  version: 1;
  baseUrl: string;
  ticket: string;
}

export interface RelayPairingPayload {
  kind: "relay";
  version: 2;
  issuer: string;
  nodeId: string;
  qwenPawId: string;
  pairingTicket: string;
  nodePublicKeyThumbprint: string;
  dpopNonce: string;
  protocolVersion: 1;
}

export type PairingPayload = DirectPairingPayload | RelayPairingPayload;

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
  if (value.trimStart().startsWith("{")) return parseRelayPairingJson(value);
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
  return {
    kind: "direct",
    version: 1,
    baseUrl: normalizeBaseUrl(baseUrl),
    ticket,
  };
}

function parseRelayPairingJson(value: string): RelayPairingPayload {
  let payload: Record<string, unknown>;
  try {
    payload = JSON.parse(value) as Record<string, unknown>;
  } catch {
    throw new Error("This QwenPaw pairing code is invalid.");
  }
  const issuer = normalizeBaseUrl(String(payload.issuer ?? ""));
  const pairingTicket = String(payload.pairing_ticket ?? "");
  const nodeId = String(payload.node_id ?? "");
  const qwenPawId = String(payload.qwenpaw_id ?? "");
  const thumbprint = String(payload.node_public_key_thumbprint ?? "");
  const dpopNonce = String(payload.dpop_nonce ?? "");
  if (
    payload.type !== "qwenpaw.relay.pairing" ||
    payload.v !== 2 ||
    payload.protocol_version !== 1 ||
    issuer !== "https://platform.agentscope.io" ||
    !isUuid(nodeId) ||
    !isUuid(qwenPawId) ||
    !pairingTicket.startsWith("qprt_v1_") ||
    pairingTicket.length < 40 ||
    thumbprint.length < 32 ||
    dpopNonce.length < 24
  ) {
    throw new Error("This QwenPaw remote pairing code is invalid or expired.");
  }
  return {
    kind: "relay",
    version: 2,
    issuer,
    nodeId,
    qwenPawId,
    pairingTicket,
    nodePublicKeyThumbprint: thumbprint,
    dpopNonce,
    protocolVersion: 1,
  };
}

function isUuid(value: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(
    value,
  );
}
