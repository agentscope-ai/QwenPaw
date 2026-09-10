import { router } from "expo-router";
import { useEffect } from "react";
import { ActivityIndicator, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { colors, spacing } from "../theme/tokens";

export default function PlatformAuthCallbackScreen() {
  useEffect(() => {
    const timer = setTimeout(() => {
      if (router.canGoBack()) {
        router.back();
        return;
      }
      router.replace({ pathname: "/", params: { platformLogin: "1" } });
    }, 0);
    return () => clearTimeout(timer);
  }, []);

  return (
    <SafeAreaView style={styles.root}>
      <View style={styles.content}>
        <ActivityIndicator color={colors.accent} size="large" />
        <Text style={styles.title}>正在完成 Platform 登录</Text>
        <Text style={styles.copy}>安全校验完成后会自动继续。</Text>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    backgroundColor: colors.canvas,
  },
  content: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.sm,
    padding: spacing.xl,
  },
  title: {
    color: colors.ink,
    fontSize: 20,
    fontWeight: "700",
  },
  copy: {
    color: colors.muted,
    fontSize: 14,
  },
});
