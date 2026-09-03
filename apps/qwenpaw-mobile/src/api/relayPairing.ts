import * as Crypto from "expo-crypto";

import { PLATFORM_BASE_URL, platformProofRequest } from "./platform";
import type { RelayPairingPayload } from "./pairing";
import { createRelayProof, relayPublicJwk } from "./relayIdentityModel";
import {
  loadOrCreateRelayDeviceKey,
  saveRelayBinding,
  type RelayBinding,
} from "../storage/relayIdentity";

interface PairingExchangeResponse {
  credential_generation: number;
  device_credential: string;
  device_id: string;
  dpop_nonce: string;
  node_id: string;
  node_public_key_thumbprint: string;
  qwenpaw_id: string;
}

const EXCHANGE_PATH = "/api/v1/qwenpaw-relay/pairing-tickets/exchange";

export async function exchangeRelayPairing(
  pairing: RelayPairingPayload,
  deviceName: string,
): Promise<RelayBinding> {
  if (pairing.issuer !== PLATFORM_BASE_URL) {
    throw new Error("Remote pairing issuer is not trusted.");
  }
  const key = await loadOrCreateRelayDeviceKey();
  const response = await platformProofRequest<PairingExchangeResponse>(
    EXCHANGE_PATH,
    (accessToken) => ({
      method: "POST",
      headers: {
        DPoP: createRelayProof({
          accessToken,
          key,
          method: "POST",
          nonce: pairing.dpopNonce,
          proofId: Crypto.randomUUID(),
          target: `${PLATFORM_BASE_URL}${EXCHANGE_PATH}`,
        }),
      },
      body: JSON.stringify({
        pairing_ticket: pairing.pairingTicket,
        device_name: deviceName,
        public_key_jwk: relayPublicJwk(key),
        protocol_version: 1,
      }),
    }),
  );
  if (
    response.node_id !== pairing.nodeId ||
    response.qwenpaw_id !== pairing.qwenPawId ||
    response.node_public_key_thumbprint !== pairing.nodePublicKeyThumbprint
  ) {
    throw new Error("Platform returned a different QwenPaw identity.");
  }
  const binding: RelayBinding = {
    credentialGeneration: response.credential_generation,
    deviceCredential: response.device_credential,
    deviceId: response.device_id,
    dpopNonce: response.dpop_nonce,
    nodeId: response.node_id,
    nodePublicKeyThumbprint: response.node_public_key_thumbprint,
    qwenPawId: response.qwenpaw_id,
  };
  await saveRelayBinding(binding);
  return binding;
}
