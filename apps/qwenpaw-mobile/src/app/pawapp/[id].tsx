import { MobileAlert } from "@/components/MobileAlert";
import { router, useLocalSearchParams } from "expo-router";
import { ChevronLeft, MoreHorizontal } from "lucide-react-native";
import { useMemo, useState } from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { WebView } from "react-native-webview";

import { useAppStore } from "../../store/app";
import { colors, spacing } from "../../theme/tokens";

export default function PawAppScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const connection = useAppStore((state) => state.connection);
  const [loading, setLoading] = useState(true);
  const source = useMemo(() => {
    if (!connection || !id) return null;
    return {
      uri: `${connection.baseUrl}/apps/${encodeURIComponent(id)}`,
      headers: {
        ...(connection.token ? { Authorization: `Bearer ${connection.token}` } : {}),
        "X-Agent-Id": connection.agentId || "default",
      },
    };
  }, [connection, id]);
  const authentication = useMemo(
    () => connection ? authenticationBridge(
      connection.baseUrl,
      connection.token,
      connection.agentId,
    ) : "true;",
    [connection],
  );

  if (!connection || !source) {
    return <SafeAreaView style={styles.root}><Text style={styles.error}>当前没有可用连接。</Text></SafeAreaView>;
  }

  return (
    <SafeAreaView edges={["top"]} style={styles.root}>
      <View style={styles.header}>
        <Pressable accessibilityLabel="返回 App Center" onPress={() => router.back()} style={styles.action}>
          <ChevronLeft color={colors.ink} size={25} />
        </Pressable>
        <View style={styles.titleBlock}>
          <Text numberOfLines={1} style={styles.title}>{id}</Text>
          <Text style={styles.subtitle}>QwenPaw App</Text>
        </View>
        <Pressable
          accessibilityLabel="App 信息"
          onPress={() => MobileAlert.alert(id, "此页面由当前 QwenPaw 安装的扩展提供。")}
          style={styles.action}
        >
          <MoreHorizontal color={colors.ink} size={23} />
        </Pressable>
      </View>
      <WebView
        allowsBackForwardNavigationGestures
        applicationNameForUserAgent="QwenPawMobile/1.0"
        injectedJavaScriptBeforeContentLoaded={authentication}
        javaScriptEnabled
        onError={(event) => MobileAlert.alert("App 加载失败", event.nativeEvent.description)}
        onLoadEnd={() => setLoading(false)}
        sharedCookiesEnabled
        source={source}
        thirdPartyCookiesEnabled
        style={styles.webView}
      />
      {loading ? (
        <View pointerEvents="none" style={styles.loading}>
          <ActivityIndicator color={colors.accent} />
          <Text style={styles.loadingText}>正在打开 App…</Text>
        </View>
      ) : null}
    </SafeAreaView>
  );
}

function authenticationBridge(
  baseUrl: string,
  token: string,
  agentId: string,
): string {
  const origin = new URL(baseUrl).origin;
  return `
    (() => {
      const allowedOrigin = ${JSON.stringify(origin)};
      const token = ${JSON.stringify(token)};
      const agentId = ${JSON.stringify(agentId || "default")};
      const sameOrigin = (input) => {
        try {
          const raw = typeof input === "string" ? input : input.url;
          return new URL(raw, window.location.href).origin === allowedOrigin;
        } catch (_) { return false; }
      };
      const originalFetch = window.fetch.bind(window);
      window.fetch = (input, init = {}) => {
        if (!sameOrigin(input)) return originalFetch(input, init);
        const headers = new Headers(init.headers || {});
        if (token) headers.set("Authorization", "Bearer " + token);
        headers.set("X-Agent-Id", agentId);
        return originalFetch(input, { ...init, headers, credentials: "include" });
      };
      const originalOpen = XMLHttpRequest.prototype.open;
      const originalSend = XMLHttpRequest.prototype.send;
      XMLHttpRequest.prototype.open = function(method, url) {
        this.__qwenpawSameOrigin = sameOrigin(url);
        return originalOpen.apply(this, arguments);
      };
      XMLHttpRequest.prototype.send = function() {
        if (this.__qwenpawSameOrigin) {
          if (token) this.setRequestHeader("Authorization", "Bearer " + token);
          this.setRequestHeader("X-Agent-Id", agentId);
        }
        return originalSend.apply(this, arguments);
      };
    })();
    true;
  `;
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.groupedBackground },
  header: {
    height: 56,
    flexDirection: "row",
    alignItems: "center",
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.hairline,
    backgroundColor: colors.tabBar,
  },
  action: { width: 52, height: 52, alignItems: "center", justifyContent: "center" },
  titleBlock: { flex: 1, alignItems: "center", gap: 1 },
  title: { color: colors.ink, fontSize: 16, fontWeight: "600" },
  subtitle: { color: colors.muted, fontSize: 10 },
  webView: { flex: 1, backgroundColor: colors.groupedBackground },
  loading: {
    position: "absolute",
    right: 0,
    bottom: 0,
    left: 0,
    top: 56,
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.sm,
    backgroundColor: colors.groupedBackground,
  },
  loadingText: { color: colors.muted, fontSize: 13 },
  error: { color: colors.ink, padding: spacing.lg, fontSize: 16 },
});
