import * as Crypto from "expo-crypto";
import * as SecureStore from "expo-secure-store";

import {
  base64UrlDecode,
  base64UrlEncode,
  relayDeviceKeyFromSecret,
  type RelayDeviceKey,
} from "../api/relayIdentityModel";

const DEVICE_KEY = "qwenpaw.mobile.relay-device-key.v1";
const BINDING_PREFIX = "qwenpaw.mobile.relay-binding.v1";

export interface RelayBinding {
  credentialGeneration: number;
  deviceCredential: string;
  deviceId: string;
  dpopNonce: string;
  nodeId: string;
  nodePublicKeyThumbprint: string;
  qwenPawId: string;
}

export async function loadOrCreateRelayDeviceKey(): Promise<RelayDeviceKey> {
  const stored = await SecureStore.getItemAsync(DEVICE_KEY);
  if (stored) return relayDeviceKeyFromSecret(base64UrlDecode(stored));
  const secret = await Crypto.getRandomBytesAsync(32);
  await SecureStore.setItemAsync(DEVICE_KEY, base64UrlEncode(secret), {
    keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
  });
  return relayDeviceKeyFromSecret(secret);
}

export async function saveRelayBinding(binding: RelayBinding): Promise<void> {
  await SecureStore.setItemAsync(
    bindingKey(binding.nodeId),
    JSON.stringify(binding),
    { keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY },
  );
}

export async function loadRelayBinding(
  nodeId: string,
): Promise<RelayBinding | null> {
  const stored = await SecureStore.getItemAsync(bindingKey(nodeId));
  if (!stored) return null;
  try {
    const value = JSON.parse(stored) as RelayBinding;
    return value.nodeId === nodeId && value.deviceCredential ? value : null;
  } catch {
    await SecureStore.deleteItemAsync(bindingKey(nodeId));
    return null;
  }
}

function bindingKey(nodeId: string): string {
  return `${BINDING_PREFIX}.${nodeId}`;
}
