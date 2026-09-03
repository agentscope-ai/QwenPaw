import * as Crypto from "expo-crypto";
import { PLATFORM_BASE_URL, platformProofRequest } from "./platform";
import { createRelayProof } from "./relayIdentityModel";
import { connectRelayWithRetry } from "./relayConnectionModel";
import { RelayMultiplexer, type RelaySocket } from "./relayMultiplexer";
import {
  loadOrCreateRelayDeviceKey,
  loadRelayBinding,
  saveRelayBinding,
  type RelayBinding,
} from "../storage/relayIdentity";

const CONNECT_PATH = "/api/v1/qwenpaw-relay/device/connect-tickets";
const CONNECT_TIMEOUT_MS = 15_000;

interface ConnectTicketResponse {
  connect_ticket: string;
  dpop_nonce: string;
  expires_in: number;
  next_credential_dpop_nonce: string;
  role: string;
  websocket_url: string;
}

export interface RelayConnectTicket {
  dpopNonce: string;
  token: string;
  websocketUrl: string;
}

export async function requestRelayConnectTicket(
  nodeId: string,
): Promise<RelayConnectTicket> {
  const binding = await loadRelayBinding(nodeId);
  if (!binding) throw new Error("这只 QwenPaw 尚未完成安全配对");
  const key = await loadOrCreateRelayDeviceKey();
  const target = `${PLATFORM_BASE_URL}${CONNECT_PATH}`;
  const ticket = await platformProofRequest<ConnectTicketResponse>(
    CONNECT_PATH,
    () => ({
      method: "POST",
      headers: {
        "Relay-Device-Credential": binding.deviceCredential,
        DPoP: createRelayProof({
          accessToken: binding.deviceCredential,
          key,
          method: "POST",
          nonce: binding.dpopNonce,
          proofId: Crypto.randomUUID(),
          target,
        }),
      },
      body: "{}",
    }),
  );
  if (!ticket || ticket.role !== "mobile") {
    throw new Error("Platform 返回了无效的安全中转票据");
  }
  validateRelayWebSocketUrl(ticket.websocket_url);
  await saveRelayBinding({
    ...binding,
    dpopNonce: ticket.next_credential_dpop_nonce,
  });
  return {
    dpopNonce: ticket.dpop_nonce,
    token: ticket.connect_ticket,
    websocketUrl: ticket.websocket_url,
  };
}

export async function connectRelayMobile(
  binding: RelayBinding,
  onClose?: () => void,
): Promise<RelayMultiplexer> {
  const key = await loadOrCreateRelayDeviceKey();
  return connectRelayWithRetry(async () => {
    const ticket = await requestRelayConnectTicket(binding.nodeId);
    const proof = createRelayProof({
      accessToken: ticket.token,
      key,
      method: "GET",
      nonce: ticket.dpopNonce,
      proofId: Crypto.randomUUID(),
      target: ticket.websocketUrl,
    });
    const socket = createRelaySocket(ticket, proof);
    try {
      await waitForOpen(socket);
      return new RelayMultiplexer(socket, undefined, onClose);
    } catch (error) {
      socket.close();
      throw error;
    }
  });
}

function createRelaySocket(
  ticket: RelayConnectTicket,
  proof: string,
): RelaySocket {
  const Socket = WebSocket as unknown as new (
    url: string,
    protocols: string[] | null,
    options: { headers: Record<string, string> },
  ) => RelaySocket;
  return new Socket(ticket.websocketUrl, null, {
    headers: {
      Authorization: `RelayTicket ${ticket.token}`,
      DPoP: proof,
    },
  });
}

function waitForOpen(socket: RelaySocket): Promise<void> {
  return new Promise((resolve, reject) => {
    let settled = false;
    const finish = (callback: () => void): void => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      callback();
    };
    const timeout = setTimeout(
      () => finish(() => reject(new Error("安全中转连接超时"))),
      CONNECT_TIMEOUT_MS,
    );
    socket.addEventListener("open", () => finish(resolve));
    socket.addEventListener("error", () =>
      finish(() => reject(new Error("安全中转连接失败"))),
    );
  });
}

function validateRelayWebSocketUrl(value: string): void {
  const url = new URL(value);
  if (
    url.protocol !== "wss:" ||
    !url.hostname ||
    url.username ||
    url.password ||
    url.search ||
    url.hash
  ) {
    throw new Error("Platform 返回了无效的安全中转地址");
  }
}
