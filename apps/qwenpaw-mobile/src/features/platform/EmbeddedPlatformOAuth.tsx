import { ChevronLeft, X } from "lucide-react-native";
import { useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  BackHandler,
  Modal,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { WebView, type WebViewNavigation } from "react-native-webview";

import { colors } from "../../theme/tokens";
import { PLATFORM_HOST } from "../../config/platform";
import { classifyEmbeddedOAuthNavigation } from "./platformOAuth";

interface OAuthRequest {
  authorizeUrl: string;
  id: number;
  redirectUri: string;
  resolve: (url: string | null) => void;
}

let nextRequestId = 1;
let activeRequest: OAuthRequest | null = null;
const listeners = new Set<() => void>();

export function openEmbeddedPlatformOAuthSession(
  authorizeUrl: string,
  redirectUri: string,
): Promise<string | null> {
  if (activeRequest) {
    return Promise.reject(new Error("已有 Platform 授权正在进行"));
  }
  return new Promise((resolve) => {
    activeRequest = {
      authorizeUrl,
      id: nextRequestId,
      redirectUri,
      resolve,
    };
    nextRequestId += 1;
    emitChange();
  });
}

export function EmbeddedPlatformOAuthHost() {
  const [request, setRequest] = useState<OAuthRequest | null>(activeRequest);
  const [canGoBack, setCanGoBack] = useState(false);
  const [loading, setLoading] = useState(true);
  const webView = useRef<WebView>(null);

  useEffect(() => {
    const listener = () => {
      setCanGoBack(false);
      setLoading(true);
      setRequest(activeRequest);
    };
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  }, []);

  useEffect(() => {
    if (!request) return;
    const subscription = BackHandler.addEventListener(
      "hardwareBackPress",
      () => {
        if (canGoBack) webView.current?.goBack();
        else finishRequest(request.id, null);
        return true;
      },
    );
    return () => subscription.remove();
  }, [canGoBack, request]);

  if (!request) return null;

  const finish = (url: string | null) => finishRequest(request.id, url);
  const allowNavigation = ({ url }: { url: string }) => {
    const action = classifyEmbeddedOAuthNavigation(url, request.redirectUri);
    if (action === "callback") {
      finish(url);
      return false;
    }
    return action === "allow";
  };
  const navigateBack = () => {
    if (canGoBack) webView.current?.goBack();
    else finish(null);
  };

  return (
    <Modal
      animationType="slide"
      onRequestClose={navigateBack}
      presentationStyle="fullScreen"
      statusBarTranslucent={false}
      visible
    >
      <SafeAreaView edges={["top", "bottom"]} style={styles.root}>
        <View style={styles.header}>
          <Pressable
            accessibilityLabel="返回"
            hitSlop={8}
            onPress={navigateBack}
            style={styles.action}
          >
            <ChevronLeft color={colors.ink} size={27} />
          </Pressable>
          <View style={styles.titleBlock}>
            <Text style={styles.title}>Platform 安全登录</Text>
            <Text style={styles.host}>{PLATFORM_HOST}</Text>
          </View>
          <Pressable
            accessibilityLabel="关闭登录"
            hitSlop={8}
            onPress={() => finish(null)}
            style={styles.action}
          >
            <X color={colors.ink} size={27} />
          </Pressable>
        </View>
        <View style={styles.progressTrack}>
          {loading ? <View style={styles.progress} /> : null}
        </View>
        <WebView
          ref={webView}
          allowsBackForwardNavigationGestures
          allowFileAccess={false}
          applicationNameForUserAgent="QwenPawMobile/1.0"
          domStorageEnabled
          javaScriptEnabled
          mixedContentMode="never"
          onLoadEnd={() => setLoading(false)}
          onLoadStart={() => setLoading(true)}
          onNavigationStateChange={(navigation: WebViewNavigation) => {
            setCanGoBack(navigation.canGoBack);
          }}
          onShouldStartLoadWithRequest={allowNavigation}
          originWhitelist={["https://*", "http://127.0.0.1:*"]}
          setSupportMultipleWindows={false}
          sharedCookiesEnabled
          source={{ uri: request.authorizeUrl }}
          thirdPartyCookiesEnabled
          style={styles.webView}
        />
        {loading ? (
          <View pointerEvents="none" style={styles.loadingBadge}>
            <ActivityIndicator color={colors.accent} size="small" />
          </View>
        ) : null}
      </SafeAreaView>
    </Modal>
  );
}

function finishRequest(id: number, url: string | null): void {
  if (!activeRequest || activeRequest.id !== id) return;
  const { resolve } = activeRequest;
  activeRequest = null;
  emitChange();
  resolve(url);
}

function emitChange(): void {
  for (const listener of listeners) listener();
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceStrong },
  header: {
    height: 64,
    flexDirection: "row",
    alignItems: "center",
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.hairline,
    backgroundColor: colors.surfaceStrong,
  },
  action: {
    width: 58,
    height: 58,
    alignItems: "center",
    justifyContent: "center",
  },
  titleBlock: { flex: 1, alignItems: "center", gap: 2 },
  title: { color: colors.ink, fontSize: 17, fontWeight: "600" },
  host: { color: colors.muted, fontSize: 11 },
  progressTrack: { height: 3, backgroundColor: colors.surfaceSoft },
  progress: { width: "38%", height: 3, backgroundColor: colors.accent },
  webView: { flex: 1, backgroundColor: colors.surfaceStrong },
  loadingBadge: {
    position: "absolute",
    top: 82,
    right: 16,
    width: 34,
    height: 34,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 17,
    backgroundColor: colors.surfaceStrong,
  },
});
