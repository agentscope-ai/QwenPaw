import { router, Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { useEffect } from "react";
import { GestureHandlerRootView } from "react-native-gesture-handler";

import { MobileAlertHost } from "../components/MobileAlert";
import { MetroConnectionGuard } from "../dev/MetroConnectionGuard";
import { EmbeddedPlatformOAuthHost } from "../features/platform/EmbeddedPlatformOAuth";
import { openNotificationTarget } from "../notifications/navigation";
import { startNotificationNavigation } from "../notifications/runtime";
import { syncPushSubscription } from "../notifications/service";
import { useAppStore } from "../store/app";
import { ThemeProvider, useAppTheme } from "../theme/ThemeProvider";
import { colors } from "../theme/tokens";

export default function RootLayout() {
  return (
    <ThemeProvider>
      <AppNavigator />
    </ThemeProvider>
  );
}

function AppNavigator() {
  const bootstrap = useAppStore((state) => state.bootstrap);
  const status = useAppStore((state) => state.status);
  const connection = useAppStore((state) => state.connection);
  const { resolvedTheme } = useAppTheme();

  useEffect(() => {
    void bootstrap();
  }, [bootstrap]);

  useEffect(() => {
    if (status === "disconnected") router.replace("/");
  }, [status]);

  useEffect(() => {
    if (status !== "ready") return;
    let dispose: (() => void) | undefined;
    void startNotificationNavigation(openNotificationTarget).then((next) => {
      dispose = next;
    });
    return () => dispose?.();
  }, [status]);

  useEffect(() => {
    if (status !== "ready" || !connection) return;
    void syncPushSubscription(connection).catch(() => undefined);
  }, [connection, status]);

  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <StatusBar style={resolvedTheme === "dark" ? "light" : "dark"} />
      <Stack
        screenOptions={{
          headerShown: false,
          contentStyle: { backgroundColor: colors.canvas },
          animation: "fade",
        }}
      />
      <EmbeddedPlatformOAuthHost />
      <MobileAlertHost />
      {__DEV__ ? <MetroConnectionGuard /> : null}
    </GestureHandlerRootView>
  );
}
