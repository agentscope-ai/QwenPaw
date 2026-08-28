import * as SecureStore from "expo-secure-store";

import type { PlatformRefreshMode } from "../api/platformSessionModel";

export interface PlatformSession {
  accessToken: string;
  refreshToken: string;
  expiresAt: number;
  refreshMode?: PlatformRefreshMode;
  username?: string;
}

const PLATFORM_SESSION_KEY = "qwenpaw.mobile.platform-session.v1";

export async function loadPlatformSession(): Promise<PlatformSession | null> {
  const stored = await SecureStore.getItemAsync(PLATFORM_SESSION_KEY);
  if (!stored) return null;
  try {
    const session = JSON.parse(stored) as PlatformSession;
    if (!session.accessToken || !session.refreshToken) return null;
    return session;
  } catch {
    await clearPlatformSession();
    return null;
  }
}

export async function savePlatformSession(
  session: PlatformSession,
): Promise<void> {
  await SecureStore.setItemAsync(
    PLATFORM_SESSION_KEY,
    JSON.stringify(session),
    { keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY },
  );
}

export async function clearPlatformSession(): Promise<void> {
  await SecureStore.deleteItemAsync(PLATFORM_SESSION_KEY);
}
