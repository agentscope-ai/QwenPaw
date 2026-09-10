import { requireNativeModule } from "expo-modules-core";
import { Platform } from "react-native";

interface OAuthLoopbackNativeModule {
  startAsync(): Promise<number>;
  stopAsync(): Promise<void>;
  waitForCallbackAsync?(): Promise<string | null>;
}

const nativeModule =
  Platform.OS === "ios" || Platform.OS === "android"
    ? requireNativeModule<OAuthLoopbackNativeModule>("QwenPawOAuthLoopback")
    : null;

export async function startOAuthLoopback(): Promise<number> {
  if (!nativeModule) {
    throw new Error("当前设备暂不支持 Platform OAuth 回跳");
  }
  return nativeModule.startAsync();
}

export async function stopOAuthLoopback(): Promise<void> {
  await nativeModule?.stopAsync();
}

export async function waitForOAuthCallback(): Promise<string | null> {
  if (Platform.OS !== "android" || !nativeModule?.waitForCallbackAsync) {
    throw new Error("当前设备不支持 Android Platform OAuth 回调监听");
  }
  return nativeModule.waitForCallbackAsync();
}
