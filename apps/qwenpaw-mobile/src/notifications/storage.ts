import AsyncStorage from "@react-native-async-storage/async-storage";
import {
  DEFAULT_NOTIFICATION_PREFERENCES,
  parseNotificationPreferences,
  type NotificationPreferences,
} from "@qwenpaw/api-contract";
import * as Crypto from "expo-crypto";
import * as SecureStore from "expo-secure-store";

import type { Connection } from "../api/types";
import { connectionKey } from "../storage/connection";

const INSTALLATION_ID_KEY = "qwenpaw.mobile.push.installation.v1";
const PREFERENCES_PREFIX = "qwenpaw.mobile.push.preferences.v1";

export async function getInstallationId(): Promise<string> {
  const stored = await SecureStore.getItemAsync(INSTALLATION_ID_KEY);
  if (stored) return stored;
  const created = Crypto.randomUUID();
  await SecureStore.setItemAsync(INSTALLATION_ID_KEY, created, {
    keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
  });
  return created;
}

export async function workspaceKey(connection: Connection): Promise<string> {
  return Crypto.digestStringAsync(
    Crypto.CryptoDigestAlgorithm.SHA256,
    connectionKey(connection),
  );
}

function preferencesKey(connection: Connection): string {
  return `${PREFERENCES_PREFIX}:${connectionKey(connection)}:${
    connection.agentId
  }`;
}

export async function loadNotificationPreferences(
  connection: Connection,
): Promise<NotificationPreferences> {
  const stored = await AsyncStorage.getItem(preferencesKey(connection));
  if (!stored) {
    return { ...DEFAULT_NOTIFICATION_PREFERENCES, enabled: false };
  }
  try {
    return (
      parseNotificationPreferences(JSON.parse(stored)) ?? {
        ...DEFAULT_NOTIFICATION_PREFERENCES,
        enabled: false,
      }
    );
  } catch {
    return { ...DEFAULT_NOTIFICATION_PREFERENCES, enabled: false };
  }
}

export async function saveNotificationPreferences(
  connection: Connection,
  preferences: NotificationPreferences,
): Promise<void> {
  await AsyncStorage.setItem(
    preferencesKey(connection),
    JSON.stringify(preferences),
  );
}
